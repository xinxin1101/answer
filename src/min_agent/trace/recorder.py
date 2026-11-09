"""SQLite-backed execution tracing with pagination, retention and error taxonomy."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from min_agent.storage.sqlite import connect_sqlite, enable_wal, prepare_database_path


class TraceRecorder:
    """Persist safe trace metadata and ordered events without storing secrets."""

    def __init__(self, database_path: str, detail_limit: int = 1000) -> None:
        self.database_path = database_path
        self.detail_limit = detail_limit
        prepare_database_path(database_path)
        self._memory_connection = (
            connect_sqlite(":memory:") if database_path == ":memory:" else None
        )
        self._memory_lock = RLock()
        enable_wal(database_path)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._memory_connection
        if connection is not None:
            with self._memory_lock, connection:
                yield connection
            return
        with closing(connect_sqlite(self.database_path)) as connection:
            with connection:
                yield connection

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
                    error_category TEXT,
                    error_message TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(traces)").fetchall()
            }
            if "error_category" not in columns:
                connection.execute("ALTER TABLE traces ADD COLUMN error_category TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_traces_user_started
                ON traces(user_id, started_at DESC, trace_id DESC)
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

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        owner = user_id.strip()
        if not owner:
            raise ValueError("user_id must not be blank")
        return owner

    def start_trace(self, user_id: str, session_id: str) -> str:
        owner = self._validate_user_id(user_id)
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
                    stop_reason = ?, error_type = ?, error_category = ?,
                    error_message = ?
                WHERE trace_id = ?
                """,
                (
                    status,
                    self._now(),
                    duration_ms,
                    stop_reason,
                    type(error).__name__ if error else None,
                    self.classify_error(error) if error else None,
                    self._safe_error(error) if error else None,
                    trace_id,
                ),
            )

    def get_trace(
        self,
        user_id: str,
        trace_id: str,
        *,
        event_limit: int = 100,
        after_event_id: int = 0,
    ) -> dict[str, Any] | None:
        if not 1 <= event_limit <= 500:
            raise ValueError("event_limit must be between 1 and 500")
        if after_event_id < 0:
            raise ValueError("after_event_id must be zero or greater")
        owner = self._validate_user_id(user_id)
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
                FROM trace_events
                WHERE trace_id = ? AND event_id > ?
                ORDER BY event_id ASC LIMIT ?
                """,
                (trace_id, after_event_id, event_limit + 1),
            ).fetchall()

        has_more = len(events) > event_limit
        page = events[:event_limit]
        result = dict(trace)
        result["events"] = [
            {
                **dict(event),
                "details": json.loads(event["details_json"]),
            }
            for event in page
        ]
        for event in result["events"]:
            event.pop("details_json", None)
        result["has_more_events"] = has_more
        result["next_after_event_id"] = (
            page[-1]["event_id"] if has_more and page else None
        )
        return result

    def list_traces(
        self,
        user_id: str,
        limit: int = 20,
        before_started_at: str | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            if before_started_at:
                rows = connection.execute(
                    """
                    SELECT trace_id, session_id, status, started_at, finished_at,
                           duration_ms, stop_reason, error_type, error_category
                    FROM traces
                    WHERE user_id = ? AND started_at < ?
                    ORDER BY started_at DESC, trace_id DESC LIMIT ?
                    """,
                    (owner, before_started_at, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT trace_id, session_id, status, started_at, finished_at,
                           duration_ms, stop_reason, error_type, error_category
                    FROM traces WHERE user_id = ?
                    ORDER BY started_at DESC, trace_id DESC LIMIT ?
                    """,
                    (owner, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def prune_older_than(self, retention_days: int) -> int:
        """Delete finished traces older than the retention window."""
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM traces
                WHERE status IN ('succeeded', 'failed')
                  AND finished_at IS NOT NULL
                  AND julianday(finished_at) < julianday('now', ?)
                """,
                (f"-{retention_days} days",),
            )
            return cursor.rowcount

    @staticmethod
    def classify_error(error: BaseException) -> str:
        """Map implementation exceptions to stable, queryable categories."""
        name = type(error).__name__.lower()
        module = type(error).__module__.lower()
        if "cancel" in name:
            return "cancelled"
        if isinstance(error, TimeoutError) or "timeout" in name:
            return "timeout"
        if isinstance(error, sqlite3.Error):
            return "storage"
        if "provider" in name or ".llm" in module:
            return "provider"
        if isinstance(error, (ValueError, TypeError)):
            return "validation"
        if ".tools" in module:
            return "tool_execution"
        return "internal"

    def _safe_details(self, details: dict[str, Any]) -> dict[str, Any]:
        """Drop likely credentials and cap all serialized event details."""
        blocked = ("api_key", "authorization", "token", "password", "secret")

        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: clean(item)
                    for key, item in value.items()
                    if not any(word in key.lower() for word in blocked)
                }
            if isinstance(value, list):
                return [clean(item) for item in value[:100]]
            return value

        safe = clean(details)
        encoded = json.dumps(safe, ensure_ascii=False, default=str)
        if len(encoded) > self.detail_limit:
            return {"truncated": True, "preview": encoded[: self.detail_limit]}
        return safe

    @staticmethod
    def _safe_error(error: BaseException) -> str:
        # Never persist exception text; providers may echo request details or secrets.
        return type(error).__name__[:120]
