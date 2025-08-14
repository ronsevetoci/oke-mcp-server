from __future__ import annotations
from typing import Optional, Dict, List, Any
from fastmcp import Context
from kubernetes import client as k8s_client
from ..auth import get_core_v1_client

# ---------- helpers ----------

_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
}

def _parse_quantity(q: Optional[str]) -> Dict[str, Optional[float]]:
    """
    Parse Kubernetes resource quantity strings.
    Returns {"cores": float|None, "bytes": int|None} depending on unit.
    Unparseable values return both None.
    """
    if not q or not isinstance(q, str):
        return {"cores": None, "bytes": None}
    try:
        # CPU: e.g. "50m" or "1" (cores)
        if q.endswith("m"):
            return {"cores": float(q[:-1]) / 1000.0, "bytes": None}
        # Memory with IEC units (Ki, Mi, Gi, ...)
        for u, mult in _UNITS.items():
            if q.endswith(u):
                num = float(q[:-len(u)])
                # Heuristic: memory units -> bytes; decimal units are also treated as bytes
                return {"cores": None, "bytes": int(num * mult)}
        # Bare number: treat CPU cores if <= 64 (heuristic), else bytes
        val = float(q)
        if val <= 64:
            return {"cores": val, "bytes": None}
        return {"cores": None, "bytes": int(val)}
    except Exception:
        return {"cores": None, "bytes": None}

def _trim_node_metric(m: Dict[str, Any]) -> Dict[str, Any]:
    meta = m.get("metadata", {})
    usage = m.get("usage", {}) or {}
    cpu = usage.get("cpu")
    mem = usage.get("memory")
    cpu_parsed = _parse_quantity(cpu)
    mem_parsed = _parse_quantity(mem)
    return {
        "name": meta.get("name"),
        "timestamp": m.get("timestamp") or m.get("window"),  # metrics API varies
        "cpu": {"usage": cpu, "cores": cpu_parsed["cores"]},
        "memory": {"usage": mem, "bytes": mem_parsed["bytes"]},
    }

def _trim_container_metric(c: Dict[str, Any]) -> Dict[str, Any]:
    name = c.get("name")
    usage = c.get("usage", {}) or {}
    cpu = usage.get("cpu")
    mem = usage.get("memory")
    cpu_parsed = _parse_quantity(cpu)
    mem_parsed = _parse_quantity(mem)
    return {
        "name": name,
        "cpu": {"usage": cpu, "cores": cpu_parsed["cores"]},
        "memory": {"usage": mem, "bytes": mem_parsed["bytes"]},
    }

def _sum_container_metrics(containers: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_cores = 0.0
    total_bytes = 0
    any_cpu = False
    any_mem = False
    for c in containers:
        cores = c.get("cpu", {}).get("cores")
        if isinstance(cores, (int, float)):
            total_cores += float(cores)
            any_cpu = True
        b = c.get("memory", {}).get("bytes")
        if isinstance(b, (int, float)):
            total_bytes += int(b)
            any_mem = True
    return {
        "cpu": {"cores": total_cores if any_cpu else None},
        "memory": {"bytes": total_bytes if any_mem else None},
    }

# ---------- tools ----------

def oke_list_node_metrics(
    ctx: Context,
    cluster_id: str,
    endpoint: Optional[str] = None,
    auth: Optional[str] = None,
    limit: Optional[int] = 100,
    continue_token: Optional[str] = None,
) -> Dict:
    """
    List node metrics via metrics.k8s.io.
    Returns compact, LLM-friendly schema with parsed CPU cores and memory bytes.
    Supports pagination (limit/_continue) when backed by the metrics server.
    """
    try:
        api_client = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth).api_client
        co = k8s_client.CustomObjectsApi(api_client)

        # Cap limit to something reasonable
        q_limit = max(1, min(int(limit or 100), 200))
        kwargs = {"limit": q_limit}
        if continue_token:
            kwargs["_continue"] = continue_token

        data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes", **kwargs)
        raw_items = data.get("items", []) or []
        items = [_trim_node_metric(m) for m in raw_items]
        cont = (data.get("metadata") or {}).get("continue")

        return {"available": True, "items": items, "continue": cont}
    except Exception as e:
        return {"available": False, "reason": str(e)}

def oke_list_pod_metrics(
    ctx: Context,
    cluster_id: str,
    namespace: Optional[str] = None,
    endpoint: Optional[str] = None,
    auth: Optional[str] = None,
    limit: Optional[int] = 100,
    continue_token: Optional[str] = None,
) -> Dict:
    """
    List pod metrics via metrics.k8s.io.
    Returns compact, LLM-friendly schema with per-container and total CPU/memory.
    Supports pagination (limit/_continue).
    """
    try:
        api_client = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth).api_client
        co = k8s_client.CustomObjectsApi(api_client)

        q_limit = max(1, min(int(limit or 100), 200))
        kwargs = {"limit": q_limit}
        if continue_token:
            kwargs["_continue"] = continue_token

        if namespace:
            data = co.list_namespaced_custom_object("metrics.k8s.io", "v1beta1", namespace, "pods", **kwargs)
        else:
            data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods", **kwargs)

        raw_items = data.get("items", []) or []

        items: List[Dict[str, Any]] = []
        for m in raw_items:
            meta = m.get("metadata", {})
            status = {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "timestamp": m.get("timestamp") or m.get("window"),
            }
            containers = [_trim_container_metric(c) for c in (m.get("containers") or [])]
            totals = _sum_container_metrics(containers)
            items.append({**status, "containers": containers, "total": totals})

        cont = (data.get("metadata") or {}).get("continue")
        return {"available": True, "items": items, "continue": cont}
    except Exception as e:
        return {"available": False, "reason": str(e)}