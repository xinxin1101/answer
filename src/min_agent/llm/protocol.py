"""Provider protocol to keep the Runtime independent from a specific LLM SDK."""

from collections.abc import Sequence
from typing import Any, Protocol

from min_agent.core.schemas import ChatMessage, LLMResponse


class LLMProvider(Protocol):
    """Minimal contract expected by the custom Agent Runtime.

    Concrete OpenAI-compatible HTTP integration will be added in the LLM
    integration phase. Keeping this as a protocol makes the Runtime testable
    with deterministic fake providers.
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Return a normalized assistant response, optionally with tool calls."""
        ...
