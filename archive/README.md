# Wavefront

Wavefront is a portrait-to-line-art generator for plotter-style contour output.
It turns a raster image into ordered polylines that can be previewed as a PNG
or exported as an SVG for pen plotting and vector workflows.

The core visual idea is a seeded radiating field: a square-ish wavefront moves
through the image, slows down around image structure, and then gets contoured
into isolines. The result sits somewhere between topographic line art, CRT-era
graphics, and plotter-native geometry.

This project started life as `Contour-V` / `MARCH-V`. The current package name
is `wavefront`.

## Status

This is a compact working prototype, not a polished library yet.

What works well now:

- image loading with EXIF-aware orientation handling
- topographic and radiating contour modes
- exact seeded weighted-distance field for radiating mode
- contour extraction, simplification, resampling, and smoothing
- overlap filtering and greedy stroke ordering for plotters
- PNG preview rendering
- aspect-safe SVG export

What is still rough:

- the contour level allocation is still linear
- the exact distance solver is correct, but may be too expensive for realtime UI
- the API is compact, but not finalized
- the package still carries some naming history from `Contour-V`

## Project Layout

```text
wavefront/
  README.md
  __init__.py
  __main__.py
  core.py
  contour.py
  examples/
```

- `core.py` is the current implementation.
- `__init__.py` re-exports the public functions.
- `__main__.py` provides a basic `python -m wavefront` entry point.
- `contour.py` is kept alongside the package during the rename transition.

## Requirements

- Python 3.10+
- `numpy`
- `scipy`
- `scikit-image`
- `Pillow`
- `matplotlib` for PNG preview rendering

Example install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install numpy scipy scikit-image Pillow matplotlib
```

## Quick Start

```python
from wavefront import generate, render_png, save_svg

image_path = "portrait.jpg"

polys, field = generate(
    image_path,
    mode="radiating",
    seed_xy=(250, 110),
    max_side=500,
)

render_png(polys, "preview.png", width=500, height=650)
save_svg(polys, "output.svg", 500, 650, width_mm=190)
```

`generate(...)` returns:

- `polys`: a list of `(N, 2)` float arrays in image-space `(x, y)` coordinates
- `field`: the scalar field that was contoured

## Modes

### `topographic`

Contours the preprocessed brightness field directly.

Use this when you want a more conventional topographic portrait look.

### `radiating`

Builds a weighted distance field from a seed and then contours it.

Use this when you want the square/radiating line language seen in the example
artworks.

## Core Pipeline

1. Load image and convert to grayscale
2. Preprocess the field
3. Build either:
   - a brightness field (`topographic`)
   - a seeded weighted distance field (`radiating`)
4. Extract isolines with marching squares
5. Simplify, resample, and smooth the polylines
6. Drop near-overlapping strokes
7. Reorder strokes for reduced pen-up travel
8. Render or export

## Important Parameters

### Shared preprocessing

- `invert`
- `gamma`
- `contrast`
- `local_equalize`
- `local_equalize_clip`
- `blur`
- `detail_sigma`
- `detail_amount`

These control how aggressively the image is shaped before contouring.

### Radiating mode

- `seed_xy`
- `seed_size`
- `speed_exponent`
- `speed_floor`
- `edge_amount`
- `edge_sigma`
- `field_detail_amount`
- `diag_cost`

These control the structure of the radiating field.

Useful intuition:

- lower `diag_cost` pushes the field toward a more square geometry
- higher `speed_exponent` makes dark regions influence line spacing more strongly
- higher `speed_floor` prevents very dark areas from consuming too many contours
- `edge_amount` increases wavefront drag around local gradients
- `field_detail_amount` adds post-distance feature perturbation

### Contouring and polyline cleanup

- `n_contours`
- `min_contour_length`
- `dp_eps`
- `resample_spacing`
- `chaikin_iters`
- `min_gap_px`
- `reorder`

These control density, smoothness, and plotter readiness.

## CLI

There is a minimal module entry point:

```bash
python -m wavefront path/to/image.jpg radiating
```

It:

- loads the image
- chooses a simple default seed
- generates the contours
- writes a demo PNG and SVG to `/mnt/user-data/outputs/`

This is mainly a smoke-test path right now, not a production CLI.

## Public API

Re-exported from `wavefront.__init__`:

- `audit`
- `extract_contours`
- `generate`
- `load_gray`
- `polish`
- `preprocess_field`
- `radiating_field`
- `render_png`
- `reorder_for_plotter`
- `save_svg`
- `topographic_field`

## Plotter Notes

Wavefront is built around polyline output rather than filled raster effects.
That means a few details matter:

- stroke order matters for pen-up travel
- line density matters more than raw tonal accuracy
- oversampling can produce visually nice previews but inefficient plots
- SVG export should preserve aspect ratio exactly

The current exporter uses a uniform scale and centers the drawing if both
`width_mm` and `height_mm` are provided.

## Known Next Step

The biggest missing feature is better contour level allocation.

Right now `extract_contours` uses linearly spaced levels across the field
range. That works, but it tends to over-spend contours in broad dark regions
and under-describe other areas. The next meaningful upgrade is a selectable
level strategy, for example:

- `linear`
- `quantile`
- `hybrid`

That is likely a larger quality win than adding more preprocessing knobs.

## Examples

The `examples/` directory contains reference images used during development:

- `example1.jpeg`
- `example2.jpeg`
- `example3.jpeg`
- `example4.jpeg`

## License

No license file is included yet. Treat the project as private/internal until
you decide how you want to publish it.
