# WAVEFRONT
### Topographic Contour Portrait Engine

A Python web application that transforms any image into topographic contour line art — replicating and extending the VEX-LINE / VEX ENGINE aesthetic used by plotter artists.

## How It Works

WAVEFRONT computes a **fast-marching contour field** — the same model as the
tool it replicates: a wavefront expands from a user-placed seed, and its local
speed is set by image brightness. The plotted lines are equal-arrival-time
fronts.

  speed[x,y] = clip(brightness[x,y], floor, 1)        # bright = fast
  cost[x,y]  = base + lum_mix * (1/speed - 1)         # dark = slow
  field      = accumulated arrival time from the seed (4-connected grid)

Three properties fall out of this:
1. **4-connectivity** makes the flat-region geodesic Manhattan (L1) distance → concentric **diamond** wavefronts
2. **Reciprocal cost** means line spacing tracks tone: whites stay open, midtones compress gently, and deep darks (eyes, visors) saturate to solid ink
3. The speed **floor** caps how slow the wave can crawl — the main tone lever

Isolines are extracted at linearly spaced thresholds (with the top of the field
range clipped) using Marching Squares via scikit-image, resampled at a fixed
3 px step to remove stairstep jitter, optionally smoothed with Chaikin
subdivision, scaled back to the original upload dimensions, and exported as SVG
in constant full-opacity ink (a plotter has one pen; weight modulation is
opt-in).

## Quick Start

  pip install -r requirements.txt
  python app.py

Open http://localhost:5055 in your browser.

> Default port is 5055 (avoids macOS AirPlay Receiver, which holds port 5000).
> Override with `PORT=8080 python app.py`.
> The development server binds to `127.0.0.1` by default. Override with `HOST=0.0.0.0` when needed.

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
| Levels | 10–150 | More levels = denser lines. 111 matches the reference tool's CONTOURS default. |
| Smooth | 0–1 | Chaikin passes (mapped to 0–4 iterations). 0 = the reference's angular-but-clean look. |
| Lum mix | 0–2 | Scales the tone term in the cost. 0 = pure diamonds, higher = image dominates. |
| Wt range | 0–1 | 0 (default) = constant plotter ink. >0 = opt-in weight/opacity modulation. |
| Seed X/Y | pixels | Click canvas. Center = concentric from middle. Off-center = asymmetric diamonds. |

The march field's own knobs (speed floor, diamond dominance, contrast/gamma/blur
pre-shaping) appear as STUDIO-style sliders in the UI, sourced live from the
engine's tuned config (`engine/march_params.json`).

## For Pen Plotters

Export SVG is sized to original image dimensions in pixels (1px = 1 unit). For plotting:
- Scale SVG to your paper size in Inkscape or Illustrator
- Recommended paper: A3 or larger
- Recommended pen: 0.1–0.3mm fineliner
- Default export is a single constant stroke width — ideal for one-pen plotting. (With `wt_range > 0` the SVG uses stroke-width variation; check your plotter software supports it.)

## Stack

- Python 3.9+
- Flask — web server
- NumPy — vectorized field computation
- SciPy — Gaussian luminance denoise
- scikit-image — fast-marching cost accumulation (`skimage.graph.MCP`) + Marching Squares contour extraction
- Pillow — image loading and preprocessing
- svgwrite — SVG generation
