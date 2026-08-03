"""Converse gate + follow-up carry-over for RAG injection (Ф0, RAG audit
2026-07-06 — /root/kukai-rag-audit/AUDIT_REPORT.md §5-6).

The audit measured: ~31% of prod turns are smalltalk/meta/short-follow-ups, and
retrieval has no "inject nothing" outcome — «привет как дела» gets ~6.6KB of
random API classes, «да» is searched literally and injects noise. This module
gives the RAG path three deterministic outcomes, all fail-open:

  - "converse"  — greeting/meta with NO action verb → inject nothing at all.
  - "followup"  — ultra-short continuation («да», «делай», «а сейчас?») with a
                  cached retrieval from this session's previous turn → reuse
                  that retrieval instead of searching the literal «да».
  - "task"      — everything else → the normal pipeline, unchanged.

Deterministic legs only (quick_classify dictionary, H4-safe: any action verb
vetoes "converse"). The LLM IntentClassifier result, when it lands in time,
may additionally confirm-gate at inject time (see client.py wiring) — but the
deterministic decision here never waits on a network call.

Flag: KUKAI_RAG_CONVERSE_GATE (default ON; "0" disables — full legacy path).
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from kukai.agents.intent_rules import _has_action_verb, quick_classify

# Action verbs MISSING from intent_rules' groups (found by this module's test:
# «привет, посчитай стены» classified converse because _COUNT only lists
# «сколько/количество»). Local supplement — widening the veto here keeps the
# gate H4-safe without changing router semantics for everyone.
_EXTRA_ACTION_VERBS = (
    "посчита", "проставь", "выгруз", "пролож", "размести", "заполни",
    "замени", "скопир", "выровня", "раскрась", "подпиши", "сравни",
    "поменяй", "задай", "настрой", "примени", "экспорт", "импорт",
    "включи", "скрой", "поверни", "перемести", "загрузи", "открой",
)


def _any_action(q: str) -> bool:
    return _has_action_verb(q) or any(w in q for w in _EXTRA_ACTION_VERBS)


# Ultra-short continuation ceiling. Real prod follow-ups («да», «нет», «делай»,
# «продолжи», «а сейчас?», «не получилось») are ≤16 chars; real one-verb tasks
# («удали стену») carry an action verb and are vetoed by _any_action.
_FOLLOWUP_MAX_CHARS = 16

# Session-scoped carry-over cache: sid -> (monotonic_ts, entries).
# Single prod worker (uvicorn --workers 1) → plain dict is safe.
_CARRY_TTL_S = 2 * 60 * 60
_CARRY_MAX_SESSIONS = 200
_last_entries: dict[str, tuple[float, list]] = {}


def gate_enabled() -> bool:
    """Read the flag at call time (same pattern as KUKAI_RAG_RECIPES_ENABLED)."""
    return os.getenv("KUKAI_RAG_CONVERSE_GATE", "1") != "0"


def classify_gate(user_message: Optional[str]) -> str:
    """Deterministic gate decision: "converse" | "followup" | "task".

    Fail-open: any surprise → "task" (the unchanged legacy pipeline).
    """
    try:
        q = (user_message or "").strip()
        if not q:
            return "task"
        ql = q.lower()
        if quick_classify(q).get("intent") == "converse" and not _any_action(ql):
            return "converse"
        if len(q) <= _FOLLOWUP_MAX_CHARS and not _any_action(ql):
            return "followup"
        return "task"
    except Exception:  # noqa: BLE001 — never block the turn on the gate
        return "task"


def llm_confirms_converse(meta: Optional[dict[str, Any]]) -> bool:
    """True when the LLM IntentClassifier result confirms a no-RAG turn.

    Strict on purpose: converse intent AND should_emit_code=False AND no
    entities. A composite «привет, посчитай стены» classifies count → False.
    """
    try:
        return bool(
            meta
            and meta.get("intent") == "converse"
            and not meta.get("should_emit_code", True)
            and not meta.get("entities")
        )
    except Exception:  # noqa: BLE001
        return False


def remember_retrieval(sid: str, entries: Optional[list]) -> None:
    """Cache this turn's retrieved entries for follow-up carry-over."""
    try:
        if not sid or not entries:
            return
        now = time.monotonic()
        _last_entries[sid] = (now, list(entries))
        if len(_last_entries) > _CARRY_MAX_SESSIONS:
            # Drop the stalest ~quarter in one pass (rare; keeps dict bounded).
            for k, _ in sorted(
                _last_entries.items(), key=lambda kv: kv[1][0],
            )[: _CARRY_MAX_SESSIONS // 4]:
                _last_entries.pop(k, None)
    except Exception:  # noqa: BLE001
        pass


def recall_retrieval(sid: str) -> Optional[list]:
    """Previous turn's entries for this session, or None if absent/expired."""
    try:
        item = _last_entries.get(sid or "")
        if not item:
            return None
        ts, entries = item
        if time.monotonic() - ts > _CARRY_TTL_S:
            _last_entries.pop(sid, None)
            return None
        return entries
    except Exception:  # noqa: BLE001
        return None
