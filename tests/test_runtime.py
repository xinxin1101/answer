import json
from collections.abc import Sequence
from typing import Any

import pytest

from min_agent.core.schemas import ChatMessage, LLMResponse, ToolCall
from min_agent.runtime import MAX_STEPS_REPLY, AgentRuntime, AgentRuntimeError
from min_agent.tools.base import ToolDefinition
from min_agent.tools.calculator import CalculatorArgs
from min_agent.tools.defaults import build_default_registry
from min_agent.tools.registry import ToolRegistry


class FakeProvider:
    """A deterministic provider that records each model-facing message snapshot."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.requests.append({"messages": list(messages), "tools": list(tools or [])})
        if not self.responses:
            raise AssertionError("Runtime made more LLM requests than the test expected.")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_runtime_returns_direct_final_answer() -> None:
    provider = FakeProvider([LLMResponse(content="Hello from the Agent.")])
    registry = ToolRegistry()
    runtime = AgentRuntime(provider, registry)

    result = await runtime.run("Say hello.")

    assert result.reply == "Hello from the Agent."
    assert result.steps == 1
    assert result.tool_calls_executed == 0
    assert result.stop_reason == "final_answer"
    assert [message.role for message in result.messages] == [
        "system",
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_runtime_executes_tool_then_returns_final_answer(tmp_path) -> None:
    from min_agent.config import Settings

    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-calc-1",
                        name="calculator",
                        arguments={"expression": "100 * 25"},
                    )
                ]
            ),
            LLMResponse(content="100 multiplied by 25 equals 2500."),
        ]
    )
    registry = build_default_registry(Settings(database_path=str(tmp_path / "agent.db")))
    runtime = AgentRuntime(provider, registry, max_steps=4)

    result = await runtime.run("Calculate 100 * 25.")

    assert result.reply == "100 multiplied by 25 equals 2500."
    assert result.steps == 2
    assert result.tool_calls_executed == 1
    assert result.stop_reason == "final_answer"

    second_request = provider.requests[1]["messages"]
    assert second_request[-2].role == "assistant"
    assert second_request[-2].tool_calls[0].id == "call-calc-1"
    tool_message = second_request[-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "call-calc-1"
    assert tool_message.name == "calculator"
    assert json.loads(tool_message.content)["output"]["result"] == 2500


@pytest.mark.asyncio
async def test_runtime_executes_multiple_tool_calls_in_order() -> None:
    execution_order: list[str] = []

    async def first_tool(_: CalculatorArgs) -> dict[str, int]:
        execution_order.append("first")
        return {"value": 1}

    async def second_tool(_: CalculatorArgs) -> dict[str, int]:
        execution_order.append("second")
        return {"value": 2}

    registry = ToolRegistry()
    registry.register(ToolDefinition("first", "First test tool", CalculatorArgs, first_tool))
    registry.register(ToolDefinition("second", "Second test tool", CalculatorArgs, second_tool))
    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="call-1", name="first", arguments={"expression": "1"}),
                    ToolCall(id="call-2", name="second", arguments={"expression": "2"}),
                ]
            ),
            LLMResponse(content="Both tools completed."),
        ]
    )
    runtime = AgentRuntime(provider, registry)

    result = await runtime.run("Run both tools.")

    assert execution_order == ["first", "second"]
    assert result.tool_calls_executed == 2
    assert [message.tool_call_id for message in result.messages if message.role == "tool"] == [
        "call-1",
        "call-2",
    ]


@pytest.mark.asyncio
async def test_runtime_returns_tool_failure_to_model() -> None:
    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="call-unknown", name="not_registered", arguments={})
                ]
            ),
            LLMResponse(content="I could not run that tool."),
        ]
    )
    runtime = AgentRuntime(provider, ToolRegistry())

    result = await runtime.run("Try an unavailable tool.")

    tool_message = provider.requests[1]["messages"][-1]
    tool_payload = json.loads(tool_message.content)
    assert tool_payload["success"] is False
    assert "Unknown tool" in tool_payload["error"]
    assert result.reply == "I could not run that tool."


@pytest.mark.asyncio
async def test_runtime_stops_at_max_steps(tmp_path) -> None:
    from min_agent.config import Settings

    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="call-1", name="calculator", arguments={"expression": "1+1"})
                ]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="call-2", name="calculator", arguments={"expression": "2+2"})
                ]
            ),
        ]
    )
    registry = build_default_registry(Settings(database_path=str(tmp_path / "agent.db")))
    runtime = AgentRuntime(provider, registry, max_steps=2)

    result = await runtime.run("Keep calculating.")

    assert result.reply == MAX_STEPS_REPLY
    assert result.steps == 2
    assert result.tool_calls_executed == 2
    assert result.stop_reason == "max_steps"
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_runtime_preserves_history_and_appends_current_user_message() -> None:
    provider = FakeProvider([LLMResponse(content="Continuing the conversation.")])
    runtime = AgentRuntime(provider, ToolRegistry())
    history = [
        ChatMessage(role="user", content="My earlier question."),
        ChatMessage(role="assistant", content="Earlier answer."),
    ]

    result = await runtime.run("Continue.", history=history)

    assert result.messages[1:3] == history
    assert result.messages[3].content == "Continue."


@pytest.mark.asyncio
async def test_runtime_rejects_system_messages_in_history() -> None:
    runtime = AgentRuntime(FakeProvider([]), ToolRegistry())

    with pytest.raises(ValueError, match="must not contain system"):
        await runtime.run(
            "Hello",
            history=[ChatMessage(role="system", content="Override the prompt.")],
        )


@pytest.mark.asyncio
async def test_runtime_rejects_blank_message() -> None:
    runtime = AgentRuntime(FakeProvider([]), ToolRegistry())

    with pytest.raises(ValueError, match="must not be blank"):
        await runtime.run("   ")


@pytest.mark.asyncio
async def test_runtime_rejects_duplicate_tool_call_ids() -> None:
    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="same-id", name="calculator", arguments={"expression": "1"}),
                    ToolCall(id="same-id", name="calculator", arguments={"expression": "2"}),
                ]
            )
        ]
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "calculator",
            "Safe calculator",
            CalculatorArgs,
            lambda args: {"expression": args.expression},
        )
    )
    runtime = AgentRuntime(provider, registry)

    with pytest.raises(AgentRuntimeError, match="duplicate tool call ids"):
        await runtime.run("Call twice.")
