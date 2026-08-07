# Sequence Diagrams

## 1. Chat Message Flow (Streaming)

```
User         Frontend         Backend API         LangGraph       LLM Provider
 │              │                  │                  │               │
 │  Send msg    │                  │                  │               │
 │─────────────>│                  │                  │               │
 │              │  POST /chat      │                  │               │
 │              │─────────────────>│                  │               │
 │              │                  │  Start graph     │               │
 │              │                  │─────────────────>│               │
 │              │                  │                  │  Validate     │
 │              │                  │                  │  Build context│
 │              │                  │                  │  Retrieve mem │
 │              │                  │                  │  Detect intent│
 │              │                  │                  │  Route        │
 │              │                  │                  │  Select tools │
 │              │                  │                  │  Call LLM     │
 │              │                  │                  │──────────────>│
 │              │                  │                  │               │
 │              │                  │   SSE stream     │◄──────────────│
 │  token       │                  │◄─────────────────│  tokens        │
 │◄─────────────│                  │                  │               │
 │  token       │                  │                  │               │
 │◄─────────────│                  │                  │               │
 │  ...         │                  │                  │  Reflect      │
 │              │                  │                  │  Validate     │
 │              │                  │                  │  Format       │
 │              │                  │  done event      │               │
 │              │                  │◄─────────────────│               │
 │  complete    │                  │                  │               │
 │◄─────────────│                  │                  │               │
```

## 2. Authentication Flow (JWT)

```
User         Frontend         Backend API         AuthService         DB
 │              │                  │                  │               │
 │  Login       │                  │                  │               │
 │─────────────>│                  │                  │               │
 │              │  POST /auth/login│                  │               │
 │              │─────────────────>│                  │               │
 │              │                  │  verify creds    │               │
 │              │                  │─────────────────>│               │
 │              │                  │                  │  query user   │
 │              │                  │                  │──────────────>│
 │              │                  │                  │  user         │
 │              │                  │                  │◄──────────────│
 │              │                  │  verify password │               │
 │              │                  │  issue JWT       │               │
 │              │                  │◄─────────────────│               │
 │              │  tokens          │                  │               │
 │              │◄─────────────────│                  │               │
 │  store tokens│                  │                  │               │
 │  navigate    │                  │                  │               │
```

## 3. RAG Pipeline Flow

```
User         API Layer        Document        Embedder        VectorDB        LLM
 │              │              Processor        │               │              │
 │  upload      │              │                │               │              │
 │─────────────>│              │                │               │              │
 │              │  save file   │                │               │              │
 │              │─────────────>│                │               │              │
 │              │              │  extract text  │               │              │
 │              │              │───────────────>│               │              │
 │              │              │                │  embed chunks │              │
 │              │              │                │──────────────>│              │
 │              │              │                │  store        │              │
 │              │              │                │──────────────>│              │
 │              │              │                │               │              │
 │  query       │              │                │               │              │
 │─────────────>│              │                │               │              │
 │              │  retrieve    │                │               │              │
 │              │─────────────>│                │               │              │
 │              │  query vector│                │               │              │
 │              │──────────────────────────────────────────────>│              │
 │              │  results     │                │               │              │
 │              │◄──────────────────────────────────────────────│              │
 │              │  rerank      │                │               │              │
 │              │  build prompt│                │               │              │
 │              │─────────────>│                │               │              │
 │              │  call LLM    │                │               │              │
 │              │───────────────────────────────────────────────>│              │
 │              │  answer+cites│                │               │              │
 │              │◄───────────────────────────────────────────────│              │
 │  answer      │              │                │               │              │
 │◄─────────────│              │                │               │              │
```

## 4. Fallback Model Switching

```
LLM Node          Primary          Fallback          Offline
                  Provider         Provider          Provider
 │                    │                │                │
 │  call             │                │                │
 │───────────────────>│                │                │
 │  error/timeout    │                │                │
 │◄───────────────────│                │                │
 │  call fallback    │                │                │
 │────────────────────────────────────>│                │
 │  response         │                │                │
 │◄────────────────────────────────────│                │
 │                                    │                │
 │  (if fallback fails)               │                │
 │  call offline     │                │                │
 │────────────────────────────────────────────────────>│
 │  response         │                │                │
 │◄────────────────────────────────────────────────────│
```

## 5. Memory Retrieval

```
Agent           Memory Manager     Short-Term       Long-Term      Semantic
 │                    │                │                │             │
 │  retrieve         │                │                │             │
 │───────────────────>│                │                │             │
 │                    │  get short-term│                │             │
 │                    │───────────────>│                │             │
 │                    │  short-term    │                │             │
 │                    │◄───────────────│                │             │
 │                    │  get long-term │                │             │
 │                    │───────────────────────────────>│             │
 │                    │  long-term     │                │             │
 │                    │◄───────────────────────────────│             │
 │                    │  semantic search               │             │
 │                    │────────────────────────────────────────────>│
 │                    │  semantic results              │             │
 │                    │◄────────────────────────────────────────────│
 │                    │  merge by importance           │             │
 │  combined memory   │                │                │             │
 │◄───────────────────│                │                │             │
```
