#!/usr/bin/env python3
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP

from config_store import get_defaults, set_defaults
from handlers.oke import (
    list_clusters as _list_clusters,
    get_cluster as _get_cluster,
    list_node_pools as _list_node_pools,
    get_node_pool as _get_node_pool,
    list_pods as _list_pods,
    list_namespaces as _list_namespaces,
    get_pod_logs as _get_pod_logs,
    list_events as _list_events,
)

mcp = FastMCP("OKE MCP Server")

# ---- Configuration tools ----
@mcp.tool()
def config_set_defaults(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict:
    """Set default compartment/cluster OCIDs for subsequent calls."""
    return set_defaults(compartment_id=compartment_id, cluster_id=cluster_id)

@mcp.tool()
def config_get_defaults() -> Dict:
    """Get current default OCIDs used by tools."""
    return get_defaults()

# ---- OKE tools (fall back to defaults) ----
@mcp.tool()
def oke_list_clusters(compartment_id: Optional[str] = None) -> List[Dict]:
    if not compartment_id:
        compartment_id = get_defaults().get("compartment_id")
    if not compartment_id:
        raise ValueError("compartment_id is required (set via config_set_defaults or pass explicitly)")
    return _list_clusters({"compartment_id": compartment_id})

@mcp.tool()
def oke_get_cluster(cluster_id: Optional[str] = None) -> Dict:
    if not cluster_id:
        cluster_id = get_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _get_cluster({"cluster_id": cluster_id})

@mcp.tool()
def oke_list_node_pools(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None) -> List[Dict]:
    defaults = get_defaults()
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

    return _list_node_pools({"compartment_id": compartment_id, "cluster_id": cluster_id})

@mcp.tool()
def oke_get_node_pool(node_pool_id: str) -> Dict:
    return _get_node_pool({"node_pool_id": node_pool_id})

@mcp.tool()
def oke_list_pods(cluster_id: Optional[str] = None, namespace: Optional[str] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_pods({"cluster_id": cluster_id, "namespace": namespace})

@mcp.tool()
def oke_list_namespaces(cluster_id: Optional[str] = None, endpoint: Optional[str] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_namespaces({"cluster_id": cluster_id, "endpoint": endpoint})

@mcp.tool()
def oke_get_pod_logs(namespace: str, pod: str, container: Optional[str] = None,
                     tail_lines: int = 200, cluster_id: Optional[str] = None,
                     endpoint: Optional[str] = None) -> Dict:
    if not cluster_id:
        cluster_id = get_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _get_pod_logs({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "tail_lines": tail_lines,
        "endpoint": endpoint,
    })

@mcp.tool()
def oke_list_events(namespace: Optional[str] = None, since_seconds: Optional[int] = None,
                    field_selector: Optional[str] = None, cluster_id: Optional[str] = None,
                    endpoint: Optional[str] = None) -> List[Dict]:
    if not cluster_id:
        cluster_id = get_defaults().get("cluster_id")
    if not cluster_id:
        raise ValueError("cluster_id is required (set via config_set_defaults or pass explicitly)")
    return _list_events({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "since_seconds": since_seconds,
        "field_selector": field_selector,
        "endpoint": endpoint,
    })

if __name__ == "__main__":
    mcp.run(transport="stdio")