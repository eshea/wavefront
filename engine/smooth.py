"""
Chaikin corner-cutting smoothing algorithm.

Repeatedly subdivides polylines by replacing each pair of adjacent points
with two new points at the 1/4 and 3/4 positions. Produces smooth curves
from angular marching-squares output.
"""

import numpy as np


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
