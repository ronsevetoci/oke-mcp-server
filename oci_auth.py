import oci
import os
from oci.auth.signers import SecurityTokenSigner
from oci.signer import load_private_key

# Module-level cache for config and signer
_cached_config = None
_cached_signer = None


def get_config():
    """
    Loads the OCI config, optionally overriding the profile via the OCI_CLI_PROFILE environment variable.
    Reads the security token if present in the config.
    Caches the config to avoid repeated disk I/O.
    Handles errors if the config file is missing or invalid.
    Returns:
        dict: The OCI configuration dictionary.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    # Determine profile
    profile = os.environ.get('OCI_CLI_PROFILE')
    try:
        if profile:
            config = oci.config.from_file(profile_name=profile)
        else:
            config = oci.config.from_file()
    except Exception as e:
        print(f"ERROR: Failed to load OCI config file: {e}")
        return {}

    # Try to read security token if specified
    if 'security_token_file' in config:
        token_path = config['security_token_file']
        if os.path.exists(token_path):
            try:
                with open(token_path, 'r') as f:
                    config['security_token'] = f.read().strip()
            except Exception as e:
                print(f"ERROR: Failed to read security token file '{token_path}': {e}")
        else:
            print(f"WARNING: security_token_file '{token_path}' not found.")
    _cached_config = config
    return config

def get_signer(config):
    """
    Returns a signer for OCI requests based on the provided config.
    Supports security token authentication and API key authentication.
    Caches the signer to avoid repeated disk I/O.
    Handles missing config keys gracefully and logs which authentication method is used.
    Args:
        config (dict): The OCI config dictionary.
    Returns:
        Signer: An OCI signer object, or None if config is invalid.
    """
    global _cached_signer
    if _cached_signer is not None:
        return _cached_signer

    # Security token authentication
    if 'security_token_file' in config and os.path.exists(config['security_token_file']):
        try:
            with open(config['security_token_file'], 'r') as tf:
                token = tf.read().strip()
            with open(config['key_file'], 'r') as kf:
                private_key = kf.read()
            private_key_obj = load_private_key(private_key, pass_phrase=None)
            print("DEBUG: Using security_token authentication method.")
            signer = SecurityTokenSigner(token, private_key_obj)
            _cached_signer = signer
            return signer
        except Exception as e:
            print(f"ERROR: Failed to initialize SecurityTokenSigner: {e}")
            return None
    # API key authentication
    required_keys = ['tenancy', 'user', 'fingerprint', 'key_file']
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        print(f"ERROR: Missing required config keys for API key authentication: {', '.join(missing_keys)}")
        return None
    try:
        print("DEBUG: Using API key authentication method.")
        signer = oci.signer.Signer(
            tenancy=config['tenancy'],
            user=config['user'],
            fingerprint=config['fingerprint'],
            private_key_file_location=config['key_file'],
            pass_phrase=config.get('pass_phrase')
        )
        _cached_signer = signer
        return signer
    except Exception as e:
        print(f"ERROR: Failed to initialize API key signer: {e}")
        return None

def get_container_engine_client():
    """
    Returns an OCI ContainerEngineClient using the cached config and signer.
    Returns:
        ContainerEngineClient: The OCI ContainerEngineClient instance.
    """
    config = get_config()
    signer = get_signer(config)
    return oci.container_engine.ContainerEngineClient(config, signer=signer)

def get_identity_client():
    """
    Returns an OCI IdentityClient using the cached config and signer.
    Returns:
        IdentityClient: The OCI IdentityClient instance.
    """
    config = get_config()
    signer = get_signer(config)
    return oci.identity.IdentityClient(config, signer=signer)
