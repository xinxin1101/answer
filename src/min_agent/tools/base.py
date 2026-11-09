"""Core contracts for tools executed by the custom Agent Runtime."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

ToolHandler = Callable[..., Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Trusted execution metadata supplied by Runtime, never by model arguments."""

    user_id: str
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A tool's public description, validated argument model and handler."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float = 10.0
    context_aware: bool = False


class ToolExecutionResult(BaseModel):
    """A normalized tool execution result safe to append to model context."""

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    error_category: str | None = None
