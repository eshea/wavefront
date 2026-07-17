"""Crosshatch second-direction depth layer (opt-in).

A single diamond direction can only get so dark before its lines pile into a
muddy blob — the artist's own stated failure mode for deep shadows. Real pen
crosshatching adds a SECOND set of lines, running across the first, in the dark
regions only: the darks deepen toward solid ink while the lines stay legible
instead of smearing.

`crosshatch_pass` builds a rotated diamond field (so its isolines cross the
primary ones — `engine.field.build_rotated_field`), extracts + resamples its
contours, then `mask_dark` clips them to the pixels below a darkness threshold.
The result is a list of extra contour dicts (tagged `hatch=True`) that extend the
primary contour list and flow through the identical downstream smooth → optimize →
color → scale → export path. Off (no `crosshatch`, or threshold/levels at 0) ⇒
returns `[]`, so the default output is unchanged."""

import numpy as np

from engine.field import build_rotated_field
from engine.contour import extract_contours, clip_contours_to_mask
from engine.smooth import resample_contours


def mask_dark(contours, gray, threshold):
    """Clip each contour to the runs of points where `gray < threshold`, splitting
    a path wherever it leaves the dark region. `gray` is the processing-grid
    luminance in 0–1 (dark = low). Runs shorter than 2 points are dropped."""
    if threshold <= 0:
        return []
    return clip_contours_to_mask(contours, gray < threshold, hatch=True)


def crosshatch_pass(luminance, seed_x, seed_y, levels, lum_mix=1.0,
                    *, threshold=0.0, angle=45.0):
    """Build the dark-region crosshatch overlay for one render. Returns a list of
    extra contour dicts to concatenate onto the primary contours, or `[]` when off
    (levels<=0 or threshold<=0)."""
    if levels <= 0 or threshold <= 0:
        return []
    field, f_min, f_max = build_rotated_field(luminance, seed_x, seed_y,
                                              lum_mix, angle)
    contours, _ = extract_contours(field, levels, f_min, f_max)
    contours = resample_contours(contours)
    gray = (luminance / 255.0).astype(np.float32)
    return mask_dark(contours, gray, threshold)
