# Developer Guide

## Project Structure

```
ai-chatbot/
├── backend/
│   └── app/
│       ├── api/          # API layer (routers, deps)
│       ├── agents/       # LangGraph agents & nodes
│       ├── core/         # Config, security, middleware, DI
│       ├── db/           # Models, session, repositories
│       ├── llm/          # LLM providers & router
│       ├── mcp/          # FastMCP client/server
│       ├── memory/       # Memory system
│       ├── rag/          # RAG pipeline
│       ├── repositories/ # Data access
│       ├── schemas/      # Pydantic schemas
│       ├── security/     # Guardrails
│       ├── services/     # Business logic
│       ├── tools/        # Tool implementations
│       └── observability/# Telemetry
├── frontend/
│   └── src/
│       ├── components/   # UI components
│       ├── hooks/        # Custom hooks
│       ├── lib/          # API, auth, utils
│       ├── pages/        # Route pages
│       └── types/        # TypeScript types
├── docs/                 # Documentation
├── tests/                # Test suites
├── docker/               # Docker configs
├── deployment/           # K8s, CI/CD
```

## Backend Development

### Adding a New Endpoint

1. Create a schema in `app/schemas/`
2. Create a service method in `app/services/`
3. Create a repository method in `app/repositories/`
4. Add a route in `app/api/v1/endpoints/`

### Adding a New LLM Provider

1. Create a provider class in `app/llm/providers/`
2. Implement the `BaseLLMProvider` protocol
3. Register it in `app/llm/router.py`
4. Add config in `app/core/config.py`

### Adding a New Tool

1. Create a tool class in `app/tools/tools/`
2. Implement the `BaseTool` protocol
3. Register it in `app/tools/registry.py`

### Adding a New Memory Type

1. Add to `MemoryType` enum in `app/db/models.py`
2. Implement storage logic in `app/memory/`
3. Add retrieval logic in `app/agents/nodes/memory_retrieval.py`

## Frontend Development

### Adding a New Page

1. Create a component in `app/pages/`
2. Add a route in `App.tsx`
3. Add navigation as needed

### Adding a New Component

1. Create in `components/` (feature-based)
2. Add UI primitives in `components/ui/`
3. Use the `cn()` utility for class merging

### Adding a New Hook

1. Create in `hooks/`
2. Use React Query for data fetching
3. Follow the existing hook patterns

## Testing

### Backend Tests

```bash
cd backend
pytest -v
```

Tests cover: security, auth service, tools, config, and API.

### Frontend Tests

```bash
cd frontend
npm test
```

## Code Standards

### Python
- Type hints on all functions
- Docstrings on modules and functions
- Use `from __future__ import annotations`
- Follow PEP 8 (enforced by ruff)

### TypeScript
- Strict mode enabled
- Type all props and returns
- Use `interface` for objects
- Follow React hooks rules

## Git Workflow

1. Create feature branch: `git checkout -b feature/name`
2. Make changes with focused commits
3. Run tests: `make test`
4. Run linter: `make lint`
5. Create PR to `develop`
6. Merge to `main` on release

## Common Tasks

### Generate a migration
```bash
cd backend
alembic revision --autogenerate -m "add_new_table"
alembic upgrade head
```

### Dev with hot reload
```bash
make backend   # http://localhost:8000/docs
make frontend  # http://localhost:5173
```

### Run all tests
```bash
make test
```

### Build for production
```bash
make docker-up
```
