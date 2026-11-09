"""Integration tests for Chat, Session and Trace HTTP endpoints."""

from collections.abc import Sequence
from typing import Any

from fastapi.testclient import TestClient

from min_agent.chat.service import ChatService
from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, LLMResponse
from min_agent.main import create_app
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.tools.registry import ToolRegistry
from min_agent.trace.recorder import TraceRecorder


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.requests.append(list(messages))
        return LLMResponse(content="Hello from the test Agent.")


def build_test_app(tmp_path):
    database_path = str(tmp_path / "api.db")
    trace_recorder = TraceRecorder(database_path)
    runtime = AgentRuntime(
        FakeProvider(),
        ToolRegistry(),
        trace_recorder=trace_recorder,
    )
    service = ChatService(
        runtime,
        SessionStore(database_path),
        ContextManager(max_messages=10),
        trace_recorder=trace_recorder,
    )
    return create_app(chat_service=service)


def test_chat_endpoint_returns_session_and_trace(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/chat",
            headers={"X-User-ID": "user-a"},
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "Hello from the test Agent."
        assert payload["session_id"]
        assert payload["trace_id"]

        trace_response = client.get(
            f"/api/v1/traces/{payload['trace_id']}",
            headers={"X-User-ID": "user-a"},
        )
        assert trace_response.status_code == 200
        event_types = [
            event["event_type"]
            for event in trace_response.json()["events"]
        ]
        assert "llm.started" in event_types
        assert "llm.completed" in event_types
        assert "runtime.completed" in event_types


def test_session_and_trace_endpoints_enforce_user_isolation(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/chat",
            headers={"X-User-ID": "user-a"},
            json={"message": "Hello"},
        )
        payload = response.json()
        session_id = payload["session_id"]
        trace_id = payload["trace_id"]

        foreign_messages = client.get(
            f"/api/v1/sessions/{session_id}/messages",
            headers={"X-User-ID": "user-b"},
        )
        foreign_trace = client.get(
            f"/api/v1/traces/{trace_id}",
            headers={"X-User-ID": "user-b"},
        )
        assert foreign_messages.status_code == 404
        assert foreign_trace.status_code == 404


def test_chat_endpoint_requires_user_header(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "Hello"},
        )

    assert response.status_code == 422
