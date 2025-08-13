from __future__ import annotations
from typing import Optional, Dict, List
from fastmcp import Context
from kubernetes import client as k8s_client
from kubernetes.client import exceptions as k8s_exceptions
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

# Inserted helper function
def _service_public_endpoints(api: k8s_client.CoreV1Api, s) -> dict:
    """Return external info for a Service (if any) and target pods."""
    spec = getattr(s, "spec", None)
    stype = getattr(spec, "type", None) or ""
    ns = getattr(s.metadata, "namespace", "")
    name = getattr(s.metadata, "name", "")

    lb = getattr(getattr(s, "status", None), "load_balancer", None)
    ing = getattr(lb, "ingress", None) if lb else None
    lb_hosts = []
    if ing:
        for i in ing:
            h = getattr(i, "hostname", None) or getattr(i, "ip", None)
            if h:
                lb_hosts.append(h)

    ports = getattr(spec, "ports", []) or []
    nodeports = [getattr(p, "node_port", None) for p in ports if getattr(p, "node_port", None)]

    selector = getattr(spec, "selector", None) or {}
    pods_slim = []
    if selector:
        sel = ",".join(f"{k}={v}" for k, v in selector.items())
        try:
            pods = api.list_namespaced_pod(ns, label_selector=sel, limit=200).items
            for p in pods:
                pods_slim.append(_summary_pod(p))
        except Exception:
            pass

    return {
        "service": {"namespace": ns, "name": name, "type": stype},
        "loadBalancer": lb_hosts or None,
        "nodePorts": nodeports or None,
        "pods": pods_slim,
    }

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
    net = k8s_client.NetworkingV1Api(api.api_client)
    storage = k8s_client.StorageV1Api(api.api_client)

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
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "service":
        resp = (api.list_namespaced_service(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                api.list_service_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        svcs = resp.items
        items = [{"name": s.metadata.name, "namespace": s.metadata.namespace, "type": getattr(s.spec, "type", None)} for s in svcs]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

        if hints:
            for s in svcs:
                sel = getattr(getattr(s, "spec", None), "selector", None) or {}
                ns = getattr(s.metadata, "namespace", None)
                svc_type = getattr(getattr(s, "spec", None), "type", None)
                # Service selector -> pods
                if sel and ns:
                    selector_str = ",".join([f"{k}={v}" for k, v in sel.items()])
                    try:
                        pods = api.list_namespaced_pod(namespace=ns, label_selector=selector_str).items
                    except Exception:
                        pods = []
                    sid = _obj_id("svc", ns, s.metadata.name)
                    for p in pods:
                        pid = _obj_id("pod", p.metadata.namespace, p.metadata.name)
                        edges.append({"from": sid, "to": pid, "type": "selects"})
                # LoadBalancer service: pseudo edge from lb:<svc> to svc:<svc>
                if svc_type and svc_type.lower() == "loadbalancer":
                    sid = _obj_id("svc", ns, s.metadata.name)
                    lbid = f"lb:{ns}/{s.metadata.name}"
                    edges.append({"from": lbid, "to": sid, "type": "traffic"})

    elif kind_l == "namespace":
        resp = api.list_namespace(limit=limit, _continue=continue_token)
        items = [{"name": o.metadata.name} for o in resp.items]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "node":
        resp = api.list_node(limit=limit, _continue=continue_token)
        items = [{"name": o.metadata.name} for o in resp.items]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "deployment":
        resp = (apps.list_namespaced_deployment(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                apps.list_deployment_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        deps = resp.items
        items = [{"name": d.metadata.name, "namespace": d.metadata.namespace,
                  "replicas": getattr(d.status, "replicas", 0),
                  "available": getattr(d.status, "available_replicas", 0)} for d in deps]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "replicaset":
        resp = (apps.list_namespaced_replica_set(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
                if namespace else
                apps.list_replica_set_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token))
        rs = resp.items
        items = [{"name": r.metadata.name, "namespace": r.metadata.namespace} for r in rs]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "endpoints":
        resp = (api.list_namespaced_endpoints(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                api.list_endpoints_for_all_namespaces(limit=limit, _continue=continue_token))
        eps = resp.items
        items = [{"name": e.metadata.name, "namespace": e.metadata.namespace} for e in eps]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "endpointslice":
        resp = (disc.list_namespaced_endpoint_slice(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                disc.list_endpoint_slice_for_all_namespaces(limit=limit, _continue=continue_token))
        es = resp.items
        items = [{"name": e.metadata.name, "namespace": e.metadata.namespace} for e in es]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l in ("hpa", "horizontalpodautoscaler"):
        resp = (autos.list_namespaced_horizontal_pod_autoscaler(namespace=namespace, limit=limit, _continue=continue_token)
                if namespace else
                autos.list_horizontal_pod_autoscaler_for_all_namespaces(limit=limit, _continue=continue_token))
        hpas = resp.items
        items = [{"name": h.metadata.name, "namespace": h.metadata.namespace,
                  "minReplicas": getattr(h.spec, "min_replicas", None),
                  "maxReplicas": getattr(h.spec, "max_replicas", None)} for h in hpas]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

    elif kind_l == "ingress":
        resp = (
            net.list_namespaced_ingress(namespace=namespace, label_selector=label_selector, limit=limit, _continue=continue_token)
            if namespace else
            net.list_ingress_for_all_namespaces(label_selector=label_selector, limit=limit, _continue=continue_token)
        )
        ings = resp.items
        def _ing_item(ing):
            spec = getattr(ing, "spec", None)
            rules = getattr(spec, "rules", []) or []
            hosts = [getattr(r, "host", None) for r in rules if getattr(r, "host", None)]
            tls = bool(getattr(spec, "tls", None))
            cls = getattr(spec, "ingress_class_name", None)
            return {
                "name": ing.metadata.name,
                "namespace": ing.metadata.namespace,
                "class": cls,
                "hosts": hosts,
                "tls": tls,
                "rules": len(rules),
            }
        items = [_ing_item(i) for i in ings]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

        if hints:
            for ing in ings:
                spec = getattr(ing, "spec", None)
                ns = getattr(getattr(ing, "metadata", None), "namespace", None)
                if not spec or not ns:
                    continue
                # default backend
                backend = getattr(spec, "default_backend", None)
                if backend and getattr(backend, "service", None):
                    svc = backend.service
                    svc_name = getattr(svc, "name", None)
                    if svc_name:
                        edges.append({
                            "from": _obj_id("ing", ns, ing.metadata.name),
                            "to": _obj_id("svc", ns, svc_name),
                            "type": "routes"
                        })
                # rules -> http -> paths -> backend.service
                for r in getattr(spec, "rules", []) or []:
                    http = getattr(r, "http", None)
                    for path in (getattr(http, "paths", []) or []):
                        b = getattr(path, "backend", None)
                        svc = getattr(b, "service", None) if b else None
                        svc_name = getattr(svc, "name", None) if svc else None
                        if svc_name:
                            edges.append({
                                "from": _obj_id("ing", ns, ing.metadata.name),
                                "to": _obj_id("svc", ns, svc_name),
                                "type": "routes"
                            })

    elif kind_l == "gateway":
        # Try to use k8s_client.ApigatewayV1beta1Api if available, otherwise use CustomObjectsApi
        try:
            apigw = getattr(k8s_client, "ApigatewayV1beta1Api", None)
        except Exception:
            apigw = None
        if apigw:
            api_gw = apigw(api.api_client)
            # Not all clusters will have this, fallback to CRD
            try:
                resp = (api_gw.list_namespaced_gateway(namespace=namespace, limit=limit, _continue=continue_token)
                        if namespace else
                        api_gw.list_gateway_for_all_namespaces(limit=limit, _continue=continue_token))
                gws = resp.items
                cont = getattr(resp, "metadata", None)._continue if getattr(resp, "metadata", None) else None
            except Exception:
                gws = []
                cont = None
        else:
            # Use CustomObjectsApi for CRD
            co = k8s_client.CustomObjectsApi(api.api_client)
            group = "gateway.networking.k8s.io"
            version = "v1beta1"
            plural = "gateways"
            if namespace:
                resp = co.list_namespaced_custom_object(group, version, namespace, plural, limit=limit, _continue=continue_token)
            else:
                resp = co.list_cluster_custom_object(group, version, plural, limit=limit, _continue=continue_token)
            gws = resp.get("items", [])
            cont = resp.get("metadata", {}).get("continue")
        # Normalize items
        def _gw_item(gw):
            meta = gw.metadata if hasattr(gw, "metadata") else gw.get("metadata", {})
            spec = getattr(gw, "spec", None) if hasattr(gw, "spec") else gw.get("spec", {})
            listeners = getattr(spec, "listeners", None) if hasattr(spec, "listeners") else spec.get("listeners", [])
            return {
                "name": getattr(meta, "name", None) if hasattr(meta, "name") else meta.get("name"),
                "namespace": getattr(meta, "namespace", None) if hasattr(meta, "namespace") else meta.get("namespace"),
                "listeners": [getattr(l, "name", None) if hasattr(l, "name") else l.get("name") for l in listeners],
            }
        items = [_gw_item(g) for g in gws]
        # Hints: Add edges from gateway to referenced services in routes (if any)
        if hints:
            # Look for HTTPRoutes that reference this gateway
            co = k8s_client.CustomObjectsApi(api.api_client)
            group = "gateway.networking.k8s.io"
            version = "v1beta1"
            plural = "httproutes"
            if namespace:
                hresp = co.list_namespaced_custom_object(group, version, namespace, plural, limit=100)
                htrs = hresp.get("items", [])
            else:
                hresp = co.list_cluster_custom_object(group, version, plural, limit=100)
                htrs = hresp.get("items", [])
            for gw in gws:
                gw_meta = gw.metadata if hasattr(gw, "metadata") else gw.get("metadata", {})
                gw_name = getattr(gw_meta, "name", None) if hasattr(gw_meta, "name") else gw_meta.get("name")
                gw_ns = getattr(gw_meta, "namespace", None) if hasattr(gw_meta, "namespace") else gw_meta.get("namespace")
                gwid = _obj_id("gateway", gw_ns, gw_name)
                # For each HTTPRoute, see if this gateway is attached
                for htr in htrs:
                    htr_spec = htr.get("spec", {})
                    parent_refs = htr_spec.get("parentRefs", [])
                    for pref in parent_refs:
                        pref_name = pref.get("name")
                        pref_ns = pref.get("namespace", gw_ns)
                        if pref_name == gw_name and pref_ns == gw_ns:
                            # Route is attached to this gateway
                            # Add edge from gateway to referenced services in rules
                            rules = htr_spec.get("rules", [])
                            for rule in rules:
                                backend_refs = rule.get("backendRefs", [])
                                for bref in backend_refs:
                                    svcname = bref.get("name")
                                    svcns = bref.get("namespace", htr.get("metadata", {}).get("namespace", gw_ns))
                                    if svcname:
                                        edges.append({
                                            "from": gwid,
                                            "to": _obj_id("svc", svcns, svcname),
                                            "type": "routes"
                                        })

    elif kind_l == "httproute":
        co = k8s_client.CustomObjectsApi(api.api_client)
        group = "gateway.networking.k8s.io"
        version = "v1beta1"
        plural = "httproutes"
        if namespace:
            resp = co.list_namespaced_custom_object(group, version, namespace, plural, limit=limit, _continue=continue_token)
        else:
            resp = co.list_cluster_custom_object(group, version, plural, limit=limit, _continue=continue_token)
        htrs = resp.get("items", [])
        cont = resp.get("metadata", {}).get("continue")
        def _htr_item(htr):
            meta = htr.get("metadata", {})
            spec = htr.get("spec", {})
            rules = spec.get("rules", [])
            parent_refs = spec.get("parentRefs", [])
            return {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "rules": len(rules),
                "parentRefs": [{"name": pr.get("name"), "namespace": pr.get("namespace")} for pr in parent_refs],
            }
        items = [_htr_item(h) for h in htrs]
        # Hints: Add edges from HTTPRoute to referenced services
        if hints:
            for htr in htrs:
                meta = htr.get("metadata", {})
                spec = htr.get("spec", {})
                htrid = _obj_id("httproute", meta.get("namespace"), meta.get("name"))
                rules = spec.get("rules", [])
                for rule in rules:
                    backend_refs = rule.get("backendRefs", [])
                    for bref in backend_refs:
                        svcname = bref.get("name")
                        svcns = bref.get("namespace", meta.get("namespace"))
                        if svcname:
                            edges.append({
                                "from": htrid,
                                "to": _obj_id("svc", svcns, svcname),
                                "type": "routes"
                            })

    elif kind_l in ("persistentvolumeclaim", "pvc"):
        resp = (
            api.list_namespaced_persistent_volume_claim(namespace=namespace, limit=limit, _continue=continue_token, label_selector=label_selector, field_selector=field_selector)
            if namespace else
            api.list_persistent_volume_claim_for_all_namespaces(limit=limit, _continue=continue_token, label_selector=label_selector, field_selector=field_selector)
        )
        pvcs = resp.items
        items = [{
            "name": p.metadata.name,
            "namespace": p.metadata.namespace,
            "status": getattr(getattr(p, "status", None), "phase", None),
            "volume": getattr(getattr(p, "status", None), "volume_name", None),
            "storageClass": getattr(getattr(p, "spec", None), "storage_class_name", None) or getattr(getattr(p, "spec", None), "storageClassName", None),
            "accessModes": getattr(getattr(p, "spec", None), "access_modes", None),
            "requested": (getattr(getattr(getattr(p, "spec", None), "resources", None), "requests", {}) or {}).get("storage") if getattr(getattr(p, "spec", None), "resources", None) else None,
        } for p in pvcs]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

        if hints:
            # PVC -> PV edges
            for p in pvcs:
                ns = getattr(getattr(p, "metadata", None), "namespace", None)
                pvc_name = getattr(getattr(p, "metadata", None), "name", None)
                pv_name = getattr(getattr(p, "status", None), "volume_name", None)
                if ns and pvc_name and pv_name:
                    edges.append({
                        "from": _obj_id("pvc", ns, pvc_name),
                        "to": _obj_id("pv", None, pv_name),
                        "type": "binds"
                    })
            # PVC -> Pod edges (pods mounting this claim)
            try:
                # Limit workload to namespace when provided, else skip for safety
                ns_list = [namespace] if namespace else []
                if namespace:
                    pod_list = api.list_namespaced_pod(namespace=namespace, limit=200).items
                    for p in pvcs:
                        pvc_ns = getattr(getattr(p, "metadata", None), "namespace", None)
                        pvc_name = getattr(getattr(p, "metadata", None), "name", None)
                        if not pvc_ns or not pvc_name:
                            continue
                        for pod in pod_list:
                            for vol in getattr(getattr(pod, "spec", None), "volumes", []) or []:
                                pvc_src = getattr(vol, "persistent_volume_claim", None)
                                if pvc_src and getattr(pvc_src, "claim_name", None) == pvc_name and pod.metadata.namespace == pvc_ns:
                                    edges.append({
                                        "from": _obj_id("pvc", pvc_ns, pvc_name),
                                        "to": _obj_id("pod", pod.metadata.namespace, pod.metadata.name),
                                        "type": "mountedBy"
                                    })
            except Exception:
                pass

    elif kind_l in ("persistentvolume", "pv"):
        resp = api.list_persistent_volume(limit=limit, _continue=continue_token)
        pvs = resp.items
        def _pv_item(v):
            spec = getattr(v, "spec", None)
            cap = (getattr(getattr(v, "spec", None), "capacity", {}) or {}).get("storage") if spec else None
            return {
                "name": v.metadata.name,
                "capacity": cap,
                "reclaimPolicy": getattr(spec, "persistent_volume_reclaim_policy", None) if spec else None,
                "storageClass": getattr(spec, "storage_class_name", None) if spec else None,
                "csi": getattr(getattr(spec, "csi", None), "driver", None) if spec and getattr(spec, "csi", None) else None,
                "nfs": getattr(getattr(spec, "nfs", None), "server", None) if spec and getattr(spec, "nfs", None) else None,
                "ociBlock": getattr(getattr(spec, "oci_block_volume", None), "volume_id", None) if spec and getattr(spec, "oci_block_volume", None) else None,
                "claimRef": (getattr(getattr(spec, "claim_ref", None), "namespace", None), getattr(getattr(spec, "claim_ref", None), "name", None)) if spec and getattr(spec, "claim_ref", None) else None,
            }
        items = [_pv_item(v) for v in pvs]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)

        if hints:
            for v in pvs:
                spec = getattr(v, "spec", None)
                sc = getattr(spec, "storage_class_name", None) if spec else None
                if sc:
                    edges.append({
                        "from": _obj_id("pv", None, v.metadata.name),
                        "to": _obj_id("storageclass", None, sc),
                        "type": "provisionedBy"
                    })
                # PV -> PVC (claimRef)
                claim_ref = getattr(spec, "claim_ref", None) if spec else None
                if claim_ref and getattr(claim_ref, "name", None):
                    edges.append({
                        "from": _obj_id("pv", None, v.metadata.name),
                        "to": _obj_id("pvc", getattr(claim_ref, "namespace", None), getattr(claim_ref, "name", None)),
                        "type": "boundTo"
                    })

    elif kind_l in ("storageclass", "sc"):
        resp = storage.list_storage_class(limit=limit, _continue=continue_token)
        scs = resp.items
        def _sc_item(sc):
            return {
                "name": sc.metadata.name,
                "provisioner": getattr(sc, "provisioner", None),
                "reclaimPolicy": getattr(sc, "reclaim_policy", None) or getattr(sc, "reclaimPolicy", None),
                "parameters": getattr(sc, "parameters", None),
                "allowVolumeExpansion": getattr(sc, "allow_volume_expansion", None) if hasattr(sc, "allow_volume_expansion") else getattr(sc, "allowVolumeExpansion", None),
            }
        items = [_sc_item(sc) for sc in scs]
        cont = getattr(getattr(resp, "metadata", None), "continue", None)
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
    elif k == "ingress":
        net = k8s_client.NetworkingV1Api(api.api_client)
        ing = net.read_namespaced_ingress(name=name, namespace=namespace)
        spec = getattr(ing, "spec", None)
        rules = getattr(spec, "rules", []) or []
        hosts = [getattr(r, "host", None) for r in rules if getattr(r, "host", None)]
        tls = bool(getattr(spec, "tls", None))
        cls = getattr(spec, "ingress_class_name", None)
        backends = []
        # default backend
        backend = getattr(spec, "default_backend", None)
        if backend and getattr(backend, "service", None):
            svc = backend.service
            backends.append({
                "service": getattr(svc, "name", None),
                "port": getattr(getattr(svc, "port", None), "number", None) or getattr(getattr(svc, "port", None), "name", None)
            })
        # rules paths backends
        for r in rules:
            http = getattr(r, "http", None)
            for p in (getattr(http, "paths", []) or []):
                b = getattr(p, "backend", None)
                svc = getattr(b, "service", None) if b else None
                if svc:
                    backends.append({
                        "service": getattr(svc, "name", None),
                        "port": getattr(getattr(svc, "port", None), "number", None) or getattr(getattr(svc, "port", None), "name", None)
                    })
        return {
            "name": ing.metadata.name,
            "namespace": ing.metadata.namespace,
            "class": cls,
            "hosts": hosts,
            "tls": tls,
            "backends": backends,
        }
    elif k == "gateway":
        # Try to use ApigatewayV1beta1Api, else CustomObjectsApi
        try:
            apigw = getattr(k8s_client, "ApigatewayV1beta1Api", None)
        except Exception:
            apigw = None
        if apigw:
            api_gw = apigw(api.api_client)
            try:
                gw = api_gw.read_namespaced_gateway(name=name, namespace=namespace)
                meta = getattr(gw, "metadata", None)
                spec = getattr(gw, "spec", None)
                listeners = getattr(spec, "listeners", []) if spec else []
                return {
                    "name": getattr(meta, "name", None),
                    "namespace": getattr(meta, "namespace", None),
                    "listeners": [getattr(l, "name", None) for l in listeners],
                }
            except Exception:
                return {"error": f"gateway not found"}
        else:
            co = k8s_client.CustomObjectsApi(api.api_client)
            group = "gateway.networking.k8s.io"
            version = "v1beta1"
            plural = "gateways"
            gw = co.get_namespaced_custom_object(group, version, namespace, plural, name)
            meta = gw.get("metadata", {})
            spec = gw.get("spec", {})
            listeners = spec.get("listeners", [])
            return {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "listeners": [l.get("name") for l in listeners],
            }
    elif k == "httproute":
        co = k8s_client.CustomObjectsApi(api.api_client)
        group = "gateway.networking.k8s.io"
        version = "v1beta1"
        plural = "httproutes"
        htr = co.get_namespaced_custom_object(group, version, namespace, plural, name)
        meta = htr.get("metadata", {})
        spec = htr.get("spec", {})
        rules = spec.get("rules", [])
        parent_refs = spec.get("parentRefs", [])
        return {
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "rules": len(rules),
            "parentRefs": [{"name": pr.get("name"), "namespace": pr.get("namespace")} for pr in parent_refs],
        }
    elif k in ("persistentvolumeclaim", "pvc"):
        p = api.read_namespaced_persistent_volume_claim(name=name, namespace=namespace)
        spec = getattr(p, "spec", None)
        status = getattr(p, "status", None)
        return {
            "name": p.metadata.name,
            "namespace": p.metadata.namespace,
            "status": getattr(status, "phase", None),
            "volume": getattr(status, "volume_name", None),
            "storageClass": getattr(spec, "storage_class_name", None) or getattr(spec, "storageClassName", None),
            "accessModes": getattr(spec, "access_modes", None),
            "requested": (getattr(getattr(spec, "resources", None), "requests", {}) or {}).get("storage") if getattr(spec, "resources", None) else None,
        }
    elif k in ("persistentvolume", "pv"):
        v = api.read_persistent_volume(name=name)
        spec = getattr(v, "spec", None)
        cap = (getattr(spec, "capacity", {}) or {}).get("storage") if spec else None
        claim = getattr(spec, "claim_ref", None)
        return {
            "name": v.metadata.name,
            "capacity": cap,
            "reclaimPolicy": getattr(spec, "persistent_volume_reclaim_policy", None) if spec else None,
            "storageClass": getattr(spec, "storage_class_name", None) if spec else None,
            "csi": getattr(getattr(spec, "csi", None), "driver", None) if spec and getattr(spec, "csi", None) else None,
            "nfs": getattr(getattr(spec, "nfs", None), "server", None) if spec and getattr(spec, "nfs", None) else None,
            "ociBlock": getattr(getattr(spec, "oci_block_volume", None), "volume_id", None) if spec and getattr(spec, "oci_block_volume", None) else None,
            "claimRef": {"namespace": getattr(claim, "namespace", None), "name": getattr(claim, "name", None)} if claim else None,
        }
    elif k in ("storageclass", "sc"):
        storage = k8s_client.StorageV1Api(api.api_client)
        sc = storage.read_storage_class(name=name)
        return {
            "name": sc.metadata.name,
            "provisioner": getattr(sc, "provisioner", None),
            "reclaimPolicy": getattr(sc, "reclaim_policy", None) or getattr(sc, "reclaimPolicy", None),
            "parameters": getattr(sc, "parameters", None),
            "allowVolumeExpansion": getattr(sc, "allow_volume_expansion", None) if hasattr(sc, "allow_volume_expansion") else getattr(sc, "allowVolumeExpansion", None),
        }
    else:
        return {"error": f"unsupported kind: {kind}"}
# Inserted by instruction: new tool function for pod logs
def oke_get_pod_logs(
    ctx: Context,
    cluster_id: str,
    namespace: str,
    pod: str,
    container: Optional[str] = None,
    tail_lines: int = 200,
    since_seconds: Optional[int] = None,
    previous: Optional[bool] = None,
    timestamps: Optional[bool] = False,
    endpoint: Optional[str] = None,
    auth: Optional[str] = None,
) -> Dict:
    """
    Fetch logs from a given pod (optionally a specific container) in an OKE cluster.
    Compatible with the original v0.1.0 behavior; adds explicit timeouts to avoid hangs.
    """
    # Required params validation
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    if not namespace:
        raise ValueError("Missing namespace")
    if not pod:
        raise ValueError("Missing pod/name")

    # Normalize numeric/bool inputs like v0.1.0
    try:
        _tail = int(tail_lines) if tail_lines is not None else 200
    except Exception:
        _tail = 200
    try:
        _since = int(since_seconds) if since_seconds is not None else None
    except Exception:
        _since = None
    _prev = bool(previous) if previous is not None else None
    _ts = bool(timestamps) if timestamps is not None else False

    # Cap tail to avoid flooding
    if _tail is not None:
        _tail = max(1, min(_tail, 5000))

    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)

    # Build kwargs only with values provided (client may error on None)
    kwargs = {}
    if container:
        kwargs["container"] = container
    if _tail is not None:
        kwargs["tail_lines"] = _tail
    if _since is not None:
        kwargs["since_seconds"] = _since
    if _prev is not None:
        kwargs["previous"] = _prev
    if _ts:
        kwargs["timestamps"] = _ts

    try:
        text = api.read_namespaced_pod_log(
            name=pod,
            namespace=namespace,
            _preload_content=True,
            _request_timeout=(10, 65),  # (connect, read) seconds to avoid hangs
            pretty="true",
            **kwargs,
        )

        # Truncate very large logs to keep responses snappy
        truncated = False
        if isinstance(text, str) and len(text) > 200_000:
            text = text[-200_000:]
            truncated = True

        return {
            "namespace": namespace,
            "pod": pod,
            "container": container,
            "tail_lines": _tail,
            "since_seconds": _since,
            "previous": _prev,
            "timestamps": _ts,
            "truncated": truncated,
            "log": text or "",
        }
    except k8s_exceptions.ApiException as e:
        body = getattr(e, "body", "") or ""
        if e.status == 404:
            # Provide helpful suggestions when the pod isn't found
            suggestions = []
            try:
                pods = api.list_namespaced_pod(namespace=namespace, limit=200).items
                suggestions = [
                    {
                        "name": getattr(p.metadata, "name", ""),
                        "containers": [c.name for c in (getattr(getattr(p, "spec", None), "containers", []) or [])],
                    }
                    for p in pods
                ]
            except Exception:
                pass
            return {
                "error": f"pod '{pod}' not found in namespace '{namespace}'",
                "status": 404,
                "suggestions": suggestions,
            }
        # kubelet 10250 timeout pattern: surface clearer hint
        if e.status in (500, 504) and ("10250" in body or "containerLogs" in body):
            return {
                "error": "failed to fetch logs: kubelet timeout",
                "status": e.status,
                "body": body,
                "hints": [
                    "This comes from apiserver proxying to kubelet:10250.",
                    "If using STS security_token, run the auth_refresh tool and retry.",
                    "Check OKE control-plane reachability to nodes (NSGs / private endpoint).",
                ],
            }
        return {"error": "failed to fetch logs", "status": e.status, "body": body}
    except Exception as ex:
        return {"error": f"failed to fetch logs: {ex!s}"}
# Replace the body of oke_service_endpoints as per instructions
def oke_service_endpoints(ctx: Context, cluster_id: str, service: str, namespace: str, endpoint: Optional[str] = None, auth: Optional[str] = None) -> Dict:
    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)
    try:
        s = api.read_namespaced_service(name=service, namespace=namespace)
        return _service_public_endpoints(api, s)
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            try:
                svcs = api.list_namespaced_service(namespace=namespace, limit=200).items
                suggestions = [{"name": x.metadata.name, "type": getattr(getattr(x, "spec", None), "type", None)} for x in svcs]
            except Exception:
                suggestions = []
            return {
                "error": f"service '{service}' not found in '{namespace}'",
                "suggestions": suggestions,
            }
        raise