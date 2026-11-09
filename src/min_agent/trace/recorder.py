"""SQLite-backed execution tracing for Agent Runtime requests."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TraceRecorder:
    """Persist trace summaries and structured events without storing secrets."""

    def __init__(self, database_path: str, detail_limit: int = 1000) -> None:
        self.database_path = database_path
        self.detail_limit = detail_limit
        self._memory_connection = (
            sqlite3.connect(":memory:", timeout=5.0)
            if database_path == ":memory:"
            else None
        )
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._memory_connection
        should_close = connection is None
        if connection is None:
            connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            if should_close:
                connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms REAL,
                    stop_reason TEXT,
                    error_type TEXT,
                    error_message TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_traces_user_started
                ON traces(user_id, started_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    step_index INTEGER,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    status TEXT,
                    duration_ms REAL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trace_events_trace
                ON trace_events(trace_id, event_id)
                """
            )
            connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def start_trace(self, user_id: str, session_id: str) -> str:
        owner = user_id.strip()
        if not owner:
            raise ValueError("user_id must not be blank")
        trace_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO traces (
                    trace_id, user_id, session_id, status, started_at
                ) VALUES (?, ?, ?, 'running', ?)
                """,
                (trace_id, owner, session_id, self._now()),
            )
            connection.commit()
        return trace_id

    def record_event(
        self,
        trace_id: str,
        event_type: str,
        *,
        step_index: int | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        duration_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = self._safe_details(details or {})
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO trace_events (
                    trace_id, event_type, step_index, tool_call_id, tool_name,
                    status, duration_ms, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    event_type[:100],
                    step_index,
                    tool_call_id,
                    tool_name,
                    status,
                    duration_ms,
                    json.dumps(safe_details, ensure_ascii=False),
                    self._now(),
                ),
            )
            connection.commit()

    def finish_trace(
        self,
        trace_id: str,
        *,
        status: str,
        stop_reason: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("trace status must be succeeded or failed")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT started_at FROM traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if row is None:
                return
            started_at = datetime.fromisoformat(row["started_at"])
            duration_ms = max(
                0.0,
                (datetime.now(UTC) - started_at).total_seconds() * 1000,
            )
            connection.execute(
                """
                UPDATE traces
                SET status = ?, finished_at = ?, duration_ms = ?,
                    stop_reason = ?, error_type = ?, error_message = ?
                WHERE trace_id = ?
                """,
                (
                    status,
                    self._now(),
                    duration_ms,
                    stop_reason,
                    type(error).__name__ if error else None,
                    self._safe_error(error) if error else None,
                    trace_id,
                ),
            )
            connection.commit()

    def get_trace(self, user_id: str, trace_id: str) -> dict[str, Any] | None:
        owner = user_id.strip()
        with self._connection() as connection:
            trace = connection.execute(
                "SELECT * FROM traces WHERE trace_id = ? AND user_id = ?",
                (trace_id, owner),
            ).fetchone()
            if trace is None:
                return None
            events = connection.execute(
                """
                SELECT event_id, event_type, step_index, tool_call_id, tool_name,
                       status, duration_ms, details_json, created_at
                FROM trace_events WHERE trace_id = ? ORDER BY event_id
                """,
                (trace_id,),
            ).fetchall()
        result = dict(trace)
        result["events"] = [
            {
                **dict(event),
                "details": json.loads(event["details_json"]),
            }
            for event in events
        ]
        for event in result["events"]:
            event.pop("details_json", None)
        return result

    def list_traces(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT trace_id, session_id, status, started_at, finished_at,
                       duration_ms, stop_reason, error_type
                FROM traces WHERE user_id = ?
                ORDER BY started_at DESC LIMIT ?
                """,
                (user_id.strip(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _safe_details(self, details: dict[str, Any]) -> dict[str, Any]:
        """Drop likely credentials and cap all serialized event details."""
        blocked = {"api_key", "authorization", "token", "password", "secret"}
        safe = {
            key: value
            for key, value in details.items()
            if not any(word in key.lower() for word in blocked)
        }
        encoded = json.dumps(safe, ensure_ascii=False, default=str)
        if len(encoded) > self.detail_limit:
            return {"truncated": True, "preview": encoded[: self.detail_limit]}
        return safe

    @staticmethod
    def _safe_error(error: BaseException) -> str:
        # Avoid persisting exception text, which may accidentally contain secrets.
        return type(error).__name__[:120]
