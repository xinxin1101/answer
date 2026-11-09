"""End-to-end acceptance tests for the hardened Agent application services."""

from collections.abc import Sequence
from typing import Any

import pytest

from min_agent.chat.service import ChatService
from min_agent.config import Settings
from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, LLMResponse, ToolCall
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.tools.defaults import build_default_registry
from min_agent.tools.todo import TodoStore
from min_agent.trace.recorder import TraceRecorder


class ScenarioProvider:
    """Return a deterministic multi-tool plan followed by a final answer."""

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
            raise AssertionError("Unexpected additional model request.")
        return self.responses.pop(0)


class TimeoutProvider:
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise TimeoutError("upstream timeout; do not persist this raw message")


@pytest.mark.asyncio
async def test_end_to_end_multitool_memory_context_and_trace(tmp_path) -> None:
    database_path = str(tmp_path / "acceptance.db")
    provider = ScenarioProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="calc-call",
                        name="calculator",
                        arguments={"expression": "12 * 8"},
                    ),
                    ToolCall(
                        id="todo-call",
                        name="todo",
                        arguments={"action": "add", "title": "Review FastAPI design"},
                    ),
                ]
            ),
            LLMResponse(content="结果是 96，并已创建待办事项。"),
        ]
    )
    memory_service = MemoryService(MemoryStore(database_path))
    memory_service.remember_from_user_message(
        "user-a",
        "以后我所有后端项目都优先使用 FastAPI。",
    )
    session_store = SessionStore(database_path)
    session = session_store.create_session("user-a", "Acceptance session")
    session_store.append_messages(
        "user-a",
        session.session_id,
        [
            ChatMessage(role="user", content="Earlier context: build an API."),
            ChatMessage(role="assistant", content="We chose a layered architecture."),
            ChatMessage(role="user", content="The API needs authentication."),
            ChatMessage(role="assistant", content="Use a verified identity."),
        ],
    )
    trace_recorder = TraceRecorder(database_path)
    registry = build_default_registry(Settings(database_path=database_path))
    runtime = AgentRuntime(provider, registry, trace_recorder=trace_recorder)
    service = ChatService(
        runtime,
        session_store,
        ContextManager(max_messages=2),
        memory_service=memory_service,
        trace_recorder=trace_recorder,
    )

    result = await service.chat(
        "user-a",
        "按 FastAPI 技术栈计算 12*8，并添加一个待办。",
        session.session_id,
    )

    assert result.reply == "结果是 96，并已创建待办事项。"
    assert result.tool_calls_executed == 2
    assert result.summary_used is True
    assert result.memory_used is True

    first_request = provider.requests[0]
    system_context = first_request[0].content or ""
    assert "FastAPI" in system_context
    assert "Earlier context" in system_context
    assert "API" in system_context

    todo_items = TodoStore(database_path).list("user-a")
    assert len(todo_items) == 1
    assert todo_items[0]["title"] == "Review FastAPI design"
    assert TodoStore(database_path).list("user-b") == []

    persisted_messages = session_store.get_messages("user-a", session.session_id)
    assert any(
        message.role == "tool" and message.tool_call_id == "calc-call"
        for message in persisted_messages
    )
    assert any(
        message.role == "tool" and message.tool_call_id == "todo-call"
        for message in persisted_messages
    )

    trace = trace_recorder.get_trace("user-a", result.trace_id or "")
    assert trace is not None
    assert trace["status"] == "succeeded"
    assert trace["stop_reason"] == "final_answer"
    event_types = [event["event_type"] for event in trace["events"]]
    assert event_types.count("tool.started") == 2
    assert event_types.count("tool.completed") == 2
    assert "llm.completed" in event_types
    assert event_types[-1] == "runtime.completed"


@pytest.mark.asyncio
async def test_end_to_end_timeout_is_classified_and_trace_is_retained(tmp_path) -> None:
    database_path = str(tmp_path / "failure-acceptance.db")
    trace_recorder = TraceRecorder(database_path)
    session_store = SessionStore(database_path)
    service = ChatService(
        AgentRuntime(
            TimeoutProvider(),
            build_default_registry(Settings(database_path=database_path)),
            trace_recorder=trace_recorder,
        ),
        session_store,
        ContextManager(max_messages=4),
        trace_recorder=trace_recorder,
    )

    with pytest.raises(TimeoutError):
        await service.chat("user-a", "Trigger an upstream timeout.")

    traces = trace_recorder.list_traces("user-a")
    assert len(traces) == 1
    trace = trace_recorder.get_trace("user-a", traces[0]["trace_id"])
    assert trace is not None
    assert trace["status"] == "failed"
    assert trace["error_category"] == "timeout"
    assert trace["error_type"] == "TimeoutError"
    assert "upstream timeout" not in (trace["error_message"] or "")
    assert any(event["event_type"] == "llm.failed" for event in trace["events"])
    assert any(event["event_type"] == "runtime.failed" for event in trace["events"])
