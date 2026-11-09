from collections.abc import Sequence
from typing import Any

import pytest

from min_agent.chat.service import ChatService
from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, LLMResponse, ToolCall
from min_agent.runtime import AgentRuntime
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore
from min_agent.sessions.store import SessionNotFoundError, SessionStore
from min_agent.tools.base import ToolDefinition
from min_agent.tools.calculator import CalculatorArgs
from min_agent.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[list[ChatMessage]] = []

    async def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.requests.append(list(messages))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_chat_service_creates_session_and_supports_follow_up(tmp_path) -> None:
    provider = FakeProvider([
        LLMResponse(content="Your preferred language is Python."),
        LLMResponse(content="You said Python."),
    ])
    service = ChatService(
        AgentRuntime(provider, ToolRegistry()),
        SessionStore(str(tmp_path / "chat.db")),
        ContextManager(max_messages=10),
    )
    first = await service.chat("user-a", "I prefer Python.")
    second = await service.chat("user-a", "What language did I mention?", first.session_id)
    assert first.session_id == second.session_id
    assert provider.requests[1][-3].content == "I prefer Python."
    assert provider.requests[1][-1].content == "What language did I mention?"


@pytest.mark.asyncio
async def test_chat_service_persists_tool_turn_for_follow_up(tmp_path) -> None:
    provider = FakeProvider([
        LLMResponse(tool_calls=[
            ToolCall(id="call-1", name="calc", arguments={"expression": "2+3"})
        ]),
        LLMResponse(content="The result was 5."),
        LLMResponse(content="It was 5."),
    ])
    registry = ToolRegistry()

    async def calc(args: CalculatorArgs) -> dict[str, int]:
        return {"result": 5}

    registry.register(ToolDefinition("calc", "calculate", CalculatorArgs, calc))
    service = ChatService(
        AgentRuntime(provider, registry),
        SessionStore(str(tmp_path / "chat.db")),
        ContextManager(max_messages=10),
    )
    first = await service.chat("user-a", "Calculate 2+3.")
    second = await service.chat("user-a", "What was the result?", first.session_id)
    assert first.tool_calls_executed == 1
    assert second.reply == "It was 5."
    assert any(
        item.role == "tool" and item.tool_call_id == "call-1"
        for item in provider.requests[2]
    )


@pytest.mark.asyncio
async def test_chat_service_rejects_foreign_session(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "chat.db"))
    session = store.create_session("user-a")
    service = ChatService(
        AgentRuntime(FakeProvider([]), ToolRegistry()), store, ContextManager()
    )
    with pytest.raises(SessionNotFoundError):
        await service.chat("user-b", "Try to read it", session.session_id)


@pytest.mark.asyncio
async def test_long_term_memory_is_recalled_across_sessions(tmp_path) -> None:
    provider = FakeProvider([
        LLMResponse(content="已记录你的技术偏好。"),
        LLMResponse(content="你偏好使用 FastAPI。"),
    ])
    database_path = str(tmp_path / "chat.db")
    memory_service = MemoryService(MemoryStore(database_path))
    service = ChatService(
        AgentRuntime(provider, ToolRegistry()),
        SessionStore(database_path),
        ContextManager(max_messages=10),
        memory_service=memory_service,
    )

    first = await service.chat(
        "user-a",
        "以后我所有后端项目都优先使用 FastAPI。",
    )
    second = await service.chat(
        "user-a",
        "FastAPI",
    )

    assert first.session_id != second.session_id
    assert second.memory_used is True
    assert any(
        "FastAPI" in (message.content or "")
        for message in provider.requests[1]
    )
