import json

import httpx
import pytest

from min_agent.config import Settings
from min_agent.core.schemas import ChatMessage, ToolCall
from min_agent.llm.errors import LLMProviderError
from min_agent.llm.openai_compatible import OpenAICompatibleProvider


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "test-secret",
        "llm_model": "test-model",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_provider_sends_openai_compatible_request() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "2"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(make_settings(), client=client)
    result = await provider.complete([ChatMessage(role="user", content="1 + 1?")])

    assert result.content == "2"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-secret"
    assert seen["body"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "1 + 1?"}],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_includes_tool_schemas_when_supplied() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == "auto"
        assert body["tools"][0]["function"]["name"] == "calculator"
        return httpx.Response(
            200,
            json={
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
                                        "arguments": "{\"expression\":\"2*3\"}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(make_settings(), client=client)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Calculate an expression",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            },
        }
    ]
    result = await provider.complete([ChatMessage(role="user", content="2*3")], tools=tools)
    assert result.tool_calls[0].arguments == {"expression": "2*3"}
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_requires_api_key() -> None:
    provider = OpenAICompatibleProvider(make_settings(llm_api_key=None))
    with pytest.raises(LLMProviderError, match="not configured"):
        await provider.complete([ChatMessage(role="user", content="hello")])
    await provider.aclose()


@pytest.mark.asyncio
async def test_provider_sanitizes_http_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "secret diagnostic"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(make_settings(), client=client)
    with pytest.raises(LLMProviderError, match="HTTP 401") as error:
        await provider.complete([ChatMessage(role="user", content="hello")])
    assert "secret diagnostic" not in str(error.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_serializes_assistant_tool_call_and_tool_result_messages() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "The result is 3."},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    messages = [
        ChatMessage(role="user", content="Calculate 1 + 2."),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="calculator",
                    arguments={"expression": "1 + 2"},
                )
            ],
        ),
        ChatMessage(
            role="tool",
            name="calculator",
            tool_call_id="call-1",
            content='{"tool_name":"calculator","success":true,"output":{"result":3}}',
        ),
    ]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(make_settings(), client=client)

    result = await provider.complete(messages)

    serialized = seen["messages"]
    assert serialized[1]["tool_calls"][0]["function"]["name"] == "calculator"
    assert serialized[1]["tool_calls"][0]["id"] == "call-1"
    assert serialized[2]["role"] == "tool"
    assert serialized[2]["tool_call_id"] == "call-1"
    assert result.content == "The result is 3."
    await client.aclose()
