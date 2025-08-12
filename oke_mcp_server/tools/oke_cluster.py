from __future__ import annotations
from typing import Optional, Dict, List
from fastmcp import Context
from ..auth import get_container_engine_client
from ..config import settings
from datetime import datetime

def _dt(v):
    return v.isoformat() if isinstance(v, datetime) else v

def _cluster_endpoints(ep) -> Dict:
    if not ep:
        return {}
    def g(name):
        return getattr(ep, name, None)
    return {
        "kubernetes": g("kubernetes") or g("kubernetes_endpoint") or g("kubernetesEndpoint"),
        "public_endpoint": g("public_endpoint") or g("publicEndpoint"),
        "private_endpoint": g("private_endpoint") or g("privateEndpoint"),
        "dashboard": g("kubernetes_dashboard") or g("kubernetesDashboard"),
    }

def _trim_cluster(c) -> dict:
    return {
        "id": getattr(c, "id", None),
        "name": getattr(c, "name", None),
        "kubernetes_version": getattr(c, "kubernetes_version", None),
        "lifecycle_state": getattr(c, "lifecycle_state", None) or getattr(c, "lifecycleState", None),
        "compartment_id": getattr(c, "compartment_id", None),
        "vcn_id": getattr(c, "vcn_id", None),
        "endpoints": _cluster_endpoints(getattr(c, "endpoints", None)),
        "time_created": _dt(getattr(c, "time_created", None) or getattr(c, "timeCreated", None)),
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