from __future__ import annotations
import os
from functools import lru_cache
import oci
from kubernetes import client as k8s_client, config as k8s_config
from .config import settings

import logging
log = logging.getLogger(__name__)

# --- Helpers ---------------------------------------------------------------

def _resolve_auth(auth: str | None) -> str | None:
    """Resolve auth mode from explicit arg, settings, or environment.
    Sets OCI_CLI_AUTH env var if resolved.
    """
    if auth is None:
        auth = settings.oci_cli_auth or os.environ.get("OCI_CLI_AUTH")
    if auth:
        os.environ["OCI_CLI_AUTH"] = auth
    return auth


def _load_oci_config() -> dict:
    """Load OCI config honoring env and settings; expand ~ in paths."""
    cfg_file = (
        settings.oci_config_file
        or os.environ.get("OCI_CONFIG_FILE")
        or oci.config.DEFAULT_LOCATION
    )
    cfg_file = os.path.expanduser(cfg_file)

    profile = (
        settings.oci_profile
        or os.environ.get("OCI_PROFILE")
        or os.environ.get("OCI_CLI_PROFILE")
        or oci.config.DEFAULT_PROFILE
    )
    log.debug(f"Loading OCI config from {cfg_file} with profile {profile}")
    return oci.config.from_file(cfg_file, profile_name=profile)

# --- SecurityTokenSigner helper -------------------------------------------
from oci.signer import load_private_key_from_file as _load_privkey

def _build_security_token_signer_from_config(config: dict):
    token_file = config.get("security_token_file") or os.environ.get("OCI_SECURITY_TOKEN_FILE")
    key_file = config.get("key_file") or os.environ.get("OCI_KEY_FILE")
    pass_phrase = config.get("pass_phrase") or os.environ.get("OCI_KEY_PASSPHRASE")

    if not token_file:
        raise RuntimeError("security_token_file not set in config or OCI_SECURITY_TOKEN_FILE env var")
    if not key_file:
        raise RuntimeError("key_file not set in config or OCI_KEY_FILE env var")

    token_path = os.path.expanduser(token_file)
    key_path = os.path.expanduser(key_file)

    if not os.path.exists(token_path):
        raise RuntimeError(f"security token file not found: {token_path}")
    if not os.path.exists(key_path):
        raise RuntimeError(f"private key file not found: {key_path}")

    with open(token_path, "r", encoding="utf-8") as f:
        token = f.read().strip()

    private_key = _load_privkey(key_path, pass_phrase=pass_phrase)

    from oci.auth.signers.security_token_signer import SecurityTokenSigner
    return SecurityTokenSigner(token, private_key)


# --- OCI clients -----------------------------------------------------------

@lru_cache(maxsize=8)
def get_container_engine_client(auth: str | None = None) -> oci.container_engine.ContainerEngineClient:
    """
    Return ContainerEngineClient. If `security_token` auth is active (explicitly
    or implied by config), build a SecurityTokenSigner so the SDK doesn't
    require `user` in config.
    """
    auth = _resolve_auth(auth)
    config = _load_oci_config()

    signer = None
    try:
        needs_token = (auth and auth.lower() == "security_token") or \
                      bool(config.get("security_token_file") or config.get("delegation_token_file"))
        if needs_token:
            log.debug("Using explicit SecurityTokenSigner from token & private key")
            signer = _build_security_token_signer_from_config(config)
    except Exception as e:
        log.error(f"Failed to initialize SecurityTokenSigner: {e}")
        raise RuntimeError(f"SecurityTokenSigner init failed: {e}")

    if signer is not None:
        return oci.container_engine.ContainerEngineClient(config, signer=signer)

    log.debug("Using standard config authentication (no signer)")
    return oci.container_engine.ContainerEngineClient(config)


# --- Kubernetes client -----------------------------------------------------

def get_core_v1_client(
    cluster_id: str,
    endpoint: str | None = None,
    auth: str | None = None,
) -> k8s_client.CoreV1Api:
    """
    Build a CoreV1Api for a given OKE cluster. Uses OCI CE create_kubeconfig to
    fetch kubeconfig (lightweight) and loads it into Kubernetes Python client.

    endpoint: "PUBLIC" | "PRIVATE" | None
    auth: e.g. "security_token"
    """
    auth = _resolve_auth(auth)
    ce = get_container_engine_client(auth=auth)

    # Build kwargs for create_kubeconfig (OCI SDK expects 'kube_endpoint', not 'endpoint')
    kwargs: dict = {}
    if endpoint:
        # Accept "PUBLIC"/"PRIVATE" (or full enum values) and pass as kube_endpoint
        kwargs["kube_endpoint"] = endpoint

    # Optional short-lived token expiration in seconds (defaults to SDK default)
    exp_env = os.environ.get("OKE_KUBECONFIG_EXP_SECONDS")
    if exp_env:
        try:
            kwargs["expiration"] = int(exp_env)
        except ValueError:
            log.warning("Ignoring non-integer OKE_KUBECONFIG_EXP_SECONDS=%s", exp_env)

    # Optional token version (e.g., "2.0.0") if callers want to pin
    token_ver = os.environ.get("OKE_KUBECONFIG_TOKEN_VERSION")
    if token_ver:
        kwargs["token_version"] = token_ver

    # Call CE to get kubeconfig content (returns oci.container_engine.models.Kubeconfig)
    resp = ce.create_kubeconfig(cluster_id=cluster_id, **kwargs)
    kubeconfig_text = resp.data.content

    # Load from string and ensure a current-context is present
    cfg_dict = _yaml_to_dict(kubeconfig_text)
    try:
        if not cfg_dict.get("current-context"):
            contexts = cfg_dict.get("contexts") or []
            if contexts:
                name = contexts[0].get("name") if isinstance(contexts[0], dict) else None
                if name:
                    cfg_dict["current-context"] = name
    except Exception:
        # If kubeconfig already valid, proceed
        pass

    k8s_config.load_kube_config_from_dict(cfg_dict)
    return k8s_client.CoreV1Api()


def _yaml_to_dict(text: str) -> dict:
    import yaml

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Invalid kubeconfig content")
    return data