# WAVEFRONT Algorithm Documentation

The **active path is now `method=march`** (`engine.march.build_march_field`): a
4-connected **fast-marching arrival-time field** with a **reciprocal** cost —
`speed = clip(gray, MARCH_FLOOR, 1)`, `cost = MARCH_BASE + lum_mix·(1/speed − 1)
+ MARCH_EDGE·edge` — the confirmed CONTOUR-V model (the STUDIO screenshot's own
subtitle is "Fast marching contour field"; see `contour-v-core-source.md`).
Since isoline spacing = level spacing ÷ cost, the reciprocal shape gives a
gentle halftone through whites and midtones while deep darks saturate to solid
ink — **tone-driven density that renders the image's tones** — and
4-connectivity keeps the L1 **diamond** topology. This replaced first the
additive `method=wave` field (Steps 2–3 below, now a **parked baseline**, which
could only make density seed-centric: `d_tone`≈0) and then the linear
`MARCH_TONE·dark` cost (which starved whites and muddied mids by the time darks
saturated). The shared pipeline (preprocess → extract → resample → smooth →
scale → export) is the same for every method; only field construction differs.
`method=wave/contour/flow` are parked baselines — documented below and at the
end, not the canonical path.

> **History note.** Earlier versions used an *adaptive / zoned* luminance blur
> that imposed a circular "ring" at ~20–35% radius, plus a steep
> `THRESHOLD_POWER` (~2.7) that crammed most levels near the seed. Both were
> **bugs** — the target's field has near-even line spacing and no circular zone.
> They were removed. Ignore any lingering references to adaptive blur.

## Pipeline Overview

  Image -> processing resize + original size retained -> luminance
  -> uniform preprocessing (denoise + shadow-lift) -> scalar field
  -> Marching Squares paths -> fixed-step resample -> Chaikin smoothing
  -> original-size coordinate scaling -> SVG

## Step 1: Image Preprocessing

  Input: RGB image (any size)

  1. Record the original upload dimensions.

  2. Resize a processing copy to a capped longest side (`MAX_DIM` = 800 by
     default; a request may raise it via `detail_px` for large prints — see
     "Mural extensions" below).
     - Aspect ratio is preserved.
     - The capped grid keeps contour extraction fast.
     - Original dimensions are retained for final SVG export.

  3. Convert the processing copy to luminance:
     L[y,x] = 0.299 * R + 0.587 * G + 0.114 * B
     (ITU-R BT.601 standard)

  4. Tonal pre-shaping (`shape_tone`, CONTOUR-V STUDIO "Input & Tonal Control").
     Applied to luminance before the field, so it shapes WHICH tones get contour
     density. Identity at defaults (existing renders unchanged). Constants in
     `engine/field.py`, applied to `wave` and `contour`:

       L = contrast_about_mid(L, TONE_CONTRAST)   # >1 sharper light/dark
       L = L ** TONE_GAMMA                         # <1 lifts shadows (de-clumps
                                                   #   over-dense dark regions)
       if TONE_INVERT >= 0.5: L = 255 - L          # dark-first (portraits)

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

  The field range is first clipped at the top (`TMAX_CLIP_PCT` in
  `engine/contour.py`, 99.5 — CONTOUR-V STUDIO's "T-MAX %"): the farthest
  fraction of arrival times is outlier tail and spending levels there starves
  the subject. Then, for N levels, compute power-spaced thresholds
  (`THRESHOLD_POWER`, currently 1.0 = linear; the ralph loop tunes it):

    frac[i] = i / (N + 1), for i in 1..N
    threshold[i] = field_min + frac[i]^THRESHOLD_POWER * (field_max - field_min)

  THRESHOLD_POWER = 1.0 is linear = even line spacing — confirmed by STUDIO's
  SPACING control reading "Linear". Values >1 concentrate levels near the seed
  (denser face). The old 2.7 put ~77% of levels near the seed and over-densified
  the face.

  Each threshold is passed to:

    skimage.measure.find_contours(field, level=threshold)

  `find_contours` implements Marching Squares and already returns connected
  polylines. Very short paths (`len(path) < MIN_PATH_POINTS`, 4 — STUDIO's
  "MIN PTS 4") are dropped; no custom chain-linking pass. Keeping tiny closed
  loops matters: they are the concentric "dots" piled around small dark features
  (eyes, brows) that make darks render as solid ink — the old filter of 30
  silently deleted them.

## Step 4b: Fixed-Step Resampling (STUDIO "STEP")

  Raw Marching Squares emits a point roughly every grid pixel; that sub-pixel
  stairstep noise is what made unsmoothed output look jittery. Each path is
  re-walked at a uniform arclength step (`RESAMPLE_STEP` in `engine/smooth.py`,
  3.0 px — STUDIO shows STEP 3.00 px) before smoothing: micro-noise straightens
  out, real corners stay, point count drops ~70%. Endpoints are preserved
  exactly (closed paths stay closed; tiny closed loops keep ≥4 samples).

## Step 4c: Crosshatch second-direction depth (opt-in — `engine/crosshatch.py`)

A single diamond direction can only get so dark before its lines pile into a muddy
blob — the artist's own stated failure mode for deep shadows. Opt-in crosshatching
adds a SECOND set of lines that cross the first, **in the dark regions only**, so
shadows deepen toward solid ink while the lines stay legible:

  1. `build_rotated_field` builds a diamond field with its L1 axes rotated by
     `hatch_angle` (default 45°) about the seed, so its isolines run across the
     primary ones.
  2. `extract_contours` + `resample_contours` at `hatch_levels` produce that second
     line set, run inside `_apply_knobs` so it shares the tone knobs.
  3. `mask_dark` clips each line to the runs of points where `luminance/255 <
     hatch_threshold`, splitting a path wherever it leaves the dark region.

The survivors (tagged `hatch=True`) extend the primary contour list and flow
through the identical smooth → optimize → color → scale → export path. Off
(`crosshatch` absent, or `hatch_levels`/`hatch_threshold` at 0) ⇒ no extra lines,
output unchanged.

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

## Step 6: Stroke (constant ink by default; modulation opt-in)

  Default (`wt_range = 0`): every path is drawn at a CONSTANT `STROKE_WIDTH`
  (0.75 px on the processing grid, scaled by original/grid so the exported SVG
  keeps the same visual weight) at FULL opacity — plotter ink, matching
  CONTOUR-V (STUDIO: STROKE 0.70, STROKE MOD off; a plotter has one pen). The
  old unconditional opacity fade (0.95 → 0.35 with field value) was a
  divergence that made everything far from the seed wash out gray.

  `wt_range > 0` opts into modulation (the STROKE MOD equivalent):

    normalized_t = (threshold - field_min) / (field_max - field_min)

    stroke_width = max(0.2,  1.4 - normalized_t * wt_range * 1.2)
    stroke_alpha = max(0.35, 0.95 - normalized_t * 0.4 * wt_range)

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

## Mural extensions (opt-in; absent ⇒ CORE behavior)

CORE renders at the source aspect in single black ink. For large wall murals three
opt-in stages extend the pipeline without changing any default. They are confined
to `app.py:/process` plus `engine/compose.py`, `engine/color.py`, and the layered
writer in `engine/export.py`; the field/contour/smooth core is untouched.

- **Wide canvas (`engine/compose.py:compose_canvas`).** When `canvas_aspect`
  (e.g. `2:1`, or derived from `phys_width:phys_height`) is given, the luminance
  grid is padded into that target aspect *before* field construction. `fit=contain`
  (default) letterboxes the whole subject and fills the margins (`margin_fill`:
  `light`/`mean`/`dark`/`edge`); `fit=cover` center-crops to the aspect. The seed
  defaults to the canvas center and the field radiates across the full canvas, so
  the margins read as the field's continuation of the subject. Export happens at the
  canvas size (vector — physical size is set separately). Returns a `subject_rect`
  so the UI can show where the photo sits inside the frame.
  - Aesthetic note: with the reciprocal `march` field a `light` margin is *fast*
    (sparse, minimal); `dark`/`mean` margins, the `wave` field, or **color depth
    mode** are what make nested diamonds visibly fill the margins.
- **Color layers (`engine/color.py:assign_layers`).** With `color_mode=tone` each
  contour is banded by the image's local darkness sampled along it (shadows →
  darkest pen); `color_mode=depth` bands by `normalized_t` (concentric color zones
  radiating from the seed — the hypsometric/elevation look). `n_colors` (1–6) and an
  optional `palette` drive the export. Assignment runs on the processing grid before
  scaling, so the `layer` index survives the scale-to-export step.
- **Layered SVG + physical size (`engine/export.py`).**
  `contours_to_svg_layered` emits one Inkscape pen layer (`<g inkscape:groupmode=
  "layer">`) per color — the multi-pen plot workflow. Passing `phys`
  (`phys_width`/`phys_height`/`phys_units`) stamps real-world width/height on the
  `<svg>` (viewBox stays in grid coords) so the file opens at wall size in
  Inkscape or a print shop with no manual rescale. With `phys` absent and
  `color_mode=off`, the single-ink output is byte-for-byte the historical SVG.
- **Physical pen width (`pen_mm`, `engine/export.py:_pen_stroke_vb`).** A plotter
  has one pen of a real width (e.g. 0.3mm). When `pen_mm` and `phys` are both set
  the stroke is computed in viewBox units so it renders at exactly that width on
  the wall regardless of `detail_px` — a constant ink that overrides `wt_range`
  modulation. Absent ⇒ the pixel-derived stroke (byte-stable default).
- **Point budget (`simplify_mm`, `engine/smooth.py:decimate_contours`).** Detail ×
  levels × Chaikin can push a mural into the millions of points, which chokes
  editors and plotters. After smoothing, a Ramer–Douglas–Peucker pass drops
  interior points within `simplify_mm` (converted from print size to grid px) of
  their chord — shape-preserving, exact endpoints, iterative so a huge path can't
  blow the recursion limit. Absent ⇒ no decimation (byte-stable default).

## Large prints: compute ceiling and guards

The `march` field is a **single global fast-marching geodesic from the seed**
(`MCP.find_costs`); arrival times propagate across the *whole* field, so the
computation **cannot be tiled** — achievable detail is bounded by the largest grid
that fits in memory for one solve. The realistic levers are therefore *raise the
cap, make the one solve leaner, and guard it*, not tiling:

- The geodesic cost array is **float32** (the heaviest array; halves peak memory
  versus the old float64 with no meaningful change to the field).
- `detail_px` tops out at the **measured** practical ceiling (~10s / ~1.4GB at
  4000px on the canonical sources); past that, time and RSS climb steeply.
- `MAX_GRID_PX` (env, default 16M px ≈ a 4000² grid) backstops the heavy solve: a
  `detail_px` × wide-`canvas_aspect` combination whose grid area exceeds it returns
  a clean **400** ("reduce DETAIL or canvas") instead of OOMing the host.
- Raising `detail_px` above the *source* resolution does nothing — the pipeline
  never upscales (Step 1). A genuinely detailed mural needs a high-res source.
- The PNG download is a raster *preview* capped to a max longest side (the SVG is
  the real print deliverable and stays full-resolution vector); the dev server runs
  `threaded=True` so a slow render doesn't serialize other requests (front with
  gunicorn + a long `--timeout` for real mural traffic).

## API Parameter Ranges

| Parameter | Range | Default | Notes |
|-----------|-------|---------|-------|
| levels | 10-150 | 111 | Number of power-spaced threshold levels. |
| smooth | 0-1 | 0.00 | Mapped to 0-4 Chaikin iterations. |
| lum_mix | 0-2 | 0.8 | Strength of luminance warping. |
| wt_range | 0-1 | 0.0 | Stroke width variation. |
| seed_x/seed_y | processing-grid pixels | center | UI seeds are in the resized preview grid (canvas grid when a canvas aspect is set). |
| method | contour/wave/flow/march | march | API + UI default — the canonical "woman output" (fast-marching reciprocal cost), matching `render_tick.sh`. |
| diamond | 0-1 | 0.0 | `wave` only — maps to `WAVE_DIAMOND` if sent. |
| detail_px | 400-4000 | `MAX_DIM` (800) | Processing-grid longest side; raise for large prints (only matters when the source exceeds the cap — never upscales). The upper bound is the measured practical ceiling for one geodesic solve (~10s / ~1.4GB at 4000px); a render whose grid area exceeds `MAX_GRID_PX` is rejected 400. |
| canvas_aspect | `W:H` / ratio | blank = source | Mural canvas target aspect (`engine/compose.py`). |
| canvas_fit | contain/cover | contain | Letterbox vs center-crop. |
| margin_fill | light/mean/dark/edge | light | Tone filling the letterbox margins. |
| color_mode | off/tone/depth | off | Pen-layer separation; off = single black ink. |
| n_colors | 1-6 | 2 | Number of pen layers when color is on. |
| palette | CSS colors | default ramp | Per-layer colors (index = layer). |
| phys_width/phys_height | > 0 | none | Physical export size; stamps real units on the SVG. |
| phys_units | in/cm/mm | in | Units for the physical size. |
| pen_mm | > 0 | none | Plotter pen width in mm — draws a constant physical stroke (overrides `wt_range`); needs `phys` to resolve to viewBox units. Absent ⇒ pixel-derived stroke (byte-stable default). |
| simplify_mm | > 0 | none | RDP point-budget tolerance in mm — drops redundant points so big-print SVGs stay light for editors/plotters; needs `phys` (converted to grid px). Absent ⇒ no decimation. |
| crosshatch | on/off | off | Add a rotated second-direction line set clipped to dark regions (`engine/crosshatch.py`), deepening shadows. Needs `hatch_levels` > 0. |
| hatch_levels | 0-150 | 0 | Number of contour levels in the crosshatch pass. 0 ⇒ no crosshatch. |
| hatch_threshold | 0-1 | 0 | Darkness cutoff (luminance/255): crosshatch lines are kept only where the image is darker than this. 0 ⇒ no crosshatch. |
| hatch_angle | 0-90 | 45 | Rotation of the crosshatch diamond axes vs the primary field. |

## The active field: method=march (fast marching, reciprocal cost)

`method=march` (`engine/march.py:build_march_field`) is the canonical field — it
shares Steps 1, 4–7 and only swaps Step 3. It is CONTOUR-V's confirmed model
(see `contour-v-core-source.md`, "STUDIO screenshot decode"): a seed emits a
wavefront whose local SPEED is set by the image, and the plotted lines are
equal-arrival-time fronts.

It is a **4-connected weighted distance** (`skimage.graph.MCP`,
`fully_connected=False`), whose geodesic is L1 (Manhattan) → concentric DIAMONDS.
MCP accumulates COST = 1/speed, with speed = brightness clamped at a floor:

    gray  = percentile_normalize -> blur -> contrast -> gamma  (engine/march.py)
    edge  = normalized |grad(gray)|
    speed = clip(gray, MARCH_FLOOR, 1)                         # bright = fast
    cost  = MARCH_BASE + lum_mix*(1/speed - 1) + MARCH_EDGE*edge
    field = MCP(cost, 4-connected).find_costs(seed)            # arrival time
    contours = extract_contours(field, levels)                 # same downstream

Why the RECIPROCAL shape matters: isoline spacing = level spacing / cost, so
whites march at ~unit cost (even, open spacing), midtones compress gently
(~2×), and deep darks cost up to 1/MARCH_FLOOR — lines bunch until they merge
into solid ink ("the visor goes black"). A linear darkness ramp (the previous
`MARCH_TONE·dark` cost) can't produce that response: by the time darks
saturated, midtones were nearly as dense and whites were starved.

`MARCH_FLOOR` is THE tone lever (lower floor ⇒ darker darks). `MARCH_BASE` is
the diamond-dominance knob: high ⇒ crisp diamonds barely bent by the image;
low ⇒ the tone term dominates relatively. Other knobs: `MARCH_EDGE` (extra edge
deflection — usually unnecessary, tonal pileup falls out of the reciprocal),
`MARCH_GAMMA`/`MARCH_CONTRAST`/`MARCH_BLUR` (tone preprocessing),
`MARCH_NORM_LO/HI` (percentile normalize). The 6 aesthetic knobs are
**externalized** to `engine/march_params.json` (loaded at import, overrides the
in-code defaults) — the tuned config the optimizer (`loop/optimize.py`)
writes and the loop edits; `engine.march.PARAM_BOUNDS` is the search/clamp box, also
the source of the web UI's STUDIO slider ranges.

**Why 4-connectivity (not a true eikonal):** an isotropic fast-marching eikonal
(scikit-fmm) was tried earlier and abandoned — its round fronts globally rerouted
into horizontal bands. The 4-connected L1 topology is constrained: tone/edges bend
and bunch the diamonds locally but cannot reroute them into bands.

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
