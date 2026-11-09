import pytest

from min_agent.tools.calculator import build_calculator_tool
from min_agent.tools.defaults import build_default_registry
from min_agent.tools.registry import ToolRegistry
from min_agent.tools.search import build_search_tool
from min_agent.tools.base import ToolExecutionContext
from min_agent.tools.todo import build_todo_tool


@pytest.mark.asyncio
async def test_calculator_computes_basic_expression() -> None:
    registry = ToolRegistry()
    registry.register(build_calculator_tool())
    result = await registry.execute("calculator", {"expression": "(12 + 8) * 3 / 2"})
    assert result.success is True
    assert result.output["result"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "open('secret.txt').read()",
        "x + 1",
        "2 ** 999",
        "1 / 0",
    ],
)
async def test_calculator_rejects_unsafe_or_invalid_expressions(expression: str) -> None:
    registry = ToolRegistry()
    registry.register(build_calculator_tool())
    result = await registry.execute("calculator", {"expression": expression})
    assert result.success is False


@pytest.mark.asyncio
async def test_search_mock_returns_deterministic_results() -> None:
    registry = ToolRegistry()
    registry.register(build_search_tool())
    result = await registry.execute("search", {"query": "agent runtime", "limit": 2})
    assert result.success is True
    assert result.output["mock"] is True
    assert result.output["results"][0]["title"] == "Agent Runtime"


@pytest.mark.asyncio
async def test_todo_add_list_complete_persists(tmp_path) -> None:
    database_path = str(tmp_path / "agent.db")
    registry = ToolRegistry()
    registry.register(build_todo_tool(database_path))

    context = ToolExecutionContext(user_id="user-a")
    added = await registry.execute(
        "todo", {"action": "add", "title": "Read the README"}, context=context
    )
    assert added.success is True
    todo_id = added.output["id"]

    listed = await registry.execute("todo", {"action": "list"}, context=context)
    assert listed.success is True
    assert listed.output[0]["title"] == "Read the README"
    assert listed.output[0]["completed"] is False

    completed = await registry.execute(
        "todo", {"action": "complete", "todo_id": todo_id}, context=context
    )
    assert completed.success is True
    assert completed.output["completed"] is True


@pytest.mark.asyncio
async def test_todo_validates_action_specific_arguments(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_todo_tool(str(tmp_path / "agent.db")))
    result = await registry.execute("todo", {"action": "add"})
    assert result.success is False
    assert "title is required" in (result.error or "")


@pytest.mark.asyncio
async def test_todo_supports_in_memory_database() -> None:
    registry = ToolRegistry()
    registry.register(build_todo_tool(":memory:"))
    context = ToolExecutionContext(user_id="user-a")
    added = await registry.execute(
        "todo", {"action": "add", "title": "In-memory task"}, context=context
    )
    listed = await registry.execute("todo", {"action": "list"}, context=context)
    assert added.success is True
    assert len(listed.output) == 1


def test_default_registry_contains_required_tools(tmp_path) -> None:
    from min_agent.config import Settings

    config = Settings(database_path=str(tmp_path / "agent.db"))
    registry = build_default_registry(config)

    assert [tool.name for tool in registry.list_tools()] == [
        "calculator",
        "search",
        "todo",
    ]
    assert {item["function"]["name"] for item in registry.schemas()} == {
        "calculator",
        "search",
        "todo",
    }



@pytest.mark.asyncio
async def test_todo_isolation_and_cross_user_completion_rejection(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_todo_tool(str(tmp_path / "tenant-todos.db")))
    user_a = ToolExecutionContext(user_id="user-a")
    user_b = ToolExecutionContext(user_id="user-b")

    added = await registry.execute(
        "todo",
        {"action": "add", "title": "Private task"},
        context=user_a,
    )
    todo_id = added.output["id"]

    list_a = await registry.execute("todo", {"action": "list"}, context=user_a)
    list_b = await registry.execute("todo", {"action": "list"}, context=user_b)
    foreign_complete = await registry.execute(
        "todo",
        {"action": "complete", "todo_id": todo_id},
        context=user_b,
    )

    assert len(list_a.output) == 1
    assert list_b.output == []
    assert foreign_complete.success is False
    assert "not found for this user" in (foreign_complete.error or "")


@pytest.mark.asyncio
async def test_todo_requires_trusted_context(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_todo_tool(str(tmp_path / "tenant-todos.db")))

    result = await registry.execute(
        "todo",
        {"action": "add", "title": "Should not be created"},
    )

    assert result.success is False
    assert result.error_category == "authorization"


def test_todo_migration_keeps_legacy_rows_unassigned(tmp_path) -> None:
    import sqlite3

    database_path = str(tmp_path / "legacy-todos.db")
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute("INSERT INTO todos (title) VALUES ('old shared task')")
    connection.commit()
    connection.close()

    from min_agent.tools.todo import TodoStore

    store = TodoStore(database_path)
    assert store.list("user-a") == []
    assert store.list("user-b") == []
