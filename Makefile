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
.SHELLFLAGS := -eu -o pipefail -c
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: help install install-dev run dev run-stdio test clean dev-inspect format lint typecheck

help:
	@echo "Targets:"
	@echo "  install       Create venv & install dependencies"
	@echo "  install-dev   Install runtime + dev dependencies"
	@echo "  run           Run MCP server directly (stdio)"
	@echo "  dev           Run MCP server directly (stdio)"
	@echo "  run-stdio     Run via MCP CLI stdio transport (recommended)"
	@echo "  test          Run pytest (if tests folder exists)"
	@echo "  clean         Remove venv and caches"
	@echo "  dev-inspect   Open MCP Inspector connected to this server (dev only)"
	@echo "  format        Run Black + Ruff (fix)"
	@echo "  lint          Run Ruff checks"
	@echo "  typecheck     Run mypy type checks"

install:
	@if [ ! -d "$(VENV)" ]; then \
		python3 -m venv $(VENV); \
	fi
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: install
	$(PIP) install -r requirements-dev.txt || true

run: install
	MCP_LOG_LEVEL=DEBUG $(PYTHON) main.py

dev: install
	MCP_LOG_LEVEL=DEBUG $(PYTHON) main.py

run-stdio: install
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio main.py

test: install
	@if [ -d tests ]; then \
		$(PYTHON) -m pytest -q; \
	else \
		echo "(skipped) no tests directory"; \
	fi

format: install
	$(PYTHON) -m black .
	$(PYTHON) -m ruff check --fix .

lint: install
	$(PYTHON) -m ruff check .

typecheck: install
	$(PYTHON) -m mypy --ignore-missing-imports .

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache **/__pycache__ .ruff_cache .mypy_cache

# --- Dev-only helpers ---
# If you prefer uv, override: make dev-inspect INSPECTOR_CMD='uvx mcp dev ./main.py'
INSPECTOR_CMD ?= mcp dev ./main.py

dev-inspect: install
	MCP_LOG_LEVEL=DEBUG $(INSPECTOR_CMD)