"""SQLite-backed session and message persistence."""

import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from min_agent.core.schemas import ChatMessage

PersistedRole = Literal["user", "assistant", "tool"]


class SessionNotFoundError(LookupError):
    """Raised when a session does not exist or is not owned by the requester."""


class SessionStoreError(RuntimeError):
    """Raised when stored session data cannot be decoded safely."""


class SessionInfo(BaseModel):
    session_id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class SessionStore:
    """Own session lifecycle and ordered message history in SQLite."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:", timeout=5.0)
        else:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._memory_connection is not None:
            self._memory_connection.row_factory = sqlite3.Row
            self._memory_connection.execute("PRAGMA foreign_keys = ON")
            with self._memory_connection:
                yield self._memory_connection
            return
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
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
                """
                SELECT * FROM sessions
                WHERE session_id = ? AND user_id = ?
                """,
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
