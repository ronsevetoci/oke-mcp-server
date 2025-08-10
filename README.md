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
# Run the MCP server directly (reads JSON-RPC from stdin)
run: venv
	$(PY) main.py

# Preferred: run through the MCP CLI using stdio transport
run-stdio: venv
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio $(PY) main.py

# Launch MCP Inspector (browser) and auto-connect to this server
# If you encounter a 'uv' error, set INSPECTOR_CMD to: mcp dev ./main.py
INSPECTOR_CMD ?= mcp dev ./main.py

dev: venv
	MCP_LOG_LEVEL=DEBUG $(INSPECTOR_CMD)

clean:
	rm -rf $(VENV) __pycache__ **/__pycache__
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

## Run with uvx (Zero-Setup)

If you have [uv](https://github.com/astral-sh/uv) installed, you can run the server without creating a local virtualenv or installing dependencies into your system Python.

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

## Project Structure

- `main.py` — MCP server entry point  
- `oke_auth.py` — OKE authentication handler  
- `oci_auth.py` — OCI authentication handler  
- `handlers/oke.py` — Core OKE logic and API interactions  
- `config_store.py` — Configuration management  
- `requirements.txt` — Runtime dependencies  
- `Makefile` — Build and run commands  

---

## Quickstart (Local Setup)

Follow these steps to get started quickly:

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

   The server will start and wait for JSON-RPC input on standard input.

4. **Initialize the JSON-RPC session:**

   Send the following commands to initialize the MCP server:

   ```json
   {"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.0.0"}}}
   {"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
   ```

5. **(Optional) Use MCP Inspector for interactive debugging:**

   ```bash
   make dev
   ```

   This opens the MCP Inspector in your browser and connects to the server. If launching `uv` fails, the command falls back to `mcp dev ./main.py`.

6. **(Optional) Manual JSON-RPC call example for listing pods:**

   After initialization, send this JSON-RPC request to list pods in the `default` namespace:

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

## Common Issues & Solutions

- **Inspector connection error or `'uv'` command not found:**  
  Use the default `make dev` command which falls back to `mcp dev ./main.py`. Install `uv` if you prefer to use it.

- **401 Unauthorized when fetching pod logs:**  
  Ensure worker nodes allow inbound access on port **10250/tcp** from the Kubernetes API endpoint CIDR via NSG or Security List. This is required for `read_namespaced_pod_log` to succeed.

- **“Invalid kubeconfig … mapping/str” error:**  
  The server now robustly decodes OCI kubeconfig payloads. Persistent errors may indicate a malformed kubeconfig. Please share the first 200 characters of your kubeconfig in an issue for assistance.

- **Security token authentication issues:**  
  Confirm that `OCI_CLI_AUTH=security_token` is set in the server environment. The server automatically patches kubeconfig exec arguments with `--auth security_token`.

---

## Using with Claude Desktop (Optional)

Create or update `~/Library/Application Support/Claude/claude_desktop_config.json` with the following, replacing paths and OCIDs accordingly:

```json
{
  "mcpServers": {
    "oke": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/main.py"],
      "env": {
        "OKE_COMPARTMENT_ID": "ocid1.compartment.oc1..YOUR_COMPARTMENT_OCID",
        "OKE_CLUSTER_ID": "ocid1.cluster.oc1..YOUR_CLUSTER_OCID",
        "OCI_CLI_AUTH": "security_token"
      }
    }
  }
}
```

### Claude Desktop via uvx (recommended)

Use uvx to fetch/build and run the console script automatically. Make sure to use the **absolute path** to `uvx` in `command` (GUI apps don’t inherit your shell PATH). You can find it with `which uvx`.

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

**Development from local source:** during development, point uvx at your repo to rebuild on changes:

```json
{
  "mcpServers": {
    "oke": {
      "command": "/Users/<you>/.local/bin/uvx",
      "args": ["--from", "/absolute/path/to/oke-mcp-server", "oke-mcp-server", "--transport", "stdio"],
      "env": {
        "OKE_COMPARTMENT_ID": "ocid1.compartment.oc1..YOUR_COMPARTMENT_OCID",
        "OKE_CLUSTER_ID": "ocid1.cluster.oc1..YOUR_CLUSTER_OCID",
        "OCI_CLI_AUTH": "security_token",
        "LOG_LEVEL": "DEBUG",
        "PATH": "/Users/<you>/.local/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

Restart Claude Desktop, then prompt it with:  
> “Using **oke**, list pods in **default**”.

---

---

## Packaging & Releases (uvx + PyPI + GitHub Actions)

This project is configured to expose a console script `oke-mcp-server` (via `pyproject.toml`) so it can be launched by `uvx` or installed from PyPI.

**Local build & smoke test**
```bash
python -m pip install --upgrade build twine
python -m build
pip install dist/oke_mcp_server-*.whl
oke-mcp-server --transport stdio
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
