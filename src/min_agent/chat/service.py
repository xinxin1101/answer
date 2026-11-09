"""Connect SessionStore, ContextManager and AgentRuntime."""

from pydantic import BaseModel

from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore


class ChatResult(BaseModel):
    session_id: str
    reply: str
    steps: int
    tool_calls_executed: int
    context_original_messages: int
    context_retained_messages: int
    context_compressed_messages: int
    summary_used: bool


class ChatService:
    """Run a chat turn without requiring the caller to load or pass history."""

    def __init__(
        self,
        runtime: AgentRuntime,
        session_store: SessionStore,
        context_manager: ContextManager,
    ) -> None:
        self.runtime = runtime
        self.session_store = session_store
        self.context_manager = context_manager

    async def chat(
        self, user_id: str, message: str, session_id: str | None = None
    ) -> ChatResult:
        if not message.strip():
            raise ValueError("message must not be blank")
        if session_id is None:
            session = self.session_store.create_session(user_id, message.strip()[:60])
            session_id = session.session_id
            history: list[ChatMessage] = []
        else:
            self.session_store.get_session(user_id, session_id)
            history = self.session_store.get_messages(user_id, session_id)

        window = self.context_manager.build(history)
        result = await self.runtime.run(
            message,
            history=window.history,
            context_summary=window.summary,
        )
        # messages = system + selected history + this turn; persist only this turn.
        start = 1 + len(window.history)
        new_messages = [item for item in result.messages[start:] if item.role != "system"]
        self.session_store.append_messages(user_id, session_id, new_messages)
        return ChatResult(
            session_id=session_id,
            reply=result.reply,
            steps=result.steps,
            tool_calls_executed=result.tool_calls_executed,
            context_original_messages=window.original_messages,
            context_retained_messages=window.retained_messages,
            context_compressed_messages=window.compressed_messages,
            summary_used=window.summary is not None,
        )
