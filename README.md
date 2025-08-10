# OKE MCP Server

The **Oracle Container Engine for Kubernetes (OKE) Model Context Protocol (MCP) Server** enables Large Language Models (LLMs) and MCP-aware clients to inspect, troubleshoot, and interact with OKE clusters programmatically. This tool is designed for OCI customers, DevOps teams, and developers seeking streamlined Kubernetes diagnostics and management through MCP.

![MCP Server Demo](assets/demo.gif)  
*Demo of the MCP Server in action.*

---

## Runtime Dependencies

The OKE MCP Server requires specific versions of dependencies, pinned or floored for compatibility. These are listed in the `requirements.txt` file located at the root of the repository.

**requirements.txt**
```txt
oci==2.157.1
kubernetes>=29.0.0
PyYAML>=6.0.1
mcp>=0.2.0
```

---

## Makefile

The provided `Makefile` offers convenient commands for setup, running the server, and development tasks:

```makefile
install: venv
	$(PY) -m pip install -r requirements.txt

run-stdio: venv
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio $(PY) main.py

dev: venv
	MCP_LOG_LEVEL=DEBUG mcp dev ./main.py

clean:
	rm -rf $(VENV) __pycache__ **/__pycache__

format:
	black .

lint:
	flake8 .

typecheck:
	mypy .
```

---

## Prerequisites

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

> **Note:** If you use security token authentication locally, your existing `kubectl` setup likely works. This server mirrors that flow by patching the kubeconfig exec arguments with `--auth security_token`.

---

## Running the MCP Server

### Primary: Using uvx (Zero-Setup)

The recommended way to run the server is with [uv](https://github.com/astral-sh/uv) and its `uvx` launcher, which requires no local virtual environment or manual dependency installation.

```bash
# Run directly from source (useful during development)
uvx --from . oke-mcp-server --transport stdio

# Or run the published package (after you publish to PyPI)
uvx oke-mcp-server --transport stdio
```

> **Tip:** Set logging for troubleshooting:
>
> ```bash
> LOG_LEVEL=DEBUG uvx --from . oke-mcp-server --transport stdio
> ```

If you see no output when piping JSON into stdin, force unbuffered/stdout line buffering in your shell:

```bash
PYTHONUNBUFFERED=1 uvx --from . oke-mcp-server --transport stdio
```

---

### Development Fallback: Using Virtualenv

If you prefer or need a local virtual environment, you can still use the traditional workflow:

1. **Clean existing environment and install dependencies:**

   ```bash
   make clean
   make install
   ```

2. **Set default environment variables:**

   Replace the placeholders with your actual OCIDs.

   ```bash
   export OKE_COMPARTMENT_ID="ocid1.compartment.oc1..YOUR_COMPARTMENT_OCID"
   export OKE_CLUSTER_ID="ocid1.cluster.oc1..YOUR_CLUSTER_OCID"
   # If using security token authentication locally:
   export OCI_CLI_AUTH=security_token
   ```

3. **Run the server using the MCP CLI with stdio transport:**

   ```bash
   make run-stdio
   ```

---

### New CLI Flags

The MCP server now supports additional CLI flags to simplify usage:

- `--set-defaults-compartment <compartment_ocid>`  
  Sets the default compartment OCID used by the server, avoiding the need to specify it in every request.

- `--set-defaults-cluster <cluster_ocid>`  
  Sets the default cluster OCID used by the server.

- `--print-tools`  
  Prints a list of available MCP tools and their descriptions, including the newly added tools.

---

### New Tools

Two new MCP tools have been added for enhanced usability:

- `meta_env`  
  Provides metadata about the server environment and configuration, useful for diagnostics and introspection.

- `auth_refresh`  
  Allows refreshing authentication tokens on-demand without restarting the server, especially useful when using security token authentication.

---

### Initializing the JSON-RPC Session

After starting the server (preferably via `uvx`), initialize the MCP server by sending these JSON-RPC commands:

```json
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.0.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
```

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

## Quickstart Example: List Pods in Default Namespace

After initializing the server, send this JSON-RPC request to list pods:

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

Use `uvx` to run the server and test:

```bash
uvx --from . oke-mcp-server --transport stdio
```

---

## Common Issues & Solutions

- **401 Unauthorized when fetching pod logs:**  
  Ensure worker nodes allow inbound access on port **10250/tcp** from the Kubernetes API endpoint CIDR via NSG or Security List. This is required for `read_namespaced_pod_log` to succeed.

- **“Invalid kubeconfig … mapping/str” error:**  
  The server now robustly decodes OCI kubeconfig payloads. Persistent errors may indicate a malformed kubeconfig. Please share the first 200 characters of your kubeconfig in an issue for assistance.

- **Security token authentication issues:**  
  Confirm that `OCI_CLI_AUTH=security_token` is set in the server environment. The server automatically patches kubeconfig exec arguments with `--auth security_token`.

- **Authentication token expiration:**  
  Instead of restarting the server when your security token expires, use the `auth_refresh` tool to refresh tokens on-demand:

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

  This avoids downtime and streamlines token management.

---

## Using with Claude Desktop (Simplified)

Create or update `~/Library/Application Support/Claude/claude_desktop_config.json` with the following, replacing paths and OCIDs accordingly.

### Using uvx (recommended)

Make sure to use the **absolute path** to `uvx` in `command` (GUI apps don’t inherit your shell PATH). You can find it with `which uvx`.

```json
{
  "mcpServers": {
    "oke": {
      "command": "/Users/<you>/.local/bin/uvx",
      "args": ["oke-mcp-server", "--transport", "stdio"],
      "env": {
        "OKE_COMPARTMENT_ID": "ocid1.compartment.oc1..YOUR_COMPARTMENT_OCID",
        "OKE_CLUSTER_ID": "ocid1.cluster.oc1..YOUR_CLUSTER_OCID",
        "OCI_CLI_AUTH": "security_token",
        "LOG_LEVEL": "INFO",
        "PATH": "/Users/<you>/.local/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

Restart Claude Desktop, then prompt it with:  
> “Using **oke**, list pods in **default**”.

---

## Advanced Usage & Future Work

- **MCP Inspector:**  
  Previously, an MCP Inspector browser interface was available for interactive debugging and visualization. This has been removed to simplify the setup. Future versions may reintroduce this or alternative UIs.

- **Multiple Transport Support:**  
  Currently, only `stdio` transport is supported and documented. Other transports may be considered in future releases.

- **Docker Usage:**  
  Docker-based deployment instructions have been removed to focus on uvx and virtualenv workflows.

- **Additional Makefile Targets:**  
  Targets like `format`, `lint`, and `typecheck` are available for code quality checks and formatting.

---

---

## Packaging & Releases (uvx + PyPI + GitHub Actions)

This project is configured to expose a console script `oke-mcp-server` (via `pyproject.toml`) so it can be launched by `uvx` or installed from PyPI.

**Local build & smoke test**
```bash
python -m pip install --upgrade build twine
python -m build
pip install dist/oke_mcp_server-*.whl
uvx oke-mcp-server --transport stdio
```

**Publish to PyPI** (optional)
```bash
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="pypi-XXXXXXXXXXXXXXXXX"
twine upload dist/*
```

**Tagging releases**
```bash
git tag v0.1.0
git push origin v0.1.0
```

**GitHub Actions (automate builds & publish on tag)**
Add a workflow at `.github/workflows/publish.yml` to build on tag and publish to PyPI. This enables a fully automated path from PR → tag → packaged release → `uvx oke-mcp-server` for users.

---

Thank you for using the OKE MCP Server. If you encounter any issues or have feature requests, please open an issue on the repository.
