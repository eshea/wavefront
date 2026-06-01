#!/usr/bin/env bash
# Held-out test for the WAVEFRONT ralph loop.
#
# Renders current code against loop/holdout/contour_space_pre.jpg (which
# the loop has never seen during optimization) and scores it. Appends
# one line to loop/holdout_metrics.jsonl.
#
# Pass condition: the holdout render produces a non-trivial output
# (edge_iou > 0.02 — basically "not blank, not crashed").
#
# This is a SANITY check that overfit-to-the-woman improvements don't
# break the engine entirely on a different image. It does NOT prove
# the engine produces "good" helmet output — that's a separate
# evaluation.
set -u
cd "$(dirname "$0")/../.."

INPUT="loop/holdout/contour_space_pre.jpg"
REFERENCE="loop/holdout/contour_space_post.webp"
SKIP_EXIT_CODE=${LOOP_SKIP_EXIT_CODE:-77}

if [ ! -f "$INPUT" ]; then echo "FAIL: missing $INPUT"; exit 2; fi
if [ ! -f "$REFERENCE" ]; then echo "FAIL: missing $REFERENCE"; exit 2; fi

if ! command -v rsvg-convert >/dev/null 2>&1; then
  echo "[holdout] rsvg-convert unavailable — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

if ! curl -s --max-time 3 -o /dev/null http://localhost:5055/; then
  echo "[holdout] Flask not reachable on :5055 — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

read INPUT_W INPUT_H <<<"$(source .venv/bin/activate && python3 -c "
from PIL import Image
w, h = Image.open('$INPUT').size
print(w, h)
")"
SEED_X=$((INPUT_W / 2))
SEED_Y=$((INPUT_H / 2))

ts=$(date +%Y%m%d-%H%M%S)
out_svg="loop/holdout/output_${ts}.svg"
out_png="loop/holdout/output_${ts}.png"
out_stats="loop/holdout/output_${ts}.stats.json"

curl -s -X POST \
  -F "image=@${INPUT}" \
  -F "levels=111" -F "smooth=0.00" -F "lum_mix=1.0" -F "wt_range=0.0" \
  -F "seed_x=${SEED_X}" -F "seed_y=${SEED_Y}" \
  -F "method=${METHOD:-wave}" \
  http://localhost:5055/process | python3 -c "
import json, sys
d = json.load(sys.stdin)
open('${out_svg}', 'w').write(d['svg'])
open('${out_stats}', 'w').write(json.dumps(d['stats']))
" || { echo "FAIL: /process call failed"; exit 1; }

rsvg-convert -w "$INPUT_W" "$out_svg" -o "$out_png" || { echo "FAIL: rsvg-convert"; exit 1; }

source .venv/bin/activate
score_line=$(python loop/score.py \
  --output "$out_png" --reference "$REFERENCE" --stats-json "$out_stats")

# Visual judge on the holdout too — a real overfitting signal. Pixel
# edge_iou only proves "not blank"; the judge catches the case where
# woman-tuned params produce garbage on a different subject.
judge_line=$(python loop/judge.py --output "$out_png" --reference "$REFERENCE" \
  --samples "${JUDGE_SAMPLES:-5}" 2>>loop/log/score_errors.log)

echo "$score_line" | TS="$ts" JUDGE="$judge_line" python3 -c "
import json, sys, os
rec = json.loads(sys.stdin.read())
rec['holdout'] = True
rec['ts_run'] = os.environ['TS']
judge = json.loads(os.environ['JUDGE']) if os.environ.get('JUDGE','').strip() else {}
for k in ('judge_score', 'judge_notes', 'judge_spread', 'judge_samples', 'model', 'judge_backend'):
    if k in judge:
        rec[k] = judge[k]
print(json.dumps(rec))
" >> loop/holdout_metrics.jsonl

iou=$(echo "$score_line" | python3 -c 'import json,sys; print(json.load(sys.stdin)["edge_iou"])')
jscore=$(echo "$judge_line" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("judge_score","?"))
except Exception: print("?")')
echo "[holdout] result: edge_iou=$iou (target > 0.02) · judge=$jscore"

if python3 -c "import sys; sys.exit(0 if $iou > 0.02 else 1)"; then
  echo "[holdout] PASS — engine produces non-trivial holdout output"
  exit 0
else
  echo "[holdout] FAIL — engine output is trivial on holdout"
  exit 1
fi
