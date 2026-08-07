# Deployment Guide

## Architecture

```
                    ┌──────────────┐
                    │    NGINX     │
                    │  (Load)      │
                    └──────┬───────┘
                           │
              ┌────────────┴─────────────┐
              │                          │
      ┌───────▼───────┐          ┌───────▼───────┐
      │   Frontend    │          │   Backend     │
      │  (React/NGNIX)│          │  (FastAPI)    │
      └───────────────┘          └───────┬───────┘
                                         │
                              ┌──────────┴──────────┐
                              │                     │
                       ┌──────▼──────┐      ┌───────▼──────┐
                       │  PostgreSQL │      │    Redis     │
                       └─────────────┘      └──────────────┘
```

## Option 1: Docker Compose (Recommended)

### Production Configuration

Create a `.env` file with production values:

```bash
APP_ENV=production
DEBUG=false
SECRET_KEY=<strong-random-string>
JWT_SECRET_KEY=<strong-random-string>
DATABASE_URL=postgresql+asyncpg://app:password@postgres:5432/ai_chatbot
REDIS_URL=redis://redis:6379/0
OPENAI_API_KEY=sk-prod-...
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
CORS_ORIGINS=["https://chat.yourdomain.com"]
```

### Deploy

```bash
docker-compose -f docker/docker-compose.yml up -d --build
```

## Option 2: Kubernetes

### Prerequisites
- Kubernetes cluster (EKS, GKE, AKS, or minikube)
- kubectl configured
- Ingress controller

### Deploy

```bash
# Create namespace
kubectl create namespace ai-chatbot

# Apply secrets (edit secret.yaml first!)
kubectl apply -f deployment/k8s/secret.yaml

# Apply configmap
kubectl apply -f deployment/k8s/configmap.yaml

# Deploy backend & frontend
kubectl apply -f deployment/k8s/backend-deployment.yaml
kubectl apply -f deployment/k8s/frontend-deployment.yaml

# Set up Ingress
kubectl apply -f deployment/k8s/ingress.yaml
```

## Option 3: Manual Server Deployment

### Backend

```bash
# Install dependencies
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run with Gunicorn + Uvicorn workers
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

### Frontend

```bash
cd frontend
npm run build
# Serve dist/ with the nginx config in frontend/nginx.conf
```

### Nginx reverse proxy

Use `docker/nginx/nginx.conf` as a template.

## Environment Variables

### Required
| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Application signing secret |
| `JWT_SECRET_KEY` | JWT signing key |
| `DATABASE_URL` | Async PostgreSQL connection |
| `REDIS_URL` | Redis connection |

### LLM Providers (at least one required in production)
| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

### Optional
| Variable | Description |
|----------|-------------|
| `CORS_ORIGINS` | JSON array of allowed origins |
| `VECTOR_DB_TYPE` | `chroma` or `faiss` |
| `RATE_LIMIT_PER_MINUTE` | Request rate limit |
| `LANGCHAIN_API_KEY` | LangSmith tracing key |

## CI/CD

GitHub Actions workflow (`.github/workflows/ci-cd.yml`) handles:
1. Backend tests
2. Frontend tests & build
3. Docker image builds
4. Deployment (on main branch)

## Monitoring

- Health check: `GET /health`
- Structured JSON logs to stdout
- OpenTelemetry metrics (optional)
- LangSmith tracing for LLM calls

## Scaling

- Backend: scale horizontally behind load balancer (stateless)
- PostgreSQL: use managed service (RDS, Cloud SQL)
- Redis: use managed service (ElastiCache)
- Vector DB: scale with ChromaDB cluster or FAISS sharding
