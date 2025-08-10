# Dockerfile
FROM python:3.11-slim

# System deps (node+npx for MCP proxy, CA, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . /app

# Non-root
RUN useradd -m appuser
USER appuser

# Defaults (override in K8s)
ENV PYTHONUNBUFFERED=1 \
    MCP_LOG_LEVEL=INFO \
    MCP_HTTP_PORT=6277 \
    OCI_CLI_PROFILE=DEFAULT \
    # Examples: set in K8s or Claude env
    # OKE_COMPARTMENT_ID=ocid1.compartment... \
    # OKE_CLUSTER_ID=ocid1.cluster... \
    # OCI_CLI_AUTH=security_token \
    # REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    # OCI_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PATH="/home/appuser/.local/bin:${PATH}"

# Expose MCP HTTP proxy port
EXPOSE 6277

# One-container model: run MCP HTTP proxy, which spawns the Python server via stdio
# You can hit http://<pod-ip>:6277 with MCP clients that support HTTP transport
CMD [ "sh", "-lc", "MCP_LOG_LEVEL=$MCP_LOG_LEVEL npx -y @modelcontextprotocol/proxy@latest http --port ${MCP_HTTP_PORT:-6277} --stdio --command python -- main.py" ]