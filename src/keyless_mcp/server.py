"""Builds the MCP server: a core ``MCPServer`` plus every selected adapter's tools."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from keyless_mcp import __version__
from keyless_mcp.core import HttpClient, HttpConfig, LoadedAdapter, register_adapters

INSTRUCTIONS = (
    "keyless-mcp exposes free public APIs that need no API key. Tool names are "
    "<adapter>_<verb>. All tools are read-only. If a tool returns an error, the message "
    "explains whether the input was invalid or the upstream service failed."
)


@dataclass(frozen=True)
class BuiltServer:
    mcp: MCPServer
    http: HttpClient
    adapters: list[LoadedAdapter]


def build_server(
    toolsets: set[str] | None = None, http_config: HttpConfig | None = None
) -> BuiltServer:
    """Create the server. ``toolsets=None`` registers every adapter."""
    mcp = MCPServer("keyless-mcp", instructions=INSTRUCTIONS, version=__version__)
    http = HttpClient(http_config if http_config is not None else HttpConfig.from_env())
    adapters = register_adapters(mcp, http, toolsets)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        """Report process-local readiness without querying an upstream API."""
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "toolsets": sorted({adapter.spec.toolset for adapter in adapters}),
                "tools": sum(len(adapter.tool_names) for adapter in adapters),
            }
        )

    return BuiltServer(mcp, http, adapters)
