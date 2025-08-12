from __future__ import annotations
from typing import Optional, Dict, List
from fastmcp import Context
from ..auth import get_container_engine_client
from ..config import settings

def _trim_cluster(c) -> dict:
    md = getattr(c, "metadata", None)
    status = getattr(c, "lifecycle_state", None) or getattr(c, "lifecycleDetails", None)
    return {
        "id": getattr(c, "id", ""),
        "name": getattr(md, "name", getattr(c, "name", "")),
        "k8sVersion": getattr(c, "kubernetes_version", None),
        "lifecycle": status,
        "endpoints": getattr(c, "endpoints", None),
    }

def oke_list_clusters(ctx: Context, compartment_id: str, page: Optional[str] = None, limit: Optional[int] = 20) -> Dict:
    ce = get_container_engine_client()
    resp = ce.list_clusters(compartment_id=compartment_id, page=page, limit=limit)
    items = [_trim_cluster(c) for c in (resp.data or [])]
    nextp = getattr(resp, "headers", {}).get("opc-next-page")
    return {"items": items, "opc_next_page": nextp}

def oke_get_cluster(ctx: Context, cluster_id: str) -> Dict:
    ce = get_container_engine_client()
    resp = ce.get_cluster(cluster_id)
    return _trim_cluster(resp.data)