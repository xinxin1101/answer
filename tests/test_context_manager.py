from min_agent.context.manager import ContextManager
from min_agent.core.schemas import ChatMessage, ToolCall


def test_context_manager_keeps_recent_turns_and_summarizes_older_ones() -> None:
    history = [
        ChatMessage(role="user", content="My name is Alex."),
        ChatMessage(role="assistant", content="Nice to meet you, Alex."),
        ChatMessage(role="user", content="I work on robotics."),
        ChatMessage(role="assistant", content="I can help with robotics."),
        ChatMessage(role="user", content="What is 1 + 1?"),
        ChatMessage(role="assistant", content="It is 2."),
    ]
    window = ContextManager(max_messages=5).build(history)
    assert window.retained_messages == 4
    assert window.compressed_messages == 2
    assert "My name is Alex" in window.summary
    assert [item.content for item in window.history] == [
        "I work on robotics.", "I can help with robotics.",
        "What is 1 + 1?", "It is 2.",
    ]


def test_context_manager_never_splits_tool_call_and_results() -> None:
    history = [
        ChatMessage(role="user", content="Calculate 1 + 1."),
        ChatMessage(role="assistant", tool_calls=[
            ToolCall(id="call-1", name="calculator", arguments={"expression": "1+1"})
        ]),
        ChatMessage(role="tool", name="calculator", tool_call_id="call-1", content='{"result": 2}'),
        ChatMessage(role="assistant", content="The answer is 2."),
        ChatMessage(role="user", content="Now multiply it by 3."),
        ChatMessage(role="assistant", content="That is 6."),
    ]
    window = ContextManager(max_messages=7).build(history)
    assert window.history[1].tool_calls[0].id == "call-1"
    assert window.history[2].tool_call_id == "call-1"
    assert window.history[3].role == "assistant"


def test_context_manager_rejects_system_history() -> None:
    manager = ContextManager()
    try:
        manager.build([ChatMessage(role="system", content="not allowed")])
    except ValueError as exc:
        assert "system messages" in str(exc)
    else:
        raise AssertionError("system history must be rejected")


def test_context_manager_handles_empty_history() -> None:
    window = ContextManager(max_messages=3).build([])
    assert window.history == []
    assert window.summary is None
