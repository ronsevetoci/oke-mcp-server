# OKE MCP Server

A Model Context Protocol (MCP) server that lets LLMs (and MCP-aware clients) inspect and troubleshoot **Oracle Container Engine for Kubernetes (OKE)**.

This README provides a clean, working quickstart and detailed information about the project. If anything here fails on your machine, please reach out and we’ll adjust accordingly.

---

![MCP Server Demo](assets/demo.gif)

## Runtime Dependencies

The runtime dependencies for the OKE MCP Server are pinned or floored to versions known to work locally. These are specified in the `requirements.txt` file, which should be placed in the root of your repository.

**requirements.txt**
```txt
oci==2.157.1
kubernetes>=29.0.0
PyYAML>=6.0.1
mcp>=0.2.0
```

---

## Makefile

The `Makefile` included in this repository provides convenient commands for setting up the environment, running the server, and development tasks.

# Run the MCP server directly (reads JSON-RPC from stdin)
run: venv
	$(PY) main.py

# Preferred: run through the MCP CLI using stdio transport
run-stdio: venv
	MCP_LOG_LEVEL=DEBUG mcp run -t stdio $(PY) main.py

# Launch MCP Inspector (browser) and auto-connect to this server
# If you see a UV error, set INSPECTOR_CMD to: mcp dev ./main.py
INSPECTOR_CMD ?= mcp dev ./main.py

dev: venv
	MCP_LOG_LEVEL=DEBUG $(INSPECTOR_CMD)

clean:
	rm -rf $(VENV) __pycache__ **/__pycache__
```

---

## Prerequisites

- **Python 3.10+** (3.11 recommended). Ensure the correct Python version is installed by running:

  ```bash
  python3 --version
  ```

- **OCI credentials**:
  - For local development using security tokens (like your `kubectl`): set `OCI_CLI_AUTH=security_token` and log in via the OCI CLI or console to refresh your token.
  - Or use API key authentication configured in `~/.oci/config` (DEFAULT or a named profile).

- **MCP CLI** (`mcp`). If not installed, install it with:

  ```bash
  pipx install mcp  # or: pip install mcp
  ```

> Tip: If you use security tokens locally, your `kubectl` likely already works. This server mirrors that flow by patching the kubeconfig exec args with `--auth security_token`.

---

## Project Structure

Key files in this repository include:

- `main.py` — Entry point for the MCP server.
- `oke_auth.py` — Handles OKE authentication.
- `oci_auth.py` - Handles OCI authentication.
- `handlers/oke.py` — Core OKE logic and API interactions.
- `config_store.py` — Configuration management.
- `requirements.txt` — Runtime dependencies.
- `Makefile` — Build and run commands.

---

## Quickstart (local)

1. **Clean existing environment and create virtual environment with dependencies**

   ```bash
   make clean
   make install
   ```

2. **Export default environment variables** (so you don’t have to pass OCIDs on every call)

   ```bash
   export OKE_COMPARTMENT_ID="ocid1.compartment.oc1..YOUR_COMP"
   export OKE_CLUSTER_ID="ocid1.cluster.oc1..YOUR_CLUSTER"
   # Only if you use security tokens locally:
   export OCI_CLI_AUTH=security_token
   ```

3. **Run the server** (using stdio via MCP CLI)

   ```bash
   make run-stdio
   ```

   You should see logs from the MCP server. It will now wait for JSON-RPC input on stdio (handled by MCP CLI).


### JSON-RPC initilization commands - 
  {"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.0.0"}}}
  {"jsonrpc":"2.0","method":"notifications/initialized","params":{}}


4. **(Option A) Use MCP Inspector**

   ```bash
   make dev
   ```

   This command opens the MCP Inspector in your browser and connects to the server. If it cannot launch `uv`, it will fallback to `mcp dev ./main.py`.

5. **(Option B) Manual JSON-RPC (for debugging)**

   After receiving `initialize` and `notifications/initialized`, send a tools call like:

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

## Common Gotchas & Fixes

- **Inspector connection error / `uv` not found**

  - `make dev` defaults to `mcp dev ./main.py`.
  - If you changed `INSPECTOR_CMD` to use `uv`, install it or revert back.

- **401 Unauthorized on pod logs**

  - Open worker nodes’ **10250/tcp** port from the K8s API endpoint CIDR to nodes (via NSG/Security List).
  - This is required for `read_namespaced_pod_log` to work.

- **“Invalid kubeconfig … mapping/str” error**

  - The server now robustly decodes OCI’s kubeconfig payload.
  - If this error persists, your kubeconfig might be malformed.
  - Paste the first 200 characters of your kubeconfig in an issue for assistance.

- **Security token authentication**

  - Ensure `OCI_CLI_AUTH=security_token` is set in the server process environment.
  - The server patches kubeconfig exec args to include `--auth security_token` automatically.

---

## Using with Claude Desktop (optional)

Create `~/Library/Application Support/Claude/claude_desktop_config.json` with the following content, replacing paths and OCIDs accordingly:

```json
{
  "mcpServers": {
    "oke": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/main.py"],
      "env": {
        "OKE_COMPARTMENT_ID": "ocid1.compartment.oc1..YOUR_COMP",
        "OKE_CLUSTER_ID": "ocid1.cluster.oc1..YOUR_CLUSTER",
        "OCI_CLI_AUTH": "security_token"
      }
    }
  }
}
```

Restart Claude, then prompt it with:  
“Using **oke**, list pods in **default**”.
