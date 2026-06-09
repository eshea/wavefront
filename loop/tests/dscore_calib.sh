#!/usr/bin/env bash
# Calibration / validation test for loop/dscore.py — the deterministic scorer.
#
# Asserts the metric is calibrated: the artist's known-good outputs score HIGH,
# degenerate images (blank / solid / noise / smooth blob) score ~0, and committed
# PLAUSIBLE-BUT-WRONG hard negatives (loop/tests/fixtures/hard_neg/) score well
# below the artists with a MARGIN. The margin is the anti-false-hill-climb lock:
# any dscore.py change that inflates a smudgy/inverted/over-regular render lifts the
# negatives toward the good band and turns this gate RED. If this fails after a
# change to dscore.py's CALIB constants, the scorer is mis-tuned.
#
# Pass conditions:
#   - every good output  >= GOOD_MIN  (samurai only needs HARD_MIN)
#   - every degenerate   <= BAD_MAX
#   - every hard negative <= NEG_MAX
#   - (worst good) - (best hard negative) >= MARGIN
#   - monotonic tiers: min(good) > max(hard_neg) > max(degenerate)
# Exit 0=pass, 77=skip (libs/refs missing), 1=fail.
set -u
cd "$(dirname "$0")/../.."

GOOD_MIN=85   # matched artist outputs (diamonds peak ~100; flowing space ~87)
HARD_MIN=58   # busy source / flowing (samurai) — fidelity-limited, must read as good
BAD_MAX=5
NEG_MAX=55    # plausible-but-wrong hard negatives must score at most this
MARGIN=20     # worst good must beat best hard negative by at least this much

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

GOODS=""; NEGS=""; DEGENS=""   # accumulate scores for the margin/monotonicity check

echo "GOOD outputs — full source-fidelity mode (3 matched pairs):"
s=$(score "$SPACE_OUT" "$SPACE_SRC");  check_high "space" "$s";  GOODS="$GOODS $s"
for n in 1 2 4; do  # output-3 is a two-face composite — excluded from calibration
  out="examples/woman/woman-sample-output-$n.jpeg"
  [ -f "$out" ] && { s=$(score "$out" "$WOMAN_SRC"); check_high "woman-$n" "$s"; GOODS="$GOODS $s"; }
done
# samurai: a genuine output but a very busy source (calligraphy+mask) → lower
# fidelity ceiling. Must still read as clearly good, not great.
s=$(score "$SAMURAI_OUT" "$SAMURAI_SRC")
check_atleast "samurai (busy source)" "$s" "$HARD_MIN"; GOODS="$GOODS $s"

echo "DEGENERATE images (must score ~0):"
for d in blank solid noise blob; do
  s=$(score /tmp/_dcalib_$d.png "$SPACE_SRC"); check_low "$d" "$s"; DEGENS="$DEGENS $s"
done

# Plausible-but-wrong renders that pass the degenerate gate (they have real line
# structure) but are NOT good matches — the corpus that makes false-hill-climbing
# detectable. Scored against their source (the canonical woman). See
# loop/tests/fixtures/README.md (hard_neg/ is gated; borderline/ is deliberately not).
echo "HARD NEGATIVES (plausible-but-wrong, must score <= $NEG_MAX):"
if compgen -G "loop/tests/fixtures/hard_neg/*.png" >/dev/null; then
  for f in loop/tests/fixtures/hard_neg/*.png; do
    s=$(score "$f" "$WOMAN_SRC")
    if python3 -c "import sys; sys.exit(0 if $s <= $NEG_MAX else 1)"; then
      note "$(basename "$f" .png)" "d_score=$s  OK (<=$NEG_MAX)"; ok=$((ok+1))
    else
      note "$(basename "$f" .png)" "d_score=$s  FAIL (want <=$NEG_MAX)"; fail=$((fail+1))
    fi
    NEGS="$NEGS $s"
  done
else
  note "hard negatives" "MISSING fixtures (run loop/tests/make_hard_negatives.py)"; fail=$((fail+1))
fi

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

# MARGIN + monotonicity: the worst good must clear the best hard negative by a gap,
# and the tiers must be strictly ordered (good > hard_neg > degenerate). This is the
# core anti-false-hill-climb assertion — it forbids the good and bad bands from
# creeping toward each other, which is exactly what a false hill would do.
echo "SEPARATION (margin >= $MARGIN, monotonic tiers):"
python3 - "$MARGIN" "$GOODS" "$NEGS" "$DEGENS" <<'PY'
import sys
margin = int(sys.argv[1])
goods  = [float(x) for x in sys.argv[2].split()]
negs   = [float(x) for x in sys.argv[3].split()]
degens = [float(x) for x in sys.argv[4].split()]
mg, xn, xd = min(goods), (max(negs) if negs else -1), (max(degens) if degens else -1)
gap = mg - xn
ok = True
def line(label, cond, detail):
    global ok
    ok = ok and cond
    print(f'  {label:26} {detail}  {"OK" if cond else "FAIL"}')
line("margin", gap >= margin, f"min_good={mg:.0f} - max_neg={xn:.0f} = {gap:.0f} (>= {margin})")
line("good > hard_neg", mg > xn, f"min_good={mg:.0f} > max_neg={xn:.0f}")
line("hard_neg > degenerate", xn > xd, f"max_neg={xn:.0f} > max_degen={xd:.0f}")
sys.exit(0 if ok else 1)
PY
if [ $? -eq 0 ]; then ok=$((ok+1)); else fail=$((fail+1)); fi

echo "  ── passed=$ok failed=$fail"
[ "$fail" -eq 0 ] || exit 1
