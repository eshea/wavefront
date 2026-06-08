#!/usr/bin/env python3
"""
loop/dscore.py — DETERMINISTIC quality score for one WAVEFRONT output.

Replaces the LLM vision judge. Emits a single JSON line with a 0-100
``d_score`` (plus its components) for one rendered output, computed purely
from image processing — no network, no backend, fully reproducible.

The score has two metric families:

  A. SOURCE-FIDELITY (the discriminating signal). A good output is the
     *source* re-expressed as flowing contour lines: lines bunch/darken/bend
     where the source has edges and tone, and flow as clean parallel waves
     where it's flat. So we compare the output to its OWN source — which is
     perfectly aligned (same composition) — at a COARSE grid. We correlate a
     source "saliency" map (edges + local contrast + inverted luminance)
     against an output "activity" map (line density + local line curvature).
     This is what makes the subject recognisable and the density
     tone-modulated. Comparing the output to a *reference output* (the old
     ssim/edge_iou approach) fails: two line drawings' strokes never align,
     so those metrics are flat across good and bad.

  B. STYLE (necessary-but-not-sufficient). Does it look like the VEX-LINE
     family at all? Dominant line spacing (radius-whitened radial FFT), ink
     coverage band, and orientation coherence — each scored by distance from
     the good-output library's profile.

Degenerate output (near-blank, near-solid, no line structure) is gated to ~0.

The calibration constants in ``CALIB`` below were fit so the artist's
good outputs (examples/space, examples/woman) land ~95 and synthesized
blank/solid/noise land <5. Re-fit with ``--calibrate`` (see dscore_calib.sh).

Usage:
    python loop/dscore.py --output loop/output/iter_037.png \\
                          --source examples/space/space-source.jpg [--iter 37]
    python loop/dscore.py --output OUT --source SRC --style-only   # subject-mismatch refs
    python loop/dscore.py --output OUT --source SRC --calibrate     # dump raw components
"""

import argparse
import json
import sys
import datetime as _dt
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from skimage.measure import block_reduce
from skimage.metrics import structural_similarity as ssim


# ── working resolutions ──────────────────────────────────────────────────
WORK = 384          # square grid for source-fidelity (384 = 48*8, clean pool)
GRID_N = 48         # coarse cells per side for the fidelity maps
STYLE_WORK = 512    # square grid for the FFT / style stats
INK_THRESH = 160    # px < this = "inked" (tolerant of AA / JPEG'd line edges)

# ── calibration constants (fit by --calibrate over the good-output library) ──
CALIB = {
    # style sub-metric Gaussians: score = exp(-0.5*((x-mu)/sigma)^2)
    "peak_mu": 6.5, "peak_sigma": 4.0,     # dominant radial-FFT spacing bin
    "peakedness_full": 3.0,                # peakedness mapped to 1.0 at/above this
    # coherence is a WEAK signal: real VEX art bends lines around features, so
    # global orientation coherence is low (measured 0.04-0.25 on good outputs).
    # Centered low + wide so it barely penalises good output and only nudges.
    "coh_mu": 0.12, "coh_sigma": 0.20,
    "ink_lo": 0.05, "ink_hi": 0.50, "ink_sigma": 0.06,  # wide plateau (density
    #                          is fidelity's job; ink only rejects extremes)
    # DIAMOND / ORGANIC-CONTOUR signature — the VEX-LINE / CONTOUR-V aesthetic.
    # L1-diamond contours run at ±45°, so edge orientation concentrates on the
    # diagonals. Measured `diag_frac` (mag-weighted fraction of gradients within
    # ±15° of 45°/135°) across the FULL artist range: samurai (heavily-warped,
    # flowing) 0.39 → woman diamonds 0.50 → space 0.57 → good engine wave 0.60.
    # The BAD axis-aligned engine flow is 0.25; the stiff moiré is 0.86. So this is
    # a PLATEAU (full credit across the genuine range) with falloff only at the
    # extremes, applied as a multiplicative factor.
    "diam_lo": 0.42, "diam_hi": 0.62, "diam_sigma": 0.08,
    "diam_floor": 0.45,    # factor = diam_floor + (1-diam_floor)*diamond_score
    # fidelity rescale: a genuinely-matched pair correlates ~0.24-0.30, not ~1.
    # fid_score = clip(fidelity_raw / FID_FULL, 0, 1). Anchored on the space pair.
    "FID_FULL": 0.28,
    # style sub-weights
    "w_freq": 0.55, "w_ink": 0.20, "w_coh": 0.25,
    # gate thresholds
    "ink_gate_lo": 0.008, "ink_gate_hi": 0.85, "std_gate": 6.0,
    "edge_frac_min": 0.03,                 # below → filled blob, not strokes
    # below → *0.3 (no real line ridge). Noise whitens to peakedness ~2; the
    # sparsest good output (woman4) is ~3.4 — floor sits between, with margin.
    "peakedness_min": 2.3,
    # final affine: d_score = 100*clip((combined - C_LO)/(C_HI - C_LO), 0, 1)
    "C_LO": 0.12, "C_HI": 0.92,
}


def gauss(x: float, mu: float, sigma: float) -> float:
    return float(np.exp(-0.5 * ((x - mu) / sigma) ** 2))


def plateau(x: float, lo: float, hi: float, sigma: float) -> float:
    """1.0 inside [lo, hi]; gaussian falloff (width sigma) outside. A tolerant
    band score — full credit across a range, penalty only at the extremes."""
    if x < lo:
        return gauss(x, lo, sigma)
    if x > hi:
        return gauss(x, hi, sigma)
    return 1.0


def load_gray_work(path: Path, work: int) -> np.ndarray:
    """Grayscale (BT.601 luma, matching the engine), resized to work×work."""
    img = Image.open(path).convert("L")
    if img.size != (work, work):
        img = img.resize((work, work), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32)


def _norm(a: np.ndarray) -> np.ndarray:
    m = float(a.max())
    return a / m if m > 1e-9 else a


# ── Module A: source fidelity ────────────────────────────────────────────
def source_saliency(src: np.ndarray, n: int = GRID_N) -> np.ndarray:
    """Coarse n×n map of 'where lines should be dense' in the source."""
    blk = src.shape[0] // n
    g = gaussian_filter(src, 2.0)                      # suppress JPEG noise
    gy, gx = np.gradient(g)
    grad = np.hypot(gy, gx)                             # structural edges
    contrast = np.sqrt(np.clip(
        gaussian_filter(src ** 2, 6.0) - gaussian_filter(src, 6.0) ** 2,
        0.0, None))                                    # local detail/texture
    inv = 255.0 - src                                  # dark → dense ink
    grad_n = _norm(block_reduce(grad, (blk, blk), np.mean))
    con_n = _norm(block_reduce(contrast, (blk, blk), np.mean))
    inv_n = _norm(block_reduce(inv, (blk, blk), np.mean))
    S = 0.45 * grad_n + 0.25 * con_n + 0.30 * inv_n
    return _norm(S)


def output_activity(out: np.ndarray, n: int = GRID_N) -> np.ndarray:
    """Coarse n×n map of line density + local line curvature in the output."""
    blk = out.shape[0] // n
    ink = (out < INK_THRESH).astype(np.float32)
    dens = _norm(block_reduce(ink, (blk, blk), np.mean))
    # local line curvature: circular variance of the DOUBLED gradient angle
    # (orientation is mod π). ~0 in clean parallel flow, high where lines bend.
    g = gaussian_filter(out, 1.0)
    gy, gx = np.gradient(g)
    theta = np.arctan2(gy, gx)
    mag = np.hypot(gy, gx)
    z = mag * np.exp(2j * theta)
    Zr = block_reduce(z.real, (blk, blk), np.sum)
    Zi = block_reduce(z.imag, (blk, blk), np.sum)
    M = block_reduce(mag, (blk, blk), np.sum)
    R = np.abs(Zr + 1j * Zi) / np.maximum(M, 1e-9)
    curv = _norm(1.0 - R)
    O = 0.75 * dens + 0.25 * curv
    return _norm(O)


def fidelity(src_work: np.ndarray, out_work: np.ndarray) -> dict:
    S = source_saliency(src_work)
    O = output_activity(out_work)
    sf, of = S.ravel(), O.ravel()
    if sf.std() < 1e-9 or of.std() < 1e-9:
        r = 0.0
    else:
        r = float(np.corrcoef(sf, of)[0, 1])
    s_so = float(ssim(S, O, data_range=1.0, win_size=7))
    raw = 0.6 * max(0.0, r) + 0.4 * max(0.0, s_so)
    return {"r": r, "ssim_so": s_so, "fidelity_raw": raw}


# ── Module B: style ──────────────────────────────────────────────────────
def _radial_profile(g: np.ndarray) -> np.ndarray:
    g = g - g.mean()
    power = np.abs(np.fft.fftshift(np.fft.fft2(g))) ** 2
    cy, cx = (s // 2 for s in power.shape)
    yy, xx = np.indices(power.shape)
    r = np.hypot(yy - cy, xx - cx).astype(int)
    tot = np.bincount(r.ravel(), weights=power.ravel())
    cnt = np.maximum(np.bincount(r.ravel()), 1)
    return tot / cnt


def style(out_work512: np.ndarray) -> dict:
    prof = _radial_profile(out_work512)
    lo, hi = 6, min(220, len(prof) - 1)
    band = np.arange(lo, hi)
    whitened = band * prof[lo:hi]                      # radius-whiten (kill DC)
    peak_i = int(band[int(np.argmax(whitened))])
    med = float(np.median(whitened)) or 1e-9
    peakedness = float(whitened.max() / med)           # sharp ridge vs blob

    ink = float((out_work512 < INK_THRESH).mean())
    std = float(out_work512.std())

    # global orientation coherence: resultant length of doubled angles
    g = gaussian_filter(out_work512, 1.0)
    gy, gx = np.gradient(g)
    theta = np.arctan2(gy, gx)
    mag = np.hypot(gy, gx)
    coh = float(np.abs((mag * np.exp(2j * theta)).sum()) / max(mag.sum(), 1e-9))
    # edge fraction: line art is thin strokes (many ink↔white edges); a smooth
    # blob / filled region has high ink but almost no edges. Separates the two.
    edge_frac = float((mag > 20.0).mean())
    # diamond signature: mag-weighted fraction of gradient orientation within
    # ±15° of the diagonals (45°/135°). High for L1-diamond contours (the target
    # aesthetic); low for axis-aligned flowing waves.
    ang = np.degrees(theta) % 180.0
    diag = (np.abs(ang - 45.0) <= 15.0) | (np.abs(ang - 135.0) <= 15.0)
    diag_frac = float(mag[diag].sum() / max(mag.sum(), 1e-9))

    freq_loc = gauss(peak_i, CALIB["peak_mu"], CALIB["peak_sigma"])
    peak_norm = min(1.0, peakedness / CALIB["peakedness_full"])
    freq_score = 0.6 * freq_loc + 0.4 * peak_norm
    if ink < CALIB["ink_lo"]:
        ink_score = gauss(ink, CALIB["ink_lo"], CALIB["ink_sigma"])
    elif ink > CALIB["ink_hi"]:
        ink_score = gauss(ink, CALIB["ink_hi"], CALIB["ink_sigma"])
    else:
        ink_score = 1.0
    coh_score = gauss(coh, CALIB["coh_mu"], CALIB["coh_sigma"])
    raw = (CALIB["w_freq"] * freq_score + CALIB["w_ink"] * ink_score
           + CALIB["w_coh"] * coh_score)
    diamond_score = plateau(diag_frac, CALIB["diam_lo"], CALIB["diam_hi"],
                            CALIB["diam_sigma"])
    return {"freq_peak": peak_i, "peakedness": peakedness, "ink": ink,
            "std": std, "coh": coh, "edge_frac": edge_frac, "diag_frac": diag_frac,
            "freq_score": freq_score, "ink_score": ink_score,
            "coh_score": coh_score, "diamond_score": diamond_score, "style_raw": raw}


def compute_gate(st: dict) -> float:
    g = 1.0
    if (st["ink"] < CALIB["ink_gate_lo"] or st["ink"] > CALIB["ink_gate_hi"]
            or st["std"] < CALIB["std_gate"]
            or st["edge_frac"] < CALIB["edge_frac_min"]):
        return 0.0
    if st["peakedness"] < CALIB["peakedness_min"]:
        g *= 0.3
    return g


def score(out_path: Path, src_path: Path, style_only: bool = False) -> dict:
    out_w = load_gray_work(out_path, WORK)
    out_s = load_gray_work(out_path, STYLE_WORK)
    st = style(out_s)
    gate = compute_gate(st)

    # Diamond factor: actively prefers the ±45° diamond aesthetic (output-4) over
    # axis-aligned flowing waves. A strong multiplicative term on the final score.
    diam_factor = CALIB["diam_floor"] + (1 - CALIB["diam_floor"]) * st["diamond_score"]

    if style_only:
        fid = {"r": None, "ssim_so": None, "fidelity_raw": None}
        combined = st["style_raw"] * gate * diam_factor
    else:
        src_w = load_gray_work(src_path, WORK)
        fid = fidelity(src_w, out_w)
        fid_score = min(1.0, fid["fidelity_raw"] / CALIB["FID_FULL"])
        combined = (0.55 * fid_score + 0.45 * st["style_raw"]) * gate * diam_factor

    lo, hi = CALIB["C_LO"], CALIB["C_HI"]
    d = int(round(100 * float(np.clip((combined - lo) / (hi - lo), 0.0, 1.0))))
    return {
        "d_score": d,
        "d_fidelity": None if fid["fidelity_raw"] is None
        else round(fid["fidelity_raw"], 4),
        "d_style": round(st["style_raw"], 4),
        "d_r": None if fid["r"] is None else round(fid["r"], 4),
        "d_ssim_so": None if fid["ssim_so"] is None else round(fid["ssim_so"], 4),
        "d_freq_peak": st["freq_peak"],
        "d_peakedness": round(st["peakedness"], 3),
        "d_ink": round(st["ink"], 4),
        "d_coh": round(st["coh"], 4),
        "d_diag": round(st["diag_frac"], 4),
        "d_diamond": round(st["diamond_score"], 4),
        "d_gate": round(gate, 3),
        "_combined": round(combined, 4),
        "_st": st,           # for --calibrate only; stripped before emit
        "_fid": fid,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--iter", type=int, default=None)
    p.add_argument("--style-only", action="store_true",
                   help="skip source-fidelity (for subject-mismatch refs)")
    p.add_argument("--calibrate", action="store_true",
                   help="dump all raw sub-metric components for fitting")
    args = p.parse_args()

    if not args.output.exists():
        sys.stderr.write(f"dscore.py: output missing: {args.output}\n")
        return 2
    if not args.style_only and not args.source.exists():
        sys.stderr.write(f"dscore.py: source missing: {args.source}\n")
        return 2

    res = score(args.output, args.source, style_only=args.style_only)

    if args.calibrate:
        flat = {"output": str(args.output), "source": str(args.source),
                **{k: v for k, v in res.items() if not k.startswith("_st")
                   and not k.startswith("_fid")},
                **res["_st"]}
        print(json.dumps(flat))
        return 0

    record = {
        "iter": args.iter,
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "output": str(args.output),
        "d_source": str(args.source),
        **{k: v for k, v in res.items() if not k.startswith("_")},
    }
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
