#!/usr/bin/env python3
"""
loop/score.py — quantitative scoring for one WAVEFRONT iteration output.

Compares a rendered output PNG against a reference image and emits a
single JSON line with three scores. Designed to be invoked once per
ralph tick; output is appended to loop/metrics.jsonl.

Metrics:
- path_fit     : 1 - min(1, |paths - target_paths| / target_paths). 1.0 is perfect.
                 Requires --stats-json with the /process response stats; otherwise null.
- ink_coverage : fraction of non-white pixels in the output (0..1). Density
                 CO-SIGNAL + degenerate-output guard. Measured empirically: it does
                 NOT separate the judge's subtle "blob" failures from good outputs
                 (judge-85 and judge-15 renders sit within ~3% of each other, and the
                 human-rated-95 anchor is the densest of all). It only catches the
                 unambiguous extremes — near-solid-black (>~0.92) or near-blank
                 (<~0.03). Subtle over-density is the visual judge's call, not this.
- ssim         : structural similarity, grayscale, output resized to ref dims. 0..1.
                 CO-SIGNAL ONLY — near-flat across good and bad outputs; do not gate on it.
- edge_iou     : IoU of Canny edge maps. 0..1. CO-SIGNAL ONLY (same caveat as ssim).

Reference numbers come from contour_woman_settings.webp screenshot:
target_paths=452, target_points=135962.

Usage:
    python loop/score.py --output loop/output/iter_037.png \\
                         --reference examples/contour_woman_post1.jpeg \\
                         [--stats-json loop/log/iter_037.stats.json] \\
                         [--iter 37]
"""

import argparse
import json
import sys
import datetime as _dt
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
from skimage.feature import canny


TARGET_PATHS = 452
TARGET_POINTS = 135_962


def load_gray(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    """Load image as grayscale uint8 numpy array, optionally resized."""
    img = Image.open(path).convert("L")
    if size is not None and img.size != size:
        img = img.resize(size, Image.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def compute_ssim(out_gray: np.ndarray, ref_gray: np.ndarray) -> float:
    # SSIM on uint8 grayscale, full image, no multichannel.
    win = min(7, min(out_gray.shape) - (1 - min(out_gray.shape) % 2))
    if win < 3:
        return float("nan")
    s = ssim(out_gray, ref_gray, data_range=255, win_size=win)
    return float(s)


def compute_edge_iou(out_gray: np.ndarray, ref_gray: np.ndarray,
                     sigma: float = 1.5) -> float:
    e_out = canny(out_gray, sigma=sigma)
    e_ref = canny(ref_gray, sigma=sigma)
    inter = np.logical_and(e_out, e_ref).sum()
    union = np.logical_or(e_out, e_ref).sum()
    if union == 0:
        return 0.0
    return float(inter / union)


def compute_ink_coverage(gray: np.ndarray, white_thresh: int = 250) -> float:
    """Fraction of pixels darker than `white_thresh` (i.e. inked).

    Computed on the output's own pixels (NOT resized to the reference) so
    anti-aliasing from a resize can't inflate it. Use as a density
    co-signal and a guard against degenerate output (near-solid-black or
    near-blank). NOTE (measured): it does NOT cleanly separate the judge's
    subtle over-dense "blob" failures — those differ from good outputs by
    only a few percent here, so don't gate quality on a fine threshold;
    only the extremes are unambiguous.
    """
    inked = int((gray < white_thresh).sum())
    return float(inked / gray.size)


def compute_path_fit(stats: dict | None) -> tuple[float | None, int | None,
                                                    int | None]:
    """Return (path_fit, paths, points). path_fit is None if no stats."""
    if not stats:
        return None, None, None
    paths = int(stats.get("paths", 0))
    points = int(stats.get("total_points", 0))
    fit = 1.0 - min(1.0, abs(paths - TARGET_PATHS) / TARGET_PATHS)
    return float(fit), paths, points


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path,
                   help="rendered output image (PNG / JPEG / WEBP)")
    p.add_argument("--reference", required=True, type=Path,
                   help="reference image to compare against")
    p.add_argument("--stats-json", type=Path, default=None,
                   help="optional JSON file containing /process stats "
                        "for path_fit calculation")
    p.add_argument("--iter", type=int, default=None,
                   help="iteration number to record in the output JSON")
    args = p.parse_args()

    if not args.output.exists():
        sys.stderr.write(f"score.py: output missing: {args.output}\n")
        return 2
    if not args.reference.exists():
        sys.stderr.write(f"score.py: reference missing: {args.reference}\n")
        return 2

    ref_gray = load_gray(args.reference)
    H, W = ref_gray.shape  # numpy: (rows, cols)
    out_native = load_gray(args.output)          # native res — for ink_coverage
    out_gray = load_gray(args.output, size=(W, H))  # resized — for ssim/edge

    record = {
        "iter": args.iter,
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "output": str(args.output),
        "reference": str(args.reference),
        "ref_size": [W, H],
        "ink_coverage": round(compute_ink_coverage(out_native), 4),
        "ssim": round(compute_ssim(out_gray, ref_gray), 4),
        "edge_iou": round(compute_edge_iou(out_gray, ref_gray), 4),
        "target_paths": TARGET_PATHS,
        "target_points": TARGET_POINTS,
    }

    stats = None
    if args.stats_json and args.stats_json.exists():
        try:
            stats = json.loads(args.stats_json.read_text())
        except json.JSONDecodeError:
            sys.stderr.write(f"score.py: bad JSON in {args.stats_json}\n")

    fit, paths, points = compute_path_fit(stats)
    record["path_fit"] = fit if fit is None else round(fit, 4)
    record["paths"] = paths
    record["points"] = points

    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
