"""Shared SQLite connection settings for safe local concurrent access."""

import sqlite3
from pathlib import Path


SQLITE_TIMEOUT_SECONDS = 10.0
SQLITE_BUSY_TIMEOUT_MS = 10_000


def prepare_database_path(database_path: str) -> None:
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)


def connect_sqlite(database_path: str) -> sqlite3.Connection:
    """Open a configured connection with foreign keys and a busy timeout."""
    connection = sqlite3.connect(
        database_path,
        timeout=SQLITE_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def enable_wal(database_path: str) -> None:
    """Enable WAL for file-backed databases; in-memory DBs do not support it."""
    if database_path == ":memory:":
        return
    prepare_database_path(database_path)
    connection = connect_sqlite(database_path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    finally:
        connection.close()
