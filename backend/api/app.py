from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.chat_stream import router as chat_stream_router
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router
from api.routes.reports import router as reports_router
from core.lifespan import lifespan


def create_app() -> FastAPI:
    app = FastAPI(
        title="Deep Financial Research Agent API",
        description="API for the Deep Financial Research Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(reports_router)
    app.include_router(jobs_router)
    app.include_router(chat_stream_router)

    return app
