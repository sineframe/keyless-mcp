# keyless-mcp container image.
#
#   docker build -t keyless-mcp .
#   docker run -i --rm --no-healthcheck keyless-mcp      # MCP over stdio (the default)
#   docker run --rm -p 8000:8000 keyless-mcp --transport http --host 0.0.0.0
#                                                        # Streamable HTTP at http://localhost:8000/mcp
#   docker run -i --rm --no-healthcheck -e KEYLESS_MCP_TOOLSETS=dev,geo keyless-mcp
#                                                        # stdio with only some toolsets
#
# The entrypoint is `keyless-mcp`, so anything after the image name is a keyless-mcp flag
# (`--toolsets`, `--list-tools`, ...). Inside a container the HTTP transport must bind 0.0.0.0
# (the default is 127.0.0.1, which a published port cannot reach). The server needs no API keys
# and no volumes; it only needs outbound HTTPS to the public APIs it wraps.

# ---- build: resolve and install the locked dependencies, then the project, into /app/.venv ----
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so this layer is cached until pyproject.toml or uv.lock change.
# README.md is optional here (the wildcard matches nothing if it does not exist yet).
COPY pyproject.toml uv.lock LICENSE README.md* ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- runtime: python + the finished virtualenv, no uv, no build tools, non-root ----
FROM python:3.12-slim

# Registry ownership proof (MCP Registry verifies this label matches server.json) and OCI metadata.
LABEL io.modelcontextprotocol.server.name="io.github.sineframe/keyless-mcp" \
      org.opencontainers.image.title="keyless-mcp" \
      org.opencontainers.image.description="One MCP server wrapping free, no-auth public APIs." \
      org.opencontainers.image.source="https://github.com/sineframe/keyless-mcp" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --system --gid 10001 keyless \
    && useradd --system --uid 10001 --gid keyless --no-create-home --shell /usr/sbin/nologin keyless

COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER keyless
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).close()"
ENTRYPOINT ["keyless-mcp"]
