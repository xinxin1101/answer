import asyncio

import pytest
from pydantic import BaseModel, ConfigDict, Field

from min_agent.tools.base import ToolDefinition
from min_agent.tools.registry import ToolRegistry


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


@pytest.mark.asyncio
async def test_registry_exposes_openai_function_schema() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo the supplied text.",
            args_model=EchoArgs,
            handler=lambda args: {"text": args.text},
        )
    )

    schema = registry.schemas()[0]["function"]
    assert schema["name"] == "echo"
    assert schema["parameters"]["type"] == "object"
    assert schema["parameters"]["required"] == ["text"]
    assert schema["parameters"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_registry_validates_arguments_before_execution() -> None:
    called = False

    async def handler(args: EchoArgs) -> dict[str, str]:
        nonlocal called
        called = True
        return {"text": args.text}

    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo", EchoArgs, handler))

    result = await registry.execute("echo", {"text": ""})

    assert result.success is False
    assert "Invalid arguments" in (result.error or "")
    assert called is False


@pytest.mark.asyncio
async def test_registry_executes_valid_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("echo", "Echo", EchoArgs, lambda args: {"text": args.text})
    )

    result = await registry.execute("echo", {"text": "hello"})

    assert result.success is True
    assert result.output == {"text": "hello"}


@pytest.mark.asyncio
async def test_registry_handles_unknown_tool() -> None:
    result = await ToolRegistry().execute("missing", {})

    assert result.success is False
    assert result.error == "Unknown tool: missing"


def test_registry_rejects_duplicate_or_invalid_names() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition("echo", "Echo", EchoArgs, lambda args: args.text)
    registry.register(definition)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(definition)
    with pytest.raises(ValueError, match="Tool name"):
        registry.register(ToolDefinition("Bad Name", "Invalid", EchoArgs, lambda args: args))


@pytest.mark.asyncio
async def test_registry_enforces_async_timeout() -> None:
    async def slow_handler(_: EchoArgs) -> str:
        await asyncio.sleep(0.05)
        return "done"

    registry = ToolRegistry()
    registry.register(
        ToolDefinition("slow", "Slow tool", EchoArgs, slow_handler, timeout_seconds=0.001)
    )

    result = await registry.execute("slow", {"text": "wait"})

    assert result.success is False
    assert "timed out" in (result.error or "")
