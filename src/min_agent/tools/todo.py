"""SQLite-backed todo tool with add, list and complete operations."""

import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from min_agent.tools.base import ToolDefinition


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
    """Small SQLite repository; each operation uses its own short-lived connection."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=5.0)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add(self, title: str) -> dict[str, object]:
        with self._connect() as connection:
            cursor = connection.execute("INSERT INTO todos (title) VALUES (?)", (title.strip(),))
            row = connection.execute(
                "SELECT id, title, completed, created_at FROM todos WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._serialize(row)

    def list(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, completed, created_at FROM todos ORDER BY id DESC"
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def complete(self, todo_id: int) -> dict[str, object]:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE todos SET completed = 1 WHERE id = ?",
                (todo_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Todo {todo_id} does not exist.")
            row = connection.execute(
                "SELECT id, title, completed, created_at FROM todos WHERE id = ?",
                (todo_id,),
            ).fetchone()
        return self._serialize(row)

    @staticmethod
    def _serialize(row: tuple[object, ...] | None) -> dict[str, object]:
        if row is None:
            raise RuntimeError("Todo record was not found after database operation.")
        return {
            "id": row[0],
            "title": row[1],
            "completed": bool(row[2]),
            "created_at": row[3],
        }


class TodoHandler:
    def __init__(self, store: TodoStore) -> None:
        self.store = store

    async def __call__(self, args: TodoArgs) -> dict[str, object] | list[dict[str, object]]:
        if args.action == "add":
            return self.store.add(args.title or "")
        if args.action == "list":
            return self.store.list()
        return self.store.complete(args.todo_id or 0)


def build_todo_tool(database_path: str) -> ToolDefinition:
    return ToolDefinition(
        name="todo",
        description=(
            "Manage the user's todo list. Use action='add' with title to create a task, "
            "action='list' to view tasks, or action='complete' with todo_id to finish one."
        ),
        args_model=TodoArgs,
        handler=TodoHandler(TodoStore(database_path)),
        timeout_seconds=5.0,
    )
