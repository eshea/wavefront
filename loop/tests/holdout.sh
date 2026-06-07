#!/usr/bin/env bash
# Held-out test for the WAVEFRONT ralph loop.
#
# Renders current code (IN-PROCESS via loop/render.py) against an UNSEEN image —
# examples/contour_woman.webp, which the loop does NOT optimize against (the
# canonical training pair is the astronaut helmet, contour_space_*). Scores it and
# appends one line to loop/holdout_metrics.jsonl.
#
# Pass condition: the holdout render produces a non-trivial output
# (edge_iou > 0.02 — basically "not blank, not crashed").
#
# This is a SANITY check that helmet-tuned improvements don't break the engine on
# a different subject. It does NOT prove the output is "good" (the woman has no
# matched target — her lineart is a different person, used here only for the
# non-triviality metric).
set -u
cd "$(dirname "$0")/../.."

INPUT="examples/contour_woman.webp"
REFERENCE="examples/contour_woman_lineart.png"
SKIP_EXIT_CODE=${LOOP_SKIP_EXIT_CODE:-77}
PY=.venv/bin/python

if [ ! -f "$INPUT" ]; then echo "FAIL: missing $INPUT"; exit 2; fi
if [ ! -f "$REFERENCE" ]; then echo "FAIL: missing $REFERENCE"; exit 2; fi
if ! command -v rsvg-convert >/dev/null 2>&1; then
  echo "[holdout] rsvg-convert unavailable — SKIP"; exit "$SKIP_EXIT_CODE"
fi

mkdir -p loop/holdout
ts=$(date +%Y%m%d-%H%M%S)
out_dir="loop/holdout"
# render.py names artifacts iter_NNN.*; use a fixed slot and rename to timestamped.
"$PY" loop/render.py 0 --method "${METHOD:-wave}" --levels 111 \
  --input "$INPUT" --out-dir "$out_dir" >/dev/null || { echo "FAIL: render"; exit 1; }
out_png="${out_dir}/output_${ts}.png"
out_stats="${out_dir}/output_${ts}.stats.json"
mv "${out_dir}/iter_000.png" "$out_png"
mv "${out_dir}/iter_000.stats.json" "$out_stats"
rm -f "${out_dir}/iter_000.svg"

score_line=$("$PY" loop/score.py --output "$out_png" --reference "$REFERENCE" --stats-json "$out_stats")
# Deterministic score against the holdout's OWN source (a true matched pair).
dscore_line=$("$PY" loop/dscore.py --output "$out_png" --source "$INPUT" \
  2>>loop/log/score_errors.log)

echo "$score_line" | TS="$ts" DSCORE="$dscore_line" "$PY" -c "
import json, sys, os
rec = json.loads(sys.stdin.read())
rec['holdout'] = True
rec['ts_run'] = os.environ['TS']
d = json.loads(os.environ['DSCORE']) if os.environ.get('DSCORE','').strip() else {}
for k in ('d_score','d_fidelity','d_style','d_r','d_ink','d_peakedness'):
    if k in d:
        rec[k] = d[k]
print(json.dumps(rec))
" >> loop/holdout_metrics.jsonl

iou=$(echo "$score_line" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["edge_iou"])')
dscore=$(echo "$dscore_line" | "$PY" -c 'import json,sys
try: print(json.load(sys.stdin).get("d_score","?"))
except Exception: print("?")')
echo "[holdout] result: edge_iou=$iou (target > 0.02) · d_score=$dscore"

if "$PY" -c "import sys; sys.exit(0 if $iou > 0.02 else 1)"; then
  echo "[holdout] PASS — engine produces non-trivial holdout output"; exit 0
else
  echo "[holdout] FAIL — engine output is trivial on holdout"; exit 1
fi
