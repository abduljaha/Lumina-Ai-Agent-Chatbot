"""MCP server - exposes local tools to external MCP clients.

Uses FastMCP to register and serve the application's tool registry
as a standard MCP server endpoint.
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from app.tools.registry import ToolRegistry

logger = logging.getLogger("app")


class MCPServer:
    """Wraps the tool registry as a FastMCP server."""

    def __init__(self, tool_registry: ToolRegistry, server_name: str = "ai-chatbot-mcp") -> None:
        self._registry = tool_registry
        self._server = FastMCP(server_name)
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all tools from the registry as MCP tools."""
        for tool_info in self._registry.list_tools():
            name = tool_info.get("name")
            description = tool_info.get("description", "")
            parameters = tool_info.get("parameters", {})

            @self._server.tool(name=name, description=description)
            async def _tool_handler(**kwargs: Any) -> Any:
                result = await self._registry.invoke(name, **kwargs)
                return result.to_dict()

    @property
    def server(self) -> FastMCP:
        """Return the FastMCP server instance."""
        return self._server

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the MCP server."""
        logger.info("Starting MCP server on %s:%d", host, port)
        self._server.run(host=host, port=port)

    def get_tools(self) -> list[dict[str, Any]]:
        """Return the registered tools."""
        return self._registry.list_tools()
