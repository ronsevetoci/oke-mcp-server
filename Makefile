VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	MCP_LOG_LEVEL=DEBUG $(PYTHON) main.py

run-stdio:
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio main.py

test:
	$(PYTHON) -m pytest tests

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache
# OKE MCP Server — Unified Makefile
# Usage:
#   make install        # create venv (if missing) & install deps
#   make run            # run the MCP server directly (stdio JSON-RPC)
#   make run-stdio      # run via MCP CLI stdio transport (recommended for testing)
#   make test           # run pytest (if tests exist)
#   make clean          # remove venv and caches
#   make dev-inspect    # (dev) open MCP Inspector connected to this server
#   make help           # list targets

SHELL := /bin/bash
VENV ?= venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install run run-stdio test clean dev-inspect

help:
	@echo "Targets:"
	@echo "  install       Create venv & install dependencies"
	@echo "  run           Run MCP server directly (stdio)"
	@echo "  run-stdio     Run via MCP CLI stdio transport (recommended)"
	@echo "  test          Run pytest (if tests folder exists)"
	@echo "  clean         Remove venv and caches"
	@echo "  dev-inspect   Open MCP Inspector connected to this server (dev only)"

install:
	@if [ ! -d "$(VENV)" ]; then \
		python3 -m venv $(VENV); \
		$(PIP) install --upgrade pip; \
	fi
	$(PIP) install -r requirements.txt

# Run the MCP server directly (reads JSON-RPC from stdin)
run: install
	MCP_LOG_LEVEL=DEBUG $(PYTHON) main.py

# Preferred for manual testing: leverage the MCP CLI stdio transport
run-stdio: install
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio $(PYTHON) main.py

# Run tests (no-op if tests/ missing)
test: install
	@if [ -d tests ]; then \
		$(PYTHON) -m pytest -q; \
	else \
		echo "(skipped) no tests directory"; \
	fi

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache **/__pycache__

# --- Dev-only helpers ---
# If you prefer uv, override: make dev-inspect INSPECTOR_CMD='uvx mcp dev ./main.py'
INSPECTOR_CMD ?= mcp dev ./main.py

dev-inspect: install
	MCP_LOG_LEVEL=DEBUG $(INSPECTOR_CMD)