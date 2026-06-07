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
# wt_range 0.0, method=wave (the active L1-diamond field — the output-4 diamond
# look). levels 111 matches CONTOUR-V CORE's CONTOURS count for this density; the
# warped relief (WAVE_RELIEF≈2.8) breaks up the regular grid so the dense lines
# don't alias into a moiré, and the 780px raster (PNG_WIDTH) resolves them cleanly.
#
# Usage:
#   ./loop/render_tick.sh <iter_number>
#
# Env overrides: PNG_WIDTH (default 434), METHOD (default wave).
set -euo pipefail
cd "$(dirname "$0")/.."

iter_num=$((10#${1:?iter number required}))   # force base-10 ('033' is octal otherwise)
png_width="${PNG_WIDTH:-780}"   # resolves CORE-like dense contours (111 levels) without raster aliasing
method="${METHOD:-wave}"   # the loop tunes engine/field.py build_wave_field (the L1-diamond field — the output-4 look)

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
