from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def normalize_role_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("role id is required")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if any(ch not in allowed for ch in normalized):
        raise ValueError("role id may contain only letters, numbers, _ and -")
    return normalized


class RoleCard(BaseModel):
    id: str
    name: str
    persona: str
    speaking_style: str = ""
    rules: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    search_style: str = ""
    memory_notes: str = ""
    created_by: int | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return normalize_role_id(value)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MessageScope:
    message_type: Literal["private", "group"]
    user_id: int
    group_id: int | None = None

    @property
    def room(self) -> str:
        if self.message_type == "group":
            return f"group_{self.group_id}_user_{self.user_id}"
        return f"private_{self.user_id}"

    @property
    def active_role_key(self) -> str:
        if self.message_type == "group":
            return f"group:{self.group_id}"
        return f"private:{self.user_id}"


@dataclass(frozen=True)
class IncomingMessage:
    message_id: int | str | None
    scope: MessageScope
    raw_text: str
    text: str
    sender_nickname: str | None = None
    raw_event: dict[str, Any] | None = None
    unsupported_content_types: tuple[str, ...] = ()


class MemoryHit(BaseModel):
    text: str
    wing: str | None = None
    room: str | None = None
    source_file: str | None = None
    similarity: float | None = None


class DialogueTurn(BaseModel):
    user_text: str
    bot_text: str
    created_at: str | None = None
    source_file: str | None = None


class DialogueContext(BaseModel):
    role_id: str
    room: str
    compacted: str = ""
    turns: list[DialogueTurn] = Field(default_factory=list)
    updated_at: str | None = None


class SearchBrief(BaseModel):
    query: str
    summary: str
    facts: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    freshness_notes: str = ""


class AgentReply(BaseModel):
    text: str
    search_brief: SearchBrief | None = None
