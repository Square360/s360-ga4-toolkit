# syntax=docker/dockerfile:1.7
#
# ga4-toolkit — MCP server container.
#
# Build:  docker build -t s360-ga4-toolkit .
# Run:    see docker-compose.yml — the compose file handles volume mounts for
#         the service-account JSON and sites.yaml, which must NEVER be baked
#         into the image.

FROM python:3.11-slim-bookworm AS builder

# uv is the fastest way to resolve + install deps in a container.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Copy only what's needed for dep resolution first — maximizes layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

RUN uv venv /opt/venv --python 3.11 \
    && uv pip install --python /opt/venv/bin/python .


FROM python:3.11-slim-bookworm AS runtime

# Create a non-root user; the MCP server does not need root.
RUN groupadd --system --gid 1000 ga4 \
    && useradd --system --uid 1000 --gid ga4 --create-home --shell /bin/bash ga4

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Default sites config location inside the container — mount over this from host.
    GA4_SITES_CONFIG=/app/config/sites.yaml \
    # Default service-account JSON location — mount over this from host.
    GA4_SERVICE_ACCOUNT_PATH=/app/secrets/service-account.json

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src /app/src

WORKDIR /app
USER ga4

# The MCP server runs on stdio transport. Containers are typically orchestrated
# by an MCP client that spawns this process and reads/writes JSON-RPC over the
# stdio pipes. For docker-compose, we use interactive stdio via `tty: true`.
CMD ["ga4-mcp"]
