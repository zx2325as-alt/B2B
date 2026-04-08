#!/bin/bash
# BtB Frontend Startup

set -e
cd "$(dirname "$0")/frontend"

echo "📦 Installing Node dependencies..."
npm install --silent

echo ""
echo "🎨 Starting BtB Frontend (Vue 3 + Vite)..."
echo "   App: http://localhost:5173"
echo ""

npm run dev
