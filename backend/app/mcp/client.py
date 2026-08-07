"""MCP client - discovers tools from external MCP servers."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.base import ToolResult

logger = logging.getLogger("app")


class MCPClient:
    """Client that connects to external MCP servers and discovers tools.

    Supports FastMCP protocol for dynamic tool discovery and invocation.
    """

    def __init__(self, server_url: str | None = None) -> None:
        self._server_url = server_url
        self._discovered_tools: dict[str, dict[str, Any]] = {}

    @property
    def has_server(self) -> bool:
        """Check if a server URL is configured."""
        return bool(self._server_url)

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Discover available tools from the MCP server."""
        if not self._server_url:
            return []
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._server_url}/tools")
                resp.raise_for_status()
                data = resp.json()
                tools = data.get("tools", data if isinstance(data, list) else [])
                for tool in tools:
                    self._discovered_tools[tool.get("name", "")] = tool
                return tools
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to discover MCP tools: %s", exc)
            return []

    async def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool on the MCP server."""
        if not self._server_url:
            return ToolResult(success=False, error="No MCP server configured")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._server_url}/tools/{tool_name}",
                    json={"arguments": arguments},
                )
                resp.raise_for_status()
                data = resp.json()
                return ToolResult(
                    success=True,
                    output=data.get("output", data),
                    metadata={"mcp_server": self._server_url},
                )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"MCP tool call failed: {exc}")

    def get_discovered_tools(self) -> list[dict[str, Any]]:
        """Return previously discovered tools."""
        return list(self._discovered_tools.values())
