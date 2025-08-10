import oci
from typing import Dict, List, Optional
from oci_auth import get_identity_client, get_container_engine_client
from oke_auth import get_core_v1_client
from oci.util import to_dict

from kubernetes import client as k8s_client
import os
import datetime as _dt


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

# --- write guard -----------------------------------------------------------

def _ensure_writes_enabled():
    if os.getenv("OKE_ENABLE_WRITE") not in ("1", "true", "True"):  # default read-only
        raise PermissionError("Write operations are disabled. Set OKE_ENABLE_WRITE=1 to enable.")


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

# =============================================================================
# Additional capabilities
# =============================================================================

def describe_resources(params: Dict) -> Dict:
    """Summarize the cluster: namespaces, pods, nodes, node pools (OCI), and recent issues.

    Inputs:
      - cluster_id (required)
      - compartment_id (optional, for node pools via OCI)
      - since_seconds (optional) for events
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    compartment_id = _param(params, "compartment_id", "compartmentId")
    since_seconds = _param(params, "since_seconds", "sinceSeconds", default=1800)

    core_v1 = get_core_v1_client(cluster_id)

    # Namespaces
    namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]

    # Pods per ns and overall counts
    total_pods = 0
    ns_counts: Dict[str, int] = {}
    unhealthy: List[Dict] = []

    for ns in namespaces:
        pods = core_v1.list_namespaced_pod(namespace=ns).items
        ns_counts[ns] = len(pods)
        total_pods += len(pods)
        for p in pods:
            phase = getattr(p.status, "phase", None)
            cs = getattr(p.status, "container_statuses", None)
            crash = False
            if cs:
                for c in cs:
                    state = getattr(c, "state", None)
                    waiting = getattr(state, "waiting", None) if state else None
                    if waiting and getattr(waiting, "reason", "") == "CrashLoopBackOff":
                        crash = True
                        break
            if phase not in ("Running", "Succeeded") or crash:
                unhealthy.append({
                    "namespace": ns,
                    "pod": getattr(p.metadata, "name", None),
                    "phase": phase,
                    "crashloop": crash,
                })

    # Recent events
    try:
        events = list_events({"cluster_id": cluster_id, "since_seconds": since_seconds})
        top_issues = events[:20]
    except Exception:
        events = []
        top_issues = []

    # Node pools (OCI) if compartment provided
    node_pools: List[Dict] = []
    if compartment_id:
        try:
            ce_client = get_container_engine_client()
            resp = ce_client.list_node_pools(compartment_id=compartment_id, cluster_id=cluster_id, limit=50)
            node_pools = [_safe_to_dict(np) for np in resp.data]
        except Exception as e:
            node_pools = [{"error": str(e)}]

    return {
        "namespaces": namespaces,
        "pod_counts": ns_counts,
        "total_pods": total_pods,
        "unhealthy_pods": unhealthy,
        "recent_events": top_issues,
        "node_pools": node_pools,
    }


def service_endpoints(params: Dict) -> Dict:
    """Return Endpoints/EndpointSlice details for a Service.

    Inputs:
      - cluster_id (required)
      - namespace (required)
      - service_name (required)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    namespace = _param(params, "namespace")
    svc_name = _param(params, "service_name", "serviceName")
    if not (cluster_id and namespace and svc_name):
        raise ValueError("cluster_id, namespace, service_name are required")

    core_v1 = get_core_v1_client(cluster_id)

    # Service ports
    svc = core_v1.read_namespaced_service(name=svc_name, namespace=namespace)
    ports = []
    for p in (getattr(svc.spec, "ports", []) or []):
        ports.append({
            "name": getattr(p, "name", None),
            "port": getattr(p, "port", None),
            "target_port": getattr(p, "target_port", None),
            "protocol": getattr(p, "protocol", None),
        })

    # Endpoints
    eps = core_v1.read_namespaced_endpoints(name=svc_name, namespace=namespace)
    backends = []
    for subset in (getattr(eps, "subsets", []) or []):
        addrs = getattr(subset, "addresses", []) or []
        not_ready = getattr(subset, "not_ready_addresses", []) or []
        ports_e = getattr(subset, "ports", []) or []
        for a in addrs:
            backends.append({
                "ip": getattr(a, "ip", None),
                "node": getattr(getattr(a, "node_name", None), "name", None) if hasattr(a, "node_name") else getattr(a, "node_name", None),
                "ready": True,
                "ports": [getattr(pp, "port", None) for pp in ports_e],
            })
        for a in not_ready:
            backends.append({
                "ip": getattr(a, "ip", None),
                "node": getattr(a, "node_name", None),
                "ready": False,
                "ports": [getattr(pp, "port", None) for pp in ports_e],
            })

    return {"service": svc_name, "ports": ports, "backends": backends}


def probe_failures(params: Dict) -> List[Dict]:
    """List pods with failing readiness/liveness probes in the last window.

    Inputs:
      - cluster_id (required)
      - namespace (optional)
      - since_seconds (optional, default 900)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    namespace = _param(params, "namespace")
    since_seconds = int(_param(params, "since_seconds", "sinceSeconds", default=900))

    events = list_events({
        "cluster_id": cluster_id,
        "namespace": namespace,
        "since_seconds": since_seconds,
        "field_selector": "reason=Unhealthy",
    })

    findings: List[Dict] = []
    for e in events:
        findings.append({
            "namespace": e.get("namespace"),
            "name": e.get("name"),
            "reason": e.get("reason"),
            "message": e.get("message"),
            "last_timestamp": e.get("last_timestamp") or e.get("event_time"),
        })
    return findings


def crashlooping(params: Dict) -> List[Dict]:
    """List containers in CrashLoopBackOff.

    Inputs:
      - cluster_id (required)
      - namespace (optional)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    namespace = _param(params, "namespace")

    core_v1 = get_core_v1_client(cluster_id)
    pods = (core_v1.list_namespaced_pod(namespace=namespace).items if namespace
            else core_v1.list_pod_for_all_namespaces().items)

    out: List[Dict] = []
    for p in pods:
        for cs in (getattr(p.status, "container_statuses", []) or []):
            st = getattr(cs, "state", None)
            wt = getattr(st, "waiting", None) if st else None
            if wt and getattr(wt, "reason", "") == "CrashLoopBackOff":
                out.append({
                    "namespace": getattr(p.metadata, "namespace", None),
                    "pod": getattr(p.metadata, "name", None),
                    "container": getattr(cs, "name", None),
                    "reason": getattr(wt, "reason", None),
                    "message": getattr(wt, "message", None),
                })
    return out


def top_pods(params: Dict) -> Dict:
    """Best-effort top pods by CPU/memory via metrics.k8s.io (if installed).

    Inputs:
      - cluster_id (required)
      - namespace (optional)
      - limit (optional, default 20)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    ns = _param(params, "namespace")
    limit = int(_param(params, "limit", default=20))

    api_client = get_core_v1_client(cluster_id).api_client
    co = k8s_client.CustomObjectsApi(api_client)
    try:
        if ns:
            data = co.list_namespaced_custom_object("metrics.k8s.io", "v1beta1", ns, "pods")
        else:
            data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods")
    except Exception as e:
        return {"available": False, "reason": str(e)}

    items = data.get("items", [])
    rows = []
    def _to_millicores(cpu: str) -> float:
        cpu = str(cpu)
        if cpu.endswith("n"):
            return float(cpu[:-1]) / 1e6
        if cpu.endswith("m"):
            return float(cpu[:-1])
        return float(cpu)
    def _to_mebibytes(mem: str) -> float:
        mem = str(mem)
        if mem.endswith("Ki"):
            return float(mem[:-2]) / 1024.0
        if mem.endswith("Mi"):
            return float(mem[:-2])
        if mem.endswith("Gi"):
            return float(mem[:-2]) * 1024.0
        return float(mem)

    for it in items:
        nsN = it.get("metadata", {}).get("namespace")
        name = it.get("metadata", {}).get("name")
        total_cpu = 0.0
        total_mem = 0.0
        for c in it.get("containers", []):
            usage = c.get("usage", {})
            total_cpu += _to_millicores(usage.get("cpu", 0))
            total_mem += _to_mebibytes(usage.get("memory", 0))
        rows.append({"namespace": nsN, "pod": name, "cpu_m": total_cpu, "mem_Mi": total_mem})

    rows.sort(key=lambda r: (r["cpu_m"], r["mem_Mi"]), reverse=True)
    return {"available": True, "items": rows[:limit]}


def rbac_who_can(params: Dict) -> Dict:
    """Naive RBAC scan to find subjects who have verb on resource (namespace-scoped).

    Inputs:
      - cluster_id (required)
      - verb (required): get|list|watch|create|update|patch|delete
      - resource (required): e.g., pods, deployments
      - namespace (optional): default to cluster-scope role bindings otherwise
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    verb = _param(params, "verb")
    resource = _param(params, "resource")
    namespace = _param(params, "namespace")
    if not (cluster_id and verb and resource):
        raise ValueError("cluster_id, verb, resource are required")

    api_client = get_core_v1_client(cluster_id).api_client
    rbac = k8s_client.RbacAuthorizationV1Api(api_client)

    subjects: List[Dict] = []
    # Namespace roles
    if namespace:
        roles = rbac.list_namespaced_role(namespace=namespace).items
        rbs = rbac.list_namespaced_role_binding(namespace=namespace).items
        role_map = {r.metadata.name: r for r in roles}
        for rb in rbs:
            role_ref = getattr(rb, "role_ref", None)
            if role_ref and role_ref.kind == "Role" and role_ref.name in role_map:
                rules = getattr(role_map[role_ref.name], "rules", []) or []
                for rule in rules:
                    if verb in (rule.verbs or []) and resource in (rule.resources or []):
                        for s in (rb.subjects or []):
                            subjects.append({"kind": s.kind, "name": s.name, "namespace": getattr(s, "namespace", namespace)})

    # Cluster roles
    croles = rbac.list_cluster_role().items
    crbs = rbac.list_cluster_role_binding().items
    crole_map = {r.metadata.name: r for r in croles}
    for rb in crbs:
        role_ref = getattr(rb, "role_ref", None)
        if role_ref and role_ref.kind == "ClusterRole" and role_ref.name in crole_map:
            rules = getattr(crole_map[role_ref.name], "rules", []) or []
            for rule in rules:
                if verb in (rule.verbs or []) and resource in (rule.resources or []):
                    for s in (rb.subjects or []):
                        subjects.append({"kind": s.kind, "name": s.name, "namespace": getattr(s, "namespace", None)})

    return {"verb": verb, "resource": resource, "subjects": subjects}


def security_findings(params: Dict) -> List[Dict]:
    """Static scan for common risks: privileged, hostPath, runAsRoot.

    Inputs:
      - cluster_id (required)
      - namespace (optional)
    """
    cluster_id = _param(params, "cluster_id", "clusterId")
    if not cluster_id:
        raise ValueError("Missing cluster_id/clusterId")
    namespace = _param(params, "namespace")

    core_v1 = get_core_v1_client(cluster_id)
    pods = (core_v1.list_namespaced_pod(namespace=namespace).items if namespace
            else core_v1.list_pod_for_all_namespaces().items)

    findings: List[Dict] = []
    for p in pods:
        ns = getattr(p.metadata, "namespace", None)
        name = getattr(p.metadata, "name", None)
        spec = getattr(p, "spec", None)
        if not spec:
            continue
        # hostPath volumes
        for v in (spec.volumes or []):
            hp = getattr(v, "host_path", None)
            if hp and getattr(hp, "path", ""):
                findings.append({"namespace": ns, "pod": name, "type": "hostPath", "path": hp.path})
        # containers securityContext
        for c in (spec.containers or []):
            sc = getattr(c, "security_context", None)
            if sc:
                if getattr(sc, "privileged", False):
                    findings.append({"namespace": ns, "pod": name, "container": c.name, "type": "privileged"})
                run_as_user = getattr(sc, "run_as_user", None)
                if run_as_user == 0:
                    findings.append({"namespace": ns, "pod": name, "container": c.name, "type": "runAsRoot"})
    return findings


def scale_node_pool(params: Dict) -> Dict:
    """Scale an OKE node pool to a desired size (guarded).

    Inputs:
      - node_pool_id (required)
      - size (required, int)
    """
    _ensure_writes_enabled()
    node_pool_id = _param(params, "node_pool_id", "nodePoolId")
    size = _param(params, "size")
    if not node_pool_id:
        raise ValueError("Missing node_pool_id/nodePoolId")
    if size is None:
        raise ValueError("Missing size")
    size = int(size)
    if size < 0 or size > 1000:
        raise ValueError("Unreasonable size; must be between 0 and 1000")

    ce_client = get_container_engine_client()
    details = oci.container_engine.models.UpdateNodePoolDetails(
        size=size
    )
    resp = ce_client.update_node_pool(node_pool_id=node_pool_id, update_node_pool_details=details)
    work_req = getattr(resp, "headers", {}).get("opc-work-request-id")
    return {"node_pool_id": node_pool_id, "requested_size": size, "work_request_id": work_req}


def list_work_requests(params: Dict) -> List[Dict]:
    """List recent OKE work requests for a compartment or resource."""
    compartment_id = _param(params, "compartment_id", "compartmentId")
    resource_id = _param(params, "resource_id", "resourceId")
    ce_client = get_container_engine_client()
    resp = ce_client.list_work_requests(compartment_id=compartment_id, resource_id=resource_id, limit=50)
    out: List[Dict] = []
    for wr in resp.data:
        out.append({
            "id": getattr(wr, "id", None),
            "operation_type": getattr(wr, "operation_type", None),
            "status": getattr(wr, "status", None),
            "time_accepted": str(getattr(wr, "time_accepted", "")),
            "time_started": str(getattr(wr, "time_started", "")),
            "time_finished": str(getattr(wr, "time_finished", "")),
        })
    return out


def restart_deployment(params: Dict) -> Dict:
    """Trigger a rolling restart by patching the pod template annotation (guarded)."""
    _ensure_writes_enabled()
    cluster_id = _param(params, "cluster_id", "clusterId")
    namespace = _param(params, "namespace")
    name = _param(params, "name")
    reason = _param(params, "reason")
    if not (cluster_id and namespace and name):
        raise ValueError("cluster_id, namespace, name are required")

    apps = k8s_client.AppsV1Api(get_core_v1_client(cluster_id).api_client)
    now = _dt.datetime.utcnow().isoformat() + "Z"
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubernetes.io/restartedAt": now,
                        **({"oke.mcp/reason": reason} if reason else {}),
                    }
                }
            }
        }
    }
    apps.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
    return {"namespace": namespace, "deployment": name, "restartedAt": now, "reason": reason}