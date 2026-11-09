"""Integration tests for JWT-authenticated Chat, Session and Trace endpoints."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.testclient import TestClient

from min_agent.chat.service import ChatService
from min_agent.config import Settings
from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, LLMResponse
from min_agent.main import create_app
from min_agent.runtime import AgentRuntime
from min_agent.sessions.store import SessionStore
from min_agent.tools.registry import ToolRegistry
from min_agent.trace.recorder import TraceRecorder

TEST_SECRET = "test-secret-for-jwt-signing-only-000000000000"


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


def create_token(user_id: str, *, expires_in: int = 3600) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "iss": "test-issuer",
            "aud": "test-audience",
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        TEST_SECRET,
        algorithm="HS256",
    )


def auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id)}"}


def build_test_app(tmp_path):
    database_path = str(tmp_path / "api.db")
    trace_recorder = TraceRecorder(database_path)
    provider = FakeProvider()
    runtime = AgentRuntime(
        provider,
        ToolRegistry(),
        trace_recorder=trace_recorder,
    )
    service = ChatService(
        runtime,
        SessionStore(database_path),
        ContextManager(max_messages=10),
        trace_recorder=trace_recorder,
    )
    config = Settings(
        app_env="test",
        jwt_secret=TEST_SECRET,
        jwt_issuer="test-issuer",
        jwt_audience="test-audience",
        database_path=database_path,
    )
    app = create_app(config=config, chat_service=service)
    app.state.test_provider = provider
    return app


def test_chat_endpoint_returns_session_and_trace(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/chat",
            headers=auth_headers("user-a"),
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "Hello from the test Agent."
        assert payload["session_id"]
        assert payload["trace_id"]

        trace_response = client.get(
            f"/api/v1/traces/{payload['trace_id']}",
            headers=auth_headers("user-a"),
            params={"event_limit": 2},
        )
        assert trace_response.status_code == 200
        trace_payload = trace_response.json()
        assert trace_payload["has_more_events"] is True
        assert len(trace_payload["events"]) == 2
        assert trace_payload["next_after_event_id"] is not None

        next_page = client.get(
            f"/api/v1/traces/{payload['trace_id']}",
            headers=auth_headers("user-a"),
            params={
                "event_limit": 2,
                "after_event_id": trace_payload["next_after_event_id"],
            },
        )
        assert next_page.status_code == 200
        assert len(next_page.json()["events"]) >= 1
        assert next_page.json()["events"][0]["event_id"] > trace_payload["events"][-1]["event_id"]


def test_session_and_trace_endpoints_enforce_user_isolation(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/chat",
            headers=auth_headers("user-a"),
            json={"message": "Hello"},
        )
        payload = response.json()
        session_id = payload["session_id"]
        trace_id = payload["trace_id"]

        foreign_messages = client.get(
            f"/api/v1/sessions/{session_id}/messages",
            headers=auth_headers("user-b"),
        )
        foreign_trace = client.get(
            f"/api/v1/traces/{trace_id}",
            headers=auth_headers("user-b"),
        )
        assert foreign_messages.status_code == 404
        assert foreign_trace.status_code == 404


def test_api_rejects_missing_invalid_and_expired_bearer_tokens(tmp_path) -> None:
    with TestClient(build_test_app(tmp_path)) as client:
        missing = client.post("/api/v1/chat", json={"message": "Hello"})
        invalid = client.post(
            "/api/v1/chat",
            headers={"Authorization": "Bearer not-a-jwt"},
            json={"message": "Hello"},
        )
        expired = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {create_token('user-a', expires_in=-1)}"},
            json={"message": "Hello"},
        )
        spoofed_header = client.post(
            "/api/v1/chat",
            headers={"X-User-ID": "admin"},
            json={"message": "Hello"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert expired.status_code == 401
    assert spoofed_header.status_code == 401


def test_idempotency_key_replays_successful_response(tmp_path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        headers = {**auth_headers("user-a"), "Idempotency-Key": "retry-001"}
        first = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "Do this once"},
        )
        second = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "Do this once"},
        )
        conflicting = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "Different request"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trace_id"] == second.json()["trace_id"]
    assert first.json()["session_id"] == second.json()["session_id"]
    assert conflicting.status_code == 409
    assert len(app.state.test_provider.requests) == 1


def test_production_app_rejects_default_jwt_secret() -> None:
    config = Settings(app_env="production")
    try:
        create_app(config=config)
    except ValueError as exc:
        assert "Production requires" in str(exc)
    else:
        raise AssertionError("Production must reject the development JWT secret.")
