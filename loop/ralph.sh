#!/usr/bin/env bash
# Ralph Wiggum Loop — dumb shell wrapper, smart-per-iteration Claude.
#
# Runs a self-driving improvement loop on WAVEFRONT. Each tick is one
# `claude -p` invocation that reads loop/PROMPT.md, makes one small
# change, tests it, and appends to loop/EXPERIMENT_LOG.md.
#
# Budgets (override via env):
#   DURATION_SEC   wall-clock seconds (default 5400 = 90 min)
#   MAX_ITERS      hard iteration cap (default 200)
#   TOKEN_BUDGET   cumulative tokens cap (default 6_000_000)
#   MODEL          claude model (default claude-sonnet-4-6)
#   SLEEP_BETWEEN  pause between ticks (default 12 sec)
#
# Stop early:
#   touch loop/STOP        — loop notices at next tick and exits
#   Ctrl-C                 — trapped, exits cleanly

set -u

cd "$(dirname "$0")/.."

DURATION_SEC=${DURATION_SEC:-5400}
MAX_ITERS=${MAX_ITERS:-200}
TOKEN_BUDGET=${TOKEN_BUDGET:-6000000}
MODEL=${MODEL:-claude-sonnet-4-6}
SLEEP_BETWEEN=${SLEEP_BETWEEN:-12}
HOLDOUT_EVERY=${HOLDOUT_EVERY:-10}   # run the holdout overfit-check every N ticks

mkdir -p loop/log loop/output

ITER_FILE=loop/.iter
ITER=$(cat "$ITER_FILE" 2>/dev/null || echo 1)

start_ts=$(date +%s)
total_in=0
total_out=0
total_cache_read=0

stopping=0
trap 'echo ""; echo "[ralph] caught signal, finishing current tick"; stopping=1' INT TERM

printf '\n'
printf '═════════════════════════════════════════════════════════\n'
printf ' RALPH LOOP · WAVEFRONT\n'
printf ' duration=%ss  max_iters=%s  token_budget=%s\n' "$DURATION_SEC" "$MAX_ITERS" "$TOKEN_BUDGET"
printf ' model=%s  sleep=%ss  holdout_every=%s\n' "$MODEL" "$SLEEP_BETWEEN" "$HOLDOUT_EVERY"
printf ' started=%s  iter=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ITER"
printf '═════════════════════════════════════════════════════════\n'

while true; do
  now=$(date +%s)
  elapsed=$((now - start_ts))

  if [ -f loop/STOP ]; then
    printf '[ralph] STOP file present, halting.\n'
    rm -f loop/STOP
    break
  fi
  if [ $stopping -eq 1 ]; then
    printf '[ralph] signal stop.\n'
    break
  fi
  if [ "$elapsed" -ge "$DURATION_SEC" ]; then
    printf '[ralph] duration budget hit (%ss / %ss).\n' "$elapsed" "$DURATION_SEC"
    break
  fi
  if [ "$ITER" -gt "$MAX_ITERS" ]; then
    printf '[ralph] max iters reached (%s).\n' "$MAX_ITERS"
    break
  fi
  if [ "$((total_in + total_out))" -ge "$TOKEN_BUDGET" ]; then
    printf '[ralph] token budget hit (%s).\n' "$((total_in + total_out))"
    break
  fi

  iter_pad=$(printf '%03d' "$ITER")
  log_file="loop/log/iter_${iter_pad}.json"
  txt_file="loop/log/iter_${iter_pad}.txt"

  printf '\n[ralph] iter %s — elapsed=%ss cum_tok=%s\n' \
    "$iter_pad" "$elapsed" "$((total_in + total_out))"

  # Write iter number so the prompt can pick it up
  printf '%s' "$ITER" > "$ITER_FILE"

  # Invoke the driver with a per-tick wall timeout (macOS has no `timeout`
  # binary by default; emulate by backgrounding and killing).
  #   DRIVER=agent  -> loop/agent.py (local vLLM drives the tick directly)
  #   DRIVER=claude -> claude -p     (real Claude Code, default)
  if [ "${DRIVER:-claude}" = "agent" ]; then
    python loop/agent.py > "$log_file" 2> "$txt_file" &
  else
    claude -p "$(cat loop/PROMPT.md)" \
      --model "$MODEL" \
      --output-format json \
      --dangerously-skip-permissions \
      --permission-mode bypassPermissions \
      > "$log_file" 2> "$txt_file" &
  fi
  claude_pid=$!

  # Watch for timeout in a subshell that signals the main proc.
  # 600s = 10 min — generous enough that build+test+document fits without
  # the iter getting SIGTERM'd mid-write.
  ( sleep 600; kill -TERM "$claude_pid" 2>/dev/null ) &
  watcher_pid=$!

  wait "$claude_pid"
  exit_code=$?
  kill "$watcher_pid" 2>/dev/null
  wait "$watcher_pid" 2>/dev/null

  if [ $exit_code -ne 0 ]; then
    printf '[ralph] claude exited %s — see %s\n' "$exit_code" "$txt_file"
  fi

  # Parse usage from response
  in_tok=$(jq -r '.usage.input_tokens // 0' "$log_file" 2>/dev/null)
  out_tok=$(jq -r '.usage.output_tokens // 0' "$log_file" 2>/dev/null)
  cache_read=$(jq -r '.usage.cache_read_input_tokens // 0' "$log_file" 2>/dev/null)
  [ -z "$in_tok" ] && in_tok=0
  [ -z "$out_tok" ] && out_tok=0
  [ -z "$cache_read" ] && cache_read=0

  total_in=$((total_in + in_tok))
  total_out=$((total_out + out_tok))
  total_cache_read=$((total_cache_read + cache_read))

  printf '[ralph] iter %s done · in=%s out=%s cache_read=%s · cum_in=%s cum_out=%s\n' \
    "$iter_pad" "$in_tok" "$out_tok" "$cache_read" "$total_in" "$total_out"

  # Auto-score the tick's output (pixel metrics + visual judge).
  # Best effort — failures don't stop the loop.
  ./loop/score_tick.sh "$ITER" 2>/dev/null || true

  # Deterministic quality gate: checkpoint engine/ on a good tick, or revert
  # it on a regression. Backstop for when Claude fails to self-revert.
  ./loop/guard_tick.sh "$ITER" || true

  # Periodic holdout overfit-check (renders + judges an unseen image).
  if [ "$HOLDOUT_EVERY" -gt 0 ] && [ $((ITER % HOLDOUT_EVERY)) -eq 0 ]; then
    printf '[ralph] holdout overfit-check at iter %s\n' "$iter_pad"
    ./loop/tests/holdout.sh || true
  fi

  ITER=$((ITER + 1))
  printf '%s' "$ITER" > "$ITER_FILE"

  sleep "$SLEEP_BETWEEN"
done

# Final holdout overfit-check on the way out (best effort).
printf '\n[ralph] final holdout overfit-check\n'
./loop/tests/holdout.sh || true

printf '\n═════════════════════════════════════════════════════════\n'
printf ' RALPH LOOP ENDED\n'
printf ' finished=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
printf ' iters_done=%s\n' "$((ITER - 1))"
printf ' total_input_tokens=%s\n' "$total_in"
printf ' total_output_tokens=%s\n' "$total_out"
printf ' total_cache_read_tokens=%s\n' "$total_cache_read"
printf '═════════════════════════════════════════════════════════\n'
