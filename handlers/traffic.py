# handlers/traffic.py
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from kubernetes import client as k8s
from kubernetes.client import ApiException
from oke_auth import get_core_v1_client  # your existing, cluster-authenticated client

def _clients(cluster_id: str) -> Tuple[k8s.CoreV1Api, k8s.NetworkingV1Api]:
    core = get_core_v1_client(cluster_id=cluster_id)
    net = k8s.NetworkingV1Api(api_client=core.api_client)
    return core, net

def _ingress_index(net: k8s.NetworkingV1Api, ns: str) -> Dict[str, List[k8s.V1Ingress]]:
    """Map serviceName -> [Ingress] in namespace."""
    m: Dict[str, List[k8s.V1Ingress]] = {}
    try:
        ings = net.list_namespaced_ingress(namespace=ns).items
    except ApiException:
        return m

    for ing in ings:
        # default backend
        try:
            b = ing.spec.default_backend
            if b and b.service and b.service.name:
                m.setdefault(b.service.name, []).append(ing)
        except Exception:
            pass
        # rules
        try:
            for rule in (ing.spec.rules or []):
                paths = rule.http.paths if (rule and rule.http) else []
                for p in paths or []:
                    svc = getattr(getattr(p, "backend", None), "service", None)
                    if svc and svc.name:
                        m.setdefault(svc.name, []).append(ing)
        except Exception:
            pass
    return m

def _service_node(svc: k8s.V1Service) -> Dict:
    t = (svc.spec.type or "ClusterIP").upper()
    ports = [{"port": p.port, "protocol": p.protocol, "targetPort": p.target_port} for p in (svc.spec.ports or [])]
    lb = []
    if t == "LOADBALANCER" and svc.status and svc.status.load_balancer and svc.status.load_balancer.ingress:
        for e in svc.status.load_balancer.ingress:
            lb.append({"ip": getattr(e, "ip", None), "hostname": getattr(e, "hostname", None)})
    return {
        "id": f"svc:{svc.metadata.namespace}/{svc.metadata.name}",
        "kind": "service",
        "name": svc.metadata.name,
        "namespace": svc.metadata.namespace,
        "type": t,
        "selector": svc.spec.selector or {},
        "ports": ports,
        "loadBalancer": lb or None,
    }

def _pod_node(pod: k8s.V1Pod) -> Dict:
    ctrs = [c.name for c in (pod.spec.containers or [])]
    return {
        "id": f"pod:{pod.metadata.namespace}/{pod.metadata.name}",
        "kind": "pod",
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "labels": pod.metadata.labels or {},
        "nodeName": pod.spec.node_name,
        "podIP": pod.status.pod_ip if (pod.status and pod.status.pod_ip) else None,
        "containers": ctrs,
    }

def _ingress_node(ing: k8s.V1Ingress) -> Dict:
    hosts = [r.host for r in (ing.spec.rules or []) if r and r.host] if ing.spec else []
    return {
        "id": f"ing:{ing.metadata.namespace}/{ing.metadata.name}",
        "kind": "ingress",
        "name": ing.metadata.name,
        "namespace": ing.metadata.namespace,
        "hosts": hosts,
        "class": getattr(getattr(ing.spec, "ingress_class_name", None), "value", None) if ing.spec else None
                      or getattr(ing.spec, "ingress_class_name", None),
    }

def _pods_for_selector(core: k8s.CoreV1Api, ns: str, sel: Dict[str, str]) -> List[k8s.V1Pod]:
    if not sel:
        return []
    label_selector = ",".join(f"{k}={v}" for k, v in sel.items())
    try:
        return core.list_namespaced_pod(namespace=ns, label_selector=label_selector).items
    except ApiException:
        return []

def build_graph_for_service(cluster_id: str, name: str, namespace: str = "default") -> Dict:
    core, net = _clients(cluster_id)
    try:
        svc = core.read_namespaced_service(name=name, namespace=namespace)
    except ApiException:
        return {"nodes": [], "edges": [], "meta": {"namespace": namespace, "warnings": [f"Service {name} not found"]}}

    nodes: Dict[str, Dict] = {}
    edges: List[Dict] = []
    add = lambda n: nodes.setdefault(n["id"], n)

    svcN = _service_node(svc); add(svcN)

    # LB path: internet -> LB -> service
    if svcN["type"] == "LOADBALANCER":
        lb_id = f"lb:{namespace}/{name}"
        add({"id": lb_id, "kind": "lb", "name": name, "namespace": namespace, "endpoints": svcN["loadBalancer"]})
        add({"id": "internet", "kind": "internet", "name": "internet"})
        edges += [{"from": "internet", "to": lb_id, "type": "external"}, {"from": lb_id, "to": svcN["id"], "type": "targets"}]

    # Ingress path: internet -> ingress -> service
    ing_index = _ingress_index(net, namespace)
    for ing in ing_index.get(name, []):
        ingN = _ingress_node(ing); add(ingN)
        add({"id": "internet", "kind": "internet", "name": "internet"})
        edges += [{"from": "internet", "to": ingN["id"], "type": "external"}, {"from": ingN["id"], "to": svcN["id"], "type": "routes"}]

    # Downstream: service -> pods
    for pod in _pods_for_selector(core, namespace, svcN["selector"]):
        podN = _pod_node(pod); add(podN)
        edges.append({"from": svcN["id"], "to": podN["id"], "type": "selects"})

    return {"nodes": list(nodes.values()), "edges": edges, "meta": {"namespace": namespace, "root": svcN["id"]}}

def build_graph_for_pod(cluster_id: str, name: str, namespace: str = "default") -> Dict:
    core, net = _clients(cluster_id)
    try:
        pod = core.read_namespaced_pod(name=name, namespace=namespace)
    except ApiException:
        return {"nodes": [], "edges": [], "meta": {"namespace": namespace, "warnings": [f"Pod {name} not found"]}}

    nodes: Dict[str, Dict] = {}
    edges: List[Dict] = []
    add = lambda n: nodes.setdefault(n["id"], n)

    podN = _pod_node(pod); add(podN)

    # Services that select this pod
    try:
        svcs = core.list_namespaced_service(namespace=namespace).items
    except ApiException:
        svcs = []

    def selects(svc: k8s.V1Service) -> bool:
        sel = svc.spec.selector or {}
        if not sel:
            return False
        labels = pod.metadata.labels or {}
        return all(labels.get(k) == v for k, v in sel.items())

    attached_svcs = [s for s in svcs if selects(s)]
    ing_index = _ingress_index(net, namespace)

    for s in attached_svcs:
        svcN = _service_node(s); add(svcN)
        edges.append({"from": svcN["id"], "to": podN["id"], "type": "selects"})

        # LB: internet -> lb -> service
        if svcN["type"] == "LOADBALANCER":
            lb_id = f"lb:{namespace}/{s.metadata.name}"
            add({"id": lb_id, "kind": "lb", "name": s.metadata.name, "namespace": namespace, "endpoints": svcN["loadBalancer"]})
            add({"id": "internet", "kind": "internet", "name": "internet"})
            edges += [{"from": "internet", "to": lb_id, "type": "external"}, {"from": lb_id, "to": svcN["id"], "type": "targets"}]

        # Ingress: internet -> ingress -> service
        for ing in ing_index.get(s.metadata.name, []):
            ingN = _ingress_node(ing); add(ingN)
            add({"id": "internet", "kind": "internet", "name": "internet"})
            edges += [{"from": "internet", "to": ingN["id"], "type": "external"}, {"from": ingN["id"], "to": svcN["id"], "type": "routes"}]

    return {"nodes": list(nodes.values()), "edges": edges, "meta": {"namespace": namespace, "root": podN["id"]}}