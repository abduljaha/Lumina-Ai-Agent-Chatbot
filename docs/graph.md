# LangGraph Agent Graph

## Flow Diagram

```
┌─────┐
│START│
└──┬──┘
   │
   ▼
┌─────────────────┐
│Input Validation │
└──┬──────────┬───┘
   │          │ needs_user_input
   │          ▼
   │     ┌──────────┐
   │     │ask_user  │──────┐
   │     └──────────┘      │ (interrupt)
   │                       ▼
   ▼
┌─────────────────┐
│ Context Builder │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Memory Retrieval │
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ Intent Detection │
└────────┬─────────┘
         │
         ▼
┌─────────────────┐
│ Route Decision  │
└──┬──────────┬───┘
   │rag       │tool
   ▼          ▼
┌────────┐ ┌─────────────┐
│RAG     │ │Tool         │
│Retrieval│ │Selection    │
└───┬────┘ └──────┬──────┘
    │             │
    │      ┌──────┘
    │      ▼
    │  ┌─────────┐
    │  │Execute  │
    │  │Tools    │
    │  └────┬────┘
    │       │
    ▼       │
┌───────────▼──┐     ┌─────────┐
│   LLM Node   │────>│Reflection│
└────────┬─────┘     └────┬────┘
         │                │ not pass & retries remain
         │                ▼ (loop back to LLM)
         │            ┌─────────────────┐
         │            │Answer Validation│
         │            └────────┬────────┘
         │                     │ not valid & retries remain
         │                     ▼ (loop back to LLM)
         ▼                     │
┌─────────────────┐            │
│   Formatting    │◄───────────┘
└────────┬────────┘
         │
         ▼
┌─────┐
│ END │
└─────┘
```

## Node Details

### input_validation
- Validates user input
- Checks for empty/too long messages
- Runs guardrails (prompt injection, jailbreak detection)
- Sets `needs_user_input` flag if clarification needed

### context_builder
- Assembles conversation context
- Loads thread history
- Prepares system prompt

### memory_retrieval
- Retrieves relevant memories
- Combines short-term, long-term, and semantic memories
- Scores by importance and relevance

### intent_detection
- Classifies user intent
- Detects: general, rag, tool, computation, code, etc.
- Sets `current_intent`

### route_decision
- Routes based on intent
- Determine whether to use tools, RAG, or direct LLM

### tool_selection
- Selects relevant tools based on intent
- Executes tool calls
- Handles ask_user tool for missing info

### llm_node
- Calls the configured LLM provider
- Supports multi-provider fallback
- Streams tokens when enabled

### reflection
- Evaluates response quality
- Checks for hallucinations, relevance
- Sets `reflection_pass` flag

### answer_validation
- Validates answer correctness
- Checks against retrieved context
- Sets `answer_valid` flag

### formatting
- Formats final response
- Adds citations if RAG used
- Applies markdown/latex formatting

## Conditional Edges

1. **After validation**: → context_builder | ask_user
2. **After route decision**: → rag_retrieval | tool_selection | llm_node
3. **After reflection**: → llm_node (retry) | answer_validation
4. **After answer validation**: → llm_node (retry) | formatting

## State

The graph uses a typed `AgentState` with:
- user, session, thread
- messages, history
- retrieved_documents, context
- current_intent, selected_tool
- current_model
- metadata, error_state, retry_count

## Checkpointing

- Uses `MemorySaver` (prod: Postgres/Redis saver)
- State persisted per thread via `configurable.thread_id`
- Enables resume and interrupt support

## Streaming

- `stream_mode="messages"` for token-level streaming
- SSE events for frontend consumption
- Supports cancel via `POST /chat/stop`
