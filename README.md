# Deep Financial Research Agent

An advanced, orchestration-driven platform designed to answer complex macroeconomic and stock market questions using asynchronous LLM agents, code execution, and interactive data visualizations.

## Overview

This system provides institutional-grade, transparent, and mathematically accurate financial research by:

- **Factuality Over Fluency:** Never guessing financial metrics—all insights derived from deterministically executed code
- **Role-Based Subagents:** Specialized agents (Data Engineer, Quantitative Developer, Technical Writer, Quality Analyst) coordinated by an Orchestrator
- **Best-in-Class Routing:** OpenAI o1/o3 for code generation, Gemini 2.0 Flash for reasoning and coordination
- **Interactive Data:** Explorable financial data with Recharts visualizations
- **Observable State:** Complete visibility into agent thought process and execution

## Architecture

```
├── frontend/          # Next.js + shadcn/ui + Recharts
│   └── src/
│       ├── app/       # Next.js App Router
│       ├── components/# UI Components
│       ├── lib/       # API client & utilities
│       └── types/     # TypeScript definitions
│
└── backend/           # FastAPI + LangChain Deep Agents + Python
    ├── api/           # REST endpoints
    ├── core/          # Configuration & database
    ├── agents/        # Role-based subagents
    │   ├── orchestrator.py          # Main coordinator
    │   ├── data_engineer.py         # Data fetching & schema extraction
    │   ├── quantitative_developer.py # Code generation & execution
    │   ├── technical_writer.py      # Report synthesis
    │   └── quality_analyst.py       # Quality & compliance review
    ├── sandbox/       # Docker execution environment
    └── services/      # External API integrations
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for sandbox execution)
- uv (fast Python package manager)
- Git Bash (if on Windows)

### Installation

**Install uv first:**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Then install project dependencies:**
```bash
# Install all dependencies
make install

# Or install separately
make install-backend   # Python dependencies via uv
make install-frontend  # Node.js dependencies
```

### Environment Setup

1. **Backend**: Copy `backend/.env.example` to `backend/.env` and fill in your API keys
2. **Frontend**: Copy `frontend/.env.local.example` to `frontend/.env.local` and add Clerk keys

### Running Locally

```bash
# Run both frontend and backend
make run-local

# Or run separately
make run-backend   # http://localhost:8000
make run-frontend  # http://localhost:3000
```

### Using Docker

```bash
# Start all services with docker-compose
make docker-up

# Stop services
make docker-down

# Rebuild containers
make docker-rebuild
```

### Build Sandbox

```bash
# Build the execution sandbox Docker image
make sandbox-build
```

## Development Workflow

### Phase 1: Local Subagent System (Current)
- ✅ Orchestrator agent (Research Director)
- ✅ Multi-model routing (OpenAI o1/o3 + Gemini 2.0 Flash)
- ✅ Role-based subagents:
  - Data Engineer (data fetching & schema extraction)
  - Quantitative Developer (code generation & execution)
  - Technical Writer (report synthesis)
  - Quality Analyst (compliance review)
- 🚧 Subagent delegation and communication
- 🚧 Code generation & execution pipeline

### Phase 2: Secure Execution & Context Persistence
- 🚧 Dockerized sandbox for code execution
- 🚧 Database storage for agent conversation history
- 🚧 Retry logic and error recovery

### Phase 3: Frontend & Auth
- 🚧 Next.js UI with shadcn/ui
- 🚧 Clerk authentication
- 🚧 Recharts visualizations

### Phase 4: GCP Migration
- ⏳ Cloud SQL, GCS, Cloud Tasks
- ⏳ Cloud Run deployment

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/research` | POST | Create new research job |
| `/api/status/{job_id}` | GET | Poll job status |
| `/api/artifacts/{job_id}` | GET | Get report & chart data |

## Technology Stack

**Frontend:**
- Next.js 16 (React 19)
- TypeScript
- Tailwind CSS
- shadcn/ui
- Recharts
- Clerk (Auth)

**Backend:**
- FastAPI
- LangChain Deep Agents
- OpenAI API (o1/o3 for code generation)
- Google Gemini API (for coordination and reasoning)
- Pandas, NumPy, SciPy
- SQLAlchemy
- Docker

**Cloud (Production):**
- Google Cloud Platform
- Cloud Run
- Cloud Tasks
- Cloud SQL
- Google Cloud Storage

## Contributing

See implementation details in:
- `prd.md` - Product Requirements Document
- `architecture.md` - Technical Architecture

## License

[Your License Here]
