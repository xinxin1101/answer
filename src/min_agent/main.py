"""FastAPI application entry point."""

from fastapi import FastAPI

from min_agent.api.routes import router
from min_agent.config import settings


def create_app() -> FastAPI:
    """Create the application; kept as a factory to make testing easier."""
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="A minimal Agent Runtime implemented from scratch.",
    )
    application.include_router(router, prefix=settings.api_prefix)
    return application


app = create_app()
