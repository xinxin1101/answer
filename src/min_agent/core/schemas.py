"""Shared domain schemas used by the Runtime and LLM adapter."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MessageRole = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    """A tool call proposed by the LLM; it is not executed automatically."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert the internal call into the OpenAI Chat Completions shape."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


class ChatMessage(BaseModel):
    """One message in the model-facing conversation context."""

    role: MessageRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_message_shape(self) -> "ChatMessage":
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("tool messages require tool_call_id")
            if self.content is None:
                raise ValueError("tool messages require content")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for tool messages")

        if self.tool_calls and self.role != "assistant":
            raise ValueError("only assistant messages can contain tool_calls")
        if self.role in {"system", "user"} and self.content is None:
            raise ValueError(f"{self.role} messages require content")

        call_ids = [call.id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call ids must be unique within an assistant message")
        return self

    def to_openai_dict(self) -> dict[str, Any]:
        """Serialize a message using the OpenAI-compatible chat message shape."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = [call.to_openai_dict() for call in self.tool_calls]
        return payload


class LLMResponse(BaseModel):
    """Normalized response returned by an LLM provider adapter."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    decision_summary: str | None = None


class AgentRunRequest(BaseModel):
    """Input contract for a future Agent execution endpoint."""

    message: str = Field(min_length=1)
    session_id: str | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class AgentRunResponse(BaseModel):
    """Output contract for a future Agent execution endpoint."""

    session_id: str
    reply: str
    trace_id: str
