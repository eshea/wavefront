#!/usr/bin/env bash
# Score a single tick's output. Runs both pixel metrics (score.py) and
# the visual judge (judge.py), merges the records into one JSON line,
# and appends to loop/metrics.jsonl.
#
# Designed to be called from ralph.sh after each Claude tick exits.
#
# Usage:
#   ./loop/score_tick.sh <iter_number>
#
# If the iter's PNG doesn't exist, exits silently (the tick may have
# crashed or chosen not to render — not a hard error).
set -u
cd "$(dirname "$0")/.."

iter_num="${1:?iter number required}"
iter_pad=$(printf '%03d' "$iter_num")
png="loop/output/iter_${iter_pad}.png"
stats="loop/output/iter_${iter_pad}.stats.json"
ref="examples/contour_woman_post1.jpeg"

if [ ! -f "$png" ]; then
  echo "[score_tick] no $png — skipping scoring for iter $iter_pad" >&2
  exit 0
fi

source .venv/bin/activate >/dev/null 2>&1

# Pixel metrics (fast, free, runs locally)
pixel_args=("--output" "$png" "--reference" "$ref" "--iter" "$iter_num")
[ -f "$stats" ] && pixel_args+=("--stats-json" "$stats")
pixel_line=$(python loop/score.py "${pixel_args[@]}" 2>>loop/log/score_errors.log)

# Judge (1-3s on local LLM, can be slow if network blip)
judge_line=$(python loop/judge.py --output "$png" --reference "$ref" --iter "$iter_num" 2>>loop/log/score_errors.log)

# Merge into one record. Both scripts emit single-line JSON.
python3 -c "
import json, sys
pixel = json.loads('''$pixel_line''') if '''$pixel_line'''.strip() else {}
judge = json.loads('''$judge_line''') if '''$judge_line'''.strip() else {}
merged = {**pixel}
for k in ('judge_score', 'judge_notes', 'elapsed_s'):
    if k in judge:
        merged[k] = judge[k]
print(json.dumps(merged))
" >> loop/metrics.jsonl

# Print latest one-liner to stdout for live tail visibility
tail -1 loop/metrics.jsonl | python3 -c "
import json, sys
r = json.loads(sys.stdin.read())
print(f\"[score_tick] iter {r.get('iter','?')}: judge={r.get('judge_score','?')} ssim={r.get('ssim','?')} edge_iou={r.get('edge_iou','?')} path_fit={r.get('path_fit','?')}\")
"
