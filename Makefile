.PHONY: setup dev backend frontend test lint format docker-up docker-down migrate seed clean

setup:
	pip install -r backend/requirements.txt
	cd frontend && npm install

dev:
	@echo "Run backend and frontend in separate terminals"
	@echo "  make backend  -> http://localhost:8000"
	@echo "  make frontend -> http://localhost:5173"

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	pytest tests/ -v

lint:
	cd backend && ruff check app
	cd frontend && npm run lint

format:
	cd backend && ruff format app
	cd frontend && npm run format

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m app.db.seed

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist .pytest_cache .coverage
