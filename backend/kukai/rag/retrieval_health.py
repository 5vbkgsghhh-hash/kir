"""Per-turn retrieval health record (plan 009 — the RAG measurement spine).

ONE instrument, three consumers: the live production turn, the offline
benchmark, and ``/health/deep`` all read/write the SAME per-turn record so the
benchmark measures the instrumented production functions, not a parallel
reimplementation.

Four load-bearing properties (do NOT regress any of them):

1. **Default-off** — every ``report_leg``/``add_flag``/``set_*`` call is a
   no-op unless ``begin_turn()`` was called in the current context. Every other
   caller of ``RevitApiIndex.search()`` (family tools, scripts, tests) sees zero
   behaviour change.
2. **Never throws** — every public function wraps its body in
   ``try/except Exception -> note_telemetry_failure``; the hot path can never be
   broken by its own instrument.
3. **Thread-hop safe** — ``begin_turn()`` stores a *mutable* record in a
   ``ContextVar``. ``asyncio.to_thread`` copies the context, so code running
   inside ``build_system_prompt`` (off-thread) resolves ``current()`` to the
   SAME object and mutates it; the mutation is visible to the caller because it
   is the same object. No value is ever passed back via ``ContextVar.set`` from
   inside the thread (that would not propagate).
4. **stdlib-only at module level** — keeps ``revit_api_index.py`` importable with
   zero new hard deps. ``note_telemetry_failure`` is imported lazily inside each
   function to avoid an import cycle.
"""

from __future__ import annotations

import contextvars
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional


# Statuses that count as a degraded leg (the strong/expected legs went dark).
#   tripped_breaker (plan 018): the semantic leg's embedding endpoint is in the
#     circuit breaker's OPEN window — a dead/slow endpoint that used to hide
#     behind a bare ``empty``. Counting it here makes such a turn DEGRADED.
_DEGRADED_LEG_STATUSES = frozenset(
    {"error", "skipped_no_key", "skipped_no_data", "tripped_breaker"}
)
# Statuses that are NORMAL operating modes — NOT degraded.
#   replayed     : benchmark replayed the gold EN translation (offline)
#   skipped_ascii: translation skipped because input was already English-ish
#   cache_hit    : translation served from cache
#   skipped_flag : a feature flag is intentionally off
#   ran / empty  : the leg executed (empty = ran but returned nothing)


def _note_failure(exc: BaseException) -> None:
    """Route an internal instrument bug through the IRON-10 pain sense.

    Imported lazily so importing this module never drags in ``kukai.telemetry``
    (and its deps) at import time — keeps ``revit_api_index`` import-cheap.
    """
    try:
        from kukai.telemetry import note_telemetry_failure

        note_telemetry_failure(exc)
    except Exception:
        # Last-resort: the pain sense itself is unavailable. Stay silent rather
        # than raise into the hot path — that is the whole contract.
        pass


@dataclass
class LegReport:
    """One retrieval leg's outcome for a single turn."""

    name: str            # translate|expand|keyword|semantic|phrasings|rrf_fuse|rerank|version_filter|recipe_backfill
    status: str          # ran|skipped_flag|skipped_no_key|skipped_no_data|skipped_ascii|cache_hit|replayed|error|empty|tripped_breaker
    n_results: int = 0
    latency_ms: float = 0.0
    detail: str = ""     # short, no PII (e.g. "TypeError", "neg_cache", model id)


@dataclass
class RetrievalHealth:
    """The full per-turn retrieval health record."""

    query_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    legs: list[LegReport] = field(default_factory=list)
    rerank_moved: int = 0          # how many of final top-5 changed position vs pre-rerank
    final_keys: list[str] = field(default_factory=list)   # "entry_type:ns.Name", max 10
    final_k: int = 0
    version_filtered_out: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when any strong/expected leg went dark or no results returned."""
        if "no_results" in self.flags:
            return True
        for leg in self.legs:
            if leg.status in _DEGRADED_LEG_STATUSES:
                return True
        return False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["degraded"] = self.degraded
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# The per-turn record lives in a ContextVar. The VALUE is a mutable object so
# that mutations performed inside an ``asyncio.to_thread`` copied context are
# visible on the caller's object (see module docstring, property 3).
_current: contextvars.ContextVar[Optional[RetrievalHealth]] = contextvars.ContextVar(
    "retrieval_health", default=None
)


# Process-level vitals for /health/deep — same spirit as cohere_rerank.RERANK_STATS.
VITALS: dict = {"turns": 0, "degraded_turns": 0, "last_degraded_flags": []}


def begin_turn() -> RetrievalHealth:
    """Install a fresh ``RetrievalHealth`` in the current context and return it.

    The caller keeps the returned object; instrumentation across the
    ``asyncio.to_thread`` hop mutates the SAME object via ``current()``.
    """
    h = RetrievalHealth()
    try:
        _current.set(h)
        VITALS["turns"] = VITALS.get("turns", 0) + 1
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)
    return h


def current() -> Optional[RetrievalHealth]:
    """Return the active record for this context, or ``None`` if no turn began."""
    try:
        return _current.get()
    except Exception as e:  # pragma: no cover - defensive
        _note_failure(e)
        return None


def report_leg(
    name: str,
    status: str,
    n_results: int = 0,
    latency_ms: float = 0.0,
    detail: str = "",
) -> None:
    """Append a leg report to the current record.

    ALWAYS a no-op (never raises) when no turn is active — this is what makes
    every other caller of ``search()`` behaviourally unchanged.
    """
    try:
        h = _current.get()
        if h is None:
            return
        h.legs.append(
            LegReport(
                name=str(name),
                status=str(status),
                n_results=int(n_results),
                latency_ms=float(latency_ms),
                detail=str(detail)[:120],
            )
        )
    except Exception as e:
        _note_failure(e)


def add_flag(flag: str) -> None:
    """Add a turn-level flag (e.g. "no_results", "keyword_only"). No-op without a turn."""
    try:
        h = _current.get()
        if h is None:
            return
        f = str(flag)
        if f not in h.flags:
            h.flags.append(f)
    except Exception as e:
        _note_failure(e)


def set_final(entries: list) -> None:
    """Record final result keys/count from a list of entries (max 10 keys).

    Key convention matches the RRF fusion in ``revit_api_index.search``:
    ``f"{entry_type}:{namespace}.{name}"``.
    """
    try:
        h = _current.get()
        if h is None:
            return
        keys: list[str] = []
        for e in (entries or [])[:10]:
            et = getattr(e, "entry_type", "")
            ns = getattr(e, "namespace", "")
            nm = getattr(e, "name", "")
            keys.append(f"{et}:{ns}.{nm}")
        h.final_keys = keys
        h.final_k = len(entries or [])
    except Exception as e:
        _note_failure(e)


def record_grounding(query, final, signature_pred=None) -> None:
    """Seed of the miss-detector: flag a substantive query that landed on thin air.

    Sets the per-turn ``low_grounding`` flag (and records a short ``detail`` via a
    dedicated ``grounding_detail`` flag suffix) when, for a SUBSTANTIVE query, the
    final result set is one of:

      * **empty** — nothing came back at all;
      * **signature-only** — every returned entry is a bare-signature class
        (``signature_pred(entry)`` is True for all) — looks populated, isn't;
      * **read-only-only** — every returned entry is a non-actionable lookup type
        (``category`` / ``parameter`` / ``version``) with no class/recipe/edge —
        i.e. a read-only-ish answer where the query likely wanted a real pattern.

    This is a SIGNAL, not a gate — it only appends a flag to the current turn's
    record (consumed later by the miss-detector). It is a no-op unless a turn is
    active, and — like every function in this module — it NEVER throws.

    ``signature_pred`` is injected by the caller (``revit_api_index`` owns the
    bare-signature definition); when absent, the signature-only branch is skipped.
    """
    try:
        h = _current.get()
        if h is None:
            return
        # A "substantive" query has at least one content-bearing word (>= 3
        # chars, not a lone connector). A trivially short / empty query is not
        # held to the grounding bar — a miss there is expected, not a signal.
        q = str(query or "").strip()
        if len(q) < 3:
            return
        words = [w for w in q.replace("(", " ").replace(")", " ").replace(".", " ").split() if len(w) >= 3]
        if not words:
            return

        entries = list(final or [])
        detail = ""
        if not entries:
            detail = "empty"
        else:
            # signature-only: every entry is a bare-signature class.
            if signature_pred is not None:
                try:
                    if all(bool(signature_pred(e)) for e in entries):
                        detail = "signatures_only"
                except Exception:
                    detail = ""
            if not detail:
                # read-only-only: nothing actionable (no class/recipe/edge).
                _ACTIONABLE = {"class", "recipe", "edge", "methodology", "formula", "rule"}
                types = {str(getattr(e, "entry_type", "")) for e in entries}
                if types and types.isdisjoint(_ACTIONABLE):
                    detail = "read_only_only"

        if detail:
            if "low_grounding" not in h.flags:
                h.flags.append("low_grounding")
            tag = f"grounding:{detail}"
            if tag not in h.flags:
                h.flags.append(tag)
    except Exception as e:
        _note_failure(e)


def set_version_filtered_out(n: int) -> None:
    """Record how many entries the version filter dropped. No-op without a turn."""
    try:
        h = _current.get()
        if h is None:
            return
        h.version_filtered_out = int(n)
    except Exception as e:
        _note_failure(e)


def set_rerank_moved(n: int) -> None:
    """Record how many of the final top-5 the reranker moved. No-op without a turn."""
    try:
        h = _current.get()
        if h is None:
            return
        h.rerank_moved = int(n)
    except Exception as e:
        _note_failure(e)


def finish_turn(h: Optional[RetrievalHealth]) -> None:
    """Close out a turn: bump degraded counter if degraded, clear the contextvar."""
    try:
        if h is not None and h.degraded:
            VITALS["degraded_turns"] = VITALS.get("degraded_turns", 0) + 1
            VITALS["last_degraded_flags"] = list(h.flags)
    except Exception as e:
        _note_failure(e)
    finally:
        try:
            _current.set(None)
        except Exception as e:  # pragma: no cover - defensive
            _note_failure(e)


def vitals() -> dict:
    """Shallow snapshot of process-level vitals + telemetry failure count.

    Read-only — safe to call from ``/health/deep`` without a turn active.
    """
    try:
        v = {
            "turns": VITALS.get("turns", 0),
            "degraded_turns": VITALS.get("degraded_turns", 0),
            "last_degraded_flags": list(VITALS.get("last_degraded_flags", [])),
        }
        try:
            from kukai.telemetry import telemetry_failure_count

            v["telemetry_failures"] = telemetry_failure_count()
        except Exception:
            v["telemetry_failures"] = None
        return v
    except Exception as e:
        _note_failure(e)
        return {"error": f"{type(e).__name__}"}
