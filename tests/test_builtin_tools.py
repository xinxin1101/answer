import pytest

from min_agent.tools.calculator import build_calculator_tool
from min_agent.tools.registry import ToolRegistry
from min_agent.tools.search import build_search_tool
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

    added = await registry.execute("todo", {"action": "add", "title": "Read the README"})
    assert added.success is True
    todo_id = added.output["id"]

    listed = await registry.execute("todo", {"action": "list"})
    assert listed.success is True
    assert listed.output[0]["title"] == "Read the README"
    assert listed.output[0]["completed"] is False

    completed = await registry.execute("todo", {"action": "complete", "todo_id": todo_id})
    assert completed.success is True
    assert completed.output["completed"] is True


@pytest.mark.asyncio
async def test_todo_validates_action_specific_arguments(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_todo_tool(str(tmp_path / "agent.db")))

    result = await registry.execute("todo", {"action": "add"})

    assert result.success is False
    assert "title is required" in (result.error or "")
