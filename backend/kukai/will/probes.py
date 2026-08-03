"""The Evaluator's read-only probe layer (Tier B) — the ONLY module in the Will
organ that touches ``bridge_callback``.

Probes are *deterministic read-only world witnesses*: they run a small,
safety-validated read-only C# body via the in-scope ``bridge_callback`` and
shape the raw result into a :class:`~kukai.will.evaluator.Check`. They NEVER
call an LLM (IRON 3) and NEVER mutate the model. Every probe:

  * validates its body with ``validate_code_safety`` before sending — a
    violation aborts the probe (``ok=None``), never raises;
  * carries **no ``"attempt"`` key** in its bridge params — that is plan 014's
    telemetry discriminator (``"attempt" in params`` ⇒ LLM-initiated), so
    Evaluator probes are correctly EXCLUDED from ``rag_execute.jsonl``;
  * is time-capped (``asyncio.wait_for``, 8s) and totally swallows
    failure/timeout into ``ok=None`` so the verdict degrades to ``unverifiable``
    rather than throwing.

v1 has two probe kinds: ``inspect_absent`` (after a delete — does the id still
resolve?) and ``warnings_count`` (a within-turn ``doc.GetWarnings().Count``
delta). Imports from ``kukai.llm.verbs`` / ``kukai.security.validation`` are
done lazily inside the functions so :mod:`kukai.will.evaluator` stays
import-light and the package's only ``llm.*`` dependency is the read-only verb
builders here.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Optional

from kukai.will.evaluator import Check, _as_int

logger = logging.getLogger(__name__)

# A 3-line read-only body mirroring model_vitals.VITALS_CS — the
# anti-fabrication anchor. Returns {"warnings_count": int|null}.
WARNINGS_COUNT_CS = (
    'var __r = new Dictionary<string,object>(); '
    'try { var __w = doc.GetWarnings(); __r["warnings_count"] = (__w != null) ? __w.Count : 0; } '
    'catch { __r["warnings_count"] = null; } '
    'return __r;'
)

_PROBE_TIMEOUT_S = 8.0

# BuiltInCategory member names are ASCII identifiers starting with "OST_".
# Anything else is rejected BEFORE building C# — this is both the lenient
# unknown-category gate (⇒ unverifiable, never an error to the model) and the
# injection guard for the interpolated string literal below.
_CATEGORY_NAME_RE = re.compile(r"^OST_[A-Za-z0-9_]{1,120}$")

# Version-safe read-only category count (expects-contract witness, IQ N2).
# Mirrors the WARNINGS_COUNT_CS conventions: Dictionary result, try/catch,
# no Transaction / .Value / .IntegerValue; Enum.TryParse<T> + FEC
# .WhereElementIsNotElementType().GetElementCount() exist on net48 AND net8
# (Revit 2021-2026). An unknown category parses false → {"count": null},
# never a thrown error. Returns {"count": int|null, "reason"?: str}.
_CATEGORY_COUNT_CS_TEMPLATE = (
    'var __r = new Dictionary<string,object>(); '
    'try { BuiltInCategory __bic = BuiltInCategory.INVALID; '
    'if (Enum.TryParse<BuiltInCategory>("{category}", out __bic)) { '
    '__r["count"] = new FilteredElementCollector(doc).OfCategory(__bic)'
    '.WhereElementIsNotElementType().GetElementCount(); '
    '} else { __r["count"] = null; __r["reason"] = "unknown_category"; } } '
    'catch { __r["count"] = null; __r["reason"] = "exception"; } '
    'return __r;'
)


def category_count_cs(category: Any) -> Optional[str]:
    """The read-only FEC count body for one BuiltInCategory name, or ``None``
    when the name is not a plausible ``OST_*`` identifier (lenient reject —
    the caller degrades to ``unverifiable``, never an error)."""
    if not isinstance(category, str) or not _CATEGORY_NAME_RE.match(category):
        return None
    return _CATEGORY_COUNT_CS_TEMPLATE.replace("{category}", category)


async def run_probe(
    kind: str,
    code: str,
    bridge_callback,
    *,
    timeout_s: float = _PROBE_TIMEOUT_S,
    transform: Optional[Callable[[str], str]] = None,
    params_extra: Optional[dict] = None,
) -> Optional[dict]:
    """Validate → execute a read-only C# body via ``bridge_callback`` → return
    the raw dict (or None on ANY failure/timeout/violation).

    ``transform`` (optional) is applied to the ALREADY-VALIDATED body right
    before sending (e.g. the exec pipeline's ``wrap_user_code``);
    ``params_extra`` (optional) is merged into the request params (e.g.
    ``{"_pipeline_prepared": True}`` to take chat_ws's transport-only branch).
    Both default to None — the legacy call shape is byte-identical.

    NOTE: the params dict deliberately carries **no ``"attempt"`` key** — plan
    014's telemetry discriminator must exclude Evaluator probes. Never raises.
    """
    if bridge_callback is None:
        return None
    try:
        from kukai.security.validation import validate_code_safety
        if validate_code_safety(code):  # non-None ⇒ a violation list
            logger.debug("Evaluator probe %s aborted: failed validate_code_safety", kind)
            return None
        if transform is not None:
            code = transform(code)
        # No "attempt" key — see the module/function docstring.
        params = {"code": code, "timeout_ms": int(timeout_s * 1000)}
        if params_extra:
            params.update(params_extra)
        from kukai.operations.effects import ReadOnlySource, mark_read_only
        params = mark_read_only(params, ReadOnlySource.EVALUATOR_PROBE)
        raw = await asyncio.wait_for(
            bridge_callback("execute", params), timeout=timeout_s
        )
        return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001 — probes never raise into the hot path
        logger.debug("Evaluator probe %s failed (non-fatal)", kind, exc_info=True)
        return None


async def probe_category_count(
    category: Any,
    bridge_callback,
    *,
    timeout_s: float = _PROBE_TIMEOUT_S,
    transform: Optional[Callable[[str], str]] = None,
    params_extra: Optional[dict] = None,
) -> tuple[Optional[int], Optional[str]]:
    """Read-only count of a category's non-type members → ``(count, reason)``.

    ``count`` is a non-negative int, or ``None`` with ``reason`` one of
    ``invalid_category`` (name failed the OST_* gate — probe never sent),
    ``unknown_category`` (Revit's enum doesn't know it), ``exception`` (the
    probe body caught), or ``probe_unavailable`` (transport/timeout/shape).
    Tolerates both the flat probe result shape (``{"count": …}``) and an
    envelope-wrapped ``{"result": {"count": …}}``. Never raises.
    """
    code = category_count_cs(category)
    if code is None:
        return None, "invalid_category"
    try:
        raw = await run_probe(
            "expects_category_count", code, bridge_callback,
            timeout_s=timeout_s, transform=transform, params_extra=params_extra,
        )
        if not isinstance(raw, dict):
            return None, "probe_unavailable"
        src = raw
        if "count" not in src and isinstance(raw.get("result"), dict):
            src = raw["result"]
        count = _as_int(src.get("count"))
        if count is None or count < 0:
            reason = src.get("reason")
            return None, (reason if isinstance(reason, str) and reason
                          else "probe_unavailable")
        return count, None
    except Exception:  # noqa: BLE001 — probes never raise into the hot path
        logger.debug("probe_category_count failed (non-fatal)", exc_info=True)
        return None, "probe_unavailable"


async def probe_inspect_absent(element_id: Any, bridge_callback) -> Check:
    """After a successful delete: does the deleted id still resolve?

    Expected world-witness of the deletion: ``{"error": "not_found"}`` →
    ``ok=True``. A real element dict back → ``ok=False`` (it was NOT deleted).
    Any failure/timeout → ``ok=None`` (undecidable, never a false fail).
    """
    try:
        from kukai.llm.verbs import build_inspect_code, perceive_inspect
        code = build_inspect_code(element_id)
        raw = await run_probe("inspect_absent", code, bridge_callback)
        if raw is None:
            return Check(
                kind="probe.inspect_absent", expect="not_found",
                observed=None, ok=None, source="probe",
                detail="probe_unavailable")
        shaped = perceive_inspect(raw)
        if shaped.get("error") == "not_found":
            return Check(
                kind="probe.inspect_absent", expect="not_found",
                observed="not_found", ok=True, source="probe")
        # bad_id / no_result → we cannot decide deletion either way.
        if shaped.get("error"):
            return Check(
                kind="probe.inspect_absent", expect="not_found",
                observed=shaped.get("error"), ok=None, source="probe",
                detail="probe_inconclusive")
        # A real element came back — the id still resolves; it was NOT deleted.
        return Check(
            kind="probe.inspect_absent", expect="not_found",
            observed=shaped.get("id"), ok=False, source="probe")
    except Exception:  # noqa: BLE001
        logger.debug("probe_inspect_absent failed (non-fatal)", exc_info=True)
        return Check(
            kind="probe.inspect_absent", expect="not_found",
            observed=None, ok=None, source="probe", detail="probe_exception")


async def probe_warnings_count(bridge_callback) -> tuple[Check, Optional[int]]:
    """Snapshot ``doc.GetWarnings().Count`` (read-only).

    Returns ``(check, count)``. The FIRST snapshot of a turn is a baseline
    (``ok=None``); the shadow orchestrator computes the within-turn DELTA on
    subsequent snapshots (``probe.warnings_delta``). Cross-turn deltas are
    NOT computed (external edits poison them). Failure → ``ok=None``,
    ``count=None``.
    """
    try:
        raw = await run_probe("warnings_count", WARNINGS_COUNT_CS, bridge_callback)
        if raw is None:
            return (
                Check(kind="probe.warnings_count", expect="baseline",
                      observed=None, ok=None, source="probe",
                      detail="probe_unavailable"),
                None,
            )
        count = raw.get("warnings_count")
        count = count if isinstance(count, int) and not isinstance(count, bool) else None
        if count is None:
            return (
                Check(kind="probe.warnings_count", expect="baseline",
                      observed=None, ok=None, source="probe",
                      detail="warnings_unavailable"),
                None,
            )
        # Baseline snapshot; the delta check is built by the orchestrator.
        return (
            Check(kind="probe.warnings_count", expect="baseline",
                  observed=count, ok=None, source="probe"),
            count,
        )
    except Exception:  # noqa: BLE001
        logger.debug("probe_warnings_count failed (non-fatal)", exc_info=True)
        return (
            Check(kind="probe.warnings_count", expect="baseline",
                  observed=None, ok=None, source="probe", detail="probe_exception"),
            None,
        )


def warnings_delta_check(baseline: Optional[int], current: Optional[int]) -> Check:
    """Build the within-turn ``probe.warnings_delta`` check (pure).

    ``delta = current - baseline``; ``delta > 0`` (the write ADDED model
    warnings) → ``ok=False`` (the world-grounded "did I damage the model"
    signal). Undecidable when either snapshot is missing.
    """
    if baseline is None or current is None:
        return Check(
            kind="probe.warnings_delta", expect={"op": "<=", "value": 0},
            observed=None, ok=None, source="probe", detail="no_baseline")
    delta = current - baseline
    return Check(
        kind="probe.warnings_delta", expect={"op": "<=", "value": 0},
        observed=delta, ok=(delta <= 0), source="probe")
