# Installation Guide

## Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16+
- Redis 7+

## Local Development Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd ai-chatbot
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your API keys and database credentials
```

### 3. Set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Set up the database

```bash
# Create the database
createdb ai_chatbot

# Run migrations
alembic upgrade head

# (Optional) Seed default data
python -m app.db.seed
```

### 5. Set up the frontend

```bash
cd frontend
npm install
```

### 6. Run the backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs available at http://localhost:8000/docs

### 7. Run the frontend

```bash
cd frontend
npm run dev
```

Frontend available at http://localhost:5173

## Using Docker

```bash
docker-compose up --build
```

This starts:
- PostgreSQL on port 5432
- Redis on port 6379
- Backend on port 8000
- Frontend on port 5173
- Nginx on port 80

## LLM Provider Configuration

### OpenAI
```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

### Google Gemini
```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

### Groq
```bash
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

### OpenRouter
```bash
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o
```

## Fallback Chain

Configure fallback models in order:
```bash
FALLBACK_MODELS=groq,gpt-4o-mini
```

The system automatically falls back when the primary model hits a rate limit, timeout, or error.
