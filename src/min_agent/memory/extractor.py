"""Conservative rule-based extraction of durable user statements."""

import re

from min_agent.memory.models import MemoryCandidate

_RULES = [
    (r"(?:以后|今后|长期|一直)[^。！？；;]{2,90}", "preference"),
    (r"(?:我偏好|我喜欢|我习惯|我通常使用).{2,60}", "preference"),
    (r"(?:我的项目|目前项目).{2,70}(?:使用|采用|基于|技术栈).{2,70}", "project"),
    (r"(?:我是|我的专业是|我目前就读于).{2,50}", "profile"),
]


class MemoryExtractor:
    """Extract only explicit durable statements from user input."""

    def extract(self, user_message: str) -> list[MemoryCandidate]:
        text = " ".join(user_message.split()).strip()
        if not text or len(text) > 1000:
            return []

        found: dict[str, MemoryCandidate] = {}
        for pattern, category in _RULES:
            match = re.search(pattern, text)
            if match is None:
                continue

            content = match.group().strip(" ，。；;")
            normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", content.lower())
            memory_key = f"{category}:{normalized[:100]}"
            found[memory_key] = MemoryCandidate(
                memory_key=memory_key,
                content=content,
                category=category,
            )

        return list(found.values())
