#!/usr/bin/env bash
# Score a single tick's output. Runs the deterministic scorer (dscore.py) plus
# the legacy pixel metrics (score.py, recorded as co-signals), merges the
# records into one JSON line, and appends to loop/metrics.jsonl.
#
# Designed to be called from ralph.sh after each Claude tick exits.
#
# Usage:
#   ./loop/score_tick.sh <iter_number>
#
# The decision signal is dscore.py's `d_score` (0-100): a DETERMINISTIC,
# backend-independent measure of how well the output re-expresses its SOURCE as
# flowing contour lines (source-fidelity) and how much it looks like the
# VEX-LINE family (style). See loop/dscore.py. The old LLM vision judge was
# removed — it was backend-dependent, noisy, and often offline.
#
# If the iter's PNG doesn't exist, exits silently (the tick may have
# crashed or chosen not to render — not a hard error).
set -u
cd "$(dirname "$0")/.."

iter_num=$((10#${1:?iter number required}))   # 10# = force base-10 (a padded
                                              # '033' would otherwise be octal)
iter_pad=$(printf '%03d' "$iter_num")
png="loop/output/iter_${iter_pad}.png"
stats="loop/output/iter_${iter_pad}.stats.json"
ref="examples/contour_space_post.webp"   # the artist's CONTOUR-V output (legacy pixel co-signals)

if [ ! -f "$png" ]; then
  echo "[score_tick] no $png — skipping scoring for iter $iter_pad" >&2
  exit 0
fi

source .venv/bin/activate >/dev/null 2>&1

# The source the tick rendered (recorded by render.py in the stats JSON). The
# deterministic scorer compares the output to its OWN source. Fall back to the
# canonical helmet source if the stats field is absent.
src="examples/space/space-source.jpg"
if [ -f "$stats" ]; then
  src=$(python3 -c "import json,sys; print(json.load(open('$stats')).get('source') or '$src')" 2>/dev/null || echo "$src")
fi

# Deterministic score (primary decision signal — fast, free, local, reproducible)
dscore_line=$(python loop/dscore.py --output "$png" --source "$src" \
  --iter "$iter_num" 2>>loop/log/score_errors.log)

# Legacy pixel metrics (path_fit, ink_coverage, ssim, edge_iou) — recorded as
# co-signals only; not gated on.
pixel_args=("--output" "$png" "--reference" "$ref" "--iter" "$iter_num")
[ -f "$stats" ] && pixel_args+=("--stats-json" "$stats")
pixel_line=$(python loop/score.py "${pixel_args[@]}" 2>>loop/log/score_errors.log)

# Merge into one record (dscore keys win on conflict). Both scripts emit single-line JSON.
python3 -c "
import json
pixel = json.loads('''$pixel_line''') if '''$pixel_line'''.strip() else {}
dscore = json.loads('''$dscore_line''') if '''$dscore_line'''.strip() else {}
merged = {**pixel, **dscore}
print(json.dumps(merged))
" >> loop/metrics.jsonl

# Print latest one-liner to stdout for live tail visibility
tail -1 loop/metrics.jsonl | python3 -c "
import json, sys
r = json.loads(sys.stdin.read())
print(f\"[score_tick] iter {r.get('iter','?')}: d_score={r.get('d_score','?')} \"
      f\"(fid={r.get('d_fidelity','?')} style={r.get('d_style','?')}) \"
      f\"ink={r.get('d_ink','?')} peak={r.get('d_peakedness','?')}\")
"

# Refresh the experiment digest, then the agent's live situational view (STATUS.md).
# Both are best-effort: never fail scoring over a reporting artifact.
python loop/distill.py >/dev/null 2>&1 || true
python loop/status.py "$iter_num" || echo "[score_tick] status refresh skipped" >&2
