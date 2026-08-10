"""LangGraph agent graph assembly.

Builds the stateful agent graph with:
- START -> Input Validation -> Context Builder -> Memory Retrieval -> RAG
  Retrieval (unconditional, when configured) -> Intent Detection
- -> Tool Selection (weather/calculator/search/knowledge-base/etc.) -> LLM
- -> Reflection -> Answer Validation -> Formatting -> END
- Conditional edges, loops, retries, fallbacks, streaming, checkpointing.
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    answer_validation,
    context_builder,
    formatting,
    input_validation,
    intent_detection,
    llm_node,
    memory_retrieval,
    rag_retrieval,
    reflection,
    tool_selection,
)
from app.agents.state import AgentState


def route_after_validation(state: AgentState) -> str:
    """Route to context builder or ask user after validation."""
    if state.get("needs_user_input"):
        return "ask_user"
    return "context_builder"


def route_after_intent(state: AgentState) -> str:
    """Route to tool selection or straight to the LLM based on detected intent.

    RAG retrieval is no longer gated behind an explicit "search my
    documents"-style intent match - it runs unconditionally for every
    message (see _build), the same way memory_retrieval does, so uploaded
    documents are available for ordinary questions about their content
    without the user having to name the lookup. "rag" intent (an explicit
    KB-phrase match) still reaches tool_selection so its dedicated
    knowledge_base_search tool call still happens too.
    """
    intent = state.get("intent", "unknown")
    # "ask_user" must also reach tool_selection - that's the node that knows
    # how to turn the ask_user intent into a needs_user_input response;
    # without it here, ask_user intents fell straight through to llm_node
    # and the clarifying-question behavior was never reachable.
    if intent in ("tool", "computation", "calculation", "ask_user", "rag"):
        return "tool_selection"
    return "llm_node"


def route_after_tool(state: AgentState) -> str:
    """Route after tool selection: ask user or proceed to LLM."""
    if state.get("needs_user_input"):
        return "ask_user"
    return "llm_node"


def route_after_reflection(state: AgentState) -> str:
    """Loop back to LLM if reflection fails quality check, up to max retries."""
    retry_count = state.get("retry_count", 0)
    if not state.get("is_valid_answer", True) and retry_count < state.get("max_retries", 2):
        return "llm_node"
    return "answer_validation"


def route_after_validation_fallback(state: AgentState) -> str:
    """If answer validation fails and retries remain, re-run the LLM."""
    retry_count = state.get("retry_count", 0)
    if not state.get("is_valid_answer", True) and retry_count < state.get("max_retries", 2):
        return "llm_node"
    return "formatting"


class AgentGraph:
    """High-level agent graph wrapper.

    Provides the `invoke` and `stream` interface expected by the chat
    service and application container. Internally assembles and compiles
    the LangGraph StateGraph.
    """

    def __init__(
        self,
        model_router: Any,
        tool_registry: Any,
        memory_manager: Any,
        retriever: Any = None,
        reranker: Any = None,
        guardrails: Any = None,
        checkpointer: Any = None,
        tool_executor: Any = None,
    ) -> None:
        self.model_router = model_router
        self.memory_manager = memory_manager
        self.tool_registry = tool_registry
        self.reranker = reranker
        self.retriever = retriever
        self.guardrails = guardrails
        self.checkpointer = checkpointer or MemorySaver()
        # Shared by both tool-calling paths (regex fast-path and native
        # function-calling) so timeouts/retry/fallback/caching/rate-limiting
        # behave identically regardless of which one triggered a tool -
        # falls back to building one locally (e.g. for tests that construct
        # AgentGraph without going through the DI container).
        if tool_executor is None:
            from app.tools.executor import ToolExecutor

            tool_executor = ToolExecutor(tool_registry)
        self.tool_executor = tool_executor
        self.graph = self._build()

    def _build(self) -> Any:
        """Construct the StateGraph with all nodes and edges."""
        workflow = StateGraph(AgentState)

        # Instantiate the node objects (each node module defines a class).
        input_validation_node = input_validation.InputValidationNode()
        context_builder_node = context_builder.ContextBuilderNode()
        memory_retrieval_node = memory_retrieval.MemoryRetrievalNode(self.memory_manager)
        intent_detection_node = intent_detection.IntentDetectionNode()
        tool_selection_node = tool_selection.ToolSelectionNode(self.tool_registry, tool_executor=self.tool_executor)
        llm_node_instance = llm_node.LLMNode(
            self.model_router, tool_registry=self.tool_registry, tool_executor=self.tool_executor
        )
        reflection_node = reflection.ReflectionNode()
        answer_validation_node = answer_validation.AnswerValidationNode()
        formatting_node = formatting.FormattingNode()

        # Add nodes
        workflow.add_node("input_validation", input_validation_node)
        workflow.add_node("context_builder", context_builder_node)
        workflow.add_node("memory_retrieval", memory_retrieval_node)
        workflow.add_node("intent_detection", intent_detection_node)
        workflow.add_node("tool_selection", tool_selection_node)
        workflow.add_node("llm_node", llm_node_instance)
        workflow.add_node("reflection", reflection_node)
        workflow.add_node("answer_validation", answer_validation_node)
        workflow.add_node("formatting", formatting_node)

        # RAG node (optional)
        has_rag = self.retriever is not None
        if has_rag:
            workflow.add_node("rag_retrieval", rag_retrieval.RAGRetrievalNode(self.retriever))

        # Add edges
        workflow.add_edge(START, "input_validation")

        workflow.add_conditional_edges(
            "input_validation",
            route_after_validation,
            {
                "context_builder": "context_builder",
                "ask_user": END,
            },
        )

        workflow.add_edge("context_builder", "memory_retrieval")
        # RAG retrieval runs unconditionally for every message when a
        # retriever is configured (like memory_retrieval), not just when
        # intent_detection spots an explicit "search my documents" phrase -
        # otherwise a plain question about an uploaded file's content never
        # reaches the knowledge base at all.
        if has_rag:
            workflow.add_edge("memory_retrieval", "rag_retrieval")
            workflow.add_edge("rag_retrieval", "intent_detection")
        else:
            workflow.add_edge("memory_retrieval", "intent_detection")

        workflow.add_conditional_edges(
            "intent_detection",
            route_after_intent,
            {
                "tool_selection": "tool_selection",
                "llm_node": "llm_node",
            },
        )

        workflow.add_conditional_edges(
            "tool_selection",
            route_after_tool,
            {
                "llm_node": "llm_node",
                "ask_user": END,
            },
        )

        workflow.add_edge("llm_node", "reflection")

        workflow.add_conditional_edges(
            "reflection",
            route_after_reflection,
            {
                "llm_node": "llm_node",
                "answer_validation": "answer_validation",
            },
        )

        workflow.add_conditional_edges(
            "answer_validation",
            route_after_validation_fallback,
            {
                "llm_node": "llm_node",
                "formatting": "formatting",
            },
        )

        workflow.add_edge("formatting", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke the agent graph and return the final state."""
        cfg = config or {"configurable": {"thread_id": state.get("thread_id", "default")}}
        return await self.graph.ainvoke(state, config=cfg)

    async def stream(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> Any:
        """Stream the agent graph execution, yielding node updates.

        This is an async generator; callers should use:
            async for event in self._graph.stream(state):
        """
        cfg = config or {"configurable": {"thread_id": state.get("thread_id", "default")}}
        async for chunk in self.graph.astream(state, config=cfg, stream_mode="updates"):
            yield chunk


def build_agent_graph(
    model_router: Any,
    tool_registry: Any,
    memory_manager: Any,
    retriever: Any = None,
    reranker: Any = None,
    guardrails: Any = None,
) -> AgentGraph:
    """Factory function for building the agent graph."""
    return AgentGraph(
        model_router=model_router,
        tool_registry=tool_registry,
        memory_manager=memory_manager,
        retriever=retriever,
reranker=reranker,
        guardrails=guardrails,
    )
