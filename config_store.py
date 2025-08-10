
from __future__ import annotations
from typing import Optional, Dict
import os
import threading

"""
Thread-safe defaults store for the MCP server.

- Reads initial values from environment variables
  * OKE_COMPARTMENT_ID or COMPARTMENT_OCID
  * OKE_CLUSTER_ID or CLUSTER_OCID
- set_defaults() accepts snake_case and camelCase aliases
- get_effective_defaults() merges stored values with env fallbacks
- reset_defaults() restores env-derived defaults
"""

# Recognized environment variable names (first hit wins)
_COMPARTMENT_ENV = ("OKE_COMPARTMENT_ID", "COMPARTMENT_OCID")
_CLUSTER_ENV = ("OKE_CLUSTER_ID", "CLUSTER_OCID")
_ENDPOINT_ENV = ("OKE_ENDPOINT",)
_REGION_ENV = ("OCI_REGION",)

_lock = threading.RLock()


def _first_env(candidates: tuple[str, ...]) -> Optional[str]:
    for key in candidates:
        val = os.getenv(key)
        if val:
            val = val.strip()
            if val:
                return val
    return None


def _initial_defaults() -> Dict[str, Optional[str]]:
    return {
        "compartment_id": _first_env(_COMPARTMENT_ENV),
        "cluster_id": _first_env(_CLUSTER_ENV),
        # Optional/forward-looking fields
        "endpoint": _first_env(_ENDPOINT_ENV),
        "region": _first_env(_REGION_ENV),
    }


# In-memory defaults (stdio / single-client is fine). Mutations guarded by _lock.
_defaults: Dict[str, Optional[str]] = _initial_defaults()


def _norm(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    return v or None


def set_defaults(
    compartment_id: Optional[str] = None,
    cluster_id: Optional[str] = None,
    *,
    endpoint: Optional[str] = None,
    region: Optional[str] = None,
    **aliases: str,
) -> Dict[str, Optional[str]]:
    """Override stored defaults.

    Accepts snake_case and camelCase aliases via **aliases.
    Returns a shallow copy of the new defaults.
    """
    comp_alias = aliases.get("compartmentId")
    clus_alias = aliases.get("clusterId")
    endpoint_alias = aliases.get("endPoint") or aliases.get("endpoint")
    region_alias = aliases.get("Region") or aliases.get("ociRegion")

    with _lock:
        if compartment_id or comp_alias:
            _defaults["compartment_id"] = _norm(compartment_id or comp_alias)
        if cluster_id or clus_alias:
            _defaults["cluster_id"] = _norm(cluster_id or clus_alias)
        if endpoint or endpoint_alias:
            _defaults["endpoint"] = _norm(endpoint or endpoint_alias)
        if region or region_alias:
            _defaults["region"] = _norm(region or region_alias)
        return _defaults.copy()


def update_from_dict(values: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    """Update defaults from a dictionary (snake_case preferred; camelCase accepted)."""
    return set_defaults(
        compartment_id=values.get("compartment_id") or values.get("compartmentId"),
        cluster_id=values.get("cluster_id") or values.get("clusterId"),
        endpoint=values.get("endpoint") or values.get("endPoint"),
        region=values.get("region") or values.get("Region") or values.get("ociRegion"),
    )


def get_defaults() -> Dict[str, Optional[str]]:
    """Return a copy of the stored defaults (no env merging)."""
    with _lock:
        return _defaults.copy()


# --- effective defaults (env fallbacks) ---

def get_effective_defaults() -> Dict[str, Optional[str]]:
    """Return defaults merged with environment fallbacks.

    If a value is not set via set_defaults(), fall back to environment variables.
    Supports both OKE_* and generic names for compatibility.
    """
    with _lock:
        current = _defaults.copy()

    if not current.get("compartment_id"):
        current["compartment_id"] = _first_env(_COMPARTMENT_ENV)
    if not current.get("cluster_id"):
        current["cluster_id"] = _first_env(_CLUSTER_ENV)
    if not current.get("endpoint"):
        current["endpoint"] = _first_env(_ENDPOINT_ENV)
    if not current.get("region"):
        current["region"] = _first_env(_REGION_ENV)

    return current


def reset_defaults() -> Dict[str, Optional[str]]:
    """Reset to environment-derived values (clears any runtime overrides)."""
    with _lock:
        _defaults.clear()
        _defaults.update(_initial_defaults())
        return _defaults.copy()