"""Stdio bridge that discovers and connects to a TG Account MCP HTTP service."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared._httpx_utils import create_mcp_http_client

from tg_mcp.discovery import DISCOVERY_PORT, discover_services, validate_endpoint


def _token() -> str:
    value = os.environ.get("TG_MCP_TOKEN", "")
    if not value:
        raise ValueError("TG_MCP_TOKEN is required")
    return value


def _discovery_port() -> int:
    value = int(os.environ.get("TG_MCP_DISCOVERY_PORT", str(DISCOVERY_PORT)))
    if not 1 <= value <= 65535:
        raise ValueError("TG_MCP_DISCOVERY_PORT must be between 1 and 65535")
    return value


@asynccontextmanager
async def upstream_session(endpoint: str, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with create_mcp_http_client(headers=headers) as client:
        async with streamable_http_client(endpoint, http_client=client) as streams:
            async with ClientSession(*streams) as session:
                result = await session.initialize()
                yield session, result


async def endpoint_works(endpoint: str, token: str, deadline_seconds: float = 2.0) -> bool:
    try:
        async with asyncio.timeout(deadline_seconds):
            async with upstream_session(endpoint, token):
                return True
    except Exception:
        return False


async def select_endpoint(token: str) -> str:
    configured = os.environ.get("TG_MCP_URL")
    if configured:
        endpoint = validate_endpoint(configured)
        if await endpoint_works(endpoint, token, deadline_seconds=5.0):
            return endpoint
        raise ConnectionError("TG_MCP_URL did not accept the configured token")

    for endpoint in await discover_services(token, _discovery_port()):
        if await endpoint_works(endpoint, token, deadline_seconds=5.0):
            return endpoint
    raise ConnectionError("No authenticated TG Account MCP service was found")


async def run_bridge() -> None:
    token = _token()
    endpoint = await select_endpoint(token)
    async with upstream_session(endpoint, token) as (session, upstream):

        async def list_tools(
            _context, params: types.PaginatedRequestParams | None
        ) -> types.ListToolsResult:
            return await session.list_tools(params=params)

        async def call_tool(
            _context, params: types.CallToolRequestParams
        ) -> types.CallToolResult | types.InputRequiredResult:
            return await session.call_tool(
                params.name,
                params.arguments,
                input_responses=params.input_responses,
                request_state=params.request_state,
                meta=params.meta,
                allow_input_required=True,
            )

        server = Server(
            "tg-account-mcp-bridge",
            version=upstream.server_info.version,
            title=upstream.server_info.title or "TG Account MCP",
            instructions=upstream.instructions,
            on_list_tools=list_tools,
            on_call_tool=call_tool,
        )
        async with stdio_server() as streams:
            await server.run(
                *streams,
                server.create_initialization_options(),
                raise_exceptions=False,
            )
