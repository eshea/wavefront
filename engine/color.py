"""
Color-layer assignment for WAVEFRONT (mural color mode).

Single black ink is the CORE default. For prints/murals this module tags each
contour with an integer 'layer' index so export.contours_to_svg_layered can emit
one pen color per layer. Two ways to split:

  - 'tone'  (duotone portrait): band by the image's local darkness sampled along
            the contour — shadows in one ink, highlights in another. Reads as a
            classic 2- or 3-color contour portrait.
  - 'depth' (elevation ramp): band by normalized_t (position in the field range)
            — concentric color zones radiating from the seed, the hypsometric /
            topographic-map look that suits the wide diamond margins.

Operates on PROCESSING-GRID contours (before scale_contours), sampling the
processing-grid gray, so indices line up with the field.
"""

import numpy as np


# Ordered dark -> light default ramp (ocean -> sand -> rust); layer 0 is darkest
# so 'tone' mode puts shadows in the deepest color. Overridable per request.
DEFAULT_PALETTE = ['#10202b', '#2a6f8f', '#5fb0a6', '#e3b23c', '#d9692b', '#a8324a']


def default_palette(n_colors):
    """First n_colors of the default ramp (clamped to 1..len)."""
    n = max(1, min(len(DEFAULT_PALETTE), int(n_colors)))
    return DEFAULT_PALETTE[:n]


def _sample_gray(points, gray):
    """Mean gray (0..1) under a contour's [row,col] points."""
    H, W = gray.shape
    rows = np.clip(np.rint(points[:, 0]).astype(np.intp), 0, H - 1)
    cols = np.clip(np.rint(points[:, 1]).astype(np.intp), 0, W - 1)
    return float(gray[rows, cols].mean())


def assign_layers(contours, n_colors, *, mode='tone', gray=None):
    """Tag each contour dict in-place with c['layer'] (int 0..n_colors-1).

    Args:
        contours: list of dicts with 'points' [row,col] and 'normalized_t'.
        n_colors: number of color layers (>=1).
        mode: 'tone' (band by local darkness; needs gray) or 'depth' (band by
            normalized_t). Unknown modes fall back to 'depth'.
        gray: float array (H, W) in 0..1 (0=black) on the processing grid, used
            for 'tone'. If None in 'tone' mode, falls back to 'depth'.

    Returns the same list (mutated), for convenience.
    """
    n = max(1, int(n_colors))
    if n == 1:
        for c in contours:
            c['layer'] = 0
        return contours

    use_tone = (mode == 'tone' and gray is not None)
    for c in contours:
        if use_tone:
            # Darkest -> layer 0. gray 0 (black) => band 0; gray 1 (white) => band n-1.
            v = _sample_gray(c['points'], gray)
        else:
            # depth: nearest the seed (low t) -> layer 0.
            v = float(c.get('normalized_t', 0.0))
        band = int(np.clip(int(v * n), 0, n - 1))
        c['layer'] = band
    return contours
