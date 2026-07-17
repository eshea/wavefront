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

from engine.field import build_rotated_distance, shape_tone_term
from engine.contour import extract_contours, clip_contours_to_mask
from engine.smooth import resample_contours


# Ordered dark -> light default ramp (ocean -> sand -> rust); layer 0 is darkest
# so 'tone' mode puts shadows in the deepest color. Overridable per request.
DEFAULT_PALETTE = ['#10202b', '#2a6f8f', '#5fb0a6', '#e3b23c', '#d9692b', '#a8324a']

# Process-color separation. Each channel is drawn as its own pen layer with the
# field rotated to a classic halftone screen angle so the four line sets cross at
# distinct angles instead of beating into a moiré (the print-craft reason screens
# are angled). Order matches rgb_to_cmyk: C, M, Y, K.
CMYK_PALETTE = ['#00aeef', '#ec008c', '#fff200', '#000000']
SCREEN_ANGLES = [15.0, 75.0, 0.0, 45.0]


def default_palette(n_colors):
    """First n_colors of the default ramp (clamped to 1..len)."""
    n = max(1, min(len(DEFAULT_PALETTE), int(n_colors)))
    return DEFAULT_PALETTE[:n]


def cmyk_palette():
    """The four process-color pen colors (cyan, magenta, yellow, black)."""
    return list(CMYK_PALETTE)


def rgb_to_cmyk(rgb_array):
    """Split an (H,W,3) 0–255 RGB image into [C, M, Y, K] float maps in 0–1."""
    rgb = rgb_array.astype(np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    k = 1.0 - np.maximum(np.maximum(r, g), b)
    denom = np.where(k < 1.0, 1.0 - k, 1.0)
    c = np.clip((1.0 - r - k) / denom, 0.0, 1.0)
    m = np.clip((1.0 - g - k) / denom, 0.0, 1.0)
    y = np.clip((1.0 - b - k) / denom, 0.0, 1.0)
    return [c, m, y, np.clip(k, 0.0, 1.0)]


def _resize_to(arr, shape):
    """Nearest-neighbour resample of a 2-D map to `shape` (crash-proof when the
    source RGB grid differs from a padded canvas luminance grid)."""
    if arr.shape == shape:
        return arr
    H, W = shape
    ys = np.linspace(0, arr.shape[0] - 1, H).astype(np.intp)
    xs = np.linspace(0, arr.shape[1] - 1, W).astype(np.intp)
    return arr[np.ix_(ys, xs)]


def separate_channels(luminance, rgb_array, seed_x, seed_y, levels, lum_mix=1.0,
                      *, mode='cmyk', n_colors=4, angles=None, threshold=0.12):
    """Multi-pen channel separation: render each channel as its own rotated diamond
    field, clipped to where that channel is present, tagged with its pen `layer`.

      - mode='cmyk': four C/M/Y/K channels from `rgb_array`; line density follows
        each channel's intensity, clipped to where the channel is >= `threshold`.
        `rgb_array` must already be registered to the `luminance` grid (the caller
        recomposes it for wide canvases); a residual shape mismatch is resampled.
      - mode='lum': `n_colors` luminance tiers from darkest to lightest; the diamond
        field follows the real luminance, each tier clipped to its tonal band — every
        tier shares ONE luminance term (computed once; only rotation/mask vary).

    Each layer's field is rotated to a distinct screen angle (`angles`, default
    `SCREEN_ANGLES`) to avoid moiré. Returns one flat contour list (layers mixed),
    each contour carrying a `layer` index for `contours_to_svg_layered`.

    Each spec is `(lum_term, mask)`: `lum_term` is the rotation-independent
    luminance field term (`shape_tone_term`), `mask` selects where that pen draws."""
    angles = angles or SCREEN_ANGLES
    shape = luminance.shape
    if mode == 'cmyk':
        chans = [_resize_to(ch, shape) for ch in rgb_to_cmyk(rgb_array)]
        # Each channel drives its OWN luminance term (density follows the channel).
        specs = [(shape_tone_term((1.0 - ch) * 255.0, lum_mix), ch >= threshold)
                 for ch in chans]
    else:  # 'lum' tonal tiers — every tier shares the SAME luminance term.
        n = max(1, int(n_colors))
        lum_term = shape_tone_term(luminance, lum_mix)
        dark = 1.0 - np.clip(luminance / 255.0, 0.0, 1.0)
        edges = np.linspace(0.0, 1.0, n + 1)
        specs = []
        for t in range(n):
            hi_ok = (dark <= edges[t + 1]) if t == n - 1 else (dark < edges[t + 1])
            specs.append((lum_term, (dark >= edges[t]) & hi_ok))

    out = []
    for idx, (lum_term, mask) in enumerate(specs):
        angle = float(angles[idx % len(angles)])
        field = build_rotated_distance(shape, seed_x, seed_y, angle) + lum_term
        contours, _ = extract_contours(field, levels,
                                       float(field.min()), float(field.max()))
        contours = resample_contours(contours)
        out.extend(clip_contours_to_mask(contours, mask, layer=idx))
    return out


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
