"""
FastAPI application entry point.

Loads environment and logging first, then builds the ASGI app via api.app.create_app.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file (backend dir first)
env_path = BASE_DIR / ".env"
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

from core.logging_config import configure_logging

configure_logging()

from api.app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[
            str(BASE_DIR / "agents"),
            str(BASE_DIR / "api"),
            str(BASE_DIR / "core"),
            str(BASE_DIR / "mcp_clients"),
            str(BASE_DIR / "services"),
        ],
        reload_excludes=[
            "__pycache__/*",
            "__pycache__/**",
            "data/*",
            "data/**",
            "outputs/*",
            "outputs/**",
        ],
    )
