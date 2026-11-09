"""Turn-aware sliding window and deterministic conversation summary."""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from min_agent.core.schemas import ChatMessage


class ContextWindow(BaseModel):
    history: list[ChatMessage] = Field(default_factory=list)
    summary: str | None = None
    original_messages: int = 0
    retained_messages: int = 0
    compressed_messages: int = 0


class ContextManager:
    """Keep recent complete turns; summarize older turns without deleting source history."""

    def __init__(self, max_messages: int = 20, summary_char_limit: int = 3000) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2")
        if summary_char_limit < 200:
            raise ValueError("summary_char_limit must be at least 200")
        self.max_messages = max_messages
        self.summary_char_limit = summary_char_limit

    def build(self, messages: Sequence[ChatMessage]) -> ContextWindow:
        if any(item.role == "system" for item in messages):
            raise ValueError("stored history must not contain system messages")
        groups = self._group_turns(messages)
        budget = self.max_messages - 1
        kept: list[list[ChatMessage]] = []
        count = 0
        for group in reversed(groups):
            if kept and count + len(group) > budget:
                break
            kept.append(group)
            count += len(group)
            if count >= budget:
                break
        kept.reverse()
        retained = [item for group in kept for item in group]
        old_groups = groups[: len(groups) - len(kept)]
        compressed = [item for group in old_groups for item in group]
        summary = self._summarize(compressed) if compressed else None
        return ContextWindow(
            history=retained,
            summary=summary,
            original_messages=len(messages),
            retained_messages=len(retained),
            compressed_messages=len(compressed),
        )

    @staticmethod
    def _group_turns(messages: Sequence[ChatMessage]) -> list[list[ChatMessage]]:
        groups: list[list[ChatMessage]] = []
        current: list[ChatMessage] = []
        for item in messages:
            if item.role == "user" and current:
                groups.append(current)
                current = []
            current.append(item)
            if item.role == "assistant" and not item.tool_calls:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups

    def _summarize(self, messages: Sequence[ChatMessage]) -> str:
        lines: list[str] = []
        for item in messages:
            if item.role == "assistant" and item.tool_calls:
                names = ", ".join(call.name for call in item.tool_calls)
                lines.append(f"Assistant requested tools: {names}.")
                continue
            content = (item.content or "").strip()
            if not content:
                continue
            label = {"user": "User", "assistant": "Assistant", "tool": "Tool"}.get(
                item.role, item.role
            )
            if item.role == "tool":
                content = content[:240]
                label += f" {item.name or 'unknown'} result"
            else:
                content = content[:400]
            lines.append(f"{label}: {content}")
        return (
            "Earlier conversation summary (compressed from prior turns):\n"
            + "\n".join(lines)
        )[: self.summary_char_limit]
