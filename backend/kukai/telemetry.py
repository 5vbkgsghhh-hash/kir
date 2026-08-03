"""Telemetry — anonymous usage tracking for product improvement.

Collects:
- Command categories (count/filter/write/qa/general)
- Response times (LLM call duration)
- Error types and frequencies
- Tool call success/failure rates
- Daily active sessions

All data is anonymous — no message content, no user identifiers stored.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IRON 10 / Article 24 — "telemetry failure is loud".
#
# Telemetry writes are best-effort and MUST NOT block a request/turn. But a
# silently-swallowed failure means the system goes blind exactly when it most
# needs to report. So every telemetry write failure is funnelled through
# note_telemetry_failure(): it (a) increments a process-level counter that a
# health/status endpoint can read, and (b) logs at WARNING — rate-limited so a
# sustained outage surfaces without spamming the journal.
# ---------------------------------------------------------------------------

# Process-level count of telemetry write failures since boot. Monotonic.
TELEMETRY_FAILURES: int = 0

# Rate-limit window for the WARNING log (seconds). We warn on the very first
# failure, then at most once per window — each warning carries the running
# count so the operator sees the true magnitude despite the suppression.
_FAILURE_WARN_INTERVAL_S: float = 60.0
_last_failure_warn_at: float = 0.0
_failure_lock = threading.Lock()


def note_telemetry_failure(exc: BaseException | None = None) -> None:
    """Record a telemetry-write failure: count it and (rate-limited) warn.

    Non-blocking and never raises — safe to call from any ``except`` arm that
    guards a telemetry write. Increments :data:`TELEMETRY_FAILURES` on every
    call; emits a WARNING on the first failure and then at most once per
    ``_FAILURE_WARN_INTERVAL_S`` seconds, always including the running count so
    a degraded pipeline is visible without flooding the log.
    """
    global TELEMETRY_FAILURES, _last_failure_warn_at
    now = time.monotonic()
    should_warn = False
    with _failure_lock:
        TELEMETRY_FAILURES += 1
        count = TELEMETRY_FAILURES
        if _last_failure_warn_at == 0.0 or (now - _last_failure_warn_at) >= _FAILURE_WARN_INTERVAL_S:
            _last_failure_warn_at = now
            should_warn = True
    if should_warn:
        # Loud: WARNING, not DEBUG. exc_info gives the operator the traceback
        # on the (sampled) lines that do get through the rate limiter.
        logger.warning(
            "Telemetry write failed (%d total since boot): %s",
            count,
            exc,
            exc_info=exc if exc is not None else False,
        )


def telemetry_failure_count() -> int:
    """Return the number of telemetry write failures since process boot.

    Exposed so a health/status endpoint can surface a degraded telemetry
    pipeline (follow-up: wire into ``/health`` alongside the other vitals).
    """
    return TELEMETRY_FAILURES


# W5-a — enum-style label set for the `error_kind` column.
#
# Kept narrow (8 values) so dashboards aggregate cleanly. New values must be
# added here AND in classify_error() below, AND should make the existing
# test_classify_error_* suite still pass.
ERROR_KIND_VALUES = (
    "compile_error",
    "type_cast",
    "security_block",
    "null_ref",
    "timeout",
    "api_misuse",
    "other",
    "none",  # reserved — used externally to mean "no error", not written to DB
)


def classify_error(error_str: str | None) -> str | None:
    """Map a raw error string to one of ERROR_KIND_VALUES.

    Returns:
        ``None``           — when ``error_str`` is falsy (no error occurred).
        ``"compile_error"`` — Roslyn diagnostics (CS####) or the word "compile".
        ``"type_cast"``    — InvalidCastException / "unable to cast".
        ``"security_block"`` — security/validation/forbidden phrases.
        ``"null_ref"``     — NullReferenceException / "object reference".
        ``"timeout"``      — TimeoutError / "timed out" / "timeout".
        ``"api_misuse"``   — ArgumentException / explicit "api_misuse" marker.
        ``"other"``        — non-empty error that didn't match any rule above.

    The matcher is case-insensitive and substring-based — deliberately loose
    so localized variants of Microsoft / .NET error text still classify
    correctly. The ordering matters: compile errors are checked first because
    Roslyn diagnostics frequently embed other keywords (e.g. a CS0019 message
    may contain the word "cast"), and we want them to land in the right
    bucket.
    """
    if not error_str:
        return None
    s = error_str.lower()
    # Compile diagnostics first — Roslyn CS#### codes are unambiguous.
    if "cs1061" in s or "cs0117" in s or "cs0246" in s or "compile" in s:
        return "compile_error"
    if "invalidcastexception" in s or "unable to cast" in s:
        return "type_cast"
    if "security" in s or "validation" in s or "forbidden" in s:
        return "security_block"
    if "nullreferenceexception" in s or "object reference" in s:
        return "null_ref"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    if "api_misuse" in s or "argumentexception" in s:
        return "api_misuse"
    return "other"


@dataclass
class RequestMetrics:
    """Metrics for a single chat request."""

    session_id: str = ""
    category: str = "general"  # count, filter, write, qa, export, general
    tool_calls: list[str] = field(default_factory=list)
    tool_success: int = 0
    tool_failure: int = 0
    llm_rounds: int = 0
    repair_attempts: int = 0
    response_time_ms: int = 0
    error: str = ""  # error type if failed, empty if success
    shortcut_used: bool = False

    # --- W5-a dashboard columns (all NULL-able in DB) ----------------------
    # error_kind is derived from `error` via classify_error() but the caller
    # may override it explicitly (e.g. when the raw error text isn't easy to
    # recover). Set to ``None`` for "no error" — the DB column is NULL.
    error_kind: str | None = None
    # Name of the tool that produced the response (or ``None`` for plain
    # chat). When multiple tools fire in a single request, this stores the
    # *last* one — sufficient for dashboard grouping and matches how
    # `tool_calls` (a list) is rendered in the legacy column.
    tool_name: str | None = None
    # Time from request-received to first stream_chunk yielded, milliseconds.
    # ``None`` when the request errored before any output, or for shortcut
    # responses (which don't stream from the LLM).
    first_token_ms: int | None = None
    # W4 prompt-cache instrumentation. Both default ``None`` so we don't
    # write 0/0 noise during the transition window.
    cached_input_tokens: int | None = None
    total_input_tokens: int | None = None
    # "fast" (default Gemini 3 Flash) or "thinking" (Gemini 3.5 Flash with
    # reasoning_effort=high). NULL on legacy rows.
    mode: str | None = None
    # plan-009 — per-turn RetrievalHealth.to_json() snapshot (which RAG legs
    # ran / degraded for this turn) or NULL when no retrieval happened. Compact
    # JSON string (~600 B).
    retrieval_health: str | None = None


class TelemetryCollector:
    """Collects and stores anonymous usage metrics."""

    def __init__(self, db: Any):
        self._db = db

    async def initialize(self) -> None:
        """Create telemetry tables if they don't exist."""
        await self._db.execute_raw("""
            CREATE TABLE IF NOT EXISTS telemetry_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                session_hash TEXT,
                category TEXT,
                tool_calls TEXT,
                tool_success INTEGER DEFAULT 0,
                tool_failure INTEGER DEFAULT 0,
                llm_rounds INTEGER DEFAULT 0,
                repair_attempts INTEGER DEFAULT 0,
                response_time_ms INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                shortcut_used INTEGER DEFAULT 0
            )
        """)
        await self._db.execute_raw("""
            CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp
                ON telemetry_requests(timestamp)
        """)
        await self._db.execute_raw("""
            CREATE TABLE IF NOT EXISTS telemetry_daily (
                date TEXT PRIMARY KEY,
                total_requests INTEGER DEFAULT 0,
                unique_sessions INTEGER DEFAULT 0,
                shortcut_requests INTEGER DEFAULT 0,
                tool_requests INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                avg_response_ms INTEGER DEFAULT 0
            )
        """)

        # ------------------------------------------------------------------
        # W5-a — extend telemetry_requests with 6 NULL-able dashboard
        # columns. Mirrors backend/migrations/2026_05_20_w5a_telemetry_columns.sql
        # so a fresh deploy self-heals without an out-of-band migration.
        # Each statement is idempotent (ADD COLUMN IF NOT EXISTS / CREATE
        # INDEX IF NOT EXISTS), so this is safe to run on every boot.
        # ------------------------------------------------------------------
        _W5A_STATEMENTS = (
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS error_kind TEXT",
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS tool_name TEXT",
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS first_token_ms INTEGER",
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS cached_input_tokens INTEGER",
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS total_input_tokens INTEGER",
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS mode TEXT",
            # plan-009 — per-turn retrieval_health JSON snapshot.
            "ALTER TABLE telemetry_requests ADD COLUMN IF NOT EXISTS retrieval_health TEXT",
            "CREATE INDEX IF NOT EXISTS idx_telemetry_requests_error_kind "
            "ON telemetry_requests(error_kind) WHERE error_kind IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_telemetry_requests_mode "
            "ON telemetry_requests(mode)",
        )
        for stmt in _W5A_STATEMENTS:
            try:
                await self._db.execute_raw(stmt)
            except Exception:
                # Most likely the underlying backend doesn't speak ALTER TABLE
                # ... ADD COLUMN IF NOT EXISTS (e.g. very old SQLite). Log
                # at DEBUG and continue — record() tolerates missing columns
                # via its own try/except, and the dashboard will simply show
                # NULLs until the operator runs the SQL file manually.
                logger.debug("W5-a migration step failed (non-fatal): %s", stmt, exc_info=True)

    async def record(self, metrics: RequestMetrics) -> None:
        """Record a request's metrics."""
        try:
            # Hash session_id for privacy
            session_hash = (
                hashlib.sha256(metrics.session_id.encode()).hexdigest()[:12]
                if metrics.session_id
                else ""
            )

            # W5-a — derive error_kind from raw error text if the caller
            # didn't set it explicitly. This guarantees the column is
            # populated for every error row, not just ones where the call
            # site remembered to classify.
            error_kind = metrics.error_kind
            if error_kind is None and metrics.error:
                error_kind = classify_error(metrics.error)

            await self._db.execute_raw(
                """INSERT INTO telemetry_requests
                   (session_hash, category, tool_calls, tool_success, tool_failure,
                    llm_rounds, repair_attempts, response_time_ms, error, shortcut_used,
                    error_kind, tool_name, first_token_ms,
                    cached_input_tokens, total_input_tokens, mode, retrieval_health)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_hash,
                    metrics.category,
                    ",".join(metrics.tool_calls),
                    metrics.tool_success,
                    metrics.tool_failure,
                    metrics.llm_rounds,
                    metrics.repair_attempts,
                    metrics.response_time_ms,
                    metrics.error,
                    1 if metrics.shortcut_used else 0,
                    error_kind,
                    metrics.tool_name,
                    metrics.first_token_ms,
                    metrics.cached_input_tokens,
                    metrics.total_input_tokens,
                    metrics.mode,
                    metrics.retrieval_health,
                ),
            )

            # Update daily aggregation.
            #
            # Column refs in the ON CONFLICT DO UPDATE SET clause are
            # explicitly qualified with the table alias `telemetry_daily.X`
            # because Postgres throws AmbiguousColumnError when a bare name
            # is used in an expression that could also resolve via the
            # `excluded` pseudo-table. SQLite tolerates both forms, so this
            # qualification is purely additive — keeps the statement portable
            # between the legacy SQLite path and the asyncpg/Postgres path
            # that production VPS now uses. (Was producing ~15 tracebacks/hr
            # in journalctl — silent at DEBUG level, but monitoring scrapes
            # for "Traceback" and was paging the on-call.)
            await self._db.execute_raw(
                """INSERT INTO telemetry_daily (date, total_requests, unique_sessions,
                     shortcut_requests, tool_requests, errors, avg_response_ms)
                   VALUES (date('now'), 1, 1, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     total_requests = telemetry_daily.total_requests + 1,
                     unique_sessions = (SELECT COUNT(DISTINCT session_hash) FROM telemetry_requests WHERE date(timestamp) = date('now')),
                     shortcut_requests = telemetry_daily.shortcut_requests + excluded.shortcut_requests,
                     tool_requests = telemetry_daily.tool_requests + excluded.tool_requests,
                     errors = telemetry_daily.errors + excluded.errors,
                     avg_response_ms = (telemetry_daily.avg_response_ms * telemetry_daily.total_requests + excluded.avg_response_ms) / (telemetry_daily.total_requests + 1)""",
                (
                    1 if metrics.shortcut_used else 0,
                    1 if metrics.tool_calls else 0,
                    1 if metrics.error else 0,
                    metrics.response_time_ms,
                ),
            )
        except Exception as e:
            # IRON 10 — telemetry write failed. Stay non-blocking (record() is
            # best-effort and must never break a turn) but make it LOUD and
            # COUNTED rather than silent-at-DEBUG.
            note_telemetry_failure(e)

    async def get_summary(self, days: int = 30) -> dict[str, Any]:
        """Get telemetry summary for the admin dashboard."""
        try:
            # Daily stats
            daily = await self._db.fetch_all(
                "SELECT * FROM telemetry_daily ORDER BY date DESC LIMIT ?",
                (days,),
            )

            # Top categories
            categories = await self._db.fetch_all(
                """SELECT category, COUNT(*) as count
                   FROM telemetry_requests
                   WHERE timestamp > datetime('now', ?)
                   GROUP BY category ORDER BY count DESC""",
                (f"-{days} days",),
            )

            # Top tool calls
            tools = await self._db.fetch_all(
                """SELECT tool_calls, COUNT(*) as count
                   FROM telemetry_requests
                   WHERE tool_calls != '' AND timestamp > datetime('now', ?)
                   GROUP BY tool_calls ORDER BY count DESC LIMIT 10""",
                (f"-{days} days",),
            )

            # Error breakdown
            errors = await self._db.fetch_all(
                """SELECT error, COUNT(*) as count
                   FROM telemetry_requests
                   WHERE error != '' AND timestamp > datetime('now', ?)
                   GROUP BY error ORDER BY count DESC LIMIT 10""",
                (f"-{days} days",),
            )

            # Totals
            totals = await self._db.fetch_one(
                """SELECT COUNT(*) as total,
                     COUNT(DISTINCT session_hash) as sessions,
                     AVG(response_time_ms) as avg_ms,
                     SUM(CASE WHEN error != '' THEN 1 ELSE 0 END) as errors,
                     SUM(tool_success) as tool_ok,
                     SUM(tool_failure) as tool_fail,
                     SUM(repair_attempts) as repairs
                   FROM telemetry_requests
                   WHERE timestamp > datetime('now', ?)""",
                (f"-{days} days",),
            )

            return {
                "period_days": days,
                "totals": dict(totals) if totals else {},
                "daily": [dict(d) for d in daily] if daily else [],
                "categories": [dict(c) for c in categories] if categories else [],
                "top_tools": [dict(t) for t in tools] if tools else [],
                "top_errors": [dict(e) for e in errors] if errors else [],
            }
        except Exception:
            logger.exception("Telemetry summary failed")
            return {"error": "Telemetry not available"}

    async def errors_today(self) -> int:
        """Return the number of errors recorded today."""
        try:
            row = await self._db.fetch_one(
                "SELECT errors FROM telemetry_daily WHERE date = date('now')",
            )
            return int(row["errors"]) if row else 0
        except Exception:
            return 0

    async def cleanup(self, keep_days: int = 90) -> int:
        """Delete telemetry_requests older than keep_days. Returns deleted count."""
        try:
            cursor = await self._db.execute_raw(
                "DELETE FROM telemetry_requests WHERE timestamp < datetime('now', ?)",
                (f"-{keep_days} days",),
            )
            return cursor.rowcount if hasattr(cursor, 'rowcount') else 0
        except Exception:
            return 0
