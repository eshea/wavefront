"""
Polyline post-processing: arclength resampling (CONTOUR-V STUDIO "STEP") and
Chaikin corner-cutting smoothing.

Resampling runs first: raw Marching Squares emits a point roughly every grid
pixel, and that sub-pixel stairstep noise is what makes unsmoothed output look
jittery. Re-walking each path at a fixed step (STUDIO shows STEP 3.00 px)
straightens the micro-noise while keeping real corners — the reference's
"angular but clean" look at LINE SMOOTH 0 — and cuts point count ~70%.
Chaikin then subdivides: each iteration replaces adjacent point pairs with new
points at the 1/4 and 3/4 positions.
"""

import numpy as np


# Resample step in processing-grid pixels (CONTOUR-V STUDIO: STEP 3.00 px).
RESAMPLE_STEP = 3.0


def resample_polyline(points, step):
    """
    Resample a polyline at a uniform arclength step.

    Endpoints are preserved exactly (closed paths stay closed). Paths shorter
    than one step collapse to their endpoints; tiny closed loops keep at least
    4 interior samples so dark-feature "dots" survive (STUDIO keeps MIN PTS 4).

    Args:
        points: numpy array (N, 2) — polyline coordinates
        step: float, target spacing in grid pixels

    Returns:
        numpy array (M, 2) — resampled polyline
    """
    n = len(points)
    if n < 3 or step <= 0:
        return points

    pts = points.astype(np.float32)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arclen = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(arclen[-1])
    closed = bool(np.allclose(pts[0], pts[-1]))
    if total <= step and not closed:
        return pts[[0, -1]]

    # Tiny closed loops keep >= 4 samples so dark-feature "dots" survive.
    n_samples = max(int(round(total / step)) + 1, 4 if closed else 2)
    targets = np.linspace(0.0, total, n_samples)
    out = np.empty((n_samples, 2), dtype=np.float32)
    out[:, 0] = np.interp(targets, arclen, pts[:, 0])
    out[:, 1] = np.interp(targets, arclen, pts[:, 1])
    # Exact endpoints (and exact closure for closed paths).
    out[0] = pts[0]
    out[-1] = pts[-1]
    return out


def resample_contours(contours, step=None):
    """
    Apply fixed-step arclength resampling to all contour paths.

    Args:
        contours: list of dicts from extract_contours()
        step: float, grid-pixel spacing (default RESAMPLE_STEP)

    Returns:
        list of dicts with resampled 'points' arrays
    """
    step = RESAMPLE_STEP if step is None else float(step)
    if step <= 0:
        return contours
    return [{**c, 'points': resample_polyline(c['points'], step)} for c in contours]


def rdp_polyline(points, epsilon):
    """
    Ramer–Douglas–Peucker decimation: drop interior points that lie within
    `epsilon` (grid px) of the chord between their kept neighbours, preserving
    overall shape and the exact endpoints. This is the point-budget lever for
    large prints — Chaikin adds points on near-straight runs that a plotter and
    vector editor don't need; RDP removes them without visible change.

    Iterative (explicit stack) so a huge mural path can't blow the recursion
    limit. epsilon <= 0 or paths shorter than 3 points are returned unchanged.

    Args:
        points: numpy array (N, 2) — polyline coordinates [row, col]
        epsilon: float, max perpendicular deviation in grid px

    Returns:
        numpy array (M, 2) — decimated polyline (M <= N)
    """
    n = len(points)
    if epsilon <= 0 or n < 3:
        return points

    pts = points.astype(np.float32)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    eps2 = float(epsilon) * float(epsilon)
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a, b = pts[i0], pts[i1]
        ab = b - a
        seg2 = float(ab[0] * ab[0] + ab[1] * ab[1])
        rel = pts[i0 + 1:i1] - a
        if seg2 <= 1e-12:
            # Degenerate chord (closed loop start==end): use distance to point a.
            d2 = rel[:, 0] ** 2 + rel[:, 1] ** 2
        else:
            cross = rel[:, 0] * ab[1] - rel[:, 1] * ab[0]
            d2 = (cross * cross) / seg2
        k = int(np.argmax(d2))
        if float(d2[k]) > eps2:
            idx = i0 + 1 + k
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))
    return pts[keep]


def decimate_contours(contours, epsilon):
    """
    RDP-decimate every contour path by `epsilon` grid px. epsilon <= 0 is a
    no-op (returns the input list unchanged), so the default pipeline is byte
    stable; callers opt in for big prints via a physical simplify tolerance.
    """
    if not epsilon or epsilon <= 0:
        return contours
    return [{**c, 'points': rdp_polyline(c['points'], epsilon)} for c in contours]


def chaikin(points, iterations):
    """
    Apply Chaikin corner-cutting algorithm to a polyline.

    Each iteration doubles the point count and smooths corners.
    After k iterations, point count ≈ 2^k * original.

    Args:
        points: numpy array (N, 2) — polyline coordinates
        iterations: int, number of subdivision passes (0–4 typical)

    Returns:
        numpy array (M, 2) — smoothed polyline
    """
    if iterations == 0 or len(points) < 3:
        return points

    pts = points.copy()

    for _ in range(iterations):
        n = len(pts)
        if n < 2:
            break

        p0 = pts[:-1]
        p1 = pts[1:]

        q = 0.75 * p0 + 0.25 * p1
        r = 0.25 * p0 + 0.75 * p1

        new_pts = np.empty((2 * (n - 1), 2), dtype=np.float32)
        new_pts[0::2] = q
        new_pts[1::2] = r

        # Preserve exact endpoints to avoid drift
        new_pts = np.vstack([pts[0:1], new_pts, pts[-1:]])
        pts = new_pts

    return pts


def smooth_param_to_iterations(smooth):
    """
    Map smooth parameter [0,1] to Chaikin iteration count [0,4].

    smooth=0.00 → 0 iterations (raw)
    smooth=0.25 → 1 iteration
    smooth=0.50 → 2 iterations
    smooth=0.70 → 3 iterations (VEX ENGINE default)
    smooth=1.00 → 4 iterations
    """
    return round(float(smooth) * 4)


def smooth_contours(contours, smooth_param):
    """
    Apply Chaikin smoothing to all contour paths.

    Args:
        contours: list of dicts from extract_contours()
        smooth_param: float 0–1

    Returns:
        list of dicts with smoothed 'points' arrays
    """
    iterations = smooth_param_to_iterations(smooth_param)

    if iterations == 0:
        return contours

    smoothed = []
    for c in contours:
        pts = c['points'].astype(np.float32)
        smoothed_pts = chaikin(pts, iterations)
        smoothed.append({
            **c,
            'points': smoothed_pts
        })

    return smoothed
