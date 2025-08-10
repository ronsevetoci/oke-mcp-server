#!/usr/bin/env python3
from typing import List, Dict, Optional
import argparse
import os
import sys
import logging
# Minimal metadata import for versioning
from importlib.metadata import version, PackageNotFoundError
import signal

# Configure logging level via env var, default INFO
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("oke-mcp-server")

# Server name and version metadata
SERVER_NAME = "OKE MCP Server"
try:
    __version__ = version("oke-mcp-server")
except PackageNotFoundError:
    __version__ = "0.0.0-local"

# Ensure stdio flushes promptly in uvx/GUI contexts
try:
    sys.stdout.reconfigure(line_buffering=True)  # Python 3.7+
except Exception:
    pass
from mcp.server.fastmcp import FastMCP

from config_store import get_defaults, set_defaults, get_effective_defaults
from oci_auth import invalidate_auth_cache
from handlers.oke import (
    list_clusters as _list_clusters,
    get_cluster as _get_cluster,
    list_node_pools as _list_node_pools,
    get_node_pool as _get_node_pool,
    list_pods as _list_pods,
    list_namespaces as _list_namespaces,
    get_pod_logs as _get_pod_logs,
    list_events as _list_events,
    describe_resources as _describe_resources,
    service_endpoints as _service_endpoints,
    probe_failures as _probe_failures,
    crashlooping as _crashlooping,
    top_pods as _top_pods,
    rbac_who_can as _rbac_who_can,
    security_findings as _security_findings,
    scale_node_pool as _scale_node_pool,
    list_work_requests as _list_work_requests,
    restart_deployment as _restart_deployment,
)

mcp = FastMCP(SERVER_NAME)

# ---- Configuration tools ----

# ---- Meta diagnostic tools ----
@mcp.tool()
def meta_health() -> Dict:
    """Lightweight health check for MCP server."""
    return {"status": "ok", "log_level": LOG_LEVEL}

@mcp.tool()
def meta_echo(payload: Optional[Dict] = None) -> Dict:
    """Echo back payload for client troubleshooting."""
    logger.debug("meta_echo payload=%s", payload)
    return {"received": payload or {}}

@mcp.tool()
def meta_env() -> Dict:
    """Return a redacted snapshot of relevant env vars (local diagnostic)."""
    keys = [
        "OKE_COMPARTMENT_ID", "OKE_CLUSTER_ID", "OCI_CLI_AUTH",
        "OCI_CLI_PROFILE", "OCI_CONFIG_FILE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "LOG_LEVEL"
    ]
    def redact(v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        if len(v) <= 8:
            return "***"
        return v[:4] + "…" + v[-4:]
    return {k: redact(os.getenv(k)) for k in keys}

@mcp.tool()
def auth_refresh() -> Dict:
    """Force refresh of cached OCI signer (useful after STS token rotation)."""
    invalidate_auth_cache()
    return {"status": "refreshed"}

@mcp.tool()
def config_set_defaults(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict:
    """Set default compartment/cluster OCIDs for subsequent calls."""
    return set_defaults(compartment_id=compartment_id, cluster_id=cluster_id)

@mcp.tool()
def config_get_defaults() -> Dict:
    """Get current default OCIDs used by tools."""
    return get_defaults()

@mcp.tool()
def config_get_effective_defaults() -> Dict:
    """Get defaults merged with environment fallbacks (what tools actually use)."""
    return get_effective_defaults()

# ---- OKE tools (fall back to defaults) ----
@mcp.tool()
def oke_list_clusters(compartment_id: Optional[str] = None, page: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
    if not compartment_id:
        compartment_id = get_effective_defaults().get("compartment_id")
    if not compartment_id:
        raise ValueError("compartment_id is required (set via config_set_defaults or pass explicitly)")
    return _list_clusters({"compartment_id": compartment_id, "page": page, "limit": limit})

@mcp.tool()
def oke_get_cluster(cluster_id: Optional[str] = None) -> Dict:
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _get_cluster({"cluster_id": cluster_id})

@mcp.tool()
def oke_list_node_pools(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None, page: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
    defaults = get_effective_defaults()
    cluster_id = cluster_id or defaults.get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")

    compartment_id = compartment_id or defaults.get("compartment_id")
    if not compartment_id:
        # Infer the compartment from the cluster if we can
        cluster = _get_cluster({"cluster_id": cluster_id})
        compartment_id = cluster.get("compartment_id") or cluster.get("compartmentId")
    if not compartment_id:
        raise ValueError("compartment_id is required and could not be inferred; set via config_set_defaults or pass explicitly")

    return _list_node_pools({"compartment_id": compartment_id, "cluster_id": cluster_id, "page": page, "limit": limit})

@mcp.tool()
def oke_get_node_pool(node_pool_id: str) -> Dict:
    return _get_node_pool({"node_pool_id": node_pool_id})

@mcp.tool()
def oke_list_pods(cluster_id: Optional[str] = None, namespace: Optional[str] = None, label_selector: Optional[str] = None, field_selector: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_pods({"cluster_id": cluster_id, "namespace": namespace, "label_selector": label_selector, "field_selector": field_selector, "limit": limit})

@mcp.tool()
def oke_list_namespaces(cluster_id: Optional[str] = None, endpoint: Optional[str] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_namespaces({"cluster_id": cluster_id, "endpoint": endpoint})

@mcp.tool()
def oke_get_pod_logs(namespace: str, pod: str, container: Optional[str] = None,
                     tail_lines: int = 200, since_seconds: Optional[int] = None,
                     previous: Optional[bool] = None, timestamps: Optional[bool] = False,
                     cluster_id: Optional[str] = None, endpoint: Optional[str] = None) -> Dict:
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _get_pod_logs({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "tail_lines": tail_lines,
        "since_seconds": since_seconds,
        "previous": previous,
        "timestamps": timestamps,
        "endpoint": endpoint,
    })

@mcp.tool()
def oke_list_events(namespace: Optional[str] = None, since_seconds: Optional[int] = None,
                    field_selector: Optional[str] = None, cluster_id: Optional[str] = None,
                    endpoint: Optional[str] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_events({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "since_seconds": since_seconds,
        "field_selector": field_selector,
        "endpoint": endpoint,
    })

@mcp.tool()
def oke_describe_resources(cluster_id: Optional[str] = None,
                           compartment_id: Optional[str] = None,
                           since_seconds: Optional[int] = 1800) -> Dict:
    """Summarize cluster state: namespaces, pods, unhealthy, recent events, node pools."""
    defaults = get_effective_defaults()
    return _describe_resources({
        "cluster_id": cluster_id or defaults.get("cluster_id"),
        "compartment_id": compartment_id or defaults.get("compartment_id"),
        "since_seconds": since_seconds,
    })

@mcp.tool()
def oke_service_endpoints(namespace: str, service_name: str, cluster_id: Optional[str] = None) -> Dict:
    """List service ports and backend endpoints for a Service."""
    if not cluster_id:
        cluster_id = get_effective_defaults().get("cluster_id")
    return _service_endpoints({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "service_name": service_name,
    })

@mcp.tool()
def oke_probe_failures(cluster_id: Optional[str] = None, namespace: Optional[str] = None, since_seconds: Optional[int] = 900) -> List[Dict]:
    """Find pods with recent failing probes (Unhealthy events)."""
    return _probe_failures({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "namespace": namespace,
        "since_seconds": since_seconds,
    })

@mcp.tool()
def oke_crashlooping(cluster_id: Optional[str] = None, namespace: Optional[str] = None) -> List[Dict]:
    """List containers in CrashLoopBackOff."""
    return _crashlooping({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "namespace": namespace,
    })

@mcp.tool()
def oke_top_pods(cluster_id: Optional[str] = None, namespace: Optional[str] = None, limit: Optional[int] = 20) -> Dict:
    """Top pods by CPU/memory via metrics.k8s.io (if available)."""
    return _top_pods({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "namespace": namespace,
        "limit": limit,
    })

@mcp.tool()
def oke_rbac_who_can(verb: str, resource: str, namespace: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict:
    """Naive RBAC scan: who can <verb> <resource>?"""
    return _rbac_who_can({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "verb": verb,
        "resource": resource,
        "namespace": namespace,
    })

@mcp.tool()
def oke_security_findings(cluster_id: Optional[str] = None, namespace: Optional[str] = None) -> List[Dict]:
    """Static checks for risky settings: hostPath, privileged, runAsRoot."""
    return _security_findings({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "namespace": namespace,
    })

@mcp.tool()
def oke_scale_node_pool(node_pool_id: str, size: int) -> Dict:
    """Scale an OKE node pool (requires OKE_ENABLE_WRITE=1)."""
    return _scale_node_pool({"node_pool_id": node_pool_id, "size": size})

@mcp.tool()
def oke_list_work_requests(compartment_id: Optional[str] = None, resource_id: Optional[str] = None) -> List[Dict]:
    """List recent OKE work requests (optionally filter by resource)."""
    return _list_work_requests({
        "compartment_id": compartment_id or get_effective_defaults().get("compartment_id"),
        "resource_id": resource_id,
    })

@mcp.tool()
def oke_restart_deployment(namespace: str, name: str, reason: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict:
    """Rolling restart for a Deployment (requires OKE_ENABLE_WRITE=1)."""
    return _restart_deployment({
        "cluster_id": cluster_id or get_effective_defaults().get("cluster_id"),
        "namespace": namespace,
        "name": name,
        "reason": reason,
    })

@mcp.tool()
def health() -> Dict:
    """Quick status including stored and effective defaults."""
    return {
        "server": SERVER_NAME,
        "version": __version__,
        "defaults": get_defaults(),
        "effective": get_effective_defaults(),
    }

def main() -> None:
    """Console entrypoint for uvx/setuptools; selects MCP transport."""
    parser = argparse.ArgumentParser(description="OKE MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio"],  # extend when adding other transports
        help="MCP transport to use (default: stdio)",
    )
    parser.add_argument(
        "--set-defaults-compartment",
        dest="defaults_compartment",
        help="Set default compartment OCID for this session (no need to call config_set_defaults).",
    )
    parser.add_argument(
        "--set-defaults-cluster",
        dest="defaults_cluster",
        help="Set default cluster OCID for this session (no need to call config_set_defaults).",
    )
    parser.add_argument(
        "--print-tools",
        action="store_true",
        help="List registered tools and exit (local sanity check).",
    )
    args = parser.parse_args()
    logger.info("Starting %s v%s (transport=%s, log_level=%s)", SERVER_NAME, __version__, args.transport, LOG_LEVEL)

    if args.defaults_compartment or args.defaults_cluster:
        set_defaults(compartment_id=args.defaults_compartment, cluster_id=args.defaults_cluster)
        logger.info("Session defaults set: compartment=%s cluster=%s", args.defaults_compartment, args.defaults_cluster)

    if args.print_tools:
        tool_names = sorted(getattr(mcp, "_tools", {}).keys())
        for name in tool_names:
            print(name)
        return

    def _graceful_exit(signum, frame):
        logger.info("Received signal %s, shutting down %s v%s", signum, SERVER_NAME, __version__)
        sys.exit(0)
    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    if logger.isEnabledFor(logging.DEBUG):
        try:
            # FastMCP stores tools in mcp._tools (dict name->callable); this is a best-effort introspection for local debugging
            tool_names = sorted(getattr(mcp, "_tools", {}).keys())
            logger.debug("Registered tools (%d): %s", len(tool_names), ", ".join(tool_names))
        except Exception:
            pass
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()