#!/usr/bin/env bash
# loop/guard_tick.sh — deterministic quality gate, run after score_tick.sh.
#
# WHY: the loop used to rely on Claude *noticing* a regression in-prompt and
# reverting it. The iter_034→035 history shows that's unreliable — a bad
# change persisted and the next tick built on top of it. This is the backstop.
#
# WHAT it does, from the latest loop/metrics.jsonl record for <iter>:
#   PASS  → commit engine/ as a loop checkpoint (so progress is durable AND a
#           future revert only rolls back to the last *good* tick, not baseline).
#   FAIL  → snapshot the diff to loop/log/reverts/*.patch (so it's recoverable),
#           then `git checkout -- engine/` (roll back to the last checkpoint) + log.
#   SKIP  → no d_score for the iter (the tick didn't render / score): can't
#           assess, so do nothing — never revert on a missing signal.
#
# Gates on the DETERMINISTIC d_score (0-100) from dscore.py — a single,
# backend-independent scale (no network, never "offline"). Degenerate output
# (near-blank / near-solid / blob / noise) is already driven to ~0 by dscore's
# own gate, so it trips the absolute floor here automatically.
#
# FAIL conditions:
#   - below floor   : d_score < GUARD_FLOOR (absolute quality bar)
#   - regression    : d_score < recent_best - GUARD_DROP (relative)
#
# Usage:   ./loop/guard_tick.sh <iter_number>
# Env:     GUARD_FLOOR(30) GUARD_DROP(8) GUARD_DISABLE GUARD_NO_COMMIT
#          GUARD_NO_COMMIT = no git side effects at all: skips the PASS commit
#          AND the FAIL revert (use it for manual/dry-run testing).
set -u
cd "$(dirname "$0")/.."

iter_num=$((10#${1:?iter number required}))   # force base-10 ('033' is octal otherwise)

if [ -n "${GUARD_DISABLE:-}" ]; then
  echo "[guard] disabled via GUARD_DISABLE"; exit 0
fi

# Decide PASS/FAIL/SKIP in python (testable in isolation; pure read of metrics).
verdict=$(python3 - "$iter_num" <<'PY'
import json, os, sys

iter_num = int(sys.argv[1])
FLOOR = float(os.environ.get("GUARD_FLOOR", 30))   # absolute d_score floor (reject
#   degenerate/broken; the current engine baseline ~47 sits above it and the
#   relative-regression gate does the real work of preventing backsliding)
DROP  = float(os.environ.get("GUARD_DROP", 8))     # max allowed drop vs recent best

rows = []
try:
    with open("loop/metrics.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except json.JSONDecodeError: pass
except FileNotFoundError:
    print("SKIP no-metrics-file"); sys.exit(0)

# Latest record for this iter (the one score_tick just appended).
cur = next((r for r in reversed(rows) if r.get("iter") == iter_num), None)
if cur is None:
    print(f"SKIP no-record-for-iter-{iter_num}"); sys.exit(0)

d = cur.get("d_score")
if d is None or not isinstance(d, (int, float)):
    print("SKIP no-d_score"); sys.exit(0)

# Absolute floor (degenerate output is ~0 from dscore's gate → caught here).
if d < FLOOR:
    print(f"FAIL below-floor d_score={d}<{FLOOR:g}"); sys.exit(0)

# Relative regression vs recent best among PRIOR scored ticks.
prior = [r.get("d_score") for r in rows
         if r.get("iter") != iter_num
         and isinstance(r.get("d_score"), (int, float))]
prior = prior[-10:]
if prior:
    best = max(prior)
    if d < best - DROP:
        print(f"FAIL regression d_score={d}<best{best}-{DROP:g}"); sys.exit(0)

print(f"PASS d_score={d}")
PY
)

decision=${verdict%% *}
reason=${verdict#* }
ts=$(date '+%Y-%m-%d %H:%M:%S')

case "$decision" in
  PASS)
    if git diff --quiet -- engine/ 2>/dev/null; then
      echo "[guard] PASS ($reason) — engine/ unchanged, nothing to checkpoint"
    elif [ -n "${GUARD_NO_COMMIT:-}" ]; then
      echo "[guard] PASS ($reason) — GUARD_NO_COMMIT set, leaving engine/ uncommitted"
    else
      git add -- engine/
      git commit -q -m "loop(auto): iter $(printf '%03d' "$iter_num") checkpoint — $reason" \
        && echo "[guard] PASS ($reason) — committed engine/ checkpoint"
    fi
    ;;
  FAIL)
    if [ -n "${GUARD_NO_COMMIT:-}" ]; then
      # No-git-side-effects mode (e.g. manual/dry-run testing): report what WOULD
      # be reverted but DO NOT touch the working tree — `git checkout -- engine/`
      # would discard ANY uncommitted engine/ changes, including pre-existing WIP
      # the tick didn't make.
      echo "[guard] FAIL ($reason) — GUARD_NO_COMMIT set, NOT reverting engine/ (would run: git checkout -- engine/)" >&2
    else
      echo "[guard] FAIL ($reason) — reverting engine/ to last checkpoint" >&2
      # Safety net: snapshot the to-be-discarded diff so a revert is NEVER
      # unrecoverable (git checkout destroys uncommitted changes permanently).
      if ! git diff --quiet -- engine/ 2>/dev/null; then
        mkdir -p loop/log/reverts
        patch="loop/log/reverts/iter_$(printf '%03d' "$iter_num")_$(date +%Y%m%d-%H%M%S).patch"
        git diff -- engine/ > "$patch" 2>/dev/null \
          && echo "[guard] saved reverted diff → $patch (restore: git apply $patch)"
      fi
      git checkout -- engine/ 2>/dev/null \
        && echo "[guard] reverted engine/ (git checkout)" \
        || echo "[guard] WARNING: git checkout -- engine/ failed" >&2
      printf '[%s] guard auto-revert iter %s: %s\n' "$ts" "$iter_num" "$reason" \
        >> loop/log/run.log
    fi
    ;;
  SKIP)
    echo "[guard] SKIP ($reason) — no commit, no revert"
    ;;
  *)
    echo "[guard] WARNING: unparseable verdict: $verdict" >&2
    ;;
esac
