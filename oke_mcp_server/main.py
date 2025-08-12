#!/usr/bin/env python3
from __future__ import annotations
import argparse
import logging
import os
import sys
from importlib.metadata import version, PackageNotFoundError
from fastmcp import FastMCP
from .config import settings, get_effective_defaults
import signal

# Import tools (registration via decorators)
from .tools.k8s import k8s_list, k8s_get     # noqa: F401
from .tools.oke_cluster import oke_list_clusters, oke_get_cluster  # noqa: F401
from .tools.metrics import oke_list_node_metrics, oke_list_pod_metrics  # noqa: F401
from .tools.events import oke_list_events  # noqa: F401

SERVER_NAME = "OKE MCP Server"
try:
    __version__ = version("oke-mcp-server")
except PackageNotFoundError:
    __version__ = "0.0.0-local"

def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="OKE MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio"], help="MCP transport")
    parser.add_argument("--print-tools", action="store_true", help="List tools and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("oke-mcp-server")
    log.info("Starting %s v%s", SERVER_NAME, __version__)

    def _graceful_exit(signum, frame):
        log.info("Received signal %s, shutting down %s v%s", signum, SERVER_NAME, __version__)
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    mcp = FastMCP(
        name=SERVER_NAME,
        instructions="Tools to manage Oracle OKE clusters & Kubernetes resources. Keep responses concise.",
    )

    @mcp.tool()
    def meta_health() -> dict:
        return {"status": "ok", "version": __version__, "effective_defaults": get_effective_defaults()}

    @mcp.tool()
    def config_get_effective_defaults() -> dict:
        return get_effective_defaults()

    if args.print_tools:
        names = sorted(getattr(mcp, "_tools", {}).keys())
        for n in names:
            print(n)
        return

    mcp.run(transport=args.transport)

if __name__ == "__main__":
    main()