"""RAG telemetry -- per-query trace for self-improvement loop.

Logs four correlated event streams to JSONL files:
  - rag_retrieval.jsonl  : what was retrieved before each LLM call
  - rag_compile.jsonl    : Roslyn compile outcome per query
  - rag_execute.jsonl    : Bridge execution outcome per query
  - eval_verdicts.jsonl  : the Evaluator's deterministic verdict per write
                           (plan 020, IRON 3 — shadow mode)
  - capability_shadow.jsonl : what capability-resolve WOULD have reordered,
                           observe-only (Stage 2.1-shadow, SHADOW_REPORT.md)

All rows share a query_id (UUID) so they can be joined.

Design principles:
  - NEVER blocks user flow: writes go through a fire-and-forget queue
  - Append-only: log files are never truncated or rewritten
  - Privacy: emails/phones stripped from queries; doc names hashed
  - Daily rotation when a file exceeds 100 MB
  - File permissions: 0644
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from kukai.telemetry import note_telemetry_failure

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------

def _telemetry_dir() -> Path:
    here = Path(__file__).parent.parent  # backend/
    tel = here / "data" / "telemetry"
    tel.mkdir(parents=True, exist_ok=True)
    return tel


def _log_path(name: str) -> Path:
    """Return active log file path, rotating if file exceeds 100 MB."""
    base_dir = _telemetry_dir()
    active = base_dir / f"{name}.jsonl"

    if active.exists() and active.stat().st_size > 100 * 1024 * 1024:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rotated = base_dir / f"{name}.{stamp}.jsonl"
        if rotated.exists():
            for i in range(1, 100):
                candidate = base_dir / f"{name}.{stamp}.{i}.jsonl"
                if not candidate.exists():
                    rotated = candidate
                    break
        try:
            active.rename(rotated)
            logger.info("Rotated %s -> %s", active.name, rotated.name)
        except OSError as exc:
            logger.warning("Log rotation failed for %s: %s", active.name, exc)

    return active


# ---------------------------------------------------------------------------
# Privacy helpers
# ---------------------------------------------------------------------------

# Match email addresses for scrubbing
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Match RU phone numbers and long digit strings
_PHONE_RE = re.compile(
    r"(?:(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}|\b\d{10,15}\b)"
)
# Extract CS-error codes from compiler messages
_CS_CODE_RE = re.compile(r"\b(CS\d{4})\b")


def _scrub_pii(text: str) -> str:
    """Remove emails and phone numbers from a user query string."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8", errors="replace")).hexdigest()


def _extract_cs_codes(messages: list) -> list:
    """Return only the CS-code tokens from compiler error messages."""
    codes: list = []
    for msg in messages:
        codes.extend(_CS_CODE_RE.findall(msg))
    return list(dict.fromkeys(codes))


# ---------------------------------------------------------------------------
# Background writer (fire-and-forget, non-blocking)
# ---------------------------------------------------------------------------


class _TelemetryWriter:
    """Background thread draining a queue and appending JSONL rows.

    Uses a plain thread (not asyncio) to keep disk I/O off the event loop.
    Queue cap prevents OOM; full queue silently drops rows (best-effort).
    """

    _QUEUE_MAX = 10_000
    _FLUSH_INTERVAL_S = 2.0

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=self._QUEUE_MAX)
        self._thread = threading.Thread(
            target=self._run,
            name="telemetry-rag-writer",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, log_name: str, row: dict) -> None:
        """Put a row onto the write queue. Non-blocking -- drops if full."""
        try:
            self._q.put_nowait((log_name, row))
        except queue.Full:
            logger.debug("Telemetry queue full -- dropping row for %s", log_name)

    def _run(self) -> None:
        while True:
            try:
                log_name, row = self._q.get(timeout=self._FLUSH_INTERVAL_S)
                self._write(log_name, row)
                self._q.task_done()
            except queue.Empty:
                pass
            except Exception:
                logger.debug("Telemetry writer error", exc_info=True)

    @staticmethod
    def _write(log_name: str, row: dict) -> None:
        path = _log_path(log_name)
        line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass  # non-fatal on Windows
        except OSError as exc:
            logger.warning("Telemetry write failed (%s): %s", log_name, exc)


# Module-level singleton -- created once on first import.
_writer = _TelemetryWriter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# Public logging functions
# ---------------------------------------------------------------------------


def log_rag_retrieval(
    query_id: str,
    user_query: str,
    intent: str,
    domain: str,
    retrieved_recipe_ids: list,
    retrieved_class_names: list,
    inject_chars: int,
    rag_legs_used: list,
    revit_version: Optional[str] = None,
    health: Optional[dict] = None,
) -> None:
    """Append a RAG retrieval telemetry row to rag_retrieval.jsonl.

    Called after RAG enrichment, before the LLM call.
    query_id links this row to the corresponding compile/execution rows.

    ``health`` (plan 009) is an optional per-turn ``RetrievalHealth.to_dict()``
    snapshot — which legs ran, which degraded — attached additively so the
    JSONL row records the full retrieval health record alongside the summary.
    """
    try:
        row = {
            "ts": _now_iso(),
            "query_id": query_id,
            "user_query": _scrub_pii(user_query)[:500],
            "intent": intent,
            "domain": domain,
            "recipe_ids": retrieved_recipe_ids,
            "class_names": retrieved_class_names,
            "inject_chars": inject_chars,
            "rag_legs": rag_legs_used,
            "revit_version": revit_version,
        }
        if health:
            row["health"] = health
        _writer.enqueue("rag_retrieval", row)
    except Exception as e:
        logger.debug("log_rag_retrieval failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


def log_compile_outcome(
    query_id: str,
    extracted_code_md5: Optional[str],
    code_length_chars: int,
    compile_ok: bool,
    compile_errors: list,
    revit_version: str,
    repair_attempt: int = 0,
) -> None:
    """Append a Roslyn compile outcome row to rag_compile.jsonl.

    compile_errors should contain CS-code strings only, not full messages
    (full messages may include code snippets with PII). _extract_cs_codes
    is applied as an additional safety net.
    """
    try:
        row = {
            "ts": _now_iso(),
            "query_id": query_id,
            "code_md5": extracted_code_md5,
            "code_length": code_length_chars,
            "compile_ok": compile_ok,
            "cs_errors": _extract_cs_codes(compile_errors) if compile_errors else [],
            "revit_version": revit_version,
            "repair_attempt": repair_attempt,
        }
        _writer.enqueue("rag_compile", row)
    except Exception as e:
        logger.debug("log_compile_outcome failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


def log_execution_outcome(
    query_id: str,
    exec_ok: bool,
    exec_exception_type: Optional[str],
    exec_time_ms: int,
    revit_version: str,
    document_name_md5: Optional[str] = None,
) -> None:
    """Append a Bridge execution outcome row to rag_execute.jsonl.

    exec_exception_type: class name only (e.g. InvalidOperationException).
    document_name_md5: md5 of the document name, never cleartext.
    """
    try:
        row = {
            "ts": _now_iso(),
            "query_id": query_id,
            "exec_ok": exec_ok,
            "exception_type": exec_exception_type,
            "exec_time_ms": exec_time_ms,
            "revit_version": revit_version,
            "doc_name_md5": document_name_md5,
        }
        _writer.enqueue("rag_execute", row)
    except Exception as e:
        logger.debug("log_execution_outcome failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


def _scrub_eval_value(value):
    """Recursively scrub PII + truncate any string inside an Evaluator row's
    nested check/violation structures. Parameter VALUES can carry user text, so
    every leaf string is run through ``_scrub_pii`` and capped at 120 chars."""
    if isinstance(value, str):
        return _scrub_pii(value)[:120]
    if isinstance(value, dict):
        return {k: _scrub_eval_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_eval_value(v) for v in value]
    return value


def log_eval_verdict(query_id: Optional[str], row: dict) -> None:
    """Append an Evaluator verdict row to eval_verdicts.jsonl (plan 020).

    The verdict is the Evaluator's deterministic judgement of ONE write's
    change-set; it is recorded in SHADOW (the model never sees it). ``row`` is
    built by ``kukai.will.shadow``; here we stamp ``ts``/``query_id`` and scrub
    PII from every string inside ``checks`` and ``violations`` (parameter
    values can carry user text). Never raises — telemetry failure is counted.
    """
    try:
        out = dict(row)
        out["ts"] = _now_iso()
        out["query_id"] = query_id
        if "checks" in out:
            out["checks"] = _scrub_eval_value(out["checks"])
        if "violations" in out:
            out["violations"] = _scrub_eval_value(out["violations"])
        _writer.enqueue("eval_verdicts", out)
    except Exception as e:
        logger.debug("log_eval_verdict failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


def log_capability_shadow(query_id: Optional[str], row: dict) -> None:
    """Append a capability-resolve SHADOW row to capability_shadow.jsonl.

    Stage 2.1-shadow (``KUKAI_RAG_CAPABILITY_SHADOW``, SHADOW_REPORT.md): one
    row per turn where ``KUKAI_RAG_CAPABILITY_RESOLVE`` is OFF but the shadow
    flag is ON and a turn ``action`` was known — records what
    ``apply_capability_resolve_positional`` WOULD have produced (would-be
    top-5, matched count, capability-gap), computed on a COPY of the ranked
    list. It is OBSERVE-ONLY: the real, live ranked order used to build the
    turn's answer is never touched (see
    ``kukai.rag.retrieval._emit_capability_shadow``). ``row`` is built there;
    here we only stamp ``ts``/``query_id`` (joins to rag_retrieval.jsonl on
    ``query_id``), same shape as ``log_truth_gate``. Never raises — telemetry
    failure is counted, never blocks the turn.
    """
    try:
        out = dict(row)
        out["ts"] = _now_iso()
        out["query_id"] = query_id
        _writer.enqueue("capability_shadow", out)
    except Exception as e:
        logger.debug("log_capability_shadow failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


def log_truth_gate(query_id: Optional[str], row: dict) -> None:
    """Append a fake-готово detection row to truth_gate.jsonl (Step 8).

    One row per Tier-0 detection (``kukai.will.truth_gate``): the model made a
    completion/observation claim on an ACTION-intent turn with ZERO successful
    world-tool calls. ``row`` carries intent / tool counts / matched cue /
    mode(shadow|enforce) / action / session_id; here we stamp ``ts`` and
    ``query_id`` (joins to rag_retrieval / eval_verdicts). The preview string
    is PII-scrubbed by the caller. Never raises — telemetry failure is counted.
    """
    try:
        out = dict(row)
        out["ts"] = _now_iso()
        out["query_id"] = query_id
        _writer.enqueue("truth_gate", out)
    except Exception as e:
        logger.debug("log_truth_gate failed (non-fatal)", exc_info=True)
        note_telemetry_failure(e)


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def _read_jsonl(log_name: str) -> list:
    """Read all rows from active and rotated log files."""
    base = _telemetry_dir()
    rows: list = []
    files = sorted(base.glob(f"{log_name}*.jsonl"))
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
    return rows


def correlate(query_id: str) -> dict:
    """Pull rows from all four logs for a single query_id.

    Returns dict with keys 'retrieval', 'compile', 'execute', 'eval' -- each a
    list of matching rows. compile may have multiple rows when the repair loop
    ran; 'eval' may have multiple rows when a turn issued several writes
    (plan 020 — the Evaluator's per-write verdicts).
    """
    result: dict = {
        "query_id": query_id,
        "retrieval": [],
        "compile": [],
        "execute": [],
        "eval": [],
    }
    for log_name, key in [
        ("rag_retrieval", "retrieval"),
        ("rag_compile", "compile"),
        ("rag_execute", "execute"),
        ("eval_verdicts", "eval"),
    ]:
        for row in _read_jsonl(log_name):
            if row.get("query_id") == query_id:
                result[key].append(row)
    return result


def gap_analysis(window_days: int = 7) -> dict:
    """Aggregate telemetry from the last N days for the self-improvement loop.

    Returns top compile failures, top exec failures, broken recipes.
    """
    cutoff_ts = datetime.now(timezone.utc).timestamp() - window_days * 86400

    def _within_window(row: dict) -> bool:
        try:
            ts = datetime.fromisoformat(row["ts"]).timestamp()
            return ts >= cutoff_ts
        except (KeyError, ValueError):
            return True

    retrieval_rows = [r for r in _read_jsonl("rag_retrieval") if _within_window(r)]
    compile_rows = [r for r in _read_jsonl("rag_compile") if _within_window(r)]
    execute_rows = [r for r in _read_jsonl("rag_execute") if _within_window(r)]

    retrieval_by_qid: dict = {
        r["query_id"]: r for r in retrieval_rows if "query_id" in r
    }
    compile_by_qid: dict = {}
    for r in compile_rows:
        compile_by_qid.setdefault(r.get("query_id", ""), []).append(r)
    execute_by_qid: dict = {
        r["query_id"]: r for r in execute_rows if "query_id" in r
    }

    failed_compile_qids = {
        qid
        for qid, rows in compile_by_qid.items()
        if any(not r.get("compile_ok", True) for r in rows)
    }
    compiled_ok_qids = {
        qid
        for qid, rows in compile_by_qid.items()
        if all(r.get("compile_ok", True) for r in rows)
    }
    exec_failed_qids = {
        qid for qid, r in execute_by_qid.items() if not r.get("exec_ok", True)
    }
    compile_ok_exec_fail_qids = compiled_ok_qids & exec_failed_qids

    compile_failures = []
    for qid in list(failed_compile_qids)[:20]:
        ret = retrieval_by_qid.get(qid, {})
        all_errors: list = []
        for cr in compile_by_qid.get(qid, []):
            all_errors.extend(cr.get("cs_errors", []))
        compile_failures.append({
            "query_id": qid,
            "user_query": ret.get("user_query", ""),
            "retrieved_recipes": ret.get("recipe_ids", []),
            "retrieved_classes": ret.get("class_names", []),
            "cs_errors": list(dict.fromkeys(all_errors)),
        })

    exec_failures = []
    for qid in list(compile_ok_exec_fail_qids)[:20]:
        ret = retrieval_by_qid.get(qid, {})
        exc_row = execute_by_qid.get(qid, {})
        exec_failures.append({
            "query_id": qid,
            "user_query": ret.get("user_query", ""),
            "retrieved_recipes": ret.get("recipe_ids", []),
            "exception_type": exc_row.get("exception_type"),
            "exec_time_ms": exc_row.get("exec_time_ms"),
        })

    all_retrieved: set = set()
    for r in retrieval_rows:
        all_retrieved.update(r.get("recipe_ids", []))

    fail_retrieved: dict = {}
    for qid in failed_compile_qids:
        ret = retrieval_by_qid.get(qid, {})
        for rid in ret.get("recipe_ids", []):
            fail_retrieved[rid] = fail_retrieved.get(rid, 0) + 1

    ok_retrieved: set = set()
    for qid, ret in retrieval_by_qid.items():
        if qid not in failed_compile_qids:
            ok_retrieved.update(ret.get("recipe_ids", []))

    broken_recipes = [
        {"recipe_id": rid, "fail_count": cnt}
        for rid, cnt in sorted(fail_retrieved.items(), key=lambda x: -x[1])
        if rid not in ok_retrieved
    ]

    return {
        "window_days": window_days,
        "total_queries": len(retrieval_rows),
        "compile_failure_count": len(failed_compile_qids),
        "exec_failure_count": len(compile_ok_exec_fail_qids),
        "top_compile_failures": compile_failures,
        "top_exec_failures": exec_failures,
        "all_retrieved_recipe_ids": sorted(all_retrieved),
        "broken_recipes": broken_recipes[:20],
    }
