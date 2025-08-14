from __future__ import annotations
import os
from functools import lru_cache
from typing import Optional, Tuple
import oci
from oci import auth as oci_auth
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

def _infer_region(config: dict) -> str:
    # Prefer explicit settings/env, else config file
    return (
        settings.oci_region
        or os.environ.get("OCI_REGION")
        or config.get("region")
        or os.environ.get("OCI_CLI_REGION")
        or ""
    )

def _load_oci_config() -> dict:
    """Load OCI config honoring env and settings; expand ~ in paths.
    Returns an empty dict if no file is present; callers decide how to auth.
    """
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
    try:
        if os.path.exists(cfg_file):
            log.debug(f"Loading OCI config from {cfg_file} with profile {profile}")
            return oci.config.from_file(cfg_file, profile_name=profile)
    except Exception as e:
        log.warning(f"Failed to load OCI config file {cfg_file}: {e}")
    # Fall back to minimal dict; region might be injected later
    return {}

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


def _try_instance_principals() -> Tuple[Optional[dict], Optional[object]]:
    try:
        signer = oci_auth.signers.InstancePrincipalsSecurityTokenSigner()
        region = os.environ.get("OCI_REGION") or getattr(signer, "region", None)
        cfg = {"region": region} if region else {}
        return cfg, signer
    except Exception:
        return None, None

def _try_resource_principals() -> Tuple[Optional[dict], Optional[object]]:
    if not os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        return None, None
    try:
        signer = oci_auth.signers.get_resource_principals_signer()
        region = os.environ.get("OCI_REGION") or getattr(signer, "region", None)
        cfg = {"region": region} if region else {}
        return cfg, signer
    except Exception as e:
        log.warning(f"Resource Principals signer not available: {e}")
        return None, None


# --- OCI clients -----------------------------------------------------------

@lru_cache(maxsize=8)
def get_container_engine_client(auth: str | None = None) -> oci.container_engine.ContainerEngineClient:
    """
    Return ContainerEngineClient using one of:
    - Resource Principals (if OCI_RESOURCE_PRINCIPAL_VERSION is set)
    - Instance Principals (if auth == "instance_principals")
    - Security Token (if auth == "security_token" or token/delegation present in config)
    - Config file user keys (default)
    """
    auth = _resolve_auth(auth)
    config = _load_oci_config()

    # Resource Principals first (common in OKE/Functions/Serverless)
    cfg_rp, signer_rp = _try_resource_principals()
    if signer_rp is not None:
        region = _infer_region(config) or _infer_region(cfg_rp or {})
        if not region:
            raise RuntimeError("Region is required for Resource Principals. Set OCI_REGION.")
        return oci.container_engine.ContainerEngineClient({"region": region}, signer=signer_rp)

    # Instance Principals when explicitly requested
    if auth and auth.lower() in {"instance_principals", "instance-principals", "ip"}:
        cfg_ip, signer_ip = _try_instance_principals()
        if signer_ip is None:
            raise RuntimeError("Failed to initialize Instance Principals signer")
        region = _infer_region(config) or _infer_region(cfg_ip or {})
        if not region:
            raise RuntimeError("Region is required for Instance Principals. Set OCI_REGION.")
        return oci.container_engine.ContainerEngineClient({"region": region}, signer=signer_ip)

    # Security token via CLI SSO or delegation tokens
    signer = None
    try:
        needs_token = (auth and auth.lower() == "security_token") or bool(
            config.get("security_token_file") or config.get("delegation_token_file")
        )
        if needs_token:
            log.debug("Using explicit SecurityTokenSigner from token & private key")
            signer = _build_security_token_signer_from_config(config)
    except Exception as e:
        log.error(f"Failed to initialize SecurityTokenSigner: {e}")
        raise RuntimeError(f"SecurityTokenSigner init failed: {e}")

    if signer is not None:
        region = _infer_region(config)
        if not region:
            raise RuntimeError("Region is required in config/env for security_token auth. Set OCI_REGION or add region to OCI config.")
        return oci.container_engine.ContainerEngineClient({"region": region}, signer=signer)

    # Default: user principal from config file
    if not config:
        raise RuntimeError("No OCI config found and no principal signer available. Provide ~/.oci/config or set OCI_RESOURCE_PRINCIPAL_VERSION/instance principals.")
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

    k8s_config.load_kube_config_from_dict(cfg_dict, persist_config=False)
    return k8s_client.CoreV1Api()


def _yaml_to_dict(text: str) -> dict:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError(f"PyYAML is required to parse kubeconfig: {e}")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Invalid kubeconfig content")
    return data


def invalidate_auth_cache() -> None:
    """Clear cached OCI clients (use after token rotation)."""
    try:
        get_container_engine_client.cache_clear()
    except Exception:
        pass