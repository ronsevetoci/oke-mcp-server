# OKE MCP Server

## Overview

The **Oracle Container Engine for Kubernetes (OKE) Model Context Protocol (MCP) Server** enables Large Language Models (LLMs) and MCP-aware clients to inspect, troubleshoot, and interact with OKE clusters programmatically. Designed for OCI customers, DevOps teams, and developers, this tool streamlines Kubernetes diagnostics and management through MCP.

---

## Quickstart (with uvx)

The easiest way to run the MCP server is using [uv](https://github.com/astral-sh/uv) and its `uvx` launcher, which requires no local virtual environment or manual dependency installation.

```bash
# Run directly from source (useful during development)
uvx --from . oke-mcp-server --transport stdio

# Or run the published package (after publishing to PyPI)
uvx oke-mcp-server --transport stdio
```

### Initializing the JSON-RPC Session

After starting the server, initialize it by sending the following JSON-RPC commands:

```json
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.0.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
```

---

## Environment Setup

Before running the MCP server, ensure you have:

- **Python 3.10+** (3.11 recommended). Verify with:

  ```bash
  python3 --version
  ```

- **OCI Credentials** configured for authentication:

  - **Security Token Authentication** (recommended for local development):  
    Set `OCI_CLI_AUTH=security_token` and authenticate via OCI CLI or Console to refresh tokens.

  - **API Key Authentication**:  
    Configure your API keys in `~/.oci/config` under the `DEFAULT` or a named profile.

- **MCP CLI (`mcp`)** installed:

  ```bash
  pipx install mcp  # or: pip install mcp
  ```

> **Note:** If using security token authentication locally, your existing `kubectl` setup likely works. The server patches kubeconfig exec arguments with `--auth security_token` for seamless integration.

---

## New Tool Highlights

The MCP server now supports additional CLI flags and tools for enhanced usability:

- `--set-defaults-compartment <compartment_ocid>`  
  Sets the default compartment OCID, avoiding repeated specification.

- `--set-defaults-cluster <cluster_ocid>`  
  Sets the default cluster OCID.

- `--print-tools`  
  Prints a list of available MCP tools and their descriptions.

### New MCP Tools

- **meta_env**  
  Provides metadata about the server environment and configuration for diagnostics and introspection.

- **auth_refresh**  
  Refreshes authentication tokens on-demand without restarting the server, especially useful with security token authentication.

---

## Project Structure

- `main.py` — MCP server entry point  
- `oke_auth.py` — OKE authentication handler  
- `oci_auth.py` — OCI authentication handler  
- `handlers/oke.py` — Core OKE logic and API interactions  
- `config_store.py` — Configuration management  
- `auth_refresh.py` — Tool for refreshing authentication tokens without restart  
- `meta_env.py` — Tool providing environment metadata and diagnostics  
- `requirements.txt` — Runtime dependencies  
- `Makefile` — Build and run commands  

---

## Testing Your Release

After building and installing your package, run the server and test with:

```bash
uvx oke-mcp-server --transport stdio
```

Example JSON-RPC request to list pods in the default namespace:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "oke_list_pods",
    "arguments": {
      "namespace": "default"
    }
  }
}
```

---

## Releasing a New Version

1. Build and test locally:

   ```bash
   python -m pip install --upgrade build twine
   python -m build
   pip install dist/oke_mcp_server-*.whl
   uvx oke-mcp-server --transport stdio
   ```

2. Publish to PyPI (optional):

   ```bash
   export TWINE_USERNAME="__token__"
   export TWINE_PASSWORD="pypi-XXXXXXXXXXXXXXXXX"
   twine upload dist/*
   ```

3. Tag and push release:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Use GitHub Actions to automate builds and publishing on tag.

---

## Common Pitfalls

- **401 Unauthorized when fetching pod logs:**  
  Ensure worker nodes allow inbound access on port **10250/tcp** from the Kubernetes API endpoint CIDR via NSG or Security List.

- **“Invalid kubeconfig … mapping/str” error:**  
  Persistent errors may indicate malformed kubeconfig. Share the first 200 characters of your kubeconfig in an issue for help.

- **Security token authentication issues:**  
  Confirm `OCI_CLI_AUTH=security_token` is set. The server patches kubeconfig exec arguments accordingly.

- **Token expiration:**  
  Use the `auth_refresh` tool to refresh tokens without restarting:

  ```json
  {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "auth_refresh",
      "arguments": {}
    }
  }
  ```

---

Thank you for using the OKE MCP Server. For issues or feature requests, please open an issue in the repository.

**Example JSON-RPC calls:**

List pods with security token auth:

```json
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"k8s_list","arguments":{"cluster_id":"ocid1.cluster.oc1.eu-frankfurt-1....","kind":"Pod","namespace":"default","auth":"security_token","limit":20}}}
```

List pods without specifying auth explicitly:

```json
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"k8s_list","arguments":{"cluster_id":"ocid1.cluster.oc1.eu-frankfurt-1....","kind":"Pod","namespace":"default","limit":20}}}
```