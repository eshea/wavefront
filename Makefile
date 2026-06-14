ARCHETYPE ?= A
APP_PORT ?= 8002
HEALTH_PATH ?= /healthz
PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: ci build test lint deploy health logs install migrate conformance

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
