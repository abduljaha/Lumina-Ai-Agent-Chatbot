"""Tool listing endpoint - powers the frontend's AI-tools picker."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.container import app_container

router = APIRouter()

# Tools that are either an internal graph-control signal (ask_user), already
# have their own dedicated UI entry point (knowledge_base_search - the
# paperclip attach button; web_search/serp_search - the globe button), so
# listing them again here would just duplicate an existing control rather
# than surface a new capability.
_HIDDEN_FROM_PICKER = {"ask_user", "knowledge_base_search", "web_search", "serp_search"}

# One natural-language example per tool, phrased to land on the same
# deterministic intent-detection patterns the backend already routes on
# (see IntentDetectionNode) - so picking a tool here uses the identical,
# already-verified path a user typing the same words would.
_EXAMPLE_PROMPTS: dict[str, str] = {
    "calculator": "Calculate ",
    "current_time": "What time is it in ",
    "weather": "What's the weather in ",
    "wikipedia": "What is ",
    "python_executor": "Run this Python code:\n\n",
}


@router.get("", summary="List available AI tools")
async def list_tools() -> dict:
    """Return the tools the assistant can use, for the frontend's tools picker."""
    tools = app_container.tool_registry.list_tools()
    items = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "example_prompt": _EXAMPLE_PROMPTS.get(tool["name"], ""),
        }
        for tool in tools
        if tool["name"] not in _HIDDEN_FROM_PICKER
    ]
    return {"items": items}
