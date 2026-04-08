#!/bin/bash
# BtB Backend Startup

set -e
cd "$(dirname "$0")/backend"

echo "📦 Installing Python dependencies..."
pip install -r requirements.txt --break-system-packages -q

echo ""
echo "🚀 Starting BtB Backend (FastAPI + AI Harness)..."
echo "   API docs: http://localhost:8000/docs"
echo "   Health:   http://localhost:8000/health"
echo ""

ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-your_key_here}" \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
