"""User-scoped SQLite todo tool with safe legacy-data migration."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from min_agent.storage.sqlite import connect_sqlite, enable_wal, prepare_database_path
from min_agent.tools.base import ToolDefinition, ToolExecutionContext


_LEGACY_OWNER = "__legacy_unassigned__"


class TodoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["add", "list", "complete"] = Field(description="Todo operation.")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    todo_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "TodoArgs":
        if self.action == "add" and not (self.title and self.title.strip()):
            raise ValueError("title is required for add.")
        if self.action == "complete" and self.todo_id is None:
            raise ValueError("todo_id is required for complete.")
        if self.action == "list" and (self.title is not None or self.todo_id is not None):
            raise ValueError("list does not accept title or todo_id.")
        if self.action == "add" and self.todo_id is not None:
            raise ValueError("add does not accept todo_id.")
        if self.action == "complete" and self.title is not None:
            raise ValueError("complete does not accept title.")
        return self


class TodoStore:
    """Persist todos with mandatory user ownership on every operation."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        prepare_database_path(database_path)
        self._memory_connection = (
            connect_sqlite(":memory:") if database_path == ":memory:" else None
        )
        enable_wal(database_path)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._memory_connection is not None:
            with self._memory_connection:
                yield self._memory_connection
            return
        with closing(connect_sqlite(self.database_path)) as connection:
            with connection:
                yield connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '__legacy_unassigned__',
                    title TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(todos)").fetchall()
            }
            if "user_id" not in columns:
                connection.execute(
                    "ALTER TABLE todos ADD COLUMN user_id TEXT NOT NULL "
                    "DEFAULT '__legacy_unassigned__'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_todos_user_id ON todos(user_id, id DESC)"
            )

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        owner = user_id.strip()
        if not owner or owner == _LEGACY_OWNER:
            raise ValueError("A valid authenticated user_id is required.")
        return owner

    def add(self, user_id: str, title: str) -> dict[str, object]:
        owner = self._validate_user_id(user_id)
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be blank")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO todos (user_id, title) VALUES (?, ?)",
                (owner, normalized_title),
            )
            row = connection.execute(
                """
                SELECT id, user_id, title, completed, created_at
                FROM todos WHERE id = ? AND user_id = ?
                """,
                (cursor.lastrowid, owner),
            ).fetchone()
        return self._serialize(row)

    def list(self, user_id: str) -> list[dict[str, object]]:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, completed, created_at
                FROM todos WHERE user_id = ? ORDER BY id DESC
                """,
                (owner,),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def complete(self, user_id: str, todo_id: int) -> dict[str, object]:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE todos SET completed = 1 WHERE id = ? AND user_id = ?",
                (todo_id, owner),
            )
            if cursor.rowcount == 0:
                raise ValueError("Todo was not found for this user.")
            row = connection.execute(
                """
                SELECT id, user_id, title, completed, created_at
                FROM todos WHERE id = ? AND user_id = ?
                """,
                (todo_id, owner),
            ).fetchone()
        return self._serialize(row)

    @staticmethod
    def _serialize(row: sqlite3.Row | None) -> dict[str, object]:
        if row is None:
            raise RuntimeError("Todo record was not found after database operation.")
        return {
            "id": row["id"],
            "title": row["title"],
            "completed": bool(row["completed"]),
            "created_at": row["created_at"],
        }


class TodoHandler:
    def __init__(self, store: TodoStore) -> None:
        self.store = store

    async def __call__(
        self,
        args: TodoArgs,
        context: ToolExecutionContext,
    ) -> dict[str, object] | list[dict[str, object]]:
        user_id = context.user_id
        if args.action == "add":
            return self.store.add(user_id, args.title or "")
        if args.action == "list":
            return self.store.list(user_id)
        return self.store.complete(user_id, args.todo_id or 0)


def build_todo_tool(database_path: str) -> ToolDefinition:
    return ToolDefinition(
        name="todo",
        description=(
            "Manage the authenticated user's todo list. Use action='add' with title to create "
            "a task, action='list' to view tasks, or action='complete' with todo_id to finish one."
        ),
        args_model=TodoArgs,
        handler=TodoHandler(TodoStore(database_path)),
        timeout_seconds=5.0,
        context_aware=True,
    )
