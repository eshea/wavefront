"""
Marching-waves scalar field for WAVEFRONT (method=march).

The "marching waves" idea: a SEED emits a wavefront; the wave's local SPEED is set
by the image, and the plotted lines are equal-arrival-time fronts. Bright regions
are fast (fronts race through -> sparse lines); dark regions and edges are slow
(fronts crawl -> lines bunch up -> the "visor goes black" density effect). This is
a weighted distance / eikonal idea.

Why 4-connectivity (the key design choice): a TRUE isotropic fast-marching eikonal
(scikit-fmm) was tried here before and abandoned — its round fronts globally
rerouted into horizontal bands under speed modulation, losing the VEX-LINE diamond
look. We instead accumulate cost on a 4-CONNECTED grid (skimage.graph.MCP), whose
geodesic distance is L1 (Manhattan) = concentric DIAMONDS. That topology is
constrained: tone/edges bend and bunch the diamonds locally but can't reroute them
into bands. With a flat cost the field is exactly |dx|+|dy| (pure diamonds);
MARCH_BASE controls how strongly the image is allowed to bend them.

MCP works in COST (~1/speed) accumulated as arrival time, so SLOW = HIGH cost.
The cost mapping is RECIPROCAL — the confirmed CONTOUR-V model (the STUDIO
screenshot's own subtitle is "Fast marching contour field"; see
docs/contour-v-core-source.md). Speed is brightness clamped at a floor:

    speed = clip(gray, MARCH_FLOOR, 1)                  # bright = fast
    cost  = MARCH_BASE + lum_mix*(1/speed - 1) + MARCH_EDGE*edge
    T     = MCP(cost, 4-connected).find_costs(seed)     # arrival time (the field)

Why reciprocal (not the old linear MARCH_TONE*dark): isoline spacing = level
spacing / cost, so 1/speed gives a gentle halftone through whites and midtones
(white cost ~1, mid ~2) while deep darks blow up to 1/MARCH_FLOOR and saturate
to solid ink — eyes/visors go black exactly like the artist outputs. A linear
ramp can't do that: by the time darks saturate, mids are nearly as dense and
whites are starved. MARCH_FLOOR is THE tone lever now (lower = darker darks).

build_march_field returns the same (field, field_min, field_max) tuple as
build_field / build_wave_field and feeds the identical isoline -> smooth -> SVG
pipeline.
"""

import os
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.graph import MCP


# --- Tunable knobs for the marching-waves field. ---
# These module globals are the LIVE tuning surface: app.py overrides them per
# request (setattr in _apply_knobs), the ralph loop / optimizer tune them, and
# build_march_field reads them as globals. The values below are the in-code
# defaults; if `engine/march_params.json` exists it is loaded at import (see
# load_params() at the bottom) and OVERRIDES them — that JSON is the externalized,
# version-controlled tuned config the optimizer writes (loop/optimize.py) and the
# loop edits. PARAM_NAMES is the 6-vector the optimizer searches; PARAM_BOUNDS
# the search/clamp box (NORM_LO/HI are fixed robustness knobs, not searched).
MARCH_BASE = 1.0        # flat per-step cost = diamond dominance. High => crisp
                        # diamonds barely bent by the image; low => the reciprocal
                        # tone term dominates relatively (image warps the diamonds).
                        # 1.0 = white regions march at unit speed (CONTOUR-V's scale).
MARCH_FLOOR = 0.07      # speed floor: gray is clamped to [FLOOR, 1] before the
                        # reciprocal, so deep darks cost up to 1/FLOOR per step.
                        # THE tone lever — LOWER floor => darker darks (solid ink in
                        # eyes/visors); higher floor => gentler, sparser shadows.
MARCH_EDGE = 0.0        # edge magnitude -> extra cost. The reciprocal mapping makes
                        # lines pile up at tonal boundaries on its own; this knob adds
                        # extra deflection only if feature definition needs it.
MARCH_GAMMA = 1.0       # tone curve on speed: >1 darkens mids (denser midtones),
                        # <1 lightens them.
MARCH_CONTRAST = 1.0    # tonal contrast about mid-grey (sharper tonal separation).
MARCH_BLUR = 1.2        # Gaussian denoise sigma on luminance (tames busy texture;
                        # also sets how wide edge pileups smear).
MARCH_NORM_LO = 2.0     # low percentile for tone normalization (robust black point).
MARCH_NORM_HI = 98.0    # high percentile (robust white point) — avoids one blown
                        # highlight/shadow dominating the whole tonal range.


# ── externalized parameter surface (config + optimizer) ──────────────────
# The 6 aesthetic knobs the optimizer searches, with (lo, hi) search/clamp bounds.
PARAM_BOUNDS = {
    "MARCH_BASE":     (0.4, 2.0),    # diamond dominance (low=image-warped, high=stiff)
    "MARCH_FLOOR":    (0.02, 0.35),  # speed floor (THE tone lever; lower=darker darks)
    "MARCH_EDGE":     (0.0, 4.0),    # edge→density (extra feature definition)
    "MARCH_GAMMA":    (0.5, 2.0),    # midtone curve on speed
    "MARCH_CONTRAST": (0.8, 3.0),    # tonal contrast about mid-grey
    "MARCH_BLUR":     (0.0, 5.0),    # denoise sigma
}
PARAM_NAMES = tuple(PARAM_BOUNDS)
_PARAMS_PATH = Path(__file__).with_name("march_params.json")


def current_params():
    """The live values of the searchable knobs as a {NAME: float} dict."""
    g = globals()
    return {n: float(g[n]) for n in PARAM_NAMES}


def apply_params(params):
    """Set the live knob globals from a {NAME: value} dict (unknown keys ignored,
    values clamped to PARAM_BOUNDS). build_march_field reads these globals, so this
    is how the optimizer drives a candidate in-process — same surface app.py uses."""
    g = globals()
    for name, val in params.items():
        if name in PARAM_BOUNDS:
            g[name] = _clamp_to_bounds(name, val)


def _clamp_to_bounds(name, val):
    """Clamp a single knob value into its PARAM_BOUNDS range."""
    lo, hi = PARAM_BOUNDS[name]
    return float(max(lo, min(hi, val)))


def suggest_params(gray):
    """Image-adaptive knob suggestion from a normalized luminance array in [0,1]
    (0=black, 1=white). Returns {MARCH_*: float, 'levels': int}, each MARCH_* clamped
    to PARAM_BOUNDS and levels to 60..150.

    Heuristic, eyeball-tunable (the coefficients are a deliberate first pass —
    validate against examples/ before trusting). Mirrors the tone reasoning in
    loop/IDEAS.md: FLOOR is THE tone lever, CONTRAST/GAMMA are the STUDIO tonal
    controls. Only the three tonal knobs + levels are returned; BASE/EDGE/BLUR are
    left at their current live values."""
    p10, p50, p90 = (float(x) for x in np.percentile(gray, [10, 50, 90]))
    dark_frac = float((gray < 0.25).mean())
    spread = p90 - p10
    out = {
        # More dark mass -> HIGHER floor, so heavy shadows don't over-densify into a
        # blob (the "shadow areas too busy" JS-loop lesson, docs/contour-v-core-source.md).
        # Little dark mass -> low floor so the few darks still saturate to solid ink.
        "MARCH_FLOOR":    0.04 + 0.5 * dark_frac,
        # Flat / low dynamic range -> lift contrast to separate tones; wide range -> ~1.
        "MARCH_CONTRAST": 1.0 + (0.5 - spread) * 2.0,
        # Dark median -> gamma<1 lifts mids; bright median -> gamma>1 adds midtone density.
        "MARCH_GAMMA":    0.6 + p50 * 1.0,
    }
    out = {k: _clamp_to_bounds(k, v) for k, v in out.items()}
    out["levels"] = int(max(60, min(150, round(80 + 90 * spread))))
    return out


def save_params(path=_PARAMS_PATH):
    """Persist the live knob values to the JSON config (the optimizer's output)."""
    Path(path).write_text(json.dumps(current_params(), indent=2, sort_keys=True) + "\n")


def load_params(path=None):
    """Apply the JSON config if present, OVERRIDING the in-code defaults. Path:
    explicit arg → $MARCH_PARAMS env → engine/march_params.json. Returns the dict
    applied ({} if no file). Called once at import so app/loop/render/optimizer all
    share one tuned config; re-import per fresh process picks up edits."""
    p = Path(path or os.environ.get("MARCH_PARAMS") or _PARAMS_PATH)
    if p.exists():
        data = json.loads(p.read_text())
        apply_params(data)
        return {n: data[n] for n in PARAM_NAMES if n in data}
    return {}


def _preprocess_gray(luminance):
    """Luminance (0..255) -> normalized gray in 0..1 after percentile-normalize,
    blur, contrast and gamma. Returns (gray, edge), both float32 in 0..1.
    gray is the wave's local SPEED source (bright = fast)."""
    lum = luminance.astype(np.float32)
    if MARCH_BLUR > 0:
        lum = gaussian_filter(lum, sigma=MARCH_BLUR)

    # Robust percentile normalization so a few extreme pixels don't dominate.
    lo, hi = np.percentile(lum, [MARCH_NORM_LO, MARCH_NORM_HI])
    if hi - lo < 1e-3:
        hi = lo + 1e-3
    gray = np.clip((lum - lo) / (hi - lo), 0.0, 1.0)

    # Contrast about mid-grey, then gamma.
    gray = np.clip((gray - 0.5) * MARCH_CONTRAST + 0.5, 0.0, 1.0)
    gray = np.power(gray, MARCH_GAMMA)

    # Edge magnitude from the gradient of the (already blurred) gray — same idiom
    # as engine/flow.py's tangent field. Normalize to 0..1.
    gy, gx = np.gradient(gray)
    edge = np.hypot(gx, gy)
    emax = float(edge.max())
    if emax > 1e-6:
        edge = edge / emax

    return gray.astype(np.float32), edge.astype(np.float32)


def build_march_field(luminance, seed_x, seed_y, lum_mix=1.0):
    """Marching-waves arrival-time field (method=march).

    Args:
        luminance: float32 array (H, W), values 0–255
        seed_x, seed_y: seed coordinates (column, row)
        lum_mix: scales the tone term (matches the other methods' render param)

    Returns:
        field: float32 array (H, W) — wave arrival time from the seed
        field_min: float
        field_max: float
    """
    H, W = luminance.shape
    gray, edge = _preprocess_gray(luminance)

    # Per-step cost = 1/speed, the confirmed CONTOUR-V mapping: bright marches at
    # ~unit cost, deep darks cost up to 1/MARCH_FLOOR (lines bunch to solid ink).
    # lum_mix scales the tone term (0 = flat cost = pure diamonds), matching its
    # semantics in the other methods. Strictly positive, so MCP's geodesic is
    # well-defined.
    speed = np.clip(gray, MARCH_FLOOR, 1.0)
    # float32 (not float64): this is the heaviest array in the pipeline and the
    # single biggest peak-memory term for large mural grids. MCP accepts float32
    # and `cumulative` is downcast to float32 below anyway, so the geodesic is
    # numerically unchanged for our purposes while the footprint halves.
    cost = (MARCH_BASE
            + float(lum_mix) * (1.0 / speed - 1.0)
            + MARCH_EDGE * edge).astype(np.float32)

    sy = int(np.clip(seed_y, 0, H - 1))
    sx = int(np.clip(seed_x, 0, W - 1))

    # 4-connectivity -> L1 geodesic -> diamond wavefronts (the whole point).
    mcp = MCP(cost, fully_connected=False)
    cumulative, _ = mcp.find_costs([(sy, sx)])

    # Unreachable cells (shouldn't occur with finite positive cost) come back inf;
    # replace with the finite max so the field is well-bounded.
    field = np.asarray(cumulative, dtype=np.float32)
    finite = np.isfinite(field)
    if not finite.all():
        field[~finite] = field[finite].max()

    return field, float(field.min()), float(field.max())


# Apply the externalized tuned config (engine/march_params.json) over the in-code
# defaults at import, so the app, the loop, render.py and the optimizer all share
# one source of truth. A fresh process per loop tick re-imports and re-reads it.
load_params()
