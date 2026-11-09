"""Async HTTP adapter for OpenAI-compatible chat completion APIs."""

from collections.abc import Sequence
from typing import Any

import httpx

from min_agent.config import Settings, settings
from min_agent.core.schemas import ChatMessage, LLMResponse
from min_agent.llm.errors import LLMProviderError
from min_agent.llm.parser import parse_chat_completion


class OpenAICompatibleProvider:
    """Call a chat-completions endpoint without relying on an LLM SDK.

    An optional httpx.AsyncClient can be injected for tests or custom transport.
    The provider only closes clients it creates itself.
    """

    def __init__(
        self,
        config: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or settings
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send messages and optional tool schemas; return a normalized response."""
        if not self.config.llm_api_key:
            raise LLMProviderError("LLM_API_KEY is not configured.")

        url = f"{self.config.llm_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.llm_model,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        try:
            response = await self.client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.config.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise LLMProviderError("LLM response body must be a JSON object.")
            return parse_chat_completion(data)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"LLM provider returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("Could not connect to the LLM provider.") from exc
        except ValueError as exc:
            raise LLMProviderError("LLM provider returned invalid JSON.") from exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client only when this provider owns it."""
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "OpenAICompatibleProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
