from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class Settings:
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    allow_write: bool = os.getenv("ALLOW_WRITE", "false").lower() == "true"
    allow_sensitive: bool = os.getenv("ALLOW_SENSITIVE", "false").lower() == "true"

    # Effective defaults for OCI/OKE context
    compartment_id: str | None = os.getenv("OKE_COMPARTMENT_ID")
    cluster_id: str | None = os.getenv("OKE_CLUSTER_ID")

    # OCI / Kube auth
    oci_profile: str | None = os.getenv("OCI_PROFILE") or os.getenv("OCI_CLI_PROFILE")
    oci_config_file: str | None = os.getenv("OCI_CONFIG_FILE")
    oci_cli_auth: str | None = os.getenv("OCI_CLI_AUTH")  # e.g. "security_token"

settings = Settings()

def get_effective_defaults() -> dict:
    return {
        "compartment_id": settings.compartment_id,
        "cluster_id": settings.cluster_id,
    }