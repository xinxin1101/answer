"""Connect SessionStore, ContextManager, MemoryService, Trace and AgentRuntime."""

import hashlib
import json

from pydantic import BaseModel

from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage
from min_agent.memory.service import MemoryService
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.trace.recorder import TraceRecorder


class ChatResult(BaseModel):
    """Public result returned by one ChatService turn."""

    session_id: str
    trace_id: str | None = None
    reply: str
    steps: int
    tool_calls_executed: int
    context_original_messages: int
    context_retained_messages: int
    context_compressed_messages: int
    summary_used: bool
    memory_used: bool = False


class ChatService:
    """Run serialized chat turns with optional memory and durable idempotency."""

    def __init__(
        self,
        runtime: AgentRuntime,
        session_store: SessionStore,
        context_manager: ContextManager,
        memory_service: MemoryService | None = None,
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self.runtime = runtime
        self.session_store = session_store
        self.context_manager = context_manager
        self.memory_service = memory_service
        self.trace_recorder = trace_recorder

    async def chat(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ChatResult:
        if not message.strip():
            raise ValueError("message must not be blank")

        request_key = idempotency_key.strip() if idempotency_key else None
        if request_key:
            canonical_request = json.dumps(
                {"message": message, "session_id": session_id},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
            cached = self.session_store.claim_idempotency_request(
                user_id,
                request_key,
                request_hash,
            )
            if cached is not None:
                return ChatResult.model_validate(cached)

        created_session = False
        try:
            if session_id is None:
                session = self.session_store.create_session(
                    user_id,
                    message.strip()[:60],
                )
                session_id = session.session_id
                created_session = True

            async with self.session_store.session_lock(user_id, session_id):
                result = await self._run_turn(user_id, message, session_id)

            if request_key:
                self.session_store.complete_idempotency_request(
                    user_id,
                    request_key,
                    result.model_dump(),
                )
            return result
        except Exception:
            if created_session and session_id is not None:
                try:
                    self.session_store.delete_session(user_id, session_id)
                except Exception:
                    pass
            if request_key:
                self.session_store.release_idempotency_request(user_id, request_key)
            raise

    async def _run_turn(
        self,
        user_id: str,
        message: str,
        session_id: str,
    ) -> ChatResult:
        history: list[ChatMessage] = self.session_store.get_messages(user_id, session_id)
        trace_id = (
            self.trace_recorder.start_trace(user_id, session_id)
            if self.trace_recorder is not None
            else None
        )
        try:
            window = self.context_manager.build(history)
            memory_context = None
            if self.memory_service is not None:
                memory_context = self.memory_service.retrieve_context(user_id, message)

            context_parts = [
                part for part in (window.summary, memory_context) if part
            ]
            result = await self.runtime.run(
                message,
                history=window.history,
                context_summary="\n\n".join(context_parts) or None,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
            )

            # Persist only this turn; original Session history remains untouched.
            start = 1 + len(window.history)
            new_messages = [
                item for item in result.messages[start:] if item.role != "system"
            ]
            self.session_store.append_messages(user_id, session_id, new_messages)

            # Extract only from the user's own message, never assistant/tool output.
            if self.memory_service is not None:
                self.memory_service.remember_from_user_message(user_id, message)

            if self.trace_recorder is not None and trace_id is not None:
                self.trace_recorder.finish_trace(
                    trace_id,
                    status="succeeded",
                    stop_reason=result.stop_reason,
                )

            return ChatResult(
                session_id=session_id,
                trace_id=trace_id,
                reply=result.reply,
                steps=result.steps,
                tool_calls_executed=result.tool_calls_executed,
                context_original_messages=window.original_messages,
                context_retained_messages=window.retained_messages,
                context_compressed_messages=window.compressed_messages,
                summary_used=window.summary is not None,
                memory_used=memory_context is not None,
            )
        except Exception as exc:
            if self.trace_recorder is not None and trace_id is not None:
                self.trace_recorder.finish_trace(
                    trace_id,
                    status="failed",
                    stop_reason="error",
                    error=exc,
                )
                try:
                    self.trace_recorder.record_event(
                        trace_id,
                        "runtime.failed",
                        status="failed",
                        details={"error_type": type(exc).__name__},
                    )
                except Exception:
                    pass
            raise
