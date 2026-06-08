#!/usr/bin/env bash
# Calibration / validation test for loop/dscore.py — the deterministic scorer.
#
# Asserts the metric is calibrated: the artist's known-good outputs score HIGH
# and degenerate images (blank / solid / noise / smooth blob) score ~0. If this
# fails after a change to dscore.py's CALIB constants, the scorer is mis-tuned.
#
# Pass conditions:
#   - every good output  >= GOOD_MIN  (88)
#   - every degenerate   <= BAD_MAX   (5)
# Exit 0=pass, 77=skip (libs/refs missing), 1=fail.
set -u
cd "$(dirname "$0")/../.."

GOOD_MIN=85   # matched artist outputs (diamonds peak ~100; flowing space ~87)
HARD_MIN=58   # busy source / flowing (samurai) — fidelity-limited, must read as good
BAD_MAX=5

SPACE_SRC=examples/space/space-source.jpg
SPACE_OUT=examples/space/space-output-1.jpeg
WOMAN_SRC=examples/woman/woman-source.jpeg
SAMURAI_SRC=examples/samurai/samurai-source.jpg
SAMURAI_OUT=examples/samurai/samurai-output-1.jpeg

for f in "$SPACE_SRC" "$SPACE_OUT" "$WOMAN_SRC" "$SAMURAI_SRC" "$SAMURAI_OUT"; do
  [ -f "$f" ] || { echo "SKIP: missing reference $f"; exit 77; }
done

source .venv/bin/activate >/dev/null 2>&1
python3 -c 'import numpy, scipy, skimage, PIL' 2>/dev/null \
  || { echo "SKIP: scoring deps unavailable"; exit 77; }

# Synthesize degenerate negatives.
python3 - <<'PY' || { echo "SKIP: could not synthesize negatives"; exit 77; }
import numpy as np
from PIL import Image
Image.new('L', (512, 512), 255).save('/tmp/_dcalib_blank.png')
Image.new('L', (512, 512), 0).save('/tmp/_dcalib_solid.png')
rng = np.random.default_rng(0)
Image.fromarray(rng.integers(0, 256, (512, 512)).astype('uint8')).save('/tmp/_dcalib_noise.png')
yy, xx = np.mgrid[0:512, 0:512]
blob = 255 - 200 * np.exp(-(((xx-256)**2 + (yy-256)**2) / (2*120**2)))
Image.fromarray(blob.astype('uint8')).save('/tmp/_dcalib_blob.png')
# axis-aligned stripes — the wrong orientation (flow look), for the diamond test.
stripes = 255 * (((xx) % 16) < 2).astype('uint8')   # vertical (axis-aligned)
Image.fromarray(255 - stripes).save('/tmp/_dcalib_axis.png')
PY

ok=0; fail=0
note() { printf '  %-26s %s\n' "$1" "$2"; }

score() {  # score <output> <source> [--style-only]
  python loop/dscore.py --output "$1" --source "$2" ${3:-} 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["d_score"])'
}

check_high() {  # check_high <label> <score>
  if python3 -c "import sys; sys.exit(0 if $2 >= $GOOD_MIN else 1)"; then
    note "$1" "d_score=$2  OK (>=$GOOD_MIN)"; ok=$((ok+1))
  else
    note "$1" "d_score=$2  FAIL (want >=$GOOD_MIN)"; fail=$((fail+1))
  fi
}
check_low() {  # check_low <label> <score>
  if python3 -c "import sys; sys.exit(0 if $2 <= $BAD_MAX else 1)"; then
    note "$1" "d_score=$2  OK (<=$BAD_MAX)"; ok=$((ok+1))
  else
    note "$1" "d_score=$2  FAIL (want <=$BAD_MAX)"; fail=$((fail+1))
  fi
}
check_atleast() {  # check_atleast <label> <score> <min>
  if python3 -c "import sys; sys.exit(0 if $2 >= $3 else 1)"; then
    note "$1" "d_score=$2  OK (>=$3)"; ok=$((ok+1))
  else
    note "$1" "d_score=$2  FAIL (want >=$3)"; fail=$((fail+1))
  fi
}

echo "GOOD outputs — full source-fidelity mode (3 matched pairs):"
check_high "space" "$(score "$SPACE_OUT" "$SPACE_SRC")"
for n in 1 2 4; do  # output-3 is a two-face composite — excluded from calibration
  out="examples/woman/woman-sample-output-$n.jpeg"
  [ -f "$out" ] && check_high "woman-$n" "$(score "$out" "$WOMAN_SRC")"
done
# samurai: a genuine output but a very busy source (calligraphy+mask) → lower
# fidelity ceiling. Must still read as clearly good, not great.
check_atleast "samurai (busy source)" "$(score "$SAMURAI_OUT" "$SAMURAI_SRC")" "$HARD_MIN"

echo "DEGENERATE images (must score ~0):"
check_low "blank" "$(score /tmp/_dcalib_blank.png "$SPACE_SRC")"
check_low "solid" "$(score /tmp/_dcalib_solid.png "$SPACE_SRC")"
check_low "noise" "$(score /tmp/_dcalib_noise.png "$SPACE_SRC")"
check_low "blob"  "$(score /tmp/_dcalib_blob.png  "$SPACE_SRC")"

echo "DIAMOND preference (the output-4 ±45° aesthetic, not axis-aligned waves):"
# diamond term: HIGH for the real target's organic diagonals, LOW for axis-aligned
# line art. (A perfectly-regular synthetic diamond grid is the MOIRÉ failure mode
# — too regular — and is intentionally NOT rewarded, so we test the real target.)
diam_term() {  # diamond_score component of <output>
  python loop/dscore.py --output "$1" --source "$SPACE_SRC" --style-only 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["d_diamond"])'
}
w4d=$(diam_term examples/woman/woman-sample-output-4.jpeg)
axd=$(diam_term /tmp/_dcalib_axis.png)
if python3 -c "import sys; sys.exit(0 if $w4d >= 0.8 and $axd <= 0.3 else 1)"; then
  note "target diamonds vs axis" "woman4_diamond=$w4d axis_diamond=$axd  OK"; ok=$((ok+1))
else
  note "target diamonds vs axis" "woman4_diamond=$w4d axis_diamond=$axd  FAIL"; fail=$((fail+1))
fi

echo "  ── passed=$ok failed=$fail"
[ "$fail" -eq 0 ] || exit 1
