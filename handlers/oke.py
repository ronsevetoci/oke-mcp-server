import oci
from typing import Dict, List, Optional
from oci_auth import get_identity_client, get_container_engine_client
from oke_auth import get_core_v1_client
from oci.util import to_dict


# --- helpers ---------------------------------------------------------------

def _param(d: Dict, *names: str, default=None):
    """Return the first present key among aliases (camelCase + snake_case)."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def _safe_to_dict(model) -> Dict:
    """OCI model -> dict (fallback to __dict__ if needed)."""
    try:
        return to_dict(model)
    except Exception:
        return getattr(model, "__dict__", {}) or {"repr": repr(model)}


def list_clusters(params: Dict) -> List[Dict]:
    """Return OKE clusters in a given compartment.

    Accepts either `compartmentId` (camelCase) or `compartment_id` (snake_case)
    to align with different caller conventions.
    """
    compartment_id = _param(params, "compartment_id", "compartmentId")
    if not compartment_id:
        raise ValueError("Missing compartment_id/compartmentId")

    ce_client = get_container_engine_client()
    page = _param(params, "page")
    limit = _param(params, "limit")
    response = ce_client.list_clusters(compartment_id=compartment_id, page=page, limit=limit)

    clusters = [
        {
            "id": c.id,
            "name": c.name,
            "compartment_id": c.compartment_id,
            "lifecycle_state": str(getattr(c, "lifecycle_state", "")),
            "kubernetes_version": getattr(c, "kubernetes_version", None),
        }
        for c in response.data
    ]
    return clusters


def get_cluster(params: Dict) -> Dict:
    """Return details for a specific OKE cluster by cluster_id."""
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    ce_client = get_container_engine_client()
    resp = ce_client.get_cluster(cluster_id)
    return _safe_to_dict(resp.data)


def list_node_pools(params: Dict) -> List[Dict]:
    """List node pools for a given cluster within a compartment."""
    compartment_id = _param(params, "compartment_id", "compartmentId")
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not compartment_id:
        raise ValueError("Missing compartment_id/compartmentId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")

    ce_client = get_container_engine_client()
    page = _param(params, "page")
    limit = _param(params, "limit")
    resp = ce_client.list_node_pools(compartment_id=compartment_id, cluster_id=cluster_id, page=page, limit=limit)
    return [_safe_to_dict(np) for np in resp.data]


def get_node_pool(params: Dict) -> Dict:
    """Return details for a specific node pool by node_pool_id."""
    node_pool_id = _param(params, "node_pool_id", "nodePoolId")
    if not node_pool_id:
        raise ValueError("Missing node_pool_id/nodePoolId")
    ce_client = get_container_engine_client()
    resp = ce_client.get_node_pool(node_pool_id)
    return _safe_to_dict(resp.data)


def list_pods(params: Dict) -> List[Dict]:
    """List pods. If `namespace` provided, list only that namespace.

    Optional filters: label_selector, field_selector, limit (namespace-scoped only)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    namespace: Optional[str] = _param(params, "namespace")
    label_selector = _param(params, "label_selector", "labelSelector")
    field_selector = _param(params, "field_selector", "fieldSelector")
    limit = _param(params, "limit")

    core_v1 = get_core_v1_client(cluster_id)

    if namespace:
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector, field_selector=field_selector, limit=limit).items
    else:
        # k8s API ignores label/field selectors when listing all namespaces for some clients; still pass them if supported
        pods = core_v1.list_pod_for_all_namespaces(label_selector=label_selector, field_selector=field_selector).items

    result: List[Dict] = []
    for p in pods:
        node_name = getattr(p.spec, "node_name", None)
        containers = [c.name for c in (getattr(p.spec, "containers", []) or [])]
        result.append({
            "name": getattr(p.metadata, "name", None),
            "namespace": getattr(p.metadata, "namespace", None),
            "node": node_name,
            "status": getattr(p.status, "phase", None),
            "start_time": str(getattr(p.status, "start_time", "")),
            "containers": containers,
        })
    return result


def list_namespaces(params: Dict) -> List[Dict]:
    """List namespaces in the given cluster.

    Params:
      - cluster_id (required): OKE cluster OCID
      - endpoint (optional): "PUBLIC"/"PRIVATE" or SDK constant
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    endpoint = _param(params, "endpoint")

    core_v1 = get_core_v1_client(cluster_id, endpoint=endpoint) if endpoint else get_core_v1_client(cluster_id)
    items = core_v1.list_namespace().items

    out: List[Dict] = []
    for ns in items:
        out.append({
            "name": getattr(ns.metadata, "name", None),
            "status": getattr(ns.status, "phase", None),
            "labels": getattr(ns.metadata, "labels", None) or {},
        })
    return out


def get_pod_logs(params: Dict) -> Dict:
    """Get logs for a specific pod (optionally a specific container).

    Params:
      - cluster_id (required)
      - namespace (required)
      - pod (required)
      - container (optional)
      - tail_lines (optional, default 200)
      - since_seconds (optional)
      - previous (optional, bool)
      - timestamps (optional, bool)
      - endpoint (optional): "PUBLIC"/"PRIVATE" or SDK constant
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    namespace = _param(params, "namespace")
    pod = _param(params, "pod", "name")
    container = _param(params, "container")
    tail_lines = _param(params, "tail_lines", "tailLines", default=200)
    since_seconds = _param(params, "since_seconds", "sinceSeconds")
    previous = _param(params, "previous")
    timestamps = _param(params, "timestamps")
    endpoint = _param(params, "endpoint")

    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    if not namespace:
        raise ValueError("Missing namespace")
    if not pod:
        raise ValueError("Missing pod/name")

    core_v1 = get_core_v1_client(cluster_id, endpoint=endpoint) if endpoint else get_core_v1_client(cluster_id)

    text = core_v1.read_namespaced_pod_log(
        name=pod,
        namespace=namespace,
        container=container,
        tail_lines=int(tail_lines) if isinstance(tail_lines, (int, str)) else 200,
        since_seconds=int(since_seconds) if since_seconds is not None else None,
        previous=bool(previous) if previous is not None else None,
        timestamps=bool(timestamps) if timestamps is not None else False,
        _preload_content=True,
    )

    return {
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "tail_lines": int(tail_lines) if isinstance(tail_lines, (int, str)) else 200,
        "since_seconds": int(since_seconds) if since_seconds is not None else None,
        "previous": bool(previous) if previous is not None else None,
        "timestamps": bool(timestamps) if timestamps is not None else False,
        "log": text or "",
    }


def list_events(params: Dict) -> List[Dict]:
    """List recent Kubernetes events.

    Params:
      - cluster_id (required)
      - namespace (optional); if omitted, returns events across all namespaces
      - since_seconds (optional, int)
      - field_selector (optional, str)
      - endpoint (optional): "PUBLIC"/"PRIVATE" or SDK constant
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")

    namespace: Optional[str] = _param(params, "namespace")
    since_seconds = _param(params, "since_seconds", "sinceSeconds")
    field_selector = _param(params, "field_selector", "fieldSelector")
    endpoint = _param(params, "endpoint")

    core_v1 = get_core_v1_client(cluster_id, endpoint=endpoint) if endpoint else get_core_v1_client(cluster_id)

    if namespace:
        evs = core_v1.list_namespaced_event(namespace=namespace, field_selector=field_selector, _preload_content=True).items
    else:
        evs = core_v1.list_event_for_all_namespaces(field_selector=field_selector, _preload_content=True).items

    out: List[Dict] = []
    for e in evs:
        involved = getattr(e, "involved_object", None)
        out.append({
            "namespace": getattr(e.metadata, "namespace", None),
            "name": getattr(e.metadata, "name", None),
            "type": getattr(e, "type", None),
            "reason": getattr(e, "reason", None),
            "message": getattr(e, "message", None),
            "count": getattr(e, "count", None),
            "event_time": str(getattr(e, "event_time", "")),
            "first_timestamp": str(getattr(e, "first_timestamp", "")),
            "last_timestamp": str(getattr(e, "last_timestamp", "")),
            "involved_object": {
                "kind": getattr(involved, "kind", None) if involved else None,
                "name": getattr(involved, "name", None) if involved else None,
                "namespace": getattr(involved, "namespace", None) if involved else None,
            },
        })

    # Optional client-side time filter
    try:
        if since_seconds is not None:
            import datetime as _dt
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(seconds=int(since_seconds))

            def _parse_iso(s: Optional[str]):
                if not s:
                    return None
                try:
                    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    return None

            filtered = []
            for ev in out:
                candidates = [
                    _parse_iso(ev.get("last_timestamp")),
                    _parse_iso(ev.get("event_time")),
                    _parse_iso(ev.get("first_timestamp")),
                ]
                mt = max([t for t in candidates if t is not None], default=None)
                if mt is None or mt >= cutoff:
                    filtered.append(ev)
            out = filtered
    except Exception:
        pass

    return out