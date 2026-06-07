#!/usr/bin/env bash
# loop/scheduled_run.sh — one self-contained unattended ralph run driven ENTIRELY
# by the local LLM (no Claude Code quota):
#   - claude -p is routed to the litellm proxy -> neuromancer vLLM (Qwen3.5-122B)
#   - scoring is deterministic (loop/dscore.py) — no vision backend needed
#   - caffeinate keeps the Mac awake for the duration
#
# Budget (the agreed "short" run; override via env):
#   DURATION_SEC=5400 (90 min)  MAX_ITERS=30   MODEL=claude-sonnet-4-6 (->qwen)
#
# Usage:  ./loop/scheduled_run.sh         (run now)
# Logs:   loop/log/scheduled_<stamp>.log
set -u
cd "$(dirname "$0")/.."
mkdir -p loop/log
stamp=$(date '+%Y%m%d-%H%M%S')
LOG="loop/log/scheduled_${stamp}.log"
exec > >(tee -a "$LOG") 2>&1

echo "[scheduled] start $(date '+%Y-%m-%d %H:%M:%S')"
source .venv/bin/activate

# Driver = the constrained proposer (loop/proposer.py): the harness drives, the
# local LLM proposes ONE edit per tick. Talks to neuromancer DIRECTLY — no
# litellm/Claude Code (the vLLM emits tool calls as text Claude Code won't run,
# and a free agent loop over-works; the proposer is reliable + fast ~10s/tick).
export DRIVER=proposer

# NOTE: no Flask app needed. render_tick.sh renders IN-PROCESS via loop/render.py
# (a fresh import per tick) so the loop's engine edits actually take effect — the
# long-running app never reloaded them. The judge talks to neuromancer directly.

# Pre-flight: judge backend reachable?
curl -s --max-time 5 -o /dev/null -w '[scheduled] neuromancer judge HTTP %{http_code}\n' \
  http://neuromancer:8000/v1/models || echo "[scheduled] WARN: judge probe failed"

# 5. Run the loop, kept awake by caffeinate. Budget = agreed short run.
echo "[scheduled] launching ralph (DURATION=${DURATION_SEC:-5400}s MAX_ITERS=${MAX_ITERS:-30})"
DURATION_SEC="${DURATION_SEC:-5400}" \
MAX_ITERS="${MAX_ITERS:-30}" \
MODEL="${MODEL:-claude-sonnet-4-6}" \
SLEEP_BETWEEN="${SLEEP_BETWEEN:-5}" \
  caffeinate -i -s ./loop/ralph.sh

echo "[scheduled] done $(date '+%Y-%m-%d %H:%M:%S')"
