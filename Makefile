ARCHETYPE ?= python-web
APP_PORT ?= 8002
HEALTH_PATH ?= /healthz
PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 5055
HOST ?= 127.0.0.1
FLASK_DEBUG ?= 1
START_FLASK_DEBUG ?= 0
TMPDIR ?= /tmp
SERVER_DIR := $(TMPDIR)/wavefront
SERVER_PID := $(SERVER_DIR)/server.pid
SERVER_LOG := $(SERVER_DIR)/server.log

.PHONY: ci build test lint deploy health logs run start stop restart status server-logs install migrate conformance

ci: install lint test build

install:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PIP) install -r requirements.txt

build:
	$(PY) -m compileall app.py engine tests

test:
	$(PY) -m unittest tests.test_app

lint:
	$(PY) -m compileall app.py engine tests

run:
	HOST=$(HOST) PORT=$(PORT) FLASK_DEBUG=$(FLASK_DEBUG) $(PY) app.py

start:
	@mkdir -p $(SERVER_DIR)
	@if [ -f $(SERVER_PID) ] && kill -0 "$$(cat $(SERVER_PID))" >/dev/null 2>&1; then \
		echo "[start] already running: $$(cat $(SERVER_PID))"; \
		exit 0; \
	fi
	@$(PY) -c 'import os, pathlib, subprocess, sys; d = pathlib.Path(r"$(SERVER_DIR)"); d.mkdir(parents=True, exist_ok=True); env = os.environ.copy(); env.update({"HOST": "$(HOST)", "PORT": "$(PORT)", "FLASK_DEBUG": "$(START_FLASK_DEBUG)"}); log = open(r"$(SERVER_LOG)", "ab"); proc = subprocess.Popen([sys.executable, "app.py"], cwd=r"$(CURDIR)", env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True); pathlib.Path(r"$(SERVER_PID)").write_text(str(proc.pid)); print(f"[start] pid={proc.pid} log=$(SERVER_LOG)")'

stop:
	@if [ -f $(SERVER_PID) ]; then \
		pid="$$(cat $(SERVER_PID))"; \
		if kill -0 "$$pid" >/dev/null 2>&1; then \
			kill "$$pid"; \
			echo "[stop] sent SIGTERM to $$pid"; \
		else \
			echo "[stop] stale pidfile $$pid"; \
		fi; \
		rm -f $(SERVER_PID); \
	else \
		echo "[stop] no pidfile at $(SERVER_PID)"; \
	fi

restart: stop start

status:
	@if [ -f $(SERVER_PID) ] && kill -0 "$$(cat $(SERVER_PID))" >/dev/null 2>&1; then \
		echo "[status] running pid=$$(cat $(SERVER_PID))"; \
	else \
		echo "[status] not running"; \
	fi

server-logs:
	tail -f $(SERVER_LOG)

deploy: install build migrate
	HOST=0.0.0.0 PORT=$(APP_PORT) pm2 startOrReload ecosystem.config.cjs --update-env
	$(MAKE) health

migrate:
	@echo "no migrations"

health:
	@url="http://127.0.0.1:$(APP_PORT)$(HEALTH_PATH)"; \
	echo "[health] checking $$url"; \
	for i in $$(seq 1 15); do \
		curl -fsS --max-time 5 "$$url" >/dev/null 2>&1 && { echo "[health] OK"; exit 0; }; \
		echo "[health] attempt $$i/15 failed"; \
		sleep 2; \
	done; \
	echo "[health] FAILED: $$url" >&2; exit 1

logs:
	pm2 logs wavefront --lines 100

conformance:
	@echo "conformance is enforced by armitage contract files"
