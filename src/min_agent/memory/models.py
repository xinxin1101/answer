"""Domain models for long-term user memories."""

from typing import Literal

from pydantic import BaseModel, Field

MemoryCategory = Literal["preference", "profile", "project", "workflow", "other"]


class MemoryItem(BaseModel):
    """A persisted memory owned by one user."""

    memory_id: str
    user_id: str
    memory_key: str
    content: str
    category: MemoryCategory
    source: str = "explicit_user_statement"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    status: str = "active"
    created_at: str
    updated_at: str
    expires_at: str | None = None


class MemoryCandidate(BaseModel):
    """A candidate extracted from an explicit user statement."""

    memory_key: str
    content: str
    category: MemoryCategory
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    expires_at: str | None = None


class MemorySearchResult(BaseModel):
    """A memory and its query relevance score."""

    item: MemoryItem
    score: float
