from __future__ import annotations
from typing import Optional, Dict, List
from fastmcp import Context
from ..auth import get_container_engine_client
from ..config import settings
import os
from datetime import datetime

def _dt(v):
    return v.isoformat() if isinstance(v, datetime) else v


# Helper to resolve compartment_id from argument, settings, or env
def _resolve_compartment_id(passed: Optional[str]) -> Optional[str]:
    """
    Prefer explicit argument, then settings, then environment.
    """
    if passed:
        return passed
    try:
        # settings may have defaults or direct attribute
        cid = getattr(getattr(settings, "defaults", None), "compartment_id", None) or getattr(settings, "compartment_id", None)
        if cid:
            return cid
    except Exception:
        pass
    return os.getenv("OKE_COMPARTMENT_ID") or os.getenv("OCI_COMPARTMENT_ID")

def _cluster_endpoints(ep) -> Dict:
    """
    Normalize endpoint shapes across SDK versions.
    """
    if not ep:
        return {}
    def g(*names):
        for n in names:
            v = getattr(ep, n, None)
            if v:
                return v
        return None
    return {
        "kubernetes": g("kubernetes", "kubernetes_endpoint", "kubernetesEndpoint"),
        "public_endpoint": g("public_endpoint", "publicEndpoint"),
        "private_endpoint": g("private_endpoint", "privateEndpoint"),
        "dashboard": g("kubernetes_dashboard", "kubernetesDashboard"),
    }

def _trim_cluster(c) -> dict:
    return {
        "id": getattr(c, "id", None),
        "name": getattr(c, "name", None),
        "kubernetes_version": getattr(c, "kubernetes_version", None),
        "lifecycle_state": getattr(c, "lifecycle_state", None) or getattr(c, "lifecycleState", None),
        "compartment_id": getattr(c, "compartment_id", None),
        "vcn_id": getattr(c, "vcn_id", None),
        "endpoints": _cluster_endpoints(getattr(c, "endpoints", None) or getattr(c, "cluster_endpoints", None)),
        "time_created": _dt(getattr(c, "time_created", None) or getattr(c, "timeCreated", None)),
    }

def oke_list_clusters(
    ctx: Context,
    compartment_id: Optional[str] = None,
    page: Optional[str] = None,
    limit: Optional[int] = 20,
) -> Dict:
    """
    List OKE clusters in a compartment. If compartment_id is not provided,
    tries settings.defaults.compartment_id or env OKE_COMPARTMENT_ID.
    """
    cid = _resolve_compartment_id(compartment_id)
    if not cid:
        return {"error": "compartment_id is required (set defaults or pass explicitly)"}

    try:
        ce = get_container_engine_client()
        resp = ce.list_clusters(compartment_id=cid, page=page, limit=limit)
        items = [_trim_cluster(c) for c in (resp.data or [])]
        nextp = None
        try:
            # oci SDK response has headers dict-like
            nextp = getattr(resp, "headers", {}).get("opc-next-page")
        except Exception:
            pass
        return {"items": items, "opc_next_page": nextp}
    except Exception as e:
        return {"error": f"{e}"}

def oke_get_cluster(ctx: Context, cluster_id: str) -> Dict:
    if not cluster_id:
        return {"error": "cluster_id is required"}
    try:
        ce = get_container_engine_client()
        resp = ce.get_cluster(cluster_id)
        return _trim_cluster(resp.data)
    except Exception as e:
        return {"error": f"{e}"}