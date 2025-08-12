from __future__ import annotations
from typing import Optional, Dict, List
from fastmcp import Context
from kubernetes import client as k8s_client
from ..auth import get_core_v1_client

# Helpers

def _obj_id(kind: str, ns: Optional[str], name: str) -> str:
    return f"{kind.lower()}:{ns + '/' if ns else ''}{name}"

def _summary_pod(p) -> dict:
    meta = getattr(p, "metadata", None)
    status = getattr(p, "status", None)
    return {
        "name": getattr(meta, "name", ""),
        "namespace": getattr(meta, "namespace", ""),
        "phase": getattr(status, "phase", None),
        "ready": _pod_ready(status),
    }

def _pod_ready(status) -> Optional[str]:
    try:
        conds = getattr(status, "conditions", []) or []
        ready = next((c.status for c in conds if getattr(c, "type", "") == "Ready"), None)
        return ready
    except Exception:
        return None

# Tools

def k8s_list(
    ctx: Context,
    cluster_id: str,
    kind: str,
    namespace: Optional[str] = None,
    label_selector: Optional[str] = None,
    field_selector: Optional[str] = None,
    limit: Optional[int] = 20,
    continue_token: Optional[str] = None,
    endpoint: Optional[str] = None,
    hints: bool = True,
    auth: Optional[str] = None
) -> Dict:
    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)
    apps = k8s_client.AppsV1Api(api.api_client)
    disc = k8s_client.DiscoveryV1Api(api.api_client)
    autos = k8s_client.AutoscalingV2Api(api.api_client)

    kind_l = (kind or "").lower()
    items: List[dict] = []
    cont = None
    edges: List[dict] = []

    if kind_l == "pod":
        resp = (api.list_namespaced_pod(namespace=namespace, label_selector=label_selector,
                                        field_selector=field_selector, limit=limit, _continue=continue_token)
                if namespace else
                api.list_pod_for_all_namespaces(label_selector=label_selector, field_selector=field_selector, limit=limit, _continue=continue_token))
        items = [_summary_pod(o) for o in resp.items]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "service":
        resp = (api.list_namespaced_service(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                api.list_service_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        svcs = resp.items
        items = [{"name": s.metadata.name, "namespace": s.metadata.namespace, "type": getattr(s.spec, "type", None)} for s in svcs]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

        if hints:
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
                sid = _obj_id("svc", ns, s.metadata.name)
                for p in pods:
                    pid = _obj_id("pod", p.metadata.namespace, p.metadata.name)
                    edges.append({"from": sid, "to": pid, "type": "selects"})

    elif kind_l == "namespace":
        resp = api.list_namespace(limit=limit, _continue=continue_token)
        items = [{"name": o.metadata.name} for o in resp.items]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "node":
        resp = api.list_node(limit=limit, _continue=continue_token)
        items = [{"name": o.metadata.name} for o in resp.items]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "deployment":
        resp = (apps.list_namespaced_deployment(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                apps.list_deployment_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        deps = resp.items
        items = [{"name": d.metadata.name, "namespace": d.metadata.namespace,
                  "replicas": getattr(d.status, "replicas", 0),
                  "available": getattr(d.status, "available_replicas", 0)} for d in deps]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "replicaset":
        resp = (apps.list_namespaced_replica_set(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                apps.list_replica_set_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        rs = resp.items
        items = [{"name": r.metadata.name, "namespace": r.metadata.namespace} for r in rs]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "endpoints":
        resp = (api.list_namespaced_endpoints(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                api.list_endpoints_for_all_namespaces(limit=limit, _continue=continue_token))
        eps = resp.items
        items = [{"name": e.metadata.name, "namespace": e.metadata.namespace} for e in eps]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l == "endpointslice":
        resp = (disc.list_namespaced_endpoint_slice(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                disc.list_endpoint_slice_for_all_namespaces(limit=limit, _continue=continue_token))
        es = resp.items
        items = [{"name": e.metadata.name, "namespace": e.metadata.namespace} for e in es]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    elif kind_l in ("hpa", "horizontalpodautoscaler"):
        resp = (autos.list_namespaced_horizontal_pod_autoscaler(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                autos.list_horizontal_pod_autoscaler_for_all_namespaces(limit=limit, _continue=continue_token))
        hpas = resp.items
        items = [{"name": h.metadata.name, "namespace": h.metadata.namespace,
                  "minReplicas": getattr(h.spec, "min_replicas", None),
                  "maxReplicas": getattr(h.spec, "max_replicas", None)} for h in hpas]
        cont = getattr(resp, "metadata", None).continue_ if getattr(resp, "metadata", None) else None

    else:
        return {"error": f"unsupported kind: {kind}"}

    return {"items": items, "continue": cont, "hints": {"edges": edges} if hints else {}}

def k8s_get(
    ctx: Context,
    cluster_id: str,
    kind: str,
    name: str,
    namespace: Optional[str] = None,
    endpoint: Optional[str] = None,
    auth: Optional[str] = None
) -> Dict:
    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)
    apps = k8s_client.AppsV1Api(api.api_client)
    disc = k8s_client.DiscoveryV1Api(api.api_client)
    k = (kind or "").lower()

    if k == "pod":
        p = api.read_namespaced_pod(name=name, namespace=namespace)
        return _summary_pod(p)
    elif k == "service":
        s = api.read_namespaced_service(name=name, namespace=namespace)
        return {"name": s.metadata.name, "namespace": s.metadata.namespace, "type": getattr(s.spec, "type", None)}
    elif k == "namespace":
        n = api.read_namespace(name=name)
        return {"name": n.metadata.name}
    elif k == "node":
        n = api.read_node(name=name)
        return {"name": n.metadata.name}
    elif k == "deployment":
        d = apps.read_namespaced_deployment(name=name, namespace=namespace)
        return {"name": d.metadata.name, "namespace": d.metadata.namespace,
                "replicas": getattr(d.status, "replicas", 0),
                "available": getattr(d.status, "available_replicas", 0)}
    elif k == "replicaset":
        r = apps.read_namespaced_replica_set(name=name, namespace=namespace)
        return {"name": r.metadata.name, "namespace": r.metadata.namespace}
    elif k == "endpoints":
        e = api.read_namespaced_endpoints(name=name, namespace=namespace)
        return {"name": e.metadata.name, "namespace": e.metadata.namespace}
    elif k == "endpointslice":
        e = disc.read_namespaced_endpoint_slice(name=name, namespace=namespace)
        return {"name": e.metadata.name, "namespace": e.metadata.namespace}
    else:
        return {"error": f"unsupported kind: {kind}"}