# Lumina AI — Seminar Reference Document

A complete, point-by-point technical reference for presenting this project in a seminar. Every section maps to real code in this repository — no invented features.

---

## 1. What Is This Project?

**Lumina AI** is a full-stack, production-style AI chatbot application. It is not a thin wrapper around a single LLM API call — it is an **agentic system** built with **LangGraph**, meaning every user message flows through a multi-step reasoning pipeline (validate → recall memory → detect intent → pick a tool or retrieve documents → generate → self-check → format) before a reply is sent back.

| | |
|---|---|
| **Type** | Full-stack web application (chatbot / AI assistant) |
| **Backend** | Python, FastAPI, LangGraph, LangChain |
| **Frontend** | React 19, TypeScript, Vite |
| **Database** | SQLite (default, via `aiosqlite`) — swappable to PostgreSQL |
| **Vector store** | ChromaDB / FAISS (for document retrieval / RAG) |
| **Architecture style** | Clean Architecture (API → Services → Repositories → DB) |

---

## 2. High-Level Architecture

```
┌──────────────────────────┐        HTTPS / SSE        ┌──────────────────────────────┐
│        FRONTEND          │ ─────────────────────────▶ │           BACKEND             │
│  React 19 + TypeScript   │ ◀───────────────────────── │  FastAPI + LangGraph Agent    │
│  Vite, TailwindCSS       │      JSON / streamed        │                                │
└──────────────────────────┘        tokens               └──────────────────────────────┘
                                                                     │
                     ┌───────────────────────────────────────────────┼───────────────────────────┐
                     ▼                                               ▼                             ▼
            ┌──────────────────┐                          ┌──────────────────┐         ┌──────────────────────┐
            │   SQL Database    │                          │   Vector Store    │         │   LLM Providers        │
            │ (SQLite/Postgres) │                          │ (Chroma / FAISS)  │         │ OpenAI / Gemini / Groq │
            │ users, threads,   │                          │ document chunks   │         │ / OpenRouter            │
            │ messages, memory  │                          │ + embeddings      │         │                        │
            └──────────────────┘                          └──────────────────┘         └──────────────────────┘
```

**Request lifecycle in one sentence:** the browser sends a message over REST/SSE → FastAPI authenticates the request → the message is handed to a `LangGraph` state machine ("the agent") → the agent reads memory, decides if a tool or document lookup is needed, calls an LLM provider, checks its own answer, and streams the final text back to the browser token-by-token.

---

## 3. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend framework | React 19 + TypeScript | Type safety, latest React concurrent features |
| Build tool | Vite | Fast dev server, instant HMR |
| Styling | TailwindCSS + ShadCN UI (Radix primitives) | Accessible, themeable components without a heavy design system |
| State/data-fetching | TanStack React Query | Caching, background refetching, optimistic UI |
| Routing | React Router v7 | Client-side navigation (`/chat/:threadId`, `/login`, etc.) |
| Backend framework | FastAPI (Python, async) | High-performance async API, automatic OpenAPI docs |
| Agent orchestration | LangGraph | Graph-based, stateful, controllable agent execution (vs. a single opaque LLM call) |
| LLM integration | LangChain + native provider SDKs | Unified interface across multiple LLM vendors |
| ORM | SQLAlchemy 2.0 (async) | Async database access with a synchronous-feeling API |
| Database | SQLite (default) / PostgreSQL (production option) | SQLite for zero-config local dev; Postgres for scale |
| Migrations | Alembic | Versioned schema changes |
| Vector DB | ChromaDB / FAISS | Embedding storage + similarity search for RAG |
| Auth | JWT (access + refresh tokens), OAuth2 (Google/GitHub), bcrypt | Stateless, standard auth |
| Streaming transport | Server-Sent Events (SSE) | Token-by-token assistant replies without WebSocket complexity |
| Observability | LangSmith, OpenTelemetry, structured logging | Trace every agent run, debug production issues |
| Testing (E2E) | Playwright | Real-browser verification of user flows |

---

## 4. The LangGraph Agent — The Core of the System

This is the most important concept to explain in the seminar: **the chatbot is not "prompt in → LLM → answer out."** It is a directed graph of nodes, where each node has one job, and edges (some conditional) decide the path a message takes.

### 4.1 The Graph (`backend/app/agents/graph.py`)

```
START
  │
  ▼
input_validation ──(needs clarification)──▶ END (ask user)
  │
  ▼
context_builder
  │
  ▼
memory_retrieval           ← pulls the user's GLOBAL memory (see §5)
  │
  ▼
intent_detection
  │
  ├──(intent = "rag")────────────▶ rag_retrieval ──┐
  ├──(intent = "tool"/"calc"/     tool_selection ──┤
  │   "ask_user")                                  │
  └──(intent = other)─────────────────────────────▶│
                                                     ▼
                                                  llm_node ◀────────────┐
                                                     │                   │
                                                     ▼                   │ (answer failed
                                                 reflection ──(retry)───┘  quality check,
                                                     │                     up to 2 retries)
                                                     ▼
                                             answer_validation ──(retry)──▶ llm_node
                                                     │
                                                     ▼
                                                 formatting
                                                     │
                                                     ▼
                                                    END
```

### 4.2 What Each Node Does

| Node | File | Responsibility |
|---|---|---|
| `input_validation` | `nodes/input_validation.py` | Rejects empty/malformed input, flags messages that need clarification |
| `context_builder` | `nodes/context_builder.py` | Assembles conversation history + system context for this turn |
| `memory_retrieval` | `nodes/memory_retrieval.py` | Fetches the user's **global** long-term memory (name, preferences, facts) — not scoped to the current thread |
| `intent_detection` | `nodes/intent_detection.py` | Regex/heuristic classification: is this a tool request, a document question (RAG), a calculation, or plain conversation? |
| `tool_selection` | `nodes/tool_selection.py` | Picks and invokes the right tool (weather, calculator, search, etc.) |
| `rag_retrieval` | `nodes/rag_retrieval.py` | Runs the retrieval-augmented-generation pipeline against uploaded documents |
| `llm_node` | `nodes/llm_node.py` | Calls the selected LLM provider (with fallback chain) to generate a reply |
| `reflection` | `nodes/reflection.py` | The agent **critiques its own draft answer** and can loop back to regenerate it |
| `answer_validation` | `nodes/answer_validation.py` | Final correctness/safety check before the answer is allowed out |
| `formatting` | `nodes/formatting.py` | Cleans up markdown/formatting for the frontend renderer |

**Key seminar talking point:** the `reflection` → `llm_node` loop and `answer_validation` → `llm_node` loop mean the agent can **retry its own answer up to `max_retries` (2) times** if it judges its first attempt low-quality — this is self-correction, not just generation.

### 4.3 Why a Graph Instead of One Big Prompt?

- **Determinism & control** — routing decisions (which tool, which retry) are explicit code, not hidden inside one giant prompt.
- **Debuggability** — LangSmith traces show exactly which node ran, in what order, with what state.
- **Extensibility** — adding a new capability (e.g. a new tool) means adding a node/edge, not rewriting a monolithic prompt.
- **Fallback safety** — if the LLM's first answer is bad, the graph can retry instead of shipping a bad response.

---

## 5. Memory System — Global, Cross-Thread User Memory

This is a standout feature worth demonstrating live: **information a user shares in one conversation is remembered in every other conversation they start**, not just within a single chat thread.

### 5.1 Memory Types (`backend/app/db/models.py` → `MemoryType` enum)

| Type | Purpose |
|---|---|
| `SHORT_TERM` | Transient, expires after a TTL |
| `LONG_TERM` | Persistent facts about the user |
| `CONVERSATION` | Context tied to a specific thread |
| `SUMMARIZATION` | Rolling summary of long conversations (keeps prompts small) |
| `ENTITY` | Structured facts — e.g. `name: Abdul`, `age: 23` |
| `SEMANTIC` | Embedding-searchable knowledge |
| `USER_PREFERENCE` | Likes/dislikes, style preferences |
| `THREAD` | Thread-scoped metadata |

### 5.2 How "Global" Memory Actually Works

1. **Extraction** (`backend/app/memory/extraction.py`) — after every user message, a fast, regex-based heuristic parser scans the text for self-disclosure patterns:
   - `"my name is X"`, `"call me X"`, `"I'm X"` (guarded by a stopword list so `"I'm tired"` isn't mistaken for a name)
   - `"my age is 23"`, `"I'm 23 years old"`
   - Location (`"I live in..."`), occupation (`"I work as..."`), preferences (`"I love/like/hate..."`)
   - Deliberately **not** an LLM call — keeps extraction free and adds no latency per message.
2. **Storage** (`backend/app/memory/manager.py`) — extracted facts are written as `ENTITY`/`USER_PREFERENCE` rows in the `Memory` table, keyed by **`user_id`**, not `thread_id`.
3. **Retrieval** — `MemoryManager.retrieve_for_context()` queries memory **by `user_id`**, so *every* thread the user opens pulls the same global fact set into the system prompt via `memory_retrieval` node (§4.2).

**Result:** tell the bot "I'm Abdul and my age is 23" in Chat A → start a brand-new Chat B → ask "what's my name and age?" → the bot answers correctly, because retrieval is user-scoped, not thread-scoped.

### 5.3 Why This Matters (Seminar Point)

Most tutorial chatbots only remember within a single conversation (or not at all). Building **cross-session, per-user persistent memory** is what makes an assistant feel like it "knows you" — this is the same category of feature found in commercial products like ChatGPT's "Memory."

---

## 6. Retrieval-Augmented Generation (RAG) Pipeline

Lets users upload documents and ask questions grounded in their own content.

| Stage | File | What it does |
|---|---|---|
| Document processing | `rag/document_processor.py` | Parses PDF, DOCX, XLSX, CSV, TXT into text, chunks it |
| Embedding | `rag/embedder.py` | Converts text chunks into vector embeddings |
| Storage | `rag/vectorstore.py` | Persists vectors in ChromaDB/FAISS |
| Hybrid search | `rag/hybrid_search.py` | Combines keyword (BM25) + vector similarity search |
| Reranking | `rag/reranker.py` | Re-orders retrieved chunks by relevance before they hit the prompt |
| Retrieval | `rag/retriever.py` | Orchestrates the full retrieve → rerank → return-with-citations flow |

**Flow:** user uploads a file → it's processed, chunked, embedded, and indexed → user asks a question → `intent_detection` classifies it as `"rag"` → `rag_retrieval` node fetches the most relevant chunks → those chunks are injected into the LLM prompt as grounding context, with citations back to source documents.

---

## 7. Tool Calling

The agent can reach outside the LLM to fetch live or computed information (`backend/app/tools/tools/`):

| Tool | Purpose |
|---|---|
| `calculator.py` | Safe arithmetic/math expression evaluation |
| `weather.py` | Live weather lookup |
| `time_tool.py` | Current date/time |
| `wikipedia_tool.py` | Wikipedia summaries |
| `web_search.py` / `serp_search.py` | Live web search (SerpAPI-backed) |
| `knowledge_base.py` | Search the user's uploaded documents |
| `python_executor.py` | Sandboxed Python execution |
| `ask_user.py` | Lets the agent pause and ask a clarifying question instead of guessing |

Tools are registered in a central `ToolRegistry` (`tools/registry.py`) and selected dynamically by the `tool_selection` node based on detected intent — the LLM isn't blindly given every tool on every call.

**MCP (Model Context Protocol)** support (`backend/app/mcp/`) also lets the app act as an MCP client/server for dynamic, external tool discovery beyond the built-in set.

---

## 8. Multi-Provider LLM Routing

`backend/app/llm/router.py` + `llm/providers/` — the app is not locked to one AI vendor:

- **Supported providers:** OpenAI (GPT-4o), Google Gemini, Groq (fast Llama inference), OpenRouter
- **Fallback chain:** if the primary provider fails or rate-limits, the router automatically falls back through a configured chain (`FALLBACK_MODELS=groq,gemini,openrouter,openai`)
- **Dynamic switching:** users can pick a model per-message from the frontend model selector

**Why this matters:** resilience (no single point of failure on one vendor's uptime) and cost/latency flexibility (route cheap/fast models for simple queries, powerful models for complex ones).

---

## 9. Streaming Responses (SSE)

- Backend: `POST /api/v1/chat/stream` opens a Server-Sent Events connection and streams events as the LangGraph executes: `start`, `token` (partial text), `tool_call` (shows "Searching the web...", etc.), `message`, `done`, `error`.
- Frontend: `frontend/src/hooks/use-messages.ts` consumes the stream and updates the UI token-by-token, so replies appear to "type" in real time rather than waiting for the full response.
- **Important detail:** each `token` event carries the **full generation so far**, not a delta — because later graph nodes (`reflection`, `formatting`) can rewrite the answer wholesale, not just append to it.

---

## 10. Authentication & Security

| Feature | Implementation |
|---|---|
| Password auth | bcrypt-hashed passwords |
| Session tokens | JWT access token (short-lived) + refresh token (long-lived) |
| OAuth | Google / GitHub social login (`authlib`) |
| Password reset | Forgot-password / reset-password flow |
| Prompt injection protection | `backend/app/security/guardrails.py` |
| Route protection | `ProtectedRoute` component (frontend) + JWT dependency injection (backend, `api/deps.py`) |

---

## 11. Database Schema

`backend/app/db/models.py` — SQLAlchemy 2.0 async ORM, 9 core tables:

| Table | Purpose |
|---|---|
| `User` | Account info, role, auth provider |
| `Thread` | A conversation ("chat"); has status (active/archived), pin state |
| `Message` | Individual messages (role: user/assistant/system), belongs to a Thread |
| `Memory` | The global memory store described in §5 — keyed by `user_id` |
| `Document` | Uploaded files for RAG |
| `Embedding` | Vector embeddings tied to document chunks |
| `Feedback` | Thumbs up/down on assistant messages |
| `UserSetting` | Per-user preferences (theme, default model, etc.) |
| `Log` | Structured application logs |
| `File` | Generic file upload metadata |

Default database is **SQLite** (`sqlite+aiosqlite:///./ai_chatbot.db`) for zero-config local development; swapping `DATABASE_URL` to a `postgresql://` connection string moves it to PostgreSQL for production without code changes (SQLAlchemy abstracts the dialect).

---

## 12. REST API Surface

All endpoints are versioned under `/api/v1` (`backend/app/api/v1/router.py`):

| Group | Endpoints |
|---|---|
| **Auth** | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| **Users** | `GET /users/me`, `PATCH /users/me`, `GET/PATCH /users/me/settings` |
| **Threads** | `POST /threads`, `GET /threads`, `GET /threads/{id}`, `PATCH /threads/{id}`, `DELETE /threads/{id}`, `POST /threads/{id}/archive`, `POST /threads/{id}/pin`, `GET /threads/{id}/messages` |
| **Chat** | `POST /chat/messages` (non-streaming), `POST /chat/stream` (SSE streaming) |
| **Models** | `GET /models`, `GET /models/providers` |
| **Memory** | `GET /memories`, `POST /memories`, `DELETE /memories/{id}`, `DELETE /memories` (clear all), `GET /memories/context` |
| **Files** | `POST /files/upload`, `POST /files/documents`, `GET /files/documents`, `DELETE /files/documents/{id}` |

FastAPI auto-generates interactive OpenAPI/Swagger docs at `/docs` — useful to show live during a demo.

---

## 13. Frontend Structure

```
frontend/src/
├── pages/            # chat, login, register, forgot-password, settings, profile
├── components/
│   ├── chat/          # MessageList, MessageItem, ChatInput, markdown/code rendering
│   ├── sidebar/        # Thread list, New Chat, search, pin/delete
│   ├── layout/          # App shell
│   └── ui/               # ShadCN primitives (button, input, dialog, etc.)
├── hooks/             # use-messages (streaming + query), use-threads, use-auth
├── lib/               # API client, utils
└── types/             # Shared TypeScript types
```

**Key UX behaviors:**
- Optimistic UI: the user's message and an assistant placeholder appear instantly, before the network round-trip completes.
- Live "thinking" indicator with tool-specific labels ("Searching the web...", "Checking the weather...") while a tool call is in flight.
- Thread sidebar with pin, rename, delete, and search.
- Markdown rendering with syntax-highlighted code blocks and KaTeX math rendering.

---

## 14. Deployment & Ops

- **Docker Compose** for one-command local orchestration (`docker-compose up --build`)
- **Alembic** migrations for schema versioning
- **GitHub Actions** CI/CD (`deployment/`)
- **Observability:** structured logs, OpenTelemetry tracing, LangSmith tracing of every agent graph run (`LANGCHAIN_TRACING_V2=true`)

---

## 15. Suggested Live Demo Flow (for the seminar)

1. **Register/login** → show JWT-based auth working.
2. **Start a chat, ask a general question** → show streaming tokens appear live.
3. **Ask a tool-triggering question** ("what's the weather in Hyderabad?") → show the "Checking the weather..." indicator and a live-data answer, proving tool calling works.
4. **Introduce yourself** ("I'm Abdul, I'm 23, I live in Hyderabad") in one chat, then **open a brand-new chat** and ask "what do you know about me?" → demonstrates **global cross-thread memory** — the standout architectural feature.
5. **Upload a document** and ask a question about its contents → demonstrates the **RAG pipeline** with citations.
6. **Open `/docs`** (FastAPI Swagger UI) → show the full API surface and the clean, versioned REST design.
7. **(Optional) Show a LangSmith trace** of one of the above requests → visually walk through the LangGraph node-by-node execution for the audience.

---

## 16. One-Slide Summary

> **Lumina AI** is a full-stack AI chatbot that goes beyond a simple LLM wrapper: it routes every message through a **LangGraph agent** (validate → recall global memory → detect intent → call tools/RAG → generate → self-reflect → validate → format), supports **multiple LLM providers with automatic fallback**, gives users **persistent, cross-conversation memory**, and grounds answers in **uploaded documents via RAG** — all behind a real-time streaming React UI with full JWT/OAuth authentication.
