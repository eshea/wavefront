#!/usr/bin/env bash
# loop/litellm.sh — start/stop/status helpers for the litellm proxy
# that translates claude-code's Anthropic-format requests to the local
# Qwen3 vLLM at 192.168.50.135:8000.
#
# Usage:
#   ./loop/litellm.sh start    # background; logs to loop/log/litellm.log
#   ./loop/litellm.sh stop     # graceful stop via PID file
#   ./loop/litellm.sh status   # health + recent log tail
#   ./loop/litellm.sh restart

set -u
cd "$(dirname "$0")/.."

PROXY_PORT=4000
PID_FILE=loop/.litellm.pid
LOG_FILE=loop/log/litellm.log
CONFIG=loop/litellm_config.yaml

case "${1:-status}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[litellm] already running pid=$(cat "$PID_FILE")"
      exit 0
    fi
    mkdir -p loop/log
    source .venv/bin/activate
    nohup litellm --config "$CONFIG" --port "$PROXY_PORT" \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    disown
    echo "[litellm] started pid=$(cat "$PID_FILE") port=$PROXY_PORT"
    # Brief wait + health check
    for i in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      code=$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" \
        "http://localhost:$PROXY_PORT/health/liveliness" 2>/dev/null)
      if [ "$code" = "200" ]; then
        echo "[litellm] ready (HTTP 200 after ${i}s)"
        exit 0
      fi
    done
    echo "[litellm] WARNING: did not become healthy after 10s — check $LOG_FILE"
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      pid=$(cat "$PID_FILE")
      kill "$pid" 2>/dev/null && echo "[litellm] stopped pid=$pid"
      rm -f "$PID_FILE"
    else
      pkill -f "litellm --config $CONFIG" 2>/dev/null \
        && echo "[litellm] killed by pattern" \
        || echo "[litellm] not running"
    fi
    ;;

  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[litellm] pid=$(cat "$PID_FILE")"
    else
      echo "[litellm] no PID file or process dead"
    fi
    code=$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" \
      "http://localhost:$PROXY_PORT/health/liveliness" 2>/dev/null)
    echo "[litellm] health: HTTP $code"
    if [ -f "$LOG_FILE" ]; then
      echo "[litellm] last 5 log lines:"
      tail -5 "$LOG_FILE"
    fi
    ;;

  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;

  *)
    echo "usage: $0 {start|stop|status|restart}"
    exit 2
    ;;
esac
