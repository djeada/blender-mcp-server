FROM python:3.12-slim AS base

LABEL maintainer="Adam Djellouli <adam@djellouli.com>"
LABEL description="Blender MCP Server (stdio). Talks to a Blender add-on bridge or a mounted Blender binary."

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 mcp

USER mcp

# Bridge transport: the add-on listens on the host's 127.0.0.1, so run the
# container with --network host (Linux) and mount the add-on's token file:
#   docker run -i --rm --network host \
#     -v ~/.blender-mcp/token:/home/mcp/.blender-mcp/token:ro blender-mcp-server
# BLENDER_MCP_HOST / BLENDER_MCP_PORT override the bridge address.
#
# Headless transport: Blender is NOT bundled. Mount a Blender install and point
# BLENDER_BIN at it, or set BLENDER_MCP_HEADLESS=0 to disable that transport.
ENV BLENDER_BIN=blender

ENTRYPOINT ["blender-mcp-server"]
