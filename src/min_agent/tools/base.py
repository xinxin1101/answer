"""Core contracts for tools executed by the custom Agent Runtime."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

ToolHandler = Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A tool's public description, validated argument model and handler."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float = 10.0


class ToolExecutionResult(BaseModel):
    """A normalized tool execution result safe to append to model context."""

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
