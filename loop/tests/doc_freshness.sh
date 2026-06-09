#!/usr/bin/env bash
# loop/tests/doc_freshness.sh — "doc-gardening" gate against config drift.
#
# WHY: the tuning docs (CLAUDE.md, loop/PROMPT.md, loop/IDEAS.md) used to hard-code
# MARCH_* knob VALUES (e.g. "MARCH_TONE ≈ 4.6", "4.0 → 5.0"). The optimizer then
# moved the live engine/march_params.json well away from those (MARCH_TONE=12.0,
# MARCH_EDGE=0.857), so the agent was being steered by numbers that no longer exist
# — the harness-engineering failure mode "what the agent sees wrongly doesn't exist".
#
# RULE: prose tuning docs must NOT pin a numeric value next to a searched knob name.
# The live values belong ONLY in engine/march_params.json (shown to the agent via the
# generated loop/STATUS.md); bounds belong ONLY in engine.march.PARAM_BOUNDS. Docs may
# name the knobs and give DIRECTIONAL guidance ("raise to densify shadows") — just no
# frozen numbers to rot.
#
# Exit: 0 pass · non-zero fail (prints the offending lines + how to fix).
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import re, sys
from pathlib import Path

DOCS = ["CLAUDE.md", "loop/PROMPT.md", "loop/IDEAS.md"]
# the 6 SEARCHED knobs (engine.march.PARAM_BOUNDS). MARCH_NORM_* are fixed, not
# tuned, so a doc may state them; they're deliberately excluded here.
KNOBS = "BASE|TONE|EDGE|GAMMA|CONTRAST|BLUR"
# A line pins a value if it names a searched knob AND carries a decimal number — the
# decimals in these docs are always frozen knob values (e.g. "≈4.6", "4.0 → 5.0").
# (MARCH_NORM_* is excluded above; integer render params like levels=111 are stable.)
KNOB = re.compile(rf"MARCH_(?:{KNOBS})\b")
DECIMAL = re.compile(r"\d+\.\d+")
# "Currently 4.0 / Currently ~0.3" pins a value even when the knob name wrapped to
# the previous line, so flag that phrasing on its own.
CURRENTLY = re.compile(r"[Cc]urrently\s+~?\d")

offenders = []
for doc in DOCS:
    p = Path(doc)
    if not p.exists():
        continue
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if (KNOB.search(line) and DECIMAL.search(line)) or CURRENTLY.search(line):
            offenders.append((doc, n, line.strip()))

if offenders:
    print("FAIL: prose tuning docs pin MARCH_* knob values that drift from "
          "engine/march_params.json.\n")
    for doc, n, line in offenders:
        print(f"  {doc}:{n}: {line[:120]}")
    print("\nFIX: remove the frozen number; keep only the knob name + a directional "
          "phrase, and point at `loop/STATUS.md` for the live value & bounds.")
    sys.exit(1)

print(f"PASS: no pinned MARCH_* values in {', '.join(DOCS)} "
      "(live values stay in engine/march_params.json → loop/STATUS.md).")
PY
