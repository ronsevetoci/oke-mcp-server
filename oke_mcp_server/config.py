from __future__ import annotations
import os
import json
import pathlib
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict, field

# Optional YAML support (file-based config)
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


# -------------------------------
# Configuration loading & merging
# -------------------------------

@dataclass
class Settings:
    # Logging / behavior
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    allow_write: bool = os.getenv("ALLOW_WRITE", "false").lower() == "true"
    allow_sensitive: bool = os.getenv("ALLOW_SENSITIVE", "false").lower() == "true"

    # OKE context
    compartment_id: Optional[str] = os.getenv("OKE_COMPARTMENT_ID")
    cluster_id: Optional[str] = os.getenv("OKE_CLUSTER_ID")

    # OCI / kube auth
    oci_profile: Optional[str] = os.getenv("OCI_PROFILE") or os.getenv("OCI_CLI_PROFILE")
    oci_config_file: Optional[str] = os.getenv("OCI_CONFIG_FILE")
    oci_cli_auth: Optional[str] = os.getenv("OCI_CLI_AUTH")  # e.g. "security_token"
    kube_endpoint: Optional[str] = os.getenv("OKE_KUBE_ENDPOINT")  # PUBLIC/PRIVATE (if set)

    # Performance knobs
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "90"))
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "20"))
    max_list_items: int = int(os.getenv("MAX_LIST_ITEMS", "200"))

    # Internal: where we loaded file config from
    _config_file: Optional[str] = field(default=None, repr=False, compare=False)

    # --- Backward-compatibility shim ---
    # Some modules may try to read `settings.oci_region`. We intentionally
    # do not require or store region here because the OCI SDK will resolve it
    # from ~/.oci/config (or instance principals) automatically. Expose a
    # read-only property returning None so older code doesn't raise
    # AttributeError.
    @property
    def oci_region(self) -> Optional[str]:
        return None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def redacted(self) -> Dict[str, Any]:
        d = self.to_dict()
        # Redact potentially sensitive values
        for k in ("oci_profile", "oci_config_file", "oci_cli_auth"):
            v = d.get(k)
            if v:
                d[k] = _redact(v)
        return d


def _redact(v: str) -> str:
    if not v:
        return v
    return v if len(v) <= 8 else f"{v[:4]}…{v[-4:]}"


def _read_file_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load YAML/JSON config for the server. Search order:
      1) explicit_path (if provided)
      2) ./config.yaml / ./config.json (next to the server binary / working dir)
      3) ~/.oke-mcp-server/config.yaml or config.json
    Returns {} if nothing found or parsing fails.
    """
    candidates = []
    if explicit_path:
        candidates.append(pathlib.Path(explicit_path))

    cwd = pathlib.Path.cwd()
    candidates.extend([
        cwd / "config.yaml",
        cwd / "config.json",
        pathlib.Path.home() / ".oke-mcp-server" / "config.yaml",
        pathlib.Path.home() / ".oke-mcp-server" / "config.json",
    ])

    for p in candidates:
        try:
            if not p.is_file():
                continue
            text = p.read_text()
            if p.suffix.lower() in (".yml", ".yaml") and yaml:
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
            if isinstance(data, dict):
                data["_config_file"] = str(p)
                return data
        except Exception:
            # ignore malformed files and keep searching
            continue
    return {}


def _overlay(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        if v is not None:
            out[k] = v
    return out


def _env_config() -> Dict[str, Any]:
    # Mirror Settings fields from environment; None if not present
    def _get(k: str) -> Optional[str]:
        return os.getenv(k) if os.getenv(k) is not None else None

    return {
        "log_level": (_get("LOG_LEVEL") or "INFO").upper() if _get("LOG_LEVEL") else None,
        "allow_write": (_get("ALLOW_WRITE") or "").lower() == "true" if _get("ALLOW_WRITE") else None,
        "allow_sensitive": (_get("ALLOW_SENSITIVE") or "").lower() == "true" if _get("ALLOW_SENSITIVE") else None,
        "compartment_id": _get("OKE_COMPARTMENT_ID"),
        "cluster_id": _get("OKE_CLUSTER_ID"),
        "oci_profile": _get("OCI_PROFILE") or _get("OCI_CLI_PROFILE"),
        "oci_config_file": _get("OCI_CONFIG_FILE"),
        "oci_cli_auth": _get("OCI_CLI_AUTH"),
        "kube_endpoint": _get("OKE_KUBE_ENDPOINT"),
        "rate_limit_per_min": int(_get("RATE_LIMIT_PER_MIN")) if _get("RATE_LIMIT_PER_MIN") else None,
        "cache_ttl_seconds": int(_get("CACHE_TTL_SECONDS")) if _get("CACHE_TTL_SECONDS") else None,
        "max_list_items": int(_get("MAX_LIST_ITEMS")) if _get("MAX_LIST_ITEMS") else None,
    }


def resolve_settings(explicit_config_path: Optional[str] = None,
                     cli_overrides: Optional[Dict[str, Any]] = None) -> Settings:
    """
    Build a Settings object by merging:
      defaults (Settings()) <- file config <- env vars <- CLI overrides
    """
    defaults = Settings()
    file_cfg = _read_file_config(explicit_config_path)
    env_cfg = _env_config()
    merged = _overlay(defaults.to_dict(), file_cfg)
    merged = _overlay(merged, env_cfg)
    merged = _overlay(merged, cli_overrides or {})
    s = Settings(**{k: v for k, v in merged.items() if k in Settings.__dataclass_fields__})
    # preserve where config was read
    s._config_file = file_cfg.get("_config_file")
    return s


# A module-level mutable settings instance.
# Other modules import `from oke_mcp_server.config import settings`.
settings = resolve_settings()


# -------------------------------
# Convenience helpers
# -------------------------------

def get_effective_defaults() -> Dict[str, Optional[str]]:
    """What tools actually use if arguments are omitted."""
    return {
        "compartment_id": settings.compartment_id,
        "cluster_id": settings.cluster_id,
    }


def set_defaults(compartment_id: Optional[str] = None, cluster_id: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Update in-memory defaults (and export to env so subprocesses inherit)."""
    if compartment_id:
        settings.compartment_id = compartment_id
        os.environ["OKE_COMPARTMENT_ID"] = compartment_id
    if cluster_id:
        settings.cluster_id = cluster_id
        os.environ["OKE_CLUSTER_ID"] = cluster_id
    return get_effective_defaults()


def refresh_settings(explicit_config_path: Optional[str] = None,
                     cli_overrides: Optional[Dict[str, Any]] = None) -> Settings:
    """Recompute settings from disk/env/overrides at runtime."""
    global settings
    settings = resolve_settings(explicit_config_path=explicit_config_path, cli_overrides=cli_overrides)
    return settings


def diagnostics() -> Dict[str, Any]:
    """Small status payload for /health-style tools."""
    return {
        "log_level": settings.log_level,
        "allow_write": settings.allow_write,
        "allow_sensitive": settings.allow_sensitive,
        "defaults": get_effective_defaults(),
        "oci_profile": _redact(settings.oci_profile or ""),
        "oci_config_file": _redact(settings.oci_config_file or ""),
        "oci_cli_auth": _redact(settings.oci_cli_auth or ""),
        "kube_endpoint": settings.kube_endpoint,
        "rate_limit_per_min": settings.rate_limit_per_min,
        "cache_ttl_seconds": settings.cache_ttl_seconds,
        "max_list_items": settings.max_list_items,
        "config_file": settings._config_file,
    }