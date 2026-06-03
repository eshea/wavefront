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
Dark must mean DENSER lines, so dark/edges ADD cost:

    cost = MARCH_BASE + MARCH_TONE*lum_mix*dark + MARCH_EDGE*edge
    T    = MCP(cost, 4-connected).find_costs(seed)      # arrival time (the field)

build_march_field returns the same (field, field_min, field_max) tuple as
build_field / build_wave_field and feeds the identical isoline -> smooth -> SVG
pipeline.
"""

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.graph import MCP


# --- Tunable knobs for the marching-waves field (the ralph loop edits these the
# same way it edits the WAVE_* constants). ---
MARCH_BASE = 1.0        # base per-step cost = diamond dominance. High => crisp
                        # diamonds barely bent by the image; low => image dominates.
MARCH_TONE = 2.5        # darkness -> extra cost (× lum_mix). Higher => darks bunch
                        # lines harder (denser shadows / "visor goes black").
MARCH_EDGE = 1.5        # edge magnitude -> extra cost. Higher => lines pile up and
                        # deflect at feature boundaries (eyes/nose/jaw rim).
MARCH_GAMMA = 1.0       # tone curve on gray: >1 darkens mids (more contour activity
                        # in midtones), <1 lightens them.
MARCH_CONTRAST = 1.4    # tonal contrast about mid-grey (sharper tonal separation).
MARCH_BLUR = 2.0        # Gaussian denoise sigma on luminance (tames busy texture).
MARCH_NORM_LO = 2.0     # low percentile for tone normalization (robust black point).
MARCH_NORM_HI = 98.0    # high percentile (robust white point) — avoids one blown
                        # highlight/shadow dominating the whole tonal range.


def _preprocess_gray(luminance):
    """Luminance (0..255) -> normalized gray in 0..1 after percentile-normalize,
    blur, contrast and gamma. Returns (gray, dark, edge), all float32 in 0..1."""
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

    dark = 1.0 - gray

    # Edge magnitude from the gradient of the (already blurred) gray — same idiom
    # as engine/flow.py's tangent field. Normalize to 0..1.
    gy, gx = np.gradient(gray)
    edge = np.hypot(gx, gy)
    emax = float(edge.max())
    if emax > 1e-6:
        edge = edge / emax

    return gray.astype(np.float32), dark.astype(np.float32), edge.astype(np.float32)


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
    _, dark, edge = _preprocess_gray(luminance)

    # Per-step cost (~1/speed). Strictly positive so MCP has a well-defined geodesic.
    cost = (MARCH_BASE
            + MARCH_TONE * float(lum_mix) * dark
            + MARCH_EDGE * edge).astype(np.float64)

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
