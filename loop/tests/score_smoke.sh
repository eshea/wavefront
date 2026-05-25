#!/usr/bin/env bash
# Smoke test for loop/score.py — confirms the scorer doesn't crash and
# returns sensible bounds.
#
# Pass conditions:
#   - self-comparison: ssim >= 0.99 AND edge_iou >= 0.99
#   - blank-vs-ref:   ssim < 0.5 AND edge_iou < 0.05
#   - iter file:      both metrics are finite numbers in [0, 1]
set -u
cd "$(dirname "$0")/../.."

REF=examples/contour_woman_post1.jpeg
ITER=loop/output/iter_014.png   # picked because user marks it visually best

source .venv/bin/activate >/dev/null 2>&1

ok=0; fail=0
note() { printf '  %-30s %s\n' "$1" "$2"; }

# 1. self
out=$(python loop/score.py --output "$REF" --reference "$REF" 2>&1) || { echo "FAIL: self crashed"; exit 1; }
ssim=$(echo "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ssim"])')
iou=$(echo  "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["edge_iou"])')
if python3 -c "import sys; sys.exit(0 if ($ssim >= 0.99 and $iou >= 0.99) else 1)"; then
  note "self == ref" "ssim=$ssim edge_iou=$iou  OK"
  ok=$((ok+1))
else
  note "self == ref" "ssim=$ssim edge_iou=$iou  FAIL (want both >=0.99)"
  fail=$((fail+1))
fi

# 2. blank vs ref
python3 -c "from PIL import Image; Image.new('RGB', (780, 835), 'white').save('/tmp/_blank.png')"
out=$(python loop/score.py --output /tmp/_blank.png --reference "$REF" 2>&1)
ssim=$(echo "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ssim"])')
iou=$(echo  "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["edge_iou"])')
if python3 -c "import sys; sys.exit(0 if ($ssim < 0.5 and $iou < 0.05) else 1)"; then
  note "blank vs ref" "ssim=$ssim edge_iou=$iou  OK"
  ok=$((ok+1))
else
  note "blank vs ref" "ssim=$ssim edge_iou=$iou  FAIL"
  fail=$((fail+1))
fi

# 3. an iter file produces finite scores in [0, 1]
if [ -f "$ITER" ]; then
  out=$(python loop/score.py --output "$ITER" --reference "$REF" 2>&1)
  ssim=$(echo "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ssim"])')
  iou=$(echo  "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["edge_iou"])')
  if python3 -c "import sys; sys.exit(0 if (0 <= $ssim <= 1 and 0 <= $iou <= 1) else 1)"; then
    note "iter_014 finite" "ssim=$ssim edge_iou=$iou  OK"
    ok=$((ok+1))
  else
    note "iter_014 finite" "ssim=$ssim edge_iou=$iou  FAIL"
    fail=$((fail+1))
  fi
else
  note "iter_014 finite" "SKIP (file missing)"
fi

echo ""
echo "[score_smoke] passed $ok · failed $fail"
exit $fail
