from __future__ import annotations
from typing import Optional, Dict
 
from ..auth import get_core_v1_client

def oke_list_events(cluster_id: str, namespace: Optional[str] = None, field_selector: Optional[str] = None, endpoint: Optional[str] = None, auth: Optional[str] = None) -> Dict:
    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)
    if namespace:
        evs = api.list_namespaced_event(namespace=namespace, field_selector=field_selector).items
    else:
        evs = api.list_event_for_all_namespaces(field_selector=field_selector).items
    # Trim
    out = []
    for e in evs[:200]:  # hard cap for LLM friendliness
        md = getattr(e, "metadata", None)
        involved = getattr(e, "involved_object", None)
        out.append({
            "name": getattr(md, "name", ""),
            "namespace": getattr(md, "namespace", ""),
            "reason": getattr(e, "reason", ""),
            "type": getattr(e, "type", ""),
            "message": getattr(e, "message", "")[:500],
            "involved": {
                "kind": getattr(involved, "kind", None),
                "name": getattr(involved, "name", None),
                "namespace": getattr(involved, "namespace", None),
            }
        })
    return {"items": out}