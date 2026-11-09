"""FastAPI application factory and dependency lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from min_agent.api.routes import router
from min_agent.chat.service import ChatService
from min_agent.config import Settings, settings
from min_agent.context.manager import ContextManager
from min_agent.llm.openai_compatible import OpenAICompatibleProvider
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.tools.defaults import build_default_registry
from min_agent.trace.recorder import TraceRecorder

_DEV_JWT_SECRET = "dev-only-insecure-secret-change-before-deploy-000000000000"


def create_app(
    config: Settings | None = None,
    chat_service: ChatService | None = None,
) -> FastAPI:
    """Create an app; dependencies can be injected for deterministic API tests."""
    app_settings = config or settings
    if (
        app_settings.app_env.lower() in {"prod", "production"}
        and app_settings.jwt_secret == _DEV_JWT_SECRET
    ):
        raise ValueError("Production requires a unique JWT_SECRET from a secret manager.")

    injected_service = chat_service

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        provider: OpenAICompatibleProvider | None = None
        if injected_service is not None:
            application.state.chat_service = injected_service
            application.state.trace_recorder = injected_service.trace_recorder
            if injected_service.trace_recorder is not None:
                injected_service.trace_recorder.prune_older_than(
                    app_settings.trace_retention_days
                )
            injected_service.session_store.prune_idempotency_requests()
        else:
            provider = OpenAICompatibleProvider(app_settings)
            session_store = SessionStore(app_settings.database_path)
            memory_service = MemoryService(MemoryStore(app_settings.database_path))
            trace_recorder = TraceRecorder(app_settings.database_path)
            trace_recorder.prune_older_than(app_settings.trace_retention_days)
            session_store.prune_idempotency_requests()
            runtime = AgentRuntime(
                provider,
                build_default_registry(app_settings),
                max_steps=app_settings.max_agent_steps,
                trace_recorder=trace_recorder,
            )
            application.state.chat_service = ChatService(
                runtime,
                session_store,
                ContextManager(max_messages=app_settings.max_context_messages),
                memory_service=memory_service,
                trace_recorder=trace_recorder,
            )
            application.state.trace_recorder = trace_recorder
        try:
            yield
        finally:
            if provider is not None:
                await provider.aclose()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.3.0",
        description="A minimal Agent Runtime implemented from scratch.",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.include_router(router, prefix=app_settings.api_prefix)
    return application


app = create_app()
