#!/bin/bash
# Setup script for the AI Chatbot project
set -e

echo "=== AI Chatbot Setup ==="

# Create environment file if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

# Backend setup
echo ""
echo "=== Setting up backend ==="
cd backend
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
cd ..

# Frontend setup
echo ""
echo "=== Setting up frontend ==="
cd frontend
npm install
cd ..

echo ""
echo "=== Setup complete ==="
echo "Backend:  make backend  (http://localhost:8000/docs)"
echo "Frontend: make frontend (http://localhost:5173)"
