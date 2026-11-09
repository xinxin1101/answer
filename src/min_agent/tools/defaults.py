"""Factory for the built-in tools required by the exercise."""

from min_agent.config import Settings, settings
from min_agent.tools.calculator import build_calculator_tool
from min_agent.tools.registry import ToolRegistry
from min_agent.tools.search import build_search_tool
from min_agent.tools.todo import build_todo_tool


def build_default_registry(config: Settings | None = None) -> ToolRegistry:
    """Create a fresh registry with calculator, mock search and SQLite todo."""
    config = config or settings
    registry = ToolRegistry()
    registry.register(build_calculator_tool())
    registry.register(build_search_tool())
    registry.register(build_todo_tool(config.database_path))
    return registry
