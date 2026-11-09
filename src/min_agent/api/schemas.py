"""HTTP request schemas for the public Chat API."""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """One user message, optionally continuing an existing session."""

    message: str = Field(min_length=1, max_length=10000)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value
