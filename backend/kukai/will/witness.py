"""The op→evaluator witness channel (2026-07-10) — evidence flows, verdicts
don't get re-derived.

Ops that run a REAL grounded witness (post-commit read-back + independent probe,
e.g. ``create_element``) used to compute the truth and throw the evidence away:
the shadow hook then blindly re-derived checks per-op, had no branch for the op,
and recorded ``unverifiable`` forever — eval_verdicts.jsonl masked real passes
and real fails equally (the "no truth layer" disease, root #1).

This module is the uniform channel between the two layers:

  * the OP side embeds its ``Check`` evidence into ``result["witness"]["checks"]``
    (:func:`attach_checks`) — the same frozen dataclass the evaluator folds;
  * the SHADOW side lifts it back (:func:`lift_op_checks`) and folds it through
    the ONE verdict engine (``evaluate_structural``) together with its own
    probes. No per-op ``if/elif`` in the evaluator, no second fold algorithm.

TRUST BOUNDARY (the load-bearing part): ``execute_revit_code`` results are the
raw output of arbitrary C# — a model could forge ``{"witness": {...}}`` there
and manufacture truth. Lifting is therefore allowlisted to :data:`WITNESS_OPS`:
(tool, op) pairs whose SERVER-side lowering (a) renders server-authored template
code from validated args only, and (b) unconditionally OVERWRITES
``result["witness"]`` after the bridge returns (create_element.py:1156), so no
bridge/template output can survive into the witness block. An op earns its
entry here by meeting both conditions — one line per op, the evaluator stays
generic.

Kill switch: ``KUKAI_WITNESS_CONSUME=0`` disables lifting (shadow falls back to
blind re-derivation, the pre-2026-07-10 behavior). Default ON — this is
shadow-only telemetry: it never gates a turn and the model never sees it.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from kukai.will.evaluator import Check

# (tool_name, operation) pairs whose server lowering attaches a trusted witness.
# See the module docstring for the two conditions an op must meet to be listed.
WITNESS_OPS: frozenset = frozenset({
    ("apply_revit_write", "create_element"),
})

# A create carries ≤ ~8 checks (count/category/level/geometry/params + probe);
# the cap is a defense against a malformed producer bloating telemetry rows.
_MAX_CHECKS = 16

_FIELDS = ("kind", "expect", "observed", "ok", "source", "detail", "partial")


def _consume_enabled() -> bool:
    """Kill switch, read at call time (ops can flip via service env)."""
    return os.environ.get("KUKAI_WITNESS_CONSUME", "1") != "0"


def check_to_dict(c: Check) -> dict:
    """Canonical serialization of one Check. Total — never raises."""
    return {
        "kind": c.kind, "expect": c.expect, "observed": c.observed,
        "ok": c.ok, "source": c.source, "detail": c.detail,
        "partial": bool(c.partial),
    }


def check_from_dict(d: Any) -> Optional[Check]:
    """Inverse of :func:`check_to_dict`. Total: malformed input → ``None``,
    never an exception (absence-tolerance, same contract as the evaluator)."""
    if not isinstance(d, dict):
        return None
    kind = d.get("kind")
    source = d.get("source")
    if not isinstance(kind, str) or not kind or not isinstance(source, str) or not source:
        return None
    ok = d.get("ok")
    if ok is not None and not isinstance(ok, bool):
        return None
    try:
        return Check(
            kind=kind, expect=d.get("expect"), observed=d.get("observed"),
            ok=ok, source=source,
            detail=d.get("detail") if isinstance(d.get("detail"), str) else None,
            partial=bool(d.get("partial", False)),
        )
    except Exception:  # noqa: BLE001 — a witness channel must never break a turn
        return None


def attach_checks(witness: dict, checks: list) -> None:
    """OP side: embed the evidence on the witness block (in place)."""
    try:
        witness["checks"] = [check_to_dict(c) for c in checks[:_MAX_CHECKS]]
    except Exception:  # noqa: BLE001
        pass


def lift_op_checks(tool_name: str, op: Optional[str], result: Any) -> list:
    """SHADOW side: recover the op's evidence — ``[]`` unless the (tool, op)
    pair is registered in :data:`WITNESS_OPS`, the kill switch is on, and the
    embedded items validate. Malformed items are skipped, never raised on."""
    if not _consume_enabled():
        return []
    if (tool_name, op) not in WITNESS_OPS:
        return []
    if not isinstance(result, dict):
        return []
    wit = result.get("witness")
    if not isinstance(wit, dict):
        return []
    raw = wit.get("checks")
    if not isinstance(raw, list):
        return []
    lifted = []
    for item in raw[:_MAX_CHECKS]:
        c = check_from_dict(item)
        if c is not None:
            lifted.append(c)
    return lifted


def op_witness_id(result: Any) -> Optional[str]:
    """The op-side witness join id (``op_id``), when present and sane."""
    if isinstance(result, dict):
        wit = result.get("witness")
        if isinstance(wit, dict):
            oid = wit.get("op_id")
            if isinstance(oid, str) and oid:
                return oid
    return None
