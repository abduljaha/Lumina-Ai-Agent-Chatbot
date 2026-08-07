"""Tests for tool implementations."""
from __future__ import annotations

import pytest

from app.tools.tools.calculator import CalculatorTool
from app.tools.tools.time_tool import CurrentTimeTool


@pytest.mark.asyncio
async def test_calculator_tool() -> None:
    """Test the calculator tool with valid expressions."""
    tool = CalculatorTool()
    result = await tool.invoke(expression="2 + 3 * 4")
    assert result.success
    assert result.output == 14.0


@pytest.mark.asyncio
async def test_calculator_tool_invalid() -> None:
    """Test the calculator tool with invalid input."""
    tool = CalculatorTool()
    result = await tool.invoke(expression="not a math expression")
    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
async def test_time_tool() -> None:
    """Test the time tool returns current time."""
    tool = CurrentTimeTool()
    result = await tool.invoke(timezone="UTC")
    assert result.success
    assert "time" in str(result.output).lower() or "utc" in str(result.output).lower()


@pytest.mark.asyncio
async def test_calculator_tool_metadata() -> None:
    """Test calculator tool metadata."""
    tool = CalculatorTool()
    metadata = tool.to_dict()
    assert metadata["name"] == "calculator"
    assert "description" in metadata
