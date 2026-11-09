"""SQLite persistence and keyword retrieval for long-term memories."""

import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from min_agent.memory.models import (
    MemoryCandidate,
    MemoryItem,
    MemorySearchResult,
)


class MemoryStore:
    """Persist memories with strict user ownership boundaries."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection = (
            sqlite3.connect(":memory:", timeout=5.0)
            if database_path == ":memory:"
            else None
        )
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
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    UNIQUE(user_id, memory_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_user_status
                ON memories(user_id, status)
                """
            )
            connection.commit()

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        owner = user_id.strip()
        if not owner:
            raise ValueError("user_id must not be blank")
        return owner

    @staticmethod
    def _to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(**dict(row))

    def upsert(
        self,
        user_id: str,
        candidate: MemoryCandidate,
    ) -> MemoryItem:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND memory_key = ?
                """,
                (owner, candidate.memory_key),
            ).fetchone()

            if existing is None:
                memory_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO memories (
                        memory_id, user_id, memory_key, content,
                        category, source, confidence, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        owner,
                        candidate.memory_key,
                        candidate.content,
                        candidate.category,
                        "explicit_user_statement",
                        candidate.confidence,
                        candidate.expires_at,
                    ),
                )
            else:
                memory_id = existing["memory_id"]
                connection.execute(
                    """
                    UPDATE memories
                    SET content = ?, category = ?, confidence = ?,
                        status = 'active', updated_at = CURRENT_TIMESTAMP,
                        expires_at = ?
                    WHERE user_id = ? AND memory_key = ?
                    """,
                    (
                        candidate.content,
                        candidate.category,
                        candidate.confidence,
                        candidate.expires_at,
                        owner,
                        candidate.memory_key,
                    ),
                )

            connection.commit()
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            return self._to_item(row)

    def list_active(self, user_id: str) -> list[MemoryItem]:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                ORDER BY updated_at DESC, memory_id
                """,
                (owner,),
            ).fetchall()
        return [self._to_item(row) for row in rows]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return set(
            re.findall(
                r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}",
                text.lower(),
            )
        )

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        query_terms = self._terms(query)
        ranked: list[MemorySearchResult] = []
        for item in self.list_active(user_id):
            memory_terms = self._terms(item.content + " " + item.category)
            overlap = len(query_terms & memory_terms)
            if overlap == 0:
                continue

            coverage = overlap / max(1, len(query_terms))
            precision = overlap / max(1, len(memory_terms))
            score = 0.75 * coverage + 0.25 * precision
            ranked.append(MemorySearchResult(item=item, score=score))

        ranked.sort(key=lambda result: (-result.score, result.item.updated_at))
        return ranked[:limit]

    def archive(self, user_id: str, memory_id: str) -> bool:
        owner = self._validate_user_id(user_id)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE memories
                SET status = 'archived', updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND memory_id = ? AND status = 'active'
                """,
                (owner, memory_id),
            )
            connection.commit()
            return cursor.rowcount > 0
