"""End-to-end coverage of tool routing, memory, context and trace behavior."""

from collections.abc import Sequence
from typing import Any

import pytest

from min_agent.chat.service import ChatService
from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, LLMResponse, ToolCall
from min_agent.llm.errors import LLMProviderError
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.tools.defaults import build_default_registry
from min_agent.tools.todo import TodoStore
from min_agent.config import Settings
from min_agent.trace.recorder import TraceRecorder


class ScriptedProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.requests.append(list(messages))
        if not self.responses:
            raise AssertionError("Unexpected additional LLM call.")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_end_to_end_multi_tool_memory_tenant_isolation_and_trace(tmp_path) -> None:
    database_path = str(tmp_path / "e2e.db")
    provider = ScriptedProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="todo-add-1",
                        name="todo",
                        arguments={"action": "add", "title": "Review Agent Runtime"},
                    ),
                    ToolCall(
                        id="calc-1",
                        name="calculator",
                        arguments={"expression": "6 * 7"},
                    ),
                ]
            ),
            LLMResponse(content="待办已创建，计算结果为 42。"),
            LLMResponse(content="你偏好使用 FastAPI。"),
        ]
    )
    config = Settings(database_path=database_path)
    registry = build_default_registry(config)
    trace_recorder = TraceRecorder(database_path)
    memory_service = MemoryService(MemoryStore(database_path))
    service = ChatService(
        AgentRuntime(
            provider,
            registry,
            trace_recorder=trace_recorder,
        ),
        SessionStore(database_path),
        ContextManager(max_messages=8),
        memory_service=memory_service,
        trace_recorder=trace_recorder,
    )

    first = await service.chat(
        "user-a",
        "以后我所有后端项目都优先使用 FastAPI。请添加待办并计算 6 * 7。",
    )
    second = await service.chat(
        "user-a",
        "我偏好什么后端框架？",
    )

    todo_store = TodoStore(database_path)
    user_a_todos = todo_store.list("user-a")
    user_b_todos = todo_store.list("user-b")
    first_trace = trace_recorder.get_trace("user-a", first.trace_id or "")

    assert first.tool_calls_executed == 2
    assert "42" in first.reply
    assert len(user_a_todos) == 1
    assert user_a_todos[0]["title"] == "Review Agent Runtime"
    assert user_b_todos == []
    assert second.memory_used is True
    assert "FastAPI" in provider.requests[2][0].content
    assert first_trace is not None
    assert first_trace["status"] == "succeeded"
    assert first_trace["stop_reason"] == "final_answer"
    assert [event["event_type"] for event in first_trace["events"]].count(
        "tool.completed"
    ) == 2


@pytest.mark.asyncio
async def test_end_to_end_context_compaction_keeps_recent_turn_and_summary(tmp_path) -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(content="First answer."),
            LLMResponse(content="Second answer."),
            LLMResponse(content="Third answer."),
        ]
    )
    service = ChatService(
        AgentRuntime(provider, build_default_registry(Settings(
            database_path=str(tmp_path / "context-e2e.db")
        ))),
        SessionStore(str(tmp_path / "context-e2e.db")),
        ContextManager(max_messages=2),
    )

    first = await service.chat("user-a", "Remember the original project codename: Atlas.")
    await service.chat("user-a", "Tell me a short joke.", first.session_id)
    third = await service.chat("user-a", "What did I call the project?", first.session_id)

    assert third.summary_used is True
    assert third.context_compressed_messages >= 2
    system_message = provider.requests[2][0]
    assert system_message.role == "system"
    assert "Atlas" in (system_message.content or "")


@pytest.mark.asyncio
async def test_end_to_end_provider_exception_is_classified_in_trace(tmp_path) -> None:
    class BrokenProvider:
        async def complete(
            self,
            messages: Sequence[ChatMessage],
            tools: Sequence[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            raise LLMProviderError("provider request failed with a sensitive payload")

    database_path = str(tmp_path / "failure-e2e.db")
    trace_recorder = TraceRecorder(database_path)
    service = ChatService(
        AgentRuntime(BrokenProvider(), build_default_registry(
            Settings(database_path=database_path)
        ), trace_recorder=trace_recorder),
        SessionStore(database_path),
        ContextManager(max_messages=8),
        trace_recorder=trace_recorder,
    )

    with pytest.raises(LLMProviderError):
        await service.chat("user-a", "Trigger the provider failure.")

    traces = trace_recorder.list_traces("user-a")
    assert len(traces) == 1
    trace = trace_recorder.get_trace("user-a", traces[0]["trace_id"])
    assert trace is not None
    assert trace["status"] == "failed"
    assert trace["error_category"] == "provider"
    assert trace["error_message"] == "LLMProviderError"
    assert "sensitive payload" not in str(trace)
