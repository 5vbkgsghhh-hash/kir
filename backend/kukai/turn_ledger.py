"""TurnLedger v1 — append-only, ONE-row-per-turn structured event ledger.

THE missing observation spine: today "tool succeeded" is decided by a JSON
substring scan (client.py:1853-1857), "a write happened" by a tool-name list
(chat_ws.py:2314-2317), "grounded" by the mere presence of a tool name
(chat_ws.py:2427-2429), and auto-show by the same name list — each subsystem
reinvents its own weaker notion of "tool ran / write landed / turn is done".
TurnLedger records those moments as STRUCTURED events on one per-turn row so
they become AUDITABLE before anything makes them authoritative.

v1 is SHADOW-ONLY behind ``KUKAI_TURN_LEDGER`` (default OFF, read at CALL
time): no consumer reads the ledger, nothing gates on it, nothing is injected
into prompts, and there is exactly ONE sink write per turn (no per-event DB
writes). Flag OFF ⇒ ``begin_turn()`` returns None, every ``record_*`` is a
no-op, prod behavior is byte-identical.

Mirrors the proven ``kukai/rag/retrieval_health.py`` contract — four
load-bearing properties (do NOT regress any of them):

1. **Default-off** — every ``record_*`` call is a no-op unless ``begin_turn()``
   was called in the current context (and it only installs a record when the
   flag is on). Every other caller sees zero behaviour change.
2. **Never throws** — every public function wraps its body in
   ``try/except Exception -> _note_failure``; the hot path can never be broken
   by its own instrument. ``flush_turn`` additionally tees to JSONL and
   re-raises ONLY ``asyncio.CancelledError`` (cancellation semantics must
   survive; the row is already teed by then).
3. **Thread-hop / child-task safe** — ``begin_turn()`` stores a *mutable*
   ledger in a ``ContextVar``. ``asyncio.to_thread`` / ``asyncio.wait_for``
   (which wraps the awaitable in a child task) copy the context, so code
   running there resolves ``current()`` to the SAME object and mutates it.
   No value is ever passed back via ``ContextVar.set`` from inside a child
   context (that would not propagate).

   Corollary (verified against prod): ``_handle_bridge_response`` runs in the
   WS *receive-loop* task (chat_ws.py:624-625), whose context snapshot predates
   the turn — ``current()`` is None there BY CONSTRUCTION. Per-turn bridge
   events must be recorded in ``_bridge_callback`` (turn's task tree); the
   receive loop may only bump the process-level ``orphan_bridge_response()``
   counter.
4. **stdlib-only at module level** — importable with zero project deps (also
   what lets the test suite exercise it in isolation).
   ``note_telemetry_failure`` is imported lazily to avoid import cycles.

Payload rules (enforced by the sanitizer, not by caller discipline):
- strings are capped; long strings (code, prompts, tool results) become
  ``{sha256, len, preview}`` digests via :func:`digest_preview`;
- keys that look like secrets (key/token/secret/password/…) are redacted;
- NO raw API keys, auth tokens, base64 images, or full C# bodies ever land in
  a row; ``device_id`` is stored only as a 16-hex sha256 prefix.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_V = 1

_FLAG = "KUKAI_TURN_LEDGER"
_TEE_FLAG = "KUKAI_TURN_LEDGER_JSONL"          # "1"/"true" ⇒ tee EVERY row
_TEE_PATH_ENV = "KUKAI_TURN_LEDGER_JSONL_PATH"  # override the tee file path

# The 10 event kinds (Codex §Task3 — the closed vocabulary consumers key on).
KINDS: frozenset[str] = frozenset(
    {
        "flags_snapshot",
        "prompt_inputs",
        "retrieval_events",
        "llm_events",
        "tool_events",
        "bridge_events",
        "witness_events",
        "present_events",
        "persistence_events",
        "degradation_events",
    }
)

# ── payload sanitation limits ────────────────────────────────────────────────
_STR_CAP = 300          # plain strings longer than this are truncated
_DIGEST_AT = 1_500      # strings longer than this become {sha256,len,preview}
_PREVIEW_LEN = 120
_MAX_DEPTH = 6
_MAX_LIST = 50
_MAX_KEYS = 64
_MAX_EVENTS = 500       # per-turn hard cap — beyond it events are counted, not stored
_ERR_CODE_CAP = 64
_SOURCE_CAP = 120

# Substrings (case-insensitive) that mark a dict key as secret-bearing.
_SENSITIVE_KEY_MARKERS = (
    "key", "token", "secret", "password", "authorization", "cookie",
    "credential", "signature",
)
# Env-name markers excluded from snapshot_flags() (values may be secrets/DSNs).
_ENV_EXCLUDE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DSN", "CREDENTIAL")


def _note_failure(exc: BaseException) -> None:
    """Route an internal instrument bug through the IRON-10 pain sense.

    Imported lazily so importing this module never drags in ``kukai.telemetry``
    at import time (and so the module works standalone in tests)."""
    try:
        from kukai.telemetry import note_telemetry_failure

        note_telemetry_failure(exc)
    except Exception:
        # Last-resort: stay silent rather than raise into the hot path.
        pass


def enabled() -> bool:
    """Flag read at CALL time (ops can flip without restart). Default OFF."""
    try:
        return os.environ.get(_FLAG, "0").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash16(s: str) -> str:
    """Stable 16-hex identifier hash (device_id must never land raw)."""
    try:
        return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()[:16]
    except Exception:
        return ""


def digest_preview(s: Any, preview_len: int = _PREVIEW_LEN) -> dict[str, Any]:
    """{sha256, len, preview} for code / prompts / tool results / screenshots.

    The digest lets golden-replay compare turns without storing the body; the
    preview keeps rows human-triageable. Never raises."""
    try:
        text = s if isinstance(s, str) else str(s)
        return {
            "sha256": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            "len": len(text),
            "preview": text[:preview_len],
        }
    except Exception:
        return {"sha256": "", "len": -1, "preview": ""}


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(m in k for m in _SENSITIVE_KEY_MARKERS)


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Best-effort deep sanitation: cap sizes, digest long strings, redact
    secret-looking keys. Deterministic, cheap, never raises (caller guards)."""
    if depth >= _MAX_DEPTH:
        return "[depth_capped]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _DIGEST_AT:
            return digest_preview(value)
        if len(value) > _STR_CAP:
            return value[:_STR_CAP] + "…"
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_KEYS:
                out["_keys_capped"] = len(value)
                break
            ks = str(k)[:_STR_CAP]
            if _is_sensitive_key(ks):
                out[ks] = "[redacted]"
            else:
                out[ks] = _sanitize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = list(value)
        out_l = [_sanitize(v, depth + 1) for v in seq[:_MAX_LIST]]
        if len(seq) > _MAX_LIST:
            out_l.append(f"[+{len(seq) - _MAX_LIST} items capped]")
        return out_l
    # bytes / arbitrary objects: never store raw — digest their repr.
    try:
        return digest_preview(repr(value))
    except Exception:
        return "[unrepresentable]"


def sanitize_payload(payload: Any) -> dict[str, Any]:
    """Coerce any payload into a sanitized dict (non-dicts wrap as {value})."""
    try:
        s = _sanitize(payload if payload is not None else {})
        return s if isinstance(s, dict) else {"value": s}
    except Exception as e:
        _note_failure(e)
        return {}


# ── dataclasses (Codex §Task3 schema) ────────────────────────────────────────


# Plain @dataclass (no slots=True) — matches the retrieval_health precedent.
# NOTE for file-path loaders (tests): with PEP 563 string annotations, dataclass
# creation reads sys.modules[cls.__module__], so follow the documented importlib
# recipe (register the module in sys.modules BEFORE exec_module) — verified
# empirically on Python 3.12.
@dataclass
class TurnLedgerEvent:
    seq: int
    ts_ms: int
    kind: str                    # one of KINDS
    source: str                  # e.g. "chat_ws._handle_chat"
    file_line: str = ""          # e.g. "kukai/api/chat_ws.py:2214"
    payload: dict[str, Any] = field(default_factory=dict)
    ok: Optional[bool] = None
    err_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "kind": self.kind,
            "source": self.source,
            "file_line": self.file_line,
            "payload": self.payload,
            "ok": self.ok,
            "err_code": self.err_code,
        }


@dataclass
class TurnLedger:
    schema_v: int = SCHEMA_V
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    ws_id: str = ""
    tenant_id: str = ""
    device_id_hash: str = ""
    started_at: str = field(default_factory=_now_iso)
    ended_at: Optional[str] = None
    flags_snapshot: dict[str, Any] = field(default_factory=dict)
    events: list[TurnLedgerEvent] = field(default_factory=list)
    degraded: bool = False
    summary: dict[str, Any] = field(default_factory=dict)
    dropped_events: int = 0

    def to_row(self) -> dict[str, Any]:
        """The ONE serializable row handed to the sink (matches turn_ledger DDL)."""
        return {
            "schema_v": self.schema_v,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "ws_id": self.ws_id,
            "tenant_id": self.tenant_id,
            "device_id_hash": self.device_id_hash,
            "started_at": self.started_at,
            "ended_at": self.ended_at or "",
            "degraded": self.degraded,
            "flags_snapshot": self.flags_snapshot,
            "events": [e.to_dict() for e in self.events],
            "summary": self.summary,
        }


# The per-turn ledger lives in a ContextVar; the VALUE is mutable so child
# contexts (to_thread / wait_for tasks) mutate the SAME object (property 3).
_current: contextvars.ContextVar[Optional[TurnLedger]] = contextvars.ContextVar(
    "turn_ledger", default=None
)

# Process-level vitals (same spirit as retrieval_health.VITALS) — includes the
# only signal a turn-scoped ledger structurally cannot own: orphaned late
# bridge responses resolved in the receive-loop context.
VITALS: dict = {
    "turns": 0,
    "flushed_turns": 0,
    "degraded_turns": 0,
    "sink_failures": 0,
    "dropped_events": 0,
    "orphan_bridge_responses": 0,
}


# ── lifecycle ────────────────────────────────────────────────────────────────


def begin_turn(
    *,
    session_id: str = "",
    ws_id: str = "",
    tenant_id: str = "",
    device_id: str = "",
) -> Optional[TurnLedger]:
    """Install a fresh ledger for this turn — ONLY when the flag is on.

    Flag OFF ⇒ returns None and touches nothing (byte-identical turn)."""
    try:
        if not enabled():
            return None
        led = TurnLedger(
            session_id=str(session_id or "")[:64],
            ws_id=str(ws_id or "")[:64],
            tenant_id=str(tenant_id or "")[:64],
            device_id_hash=_hash16(device_id) if device_id else "",
        )
        _current.set(led)
        VITALS["turns"] = VITALS.get("turns", 0) + 1
        return led
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)
        return None


def current() -> Optional[TurnLedger]:
    """The active ledger for this context, or None (flag off / no turn)."""
    try:
        return _current.get()
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)
        return None


def set_ids(
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    ws_id: Optional[str] = None,
) -> None:
    """Fill identifiers that are only known after begin (session resolution
    happens ~80 lines below the begin site in _handle_chat). No-op without a turn."""
    try:
        led = _current.get()
        if led is None:
            return
        if session_id is not None:
            led.session_id = str(session_id)[:64]
        if tenant_id is not None:
            led.tenant_id = str(tenant_id)[:64]
        if ws_id is not None:
            led.ws_id = str(ws_id)[:64]
    except Exception as e:
        _note_failure(e)


def record(
    kind: str,
    source: str,
    payload: Any = None,
    *,
    ok: Optional[bool] = None,
    err_code: Optional[str] = None,
    file_line: str = "",
) -> None:
    """Append one structured event to the current turn's ledger.

    ALWAYS a no-op (never raises) when no turn is active — this is what keeps
    every instrumented call site behaviourally unchanged with the flag off.
    Unknown kinds are folded into degradation_events (closed vocabulary, no
    lost signal). Beyond _MAX_EVENTS events are counted, not stored."""
    try:
        led = _current.get()
        if led is None:
            return
        if len(led.events) >= _MAX_EVENTS:
            led.dropped_events += 1
            VITALS["dropped_events"] = VITALS.get("dropped_events", 0) + 1
            return
        k = str(kind)
        pl = sanitize_payload(payload)
        if k not in KINDS:
            pl = {"bad_kind": k[:_STR_CAP], "orig_payload": pl}
            k = "degradation_events"
        led.events.append(
            TurnLedgerEvent(
                seq=len(led.events) + 1,
                ts_ms=int(time.time() * 1000),
                kind=k,
                source=str(source)[:_SOURCE_CAP],
                file_line=str(file_line)[:_SOURCE_CAP],
                payload=pl,
                ok=None if ok is None else bool(ok),
                err_code=None if err_code is None else str(err_code)[:_ERR_CODE_CAP],
            )
        )
        # Degradation semantics: any degradation event, or a failed
        # persistence write, marks the TURN degraded (mirrors
        # retrieval_health.degraded's "strong leg went dark" idea).
        if k == "degradation_events" or (k == "persistence_events" and ok is False):
            led.degraded = True
    except Exception as e:
        _note_failure(e)


def _make_recorder(kind: str):
    def _rec(
        source: str,
        payload: Any = None,
        *,
        ok: Optional[bool] = None,
        err_code: Optional[str] = None,
        file_line: str = "",
    ) -> None:
        record(kind, source, payload, ok=ok, err_code=err_code, file_line=file_line)

    _rec.__name__ = f"record_{kind}"
    _rec.__doc__ = f"Best-effort {kind} event; no-op without an active turn; never raises."
    return _rec


record_prompt_inputs = _make_recorder("prompt_inputs")
record_retrieval = _make_recorder("retrieval_events")
record_llm = _make_recorder("llm_events")
record_tool = _make_recorder("tool_events")
record_bridge = _make_recorder("bridge_events")
record_witness = _make_recorder("witness_events")
record_present = _make_recorder("present_events")
record_persistence = _make_recorder("persistence_events")
record_degradation = _make_recorder("degradation_events")


def record_flags_snapshot(
    source: str,
    payload: Any = None,
    *,
    ok: Optional[bool] = None,
    err_code: Optional[str] = None,
    file_line: str = "",
) -> None:
    """flags_snapshot event + mirror onto the row's flags_snapshot column
    (the column is what B1/B2/golden-replay JOIN on; the event keeps ordering)."""
    try:
        record("flags_snapshot", source, payload, ok=ok, err_code=err_code, file_line=file_line)
        led = _current.get()
        if led is not None:
            snap = sanitize_payload(payload)
            if snap:
                led.flags_snapshot.update(snap)
    except Exception as e:
        _note_failure(e)


def snapshot_flags(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Current KUKAI_*/EVALUATOR_* env flags, secrets excluded by NAME marker
    (KEY/TOKEN/SECRET/PASSWORD/DSN/CREDENTIAL) and values capped. Scanning the
    environment (not a hardcoded list) means new flags appear without edits."""
    try:
        out: dict[str, Any] = {}
        for name, val in os.environ.items():
            if not (name.startswith("KUKAI_") or name.startswith("EVALUATOR_")):
                continue
            if any(m in name for m in _ENV_EXCLUDE_MARKERS):
                continue
            out[name] = str(val)[:64]
        if extra:
            out.update(sanitize_payload(extra))
        return out
    except Exception as e:
        _note_failure(e)
        return {}


def orphan_bridge_response(req_id: str = "") -> None:
    """Process-level counter for a LATE bridge_response resolved in the
    receive-loop task (chat_ws.py:944-955) — there is NO active turn in that
    context by construction (see module docstring, property 3 corollary), so
    this is the only honest place the signal can live."""
    try:
        VITALS["orphan_bridge_responses"] = VITALS.get("orphan_bridge_responses", 0) + 1
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)


def _build_summary(led: TurnLedger) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    n_err = 0
    for ev in led.events:
        by_kind[ev.kind] = by_kind.get(ev.kind, 0) + 1
        if ev.ok is False:
            n_err += 1
    summary: dict[str, Any] = {
        "n_events": len(led.events),
        "by_kind": by_kind,
        "n_err": n_err,
    }
    if led.dropped_events:
        summary["dropped_events"] = led.dropped_events
    try:
        t0 = datetime.fromisoformat(led.started_at)
        t1 = datetime.fromisoformat(led.ended_at) if led.ended_at else datetime.now(timezone.utc)
        summary["duration_ms"] = int((t1 - t0).total_seconds() * 1000)
    except Exception:
        pass
    return summary


def finish_turn() -> Optional[dict[str, Any]]:
    """Close the turn: stamp ended_at, build the summary, CLEAR the ContextVar,
    return the one serializable row. Idempotent — a second call returns None.
    Does NOT write anywhere (the sink write belongs to flush_turn)."""
    try:
        led = _current.get()
        if led is None:
            return None
        _current.set(None)
        led.ended_at = _now_iso()
        led.summary = _build_summary(led)
        if led.degraded:
            VITALS["degraded_turns"] = VITALS.get("degraded_turns", 0) + 1
        return led.to_row()
    except Exception as e:
        _note_failure(e)
        try:
            _current.set(None)
        except Exception:
            pass
        return None


# ── sink (ONE write per turn) ────────────────────────────────────────────────


def _jsonl_path() -> Path:
    override = os.environ.get(_TEE_PATH_ENV, "").strip()
    if override:
        return Path(override)
    # Destined location is backend/kukai/turn_ledger.py → backend/data/
    # (same derivation as chat_ws._witness_log_path).
    return Path(__file__).resolve().parent.parent / "data" / "turn_ledger.jsonl"


def _always_tee() -> bool:
    return os.environ.get(_TEE_FLAG, "0").strip().lower() in ("1", "true", "yes", "on")


def _tee_jsonl(row: dict[str, Any]) -> bool:
    """Append one row to the non-authoritative JSONL tee. Best-effort."""
    try:
        path = _jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception as e:
        _note_failure(e)
        return False


async def flush_turn(db: Any = None) -> Optional[dict[str, Any]]:
    """finish_turn + the turn's ONE sink write. Never raises into the caller
    (re-raises ONLY CancelledError, after the row is safely teed to JSONL).

    Sink policy (Codex §Task3 sink decision, verified against database.py):
    Postgres via ``db.save_turn_ledger(row)`` is canonical; JSONL is the
    non-authoritative tee — always-on via KUKAI_TURN_LEDGER_JSONL=1, and the
    automatic fallback when the DB write fails or no db was passed. Never
    retried, never blocking beyond the single awaited insert."""
    row = finish_turn()
    if row is None:
        return None
    teed = _tee_jsonl(row) if _always_tee() else False
    save = getattr(db, "save_turn_ledger", None) if db is not None else None
    if save is not None:
        try:
            await save(row)
            VITALS["flushed_turns"] = VITALS.get("flushed_turns", 0) + 1
            return row
        except asyncio.CancelledError:
            VITALS["sink_failures"] = VITALS.get("sink_failures", 0) + 1
            if not teed:
                _tee_jsonl(row)
            raise  # honor cancellation — the row is already on disk
        except Exception as e:
            VITALS["sink_failures"] = VITALS.get("sink_failures", 0) + 1
            _note_failure(e)
            if not teed:
                _tee_jsonl(row)
            return row
    if not teed:
        _tee_jsonl(row)
    VITALS["flushed_turns"] = VITALS.get("flushed_turns", 0) + 1
    return row


def vitals() -> dict:
    """Shallow snapshot of process-level vitals (for /health/deep, read-only)."""
    try:
        return dict(VITALS)
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)
        return {"error": type(e).__name__}
