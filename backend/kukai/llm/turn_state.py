"""Per-turn request state, isolated via an asyncio ContextVar.

WHY: ``LLMClient`` is a process-wide singleton — ``main.py`` builds ONE instance
and every WebSocket/HTTP request reuses it (``state.llm``). Per-request mutable
state used to live on ``self.*`` (``_last_large_result``, ``_last_generated_excel_*``,
``_last_uploaded_file_bytes``, ``_revit_version``) and was read across concurrent
users — a cross-tenant leak (the F012 class): user B's upload / generated Excel /
large query result / Revit version could overwrite user A's mid-turn.

FIX: move that state into a ``TurnState`` bound to the CURRENT asyncio task. Each
request runs in its own task (FastAPI per-request task; the WS chat path spawns
``asyncio.create_task(_tracked_handle_chat(...))``), and asyncio copies the context
per task, so ``ContextVar.set()`` in one task never affects another.

SAFETY (the asyncio gotcha): a task that does ``create_task`` *copies* the current
context — so if ``_active_turn`` were ever ``set()`` in a long-lived PARENT context,
children would inherit the SAME object and share it. Two guarantees prevent that:
(1) ``LLMClient.__init__`` never touches the turn properties (so app startup, which
runs in the root context, never pollutes it); (2) ``stream_chat`` calls
``begin_turn()`` FIRST — which always binds a FRESH ``TurnState`` — so even a
polluted inherited context is overridden before any read.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TurnState:
    """Mutable state scoped to a single chat turn / request."""
    revit_version: str = ""
    last_large_result: Any = None
    uploaded_file_bytes: Optional[bytes] = None
    last_generated_excel_bytes: Optional[bytes] = None
    last_generated_excel_filename: Optional[str] = None


_active_turn: ContextVar[Optional[TurnState]] = ContextVar("_active_turn", default=None)


def begin_turn(revit_version: str = "", uploaded_file_bytes: Optional[bytes] = None) -> Token:
    """Bind a FRESH TurnState to the current task. Call once at the chat entry
    (``stream_chat``); pair with ``end_turn(token)`` in a ``finally``."""
    return _active_turn.set(TurnState(
        revit_version=revit_version or "",
        uploaded_file_bytes=uploaded_file_bytes,
    ))


def end_turn(token: Token) -> None:
    """Reset the ContextVar to its prior value (best-effort)."""
    try:
        _active_turn.reset(token)
    except (ValueError, LookupError):
        pass


def current_turn() -> TurnState:
    """The current task's TurnState. Lazily creates one (bound to THIS task's
    context) if a code path runs outside ``begin_turn`` — never returns None."""
    ts = _active_turn.get()
    if ts is None:
        ts = TurnState()
        _active_turn.set(ts)
    return ts
