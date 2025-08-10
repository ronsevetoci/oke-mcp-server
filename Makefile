# OKE MCP Server — Unified Makefile
# Usage:
#   make setup        # create venv (if missing) & install deps (add DEV=1 for dev deps)
#   make run          # run the MCP server directly (stdio JSON-RPC)
#   make run-stdio    # run via MCP CLI stdio transport (recommended for testing)
#   make test         # run pytest (if tests exist)
#   make clean        # remove venv and caches
#   make dev-inspect  # (dev) open MCP Inspector connected to this server
#   make package      # build and upload package to PyPI
#   make help         # list targets

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: help setup run run-stdio test clean dev-inspect format lint typecheck package

help:
	@echo "Targets:"
	@echo "  setup         Create venv & install dependencies (add DEV=1 for dev deps)"
	@echo "  run           Run MCP server directly (stdio)"
	@echo "  run-stdio     Run via MCP CLI stdio transport (recommended)"
	@echo "  test          Run pytest (if tests folder exists)"
	@echo "  clean         Remove venv and caches"
	@echo "  dev-inspect   Open MCP Inspector connected to this server (dev only)"
	@echo "  package       Build and upload package to PyPI"
	@echo "  format        Run Black + Ruff (fix)"
	@echo "  lint          Run Ruff checks"
	@echo "  typecheck     Run mypy type checks"

setup:
	@if [ ! -d "$(VENV)" ]; then \
		python3 -m venv $(VENV); \
	fi
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@if [ "${DEV}" = "1" ]; then \
		$(PIP) install -r requirements-dev.txt; \
	fi

run: setup
	MCP_LOG_LEVEL=DEBUG $(PYTHON) main.py

run-stdio: setup
	MCP_LOG_LEVEL=DEBUG uvx mcp -t stdio main.py

test: setup
	@if [ -d tests ]; then \
		$(PYTHON) -m pytest -q; \
	else \
		echo "(skipped) no tests directory"; \
	fi

format: setup
	$(PYTHON) -m black .
	$(PYTHON) -m ruff check --fix .

lint: setup
	$(PYTHON) -m ruff check .

typecheck: setup
	$(PYTHON) -m mypy --ignore-missing-imports .

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache **/__pycache__ .ruff_cache .mypy_cache dist build *.egg-info

package: setup
	$(PYTHON) -m build
	$(PYTHON) -m twine upload dist/*

# --- Dev-only helpers ---
INSPECTOR_CMD ?= uvx mcp dev ./main.py

dev-inspect: setup
	MCP_LOG_LEVEL=DEBUG $(INSPECTOR_CMD)