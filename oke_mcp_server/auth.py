from __future__ import annotations
import os
from functools import lru_cache
import oci
from kubernetes import client as k8s_client, config as k8s_config
from .config import settings

# --- OCI clients -----------------------------------------------------------

def _load_oci_config():
    cfg_file = settings.oci_config_file or oci.config.DEFAULT_LOCATION
    profile = settings.oci_profile or oci.config.DEFAULT_PROFILE
    return oci.config.from_file(cfg_file, profile_name=profile)

@lru_cache(maxsize=8)
def get_container_engine_client(auth: str | None = None) -> oci.container_engine.ContainerEngineClient:
    """
    Returns ContainerEngineClient honoring OCI_CLI_AUTH=security_token when requested.
    """
    # If explicit auth requested, propagate to env as fallback behavior
    if auth:
        os.environ["OCI_CLI_AUTH"] = auth

    config = _load_oci_config()

    # OCI SDK will pick up security token automatically if config references it.
    # For instance principals, you could instead use InstancePrincipalsSecurityTokenSigner.
    return oci.container_engine.ContainerEngineClient(config)

# --- Kubernetes client -----------------------------------------------------

def get_core_v1_client(
    cluster_id: str,
    endpoint: str | None = None,
    auth: str | None = None
) -> k8s_client.CoreV1Api:
    """
    Build a CoreV1Api for a given OKE cluster. Uses OCI CE create_kubeconfig to
    fetch kubeconfig (lightweight) and loads it into Kubernetes Python client.

    endpoint: "PUBLIC" | "PRIVATE" | None
    auth: e.g. "security_token"
    """
    if auth:
        os.environ["OCI_CLI_AUTH"] = auth

    ce = get_container_engine_client(auth=auth)

    # create_kubeconfig returns the config text; set type to OIDC for modern clusters
    kwargs = {}
    if endpoint:
        kwargs["endpoint"] = endpoint  # PUBLIC/PRIVATE

    # returns oci.container_engine.models.Kubeconfig
    resp = ce.create_kubeconfig(
        cluster_id=cluster_id,
        kubeconfig_type="OIDC",
        **kwargs
    )
    kubeconfig_text = resp.data.content

    # Load from string
    k8s_config.load_kube_config_from_dict(_yaml_to_dict(kubeconfig_text))
    return k8s_client.CoreV1Api()

def _yaml_to_dict(text: str) -> dict:
    import yaml
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Invalid kubeconfig content")
    return data