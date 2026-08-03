"""Storage data models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Session(BaseModel):
    """Chat session."""
    id: str
    device_id: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """Chat message (user or assistant)."""
    id: str
    session_id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class AuditEntry(BaseModel):
    """Audit log entry for write operations."""
    id: str
    session_id: str
    device_id: str = ""
    action: str  # "execute_code", "select_elements", "highlight_elements"
    details: dict[str, Any] = Field(default_factory=dict)
    result: str = ""  # "success", "error", "blocked"
    created_at: datetime = Field(default_factory=_utcnow)
