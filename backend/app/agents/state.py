"""LangGraph state definitions.

The state is a typed dictionary that flows through every node in the graph.
It captures the full conversational context, memory, tool selection,
model routing, and error handling state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.graph import MessagesState

# Sentinel to track "no intent detected yet"
INTENT_UNKNOWN = "unknown"
INTENT_CHAT = "chat"
INTENT_TOOL = "tool"
INTENT_ASK_USER = "ask_user"
INTENT_RAG = "rag"
INTENT_IMAGE = "image"
INTENT_FOLLOWUP = "followup"


@dataclass
class ChatState(MessagesState):
    """Extended graph state for the conversational agent.

    Inherits from MessagesState which provides the `messages` list.
    Additional fields cover memory, retrieval, intent, tool routing,
    model selection, and failure handling.
    """

    # --- Identity / Context ---
    user_id: str | None = None
    thread_id: str | None = None
    session_id: str | None = None
    # User-configurable custom instructions (Settings > System Prompt),
    # appended to the base system prompt built in the LLM node.
    custom_system_prompt: str | None = None
    # Base64 data URLs for this turn's image attachments (see llm_node.py) -
    # kept separate from `messages`'s durable, DB-replayed text history since
    # only the *current* turn's images are ever sent to a vision model, not
    # every image from earlier in the thread.
    images: list[str] = field(default_factory=list)

    # --- Memory ---
    short_term_memory: list[dict] = field(default_factory=list)
    long_term_memory: list[dict] = field(default_factory=list)
    conversation_memory: list[dict] = field(default_factory=list)
    entity_memory: dict[str, Any] = field(default_factory=dict)
    semantic_memory: list[dict] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)
    memory_summary: str | None = None

    # --- Retrieval / RAG ---
    retrieved_documents: list[dict] = field(default_factory=list)
    context: str | None = None
    citations: list[dict] = field(default_factory=list)

    # --- Intent & routing ---
    intent: str = INTENT_UNKNOWN
    route: Literal["direct", "rag", "tool", "ask_user"] = "direct"
    selected_tool: str | None = None
    # Multiple live-data tools can be needed by a single message (e.g. "time
    # and weather in Paris"); this holds all of them, with selected_tool kept
    # as the first entry for nodes/routing that only care about one.
    detected_tools: list[str] = field(default_factory=list)
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict] = field(default_factory=list)
    tool_request: dict[str, Any] | None = None

    # --- Model / Provider ---
    requested_model: str | None = None
    current_model: str | None = None
    current_provider: str | None = None
    fallback_chain: list[str] = field(default_factory=list)
    model_attempts: int = 0

    # --- Metadata & errors ---
    metadata: dict[str, Any] = field(default_factory=dict)
    error_state: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    needs_user_input: bool = False
    pending_question: str | None = None

    # --- Streaming / generation ---
    generation: str | None = None
    reflection_feedback: str | None = None
    is_valid_answer: bool = True

    # --- Performance ---
    latency_ms: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0


# Alias for compatibility with the graph builder and nodes.
AgentState = ChatState

