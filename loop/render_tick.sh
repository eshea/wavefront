#!/usr/bin/env bash
# loop/render_tick.sh — canonical render for one ralph tick.
#
# POSTs the canonical test input to the running Flask app's /process
# endpoint and writes THREE artifacts to loop/output/, atomically named
# by iteration:
#   iter_NNN.svg         — the SVG returned by /process
#   iter_NNN.png         — rasterized via rsvg-convert (for Read + judge)
#   iter_NNN.stats.json  — the /process `stats` block (paths, total_points,
#                          levels, t_min, t_max, grid, segments)
#
# The stats.json is the missing piece that lets loop/score.py compute
# path_fit — previously no tick wrote it, so path_fit was always null.
# Using ONE render helper (instead of ad-hoc per-tick curl) also removes
# render drift between ticks: every tick renders the exact same settings.
#
# Canonical settings (from contour_woman_settings.webp, baked into
# loop/score_tick.sh's reference): seed=(227,225), levels=111,
# smooth=0.00, lum_mix=1.0, wt_range=0.0.
#
# Usage:
#   ./loop/render_tick.sh <iter_number>
#
# Env overrides: PORT (default 5055), PNG_WIDTH (default 434).
# Requires the Flask app to be running; exits non-zero with a clear
# message if /process is unreachable (the caller owns app lifecycle).
set -euo pipefail
cd "$(dirname "$0")/.."

iter_num="${1:?iter number required}"
iter_pad=$(printf '%03d' "$iter_num")
port="${PORT:-5055}"
png_width="${PNG_WIDTH:-434}"

base="loop/output/iter_${iter_pad}"
svg="${base}.svg"
png="${base}.png"
stats_json="${base}.stats.json"
input="examples/contour_woman.webp"

mkdir -p loop/output

# Fail fast with an actionable message if the app isn't up.
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/" || echo 000)
if [ "$code" != "200" ]; then
  echo "[render_tick] Flask app not reachable on :${port} (got HTTP ${code})." >&2
  echo "[render_tick] Start it first:  source .venv/bin/activate && PORT=${port} python app.py &" >&2
  exit 1
fi

# Render to a temp JSON, then split into svg + stats.json so a partial
# failure never leaves a stale/mismatched stats.json next to a new svg.
resp=$(mktemp)
trap 'rm -f "$resp"' EXIT

curl -s --fail -X POST \
  -F "image=@${input}" \
  -F "levels=111" \
  -F "smooth=0.00" \
  -F "lum_mix=1.0" \
  -F "wt_range=0.0" \
  -F "seed_x=227" \
  -F "seed_y=225" \
  "http://localhost:${port}/process" -o "$resp"

python3 - "$resp" "$svg" "$stats_json" <<'PY'
import json, sys
resp_path, svg_path, stats_path = sys.argv[1:4]
with open(resp_path) as f:
    d = json.load(f)
if "error" in d:
    sys.stderr.write(f"[render_tick] /process error: {d['error']}\n")
    sys.exit(1)
with open(svg_path, "w") as f:
    f.write(d["svg"])
with open(stats_path, "w") as f:
    json.dump(d["stats"], f, indent=2, sort_keys=True)
s = d["stats"]
print(f"[render_tick] stats: paths={s.get('paths')} "
      f"total_points={s.get('total_points')} levels={s.get('levels')} "
      f"grid={s.get('grid')} t=[{s.get('t_min')},{s.get('t_max')}]")
PY

# Rasterize for visual judging / Read.
rsvg-convert -w "$png_width" "$svg" -o "$png"
echo "[render_tick] wrote $svg, $png, $stats_json"
