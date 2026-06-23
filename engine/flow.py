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
FLOW_SIGMA = 3.0       # base blur for the tangent field (higher => smoother, longer lines)
FLOW_TONE_DENSITY = 0.6  # darkness -> tighter line spacing (denser lines in dark regions,
                         # e.g. the visor). 0 = even spacing everywhere; 0.6 packs darks
                         # to ~40% of the base separation. The artist's output is dense
                         # in shadow and sparse in highlight — this reproduces that.

# Edge-Tangent-Flow (ETF) coherence smoothing — Kang, Lee & Chui (2007),
# "Coherent Line Drawing". The raw rotated-gradient tangent is noisy ("hair-like");
# ETF iteratively realigns each tangent toward neighbours that are spatially near,
# carry STRONGER edges, and already point a similar way, turning the field into
# clean, coherent streamlines. FLOW_ETF=0 (default) skips it entirely → the parked
# flow output is byte-identical to before; >0 blends the smoothed field in.
FLOW_ETF = 0.0          # 0 = off (identity); 1 = fully replace with the ETF-smoothed field
FLOW_ETF_RADIUS = 3.0   # neighbourhood radius in px for the coherence kernel
FLOW_ETF_ITERS = 2.0    # refinement passes (rounded to int; 0 = identity)


def _shift_clamp(a, dx, dy):
    """Edge-clamped shift: returns S with S[y, x] = a[y+dy, x+dx] (no wrap-around).
    Used to gather neighbour values for the vectorised ETF kernel."""
    H, W = a.shape
    ys = np.clip(np.arange(H) + dy, 0, H - 1)
    xs = np.clip(np.arange(W) + dx, 0, W - 1)
    return a[np.ix_(ys, xs)]


def etf_smooth(tx, ty, mag, radius, iters):
    """Edge-Tangent-Flow coherence smoothing of a unit tangent field.

    Per Kang et al., the refined tangent at x is the normalised sum over a disc
    neighbourhood of  φ·w_m·w_d·t(y),  where
        φ   = sign(t(x)·t(y))            resolves the 180° tangent ambiguity,
        w_d = |t(x)·t(y)|                weights aligned neighbours,
        w_m = ½(1 + tanh(ĝ(y) − ĝ(x)))   weights neighbours on stronger edges,
    and the spatial weight is a box disc of the given radius (w_s ∈ {0,1}). ĝ is the
    fixed normalised gradient magnitude; only the tangent updates between passes.

    Returns a new (tx, ty) unit field. iters<1 or radius<1 → returns the input.
    """
    radius = int(round(float(radius)))
    iters = int(round(float(iters)))
    if iters < 1 or radius < 1:
        return tx, ty
    mmax = float(mag.max())
    ghat = (mag / mmax).astype(np.float32) if mmax > 1e-8 else np.zeros_like(mag)
    # Disc of integer offsets within the radius (deterministic order).
    offsets = [(dx, dy)
               for dy in range(-radius, radius + 1)
               for dx in range(-radius, radius + 1)
               if dx * dx + dy * dy <= radius * radius and not (dx == 0 and dy == 0)]
    cx, cy = tx.astype(np.float32), ty.astype(np.float32)
    for _ in range(iters):
        ax = np.zeros_like(cx)
        ay = np.zeros_like(cy)
        for dx, dy in offsets:
            nbx = _shift_clamp(cx, dx, dy)
            nby = _shift_clamp(cy, dx, dy)
            ng = _shift_clamp(ghat, dx, dy)
            dot = cx * nbx + cy * nby           # t(x)·t(y)
            wm = 0.5 * (1.0 + np.tanh(ng - ghat))   # stronger edge dominates
            wgt = np.sign(dot) * np.abs(dot) * wm   # φ·w_d·w_m  (w_s=1 inside disc)
            ax += wgt * nbx
            ay += wgt * nby
        n = np.hypot(ax, ay) + 1e-8
        cx = (ax / n).astype(np.float32)
        cy = (ay / n).astype(np.float32)
    return cx, cy


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

    # Edge-Tangent-Flow coherence smoothing (opt-in). FLOW_ETF=0 (default) skips
    # this entirely so the parked flow output is unchanged; >0 blends in the
    # ETF-smoothed field (sign-aligned to avoid 180°-ambiguity cancellation).
    if FLOW_ETF > 0:
        etx, ety = etf_smooth(tx, ty, mag, FLOW_ETF_RADIUS, FLOW_ETF_ITERS)
        sign = np.sign(tx * etx + ty * ety)
        sign[sign == 0] = 1.0
        etx *= sign
        ety *= sign
        f = float(FLOW_ETF)
        tx = (1.0 - f) * tx + f * etx
        ty = (1.0 - f) * ty + f * ety
        en = np.hypot(tx, ty) + 1e-6
        tx /= en
        ty /= en

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
                     sigma=None, max_lines=4000):
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
    if sigma is None:
        sigma = FLOW_SIGMA
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

    # Tone-modulated spacing: tighter line separation in dark regions so shadows
    # (the visor) pack denser, like the artist's output. The spatial hash keeps the
    # base (largest) cell size; only the proximity radius / seed offset shrink.
    dark = 1.0 - np.clip(gaussian_filter(luminance, sigma=max(2.0, sigma)) / 255.0, 0.0, 1.0)

    def sep_at(x, y):
        xi = int(x) if 0 <= x < W else int(np.clip(x, 0, W - 1))
        yi = int(y) if 0 <= y < H else int(np.clip(y, 0, H - 1))
        return max(1.5, d_sep * (1.0 - FLOW_TONE_DENSITY * float(dark[yi, xi])))

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
            if i > 1 and grid.too_close(nx, ny, 0.5 * sep_at(nx, ny)):
                break
            x, y = nx, ny
            pts.append((x, y))
        return pts

    lines = []
    queue = [(float(np.clip(seed_x, 1, W - 2)), float(np.clip(seed_y, 1, H - 2)))]
    qi = 0
    while qi < len(queue) and len(lines) < max_lines:
        sx, sy = queue[qi]; qi += 1
        if grid.too_close(sx, sy, 0.5 * sep_at(sx, sy)):
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
            s = sep_at(px, py)       # tone-local separation -> denser seeds in shadow
            queue.append((px + nx_ * s, py + ny_ * s))
            queue.append((px - nx_ * s, py - ny_ * s))

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
