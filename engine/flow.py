"""
Approach 3: flow-field streamline contours for WAVEFRONT.

A fundamentally different aesthetic from the marching-squares isolines: instead
of slicing a scalar field at thresholds, we build a TANGENT field from the image
gradient (rotate the gradient 90°) and trace evenly-spaced streamlines that flow
ALONG image structure. Dense, fluid, hair-like linework rather than nested rings.

The even spacing uses the Jobard & Lefebvre (1997) method: grow streamlines from
a queue of candidate seeds, stop a line when it comes within d_test of any
already-accepted line, and spawn new seeds offset ±d_sep perpendicular to each
accepted line. A spatial hash makes the proximity test O(1).

trace_flow_lines() returns the SAME contour-dict list shape as
engine.contour.extract_contours (points in [row, col] order, plus
'normalized_t' for stroke weighting), so it feeds straight into the existing
smoothing + SVG export path.
"""

import numpy as np
from scipy.ndimage import gaussian_filter


class _SpatialHash:
    """Bucket grid for fast 'is any accepted point within r of (x,y)?' queries."""

    def __init__(self, cell, w, h):
        self.cell = cell
        self.buckets = {}

    def _key(self, x, y):
        return (int(x / self.cell), int(y / self.cell))

    def add(self, x, y):
        self.buckets.setdefault(self._key(x, y), []).append((x, y))

    def too_close(self, x, y, r):
        r2 = r * r
        cx, cy = self._key(x, y)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for px, py in self.buckets.get((gx, gy), ()):  # noqa: E1133
                    if (x - px) ** 2 + (y - py) ** 2 < r2:
                        return True
        return False


# Directional carrier for the flow field. Pure image-tangent flow curls randomly in
# FLAT regions (e.g. open sky) where the gradient direction is undefined. Blending a
# global carrier direction there makes those regions flow STRAIGHT (long, clean waves
# like the artist's output) while feature regions still follow the image. The ralph
# loop can tune these like the WAVE_*/MARCH_* constants.
FLOW_ANGLE = 20.0      # carrier direction in degrees (0 = horizontal waves)
FLOW_CARRIER = 0.6     # 0 = pure image tangent; 1 = carrier fully dominates flat areas
FLOW_CARRIER_MAG = 6.0 # gradient magnitude at which the image fully overrides the carrier


def _tangent_field(luminance, sigma):
    """Unit tangent field = image gradient rotated 90° (flows along iso-brightness),
    blended with a global carrier direction in flat regions (see FLOW_* constants)."""
    lum = gaussian_filter(luminance.astype(np.float32), sigma=sigma)
    gy, gx = np.gradient(lum)            # gy = d/d(row), gx = d/d(col)
    mag = np.hypot(gx, gy)
    # Tangent perpendicular to gradient, in (x=col, y=row) components.
    tx = -gy
    ty = gx
    norm = np.hypot(tx, ty) + 1e-6
    tx /= norm
    ty /= norm

    # Carrier unit vector.
    ca = np.radians(FLOW_ANGLE)
    cx, cy = float(np.cos(ca)), float(np.sin(ca))
    # Resolve the tangent's 180° ambiguity by flipping it into the carrier's
    # hemisphere, so blending can't cancel two opposite-pointing-but-equal tangents.
    flip = (tx * cx + ty * cy) < 0
    tx = np.where(flip, -tx, tx)
    ty = np.where(flip, -ty, ty)
    # Blend weight w: ~1 where the gradient is strong (follow the image), ->carrier
    # where it's flat. FLOW_CARRIER scales how much the carrier intrudes overall.
    w0 = mag / (mag + FLOW_CARRIER_MAG)
    w = 1.0 - FLOW_CARRIER * (1.0 - w0)
    bx = w * tx + (1.0 - w) * cx
    by = w * ty + (1.0 - w) * cy
    bn = np.hypot(bx, by) + 1e-6
    return (bx / bn).astype(np.float32), (by / bn).astype(np.float32), mag


def _sample(field_x, field_y, x, y):
    """Bilinear sample of the tangent field at float (x, y). Returns (ux, uy)."""
    H, W = field_x.shape
    x0 = int(np.floor(x)); y0 = int(np.floor(y))
    if x0 < 0 or y0 < 0 or x0 >= W - 1 or y0 >= H - 1:
        return None
    fx = x - x0; fy = y - y0
    def bil(f):
        return (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x0 + 1] * fx * (1 - fy)
                + f[y0 + 1, x0] * (1 - fx) * fy + f[y0 + 1, x0 + 1] * fx * fy)
    ux = float(bil(field_x)); uy = float(bil(field_y))
    n = (ux * ux + uy * uy) ** 0.5
    if n < 1e-4:
        return None
    return ux / n, uy / n


def trace_flow_lines(luminance, seed_x, seed_y, n_levels, lum_mix=1.0,
                     sigma=3.0, max_lines=4000):
    """Trace evenly-spaced streamlines through the image tangent field.

    Args:
        luminance: float32 (H, W), 0–255
        seed_x, seed_y: first streamline seed (the UI click point)
        n_levels: density knob (10–150) → mapped to line separation
        lum_mix: gradient-smoothing strength (higher → smoother flow)
        sigma: base blur for the tangent field
    Returns:
        (contours, stats) — same shapes as engine.contour.extract_contours.
    """
    H, W = luminance.shape
    # More smoothing when lum_mix is high → calmer, longer flow lines.
    tx, ty, mag = _tangent_field(luminance, sigma * (0.5 + lum_mix))

    # Density: levels 10→sparse (d_sep~14px), 150→dense (d_sep~2px).
    d_sep = float(np.clip(14.0 - (n_levels - 10) * (12.0 / 140.0), 2.0, 14.0))
    d_test = 0.5 * d_sep
    step = max(0.5, 0.5 * d_sep)        # integration step ~ half separation
    min_len = max(10, int(2 * d_sep / step))   # drop stubs
    max_steps = int(2.0 * (W + H) / step)      # per direction cap

    grid = _SpatialHash(max(d_sep, 1.0), W, H)
    diag = float(np.hypot(W, H))

    def integrate(x0, y0, sign):
        """RK2-integrate from (x0,y0); stop at bounds / flat field / a neighbor line."""
        pts = []
        x, y = x0, y0
        for i in range(max_steps):
            d1 = _sample(tx, ty, x, y)
            if d1 is None:
                break
            mx, my = x + sign * d1[0] * step * 0.5, y + sign * d1[1] * step * 0.5
            d2 = _sample(tx, ty, mx, my)
            if d2 is None:
                break
            nx, ny = x + sign * d2[0] * step, y + sign * d2[1] * step
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                break
            # Don't let the very first steps trip on the seeding line's own points.
            if i > 1 and grid.too_close(nx, ny, d_test):
                break
            x, y = nx, ny
            pts.append((x, y))
        return pts

    lines = []
    queue = [(float(np.clip(seed_x, 1, W - 2)), float(np.clip(seed_y, 1, H - 2)))]
    qi = 0
    while qi < len(queue) and len(lines) < max_lines:
        sx, sy = queue[qi]; qi += 1
        if grid.too_close(sx, sy, d_test):
            continue
        fwd = integrate(sx, sy, +1.0)
        bwd = integrate(sx, sy, -1.0)
        line = list(reversed(bwd)) + [(sx, sy)] + fwd
        if len(line) < min_len:
            continue
        for (px, py) in line:
            grid.add(px, py)
        lines.append(line)
        # Spawn candidate seeds offset ±d_sep perpendicular to the line.
        for k in range(0, len(line), max(1, int(d_sep / step))):
            px, py = line[k]
            d = _sample(tx, ty, px, py)
            if d is None:
                continue
            nx_, ny_ = -d[1], d[0]   # perpendicular
            queue.append((px + nx_ * d_sep, py + ny_ * d_sep))
            queue.append((px - nx_ * d_sep, py - ny_ * d_sep))

    contours = []
    total_points = 0
    for line in lines:
        arr = np.array([(y, x) for (x, y) in line], dtype=np.float32)  # [row,col]
        # Depth cue: lines near the seed are "closer" → thicker (low normalized_t).
        cx = arr[:, 1].mean(); cy = arr[:, 0].mean()
        nt = float(np.clip(np.hypot(cx - seed_x, cy - seed_y) / (0.5 * diag), 0.0, 1.0))
        contours.append({'points': arr, 'threshold': nt, 'normalized_t': nt})
        total_points += len(arr)

    stats = {
        'paths': len(contours),
        'total_points': total_points,
        'segments': max(total_points - len(contours), 0),
        'levels': n_levels,
        't_min': 0.0,
        't_max': round(d_sep, 1),
        'grid': f'{W}x{H}',
    }
    return contours, stats
