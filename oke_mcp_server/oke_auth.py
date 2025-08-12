# oke_auth.py
"""
Helpers for connecting to an OKE cluster's Kubernetes API.

- Builds a short-lived kubeconfig via OCI Container Engine
- Loads it in-memory (no temp files)
- Returns initialized Kubernetes API clients
"""

from typing import Optional, Union
import os
import time
import threading
from typing import Dict, Tuple

import oci
import yaml
from kubernetes import client as k8s_client, config as k8s_config
from oci.container_engine.models import CreateClusterKubeconfigContentDetails

from oci_auth import get_config, get_signer


# Simple in-memory cache: {(cluster_id, endpoint, token_version): (cfg_dict, expires_at)}
_CFG_CACHE: Dict[Tuple[str, str, str], Tuple[dict, float]] = {}
_CACHE_LOCK = threading.RLock()

def _maybe_patch_security_token_exec(cfg: dict) -> None:
    """If OCI_CLI_AUTH=security_token, ensure the kubeconfig user exec args include it.
    This matches local kubectl behavior when users rely on STS.
    """
    if os.getenv("OCI_CLI_AUTH", "").lower() != "security_token":
        return
    try:
        users = cfg.get("users") or []
        if not isinstance(users, list):
            return
        for u in users:
            user = u.get("user") if isinstance(u, dict) else None
            if not isinstance(user, dict):
                continue
            exec_cfg = user.get("exec")
            if not isinstance(exec_cfg, dict):
                continue
            args = exec_cfg.get("args")
            if not isinstance(args, list):
                continue
            if "--auth" in args:
                # Update value if present but different
                try:
                    idx = args.index("--auth")
                    if idx + 1 < len(args):
                        args[idx + 1] = "security_token"
                    else:
                        args.extend(["--auth", "security_token"])
                except Exception:
                    pass
            else:
                args.extend(["--auth", "security_token"])
    except Exception:
        # Best-effort; do not fail kubeconfig load due to patch
        pass


def _resolve_endpoint(endpoint: Union[str, None]) -> str:
    """Normalize endpoint to the SDK constant used by CreateClusterKubeconfigContentDetails.

    Accepts either the SDK constants or human-friendly strings like
    "PUBLIC" / "PRIVATE" (case-insensitive). Defaults to PUBLIC when None.
    """
    # Environment override (e.g., OKE_ENDPOINT=PRIVATE)
    env_ep = os.getenv("OKE_ENDPOINT")
    if endpoint is None and env_ep:
        endpoint = env_ep

    default_public = CreateClusterKubeconfigContentDetails.ENDPOINT_PUBLIC_ENDPOINT
    if endpoint is None:
        return default_public
    if isinstance(endpoint, str):
        e = endpoint.strip().upper()
        if e in {"PUBLIC", "PUBLIC_ENDPOINT"}:
            return CreateClusterKubeconfigContentDetails.ENDPOINT_PUBLIC_ENDPOINT
        if e in {"PRIVATE", "PRIVATE_ENDPOINT"}:
            return CreateClusterKubeconfigContentDetails.ENDPOINT_PRIVATE_ENDPOINT
    # If caller passed an SDK constant already, return as-is
    return endpoint


def _load_kubeconfig_for_cluster(
    cluster_id: str,
    *,
    endpoint: str = CreateClusterKubeconfigContentDetails.ENDPOINT_PUBLIC_ENDPOINT,
    token_version: Optional[str] = "2.0.0",
    expiration: Optional[int] = 3600,
) -> None:
    """Fetch kubeconfig for the OKE cluster and load it in-memory.

    For OCI Python SDK 2.157.1, use `ContainerEngineClient.create_kubeconfig` and
    pass a `CreateClusterKubeconfigContentDetails` instance via the
    `create_cluster_kubeconfig_content_details` keyword argument.
    """
    # Respect simple in-memory cache when not expired
    cache_key = (cluster_id, str(endpoint), str(token_version))
    now = time.time()
    with _CACHE_LOCK:
        entry = _CFG_CACHE.get(cache_key)
        if entry and entry[1] > now:
            k8s_config.load_kube_config_from_dict(entry[0])
            return

    config = get_config()
    signer = get_signer(config)
    ce = oci.container_engine.ContainerEngineClient(config, signer=signer)

    # Normalize endpoint and validate expiration
    endpoint = _resolve_endpoint(endpoint)
    if expiration is not None:
        try:
            expiration = int(expiration)
        except (TypeError, ValueError):
            raise ValueError("expiration must be an integer number of seconds")
        # Clamp between 5 minutes and 24 hours
        expiration = max(300, min(expiration, 24 * 3600))

    details = CreateClusterKubeconfigContentDetails(
        endpoint=endpoint,
        token_version=token_version,
        expiration=expiration,
    )

    # Correct signature for oci==2.157.1
    resp = ce.create_kubeconfig(
        cluster_id,
        create_cluster_kubeconfig_content_details=details,
    )

    kubeconfig_str = _read_response_text(resp.data)

    # Load directly from dict to avoid writing to disk, but ensure we get a mapping.
    # Some environments return the kubeconfig as a quoted/escaped single-line string.
    cfg = None

    def _try_parse_yaml(text: str):
        try:
            val = yaml.safe_load(text)
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    # 0) Fast path: parse as-is
    cfg = _try_parse_yaml(kubeconfig_str)

    if cfg is None:
        s = kubeconfig_str.strip()

        # 1) If wrapped in quotes, strip once and try again
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s1 = s[1:-1]
            cfg = _try_parse_yaml(s1)
            if cfg is None:
                # 2) Unescape common sequences (e.g., \n) and try again
                try:
                    s1u = bytes(s1, 'utf-8').decode('unicode_escape')
                    cfg = _try_parse_yaml(s1u)
                except Exception:
                    pass

        # 3) If still not a dict, try JSON-unescape then YAML parse
        if cfg is None:
            try:
                import json as _json
                inner = _json.loads(kubeconfig_str)
                if isinstance(inner, str):
                    cfg = _try_parse_yaml(inner)
                    if cfg is None:
                        try:
                            inner_u = bytes(inner, 'utf-8').decode('unicode_escape')
                            cfg = _try_parse_yaml(inner_u)
                        except Exception:
                            pass
            except Exception:
                pass

        # 4) Last attempt: treat the original as unicode-escaped YAML
        if cfg is None:
            try:
                s2 = bytes(kubeconfig_str, 'utf-8').decode('unicode_escape')
                cfg = _try_parse_yaml(s2)
            except Exception:
                pass

    if cfg is None:
        raise ValueError("Invalid kubeconfig content: expected a YAML mapping after decoding")

    _maybe_patch_security_token_exec(cfg)

    # Some SDK versions/tenancies emit kubeconfig without `current-context`.
    # If there is exactly one context, set it as current to satisfy the k8s loader.
    if "current-context" not in cfg:
        contexts = cfg.get("contexts") or []
        if isinstance(contexts, list) and len(contexts) == 1 and isinstance(contexts[0], dict):
            name = contexts[0].get("name")
            if name:
                cfg["current-context"] = name

    # If still missing, try to synthesize a context from the first cluster/user pair (defensively)
    if "current-context" not in cfg:
        clusters = cfg.get("clusters")
        users = cfg.get("users")

        cluster_name = None
        user_name = None

        if isinstance(clusters, list) and clusters and isinstance(clusters[0], dict):
            cluster_name = clusters[0].get("name")
        if isinstance(users, list) and users and isinstance(users[0], dict):
            user_name = users[0].get("name")

        if cluster_name and user_name:
            ctx_name = f"ctx-{cluster_name}-{user_name}"
            contexts = cfg.get("contexts")
            if not isinstance(contexts, list):
                contexts = []
                cfg["contexts"] = contexts
            contexts.append({
                "name": ctx_name,
                "context": {"cluster": cluster_name, "user": user_name},
            })
            cfg["current-context"] = ctx_name
        else:
            # Last resort: if contexts exist and have a name, pick the first
            contexts = cfg.get("contexts")
            if isinstance(contexts, list) and contexts and isinstance(contexts[0], dict):
                name = contexts[0].get("name")
                if name:
                    cfg["current-context"] = name

    k8s_config.load_kube_config_from_dict(cfg)

    # Cache the parsed config for a short duration to avoid re-fetching on repeated calls
    ttl = max(300, min(int(expiration or 3600) // 6, 1200))  # between 5m and 20m
    with _CACHE_LOCK:
        _CFG_CACHE[cache_key] = (cfg, time.time() + ttl)


def get_core_v1_client(
    cluster_id: str,
    *,
    endpoint: str = CreateClusterKubeconfigContentDetails.ENDPOINT_PUBLIC_ENDPOINT,
    token_version: Optional[str] = "2.0.0",
    expiration: Optional[int] = 3600,
) -> k8s_client.CoreV1Api:
    """
    Return a configured CoreV1Api client for the specified OKE cluster.

    `endpoint` may be a constant from CreateClusterKubeconfigContentDetails
    or a string: "PUBLIC" / "PUBLIC_ENDPOINT" / "PRIVATE" / "PRIVATE_ENDPOINT".
    """
    # In-cluster fast path (for future/CI use): set OKE_IN_CLUSTER=1 to skip OCI kubeconfig
    if os.getenv("OKE_IN_CLUSTER") in ("1", "true", "True") or os.getenv("RUN_MODE") == "in_cluster":
        k8s_config.load_incluster_config()
        return k8s_client.CoreV1Api()

    endpoint = _resolve_endpoint(endpoint)
    _load_kubeconfig_for_cluster(
        cluster_id,
        endpoint=endpoint,
        token_version=token_version,
        expiration=expiration,
    )
    return k8s_client.CoreV1Api()


def get_apps_v1_client(
    cluster_id: str,
    *,
    endpoint: str = CreateClusterKubeconfigContentDetails.ENDPOINT_PUBLIC_ENDPOINT,
    token_version: Optional[str] = "2.0.0",
    expiration: Optional[int] = 3600,
) -> k8s_client.AppsV1Api:
    """
    Return a configured AppsV1Api client (Deployments, StatefulSets, etc.)
    for the specified OKE cluster.

    `endpoint` may be a constant from CreateClusterKubeconfigContentDetails
    or a string: "PUBLIC" / "PUBLIC_ENDPOINT" / "PRIVATE" / "PRIVATE_ENDPOINT".
    """
    # In-cluster fast path (for future/CI use): set OKE_IN_CLUSTER=1 to skip OCI kubeconfig
    if os.getenv("OKE_IN_CLUSTER") in ("1", "true", "True") or os.getenv("RUN_MODE") == "in_cluster":
        k8s_config.load_incluster_config()
        return k8s_client.AppsV1Api()

    endpoint = _resolve_endpoint(endpoint)
    _load_kubeconfig_for_cluster(
        cluster_id,
        endpoint=endpoint,
        token_version=token_version,
        expiration=expiration,
    )
    return k8s_client.AppsV1Api()


def _read_response_text(data_obj) -> str:
    """Return response payload as text from various SDK stream shapes.
    Handles bytes, str, file-like objects, requests.Response, urllib3 responses, etc.
    """
    # Direct primitives
    if isinstance(data_obj, (bytes, bytearray)):
        return data_obj.decode("utf-8", errors="replace")
    if isinstance(data_obj, str):
        return data_obj

    # requests.Response-like
    text = getattr(data_obj, "text", None)
    if isinstance(text, str) and text:
        return text

    # file-like (has read())
    read = getattr(data_obj, "read", None)
    if callable(read):
        try:
            b = read()
            if isinstance(b, (bytes, bytearray)):
                return b.decode("utf-8", errors="replace")
            if isinstance(b, str):
                return b
        except Exception:
            pass

    # objects with .data or .raw that is file-like
    inner = getattr(data_obj, "data", None)
    if inner is not None and inner is not data_obj:
        return _read_response_text(inner)
    raw = getattr(data_obj, "raw", None)
    if raw is not None and raw is not data_obj:
        return _read_response_text(raw)

    # Fallback: last-resort string coercion
    return str(data_obj)