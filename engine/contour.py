"""
Isoline extraction using scikit-image Marching Squares.

Takes the scalar field and extracts N evenly-spaced contour levels.
Returns lists of polyline coordinate arrays.
"""

import numpy as np
from skimage import measure


def compute_thresholds(field_min, field_max, n_levels):
    """
    Compute N quadratically-spaced threshold values across the field range.

    Uses quadratic (power=2) spacing to concentrate iso-levels near field_min
    (face/center region) and spread them near field_max (background). This
    matches the reference behavior: dense rings in the face, sparse bands in
    the background. Linear spacing puts ~60% of levels in the background.

    Args:
        field_min: minimum field value
        field_max: maximum field value
        n_levels: number of contour levels

    Returns:
        list of float threshold values, length n_levels
    """
    field_range = field_max - field_min
    fracs = [i / (n_levels + 1) for i in range(1, n_levels + 1)]
    return [field_min + f ** 2.5 * field_range for f in fracs]


def extract_contours(field, n_levels, field_min=None, field_max=None):
    """
    Extract contour polylines from scalar field at N evenly-spaced levels.

    Uses skimage.measure.find_contours which implements Marching Squares.
    Returns connected paths (skimage handles chaining internally).

    Args:
        field: numpy float32 array (H, W)
        n_levels: number of contour levels
        field_min: override field minimum (optional)
        field_max: override field maximum (optional)

    Returns:
        contours: list of dicts, each with:
            'points': numpy array (N, 2) in [row, col] = [y, x] order
            'threshold': float threshold value used
            'normalized_t': float 0–1, position in field range
        stats: dict with paths, total_points, t_range
    """
    fmin = field_min if field_min is not None else float(field.min())
    fmax = field_max if field_max is not None else float(field.max())

    thresholds = compute_thresholds(fmin, fmax, n_levels)
    field_range = fmax - fmin if fmax != fmin else 1.0

    all_contours = []
    total_points = 0

    for t in thresholds:
        paths = measure.find_contours(field, level=t)
        for path in paths:
            if len(path) < 30:
                continue
            normalized = (t - fmin) / field_range
            all_contours.append({
                'points': path,
                'threshold': t,
                'normalized_t': normalized
            })
            total_points += len(path)

    stats = {
        'paths': len(all_contours),
        'total_points': total_points,
        'levels': n_levels,
        't_min': round(fmin, 1),
        't_max': round(fmax, 1),
        'grid': f'{field.shape[1]}x{field.shape[0]}'
    }

    return all_contours, stats
