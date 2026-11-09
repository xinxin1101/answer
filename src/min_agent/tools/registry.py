"""Tool registration, schema exposure, validation and controlled execution."""

import asyncio
import inspect
import re
from typing import Any

from pydantic import ValidationError

from min_agent.tools.base import (
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
)

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ToolNotFoundError(LookupError):
    """Raised when a requested tool is not registered."""


class ToolRegistry:
    """In-memory registry with schema validation and explicit trusted context."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not _TOOL_NAME_PATTERN.fullmatch(tool.name):
            raise ValueError("Tool name must use lowercase letters, digits and underscores.")
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        if tool.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be greater than zero.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_model.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolExecutionResult:
        """Validate model arguments, then execute with trusted runtime context."""
        try:
            tool = self.get(name)
        except ToolNotFoundError:
            return ToolExecutionResult(
                tool_name=name,
                success=False,
                error=f"Unknown tool: {name}",
                error_category="not_found",
            )

        try:
            validated_args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: {item['msg']}"
                for item in exc.errors()
            )
            return ToolExecutionResult(
                tool_name=name,
                success=False,
                error=f"Invalid arguments: {details}",
                error_category="validation",
            )

        if tool.context_aware and (context is None or not context.user_id.strip()):
            return ToolExecutionResult(
                tool_name=name,
                success=False,
                error="Trusted user context is required for this tool.",
                error_category="authorization",
            )

        try:
            if tool.context_aware:
                result = tool.handler(validated_args, context)
            else:
                result = tool.handler(validated_args)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=tool.timeout_seconds)
            return ToolExecutionResult(tool_name=name, success=True, output=result)
        except TimeoutError:
            return ToolExecutionResult(
                tool_name=name,
                success=False,
                error=f"Tool '{name}' timed out.",
                error_category="timeout",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name=name,
                success=False,
                error=f"Tool '{name}' failed ({type(exc).__name__}).",
                error_category="tool_execution",
            )
