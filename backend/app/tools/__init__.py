"""Tool layer - executable tools for the agent.

Tools are registered with the ToolRegistry and injected into the LangGraph
agent nodes. Each tool implements the BaseTool protocol with a name,
description, and async invoke method.
"""
from __future__ import annotations

from typing import Protocol

from app.tools.registry import ToolRegistry
from app.tools.base import BaseTool, ToolResult

__all__ = ["ToolRegistry", "BaseTool", "ToolResult"]
