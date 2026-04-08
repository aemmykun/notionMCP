# Dockerfile for Notion MCP Governance-First Server

# Stage 1: Build runtime environment
FROM python:3.11.15-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Upgrade packaging tools to address CVEs:
# - CVE-2026-24049 (wheel 0.45.1 vendored in setuptools)
# - CVE-2026-1703 (pip 24.0)
# - CVE-2025-8869 (pip, mitigated by Python 3.11.15)
RUN python -m venv "$VIRTUAL_ENV" && \
    python -m pip install --upgrade \
    pip==26.0.1 \
    setuptools==82.0.1

# Update Debian system packages for security vulnerabilities
RUN apt-get update && \
    apt-get install -y --only-upgrade util-linux tar && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


# Stage 2: Final image
FROM python:3.11.15-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    MCP_HTTP_MODE=1

# Upgrade packaging tools to address CVEs
RUN python -m pip install --upgrade \
    pip==26.0.1 \
    setuptools==82.0.1

# Update Debian system packages for security vulnerabilities and create a non-root runtime user
RUN apt-get update && \
    apt-get install -y --only-upgrade util-linux tar && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/app app && \
    mkdir -p /app /tmp && \
    chown -R app:app /app /tmp

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src/mcp_server ./src/mcp_server

USER app:app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"

CMD ["python", "-m", "uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "src"]
