# Repository Instructions

## Docker logs

The frontend, backend, and database run through `docker-compose.yml`. When debugging running services, prefer these Make targets:

- `make logs` for a recent combined snapshot of backend, frontend, and db logs.
- `make logs-backend` for backend logs only.
- `make logs-frontend` for frontend logs only.
- `make logs-db` for database logs only.
- `make logs-follow` to stream all service logs while reproducing an issue.
- `make logs-snapshot` to write searchable log files under `logs/`.

Always use Context7 to retrieve current documentation before making changes involving the Vercel AI SDK or LangChain DeepAgents. Do not rely on model memory alone for these libraries.