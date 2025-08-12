from __future__ import annotations
from typing import Optional, Dict
from fastmcp import Context
from kubernetes import client as k8s_client
from ..auth import get_core_v1_client

def oke_list_node_metrics(ctx: Context, cluster_id: str, endpoint: Optional[str] = None, auth: Optional[str] = None) -> Dict:
    try:
        api_client = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth).api_client
        co = k8s_client.CustomObjectsApi(api_client)
        data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
        return {"available": True, "items": data.get("items", [])}
    except Exception as e:
        return {"available": False, "reason": str(e)}

def oke_list_pod_metrics(ctx: Context, cluster_id: str, namespace: Optional[str] = None, endpoint: Optional[str] = None, auth: Optional[str] = None) -> Dict:
    try:
        api_client = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth).api_client
        co = k8s_client.CustomObjectsApi(api_client)
        if namespace:
            data = co.list_namespaced_custom_object("metrics.k8s.io", "v1beta1", namespace, "pods")
        else:
            data = co.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods")
        return {"available": True, "items": data.get("items", [])}
    except Exception as e:
        return {"available": False, "reason": str(e)}