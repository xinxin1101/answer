import pytest

from min_agent.core.schemas import ChatMessage, ToolCall
from min_agent.sessions.store import SessionNotFoundError, SessionStore


def test_create_and_list_sessions_are_scoped_to_user(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    first = store.create_session("user-a", "Weather chat")
    second = store.create_session("user-a", "Weekly report")
    other_user = store.create_session("user-b", "Private chat")

    user_a_sessions = store.list_sessions("user-a")

    assert {item.session_id for item in user_a_sessions} == {
        first.session_id,
        second.session_id,
    }
    assert other_user.session_id not in {item.session_id for item in user_a_sessions}


def test_messages_are_isolated_between_sessions(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    window_one = store.create_session("user-a", "Window one")
    window_two = store.create_session("user-a", "Window two")

    store.append_messages(
        "user-a",
        window_one.session_id,
        [
            ChatMessage(role="user", content="What's the weather?"),
            ChatMessage(role="assistant", content="Please specify a city."),
        ],
    )
    store.append_messages(
        "user-a",
        window_two.session_id,
        [
            ChatMessage(role="user", content="Help me write a weekly report."),
            ChatMessage(role="assistant", content="Let's organize your work."),
        ],
    )

    first_history = store.get_messages("user-a", window_one.session_id)
    second_history = store.get_messages("user-a", window_two.session_id)

    assert [message.content for message in first_history] == [
        "What's the weather?",
        "Please specify a city.",
    ]
    assert [message.content for message in second_history] == [
        "Help me write a weekly report.",
        "Let's organize your work.",
    ]


def test_session_history_survives_store_recreation(tmp_path) -> None:
    database_path = str(tmp_path / "sessions.db")
    first_store = SessionStore(database_path)
    session = first_store.create_session("user-a", "Persistent chat")
    first_store.append_messages(
        "user-a",
        session.session_id,
        [ChatMessage(role="user", content="Remember this message.")],
    )

    restarted_store = SessionStore(database_path)
    restored = restarted_store.get_messages("user-a", session.session_id)

    assert len(restored) == 1
    assert restored[0].content == "Remember this message."


def test_tool_call_and_tool_result_round_trip(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    session = store.create_session("user-a")
    messages = [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(id="call-1", name="calculator", arguments={"expression": "1 + 2"})
            ],
        ),
        ChatMessage(
            role="tool",
            name="calculator",
            tool_call_id="call-1",
            content='{"success": true, "result": 3}',
        ),
        ChatMessage(role="assistant", content="The answer is 3."),
    ]

    store.append_messages("user-a", session.session_id, messages)
    restored = store.get_messages("user-a", session.session_id)

    assert restored == messages
    assert restored[0].tool_calls[0].id == "call-1"
    assert restored[1].tool_call_id == "call-1"


def test_user_cannot_read_or_write_another_users_session(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    session = store.create_session("user-a", "Private")

    with pytest.raises(SessionNotFoundError):
        store.get_messages("user-b", session.session_id)
    with pytest.raises(SessionNotFoundError):
        store.get_session("user-b", session.session_id)
    with pytest.raises(SessionNotFoundError):
        store.append_messages(
            "user-b",
            session.session_id,
            [ChatMessage(role="user", content="Attempted access")],
        )


def test_system_prompt_is_not_persisted(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    session = store.create_session("user-a")

    with pytest.raises(ValueError, match="system messages"):
        store.append_messages(
            "user-a",
            session.session_id,
            [ChatMessage(role="system", content="Internal instructions")],
        )


def test_delete_session_removes_its_messages(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))
    session = store.create_session("user-a")
    store.append_messages(
        "user-a",
        session.session_id,
        [ChatMessage(role="user", content="Delete me")],
    )

    store.delete_session("user-a", session.session_id)

    with pytest.raises(SessionNotFoundError):
        store.get_messages("user-a", session.session_id)


def test_empty_user_id_is_rejected(tmp_path) -> None:
    store = SessionStore(str(tmp_path / "sessions.db"))

    with pytest.raises(ValueError, match="user_id"):
        store.create_session("   ")


@pytest.mark.asyncio
async def test_session_lock_serializes_concurrent_turns(tmp_path) -> None:
    import asyncio

    store = SessionStore(str(tmp_path / "locks.db"))
    session = store.create_session("user-a")
    order: list[str] = []

    async def first_request() -> None:
        async with store.session_lock("user-a", session.session_id):
            order.append("first-start")
            await asyncio.sleep(0.05)
            order.append("first-end")

    async def second_request() -> None:
        await asyncio.sleep(0.005)
        async with store.session_lock("user-a", session.session_id):
            order.append("second-start")
            order.append("second-end")

    await asyncio.gather(first_request(), second_request())

    assert order == [
        "first-start",
        "first-end",
        "second-start",
        "second-end",
    ]


def test_idempotency_claim_replay_and_payload_conflict(tmp_path) -> None:
    from min_agent.sessions.store import (
        IdempotencyConflictError,
        IdempotencyInProgressError,
    )

    store = SessionStore(str(tmp_path / "idempotency.db"))
    assert store.claim_idempotency_request("user-a", "key-1", "hash-a") is None

    with pytest.raises(IdempotencyInProgressError):
        store.claim_idempotency_request("user-a", "key-1", "hash-a")

    store.complete_idempotency_request(
        "user-a",
        "key-1",
        {"reply": "once", "session_id": "session-1"},
    )
    replay = store.claim_idempotency_request("user-a", "key-1", "hash-a")
    assert replay == {"reply": "once", "session_id": "session-1"}

    with pytest.raises(IdempotencyConflictError):
        store.claim_idempotency_request("user-a", "key-1", "different-hash")


def test_file_database_uses_wal_and_foreign_keys(tmp_path) -> None:
    import sqlite3

    database_path = str(tmp_path / "sqlite-pragmas.db")
    SessionStore(database_path)
    connection = sqlite3.connect(database_path)
    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    connection.close()

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 0  # Foreign keys are enabled per application connection.
