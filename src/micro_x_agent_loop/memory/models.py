from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionRecord:
    id: str
    parent_session_id: str | None
    created_at: str
    updated_at: str
    status: str
    model: str
    metadata_json: str


@dataclass(frozen=True)
class MessageRecord:
    id: str
    session_id: str
    seq: int
    role: str
    content_json: str
    created_at: str
    token_estimate: int
