# WAVEFRONT
### Topographic Contour Portrait Engine

A Python web application that transforms any image into topographic contour line art — replicating and extending the VEX-LINE / VEX ENGINE aesthetic used by plotter artists.

## How It Works

WAVEFRONT treats image brightness as elevation. A scalar field is computed for every pixel:

  field[x,y] = euclidean_distance(x, y, seed_x, seed_y) + (255 - luminance[x,y]) * lum_mix

This hybrid field combines:
1. **Radial distance** from a user-defined seed point → creates concentric diamond/ring base pattern
2. **Inverted luminance** → dark areas add elevation, distorting rings to follow image topology

Isolines (contour lines at equal field values) are then extracted using the Marching Squares algorithm via scikit-image, smoothed with Chaikin subdivision, and exported as SVG with adaptive stroke weights.

## Quick Start

  pip install -r requirements.txt
  python app.py

Open http://localhost:5055 in your browser.

> Default port is 5055 (avoids macOS AirPlay Receiver, which holds port 5000).
> Override with `PORT=8080 python app.py`.

## Usage

1. Upload any image (portrait or object)
2. Click the preview canvas to set the seed point (origin of concentric rings)
3. Adjust sliders:
   - **Levels** — number of contour lines (10–150)
   - **Smooth** — Chaikin subdivision passes (0 = raw, 1 = very smooth)
   - **Lum mix** — how strongly image warps the distance field (0 = pure rings, 2 = max warp)
   - **Wt range** — stroke weight variation (0 = flat, 1 = thick near seed / thin at edges)
4. Click **Compute** to generate
5. Export SVG for pen plotter use

## Parameters Guide

| Parameter | Range | Effect |
|-----------|-------|--------|
| Levels | 10–150 | More levels = denser lines. 63 is the VEX ENGINE default. |
| Smooth | 0–1 | Chaikin passes (mapped to 0–4 iterations). 0.70 is VEX default. |
| Lum mix | 0–2 | k in field formula. 1.0 matches VEX ENGINE behavior. |
| Wt range | 0–1 | Stroke weight delta. 0.6 gives good depth. |
| Seed X/Y | pixels | Click canvas. Center = concentric from middle. Off-center = asymmetric diamonds. |

## For Pen Plotters

Export SVG is sized to original image dimensions in pixels (1px = 1 unit). For plotting:
- Scale SVG to your paper size in Inkscape or Illustrator
- Recommended paper: A3 or larger
- Recommended pen: 0.1–0.3mm fineliner
- The SVG uses stroke-width variation — check your plotter software supports this

## Stack

- Python 3.9+
- Flask — web server
- NumPy — vectorized field computation
- scikit-image — Marching Squares contour extraction
- Pillow — image loading and preprocessing
- svgwrite — SVG generation
