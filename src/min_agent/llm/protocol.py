"""Provider protocol to keep the Runtime independent from a specific LLM SDK."""

from collections.abc import Sequence
from typing import Any, Protocol

from min_agent.core.schemas import ChatMessage, LLMResponse


class LLMProvider(Protocol):
    """Minimal contract expected by the custom Agent Runtime.

    A provider handles model HTTP requests and normalizes responses. It does not
    execute tools, persist conversation history or control the Agent Loop.
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Return a normalized assistant response, optionally with tool calls."""
        ...
