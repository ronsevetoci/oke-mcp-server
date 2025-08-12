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

    # --- Explicit tool registration (decorator-free) ---
    from .tools import k8s as k8s_tools
    from .tools import oke_cluster as oke_cluster_tools
    from .tools import metrics as metrics_tools
    from .tools import events as events_tools

    mcp.tool(name="k8s_list", description="List Kubernetes resources (trimmed). Supports kind={Pod|Service|Namespace|Node|Deployment|ReplicaSet|Endpoints|EndpointSlice|HPA}.")(k8s_tools.k8s_list)
    mcp.tool(name="k8s_get", description="Get a single Kubernetes resource by kind/name (trimmed).")(
        k8s_tools.k8s_get
    )
    mcp.tool(name="oke_get_pod_logs", description="Get Kubernetes pod logs (optionally container-specific, supports tail/timestamps/previous).")(k8s_tools.oke_get_pod_logs)

    mcp.tool(name="oke_list_clusters", description="List OKE clusters in a compartment (trimmed).")(
        oke_cluster_tools.oke_list_clusters
    )
    mcp.tool(name="oke_get_cluster", description="Get an OKE cluster by OCID (trimmed).")(
        oke_cluster_tools.oke_get_cluster
    )

    mcp.tool(name="oke_list_node_metrics", description="List node metrics from metrics.k8s.io if available.")(
        metrics_tools.oke_list_node_metrics
    )
    mcp.tool(name="oke_list_pod_metrics", description="List pod metrics (optionally namespaced) from metrics.k8s.io if available.")(
        metrics_tools.oke_list_pod_metrics
    )

    mcp.tool(name="oke_list_events", description="List Kubernetes events (optionally namespaced).")(
        events_tools.oke_list_events
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