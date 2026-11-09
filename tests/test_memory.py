"""Tests for long-term memory extraction, persistence and retrieval."""

from min_agent.memory.extractor import MemoryExtractor
from min_agent.memory.models import MemoryCandidate
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore


def test_extraction_is_conservative() -> None:
    extractor = MemoryExtractor()
    candidates = extractor.extract("以后我所有后端项目都优先使用 FastAPI。")

    assert candidates
    assert "FastAPI" in candidates[0].content
    assert extractor.extract("今天帮我写一个 Python 脚本") == []


def test_isolation_and_upsert(tmp_path) -> None:
    store = MemoryStore(str(tmp_path / "memory.db"))
    first_candidate = MemoryCandidate(
        memory_key="preference:stack",
        content="Prefer Flask",
        category="preference",
    )
    updated_candidate = MemoryCandidate(
        memory_key="preference:stack",
        content="Prefer FastAPI",
        category="preference",
    )

    first = store.upsert("user-a", first_candidate)
    updated = store.upsert("user-a", updated_candidate)

    assert first.memory_id == updated.memory_id
    assert updated.content == "Prefer FastAPI"
    assert store.list_active("user-b") == []


def test_retrieval_and_archive(tmp_path) -> None:
    store = MemoryStore(str(tmp_path / "memory.db"))
    service = MemoryService(store)
    service.remember_from_user_message(
        "user-a",
        "以后我所有后端项目都优先使用 FastAPI。",
    )
    service.remember_from_user_message(
        "user-a",
        "我的项目目前使用 React 和 TypeScript。",
    )

    results = store.search("user-a", "FastAPI 后端开发")
    assert results
    assert "FastAPI" in results[0].item.content
    assert store.archive("user-a", results[0].item.memory_id)
    assert len(store.list_active("user-a")) == 1
