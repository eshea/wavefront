# WAVEFRONT Algorithm Documentation

## Pipeline Overview

  Image -> processing resize + original size retained -> luminance -> adaptive blur
  -> scalar field -> Marching Squares paths -> Chaikin smoothing
  -> original-size coordinate scaling -> SVG

## Step 1: Image Preprocessing

  Input: RGB image (any size)

  1. Record the original upload dimensions.

  2. Resize a processing copy to max 640px on the longest side.
     - Aspect ratio is preserved.
     - The capped grid keeps contour extraction fast.
     - Original dimensions are retained for final SVG export.

  3. Convert the processing copy to luminance:
     L[y,x] = 0.299 * R + 0.587 * G + 0.114 * B
     (ITU-R BT.601 standard)

## Step 2: Adaptive Luminance Blur

  Two blurred luminance maps are built:

    L_light = gaussian_filter(L, sigma=8)
    L_heavy = gaussian_filter(L, sigma=30)

  A distance blend chooses how much of each blur to use:

    dist_to_seed = sqrt((x - sx)^2 + (y - sy)^2)
    inner_r = 0.20 * min(width, height)
    outer_r = 0.35 * min(width, height)
    dist_weight = clamp((dist_to_seed - inner_r) / (outer_r - inner_r), 0, 1)

    L_blur = (1 - dist_weight) * L_light + dist_weight * L_heavy

  Near the seed, lighter blur preserves facial features. Farther away, heavier
  blur suppresses hair/background texture so contours remain open and flowing.

## Step 3: Scalar Field Construction

  The base field uses Manhattan distance, which produces diamond/ring geometry:

    dist_field = abs(x - sx) + abs(y - sy)

  The luminance contribution is reduced away from the seed:

    effective_lum_mix = lum_mix * ((1 - dist_weight) * 1.0 + dist_weight * 0.70)
    lum_field = (255 - L_blur) * effective_lum_mix

  Final field:

    field[y,x] = dist_field + lum_field

  Properties:
  - Dark pixels raise the field and pull isolines tighter.
  - Bright pixels add little or no luminance warp.
  - Far-field texture still affects the lines, but at lower strength.
  - `lum_mix` is clamped to 0-2 by the Flask API and UI.

## Step 4: Isoline Extraction

  For N levels, compute power-spaced thresholds:

    frac[i] = i / (N + 1), for i in 1..N
    threshold[i] = field_min + frac[i]^2.7 * (field_max - field_min)

  Power spacing concentrates more contours near low field values around the
  seed and leaves fewer levels in the far background. This matches the desired
  dense-face / sparse-background distribution better than linear spacing.

  Each threshold is passed to:

    skimage.measure.find_contours(field, level=threshold)

  `find_contours` implements Marching Squares and already returns connected
  polylines. WAVEFRONT filters out very short paths (`len(path) < 30`) but does
  not run a custom chain-linking pass.

## Step 5: Chaikin Smoothing

  Chaikin's corner-cutting algorithm is applied iteratively:

    Q = 0.75 * P0 + 0.25 * P1
    R = 0.25 * P0 + 0.75 * P1

  Number of iterations:
  - smooth=0.00 -> 0 iterations
  - smooth=0.25 -> 1 iteration
  - smooth=0.50 -> 2 iterations
  - smooth=0.70 -> 3 iterations
  - smooth=1.00 -> 4 iterations

  `smooth` is clamped to 0-1 by the Flask API and UI.

## Step 6: Adaptive Stroke Weight

  Lines closer to low field values are drawn thicker and darker.

    normalized_t = (threshold - field_min) / (field_max - field_min)

    stroke_width = max(0.2,  1.4 - normalized_t * wt_range * 1.2)
    stroke_alpha = max(0.35, 0.95 - normalized_t * 0.4)

  This gives:
  - Near seed: width about 1.4px, alpha about 0.95
  - Far field: width down to 0.2px, alpha down to 0.35
  - wt_range=0: flat 1.4px width
  - wt_range=1: full width variation

  `wt_range` is clamped to 0-1 by the Flask API and UI.

## Step 7: SVG Export

  Contours are extracted on the capped processing grid, then scaled back to the
  original uploaded image dimensions before SVG generation:

    x_original = x_processed * original_width / processed_width
    y_original = y_processed * original_height / processed_height

  Output SVG:
  - width/height and viewBox match the original upload dimensions.
  - A white background rect is emitted.
  - One `<path>` element is emitted per connected contour.
  - Path coordinates use `M x0,y0 L x1,y1 ...`.
  - Strokes use round caps and joins.

## API Parameter Ranges

| Parameter | Range | Default | Notes |
|-----------|-------|---------|-------|
| levels | 10-150 | 63 | Number of power-spaced threshold levels. |
| smooth | 0-1 | 0.70 | Mapped to 0-4 Chaikin iterations. |
| lum_mix | 0-2 | 1.0 | Strength of luminance warping. |
| wt_range | 0-1 | 0.6 | Stroke width variation. |
| seed_x/seed_y | processing-grid pixels | center | UI seeds are in the resized preview grid. |

Malformed numeric values return HTTP 400. Out-of-range numeric values are
clamped to the ranges above.
