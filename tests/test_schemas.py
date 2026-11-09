import pytest
from pydantic import ValidationError

from min_agent.core.schemas import AgentRunRequest, ChatMessage, ToolCall


def test_agent_request_accepts_non_empty_message() -> None:
    request = AgentRunRequest(message="Calculate 1 + 2", session_id="session-a")

    assert request.message == "Calculate 1 + 2"
    assert request.session_id == "session-a"


def test_agent_request_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValidationError):
        AgentRunRequest(message="   ")


def test_chat_message_supports_tool_result_role() -> None:
    message = ChatMessage(
        role="tool",
        name="calculator",
        tool_call_id="call-001",
        content="3",
    )

    assert message.role == "tool"
    assert message.tool_call_id == "call-001"


def test_chat_message_serializes_assistant_tool_calls_in_openai_shape() -> None:
    message = ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id="call-001",
                name="calculator",
                arguments={"expression": "1 + 2"},
            )
        ],
    )

    payload = message.to_openai_dict()

    assert payload["role"] == "assistant"
    assert payload["content"] is None
    assert payload["tool_calls"][0] == {
        "id": "call-001",
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": '{"expression": "1 + 2"}',
        },
    }


def test_chat_message_rejects_tool_message_without_call_id() -> None:
    with pytest.raises(ValidationError, match="require tool_call_id"):
        ChatMessage(role="tool", content="3")


def test_tool_call_defaults_to_empty_arguments() -> None:
    call = ToolCall(id="call-001", name="todo_add")

    assert call.arguments == {}
