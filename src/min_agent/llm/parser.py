"""Parse OpenAI-compatible chat completion payloads into domain schemas."""

import json
from typing import Any

from pydantic import ValidationError

from min_agent.core.schemas import LLMResponse, ToolCall
from min_agent.llm.errors import LLMProviderError


def parse_chat_completion(payload: dict[str, Any]) -> LLMResponse:
    """Normalize the first assistant choice from a chat completion response."""
    try:
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise LLMProviderError("LLM response contains no choices.")
        choice = choices[0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise LLMProviderError("LLM response message must be an object.")

        raw_tool_calls = message.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list):
            raise LLMProviderError("LLM tool_calls must be a list.")

        tool_calls: list[ToolCall] = []
        for raw_call in raw_tool_calls:
            function = raw_call["function"]
            raw_arguments = function.get("arguments", "{}")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise LLMProviderError(
                        f"Tool call '{function.get('name', 'unknown')}' has invalid JSON arguments."
                    ) from exc
            else:
                arguments = raw_arguments
            if not isinstance(arguments, dict):
                raise LLMProviderError("Tool call arguments must decode to a JSON object.")
            tool_calls.append(
                ToolCall(id=raw_call["id"], name=function["name"], arguments=arguments)
            )

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )
    except LLMProviderError:
        raise
    except (KeyError, TypeError, ValidationError) as exc:
        raise LLMProviderError("LLM response has an unexpected OpenAI-compatible shape.") from exc
