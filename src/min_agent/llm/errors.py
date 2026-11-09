"""Errors raised while communicating with or parsing LLM responses."""


class LLMProviderError(RuntimeError):
    """A safe, provider-agnostic error for failed LLM requests or responses."""
