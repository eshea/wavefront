"""
Wide-canvas composition for WAVEFRONT (mural mode).

CORE renders at the source photo's aspect. A wall mural is wide (~2:1), and the
L1 diamond field *radiates from the seed*, so the natural mural move is to place
the subject inside a wider canvas and let the diamonds fill the margins as clean
nested rings. This module does exactly that: it pads the (already preprocessed,
max_dim-capped) luminance grid out to a target aspect, fills the margins with a
chosen tone, and remaps the seed into canvas space. Everything downstream
(field -> contours -> smooth -> SVG) runs unchanged on the wider grid.

Opt-in: compose_canvas is only called when the request asks for a canvas aspect.
Default behavior (no aspect) leaves the source untouched.
"""

import numpy as np


# Margin fill modes. 'light' makes the padded field resolve to pure diamonds
# (255-lum term -> 0 / march speed -> 1), the striking clean-ring mural border.
MARGIN_FILLS = ('light', 'mean', 'dark', 'edge')


def parse_aspect(spec):
    """Parse a target width:height aspect from a string.

    Accepts 'W:H' (e.g. '2:1', '7:3.5'), a bare ratio ('2', '1.85'), or
    'WxH'/'W,H'. Returns a positive float W/H, or None if spec is blank/None
    (meaning: keep the source aspect, i.e. mural mode off).

    Raises ValueError on a malformed or non-positive spec.
    """
    if spec is None:
        return None
    s = str(spec).strip().lower()
    if s == '':
        return None
    for sep in (':', 'x', ',', '/'):
        if sep in s:
            a, _, b = s.partition(sep)
            w, h = float(a), float(b)
            break
    else:
        w, h = float(s), 1.0
    if not (np.isfinite(w) and np.isfinite(h)) or w <= 0 or h <= 0:
        raise ValueError('aspect must be positive')
    return w / h


def _fill_value(luminance, margin_fill):
    """Scalar luminance (0..255) used to fill padded margins."""
    if margin_fill == 'mean':
        return float(luminance.mean())
    if margin_fill == 'dark':
        return 0.0
    # 'light' (default) and 'edge' both start from white; 'edge' overwrites the
    # margins with replicated border pixels afterward.
    return 255.0


def compose_canvas(luminance, aspect, *, seed=None, fit='contain',
                   margin_fill='light'):
    """Place a luminance grid inside a target-aspect canvas.

    Args:
        luminance: float32 array (H, W), values 0..255 (the subject grid).
        aspect: target canvas width/height ratio (float > 0).
        seed: (sx, sy) seed in subject-grid coords, or None to center on the canvas.
        fit: 'contain' (letterbox the whole subject, fill margins — the mural
             default) or 'cover' (center-crop the subject to the aspect, no margins).
        margin_fill: one of MARGIN_FILLS, used for 'contain' padding.

    Returns:
        canvas: float32 array (CH, CW) — the composed luminance grid.
        canvas_size: (CW, CH) tuple (width, height).
        seed_xy: (sx, sy) seed remapped into canvas coords.
        subject_rect: {'x', 'y', 'w', 'h'} subject placement in canvas coords
                      (for the UI to draw the ghost / bounds correctly).
    """
    if aspect is None or aspect <= 0:
        raise ValueError('aspect must be a positive number')
    if margin_fill not in MARGIN_FILLS:
        margin_fill = 'light'

    H, W = luminance.shape
    src_aspect = W / H
    sx, sy = (W / 2.0, H / 2.0) if seed is None else (float(seed[0]), float(seed[1]))

    if fit == 'cover':
        # Center-crop the subject grid to the target aspect (no margins).
        if aspect >= src_aspect:
            cw, ch = W, int(round(W / aspect))
        else:
            ch, cw = H, int(round(H * aspect))
        cw, ch = max(1, min(W, cw)), max(1, min(H, ch))
        x0 = (W - cw) // 2
        y0 = (H - ch) // 2
        canvas = luminance[y0:y0 + ch, x0:x0 + cw].astype(np.float32, copy=True)
        seed_xy = (_clampf(sx - x0, 0, cw - 1), _clampf(sy - y0, 0, ch - 1))
        subject_rect = {'x': 0, 'y': 0, 'w': cw, 'h': ch}
        return canvas, (cw, ch), seed_xy, subject_rect

    # 'contain': pad the subject out to the target aspect.
    if aspect >= src_aspect:
        ch = H
        cw = int(round(H * aspect))
    else:
        cw = W
        ch = int(round(W / aspect))
    cw, ch = max(W, cw), max(H, ch)
    x0 = (cw - W) // 2
    y0 = (ch - H) // 2

    canvas = np.full((ch, cw), _fill_value(luminance, margin_fill),
                     dtype=np.float32)
    canvas[y0:y0 + H, x0:x0 + W] = luminance

    if margin_fill == 'edge':
        # Replicate the subject's border pixels across the margins (a smeared
        # continuation rather than a flat tone).
        if x0 > 0:
            canvas[y0:y0 + H, :x0] = luminance[:, :1]
            canvas[y0:y0 + H, x0 + W:] = luminance[:, -1:]
        if y0 > 0:
            canvas[:y0, :] = canvas[y0:y0 + 1, :]
            canvas[y0 + H:, :] = canvas[y0 + H - 1:y0 + H, :]

    seed_xy = (_clampf(sx + x0, 0, cw - 1), _clampf(sy + y0, 0, ch - 1))
    subject_rect = {'x': x0, 'y': y0, 'w': W, 'h': H}
    return canvas, (cw, ch), seed_xy, subject_rect


def compose_rgb_canvas(rgb, aspect, *, fit='contain'):
    """Register an (H, W, 3) RGB grid into the SAME target-aspect canvas that
    `compose_canvas` produces for the luminance (the placement is purely geometric,
    so every channel lands identically) — used so CMYK channel separation stays
    aligned to the subject on wide canvases instead of stretching across the whole
    frame. Margins are filled white (→ no color ink there) regardless of the
    luminance `margin_fill`. Returns an (CH, CW, 3) float32 array."""
    chans = [compose_canvas(rgb[..., k].astype(np.float32), aspect,
                            fit=fit, margin_fill='light')[0] for k in range(3)]
    return np.stack(chans, axis=-1)


def _clampf(v, lo, hi):
    return int(round(max(lo, min(hi, v))))
