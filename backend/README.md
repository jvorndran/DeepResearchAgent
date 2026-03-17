# Backend - Deep Financial Research Agent

FastAPI backend with LangGraph orchestration for asynchronous financial research.

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended - fast Python package manager)
uv sync

# Or using pip
pip install -e .
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required environment variables:
- `OPENAI_API_KEY` - For code generation
- `GOOGLE_AI_API_KEY` - For Gemini synthesis
- `FMP_API_KEY` - Financial Modeling Prep
- `FRED_API_KEY` - Federal Reserve Economic Data
- `CLERK_SECRET_KEY` - For authentication
- `DATABASE_URL` - SQLite or PostgreSQL connection string

### 3. Run the Server

```bash
# Development mode with auto-reload
uv run python main.py

# Or using uvicorn directly
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000

## Project Structure

```
backend/
├── main.py                 # FastAPI application entry point
├── pyproject.toml          # uv/pip dependencies (PEP 621 format)
├── .env.example            # Environment variables template
│
├── api/                    # REST API endpoints
│   ├── routes/
│   │   ├── research.py     # POST /api/research
│   │   └── status.py       # GET /api/status/{job_id}
│   └── dependencies.py     # Clerk JWT validation
│
├── core/                   # Core configuration
│   ├── config.py           # Pydantic settings
│   └── database.py         # SQLAlchemy models & session
│
├── graph/                  # LangGraph orchestration
│   ├── workflow.py         # State machine DAG
│   ├── state.py            # TypedDict state definition
│   └── nodes/              # Individual agent nodes
│       ├── gatekeeper.py   # Schema extraction (no LLM)
│       ├── code_gen.py     # OpenAI Agents SDK
│       ├── execution.py    # Docker sandbox runner
│       └── writer.py       # Gemini synthesis
│
├── sandbox/                # Execution environment
│   ├── Dockerfile          # Minimal Python sandbox
│   └── runner.py           # Docker execution wrapper
│
└── services/               # External API clients
    └── (TBD: fmp.py, fred.py, gcs.py, cloud_tasks.py)
```

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Development

### Running Tests

```bash
uv run pytest
```

### Code Formatting

```bash
# Format with Black
uv run black .

# Lint with Ruff
uv run ruff check .
```

### Type Checking

```bash
uv run mypy .
```

## Database Migrations

```bash
# TODO: Add Alembic migration commands when implemented
```

## Docker Sandbox

Build the execution sandbox image:

```bash
cd sandbox
docker build -t deep-research-sandbox:latest .
```

## About uv

This project uses [uv](https://github.com/astral-sh/uv), a fast Python package manager written in Rust.

Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

## Implementation Status

All backend files currently contain only structural comments explaining their purpose.
Implementation will proceed in phases as outlined in the PRD.
