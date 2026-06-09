#!/usr/bin/env bash
# loop/tests/doc_freshness.sh — "doc-gardening" gate against config drift.
#
# WHY: docs that pin a config value go stale the moment the loop/optimizer moves it,
# and then the agent (or a human) is steered by a number that no longer exists — the
# harness-engineering failure mode "what the agent sees wrongly doesn't exist". This
# was real: the tuning docs said MARCH_TONE≈4.6 while the live JSON was 12.0, and the
# loop's MAX_DIM 640→800 change left CLAUDE.md/tech.md still saying 640.
#
# Two checks:
#   1. TUNED knobs (MARCH_*): the tuning docs must NOT pin a value at all. The live
#      values belong ONLY in engine/march_params.json (shown via loop/STATUS.md),
#      bounds ONLY in PARAM_BOUNDS. Docs name the knob + give DIRECTION, no numbers.
#   2. ARCHITECTURAL constants (MAX_DIM, THRESHOLD_POWER): docs MAY state them as
#      facts, but the stated number must MATCH the code. Semantic/historical mentions
#      (e.g. "THRESHOLD_POWER = 1.0 is linear", "~2.7 bug") are exempt.
#
# Exit: 0 pass · non-zero fail (prints the offending lines + how to fix).
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import re, sys
from pathlib import Path

offenders = []

# ── Check 1: tuned MARCH_* knobs must not be pinned in the tuning docs ───────
TUNING_DOCS = ["CLAUDE.md", "loop/PROMPT.md", "loop/IDEAS.md"]
KNOBS = "BASE|TONE|EDGE|GAMMA|CONTRAST|BLUR"   # the 6 searched knobs (PARAM_BOUNDS)
KNOB = re.compile(rf"MARCH_(?:{KNOBS})\b")
DECIMAL = re.compile(r"\d+\.\d+")
CURRENTLY = re.compile(r"[Cc]urrently\s+~?\d")   # catches a value when the knob name
                                                 # wrapped to the previous line
for doc in TUNING_DOCS:
    p = Path(doc)
    if not p.exists():
        continue
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if (KNOB.search(line) and DECIMAL.search(line)) or CURRENTLY.search(line):
            offenders.append((doc, n, line.strip(), "pinned MARCH_* value"))

# ── Check 2: architectural constants stated in docs must match the code ──────
# (name, source file, regex exempting semantic/historical mentions on a line)
CONSTS = [
    ("MAX_DIM", "engine/field.py", None),
    # THRESHOLD_POWER docs explain its SEMANTICS (1.0 = linear) and HISTORY (~2.7
    # bug), never its tuned value — exempt those so we only catch a real "current
    # value" claim that drifted.
    ("THRESHOLD_POWER", "engine/contour.py", re.compile(r"linear|even|cramm|~|\bold\b|\bbug\b", re.I)),
]
VALUE_DOCS = ["CLAUDE.md", "docs/tech.md", "docs/algorithm.md",
              "loop/PROMPT.md", "loop/IDEAS.md"]

def live_value(name, src):
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", Path(src).read_text(), re.MULTILINE)
    return m.group(1).rstrip(".") if m else None

for name, src, exempt in CONSTS:
    live = live_value(name, src)
    if live is None:
        continue
    # the value attached to the name on the same line: "NAME = N", "NAME=N", "NAME N"
    pat = re.compile(rf"{name}\s*[=:]?\s*~?([0-9]+(?:\.[0-9]+)?)")
    for doc in VALUE_DOCS:
        p = Path(doc)
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if exempt and exempt.search(line):
                continue
            m = pat.search(line)
            if m and m.group(1).rstrip(".") != live:
                offenders.append((doc, n, line.strip(),
                                  f"{name} says {m.group(1)} but code is {live}"))

if offenders:
    print("FAIL: docs drifted from code config.\n")
    for doc, n, line, why in offenders:
        print(f"  {doc}:{n} [{why}]: {line[:110]}")
    print("\nFIX: for MARCH_* knobs remove the number (point at loop/STATUS.md); for "
          "architectural constants update the doc to the code's current value.")
    sys.exit(1)

print("PASS: no pinned MARCH_* values, and MAX_DIM/THRESHOLD_POWER match the code.")
PY
