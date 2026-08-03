"""PostgreSQL database — async via asyncpg with connection pool.

This module exposes the same `Database` interface that the rest of the
backend (chat_ws, telemetry, license_manager, command storage, etc.)
already consumes. Public method signatures are unchanged from the
SQLite/aiosqlite implementation.

SQL is written in PostgreSQL dialect:
  - Numbered placeholders ($1, $2, ...)
  - INSERT ... ON CONFLICT DO NOTHING / DO UPDATE
  - asyncpg transactions for atomic DELETE+INSERT

The `raw_connection` property returns a small adapter object that
exposes an aiosqlite-compatible API (.execute, .commit, .rollback,
.executescript, .fetchone, .fetchall, .rowcount) so that
LicenseManager and CommandStorage — which were built around aiosqlite
semantics — keep working without rewrites.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

import asyncpg

from kukai.storage.models import AuditEntry, Message, Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Timestamps remain TEXT (ISO-8601 strings) so existing data and SQL queries
# (e.g. telemetry's "datetime('now')" on the application side) keep working.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_calls TEXT,
        tool_call_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        device_id TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}',
        result TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS project_memory (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL DEFAULT '',
        project_name TEXT NOT NULL,
        summary TEXT NOT NULL,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    # KUKAI_COMPACT_CACHE: rolling context-compaction summary per session.
    # `summary` covers the session's messages up to and including the message
    # whose id is `watermark_id` (`watermark_count` = how many messages that
    # prefix held when the summary was produced — diagnostics only, the id is
    # the source of truth). One row per session, upserted each time the
    # watermark advances.
    """CREATE TABLE IF NOT EXISTS compact_cache (
        session_id TEXT PRIMARY KEY,
        summary TEXT NOT NULL,
        watermark_id TEXT NOT NULL,
        watermark_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""",
    # TurnLedger v1 (KUKAI_TURN_LEDGER, shadow-only): ONE structured row per
    # chat turn — the per-turn observation spine (flags snapshot + ordered
    # events + summary). JSONB, not TEXT, because the planned consumers
    # (grounding gate B2, auto-show B1, golden replay) need server-side joins
    # and containment queries over events. Written at most once per turn by
    # Database.save_turn_ledger; nothing reads it in v1.
    """CREATE TABLE IF NOT EXISTS turn_ledger (
        turn_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT '',
        device_id_hash TEXT NOT NULL DEFAULT '',
        ws_id TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL DEFAULT '',
        schema_v INTEGER NOT NULL DEFAULT 1,
        degraded BOOLEAN NOT NULL DEFAULT FALSE,
        flags_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        events JSONB NOT NULL DEFAULT '[]'::jsonb,
        summary JSONB NOT NULL DEFAULT '{}'::jsonb
    )""",
    # Operation truth v2: one durable row per concrete Revit execution payload.
    # Unlike TurnLedger this is authoritative and is written BEFORE dispatch.
    """CREATE TABLE IF NOT EXISTS operations (
        operation_id TEXT PRIMARY KEY,
        action_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        protocol_version INTEGER NOT NULL DEFAULT 2,
        method TEXT NOT NULL,
        ws_id TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT '',
        tenant_id TEXT NOT NULL DEFAULT '',
        device_id_hash TEXT NOT NULL DEFAULT '',
        phase TEXT NOT NULL,
        attempt_id TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '',
        receipt JSONB,
        error JSONB,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS operation_events (
        id BIGSERIAL PRIMARY KEY,
        operation_id TEXT NOT NULL,
        phase TEXT NOT NULL,
        attempt_id TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TEXT NOT NULL
    )""",
    # A5 live-document ownership.  Expiry is evaluated by PostgreSQL's clock,
    # so workers with skewed host clocks cannot steal or retain a lease.
    """CREATE TABLE IF NOT EXISTS a5_document_leases (
        fingerprint_digest TEXT PRIMARY KEY,
        owner_token TEXT NOT NULL,
        run_id TEXT NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_turn_ledger_session ON turn_ledger(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_turn_ledger_degraded "
    "ON turn_ledger(degraded) WHERE degraded",
    "CREATE INDEX IF NOT EXISTS idx_operations_action ON operations(action_id)",
    "CREATE INDEX IF NOT EXISTS idx_operations_turn ON operations(turn_id)",
    "CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_operations_phase ON operations(phase)",
    "CREATE INDEX IF NOT EXISTS idx_operations_updated ON operations(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_operation "
    "ON operation_events(operation_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_a5_document_leases_expires "
    "ON a5_document_leases(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_project_memory_device_project "
    "ON project_memory(device_id, project_name)",
    "CREATE INDEX IF NOT EXISTS idx_project_memory_created "
    "ON project_memory(created_at)",
)


def _safe_json_loads(s: Any) -> Any:
    """Parse JSON, returning None on error instead of crashing."""
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _json_dict(value: Any) -> Optional[dict[str, Any]]:
    """Normalize asyncpg JSONB (str by default) or an already-decoded dict."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    parsed = _safe_json_loads(value)
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

# Compiled SQL translation regex: replace SQLite "?" placeholders with
# PostgreSQL "$1, $2, ..." numbered placeholders. We respect string literals
# by checking that the "?" is not inside single quotes (a simple state machine).
def _translate_qmark_to_numbered(sql: str) -> str:
    """Convert ? placeholders to $1, $2, ... — respecting string literals.

    Used by the aiosqlite-compatibility adapter so LicenseManager and
    CommandStorage SQL (with ? placeholders) keeps working.
    """
    out: list[str] = []
    i = 0
    in_single = False
    in_double = False
    counter = 0
    while i < len(sql):
        ch = sql[i]
        if in_single:
            out.append(ch)
            if ch == "'":
                # SQLite-style escaped single quote ''
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            counter += 1
            out.append(f"${counter}")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# Patterns we need to translate from SQLite dialect to PostgreSQL dialect
# inside SQL strings that originate from license_manager / commands / telemetry.
_SQLITE_TO_PG_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # INSERT OR IGNORE INTO foo  ->  INSERT INTO foo  (caller appends ON CONFLICT)
    # We translate to INSERT INTO ... and add ON CONFLICT DO NOTHING at the end.
    # Handled below via a more robust regex (post-processing).
    (re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE),
     "INSERT INTO"),
    # AUTOINCREMENT -> (drop; PG uses SERIAL/BIGSERIAL or GENERATED ALWAYS AS IDENTITY)
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE),
     "BIGSERIAL PRIMARY KEY"),
    # BOOLEAN DEFAULT FALSE / TRUE — keep as-is (PG supports it).
    # TIMESTAMP DEFAULT CURRENT_TIMESTAMP -> TIMESTAMPTZ DEFAULT now() — but we
    # don't want to convert ISO TEXT timestamps; we only convert if column type
    # is TIMESTAMP. Leave as TEXT for compat with existing rows.
    # datetime('now') -> CURRENT_TIMESTAMP (used by telemetry default)
    (re.compile(r"datetime\(\s*'now'\s*\)", re.IGNORECASE),
     "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"),
    # date('now') -> to_char(...)
    (re.compile(r"\bdate\(\s*'now'\s*\)", re.IGNORECASE),
     "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD')"),
    # SQLite uses LIMIT N OFFSET M — same in PG, OK.
    # COALESCE same in both, OK.
)

# datetime('now', '-30 days')  -> to_char(now() - interval '30 days', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
# We need a more careful transform here.
_DATETIME_OFFSET_RE = re.compile(
    r"datetime\(\s*'now'\s*,\s*'(?P<sign>[+-]?)\s*(?P<amount>\d+)\s+(?P<unit>day|days|hour|hours|minute|minutes|second|seconds)\s*'\s*\)",
    re.IGNORECASE,
)
_DATETIME_PARAM_OFFSET_RE = re.compile(
    r"datetime\(\s*'now'\s*,\s*\$(?P<n>\d+)\s*\)",
    re.IGNORECASE,
)
# date(timestamp) — on SQLite returns YYYY-MM-DD; on PG date(...) works for
# timestamp/timestamptz, but our timestamps are TEXT. Convert to substring.
_DATE_OF_COL_RE = re.compile(
    r"date\(\s*(?P<expr>[A-Za-z_][\w\.]*)\s*\)",
    re.IGNORECASE,
)


def _translate_datetime_offsets(sql: str) -> str:
    """Translate datetime('now', '-N days') and date(col) into PG equivalents."""

    def _repl_offset(m: re.Match[str]) -> str:
        sign = m.group("sign") or "+"
        amount = m.group("amount")
        unit = m.group("unit").lower().rstrip("s")
        # PG interval syntax
        return (
            f"to_char(now() {sign} interval '{amount} {unit}', "
            f"'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"
        )

    sql = _DATETIME_OFFSET_RE.sub(_repl_offset, sql)

    def _repl_param_offset(m: re.Match[str]) -> str:
        n = m.group("n")
        # The bound parameter is a Python string like "-30 days". We must cast
        # via text first ($n::text::interval), not directly to interval —
        # otherwise asyncpg infers the param type as `interval` and calls
        # interval_encode() which expects a datetime.timedelta and crashes
        # with AttributeError: 'str' object has no attribute 'days'.
        # text→interval cast happens on PG side, so str param is fine.
        return f"to_char(now() + ($" + n + "::text)::interval, 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"

    sql = _DATETIME_PARAM_OFFSET_RE.sub(_repl_param_offset, sql)

    # date(some_column) → substring(some_column, 1, 10)
    def _repl_date_col(m: re.Match[str]) -> str:
        expr = m.group("expr")
        # Don't rewrite date() applied to a literal 'now' (handled elsewhere).
        if expr.lower() == "now":
            return m.group(0)
        return f"substring({expr}, 1, 10)"

    sql = _DATE_OF_COL_RE.sub(_repl_date_col, sql)
    return sql


def _translate_sqlite_sql(sql: str, *, has_qmark: bool = True) -> str:
    """Translate SQLite SQL to PostgreSQL SQL.

    - Converts ? placeholders to $1, $2, ... (if has_qmark=True)
    - Replaces INSERT OR IGNORE with INSERT ... ON CONFLICT DO NOTHING
    - Replaces datetime('now') / date('now') with PG equivalents
    - Replaces datetime('now', '-N days') with PG interval arithmetic
    - Replaces date(col) with substring(col, 1, 10)
    - Replaces INTEGER PRIMARY KEY AUTOINCREMENT with BIGSERIAL PRIMARY KEY
    """
    if has_qmark and "?" in sql:
        sql = _translate_qmark_to_numbered(sql)

    # First handle INSERT OR IGNORE: append ON CONFLICT DO NOTHING if not present.
    # Match "INSERT OR IGNORE INTO <table> (...) VALUES (...)"
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", sql, re.IGNORECASE):
        sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE)
        # Append ON CONFLICT DO NOTHING if not already present
        if "ON CONFLICT" not in sql.upper():
            # Strip trailing semicolon/whitespace, then append
            sql = sql.rstrip().rstrip(";")
            sql += " ON CONFLICT DO NOTHING"

    for pattern, replacement in _SQLITE_TO_PG_PATTERNS:
        sql = pattern.sub(replacement, sql)

    sql = _translate_datetime_offsets(sql)

    # Boolean comparisons: "active = 1" / "active = 0" still work on PG only
    # if active is INTEGER. We declare licensing.active as INTEGER in our PG
    # schema (matching SQLite), so this stays compatible.

    return sql


def _split_sql_statements(script: str) -> list[str]:
    """Split a script into individual statements respecting quotes.

    Used by the executescript adapter. Splits on `;` outside of single quotes.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_single = False
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if in_single:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and script[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


# ---------------------------------------------------------------------------
# aiosqlite-compatibility adapter
# ---------------------------------------------------------------------------


class _RowDict(dict):
    """A dict that also supports tuple-style integer indexing.

    asyncpg.Record supports row["key"] and row[0]; some legacy code reads
    row by index. We materialize records into this hybrid type.
    """

    def __init__(self, data: dict[str, Any], values: list[Any]) -> None:
        super().__init__(data)
        self._values = values

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def __iter__(self):  # type: ignore[override]
        # Default dict iteration yields keys; preserve that.
        return iter(self.keys())


def _record_to_rowdict(rec: asyncpg.Record | None) -> _RowDict | None:
    if rec is None:
        return None
    keys = list(rec.keys())
    values = [rec[k] for k in keys]
    return _RowDict(dict(zip(keys, values)), values)


class _LegacyCursor:
    """Mimics aiosqlite cursor: .fetchone(), .fetchall(), .rowcount, .lastrowid."""

    __slots__ = ("_rows", "_rowcount", "_lastrowid")

    def __init__(
        self,
        rows: list[_RowDict] | None = None,
        rowcount: int = 0,
        lastrowid: int | None = None,
    ) -> None:
        self._rows = rows or []
        self._rowcount = rowcount
        self._lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    async def fetchone(self) -> _RowDict | None:
        if not self._rows:
            return None
        return self._rows[0]

    async def fetchall(self) -> list[_RowDict]:
        return list(self._rows)


class _LegacyConnection:
    """Adapter exposing an aiosqlite-like API on top of the Database's
    per-loop asyncpg pools.

    Provided to LicenseManager and CommandStorage via Database.raw_connection.

    Notes:
      - Each `execute` acquires a fresh pooled connection from whichever pool
        is bound to the current event loop. PostgreSQL is already in
        autocommit-by-default for a single statement, so the explicit
        `commit()` calls in legacy code become no-ops.
      - The adapter is concurrency- and loop-safe; legacy code that runs in
        a different loop than the original connect() will lazily build a
        pool there (this matters for FastAPI's TestClient).
      - Multi-statement transactions still work via `executescript` (each
        statement is committed independently — same behaviour as aiosqlite's
        executescript which auto-commits at the end).
    """

    def __init__(self, database: "Database") -> None:
        self._database = database

    async def _pool(self) -> asyncpg.Pool:
        return await self._database._get_pool()  # noqa: SLF001

    @staticmethod
    def _normalize_params(params: Sequence[Any] | None) -> tuple[Any, ...]:
        if params is None:
            return ()
        if isinstance(params, (tuple, list)):
            return tuple(params)
        # asyncpg expects positional args; wrap a single value
        return (params,)

    async def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> _LegacyCursor:
        """Execute a single statement; return cursor with rows for SELECT."""
        translated = _translate_sqlite_sql(sql)
        args = self._normalize_params(params)
        pool = await self._pool()
        async with pool.acquire() as conn:
            stripped = translated.lstrip().lower()
            if stripped.startswith(("select", "with", "show", "values", "table")):
                records = await conn.fetch(translated, *args)
                rows = [_record_to_rowdict(r) for r in records]
                return _LegacyCursor(rows=[r for r in rows if r is not None], rowcount=len(records))
            # INSERT ... RETURNING  -> fetch
            if " returning " in translated.lower():
                records = await conn.fetch(translated, *args)
                rows = [_record_to_rowdict(r) for r in records]
                lastrow = None
                if rows and "id" in rows[0]:
                    val = rows[0]["id"]
                    if isinstance(val, int):
                        lastrow = val
                return _LegacyCursor(rows=[r for r in rows if r is not None], rowcount=len(records), lastrowid=lastrow)
            # INSERT into a table with a serial `id` column: auto-append
            # RETURNING id so legacy callers that read cursor.lastrowid keep
            # working. Covers plain INSERTs only — for ON CONFLICT DO UPDATE
            # upserts we DON'T do this, because PG sometimes returns
            # AmbiguousColumnError when `RETURNING id` is combined with the
            # ON CONFLICT update clause (the planner can't unambiguously bind
            # `id` between the target row and the EXCLUDED pseudo-row even
            # when only the target has it). Telemetry's daily aggregation
            # upsert is the canonical case that hit this in production.
            # Plain INSERTs and ON CONFLICT DO NOTHING still go through the
            # auto-RETURNING path; ON CONFLICT DO UPDATE always falls through.
            lastrowid: int | None = None
            lower = translated.lstrip().lower()
            looks_like_returnable_insert = (
                lower.startswith("insert ")
                and "returning" not in lower
                and "on conflict" not in lower  # skip ALL ON CONFLICT variants
            )
            if looks_like_returnable_insert:
                try:
                    rec = await conn.fetchrow(translated + " RETURNING id", *args)
                    if rec is not None:
                        try:
                            val = rec["id"]
                            if isinstance(val, int):
                                lastrowid = val
                        except (KeyError, IndexError):
                            pass
                    return _LegacyCursor(rowcount=1, lastrowid=lastrowid)
                except (
                    asyncpg.exceptions.UndefinedColumnError,
                    asyncpg.exceptions.PostgresSyntaxError,
                    asyncpg.exceptions.AmbiguousColumnError,
                ):
                    # Table has no `id` column, RETURNING isn't applicable,
                    # or the planner can't bind `id` cleanly — fall through
                    # to a plain execute and live without lastrowid.
                    pass
            # INSERT/UPDATE/DELETE/DDL — use execute() and parse status
            status = await conn.execute(translated, *args)
            rowcount = _parse_status_rowcount(status)
            return _LegacyCursor(rowcount=rowcount, lastrowid=lastrowid)

    async def executescript(self, script: str) -> _LegacyCursor:
        """Execute multiple statements separated by `;`."""
        translated = _translate_sqlite_sql(script, has_qmark=False)
        statements = _split_sql_statements(translated)
        pool = await self._pool()
        async with pool.acquire() as conn:
            for stmt in statements:
                if stmt.strip():
                    await conn.execute(stmt)
        return _LegacyCursor()

    async def commit(self) -> None:
        """No-op: each execute() runs in its own pooled connection (autocommit)."""
        return None

    async def rollback(self) -> None:
        """No-op: there's no open transaction to roll back at this layer."""
        return None

    async def close(self) -> None:
        """No-op: the pool owns the lifecycle."""
        return None


def _parse_status_rowcount(status: str) -> int:
    """Parse asyncpg's status string ("INSERT 0 5", "UPDATE 3", "DELETE 2") to rowcount."""
    if not status:
        return 0
    parts = status.split()
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class Database:
    """Async PostgreSQL database with connection pool.

    Public API matches the previous SQLite implementation. Behaviour for
    `replace_project_memories` uses an asyncpg transaction (atomic
    DELETE + INSERT) — strictly more robust than the BEGIN IMMEDIATE
    serialization the SQLite version needed.
    """

    # Pool sizing — small overhead, plenty of room for production load.
    DEFAULT_MIN_POOL = 2
    DEFAULT_MAX_POOL = 20

    def __init__(
        self,
        dsn_or_path: str,
        *,
        min_pool: Optional[int] = None,
        max_pool: Optional[int] = None,
        schema: Optional[str] = None,
    ) -> None:
        # Accept a Path-like string for backward compat with tests/main that
        # pass a SQLite-style path. If it doesn't look like a postgres:// URL,
        # we resolve a real DSN (env override or default 127.0.0.1) AND derive
        # a unique PG schema name from the path so each test gets its own
        # isolated namespace inside the shared dev database. Without this,
        # parallel test runs and per-test tmp_path setups would all share the
        # same `public` schema and stomp on each other.
        original = str(dsn_or_path)
        dsn = self._coerce_dsn(original)
        self._dsn = dsn
        # Per-event-loop connection pools.
        # asyncpg pools are bound to the loop that created them; FastAPI's
        # TestClient runs requests in a different loop than the one that
        # constructed the Database fixture, so we keep a pool per loop.
        # In production (single uvicorn loop) this is just one entry.
        self._pools: dict[Any, asyncpg.Pool] = {}
        # Lock per loop guards lazy pool creation — separate dict because
        # asyncio.Lock is also loop-bound.
        self._pool_locks: dict[Any, asyncio.Lock] = {}
        self._min_pool = min_pool if min_pool is not None else self.DEFAULT_MIN_POOL
        self._max_pool = max_pool if max_pool is not None else self.DEFAULT_MAX_POOL
        # Mostly historical — kept so legacy attribute access doesn't crash.
        self._write_lock = asyncio.Lock()
        self._raw: Optional[_LegacyConnection] = None
        # If the caller passed a SQLite-style path (typical for tests), give
        # them a private schema named from the path. Real DSNs use the default
        # `public` schema unless `schema=` is set explicitly.
        if schema is None and not original.startswith(("postgresql://", "postgres://")):
            schema = self._schema_from_path(original)
        self._schema = schema or "public"
        self._connected = False
        self._schema_initialized = False

    @staticmethod
    def _schema_from_path(path: str) -> str:
        """Derive a stable, valid PG schema name from a filesystem path.

        Used when tests construct `Database(tmp_path / 'test.db')`: each
        test_path produces a distinct schema, giving us per-test isolation
        without needing a CREATE DATABASE per test.
        """
        import hashlib
        digest = hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"kukai_t_{digest}"

    @staticmethod
    def _coerce_dsn(value: str) -> str:
        """Accept either a PG DSN or a legacy SQLite path; resolve to a DSN.

        Resolution order:
          1. The value itself if it starts with postgresql:// or postgres://
          2. KUKAI_DATABASE_URL env var
          3. A 127.0.0.1 default — postgresql://kukai:kukai@127.0.0.1:5432/kukai
             (NB: 127.0.0.1 not localhost — `localhost` on Windows can prefer
             IPv6 and stall connect() for ~40s while the IPv6 attempt times out.)
        """
        import os

        s = str(value)
        if s.startswith(("postgresql://", "postgres://")):
            return s
        env = os.environ.get("KUKAI_DATABASE_URL", "").strip()
        if env:
            return env
        return "postgresql://kukai:kukai@127.0.0.1:5432/kukai"

    # --- Lifecycle ---

    async def connect(self) -> None:
        """Open the connection pool for the current event loop and initialize
        schema. Safe to call from any loop; subsequent calls in other loops
        lazily build a pool there too (used by FastAPI's TestClient).
        """
        await self._get_pool()
        self._connected = True

    async def _get_pool(self) -> asyncpg.Pool:
        """Return the asyncpg pool for the current running loop, creating it
        on first use. Concurrent calls in the same loop are serialized via a
        per-loop asyncio.Lock so we only ever create one pool per loop.
        """
        loop = asyncio.get_running_loop()
        existing = self._pools.get(loop)
        if existing is not None and not existing._closed:  # noqa: SLF001
            return existing

        # Per-loop lock so two concurrent first-callers don't both build a pool.
        lock = self._pool_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._pool_locks[loop] = lock

        async with lock:
            existing = self._pools.get(loop)
            if existing is not None and not existing._closed:  # noqa: SLF001
                return existing

            schema = self._schema

            async def _setup_conn(conn: asyncpg.Connection) -> None:
                # Each pooled connection sets its search_path so SQL written
                # without schema-qualification still hits our schema.
                # NB: asyncpg's pool resets session state on release (RESET
                # ALL), which would wipe this. We compensate by re-setting
                # in `setup` (called on every acquire), not just `init`.
                await conn.execute(f'SET search_path TO "{schema}"')

            # Create the schema on the first connect (in the first loop) only;
            # other loops share the catalog already.
            if schema != "public" and not self._schema_initialized:
                bootstrap = await asyncpg.connect(self._dsn)
                try:
                    await bootstrap.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                finally:
                    await bootstrap.close()

            pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_pool,
                max_size=self._max_pool,
                command_timeout=60.0,
                # `setup` runs on every acquire (after the post-release reset),
                # `init` runs once when the connection is first created. We use
                # `setup` so search_path survives RESET ALL between acquires.
                setup=_setup_conn,
            )

            if not self._schema_initialized:
                async with pool.acquire() as conn:
                    for stmt in SCHEMA_STATEMENTS:
                        await conn.execute(stmt)
                self._schema_initialized = True

            self._pools[loop] = pool
            self._raw = _LegacyConnection(self)
            masked = re.sub(r"://[^@]*@", "://***@", self._dsn)
            logger.info("Database connected: %s (schema=%s)", masked, schema)
            return pool

    async def close(self) -> None:
        if not self._pools:
            self._connected = False
            return
        schema = self._schema
        # Close every per-loop pool. Each must be closed from its own loop;
        # if we're not in one of those loops we close it via run_until_complete
        # — but in practice the typical path is "create+close in same loop".
        for loop, pool in list(self._pools.items()):
            try:
                if asyncio.get_running_loop() is loop:
                    await pool.close()
                else:
                    pool.terminate()
            except RuntimeError:
                # No running loop (shouldn't happen — close() is async).
                pool.terminate()
            except Exception:
                logger.debug("pool close failed", exc_info=True)
        self._pools.clear()
        self._pool_locks.clear()
        self._raw = None
        self._connected = False
        self._schema_initialized = False
        # Drop test schemas eagerly so PG doesn't accumulate junk between
        # test runs. We never drop `public` (production) or schemas we didn't
        # create ourselves.
        if schema != "public" and schema.startswith("kukai_t_"):
            try:
                bootstrap = await asyncpg.connect(self._dsn)
                try:
                    await bootstrap.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                finally:
                    await bootstrap.close()
            except Exception:
                logger.debug("test schema cleanup failed for %s", schema, exc_info=True)

    async def _ensure_pool(self) -> asyncpg.Pool:
        if not self._connected and not self._pools:
            raise RuntimeError("Database not connected. Call connect() first.")
        return await self._get_pool()

    # Kept for backward compatibility — some tests reach into `_ensure_connected()`.
    def _ensure_connected(self) -> _LegacyConnection:
        if not self._connected:
            raise RuntimeError("Database not connected. Call connect() first.")
        if self._raw is None:
            self._raw = _LegacyConnection(self)
        return self._raw

    @property
    def raw_connection(self) -> _LegacyConnection:
        """Public access to an aiosqlite-compatible adapter over the PG pool.

        Used by LicenseManager and CommandStorage which were written against
        aiosqlite's API. The adapter translates SQLite SQL/placeholders to
        PostgreSQL on every call.
        """
        if self._raw is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._raw

    # --- Sessions ---

    async def get_or_create_session(self, session_id: str, device_id: str = "") -> Session:
        """Get existing session or create a new one (race-safe)."""
        pool = await self._ensure_pool()
        now = datetime.now(timezone.utc).isoformat()

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO sessions (id, device_id, created_at, updated_at) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
                    session_id, device_id, now, now,
                )
                await conn.execute(
                    "UPDATE sessions SET updated_at = $1 WHERE id = $2",
                    now, session_id,
                )
                row = await conn.fetchrow(
                    "SELECT * FROM sessions WHERE id = $1",
                    session_id,
                )

        if row is None:
            # Should be unreachable — INSERT just ran — but be defensive.
            raise RuntimeError(f"Session {session_id!r} vanished after INSERT")

        return Session(
            id=row["id"],
            device_id=row["device_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(now),
            metadata=_safe_json_loads(row["metadata"]) or {},
        )

    async def get_session_device_id(self, session_id: str) -> str | None:
        """Get the device_id that owns a session, or None if missing."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT device_id FROM sessions WHERE id = $1",
                session_id,
            )
        if row:
            return row["device_id"]
        return None

    async def claim_unowned_session(self, session_id: str, device_id: str) -> bool:
        """Claim an existing session whose device_id is empty.

        Race-safe: the WHERE clause includes `device_id = ''`, so two
        simultaneous claims won't both succeed — only the first UPDATE
        actually changes a row.

        Returns True if the row was updated (this device became the owner),
        False if no matching row (session already owned, or doesn't exist).
        """
        if not device_id:
            return False  # Nothing to claim with.
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE sessions SET device_id = $1 WHERE id = $2 AND device_id = ''",
                device_id,
                session_id,
            )
        # asyncpg returns string like "UPDATE 1" or "UPDATE 0".
        try:
            return int(str(result).split()[-1]) > 0
        except (ValueError, IndexError):
            return False

    # --- Messages ---

    async def save_message(self, message: Message) -> None:
        """Save a chat message."""
        pool = await self._ensure_pool()
        tool_calls_json = json.dumps(message.tool_calls) if message.tool_calls else None
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO messages
                       (id, session_id, role, content, tool_calls, tool_call_id, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                message.id,
                message.session_id,
                message.role,
                message.content,
                tool_calls_json,
                message.tool_call_id,
                message.created_at.isoformat(),
            )

    async def save_turn(self, messages: list[Message]) -> None:
        """Save several messages ATOMICALLY — all land or none do (one txn).

        Step 6: the assistant-with-tool_calls message and its tool-result
        message must be persisted together. With two separate save_message
        calls, a failure between them leaves an orphaned assistant tool_call
        with no matching tool result; the next turn rebuilds an invalid history
        (an LLM API rejects tool_calls not followed by tool messages) and the
        session is permanently bricked. A single transaction removes that
        window: on any error nothing is written, so history stays consistent.
        """
        if not messages:
            return
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for message in messages:
                    tool_calls_json = (
                        json.dumps(message.tool_calls) if message.tool_calls else None
                    )
                    await conn.execute(
                        """INSERT INTO messages
                               (id, session_id, role, content, tool_calls, tool_call_id, created_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        message.id,
                        message.session_id,
                        message.role,
                        message.content,
                        tool_calls_json,
                        message.tool_call_id,
                        message.created_at.isoformat(),
                    )

    async def save_turn_ledger(self, row: dict[str, Any]) -> None:
        """Persist ONE TurnLedger row (TurnLedger v1, KUKAI_TURN_LEDGER).

        Called at most once per turn from turn_ledger.flush_turn (the single
        sink write — there are NO per-event writes in v1). Upsert by turn_id so a
        duplicate flush of the same turn is idempotent. The caller treats any
        exception as non-fatal and falls back to the JSONL tee — this method may
        raise normally (fail-open lives in the instrument, not the storage layer)."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO turn_ledger
                       (turn_id, session_id, tenant_id, device_id_hash, ws_id,
                        started_at, ended_at, schema_v, degraded,
                        flags_snapshot, events, summary)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                           $10::jsonb, $11::jsonb, $12::jsonb)
                   ON CONFLICT (turn_id) DO UPDATE SET
                       ended_at = EXCLUDED.ended_at,
                       degraded = EXCLUDED.degraded,
                       flags_snapshot = EXCLUDED.flags_snapshot,
                       events = EXCLUDED.events,
                       summary = EXCLUDED.summary""",
                str(row.get("turn_id", "")),
                str(row.get("session_id", "")),
                str(row.get("tenant_id", "")),
                str(row.get("device_id_hash", "")),
                str(row.get("ws_id", "")),
                str(row.get("started_at", "")),
                str(row.get("ended_at", "")),
                int(row.get("schema_v", 1)),
                bool(row.get("degraded", False)),
                json.dumps(row.get("flags_snapshot") or {}, ensure_ascii=False, default=str),
                json.dumps(row.get("events") or [], ensure_ascii=False, default=str),
                json.dumps(row.get("summary") or {}, ensure_ascii=False, default=str),
            )

    async def cleanup_turn_ledger(self, keep_days: int = 30) -> int:
        """Delete TurnLedger rows older than keep_days (TurnLedger v1 has one row
        per turn and no retention on its own). started_at is ISO-8601 TEXT, so a
        lexicographic `<` is chronological. Returns the number of rows deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM turn_ledger WHERE started_at < $1", cutoff,
            )
        try:
            return int(str(status).split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    # --- A5 durable document lease -----------------------------------------

    @staticmethod
    def _validate_a5_lease_args(
        fingerprint_digest: str,
        owner_token: str,
        *,
        run_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        if not isinstance(fingerprint_digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", fingerprint_digest):
            raise ValueError("fingerprint_digest must be lowercase sha256")
        if not isinstance(owner_token, str) or not re.fullmatch(
                r"[0-9a-f]{32}", owner_token):
            raise ValueError("owner_token must be 128-bit lowercase hex")
        if run_id is not None and (
                not isinstance(run_id, str)
                or not re.fullmatch(r"[0-9a-f]{16}", run_id)):
            raise ValueError("run_id must be 64-bit lowercase hex")
        if ttl_seconds is not None and (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, int)
                or not 3 <= ttl_seconds <= 3600):
            raise ValueError("ttl_seconds must be an integer within [3, 3600]")

    async def acquire_a5_document_lease(
        self,
        fingerprint_digest: str,
        owner_token: str,
        run_id: str,
        ttl_seconds: int,
    ) -> bool:
        """Atomically acquire an absent/expired lease for one document."""

        self._validate_a5_lease_args(
            fingerprint_digest, owner_token, run_id=run_id,
            ttl_seconds=ttl_seconds)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO a5_document_leases
                       (fingerprint_digest, owner_token, run_id, acquired_at,
                        heartbeat_at, expires_at)
                   VALUES ($1, $2, $3, NOW(), NOW(),
                           NOW() + make_interval(secs => $4))
                   ON CONFLICT (fingerprint_digest) DO UPDATE SET
                       owner_token = EXCLUDED.owner_token,
                       run_id = EXCLUDED.run_id,
                       acquired_at = NOW(),
                       heartbeat_at = NOW(),
                       expires_at = NOW() + make_interval(secs => $4)
                   WHERE a5_document_leases.expires_at <= NOW()
                   RETURNING owner_token""",
                fingerprint_digest, owner_token, run_id, ttl_seconds,
            )
        return row is not None and row["owner_token"] == owner_token

    async def renew_a5_document_lease(
        self,
        fingerprint_digest: str,
        owner_token: str,
        ttl_seconds: int,
    ) -> bool:
        """Renew only the still-live lease held by this exact owner."""

        self._validate_a5_lease_args(
            fingerprint_digest, owner_token, ttl_seconds=ttl_seconds)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE a5_document_leases
                   SET heartbeat_at = NOW(),
                       expires_at = NOW() + make_interval(secs => $3)
                   WHERE fingerprint_digest = $1 AND owner_token = $2
                     AND expires_at > NOW()
                   RETURNING owner_token""",
                fingerprint_digest, owner_token, ttl_seconds,
            )
        return row is not None and row["owner_token"] == owner_token

    async def release_a5_document_lease(
        self,
        fingerprint_digest: str,
        owner_token: str,
    ) -> bool:
        """Release only the lease held by this exact owner token."""

        self._validate_a5_lease_args(fingerprint_digest, owner_token)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """DELETE FROM a5_document_leases
                   WHERE fingerprint_digest = $1 AND owner_token = $2
                   RETURNING owner_token""",
                fingerprint_digest, owner_token,
            )
        return row is not None and row["owner_token"] == owner_token

    # --- Operation truth v2 -------------------------------------------------

    @staticmethod
    def _operation_record(row: Any) -> dict[str, Any]:
        """Convert an asyncpg Record into the operation-store wire shape."""
        data = dict(row)
        data["receipt"] = _json_dict(data.get("receipt"))
        data["error"] = _json_dict(data.get("error"))
        return data

    async def create_operation(self, row: dict[str, Any]) -> dict[str, Any]:
        """Write-ahead create of one immutable operation identity.

        Replaying the same operation/payload is idempotent. Reusing an
        operation id for another action, method or payload is a hard conflict.
        The row and its first event are committed in one DB transaction.
        """
        from kukai.operations.store import OperationConflict

        now = str(row.get("created_at") or datetime.now(timezone.utc).isoformat())
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    """INSERT INTO operations
                           (operation_id, action_id, turn_id, payload_hash,
                            protocol_version, method, ws_id, session_id,
                            tenant_id, device_id_hash, phase, attempt_id,
                            outcome, receipt, error, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                               $11, $12, $13, $14::jsonb, $15::jsonb, $16, $17)
                       ON CONFLICT (operation_id) DO NOTHING
                       RETURNING *""",
                    str(row.get("operation_id", "")),
                    str(row.get("action_id", "")),
                    str(row.get("turn_id", "")),
                    str(row.get("payload_hash", "")),
                    int(row.get("protocol_version", 2)),
                    str(row.get("method", "")),
                    str(row.get("ws_id", "")),
                    str(row.get("session_id", "")),
                    str(row.get("tenant_id", "")),
                    str(row.get("device_id_hash", "")),
                    str(row.get("phase", "persisted_server")),
                    str(row.get("attempt_id", "")),
                    str(row.get("outcome", "")),
                    json.dumps(row.get("receipt"), ensure_ascii=False, default=str)
                    if row.get("receipt") is not None else None,
                    json.dumps(row.get("error"), ensure_ascii=False, default=str)
                    if row.get("error") is not None else None,
                    now,
                    now,
                )
                if inserted is not None:
                    await conn.execute(
                        """INSERT INTO operation_events
                               (operation_id, phase, attempt_id, outcome, payload, created_at)
                           VALUES ($1, $2, $3, $4, '{}'::jsonb, $5)""",
                        str(row.get("operation_id", "")),
                        str(row.get("phase", "persisted_server")),
                        str(row.get("attempt_id", "")),
                        str(row.get("outcome", "")),
                        now,
                    )
                    return self._operation_record(inserted)

                existing = await conn.fetchrow(
                    "SELECT * FROM operations WHERE operation_id = $1 FOR UPDATE",
                    str(row.get("operation_id", "")),
                )
                if existing is None:  # pragma: no cover - impossible under PK conflict
                    raise RuntimeError("operation disappeared after conflict")
                if (
                    existing["action_id"] != str(row.get("action_id", ""))
                    or existing["payload_hash"] != str(row.get("payload_hash", ""))
                    or existing["method"] != str(row.get("method", ""))
                    or int(existing["protocol_version"]) != int(row.get("protocol_version", 2))
                ):
                    raise OperationConflict(
                        "operation id reused with conflicting immutable identity"
                    )
                return self._operation_record(existing)

    async def transition_operation(
        self,
        operation_id: str,
        phase: str,
        *,
        attempt_id: str = "",
        outcome: str = "",
        receipt: Optional[dict[str, Any]] = None,
        error: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Atomically advance an operation and append its lifecycle event."""
        from kukai.operations.protocol import transition_allowed
        from kukai.operations.store import OperationConflict

        now = datetime.now(timezone.utc).isoformat()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT * FROM operations WHERE operation_id = $1 FOR UPDATE",
                    operation_id,
                )
                if current is None:
                    raise KeyError(operation_id)
                if not transition_allowed(str(current["phase"]), phase):
                    raise OperationConflict(
                        f"illegal operation transition {current['phase']} -> {phase}"
                    )

                current_receipt = _json_dict(current["receipt"])
                if current_receipt is not None and receipt is not None and current_receipt != receipt:
                    raise OperationConflict("terminal receipt changed on replay")

                next_attempt = attempt_id or str(current["attempt_id"] or "")
                next_outcome = outcome or str(current["outcome"] or "")
                next_receipt = receipt if receipt is not None else current_receipt
                current_error = _json_dict(current["error"])
                next_error = error if error is not None else current_error

                updated = await conn.fetchrow(
                    """UPDATE operations SET
                           phase = $2, attempt_id = $3, outcome = $4,
                           receipt = $5::jsonb, error = $6::jsonb, updated_at = $7
                       WHERE operation_id = $1
                       RETURNING *""",
                    operation_id,
                    phase,
                    next_attempt,
                    next_outcome,
                    json.dumps(next_receipt, ensure_ascii=False, default=str)
                    if next_receipt is not None else None,
                    json.dumps(next_error, ensure_ascii=False, default=str)
                    if next_error is not None else None,
                    now,
                )
                await conn.execute(
                    """INSERT INTO operation_events
                           (operation_id, phase, attempt_id, outcome, payload, created_at)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6)""",
                    operation_id,
                    phase,
                    next_attempt,
                    next_outcome,
                    json.dumps(
                        {
                            "has_receipt": receipt is not None,
                            "has_error": error is not None,
                        }
                    ),
                    now,
                )
                if updated is None:  # pragma: no cover - row locked above
                    raise RuntimeError("operation update returned no row")
                return self._operation_record(updated)

    async def get_operation(self, operation_id: str) -> Optional[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM operations WHERE operation_id = $1",
                operation_id,
            )
        return self._operation_record(row) if row is not None else None

    async def cleanup_operations(
        self, keep_days: int = 90, stuck_keep_days: int = 180
    ) -> int:
        """Remove old terminal operation rows and their append-only events.

        Rows that never reached a terminal phase (e.g. RUNNING_UNKNOWN left by an
        old client that cannot deliver receipts, or SENT rows from a crashed
        turn) are evidence, so they get a LONGER retention — but not an infinite
        one, or the table grows monotonically (verified 2026-07-16: nothing else
        ever deletes them).
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        stuck_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=stuck_keep_days)
        ).isoformat()
        terminal = (
            "acknowledged",
            "rolled_back",
            "failed_before_commit",
            "cancelled_before_start",
        )
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT operation_id FROM operations "
                    "WHERE (updated_at < $1 AND phase = ANY($2::text[])) "
                    "   OR updated_at < $3",
                    cutoff,
                    list(terminal),
                    stuck_cutoff,
                )
                ids = [str(row["operation_id"]) for row in rows]
                if not ids:
                    return 0
                await conn.execute(
                    "DELETE FROM operation_events WHERE operation_id = ANY($1::text[])",
                    ids,
                )
                await conn.execute(
                    "DELETE FROM operations WHERE operation_id = ANY($1::text[])",
                    ids,
                )
                return len(ids)

    async def get_session_messages(
        self, session_id: str, limit: int = 500
    ) -> list[Message]:
        """Get the most recent messages for a session in chronological order."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM (
                       SELECT * FROM messages WHERE session_id = $1
                       ORDER BY created_at DESC LIMIT $2
                   ) sub ORDER BY created_at ASC""",
                session_id, limit,
            )
        return [
            Message(
                id=r["id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                tool_calls=_safe_json_loads(r["tool_calls"]) if r["tool_calls"] else None,
                tool_call_id=r["tool_call_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- Context compaction cache (KUKAI_COMPACT_CACHE) ---

    async def get_compact_cache(self, session_id: str) -> Optional[dict[str, Any]]:
        """Load the persisted rolling compaction summary for a session.

        Returns {summary, watermark_id, watermark_count, updated_at} or None
        when the session has never been compacted. The summary covers the
        session's messages up to and including `watermark_id`.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT summary, watermark_id, watermark_count, updated_at "
                "FROM compact_cache WHERE session_id = $1",
                session_id,
            )
        if row is None:
            return None
        return {
            "summary": row["summary"],
            "watermark_id": row["watermark_id"],
            "watermark_count": row["watermark_count"],
            "updated_at": row["updated_at"],
        }

    async def save_compact_cache(
        self,
        session_id: str,
        summary: str,
        watermark_id: str,
        watermark_count: int,
    ) -> None:
        """Upsert the rolling compaction summary for a session.

        One row per session; ON CONFLICT DO UPDATE makes concurrent turns
        race-safe (last writer wins — the loser's watermark self-heals on the
        next turn because reuse is validated against the live history).
        """
        pool = await self._ensure_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO compact_cache
                       (session_id, summary, watermark_id, watermark_count, updated_at)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (session_id) DO UPDATE SET
                       summary = EXCLUDED.summary,
                       watermark_id = EXCLUDED.watermark_id,
                       watermark_count = EXCLUDED.watermark_count,
                       updated_at = EXCLUDED.updated_at""",
                session_id, summary, watermark_id, watermark_count, now,
            )

    async def delete_compact_cache(self, session_id: str) -> None:
        """Drop the persisted summary for a session (history invalidated)."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM compact_cache WHERE session_id = $1",
                session_id,
            )

    # --- Project Memory ---

    async def save_project_memory(
        self,
        device_id: str,
        project_name: str,
        summary: str,
        message_count: int = 0,
    ) -> None:
        """Save a project memory entry (per device + project)."""
        pool = await self._ensure_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO project_memory
                       (id, device_id, project_name, summary, message_count, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                str(uuid.uuid4()), device_id, project_name, summary, message_count, now,
            )

    async def get_project_memories(
        self, device_id: str, project_name: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all memory entries for a device+project, chronologically."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT summary, message_count, created_at FROM project_memory
                   WHERE device_id = $1 AND project_name = $2
                   ORDER BY created_at ASC LIMIT $3""",
                device_id, project_name, limit,
            )
        return [
            {"summary": r["summary"], "message_count": r["message_count"],
             "created_at": r["created_at"]}
            for r in rows
        ]

    async def replace_project_memories(
        self,
        device_id: str,
        project_name: str,
        compacted_summary: str,
        total_messages: int,
    ) -> None:
        """Atomically replace all memory entries for a device+project with one
        compacted entry. Uses a real PG transaction — strictly more robust
        than the SQLite BEGIN IMMEDIATE + asyncio.Lock hack the previous
        implementation needed.
        """
        pool = await self._ensure_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM project_memory WHERE device_id = $1 AND project_name = $2",
                    device_id, project_name,
                )
                await conn.execute(
                    """INSERT INTO project_memory
                           (id, device_id, project_name, summary, message_count, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    str(uuid.uuid4()), device_id, project_name,
                    compacted_summary, total_messages, now,
                )

    async def count_project_memories(self, device_id: str, project_name: str) -> int:
        """Count memory entries for a device+project."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM project_memory "
                "WHERE device_id = $1 AND project_name = $2",
                device_id, project_name,
            )
        return int(row["cnt"]) if row else 0

    # --- Audit ---

    async def log_audit(
        self,
        session_id: str,
        action: str,
        details: dict[str, Any] | None = None,
        result: str = "",
        device_id: str = "",
    ) -> AuditEntry:
        """Record a write operation in the audit log."""
        pool = await self._ensure_pool()
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            device_id=device_id,
            action=action,
            details=details or {},
            result=result,
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                       (id, session_id, device_id, action, details, result, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                entry.id,
                entry.session_id,
                entry.device_id,
                entry.action,
                json.dumps(entry.details),
                entry.result,
                entry.created_at.isoformat(),
            )
        return entry

    async def get_audit_log(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[AuditEntry]:
        """Get audit entries, optionally filtered by session."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    "SELECT * FROM audit_log WHERE session_id = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    session_id, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
        return [
            AuditEntry(
                id=r["id"],
                session_id=r["session_id"],
                device_id=r["device_id"],
                action=r["action"],
                details=_safe_json_loads(r["details"]) or {},
                result=r["result"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- Usage tracking ---

    async def get_weekly_usage(self, session_id: str) -> int:
        """Count user messages in the last 7 days for sliding window rate limiting."""
        pool = await self._ensure_pool()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT COUNT(*) AS cnt FROM messages
                   WHERE session_id = $1 AND role = 'user' AND created_at >= $2""",
                session_id, cutoff,
            )
        return int(row["cnt"]) if row else 0

    # --- Cleanup ---

    async def cleanup_old_sessions(self, ttl_days: int = 30) -> int:
        """Delete sessions and their messages older than ttl_days."""
        pool = await self._ensure_pool()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM sessions WHERE updated_at < $1",
                cutoff,
            )
            if not rows:
                return 0
            ids = [r["id"] for r in rows]
            async with conn.transaction():
                # PG ANY() lets us pass an array of values without batching.
                await conn.execute(
                    "DELETE FROM messages WHERE session_id = ANY($1::text[])",
                    ids,
                )
                await conn.execute(
                    "DELETE FROM audit_log WHERE session_id = ANY($1::text[])",
                    ids,
                )
                await conn.execute(
                    "DELETE FROM compact_cache WHERE session_id = ANY($1::text[])",
                    ids,
                )
                await conn.execute(
                    "DELETE FROM sessions WHERE id = ANY($1::text[])",
                    ids,
                )
        logger.info("Cleaned up %d old sessions", len(ids))
        return len(ids)

    # --- Raw query helpers (telemetry, migrations, etc.) ---

    async def execute_raw(self, sql: str, params: tuple = ()) -> _LegacyCursor:
        """Execute raw SQL (used by telemetry).

        Translates SQLite syntax to PostgreSQL on the fly so existing callers
        with `?` placeholders and `datetime('now', '-N days')` keep working.
        Returns a cursor-like object so callers that use .rowcount work too.
        """
        return await self._raw.execute(sql, params) if self._raw else _LegacyCursor()

    async def fetch_all(self, sql: str, params: tuple = ()) -> list:
        """Fetch all rows from a raw SQL query."""
        cur = await self.execute_raw(sql, params)
        return await cur.fetchall()

    async def fetch_one(self, sql: str, params: tuple = ()):
        """Fetch one row from a raw SQL query."""
        cur = await self.execute_raw(sql, params)
        return await cur.fetchone()

    # --- Session clear ---

    async def clear_session(self, session_id: str) -> None:
        """Delete all messages for a session (keep the session itself).

        Also drops the compact_cache row: with the history gone, the persisted
        rolling summary describes messages that no longer exist. (Reuse is
        watermark-validated anyway, so a stale row could never be folded in —
        this is hygiene, not correctness.)
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM messages WHERE session_id = $1",
                session_id,
            )
            await conn.execute(
                "DELETE FROM compact_cache WHERE session_id = $1",
                session_id,
            )
