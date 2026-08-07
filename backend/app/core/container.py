"""Application wiring - builds and caches core services.

This is the composition root that wires all dependencies:
- LLM router
- Tool registry
- Memory manager
- RAG components
- LangGraph agent
- Services
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.di import container
from app.llm.router import ModelRouter
from app.tools.registry import ToolRegistry
from typing import Any


DocumentProcessorType = Any
EmbedderType = Any
HybridSearchType = Any
RerankerType = Any
RetrieverType = Any
VectorStoreType = Any

logger = logging.getLogger("app")


class AppContainer:
    """Wires all application services together lazily."""

    def __init__(self) -> None:
        self._router: ModelRouter | None = None
        self._tools: ToolRegistry | None = None
        self._vector_store: VectorStore | None = None
        self._profile_vector_store: VectorStoreType = None
        self._profile_index: Any = None
        self._embedder: Embedder | None = None
        self._retriever: Retriever | None = None
        self._processor: DocumentProcessor | None = None
        self._agent: Any = None

    # ------------------------------------------------------------------
    # Core services
    # ------------------------------------------------------------------
    @property
    def model_router(self) -> ModelRouter:
        """Return the model router."""
        if self._router is None:
            self._router = ModelRouter()
        return self._router

    @property
    def tool_registry(self) -> ToolRegistry:
        """Return the tool registry with auto-discovered tools."""
        if self._tools is None:
            self._tools = ToolRegistry()
            try:
                from app.tools.tools import (
                    AskUserTool,
                    CalculatorTool,
                    CurrentTimeTool,
                    KnowledgeBaseSearchTool,
                    PythonExecutorTool,
                    SerpApiTool,
                    WeatherTool,
                    WebSearchTool,
                    WikipediaTool,
                )

                try:
                    retriever = self.get_retriever()
                except Exception as retriever_exc:  # noqa: BLE001
                    logger.warning("Knowledge base retriever unavailable: %s", retriever_exc)
                    retriever = None

                self._tools.register_all(
                    [
                        CalculatorTool(),
                        CurrentTimeTool(),
                        WebSearchTool(),
                        WikipediaTool(),
                        WeatherTool(),
                        PythonExecutorTool(),
                        AskUserTool(),
                        KnowledgeBaseSearchTool(retriever=retriever),
                        SerpApiTool(),
                    ]
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Tool registration failed: %s", exc)
        return self._tools

    # ------------------------------------------------------------------
    # RAG services
    # ------------------------------------------------------------------
    def get_vector_store(self) -> VectorStoreType:
        """Return the vector store."""
        if self._vector_store is None:
            from app.rag.vectorstore import VectorStore

            self._vector_store = VectorStore()
        return self._vector_store

    def get_profile_vector_store(self) -> VectorStoreType:
        """Return the vector store used for global user-profile memory.

        A distinct collection from `get_vector_store()` (RAG documents) -
        different data with a different lifecycle, kept apart so a bug in
        one filter path can't leak the other's data.
        """
        if self._profile_vector_store is None:
            from app.rag.vectorstore import VectorStore

            self._profile_vector_store = VectorStore(collection="profile_memory")
        return self._profile_vector_store

    def get_profile_memory_index(self) -> Any:
        """Return the semantic index over user profile facts."""
        if self._profile_index is None:
            from app.memory.semantic import ProfileMemoryIndex

            self._profile_index = ProfileMemoryIndex(
                embedder=self.get_embedder(),
                vector_store=self.get_profile_vector_store(),
            )
        return self._profile_index

    def get_embedder(self) -> EmbedderType:
        """Return the embedder."""
        if self._embedder is None:
            from app.rag.embedder import Embedder

            self._embedder = Embedder()
        return self._embedder

    def get_document_processor(self) -> DocumentProcessorType:
        """Return the document processor."""
        if self._processor is None:
            from app.rag.document_processor import DocumentProcessor

            self._processor = DocumentProcessor()
        return self._processor

    def get_retriever(self) -> RetrieverType:
        """Return the RAG retriever."""
        if self._retriever is None:
            from app.rag.hybrid_search import HybridSearch
            from app.rag.reranker import Reranker
            from app.rag.retriever import Retriever

            self._retriever = Retriever(
                vector_store=self.get_vector_store(),
                embedder=self.get_embedder(),
                hybrid_search=HybridSearch(),
                reranker=Reranker(),
            )
        return self._retriever

    def get_agent(self) -> Any:
        """Return the LangGraph agent (lazy build)."""
        if self._agent is None:
            from app.agents.graph import AgentGraph

            try:
                retriever = self.get_retriever()
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG unavailable, building agent without retriever: %s", exc)
                retriever = None

            self._agent = AgentGraph(
                model_router=self.model_router,
                tool_registry=self.tool_registry,
                # The agent is cached for the process lifetime, so it cannot hold a
                # request-scoped MemoryManager; its nodes open their own session.
                memory_manager=None,
                retriever=retriever,
            )
        return self._agent

    # ------------------------------------------------------------------
    # Register with DI container
    # ------------------------------------------------------------------
    def register_all(self) -> None:
        """Register all services with the DI container."""
        container.register("model_router", self.model_router)
        container.register("tool_registry", self.tool_registry)


app_container = AppContainer()
