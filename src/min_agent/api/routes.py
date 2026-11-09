"""Health, chat, session and trace HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from min_agent.api.schemas import ChatRequest
from min_agent.chat.service import ChatService
from min_agent.llm.errors import LLMProviderError
from min_agent.sessions.store import SessionNotFoundError
from min_agent.trace.recorder import TraceRecorder

router = APIRouter()


def get_chat_service(request: Request) -> ChatService:
    """Resolve the application-scoped ChatService."""
    service = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Chat service is not initialized.")
    return service


def get_trace_recorder(request: Request) -> TraceRecorder:
    """Resolve the application-scoped TraceRecorder."""
    recorder = getattr(request.app.state, "trace_recorder", None)
    if recorder is None:
        raise HTTPException(status_code=503, detail="Trace recorder is not initialized.")
    return recorder


def require_user_id(\n    x_user_id: Annotated[str, Header(alias="X-User-ID", min_length=1)],\n) -> str:
    """Demo identity boundary; production should derive this from authentication."""
    user_id = x_user_id.strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header is required.")
    return user_id


@router.get("/health", tags=["system"], summary="Health check")
async def health_check() -> dict[str, str]:
    """Return a lightweight process health status."""
    return {
        "status": "ok",
        "service": "minimal-agent-runtime",
    }


@router.post("/chat", tags=["chat"], summary="Send a message to the Agent")
async def chat(
    payload: ChatRequest,
    user_id: Annotated[str, Depends(require_user_id)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> dict[str, object]:
    """Create a session or continue the caller's existing session."""
    try:
        result = await service.chat(
            user_id=user_id,
            message=payload.message,
            session_id=payload.session_id,
        )
        return result.model_dump()
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail="The configured LLM provider could not complete the request.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions", tags=["sessions"], summary="List the user's sessions")
async def list_sessions(
    user_id: str = Depends(require_user_id),
    service: ChatService = Depends(get_chat_service),
) -> list[dict[str, object]]:
    """List sessions owned by the caller."""
    return [
        item.model_dump()
        for item in service.session_store.list_sessions(user_id)
    ]


@router.get(
    "/sessions/{session_id}/messages",
    tags=["sessions"],
    summary="Read messages in a session",
)
async def get_session_messages(
    session_id: str,
    user_id: str = Depends(require_user_id),
    service: ChatService = Depends(get_chat_service),
) -> list[dict[str, object]]:
    """Read a session's history after checking ownership."""
    try:
        messages = service.session_store.get_messages(user_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    return [message.model_dump() for message in messages]


@router.delete(
    "/sessions/{session_id}",
    tags=["sessions"],
    summary="Delete a session and its messages",
)
async def delete_session(
    session_id: str,
    user_id: str = Depends(require_user_id),
    service: ChatService = Depends(get_chat_service),
) -> dict[str, str]:
    """Delete only a session owned by the caller."""
    try:
        service.session_store.delete_session(user_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    return {"status": "deleted", "session_id": session_id}


@router.get("/traces", tags=["traces"], summary="List recent execution traces")
async def list_traces(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    user_id: str = Depends(require_user_id),
    recorder: Annotated[TraceRecorder, Depends(get_trace_recorder)],
) -> list[dict[str, object]]:
    """List recent traces owned by the caller."""
    return recorder.list_traces(user_id, limit)


@router.get(
    "/traces/{trace_id}",
    tags=["traces"],
    summary="Inspect an execution trace",
)
async def get_trace(
    trace_id: str,
    user_id: str = Depends(require_user_id),
    recorder: TraceRecorder = Depends(get_trace_recorder),
) -> dict[str, object]:
    """Read trace metadata and ordered execution events."""
    trace = recorder.get_trace(user_id, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return trace
