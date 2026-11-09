"""Shared domain schemas used by the Runtime and LLM adapter."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


MessageRole = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    """One message in the model-facing conversation context."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    """A tool call proposed by the LLM; it is not executed automatically."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


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
