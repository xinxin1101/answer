"""SQLite-backed session, message, idempotency and concurrency persistence."""

import asyncio
import json
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, closing, contextmanager
from threading import RLock
from typing import Literal

from pydantic import BaseModel

from min_agent.core.schemas import ChatMessage
from min_agent.storage.sqlite import connect_sqlite, enable_wal, prepare_database_path

PersistedRole = Literal["user", "assistant", "tool"]


class SessionNotFoundError(LookupError):
    """Raised when a session does not exist or is not owned by the requester."""


class SessionStoreError(RuntimeError):
    """Raised when stored session data cannot be decoded safely."""


class SessionBusyError(RuntimeError):
    """Raised when another request holds a session lock for too long."""


class IdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused with a different request body."""


class IdempotencyInProgressError(RuntimeError):
    """Raised when an identical idempotent request is still being processed."""


class SessionInfo(BaseModel):
    session_id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class SessionStore:
    """Own session lifecycle, ordered history and cross-process request coordination."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        prepare_database_path(database_path)
        self._memory_connection = (
            connect_sqlite(":memory:") if database_path == ":memory:" else None
        )
        self._memory_lock = RLock()
        enable_wal(database_path)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._memory_connection is not None:
            with self._memory_lock, self._memory_connection:
                yield self._memory_connection
            return
        with closing(connect_sqlite(self.database_path)) as connection:
            with connection:
                yield connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user_updated
                    ON sessions(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool')),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                    ON messages(session_id, id ASC);
                CREATE TABLE IF NOT EXISTS session_locks (
                    session_id TEXT PRIMARY KEY,
                    owner_token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS idempotency_requests (
                    user_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
                    response_json TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, idempotency_key)
                );
                """
            )

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        owner = user_id.strip()
        if not owner:
            raise ValueError("user_id must not be blank")
        return owner

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionInfo:
        return SessionInfo(
            session_id=row["session_id"],
            user_id=row["user_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_session(self, user_id: str, title: str = "New conversation") -> SessionInfo:
        owner = self._validate_user_id(user_id)
        normalized_title = title.strip() or "New conversation"
        if len(normalized_title) > 200:
            raise ValueError("session title must not exceed 200 characters")
        session_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions (session_id, user_id, title) VALUES (?, ?, ?)",
                (session_id, owner, normalized_title),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._row_to_session(row)

    def get_session(self, user_id: str, session_id: str) -> SessionInfo:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, owner),
            ).fetchone()
        if row is None:
            raise SessionNotFoundError("Session was not found for this user.")
        return self._row_to_session(row)

    def list_sessions(self, user_id: str) -> list[SessionInfo]:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sessions WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC
                """,
                (owner,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def append_messages(
        self,
        user_id: str,
        session_id: str,
        messages: Sequence[ChatMessage],
    ) -> int:
        owner = self._validate_user_id(user_id)
        if not messages:
            return 0
        serialized: list[tuple[str, str, str]] = []
        for message in messages:
            if message.role == "system":
                raise ValueError("system messages must not be persisted in session history")
            serialized.append((message.role, message.model_dump_json(), session_id))

        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, owner),
            ).fetchone()
            if exists is None:
                raise SessionNotFoundError("Session was not found for this user.")
            connection.executemany(
                "INSERT INTO messages (role, payload, session_id) VALUES (?, ?, ?)",
                serialized,
            )
            connection.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
        return len(serialized)

    def get_messages(self, user_id: str, session_id: str) -> list[ChatMessage]:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, owner),
            ).fetchone()
            if exists is None:
                raise SessionNotFoundError("Session was not found for this user.")
            rows = connection.execute(
                "SELECT payload FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        try:
            return [ChatMessage.model_validate_json(row["payload"]) for row in rows]
        except ValueError as exc:
            raise SessionStoreError("Stored session message is invalid.") from exc

    def delete_session(self, user_id: str, session_id: str) -> None:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, owner),
            )
            if cursor.rowcount == 0:
                raise SessionNotFoundError("Session was not found for this user.")

    @asynccontextmanager
    async def session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        wait_timeout_seconds: float = 30.0,
        lease_seconds: float = 900.0,
    ) -> AsyncIterator[None]:
        """Acquire a SQLite lease so one session is processed by one worker at a time."""
        owner = self._validate_user_id(user_id)
        self.get_session(owner, session_id)
        token = str(uuid.uuid4())
        deadline = time.monotonic() + wait_timeout_seconds

        while True:
            now = time.time()
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO session_locks (session_id, owner_token, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        owner_token = excluded.owner_token,
                        expires_at = excluded.expires_at
                    WHERE session_locks.expires_at < ?
                    """,
                    (session_id, token, now + lease_seconds, now),
                )
                row = connection.execute(
                    "SELECT owner_token FROM session_locks WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                acquired = row is not None and row["owner_token"] == token

            if acquired:
                break
            if time.monotonic() >= deadline:
                raise SessionBusyError("Session is busy; retry the request shortly.")
            await asyncio.sleep(0.05)

        try:
            yield
        finally:
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM session_locks WHERE session_id = ? AND owner_token = ?",
                    (session_id, token),
                )

    def claim_idempotency_request(
        self,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        *,
        lease_seconds: float = 900.0,
    ) -> dict[str, object] | None:
        """Claim a request key, return a completed response, or reject a duplicate."""
        owner = self._validate_user_id(user_id)
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise ValueError("Idempotency-Key must contain 1 to 128 characters.")
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_hash, status, response_json, updated_at
                FROM idempotency_requests
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (owner, key),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO idempotency_requests (
                        user_id, idempotency_key, request_hash, status, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (owner, key, request_hash, now),
                )
                return None
            if row["request_hash"] != request_hash:
                raise IdempotencyConflictError(
                    "This Idempotency-Key was already used with a different request."
                )
            if row["status"] == "completed" and row["response_json"]:
                return json.loads(row["response_json"])
            if now - row["updated_at"] > lease_seconds:
                connection.execute(
                    """
                    UPDATE idempotency_requests
                    SET status = 'pending', response_json = NULL, updated_at = ?
                    WHERE user_id = ? AND idempotency_key = ?
                    """,
                    (now, owner, key),
                )
                return None
            raise IdempotencyInProgressError(
                "A request with this Idempotency-Key is still running."
            )

    def complete_idempotency_request(
        self,
        user_id: str,
        idempotency_key: str,
        response: dict[str, object],
    ) -> None:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE idempotency_requests
                SET status = 'completed', response_json = ?, updated_at = ?
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (
                    json.dumps(response, ensure_ascii=False),
                    time.time(),
                    owner,
                    idempotency_key,
                ),
            )

    def release_idempotency_request(self, user_id: str, idempotency_key: str) -> None:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            connection.execute(
                """
                DELETE FROM idempotency_requests
                WHERE user_id = ? AND idempotency_key = ? AND status = 'pending'
                """,
                (owner, idempotency_key),
            )

    def prune_idempotency_requests(self, older_than_seconds: int = 86_400) -> int:
        cutoff = time.time() - older_than_seconds
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM idempotency_requests WHERE updated_at < ?",
                (cutoff,),
            )
            return cursor.rowcount
