"""
Isoline extraction using scikit-image Marching Squares.

Takes the scalar field and extracts N power-spaced contour levels.
Returns lists of polyline coordinate arrays.
"""

import numpy as np
from skimage import measure


# Level-spacing exponent (ralph loop tunes this). 1.0 = LINEAR = even spacing —
# confirmed: CONTOUR-V STUDIO's SPACING control reads "Linear". The old 2.7
# concentrated ~77% of levels near the seed, over-densifying the face.
THRESHOLD_POWER = 1.0

# Keep tiny closed loops: CONTOUR-V STUDIO filters at MIN PTS 4. The previous 30
# silently dropped the small concentric loops around dark features (eyes, brows),
# which are exactly what makes darks render as solid ink (652 paths in the CORE
# reference capture vs 267 in ours before this change).
MIN_PATH_POINTS = 4

# Clip the top of the field range before spacing levels (CONTOUR-V STUDIO
# "T-MAX %", default 99.50): the farthest fraction of arrival times is outlier
# tail (slow corners), and spending levels there starves the subject.
TMAX_CLIP_PCT = 99.5


def compute_thresholds(field_min, field_max, n_levels):
    """
    Compute N power-spaced threshold values across the field range.

    THRESHOLD_POWER controls the distribution: 1.0 is linear (even line spacing,
    like the reference); >1 concentrates levels near field_min (denser face).

    Args:
        field_min: minimum field value
        field_max: maximum field value
        n_levels: number of contour levels

    Returns:
        list of float threshold values, length n_levels
    """
    field_range = field_max - field_min
    fracs = [i / (n_levels + 1) for i in range(1, n_levels + 1)]
    return [field_min + f ** THRESHOLD_POWER * field_range for f in fracs]


def extract_contours(field, n_levels, field_min=None, field_max=None):
    """
    Extract contour polylines from scalar field at N power-spaced levels.

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
    if TMAX_CLIP_PCT < 100.0:
        fmax = min(fmax, float(np.percentile(field, TMAX_CLIP_PCT)))

    thresholds = compute_thresholds(fmin, fmax, n_levels)
    field_range = fmax - fmin if fmax != fmin else 1.0

    all_contours = []
    total_points = 0

    for t in thresholds:
        paths = measure.find_contours(field, level=t)
        for path in paths:
            if len(path) < MIN_PATH_POINTS:
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
        'segments': max(total_points - len(all_contours), 0),
        'levels': n_levels,
        't_min': round(fmin, 1),
        't_max': round(fmax, 1),
        'grid': f'{field.shape[1]}x{field.shape[0]}'
    }

    return all_contours, stats


def scale_contours(contours, from_size, to_size):
    """
    Scale contour coordinates from one image size to another.

    Contour points are stored as [row, col] = [y, x]. Sizes are (width, height).
    """
    from_w, from_h = from_size
    to_w, to_h = to_size
    if from_w <= 0 or from_h <= 0:
        raise ValueError('from_size dimensions must be positive')

    scale_x = to_w / from_w
    scale_y = to_h / from_h
    if scale_x == 1 and scale_y == 1:
        return contours

    scaled = []
    for contour in contours:
        points = contour['points'].astype(np.float32, copy=True)
        points[:, 0] *= scale_y
        points[:, 1] *= scale_x
        scaled.append({
            **contour,
            'points': points
        })

    return scaled


def clip_contours_to_mask(contours, mask, **tags):
    """Split each contour into the maximal runs of points where `mask` is True,
    emitting one new contour dict per run (runs shorter than 2 points are dropped).

    `mask` is a boolean (H, W) grid; points are sampled by their integer [row, col].
    Each emitted dict inherits `threshold`/`normalized_t` from its source and is
    annotated with any `**tags` (e.g. layer=i, or hatch=True). Shared by the
    crosshatch dark-region clip and the color channel-separation clip."""
    H, W = mask.shape
    out = []
    for c in contours:
        pts = c['points']
        rr = np.clip(pts[:, 0].astype(np.int32), 0, H - 1)
        cc = np.clip(pts[:, 1].astype(np.int32), 0, W - 1)
        keep = mask[rr, cc]
        run = []
        for i, k in enumerate(keep):
            if k:
                run.append(pts[i])
            else:
                if len(run) >= 2:
                    out.append({'points': np.asarray(run, dtype=np.float32),
                                'threshold': c.get('threshold', 1.0),
                                'normalized_t': c.get('normalized_t', 0.5),
                                **tags})
                run = []
        if len(run) >= 2:
            out.append({'points': np.asarray(run, dtype=np.float32),
                        'threshold': c.get('threshold', 1.0),
                        'normalized_t': c.get('normalized_t', 0.5),
                        **tags})
    return out
