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
#   FAIL  → `git checkout -- engine/` (roll back to the last checkpoint) + log.
#   SKIP  → judge unavailable (e.g. vLLM offline, judge_score -1): can't assess
#           quality, so do nothing — never revert on a missing signal.
#
# FAIL conditions:
#   - degenerate output: ink_coverage > GUARD_INK_HI (near solid black)
#                     or ink_coverage < GUARD_INK_LO (near blank)
#   - judge regression : judge_score < GUARD_FLOOR (absolute), or
#                        judge_score < recent_best - GUARD_DROP (relative).
# NOTE: we gate on the JUDGE (de-noised median from judge.py --samples), not on
# pixel metrics — measured, pixel metrics do NOT separate subtle "blob" failures
# from good outputs (judge-85 and judge-15 renders differ by only a few %).
#
# Usage:   ./loop/guard_tick.sh <iter_number>
# Env:     GUARD_FLOOR(8) GUARD_DROP(12) GUARD_INK_HI(0.92) GUARD_INK_LO(0.03)
#          GUARD_FLOORS("8000=8,5002=8") GUARD_DISABLE GUARD_NO_COMMIT
# Scale note: judge.py now uses the HARSH reference-replication rubric, where
# current attempts score ~5-25 and a genuine artist output ~90-100. So the
# absolute floor is LOW (it only rejects near-degenerate output; the ink_coverage
# gate already catches blank/solid renders), and climbing is driven by the
# relative-regression gate (revert if judge < recent_best - GUARD_DROP). Floors
# are still matched per backend by substring of judge_backend so a cross-scale
# fallback can't trigger a false revert.
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
FLOOR  = float(os.environ.get("GUARD_FLOOR", 8))
DROP   = float(os.environ.get("GUARD_DROP", 12))
INK_HI = float(os.environ.get("GUARD_INK_HI", 0.92))
INK_LO = float(os.environ.get("GUARD_INK_LO", 0.03))
# Per-backend floor map "substr=floor,...". With the harsh resemblance rubric the
# floor only needs to reject near-degenerate output (the ink gate handles blank/
# solid); current attempts legitimately sit ~5-25 while climbing toward ~90, so
# keep this LOW. A backend matching no key falls back to GUARD_FLOOR.
FLOORS = os.environ.get("GUARD_FLOORS", "8000=8,5002=8")

def floor_for(backend: str) -> float:
    for pair in FLOORS.split(","):
        if "=" in pair:
            key, val = pair.split("=", 1)
            if key.strip() and key.strip() in (backend or ""):
                try: return float(val)
                except ValueError: pass
    return FLOOR

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

judge   = cur.get("judge_score")
ink     = cur.get("ink_coverage")
backend = cur.get("judge_backend", "")

if judge is None or judge < 0:
    print("SKIP judge-unavailable"); sys.exit(0)

# Degenerate-output guard (the only thing pixels reliably catch).
if ink is not None and ink > INK_HI:
    print(f"FAIL degenerate-solid ink={ink:.3f}>{INK_HI}"); sys.exit(0)
if ink is not None and ink < INK_LO:
    print(f"FAIL degenerate-blank ink={ink:.3f}<{INK_LO}"); sys.exit(0)

# Absolute floor, on this backend's scale.
floor = floor_for(backend)
if judge < floor:
    print(f"FAIL below-floor judge={judge}<{floor:g} (backend={backend or '?'})")
    sys.exit(0)

# Relative regression vs recent best — only among PRIOR ticks scored by the
# SAME backend, so an auto-fallback to a different-scale judge can't look like
# a regression. (If this backend is unknown, compare within unknowns too.)
prior = [r.get("judge_score") for r in rows
         if r.get("iter") != iter_num
         and r.get("judge_backend", "") == backend
         and isinstance(r.get("judge_score"), (int, float))
         and r.get("judge_score") >= 0]
prior = prior[-10:]
if prior:
    best = max(prior)
    if judge < best - DROP:
        print(f"FAIL regression judge={judge}<best{best}-{DROP:g}"); sys.exit(0)

print(f"PASS judge={judge} ink={ink} backend={backend or '?'}")
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
    echo "[guard] FAIL ($reason) — reverting engine/ to last checkpoint" >&2
    git checkout -- engine/ 2>/dev/null \
      && echo "[guard] reverted engine/ (git checkout)" \
      || echo "[guard] WARNING: git checkout -- engine/ failed" >&2
    printf '[%s] guard auto-revert iter %s: %s\n' "$ts" "$iter_num" "$reason" \
      >> loop/log/run.log
    ;;
  SKIP)
    echo "[guard] SKIP ($reason) — no commit, no revert"
    ;;
  *)
    echo "[guard] WARNING: unparseable verdict: $verdict" >&2
    ;;
esac
