.PHONY: dev run tools build dist publish clean

PY ?= python3

dev:
	uvx --from oke-mcp-server oke-mcp-server --transport stdio

run:
	$(PY) -m oke_mcp_server.main --transport stdio

tools:
	$(PY) -m oke_mcp_server.main --print-tools

build:
	$(PY) -m build

dist: clean build

publish:
	$(PY) -m twine upload dist/*

clean:
	rm -rf dist build *.egg-info