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
#   - below floor    : d_score < GUARD_FLOOR (absolute quality bar)
#   - regression     : d_score < recent_best - GUARD_DROP (relative)
#   - regression-fine: d_fine  < recent_best - GUARD_FINE_DROP (the fine-hatch climb
#                      signal; d_score pins at 100 on the canonical, so this is what
#                      stops a tick trading away hatch quality while d_score holds)
#   - tests-failed   : a metric-PASS that touched engine/ but broke the app's unit
#                      tests (tests.test_app) — the metrics don't exercise them, so
#                      the suite runs here before any checkpoint (skip: GUARD_NO_TEST)
#
# Usage:   ./loop/guard_tick.sh <iter_number>
# Env:     GUARD_FLOOR(30) GUARD_DROP(8) GUARD_FINE_DROP(0.04) GUARD_DISABLE GUARD_NO_COMMIT
#          GUARD_NO_TEST GUARD_TEST_CMD(python -m unittest tests.test_app)
#          GUARD_NO_COMMIT = no git side effects at all: skips the PASS commit
#          AND the FAIL revert (use it for manual/dry-run testing).
#          GUARD_NO_TEST   = skip the unit-test gate (e.g. deps unavailable).
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

# d_fine tie-breaker: d_score pins at 100 on the canonical woman render, so the
# fine-hatch metric (dscore.py d_fine — fine-grid tone fidelity, reported-not-gated)
# is the real climb signal once d_score saturates. Don't let a tick trade fine-hatch
# quality away while d_score holds: FAIL if d_fine regressed vs recent best.
FINE_DROP = float(os.environ.get("GUARD_FINE_DROP", 0.04))
fcur = cur.get("d_fine")
if isinstance(fcur, (int, float)):
    fprior = [r.get("d_fine") for r in rows
              if r.get("iter") != iter_num
              and isinstance(r.get("d_fine"), (int, float))]
    fprior = fprior[-10:]
    if fprior:
        fbest = max(fprior)
        if fcur < fbest - FINE_DROP:
            print(f"FAIL regression-fine d_fine={fcur:.3f}<best{fbest:.3f}-{FINE_DROP:g}")
            sys.exit(0)

print(f"PASS d_score={d}" + (f" d_fine={fcur:.3f}" if isinstance(fcur, (int, float)) else ""))
PY
)

decision=${verdict%% *}
reason=${verdict#* }
ts=$(date '+%Y-%m-%d %H:%M:%S')

# ── test gate ───────────────────────────────────────────────────────────────
# A metric PASS isn't sufficient: the loop only edits engine/, and the canonical
# render + dscore don't exercise the app's unit tests — so a tick can satisfy
# d_score/d_fine yet break tests.test_app (this really happened with MAX_DIM
# 640→800, which the loop auto-committed). Before checkpointing a PASS that
# touched engine/, run the fast suite against the working tree; if it fails, flip
# to FAIL so the change is reverted, not committed. Skip with GUARD_NO_TEST;
# override the command with GUARD_TEST_CMD.
if [ "$decision" = "PASS" ] && [ -z "${GUARD_NO_TEST:-}" ] \
   && ! git diff --quiet -- engine/ 2>/dev/null; then
  mkdir -p loop/log
  if [ -x .venv/bin/python ]; then tpy=".venv/bin/python"; else tpy="python3"; fi
  test_cmd="${GUARD_TEST_CMD:-$tpy -m unittest tests.test_app}"
  if $test_cmd >loop/log/guard_test.log 2>&1; then
    echo "[guard] tests PASS — engine change is safe to checkpoint"
  else
    fail_line=$(grep -m1 -E '^(FAIL|ERROR):' loop/log/guard_test.log)
    decision="FAIL"
    reason="tests-failed ${fail_line:-see loop/log/guard_test.log}"
    echo "[guard] tests FAIL — $reason" >&2
  fi
fi

# Remediation note → loop/.guard_feedback. status.py folds this into STATUS.md so the
# NEXT tick's agent sees WHY the prior change was kept/reverted (the harness-engineering
# "inject remediation into the agent's context"). Map the verdict to a concrete nudge.
case "$reason" in
  regression-fine*) suggest="That change traded away fine-hatch tone fidelity (d_fine). It was reverted — try a DIFFERENT idea category (see IDEAS.md), not the same knob." ;;
  regression*)      suggest="That change regressed the primary d_score. Reverted — try a qualitatively different approach, or check d_diag/d_ink for what broke." ;;
  below-floor*)     suggest="Output was degenerate (below floor). Reverted — check the dscore gate inputs (d_ink in 0.05–0.85, d_peakedness, d_diag in band)." ;;
  tests-failed*)    suggest="The change passed the metrics but BROKE the app's unit tests — reverted. Run \`python -m unittest tests.test_app\` after engine edits; see loop/log/guard_test.log for the failure." ;;
  no-*|no\ *)       suggest="No score for this tick (render/score skipped). Re-run render_tick.sh + score_tick.sh before tuning." ;;
  *)                suggest="Kept as a checkpoint. Address the next-lowest metric in STATUS.md (steer by d_fine while d_score holds at 100)." ;;
esac
printf '_iter %03d · %s_\n\n- **%s** — %s\n- %s\n' \
  "$iter_num" "$ts" "$decision" "$reason" "$suggest" > loop/.guard_feedback

case "$decision" in
  PASS)
    # Best-so-far pointer: if this tick set a new max d_fine, snapshot its PNG so the
    # montage can show "current vs best" honestly. Pure read of metrics.jsonl.
    python3 - "$iter_num" <<'PY' || true
import json, shutil, sys
from pathlib import Path
it = int(sys.argv[1])
rows = []
for ln in Path("loop/metrics.jsonl").read_text().splitlines():
    ln = ln.strip()
    if ln:
        try: rows.append(json.loads(ln))
        except json.JSONDecodeError: pass
cur = next((r for r in reversed(rows) if r.get("iter") == it), None)
if not cur or not isinstance(cur.get("d_fine"), (int, float)):
    sys.exit(0)
prior = [r["d_fine"] for r in rows
         if r.get("iter") != it and isinstance(r.get("d_fine"), (int, float))]
if prior and cur["d_fine"] <= max(prior):
    sys.exit(0)   # not a new best
png = Path(f"loop/output/iter_{it:03d}.png")
if png.exists():
    shutil.copyfile(png, "loop/output/_best.png")
    Path("loop/output/_best.json").write_text(
        json.dumps({"iter": it, "d_fine": cur["d_fine"]}))
    print(f"[guard] new best d_fine={cur['d_fine']:.3f} (iter {it:03d}) → _best.png")
PY
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
