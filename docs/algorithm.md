# WAVEFRONT Algorithm Documentation

This documents the **active `method=wave` path** (`engine.field.build_wave_field`),
the L1-diamond field WAVEFRONT now uses to replicate CONTOUR-V CORE. See
`contour-v-core-source.md` for the replication target. The shared pipeline
(preprocess → extract → smooth → scale → export) is the same for every method;
only field construction (Step 3) differs. `method=contour` (`build_field`, the
simpler uniform formula) and `method=flow` (`engine.flow`) are **parked
baselines/experiments** — summarized at the end, not the canonical path.

> **History note.** Earlier versions used an *adaptive / zoned* luminance blur
> that imposed a circular "ring" at ~20–35% radius, plus a steep
> `THRESHOLD_POWER` (~2.7) that crammed most levels near the seed. Both were
> **bugs** — the target's field has near-even line spacing and no circular zone.
> They were removed. Ignore any lingering references to adaptive blur.

## Pipeline Overview

  Image -> processing resize + original size retained -> luminance
  -> uniform preprocessing (denoise + shadow-lift) -> scalar field
  -> Marching Squares paths -> Chaikin smoothing
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

## Step 2: Adaptive Luminance Blur (zoned by seed distance)

  The wave field blurs luminance differently near vs. far from the seed — light
  blur near the face preserves feature wrap, heavy blur in the background kills
  hair/texture. All constants live in `engine/field.py`:

    L_light = gaussian_filter(L, sigma=WAVE_SIGMA_FACE)   # default 8.0
    L_heavy = gaussian_filter(L, sigma=WAVE_SIGMA_BG)     # default 30.0

    dist    = sqrt((x-sx)^2 + (y-sy)^2)
    inner   = WAVE_INNER * min(W, H)      # default 0.10
    outer   = WAVE_OUTER * min(W, H)      # default 0.90
    dw      = clamp((dist - inner) / (outer - inner), 0, 1)   # 0=face .. 1=bg
    L_blend = (1 - dw) * L_light + dw * L_heavy

  IMPORTANT — keep the zone WIDE. `inner`/`outer` are set so the fade spans from
  near the seed to *past the image corners* (corner dist ≈ 0.71·min(W,H) for a
  centered seed, well inside outer=0.90). A narrow zone (the old 0.20/0.42) made
  the relief fall off across a visible circle — the "limited circle vs uniform"
  artifact. Widening it (plus a non-trivial `WAVE_FAR`, Step 3) dissolves that
  boundary into a smooth, near-uniform gradient.

## Step 3: Wave / L1-Diamond Field Construction (active — `build_wave_field`)

  The signature CONTOUR-V geometry: a Manhattan (L1) distance base that dominates
  the gradient — giving crisp concentric **diamonds** that stay topologically
  intact everywhere — plus a GENTLE luminance relief so the diamonds ripple
  around features without breaking into closed loops.

    l1      = abs(x - sx) + abs(y - sy)              # L1 diamond base (px)
    relief_w= (1 - dw) * 1.0 + dw * WAVE_FAR         # fade relief into the bg
    ripple  = (255 - L_blend) * WAVE_RELIEF * lum_mix * (1 - WAVE_DIAMOND) * relief_w
    field[y,x] = l1 + ripple

  Manhattan (L1) distance — NOT Euclidean — is what produces the diamonds
  (Euclidean would give circles; older notes that hypothesize `sqrt(...)` for the
  base are superseded). Knobs and their effect:
  - `WAVE_DIAMOND` (0–1): biases toward pure crisp diamonds; 1 ignores the face.
  - `WAVE_RELIEF`: luminance ripple amplitude — low keeps diamonds dominant.
  - `WAVE_FAR`: far-field ripple multiplier — low gives clean background diamonds.
  - `WAVE_SIGMA_FACE` / `WAVE_SIGMA_BG`, `WAVE_INNER` / `WAVE_OUTER`: see Step 2.
  - `lum_mix` (clamped 0–2 by the API) scales the relief; the loop renders at 0.8.

  Because the L1 base dominates and the relief is bounded + suppressed far from
  the seed, rings stay continuous and the page stays light and even — the target
  look (vs. `build_field`, whose full-strength uniform warp over-densifies the
  face into a smudge; see the baselines note below).

## Step 4: Isoline Extraction

  For N levels, compute power-spaced thresholds (`THRESHOLD_POWER` in
  `engine/contour.py`, currently ~1.3; the ralph loop tunes it):

    frac[i] = i / (N + 1), for i in 1..N
    threshold[i] = field_min + frac[i]^THRESHOLD_POWER * (field_max - field_min)

  THRESHOLD_POWER = 1.0 is linear = even line spacing, which matches the
  reference's near-uniform density. Values >1 concentrate levels near the seed
  (denser face). The old 2.7 put ~77% of levels near the seed and over-densified
  the face — it was tuned down toward linear to match the target.

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
| method | contour/wave/flow | contour | API default; the **ralph loop renders `wave`**. |
| diamond | 0-1 | 0.0 | `wave` only — maps to `WAVE_DIAMOND` if sent. |

## Parked baselines (not the active path)

Two other field methods exist behind `method=`; they share Steps 1, 4–7 and only
swap Step 3. They are not actively tuned — left for comparison/experiment.

- **`method=contour` (`build_field`)** — the simpler reverse-engineered formula,
  applied UNIFORMLY: `field = (|x-sx|+|y-sy|) + (255 - L_pre)·lum_mix`, where
  `L_pre` is luminance after a uniform Gaussian denoise (`FIELD_DENOISE_SIGMA`)
  and shadow-lift (`FIELD_SHADOW_LIFT`). Correct diamonds, but the full-strength
  uniform warp tends to over-densify the face into a smudge — which is why the
  wave field (bounded, seed-faded relief) became the active method.
- **`method=flow` (`engine/flow.py`)** — evenly-spaced gradient streamlines
  (Jobard & Lefebvre); a fundamentally different, hair-like aesthetic.

Malformed numeric values return HTTP 400. Out-of-range numeric values are
clamped to the ranges above.
