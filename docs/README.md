# AI Chatbot Documentation

Welcome to the AI Chatbot documentation. This is an enterprise-grade, production-ready AI chatbot application

## Table of Contents

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System architecture and Clean Architecture layers |
| [Graph](graph.md) | LangGraph agent graph and node flow |
| [API](api.md) | REST API reference |
| [Database](database.md) | Database schema and ERD |
| [Sequence Diagrams](sequence.md) | Message, auth, RAG, fallback, memory flows |
| [Flowcharts](flowcharts.md) | Application and orchestration flowcharts |
| [Installation](installation.md) | Setup and installation guide |
| [Deployment](deployment.md) | Deployment guide (Docker, K8s, manual) |
| [Developer Guide](developer.md) | Development guide and code standards |

## Quick Start

```bash
# 1. Copy environment config
cp .env.example .env

# 2. Run with Docker
docker-compose up --build

# Backend: http://localhost:8000/docs
# Frontend: http://localhost:5173
```

## Project Structure

```
ai-chatbot/
├── backend/          # FastAPI + LangGraph backend
├── frontend/         # React 19 + TypeScript frontend
├── docs/             # Documentation
├── tests/            # Test suites
├── scripts/          # Utility scripts
├── docker/           # Docker configuration
├── deployment/       # Kubernetes & CI/CD
├── config/           # Configuration files
├── database/         # DB migrations & seeds
├── migrations/       # Alembic migrations
├── logs/             # Log output
├── uploads/          # Uploaded files
└── assets/           # Static assets
```

## Key Features

- **Multi-Provider LLM**: OpenAI, Gemini, Groq, OpenRouter with dynamic switching
- **LangGraph Agent**: Full state machine with validation, memory, routing, reflection
- **RAG Pipeline**: Chunking, hybrid search, reranking, citations
- **Memory System**: Short-term, long-term, semantic, entity, user-preference
- **FastMCP**: MCP client & server integration
- **Streaming**: Token-by-token SSE responses
- **Multimodal**: Text, images, audio, documents, OCR, STT/TTS
- **Security**: JWT, OAuth, prompt injection protection, content filtering
- **Observability**: Structured logging, metrics, tracing, LangSmith
