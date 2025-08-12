import oci
from typing import Dict, List, Optional
from oci_auth import get_container_engine_client
from oke_auth import get_core_v1_client
from oci.util import to_dict
from kubernetes import client as k8s_client
import os

# --- helpers ---------------------------------------------------------------

def _param(d: Dict, *names: str, default=None):
    """Return the first present key among aliases (camelCase + snake_case)."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

def _safe_to_dict(model) -> Dict:
    """Serialize OCI/K8s model -> JSON-safe dict.

    Preference order:
      1) For Kubernetes models, use ApiClient.sanitize_for_serialization (handles datetimes, enums)
      2) Fall back to OCI util.to_dict
      3) Fall back to __dict__ or repr
    """
    try:
        mod = getattr(model, "__class__", type(model)).__module__
    except Exception:
        mod = None

    # If it looks like a Kubernetes client model, use the official sanitizer
    if isinstance(mod, str) and mod.startswith("kubernetes."):
        try:
            from kubernetes.client import ApiClient as _K8sApiClient  # local import to avoid hard dep at import time
            return _K8sApiClient().sanitize_for_serialization(model)
        except Exception:
            pass

    # Try OCI's to_dict (works well for OCI SDK models)
    try:
        return to_dict(model)
    except Exception:
        pass

    # Last resort
    return getattr(model, "__dict__", {}) or {"repr": repr(model)}

# Build CoreV1 client honoring optional auth mode (e.g., 'security_token').
# Falls back gracefully if oke_auth.get_core_v1_client does not accept an 'auth' kwarg.
def _get_core_client(cluster_id: str, endpoint: Optional[str], auth_mode: Optional[str]):
    # Best-effort: allow explicit override via env for older helper signatures
    if auth_mode:
        try:
            os.environ["OCI_CLI_AUTH"] = auth_mode
        except Exception:
            pass
    try:
        if auth_mode is not None:
            return get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth_mode)  # type: ignore[arg-type]
        else:
            return get_core_v1_client(cluster_id, endpoint=endpoint)
    except TypeError:
        # Backward compatibility: older get_core_v1_client may not accept 'auth'
        return get_core_v1_client(cluster_id, endpoint=endpoint)

# --- OKE (OCI) primitives ---------------------------------------------------

def list_clusters(params: Dict) -> Dict:
    """Return OKE clusters for a compartment (raw objects).

    Inputs:
      - compartment_id (required) [alias: compartmentId]
      - page, limit (optional)
    """
    try:
        compartment_id = _param(params, "compartment_id", "compartmentId")
        if not compartment_id:
            return {"error": "Missing compartment_id/compartmentId"}
        page = _param(params, "page")
        limit = _param(params, "limit")
        ce = get_container_engine_client()
        resp = ce.list_clusters(compartment_id=compartment_id, page=page, limit=limit)
        return {"items": [_safe_to_dict(c) for c in resp.data], "opc_next_page": getattr(resp, "headers", {}).get("opc-next-page")}
    except Exception as e:
        return {"error": str(e)}


def get_cluster(params: Dict) -> Dict:
    """Return a single cluster by cluster_id (raw object)."""
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        if not cluster_id:
            return {"error": "Missing cluster_id/clusterId"}
        ce = get_container_engine_client()
        resp = ce.get_cluster(cluster_id)
        return _safe_to_dict(resp.data)
    except Exception as e:
        return {"error": str(e)}


# --- GENERIC K8S LIST/GET WITH HINTS ---------------------------------------

def _obj_id(kind: str, namespace: Optional[str], name: str) -> str:
    ns_part = f"{namespace}/" if namespace else ""
    return f"{kind.lower()}:{ns_part}{name}"

# Helper: extract Kubernetes list continue token regardless of client property naming
# The Python client exposes it as `metadata._continue` (underscore prefix)
# See: https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1ListMeta.md
def _list_continue(resp) -> Optional[str]:
    meta = getattr(resp, "metadata", None)
    if not meta:
        return None
    # V1ListMeta uses `_continue` attribute with alias "continue"
    return getattr(meta, "_continue", None)


def k8s_get(params: Dict) -> Dict:
    """Get exactly one Kubernetes resource (no recursion, no traversal).

    Inputs:
      - cluster_id (required)
      - group (optional, informational)
      - version (optional, informational)
      - kind (required): Pod|Service|Namespace|Node|Deployment|ReplicaSet|Endpoints|EndpointSlice
      - namespace (optional for cluster-scoped kinds)
      - name (required)
      - endpoint (optional): "PUBLIC"/"PRIVATE"
    Returns the raw object (as dict) or {"error": str}.
    """
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        kind = _param(params, "kind")
        namespace = _param(params, "namespace")
        name = _param(params, "name")
        endpoint = _param(params, "endpoint")
        auth_mode = _param(params, "auth", "auth_mode")
        if not (cluster_id and kind and name):
            return {"error": "cluster_id, kind, name are required"}

        api = _get_core_client(cluster_id, endpoint, auth_mode)
        apps = k8s_client.AppsV1Api(api.api_client)
        disc = k8s_client.DiscoveryV1Api(api.api_client)

        k = (kind or "").lower()
        if k == "pod":
            obj = api.read_namespaced_pod(name=name, namespace=namespace)
        elif k == "service":
            obj = api.read_namespaced_service(name=name, namespace=namespace)
        elif k == "namespace":
            obj = api.read_namespace(name=name)
        elif k == "node":
            obj = api.read_node(name=name)
        elif k == "deployment":
            obj = apps.read_namespaced_deployment(name=name, namespace=namespace)
        elif k == "replicaset":
            obj = apps.read_namespaced_replica_set(name=name, namespace=namespace)
        elif k == "endpoints":
            obj = api.read_namespaced_endpoints(name=name, namespace=namespace)
        elif k == "endpointslice":
            obj = disc.read_namespaced_endpoint_slice(name=name, namespace=namespace)
        else:
            return {"error": f"unsupported kind: {kind}"}
        return _safe_to_dict(obj)
    except Exception as e:
        return {"error": str(e)}


def k8s_list(params: Dict) -> Dict:
    """List Kubernetes resources with optional lightweight relationship hints.

    Inputs:
      - cluster_id (required)
      - kind (required): Pod|Service|Namespace|Node|Deployment|ReplicaSet|Endpoints|EndpointSlice|HPA
      - namespace (optional)
      - label_selector (optional)
      - field_selector (optional)
      - limit (optional)
      - continue_token (optional)
      - endpoint (optional): "PUBLIC"/"PRIVATE"
      - hints (optional, bool; default True): include minimal edges for common relationships

    Returns:
      { "items": [raw objects], "continue": str|None, "hints": {"edges": [...]}}
    """
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        kind = _param(params, "kind")
        namespace = _param(params, "namespace")
        label_selector = _param(params, "label_selector", "labelSelector")
        field_selector = _param(params, "field_selector", "fieldSelector")
        limit = _param(params, "limit")
        continue_token = _param(params, "continue_token", "continue")
        endpoint = _param(params, "endpoint")
        want_hints = bool(_param(params, "hints", default=True))
        auth_mode = _param(params, "auth", "auth_mode")
        if not (cluster_id and kind):
            return {"error": "cluster_id and kind are required"}

        api = _get_core_client(cluster_id, endpoint, auth_mode)
        apps = k8s_client.AppsV1Api(api.api_client)
        disc = k8s_client.DiscoveryV1Api(api.api_client)
        autos = k8s_client.AutoscalingV2Api(api.api_client)

        items: List[Dict] = []
        cont: Optional[str] = None
        edges: List[Dict] = []

        k = (kind or "").lower()
        # --- core kinds ---
        if k == "pod":
            resp = (api.list_namespaced_pod(namespace=namespace, label_selector=label_selector,
                                            field_selector=field_selector, limit=limit, _continue=continue_token)
                    if namespace else
                    api.list_pod_for_all_namespaces(label_selector=label_selector, field_selector=field_selector, limit=limit, _continue=continue_token))
            items = [_safe_to_dict(o) for o in resp.items]
            cont = _list_continue(resp)

        elif k == "service":
            resp = (api.list_namespaced_service(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                    if namespace else
                    api.list_service_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
            svcs = resp.items
            items = [_safe_to_dict(o) for o in svcs]
            cont = _list_continue(resp)

            if want_hints:
                # For each service, connect to pods matching selector in same namespace
                for s in svcs:
                    sel = getattr(getattr(s, "spec", None), "selector", None) or {}
                    ns = getattr(s.metadata, "namespace", None)
                    if not sel or not ns:
                        continue
                    selector_str = ",".join([f"{k}={v}" for k, v in sel.items()])
                    try:
                        pods = api.list_namespaced_pod(namespace=ns, label_selector=selector_str).items
                    except Exception:
                        pods = []
                    sid = _obj_id("svc", ns, getattr(s.metadata, "name", ""))
                    for p in pods:
                        pid = _obj_id("pod", getattr(p.metadata, "namespace", None), getattr(p.metadata, "name", ""))
                        edges.append({"from": sid, "to": pid, "type": "selects"})

        elif k == "namespace":
            resp = api.list_namespace(limit=limit, _continue=continue_token)
            items = [_safe_to_dict(o) for o in resp.items]
            cont = _list_continue(resp)

        elif k == "node":
            resp = api.list_node(limit=limit, _continue=continue_token)
            items = [_safe_to_dict(o) for o in resp.items]
            cont = _list_continue(resp)

        elif k == "endpoints":
            resp = (api.list_namespaced_endpoints(namespace=namespace, limit=limit, _continue=continue_token)
                    if namespace else
                    api.list_endpoints_for_all_namespaces(limit=limit, _continue=continue_token))
            items = [_safe_to_dict(o) for o in resp.items]
            cont = _list_continue(resp)

        elif k == "endpointslice":
            resp = (disc.list_namespaced_endpoint_slice(namespace=namespace, limit=limit, _continue=continue_token)
                    if namespace else
                    disc.list_endpoint_slice_for_all_namespaces(limit=limit, _continue=continue_token))
            items = [_safe_to_dict(o) for o in resp.items]
            cont = _list_continue(resp)

        # --- apps kinds ---
        elif k == "deployment":
            resp = (apps.list_namespaced_deployment(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                    if namespace else
                    apps.list_deployment_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
            deps = resp.items
            items = [_safe_to_dict(o) for o in deps]
            cont = _list_continue(resp)

            if want_hints:
                # Build dep -> rs -> pod edges WITHOUT cluster-wide scans.
                for d in deps:
                    ns_d = getattr(d.metadata, "namespace", None)
                    name_d = getattr(d.metadata, "name", "")
                    did = _obj_id("deploy", ns_d, name_d)
                    duid = getattr(d.metadata, "uid", None)

                    # Use deployment's selector if available to narrow RS search
                    rs_selector = None
                    try:
                        mlabels = getattr(getattr(d.spec, "selector", None), "match_labels", None)
                        if mlabels:
                            rs_selector = ",".join([f"{k}={v}" for k, v in mlabels.items()])
                    except Exception:
                        rs_selector = None

                    try:
                        rs_resp = apps.list_namespaced_replica_set(namespace=ns_d, label_selector=rs_selector)
                        rs_list = rs_resp.items
                    except Exception:
                        rs_list = []

                    # Filter RS owned by this deployment, emit dep->rs edges
                    for rs in rs_list:
                        owned = False
                        for ref in (getattr(rs.metadata, "owner_references", []) or []):
                            if getattr(ref, "kind", "") == "Deployment" and getattr(ref, "uid", None) == duid:
                                owned = True
                                break
                        if not owned:
                            continue

                        rsid = _obj_id("rs", getattr(rs.metadata, "namespace", None), getattr(rs.metadata, "name", ""))
                        edges.append({"from": did, "to": rsid, "type": "controls"})

                        # rs -> pods via rs selector (namespace-scoped)
                        try:
                            sel = getattr(getattr(rs, "spec", None), "selector", None)
                            ml = getattr(sel, "match_labels", None) if sel else None
                            psel = ",".join([f"{k}={v}" for k, v in (ml or {}).items()]) if ml else None
                            pods = api.list_namespaced_pod(namespace=ns_d, label_selector=psel).items if psel else []
                        except Exception:
                            pods = []

                        for p in pods:
                            pid = _obj_id("pod", getattr(p.metadata, "namespace", None), getattr(p.metadata, "name", ""))
                            edges.append({"from": rsid, "to": pid, "type": "owns"})

        elif k == "replicaset":
            resp = (apps.list_namespaced_replica_set(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                    if namespace else
                    apps.list_replica_set_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
            rsets = resp.items
            items = [_safe_to_dict(o) for o in rsets]
            cont = _list_continue(resp)

            if want_hints:
                for rs in rsets:
                    ns = getattr(rs.metadata, "namespace", None)
                    rsid = _obj_id("rs", ns, getattr(rs.metadata, "name", ""))
                    # pods via selector
                    try:
                        sel = getattr(getattr(rs, "spec", None), "selector", None)
                        ml = getattr(sel, "match_labels", None) if sel else None
                        selector_str = ",".join([f"{k}={v}" for k, v in (ml or {}).items()]) if ml else None
                        pods = api.list_namespaced_pod(namespace=ns, label_selector=selector_str).items if selector_str else []
                    except Exception:
                        pods = []
                    for p in pods:
                        pid = _obj_id("pod", getattr(p.metadata, "namespace", None), getattr(p.metadata, "name", ""))
                        edges.append({"from": rsid, "to": pid, "type": "owns"})
                    # owner backref
                    for ref in (getattr(rs.metadata, "owner_references", []) or []):
                        if getattr(ref, "kind", "") == "Deployment":
                            did = _obj_id("deploy", ns, getattr(ref, "name", ""))
                            edges.append({"from": did, "to": rsid, "type": "controls"})

        # --- autoscaling hints ---
        elif k in ("hpa", "horizontalpodautoscaler"):
            resp = (autos.list_namespaced_horizontal_pod_autoscaler(namespace=namespace, limit=limit, _continue=continue_token)
                    if namespace else
                    autos.list_horizontal_pod_autoscaler_for_all_namespaces(limit=limit, _continue=continue_token))
            hpas = resp.items
            items = [_safe_to_dict(o) for o in hpas]
            cont = _list_continue(resp)

            if want_hints:
                for h in hpas:
                    ns = getattr(h.metadata, "namespace", None)
                    hid = _obj_id("hpa", ns, getattr(h.metadata, "name", ""))
                    tref = getattr(h.spec, "scale_target_ref", None)
                    if tref:
                        tid = _obj_id(tref.kind or "", ns, getattr(tref, "name", ""))
                        edges.append({"from": hid, "to": tid, "type": "targets"})

        else:
            return {"error": f"unsupported kind for list: {kind}"}

        return {"items": items, "continue": cont, "hints": {"edges": edges} if want_hints else {}}
    except Exception as e:
        return {"error": str(e)}


# --- Focused single-purpose utilities --------------------------------------

def get_pod_logs(params: Dict) -> Dict:
    """Return logs for a pod/container (raw text + echoes of inputs).

    Inputs:
      - cluster_id (required)
      - namespace (required)
      - pod (required)
      - container (optional)
      - tail_lines (optional, default 200)
      - since_seconds (optional)
      - previous (optional, bool)
      - timestamps (optional, bool)
      - endpoint (optional): "PUBLIC"/"PRIVATE"
    """
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        namespace = _param(params, "namespace")
        pod = _param(params, "pod", "name")
        container = _param(params, "container")
        tail_lines = _param(params, "tail_lines", "tailLines", default=200)
        since_seconds = _param(params, "since_seconds", "sinceSeconds")
        previous = _param(params, "previous")
        timestamps = _param(params, "timestamps")
        endpoint = _param(params, "endpoint")

        if not (cluster_id and namespace and pod):
            return {"error": "cluster_id, namespace, pod are required"}

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
    except Exception as e:
        return {"error": str(e)}


def list_events(params: Dict) -> Dict:
    """Return raw Kubernetes events (optionally namespaced)."""
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        if not cluster_id:
            return {"error": "Missing cluster_id/clusterId"}
        namespace: Optional[str] = _param(params, "namespace")
        field_selector = _param(params, "field_selector", "fieldSelector")
        endpoint = _param(params, "endpoint")

        core_v1 = get_core_v1_client(cluster_id, endpoint=endpoint) if endpoint else get_core_v1_client(cluster_id)
        if namespace:
            evs = core_v1.list_namespaced_event(namespace=namespace, field_selector=field_selector, _preload_content=True).items
        else:
            evs = core_v1.list_event_for_all_namespaces(field_selector=field_selector, _preload_content=True).items
        return {"items": [_safe_to_dict(e) for e in evs]}
    except Exception as e:
        return {"error": str(e)}


# --- metrics (raw) ----------------------------------------------------------

def list_node_metrics(params: Dict) -> Dict:
    """Raw node CPU/memory from metrics.k8s.io (if installed)."""
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        if not cluster_id:
            return {"error": "Missing cluster_id/clusterId"}
        api_client = get_core_v1_client(cluster_id).api_client
        co = k8s_client.CustomObjectsApi(api_client)
        data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
        return {"available": True, "items": data.get("items", [])}
    except Exception as e:
        return {"available": False, "reason": str(e)}


def list_pod_metrics(params: Dict) -> Dict:
    """Raw pod metrics from metrics.k8s.io (if installed)."""
    try:
        cluster_id = _param(params, "cluster_id", "clusterId")
        if not cluster_id:
            return {"error": "Missing cluster_id/clusterId"}
        ns = _param(params, "namespace")
        api_client = get_core_v1_client(cluster_id).api_client
        co = k8s_client.CustomObjectsApi(api_client)
        if ns:
            data = co.list_namespaced_custom_object("metrics.k8s.io", "v1beta1", ns, "pods")
        else:
            data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods")
        return {"available": True, "items": data.get("items", [])}
    except Exception as e:
        return {"available": False, "reason": str(e)}