import pytest

from min_agent.core.schemas import LLMResponse
from min_agent.llm.errors import LLMProviderError
from min_agent.llm.parser import parse_chat_completion


def test_parse_text_completion() -> None:
    result = parse_chat_completion(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    assert result == LLMResponse(content="Hello!", finish_reason="stop")
    assert result.tool_calls == []


def test_parse_tool_call_arguments_from_json_string() -> None:
    result = parse_chat_completion(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "calculator",
                                    "arguments": "{\"expression\":\"1 + 2\"}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].arguments == {"expression": "1 + 2"}
    assert result.finish_reason == "tool_calls"


def test_parser_rejects_invalid_tool_json() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "calculator", "arguments": "{bad json"},
                        }
                    ],
                }
            }
        ]
    }
    with pytest.raises(LLMProviderError, match="invalid JSON arguments"):
        parse_chat_completion(payload)


def test_parser_rejects_non_object_tool_arguments() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "calculator", "arguments": "[1, 2]"},
                        }
                    ],
                }
            }
        ]
    }
    with pytest.raises(LLMProviderError, match="JSON object"):
        parse_chat_completion(payload)


def test_parser_rejects_empty_choices() -> None:
    with pytest.raises(LLMProviderError, match="no choices"):
        parse_chat_completion({"choices": []})
