#!/usr/bin/env bash
# loop/render_tick.sh — canonical render for one ralph tick.
#
# Renders IN-PROCESS via loop/render.py (NOT the Flask app). This is the key fix
# for the loop: the long-running app imports the engine once and never reloads it,
# so POSTing to it rendered STALE code every tick — the loop's edits to engine
# constants had no effect. render.py runs the same pipeline in a fresh process so
# each edit actually takes effect. No running app required.
#
# Writes THREE artifacts to loop/output/, named by iteration:
#   iter_NNN.svg         — the SVG
#   iter_NNN.png         — rasterized via rsvg-convert (for Read + judge)
#   iter_NNN.stats.json  — the stats block (paths, total_points, levels, t_*, grid)
#
# Canonical settings: centered seed, levels 111, smooth 0.00, lum_mix 0.8,
# wt_range 0.0, method=march (the active method — a 4-connected geodesic where
# dark pixels cost more, so contours BUNCH in dark regions: tone-driven density
# that actually renders the image, while 4-connectivity keeps L1 diamonds). levels
# 111 = CONTOUR-V CORE density; the 780px raster (PNG_WIDTH) resolves the lines.
#
# Usage:
#   ./loop/render_tick.sh <iter_number>
#
# Env overrides: PNG_WIDTH (default 780), METHOD (default march).
set -euo pipefail
cd "$(dirname "$0")/.."

iter_num=$((10#${1:?iter number required}))   # force base-10 ('033' is octal otherwise)
png_width="${PNG_WIDTH:-780}"   # resolves CORE-like dense contours (111 levels) without raster aliasing
method="${METHOD:-march}"   # the loop tunes engine/march.py build_march_field (tone-cost geodesic diamonds — renders the image's tones)

# Prefer the project venv python (it has the deps); the loop may invoke this from a
# subprocess where the venv isn't activated, so don't rely on PATH `python`.
if [ -x .venv/bin/python ]; then
  python_bin=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  python_bin="python"
else
  python_bin="python3"
fi

"$python_bin" loop/render.py "$iter_num" \
  --method "$method" \
  --levels 111 \
  --smooth 0.0 \
  --lum-mix 0.8 \
  --wt-range 0.0 \
  --png-width "$png_width"
