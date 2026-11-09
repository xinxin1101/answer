"""A deterministic mock search tool for offline development and tests."""

from pydantic import BaseModel, ConfigDict, Field

from min_agent.tools.base import ToolDefinition


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200, description="Search query.")
    limit: int = Field(default=3, ge=1, le=5, description="Maximum number of results.")


MOCK_DOCUMENTS = [
    {
        "title": "Agent Runtime",
        "snippet": "An Agent Runtime coordinates model calls, tool execution, context and stopping conditions.",
        "keywords": {"agent", "runtime", "loop", "tool"},
    },
    {
        "title": "Tool Calling",
        "snippet": "The model proposes structured tool calls; the application validates and executes them.",
        "keywords": {"tool", "calling", "schema", "function"},
    },
    {
        "title": "Memory and Context",
        "snippet": "Conversation history, summaries and relevant long-term memories form the model context.",
        "keywords": {"memory", "context", "history", "summary"},
    },
]


async def search_mock(args: SearchArgs) -> dict[str, object]:
    """Return predictable local results; no external network request is made."""
    terms = set(args.query.lower().split())
    ranked = sorted(
        MOCK_DOCUMENTS,
        key=lambda item: len(terms.intersection(item["keywords"])),
        reverse=True,
    )
    matches = [
        {"title": item["title"], "snippet": item["snippet"]}
        for item in ranked
        if terms.intersection(item["keywords"])
    ]
    return {"query": args.query, "mock": True, "results": matches[: args.limit]}


def build_search_tool() -> ToolDefinition:
    return ToolDefinition(
        name="search",
        description="Search a small built-in mock knowledge set. This tool works offline.",
        args_model=SearchArgs,
        handler=search_mock,
        timeout_seconds=2.0,
    )
