# Architecture

## Overview

The AI Chatbot is built using Clean Architecture with strict separation of concerns across layers. Each layer is independent and communicates through well-defined interfaces.

## Layer Diagram

```
┌─────────────────────────────────────────────┐
│           Presentation Layer (React)         │
│          UI Components, Pages, Hooks          │
└──────────────────┬──────────────────────────┘
                   │ HTTP / JSON / SSE
┌──────────────────▼──────────────────────────┐
│              API Layer (FastAPI)             │
│      Routes, Middleware, Validation, Auth     │
└──────────────────┬──────────────────────────┘
                   │ Service Calls
┌──────────────────▼──────────────────────────┐
│              Graph Layer (LangGraph)         │
│          StateGraph, Nodes, Edges             │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             Agents (LangGraph)               │
│   Intent, Routing, Tool Selection, LLM       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Tools (MCP)                    │
│  Calculator, Search, Weather, Python, etc.   │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Memory System                  │
│  Short-term, Long-term, Semantic, Entity     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             Database (PostgreSQL)            │
│      Users, Threads, Messages, Memory        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               LLM Providers                  │
│     OpenAI, Gemini, Groq, OpenRouter          │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             External APIs                    │
│       Web Search, Weather, Wikipedia         │
└─────────────────────────────────────────────┘
```

## Clean Architecture Layers

### 1. Presentation Layer
- React 19 + TypeScript SPA
- Components organized by feature
- Custom hooks for state management
- React Query for server state
- Framer Motion for animations

### 2. API Layer
- FastAPI with versioned routes (`/api/v1`)
- Pydantic schemas for validation
- JWT authentication middleware
- Rate limiting, request/response logging
- Streaming responses via SSE

### 3. Graph Layer
- LangGraph StateGraph
- Nodes: validation, context, memory, intent, routing, LLM, reflection, answer validation, formatting
- Conditional edges, loops, retries, fallbacks
- Checkpointing for state persistence

### 4. Agents
- Intent detection node
- Route decision node
- Tool selection node
- LLM node with multi-provider support

### 5. Tools
- Protocol-based tool interface
- Registry for dynamic tool discovery
- FastMCP integration
- Built-in tools: calculator, search, weather, Python, knowledge base

### 6. Memory
- Multiple memory types via abstraction
- Short-term, long-term, conversation, semantic, entity, user-preference
- Memory compression and summarization

### 7. Database
- PostgreSQL via SQLAlchemy async
- Repository pattern for data access
- Alembic migrations
- 11 core tables

### 8. LLM Providers
- Provider abstraction layer
- OpenAI, Gemini, Groq, OpenRouter
- Dynamic model switching via configuration
- Fallback chain with automatic retry

### 9. External APIs
- Web search, Weather, Wikipedia, Python execution
- Async HTTP clients
- Rate-limit aware

## SOLID Principles

- **S**ingle Responsibility: Each module has one purpose
- **O**pen/Closed: Extensible via interfaces and DI
- **L**iskov: Derived types are substitutable
- **I**nterface Segregation: Focused interfaces
- **D**ependency Inversion: High-level depends on abstractions

## Dependency Injection

- Central `Container` class manages service lifetimes
- Constructor injection for services
- Protocol typing for testability
- Lazy initialization for performance

## Data Flow

1. User sends message via React
2. API validates and authenticates
3. LangGraph starts pipeline
4. Memory retrieved and context built
5. Intent detected and route selected
6. Tools invoked if needed
7. LLM generates response
8. Reflection validates quality
9. Answer validated and formatted
10. Response streamed back to client
