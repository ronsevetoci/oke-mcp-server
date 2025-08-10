from typing import Optional, Dict
import os

# In-memory defaults (good for stdio, single-client servers)
_defaults: Dict[str, Optional[str]] = {
    "compartment_id": os.getenv("COMPARTMENT_OCID"),
    "cluster_id": os.getenv("CLUSTER_OCID"),
}

def set_defaults(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict[str, Optional[str]]:
    if compartment_id:
        _defaults["compartment_id"] = compartment_id
    if cluster_id:
        _defaults["cluster_id"] = cluster_id
    return _defaults.copy()

def get_defaults() -> Dict[str, Optional[str]]:
    return _defaults.copy()