#!/usr/bin/env bash
# Anchor test: iter_014.png is the human-judged best output from loop pass 1.
# The metric (visual judge via local Qwen3 122B) should rank iter_014 in
# the top 5 across all loop/output/iter_*.png files.
#
# Pass condition: iter_014 ranks in the top 5 by judge_score.
#
# This is the canary for metric quality. If iter_014 is mid-pack, our
# scoring is poorly aligned with human judgment and we shouldn't trust
# improvement claims from the loop.
set -u
cd "$(dirname "$0")/../.."

REF=examples/contour_woman_post1.jpeg
ANCHOR_BASENAME=iter_014.png
ANCHOR_PATH="loop/output/${ANCHOR_BASENAME}"
TOP_N=5
SKIP_EXIT_CODE=${LOOP_SKIP_EXIT_CODE:-77}

source .venv/bin/activate >/dev/null 2>&1

if [ ! -f "$ANCHOR_PATH" ]; then
  echo "[iter014_anchor] missing $ANCHOR_PATH — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

if ! compgen -G "loop/output/iter_*.png" >/dev/null; then
  echo "[iter014_anchor] no loop/output/iter_*.png artifacts — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

# Sanity: judge endpoint must be reachable
if ! curl -s --max-time 3 -o /dev/null "${WAVEFRONT_LLM:-http://192.168.50.135:8000}/health"; then
  echo "[iter014_anchor] judge LLM unreachable — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

# Score every iter_*.png that exists
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
for f in loop/output/iter_*.png; do
  [ -f "$f" ] || continue
  n=$(basename "$f" .png | sed 's/iter_//; s/^0*//')
  if ! python loop/judge.py --output "$f" --reference "$REF" --iter "$n" 2>/dev/null >> "$tmp"; then
    echo "[iter014_anchor] judge failed for $f  FAIL"
    exit 1
  fi
done

if [ ! -s "$tmp" ]; then
  echo "[iter014_anchor] no iter outputs scored — SKIP"
  exit "$SKIP_EXIT_CODE"
fi

ranked=$(python3 -c "
import json
rows = [json.loads(l) for l in open('$tmp')]
rows.sort(key=lambda r: r['judge_score'], reverse=True)
for i, r in enumerate(rows, 1):
    name = r['output'].split('/')[-1]
    print(f'{i:3d}  {name:25s} score={r[\"judge_score\"]:3d}')
")
echo "$ranked" | head -10
echo "..."
echo "$ranked" | grep -F "$ANCHOR_BASENAME"
echo ""

anchor_rank=$(echo "$ranked" | grep -F "$ANCHOR_BASENAME" | awk '{print $1}')
if [ -z "$anchor_rank" ]; then
  echo "[iter014_anchor] anchor $ANCHOR_BASENAME not found  FAIL"
  exit 1
fi

if [ "$anchor_rank" -le "$TOP_N" ]; then
  echo "[iter014_anchor] PASS — $ANCHOR_BASENAME ranks #${anchor_rank} (target: top-$TOP_N)"
  exit 0
else
  echo "[iter014_anchor] FAIL — $ANCHOR_BASENAME ranks #${anchor_rank} (target: top-$TOP_N)"
  echo "    judge does not match human judgment; tune loop/judge.py PROMPT"
  exit 1
fi
