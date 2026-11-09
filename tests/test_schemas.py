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


def test_tool_call_defaults_to_empty_arguments() -> None:
    call = ToolCall(id="call-001", name="todo_add")

    assert call.arguments == {}
