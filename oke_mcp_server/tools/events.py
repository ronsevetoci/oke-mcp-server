from __future__ import annotations
from typing import Optional, Dict, List

from ..auth import get_core_v1_client


def _trim_event(e) -> Dict:
    md = getattr(e, "metadata", None)
    involved = getattr(e, "involved_object", None)
    # timestamps (not always present depending on k8s version)
    first_ts = getattr(e, "first_timestamp", None) or getattr(e, "event_time", None)
    last_ts = getattr(e, "last_timestamp", None) or getattr(e, "event_time", None)
    # count
    count = getattr(e, "count", None)

    return {
        "name": getattr(md, "name", ""),
        "namespace": getattr(md, "namespace", ""),
        "type": getattr(e, "type", "") or None,
        "reason": getattr(e, "reason", "") or None,
        "message": (getattr(e, "message", "") or "")[:500],
        "firstTimestamp": str(first_ts) if first_ts else None,
        "lastTimestamp": str(last_ts) if last_ts else None,
        "count": count,
        "involved": {
            "kind": getattr(involved, "kind", None),
            "name": getattr(involved, "name", None),
            "namespace": getattr(involved, "namespace", None),
        },
        # lightweight hints to help LLMs
        "_hint": {
            "obj_id": f"{(getattr(involved, 'kind', '') or '').lower()}:{(getattr(involved, 'namespace', '') + '/' if getattr(involved, 'namespace', None) else '')}{getattr(involved, 'name', '')}"
        }
    }


def oke_list_events(
    cluster_id: str,
    namespace: Optional[str] = None,
    field_selector: Optional[str] = None,
    type_filter: Optional[str] = None,
    limit: Optional[int] = 100,
    continue_token: Optional[str] = None,
    endpoint: Optional[str] = None,
    auth: Optional[str] = None,
) -> Dict:
    """
    List Kubernetes Events with safe trimming and pagination.

    Args:
      cluster_id: OKE cluster OCID (required)
      namespace: optional namespace; if omitted, lists cluster-wide
      field_selector: raw Kubernetes fieldSelector string (e.g. "involvedObject.kind=Pod,type=Warning")
      type_filter: convenience filter for Event.type (e.g. "Warning" or "Normal"); combined with field_selector
      limit: page size (default 100, hard-capped at 200)
      continue_token: pass-through pagination token
      endpoint: OKE endpoint preference ("PUBLIC"/"PRIVATE")
      auth: authentication mode override (e.g. "security_token")
    """
    api = get_core_v1_client(cluster_id, endpoint=endpoint, auth=auth)

    # Combine selectors
    selectors: List[str] = []
    if field_selector:
        selectors.append(field_selector)
    if type_filter:
        selectors.append(f"type={type_filter}")
    fs = ",".join(selectors) if selectors else None

    # Respect a hard safety cap for LLM-friendliness
    page_limit = max(1, min(int(limit or 100), 200))

    if namespace:
        resp = api.list_namespaced_event(
            namespace=namespace,
            field_selector=fs,
            limit=page_limit,
            _continue=continue_token,
        )
    else:
        resp = api.list_event_for_all_namespaces(
            field_selector=fs,
            limit=page_limit,
            _continue=continue_token,
        )

    items = [_trim_event(e) for e in getattr(resp, "items", [])]
    meta = getattr(resp, "metadata", None)
    cont = getattr(meta, "_continue", None) if meta else None  # python client uses `_continue`

    return {"items": items, "continue": cont}