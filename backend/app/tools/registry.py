"""Tool registry - discovers and manages tool instances."""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger("app")


class ToolRegistry:
    """Registry that discovers, registers, and resolves tools.

    Tools can be registered manually or auto-discovered by scanning
    the `app.tools` package for `BaseTool` subclasses.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, tool: BaseTool) -> None:
        """Register a single tool instance."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def register_class(self, tool_cls: type[BaseTool], **kwargs: Any) -> None:
        """Instantiate and register a tool class."""
        self.register(tool_cls(**kwargs))

    def register_all(self, tools: list[BaseTool]) -> None:
        """Register multiple tool instances."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def auto_discover(self) -> None:
        """Discover and register all tools in the `app.tools.tools` module."""
        try:
            import app.tools.tools as tools_pkg

            for mod_info in pkgutil.iter_modules(tools_pkg.__path__):
                module = importlib.import_module(f"app.tools.tools.{mod_info.name}")
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        obj is not BaseTool
                        and issubclass(obj, BaseTool)
                        and obj.__module__ == module.__name__
                        and getattr(obj, "name", None)
                    ):
                        self.register_class(obj)
        except ImportError as exc:
            logger.warning("Tool auto-discovery failed: %s", exc)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def get(self, name: str) -> BaseTool:
        """Resolve a tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found in registry")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check whether a tool is registered."""
        return name in self._tools

    async def invoke(self, name: str, **kwargs: Any) -> ToolResult:
        """Invoke a tool by name with given arguments."""
        tool = self.get(name)
        try:
            return await tool.invoke(**kwargs)
        except Exception as exc:
            logger.exception("Tool '%s' failed", name)
            return ToolResult(success=False, error=str(exc), metadata={"tool": name})

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools as metadata dicts."""
        return [tool.to_dict() for tool in self._tools.values()]

    # ------------------------------------------------------------------
    # Tool calling schema for LLM function-calling
    # ------------------------------------------------------------------
    def to_openai_schemas(self) -> list[dict[str, Any]]:
        """Convert registered tools to OpenAI function-calling schemas."""
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            tool_dict = tool.to_dict()
            params = tool_dict.get("parameters") or {}
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_dict["name"],
                        "description": tool_dict["description"],
                        "parameters": params,
                    },
                }
            )
        return schemas
