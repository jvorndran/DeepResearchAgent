.PHONY: help install run-local build clean test docker-up docker-down sandbox-build

# Default target
help:
	@echo "Deep Financial Research Agent - Development Commands"
	@echo "====================================================="
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install          - Install all dependencies (frontend + backend)"
	@echo "  make install-backend  - Install Python dependencies via uv"
	@echo "  make install-frontend - Install Node.js dependencies"
	@echo ""
	@echo "Local Development:"
	@echo "  make run-local        - Run both frontend and backend locally"
	@echo "  make run-backend      - Run backend API only"
	@echo "  make run-frontend     - Run frontend only"
	@echo ""
	@echo "Docker Development:"
	@echo "  make docker-up        - Start all services with docker-compose"
	@echo "  make docker-down      - Stop all services"
	@echo "  make docker-rebuild   - Rebuild and restart all containers"
	@echo ""
	@echo "Build & Test:"
	@echo "  make build            - Build production artifacts"
	@echo "  make test             - Run all tests"
	@echo "  make test-backend     - Run backend tests only"
	@echo "  make sandbox-build    - Build the execution sandbox Docker image"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean            - Remove build artifacts and caches"
	@echo "  make lint             - Run linters on backend code"
	@echo "  make format           - Format backend code with Black"

# ==========================================
# INSTALLATION
# ==========================================
install: install-backend install-frontend
	@echo "✅ All dependencies installed!"

install-backend:
	@echo "📦 Installing backend dependencies..."
	cd backend && uv sync

install-frontend:
	@echo "📦 Installing frontend dependencies..."
	cd frontend && npm install

# ==========================================
# LOCAL DEVELOPMENT
# ==========================================
# NOTE: Git Bash users - if parallel execution (-j2) has issues,
# run backend and frontend in separate terminals instead
run-local:
	@echo "🚀 Starting local development environment..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:3000"
	@make -j2 run-backend run-frontend

run-backend:
	@echo "🐍 Starting FastAPI backend..."
	cd backend && uv run python main.py

run-frontend:
	@echo "⚛️  Starting Next.js frontend..."
	cd frontend && npm run dev

# ==========================================
# DOCKER DEVELOPMENT
# ==========================================
docker-up:
	@echo "🐳 Starting Docker Compose services..."
	docker-compose up -d
	@echo "✅ Services running:"
	@echo "   Backend:  http://localhost:8000"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Database: localhost:5432"

docker-down:
	@echo "🛑 Stopping Docker Compose services..."
	docker-compose down

docker-rebuild:
	@echo "🔄 Rebuilding Docker containers..."
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d

# ==========================================
# SANDBOX
# ==========================================
sandbox-build:
	@echo "🛡️  Building execution sandbox Docker image..."
	cd backend/sandbox && docker build -t deep-research-sandbox:latest .

# ==========================================
# BUILD & TEST
# ==========================================
build: build-frontend
	@echo "✅ Build complete!"

build-frontend:
	@echo "📦 Building Next.js production bundle..."
	cd frontend && npm run build

test: test-backend
	@echo "✅ All tests passed!"

test-backend:
	@echo "🧪 Running backend tests..."
	cd backend && uv run pytest

# ==========================================
# CODE QUALITY
# ==========================================
lint:
	@echo "🔍 Linting backend code..."
	cd backend && uv run ruff check .

format:
	@echo "🎨 Formatting backend code..."
	cd backend && uv run black .

# ==========================================
# CLEANUP
# ==========================================
# NOTE: Git Bash users - if "backend/**/__pycache__" doesn't work,
# run manually: find backend -type d -name "__pycache__" -exec rm -rf {} +
clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf backend/__pycache__
	rm -rf backend/**/__pycache__
	rm -rf backend/.pytest_cache
	rm -rf backend/.ruff_cache
	rm -rf backend/.mypy_cache
	rm -rf frontend/.next
	rm -rf frontend/node_modules/.cache
	@echo "✅ Clean complete!"
