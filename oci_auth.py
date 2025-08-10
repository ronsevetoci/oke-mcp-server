import oci
import os
from oci.auth.signers import SecurityTokenSigner
from oci.signer import load_private_key

def get_config():
    config = oci.config.from_file()
    
    if 'security_token_file' in config:
        token_path = config['security_token_file']
        if os.path.exists(token_path):
            with open(token_path, 'r') as f:
                config['security_token'] = f.read().strip()
    return config

def get_signer(config):
    if 'security_token_file' in config and os.path.exists(config['security_token_file']):
        with open(config['security_token_file'], 'r') as tf:
            token = tf.read().strip()

        with open(config['key_file'], 'r') as kf:
            private_key = kf.read()

        private_key_obj = load_private_key(private_key, pass_phrase=None)
        return SecurityTokenSigner(token, private_key_obj)
    else:
        return oci.signer.Signer(
            tenancy=config['tenancy'],
            user=config['user'],
            fingerprint=config['fingerprint'],
            private_key_file_location=config['key_file'],
            pass_phrase=config.get('pass_phrase')
        )

def get_container_engine_client():
    config = get_config()
    signer = get_signer(config)
    return oci.container_engine.ContainerEngineClient(config, signer=signer)

def get_identity_client():
    config = get_config()
    signer = get_signer(config)
    return oci.identity.IdentityClient(config, signer=signer)

##{"jsonrpc":"2.0","id":1,"method":"oke.list_clusters","params":{"compartmentId":"ocid1.compartment.oc1..aaaaaaaayevnkjfyjb6nglndfrvgoy7hciclgf4kq7ioulokey7xfpixjhxa"}}