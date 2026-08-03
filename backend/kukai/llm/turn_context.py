"""Per-turn ContextVars + per-turn flag readers (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 1): the bodies below
are byte-identical to their previous definitions in ``kukai/llm/client.py``.
This module is the SINGLE home of the turn-scoped ContextVars — everyone else
(including ``client.py``, which re-exports them for backward compatibility)
imports THE SAME objects. ContextVar identity is load-bearing:
``chat_ws.py`` binds ``_active_session_id`` and
``revit_execution_pipeline.py`` reads the capture vars — both through the
``kukai.llm.client`` re-exports, which resolve to the objects defined here.

Sibling of ``turn_state.py`` (the per-turn mutable state dataclass) — same
asyncio-task isolation discipline.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Optional

# Per-task WebSocket reference (scoped via asyncio task context).
# Each asyncio.create_task() copies the context, so concurrent users
# never share the same WebSocket reference.
_active_ws: ContextVar[Any] = ContextVar('_active_ws', default=None)

# Per-task device_id (scoped via asyncio task context).
# Used by VOR session store to isolate results by user.
_active_device_id: ContextVar[Optional[str]] = ContextVar('_active_device_id', default=None)

# Per-task KUKI session_id (scoped via asyncio task context).
# Forwarded to agy_proxy as OpenAI `user` field so that proxy can pin each
# KUKI session to a stable Antigravity Pro account (multi-account rotation).
_active_session_id: ContextVar[Optional[str]] = ContextVar('_active_session_id', default=None)


def _exec_pipeline_active() -> bool:
    """Whether the RevitExecutionPipeline (Step 7 keystone) runs for THIS turn.

    KUKAI_EXEC_PIPELINE (read at call time — single source of truth for the
    three gate sites):
      * "1" / "fleet"  → every turn (fleet activation);
      * "canary"       → ONLY audit / eval sessions (``_active_session_id`` is
                         set solely for ``audit-``/``claude-``/``ladder-``/…
                         prefixed sessions — chat_ws.py:1427), so the operator
                         can validate the pipeline on the authorized device with
                         ZERO real-user exposure before the fleet flip;
      * anything else  → OFF (a typo can never activate).
    """
    v = os.environ.get("KUKAI_EXEC_PIPELINE", "0").strip().lower()
    if v in ("1", "fleet"):
        return True
    if v == "canary":
        return bool(_active_session_id.get())
    return False

# Per-turn intent metadata, scoped via the asyncio task context. The capture
# site can read it without storing request state on the process-wide client.
# It is reset at the top of every turn.
_turn_intent_metadata: ContextVar[Optional[dict]] = ContextVar('_turn_intent_metadata', default=None)


# ── Tool Palette v2 / per-intent masking (KUKAI_TOOL_MASKING) ────────────────
# The router's RouteDecision.intent, published per turn so the tool panel can
# be gated at _resolve_tools time (kukai/llm/tool_masking.py) WITHOUT widening
# any signature on the hot path. Same asyncio-task isolation as the vars above.
#
# _turn_tool_mask_state holds a MUTABLE dict on purpose: tool execution may run
# inside asyncio.wait_for (a child task on some runtimes, which copies the
# context — a ContextVar.set() there would NOT propagate back). Children see
# the SAME dict object, so request_more_tools can flip state["unmasked"]=True
# and the parent's next _resolve_tools observes it. Both are (re)bound fresh
# by publish_route_intent() at the router site each turn — no cross-turn leak.
_turn_route_intent: ContextVar[Optional[str]] = ContextVar('_turn_route_intent', default=None)
_turn_tool_mask_state: ContextVar[Optional[dict]] = ContextVar('_turn_tool_mask_state', default=None)


def publish_route_intent(intent: Optional[str]) -> None:
    """Publish THIS turn's router intent + bind a fresh tool-mask state.

    Called from the single surgical site in client.py where ``_route`` is
    computed. Junk (None/empty/non-str) normalizes to None → masking fails
    open to the FULL tool list."""
    _turn_route_intent.set(intent if isinstance(intent, str) and intent else None)
    _turn_tool_mask_state.set({"unmasked": False})


# ── KUKAI_PREFLIGHT_V2: overlap request-level intent classification ─────────
# Wiki routing itself is local and deterministic. When enabled, the optional
# classifier starts before prompt assembly; the router later awaits only its
# remaining bounded budget and otherwise uses the generated lexical index.


def _preflight_v2_enabled() -> bool:
    """Per-turn read of the Step 9B latency flag (default OFF)."""
    return os.environ.get("KUKAI_PREFLIGHT_V2", "0") == "1"


def _pf2_deadline(env_name: str, default: float) -> float:
    """Positive-float env knob with a safe fallback (garbage/zero/neg → default)."""
    try:
        v = float(os.environ.get(env_name, "") or default)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default
