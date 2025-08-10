import oci
from typing import Dict, List, Optional
from oci_auth import get_identity_client, get_container_engine_client
from oke_auth import get_core_v1_client
from oci.util import to_dict


def list_clusters(params: Dict) -> List[Dict]:
    """Return OKE clusters in a given compartment.

    Accepts either `compartmentId` (camelCase) or `compartment_id` (snake_case)
    to align with different caller conventions.
    """
    compartment_id = params.get("compartmentId") or params.get("compartment_id")
    if not compartment_id:
        raise ValueError("Missing compartmentId/compartment_id")

    ce_client = get_container_engine_client()
    response = ce_client.list_clusters(compartment_id=compartment_id)

    clusters = [
        {
            "id": c.id,
            "name": c.name,
            "compartmentId": c.compartment_id,
            "lifecycleState": str(getattr(c, "lifecycle_state", "")),
            "kubernetesVersion": getattr(c, "kubernetes_version", None),
        }
        for c in response.data
    ]

    return clusters


def get_cluster(params: Dict) -> Dict:
    """Return details for a specific OKE cluster by cluster_id."""
    cluster_id = params.get("cluster_id")
    if not cluster_id:
        raise ValueError("Missing cluster_id")

    ce_client = get_container_engine_client()
    resp = ce_client.get_cluster(cluster_id)
    return to_dict(resp.data)


def list_node_pools(params: Dict) -> List[Dict]:
    """List node pools for a given cluster within a compartment."""
    compartment_id = params.get("compartment_id") or params.get("compartmentId")
    cluster_id = params.get("cluster_id") or params.get("clusterId")
    if not compartment_id:
        raise ValueError("Missing compartment_id/compartmentId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")

    ce_client = get_container_engine_client()
    resp = ce_client.list_node_pools(compartment_id=compartment_id, cluster_id=cluster_id)
    return [to_dict(np) for np in resp.data]


def get_node_pool(params: Dict) -> Dict:
    """Return details for a specific node pool by node_pool_id."""
    node_pool_id = params.get("node_pool_id") or params.get("nodePoolId")
    if not node_pool_id:
        raise ValueError("Missing node_pool_id/nodePoolId")

    ce_client = get_container_engine_client()
    resp = ce_client.get_node_pool(node_pool_id)
    return to_dict(resp.data)


def list_pods(params: Dict) -> List[Dict]:
    """List pods in the cluster. If `namespace` provided, list only that namespace."""
    cluster_id = params.get("cluster_id") or params.get("clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    namespace: Optional[str] = params.get("namespace")

    core_v1 = get_core_v1_client(cluster_id)

    if namespace:
        pods = core_v1.list_namespaced_pod(namespace=namespace).items
    else:
        pods = core_v1.list_pod_for_all_namespaces().items

    result: List[Dict] = []
    for p in pods:
        result.append({
            "name": getattr(p.metadata, "name", None),
            "namespace": getattr(p.metadata, "namespace", None),
            "node": getattr(getattr(p.spec, "node_name", None), "__str__", lambda: None)() if hasattr(p.spec, "node_name") else None,
            "status": getattr(p.status, "phase", None),
            "start_time": str(getattr(p.status, "start_time", "")),
            "containers": [c.name for c in (getattr(p.spec, "containers", []) or [])],
        })
    return result


def list_namespaces(params: Dict) -> List[Dict]:
    """List namespaces in the given cluster.

    Params:
      - cluster_id (required): OKE cluster OCID
      - endpoint (optional): "PUBLIC"/"PRIVATE" or SDK constant
    """
    cluster_id = params.get("cluster_id") or params.get("clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    endpoint = params.get("endpoint")

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
      - endpoint (optional): "PUBLIC"/"PRIVATE" or SDK constant
    """
    cluster_id = params.get("cluster_id") or params.get("clusterId")
    namespace = params.get("namespace")
    pod = params.get("pod") or params.get("name")
    container = params.get("container")
    tail_lines = params.get("tail_lines") or params.get("tailLines") or 200
    endpoint = params.get("endpoint")

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
        timestamps=False,
        _preload_content=True,
    )

    return {
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "tail_lines": int(tail_lines) if isinstance(tail_lines, (int, str)) else 200,
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
    cluster_id = params.get("cluster_id") or params.get("clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")

    namespace: Optional[str] = params.get("namespace")
    since_seconds = params.get("since_seconds") or params.get("sinceSeconds")
    field_selector = params.get("field_selector") or params.get("fieldSelector")
    endpoint = params.get("endpoint")

    core_v1 = get_core_v1_client(cluster_id, endpoint=endpoint) if endpoint else get_core_v1_client(cluster_id)

    if namespace:
        evs = core_v1.list_namespaced_event(
            namespace=namespace,
            field_selector=field_selector,
            _preload_content=True,
        ).items
    else:
        evs = core_v1.list_event_for_all_namespaces(
            field_selector=field_selector,
            _preload_content=True,
        ).items

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

    # Apply since_seconds filter client-side if the server-side field isn't provided
    try:
        if since_seconds is not None:
            import datetime as _dt
            try:
                since = _dt.datetime.utcnow() - _dt.timedelta(seconds=int(since_seconds))
                def _to_dt(s: Optional[str]):
                    if not s:
                        return None
                    try:
                        # Handle both RFC3339 and naive ISO forms
                        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        return None
                out = [ev for ev in out if (_to_dt(ev.get("last_timestamp")) or _to_dt(ev.get("event_time")) or _to_dt(ev.get("first_timestamp"))) and (max(filter(None, [_to_dt(ev.get("last_timestamp")), _to_dt(ev.get("event_time")), _to_dt(ev.get("first_timestamp"))])) >= since)]
            except Exception:
                pass
    except Exception:
        pass

    return out