"""
FastAPI application entry point.

Loads environment and logging first, then builds the ASGI app via api.app.create_app.
"""

import os

from dotenv import load_dotenv

# Load environment variables from .env file (backend dir first)
env_path = os.path.join(os.path.dirname(__file__), ".env")
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
        reload=False,
    )
