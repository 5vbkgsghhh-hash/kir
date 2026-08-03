"""Flag-gated per-stage audit tracer. Zero overhead when KUKAI_AUDIT_TRACE!=1.

Only traces sessions whose id starts with an audit prefix, so production
traffic is never written. One JSON record per stage per request appended to
data/audit_trace.jsonl. Tracing must NEVER raise into the request path.
"""
from __future__ import annotations
import json, os, time
from contextvars import ContextVar
from pathlib import Path

_ENABLED = os.environ.get("KUKAI_AUDIT_TRACE") == "1"
_PATH = Path(__file__).parent.parent / "data" / "audit_trace.jsonl"
_AUDIT_PREFIXES = ("audit-", "ladder-", "scen-", "ragcert-", "claude-")  # only trace audit sessions

# Per-request session id, set by client._stream_chat_inner. Lets deep modules
# (e.g. rag_prompt) emit traces without importing the client's ContextVar.
_current_sid: ContextVar[str] = ContextVar("_audit_current_sid", default="")


def set_session(session_id: str) -> None:
    try:
        _current_sid.set(session_id or "")
    except Exception:
        pass


def current_session() -> str:
    try:
        return _current_sid.get()
    except Exception:
        return ""


def is_audit_session(session_id: str) -> bool:
    return bool(session_id) and str(session_id).startswith(_AUDIT_PREFIXES)


def trace(session_id: str, stage: str, data: dict) -> None:
    if not _ENABLED or not is_audit_session(session_id):
        return
    rec = {"ts": time.time(), "session_id": session_id, "stage": stage, **data}
    try:
        with _PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # tracing must never break the request


def count_deepseek_calls(prefix: str = "audit-") -> int:
    """Count deepseek_call stage records for sessions starting with prefix.

    This is the budget meter source of truth. Pass prefix="" to count all
    audit sessions (any audit prefix), or a specific prefix like "audit-".
    """
    if not _PATH.exists():
        return 0
    n = 0
    try:
        for line in _PATH.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("stage") == "deepseek_call" and str(r.get("session_id", "")).startswith(prefix):
                    n += 1
            except Exception:
                pass
    except Exception:
        return n
    return n
