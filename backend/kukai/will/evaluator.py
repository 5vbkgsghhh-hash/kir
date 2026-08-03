"""The Evaluator — IRON 3, the deterministic value function (pure core).

This module is the heart of the Will organ: given a write's ``(tool_name,
args, result)`` it returns an :class:`EvalReport` — a verdict
(``pass | partial | fail | unverifiable``) plus the individual :class:`Check`
rows that produced it. It is the apex metric KUKAI is graded by: it upgrades
"the bridge didn't throw" into "did the right thing".

**THE ONE IRON RULE (VISION.md §2 I3, "The Evaluator … It never calls an
LLM"):** every check in this module is a *pure computation* over the args and
the result dict, or (in :mod:`kukai.will.probes`) a *deterministic read-only
probe*. This file imports ONLY the standard library — no ``llm/``, no
``api/``, no ``agents/`` — so the core stays offline-pure, import-cheap, and
obviously LLM-free. (``kukai.agents.error_interpreter`` looks relevant but is
LLM-backed; it is constitutionally excluded — its home is the W4 repair lane.)

Absence is tolerated, never punished: when an expected witness field is
missing (older bridge, family-tool shape, camelCase drift, a raw-C# write that
has no derivable postcondition) the check records ``ok=None`` — *undecidable*,
NOT *failed*. The honest v1 answer for such writes is ``unverifiable``; v2's
effects witness upgrades them. ``unverifiable`` is never silently inflated to
``pass``.

The two public functions — :func:`derive_checks` and
:func:`evaluate_structural` — implement Tier-A (claim-vs-args, zero bridge
cost) end-to-end as pure functions; they are also the functions an offline
grader (plan 014/016) can import to score recorded runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# v2 (2026-06-13): coherence guard — logically impossible counts (a witnessed
# count exceeding its ceiling, or a negative count) are now a hard FAIL, never
# downgraded to 'partial'. Bumped so the offline report never mixes v1/v2 rows.
# 2026-07-05 (IQ moment N2, additive — no bump): expects-contract rows
# (claim.expects_declared / probe.expects_count_delta / expects_count_mismatch)
# only appear when the model declared an `expects` postcondition (schema gated
# by KUKAI_EXPECTS_CONTRACT); pre-existing row semantics are untouched.
EVALUATOR_VERSION = 2

# Verdict literals (kept as plain strings to stay stdlib-only and JSON-native).
PASS = "pass"
PARTIAL = "partial"
FAIL = "fail"
UNVERIFIABLE = "unverifiable"

# Sources that constitute a *world witness* — only these can decide pass/fail.
# A result_claim (an echo of the input) and a structure/envelope observation are
# self-reported, NOT proof the model changed; they refine but never ground.
_WORLD_GROUNDED = frozenset({"read_back", "probe"})


@dataclass(frozen=True)
class Check:
    """One deterministic observation about a write's outcome.

    ``ok is None`` means *undecidable* (a witness was absent or unparseable) —
    the absence-tolerance contract: a missing field NEVER reads as ``False``.
    """

    kind: str            # e.g. "claim.verified_count", "probe.inspect_absent"
    expect: Any          # the derived postcondition (from args / prior state)
    observed: Any        # what the result/probe actually said (None if absent)
    ok: Optional[bool]   # None = undecidable (never guessed)
    source: str          # "read_back" | "result_claim" | "probe" | "envelope" | "structure"
    detail: Optional[str] = None
    # Tri-state nuance for a count witness: when ``ok is False`` but the world
    # DID move partway toward the target (e.g. 2 of 5 set / 3 of 5 deleted),
    # ``partial=True`` downgrades the verdict fail→partial. ``ok=False`` with
    # ``partial=False`` is zero/wrong progress (a true fail). Ignored when
    # ``ok`` is True or None.
    partial: bool = False


@dataclass
class EvalReport:
    verdict: str                       # "pass" | "partial" | "fail" | "unverifiable"
    score: float                       # decided-checks pass fraction; 0.0 when fail-on-error
    checks: list[Check] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    blast_radius: dict = field(default_factory=dict)  # {"elements_targeted": N} where derivable
    cost: dict = field(default_factory=dict)          # {"probes_run": n, "probe_ms": int}
    evaluator_version: int = EVALUATOR_VERSION


# ---------------------------------------------------------------------------
# Small, total helpers — never raise on malformed input.
# ---------------------------------------------------------------------------

def _as_int(value: Any) -> Optional[int]:
    """Return value as an int, or None when it is missing/non-numeric.

    bool is rejected (a bool is not a count witness). The absence-tolerance
    workhorse: a field that cannot be read as a number yields ``None`` →
    ``ok=None`` downstream, never a False.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(s)
        except (TypeError, ValueError):
            return None
    return None


def _n_targets(args: dict) -> Optional[int]:
    """Count of elements the op targeted, from args ``element_ids`` — the
    postcondition basis. None when not derivable (the op carries no id list)."""
    if not isinstance(args, dict):
        return None
    ids = args.get("element_ids")
    if isinstance(ids, (list, tuple, set)):
        return len(ids)
    return None


def _op_of(tool_name: str, args: dict) -> Optional[str]:
    """The apply_revit_write operation discriminator, else None."""
    if tool_name == "apply_revit_write" and isinstance(args, dict):
        op = args.get("operation")
        return op if isinstance(op, str) else None
    return None


def _is_empty_result(result: Any) -> bool:
    """True when a write 'succeeded' but returned nothing meaningful."""
    if result is None:
        return True
    if isinstance(result, str):
        return result.strip() == ""
    if isinstance(result, (dict, list, tuple, set)):
        return len(result) == 0
    return False


def _err_code(result: Any) -> Optional[str]:
    """Extract the envelope err.code (plan 004) if present, else None."""
    if isinstance(result, dict):
        err = result.get("err")
        if isinstance(err, dict):
            code = err.get("code")
            if isinstance(code, str) and code:
                return code
    return None


def _impossible(
    observed: Optional[int],
    ceiling_n: Optional[int],
    ceiling_total: Optional[int] = None,
    *,
    also_nonneg: tuple = (),
) -> bool:
    """True when counts are logically impossible — a lying or corrupt result.

    A negative count, or a witnessed count that EXCEEDS its ceiling (the
    requested ``ceiling_n`` ids, or a declared ``ceiling_total``), cannot be
    'partial progress' — it is a hard FAIL. Examples the v1 fold wrongly rated
    partial/pass: ``verified=5`` of ``total=3``; ``deleted=5`` of 3 requested;
    ``copied=5`` of 2 requested; ``failed=-1``. Guarding these stops the apex
    disagreement-rate from under-counting failures as 'partial'. Pure; never
    raises (only operates on ints already coerced by :func:`_as_int`)."""
    for c in (observed, ceiling_total, *also_nonneg):
        if c is not None and c < 0:
            return True
    if observed is not None:
        if ceiling_total is not None and observed > ceiling_total:
            return True
        if ceiling_n is not None and observed > ceiling_n:
            return True
    if ceiling_total is not None and ceiling_n is not None and ceiling_total > ceiling_n:
        return True
    return False


# ---------------------------------------------------------------------------
# Expects contract (IQ moment N2) — the model-declared postcondition for raw
# C# writes. Pure helpers only: parsing the optional ``expects`` tool arg and
# building the world-grounded delta check from before/after category counts
# that the PIPELINE witnesses (kukai/llm/revit_execution_pipeline.py, gated by
# KUKAI_EXPECTS_CONTRACT). This module stays flag-blind and bridge-blind: it
# derives what it can from (args, counts) and never reads the environment.
# ---------------------------------------------------------------------------

# The declared-op vocabulary (mirrors the tool-schema enum in llm/tools.py).
EXPECTS_OPS = frozenset({"create", "modify", "delete"})


def parse_expects(args: Any) -> Optional[dict]:
    """Leniently normalize the optional ``expects`` postcondition contract.

    Returns ``{"op": str, "category": Optional[str], "count": Optional[int]}``
    when ``args["expects"]`` is a dict with a recognized op, else ``None``.
    Malformed category/count degrade to ``None`` fields (the declaration is
    still recorded; the witness simply cannot run) — a bad contract NEVER
    becomes an error to the model. Total; never raises.
    """
    if not isinstance(args, dict):
        return None
    exp = args.get("expects")
    if not isinstance(exp, dict):
        return None
    op = exp.get("op")
    if not isinstance(op, str):
        return None
    op = op.strip().lower()
    if op not in EXPECTS_OPS:
        return None
    category = exp.get("category")
    category = category.strip() if isinstance(category, str) and category.strip() else None
    count = _as_int(exp.get("count"))
    if count is not None and count < 0:
        count = None
    return {"op": op, "category": category, "count": count}


def expects_delta_check(
    expects: dict,
    before: Any,
    after: Any,
    *,
    reason: Optional[str] = None,
) -> Check:
    """Build the world-grounded ``probe.expects_count_delta`` check (pure).

    Semantics (op × outcome ⇒ ok/partial; the verdict mapping is
    :func:`expects_verdict_from_check`):

    * ``create``: ``delta = after - before``; ``delta >= count`` → ok (pass);
      ``0 < delta < count`` → partial; ``delta <= 0`` → fail.
    * ``delete``: ``delta = before - after``; same thresholds.
    * ``modify``: a count probe cannot witness in-place mutation — honestly
      ``ok=None`` (unverifiable-by-count in v1; never faked).
    * Missing/negative counts or probe failure → ``ok=None`` (undecidable,
      never a false fail — the absence-tolerance contract).
    """
    op = expects.get("op") if isinstance(expects, dict) else None
    c = _as_int(expects.get("count")) if isinstance(expects, dict) else None
    category = expects.get("category") if isinstance(expects, dict) else None
    expect_repr = {"op": op, "category": category, "count": c}
    kind = "probe.expects_count_delta"

    if op == "modify":
        return Check(kind=kind, expect=expect_repr, observed=None, ok=None,
                     source="probe", detail=reason or "modify_not_countable")

    b = _as_int(before)
    a = _as_int(after)
    if (op not in ("create", "delete") or c is None or c < 0
            or b is None or a is None or b < 0 or a < 0):
        observed = None
        if b is not None or a is not None:
            observed = {"before": b, "after": a}
        return Check(kind=kind, expect=expect_repr, observed=observed, ok=None,
                     source="probe", detail=reason or "probe_unavailable")

    delta = (a - b) if op == "create" else (b - a)
    observed = {"before": b, "after": a, "delta": delta}
    ok = delta >= c
    partial = (not ok) and delta > 0
    return Check(kind=kind, expect=expect_repr, observed=observed, ok=ok,
                 source="probe", partial=partial)


def expects_verdict_from_check(check: Check) -> str:
    """Map the expects delta check to its contract verdict (pure)."""
    if check.ok is None:
        return UNVERIFIABLE
    if check.ok:
        return PASS
    return PARTIAL if check.partial else FAIL


# ---------------------------------------------------------------------------
# Tier A — claim-vs-args checks (pure; zero bridge cost; runs at every level >=1)
# ---------------------------------------------------------------------------

def derive_checks(tool_name: str, args: dict, result: Any) -> list[Check]:
    """Pure Tier-A derivation: the per-op claim-vs-args checks plus the
    universal ``structure.nonempty`` / ``envelope.no_error`` rows.

    Never raises. Missing/non-numeric witnesses → ``ok=None`` (undecidable).
    """
    checks: list[Check] = []
    op = _op_of(tool_name, args)
    n = _n_targets(args)
    rd: dict = result if isinstance(result, dict) else {}

    # --- per-op witness checks (apply_revit_write declarative ops) ---
    if op == "set_parameter":
        verified = _as_int(rd.get("verified"))
        total = _as_int(rd.get("total"))
        failed = _as_int(rd.get("failed"))
        # Expect: verified == total == len(element_ids). The read-back count is
        # the witness built precisely against the "459 set / 0 in model" bug.
        if verified is None or total is None:
            checks.append(Check(
                kind="claim.verified_count", expect={"verified": n, "total": n},
                observed={"verified": verified, "total": total}, ok=None,
                source="read_back", detail="missing_readback_counts"))
        elif _impossible(verified, n, total, also_nonneg=(failed,)):
            # verified>total, count>requested, or a negative count is logically
            # impossible — the result is lying/corrupt: a hard FAIL, never partial.
            checks.append(Check(
                kind="claim.verified_count", expect={"verified": n, "total": n},
                observed={"verified": verified, "total": total, "failed": failed},
                ok=False, source="read_back", partial=False, detail="impossible_counts"))
        else:
            target = total
            ok = (verified == target) and (n is None or total == n)
            # partial progress: some verified, but short of target (not a zero/wrong write).
            partial = (not ok) and verified > 0
            checks.append(Check(
                kind="claim.verified_count",
                expect={"verified": target, "total": (n if n is not None else total)},
                observed={"verified": verified, "total": total, "failed": failed},
                ok=ok, source="read_back", partial=partial))

    elif op == "delete_elements":
        deleted = _as_int(rd.get("deleted"))
        # Expect: deleted == len(element_ids). deleted comes from the id set
        # doc.Delete() returned — a genuine world witness.
        if deleted is None or n is None:
            checks.append(Check(
                kind="claim.deleted_count", expect=n, observed=deleted, ok=None,
                source="read_back", detail="missing_readback_counts"))
        elif _impossible(deleted, n):
            # deleted>requested or negative is impossible — hard FAIL, not partial.
            checks.append(Check(
                kind="claim.deleted_count", expect=n, observed=deleted,
                ok=False, source="read_back", partial=False, detail="impossible_counts"))
        else:
            ok = (deleted == n)
            partial = (not ok) and deleted > 0  # some deleted, short of requested
            checks.append(Check(
                kind="claim.deleted_count", expect=n, observed=deleted,
                ok=ok, source="read_back", partial=partial))

    elif op == "copy_elements":
        copied = _as_int(rd.get("copied_count"))
        if copied is None or n is None:
            checks.append(Check(
                kind="claim.copied_count", expect=n, observed=copied, ok=None,
                source="read_back", detail="missing_readback_counts"))
        elif _impossible(copied, n):
            # copied>requested or negative is impossible — hard FAIL, not partial.
            checks.append(Check(
                kind="claim.copied_count", expect=n, observed=copied,
                ok=False, source="read_back", partial=False, detail="impossible_counts"))
        else:
            ok = (copied == n)
            partial = (not ok) and copied > 0
            checks.append(Check(
                kind="claim.copied_count", expect=n, observed=copied,
                ok=ok, source="read_back", partial=partial))

    elif op == "rename_entities":
        failed = _as_int(rd.get("failed"))
        total = _as_int(rd.get("total"))
        # Expect: failed == 0 (per-element API outcome counts).
        if failed is None:
            checks.append(Check(
                kind="claim.rename_failed", expect=0, observed=failed, ok=None,
                source="read_back", detail="missing_readback_counts"))
        elif _impossible(failed, None, total):
            # failed>total or a negative count is impossible — hard FAIL.
            checks.append(Check(
                kind="claim.rename_failed", expect=0,
                observed={"failed": failed, "total": total},
                ok=False, source="read_back", partial=False, detail="impossible_counts"))
        else:
            ok = (failed == 0)
            # partial: some renamed (total > failed), but not all.
            partial = (not ok) and (total is not None and (total - failed) > 0)
            checks.append(Check(
                kind="claim.rename_failed", expect=0,
                observed={"failed": failed, "total": total}, ok=ok,
                source="read_back", partial=partial))

    elif op == "create_schedule":
        sched_id = rd.get("schedule_id")
        present = sched_id is not None and sched_id != ""
        # The created element's id is the witness; if the field is absent we
        # cannot decide (older shape) → ok=None.
        if "schedule_id" not in rd:
            checks.append(Check(
                kind="claim.schedule_created", expect="non-null id",
                observed=None, ok=None, source="read_back",
                detail="missing_schedule_id"))
        else:
            checks.append(Check(
                kind="claim.schedule_created", expect="non-null id",
                observed=sched_id, ok=bool(present), source="read_back"))

    elif op == "move_elements":
        # Echo only — moved_count == ids.Count, NOT a read-back. result_claim
        # never grounds a verdict (the fold treats it as non-witness).
        moved = _as_int(rd.get("moved_count"))
        checks.append(Check(
            kind="claim.moved_count", expect=n, observed=moved,
            ok=(None if (moved is None or n is None) else (moved == n)),
            source="result_claim"))

    elif op == "hide_or_isolate":
        # Echo only — count == elementIds.Count.
        count = _as_int(rd.get("count"))
        checks.append(Check(
            kind="claim.affected_count", expect=n,
            observed={"count": count, "action": rd.get("action")},
            ok=(None if (count is None or n is None) else (count == n)),
            source="result_claim"))

    # --- expects contract (IQ moment N2, execute_revit_code only) ---
    # The model DECLARED a postcondition. Tier-A alone cannot witness it (the
    # before/after category counts come from the pipeline's read-only probes,
    # folded in via extra_checks as probe.expects_count_delta) — so this row
    # records the declaration itself: ok=None, source=result_claim (a claim,
    # not a witness; it refines but never grounds the verdict).
    if tool_name == "execute_revit_code":
        declared = parse_expects(args)
        if declared is not None:
            checks.append(Check(
                kind="claim.expects_declared", expect=dict(declared),
                observed=None, ok=None, source="result_claim",
                detail="declared_contract"))

    # --- universal checks (every write result, regardless of tool) ---
    # structure.nonempty: an empty "success" is suspicious but never proof of
    # failure — it adds a violation and leaves the verdict to the fold.
    empty = _is_empty_result(result)
    checks.append(Check(
        kind="structure.nonempty", expect="non-empty result",
        observed=("<empty>" if empty else "<present>"),
        ok=(False if empty else True), source="structure"))

    # envelope.no_error: redundant with fold rule 1 but recorded so every row
    # is self-describing.
    code = _err_code(result)
    checks.append(Check(
        kind="envelope.no_error", expect="no err.code",
        observed=code, ok=(code is None), source="envelope"))

    return checks


def evaluate_structural(
    tool_name: str,
    args: dict,
    result: Any,
    *,
    is_error: bool,
    extra_checks: Optional[list[Check]] = None,
    cost: Optional[dict] = None,
) -> EvalReport:
    """Pure Tier-A (+ optional already-run probe) evaluation → EvalReport.

    ``is_error`` is the harness's structure-first error flag (client.py:2045).
    ``extra_checks`` lets the shadow orchestrator fold in read-only probe
    results (Tier B) without this core ever touching a bridge. NEVER raises.
    """
    blast: dict = {}
    n = _n_targets(args)
    if n is not None:
        blast["elements_targeted"] = n
    cost = dict(cost) if isinstance(cost, dict) else {}

    # --- Fold rule 1: envelope error → fail, no probes. ---
    if is_error:
        code = _err_code(result)
        violation = code or "error"
        return EvalReport(
            verdict=FAIL,
            score=0.0,
            checks=[Check(
                kind="envelope.no_error", expect="no err.code",
                observed=code, ok=False, source="envelope")],
            violations=[violation],
            blast_radius=blast,
            cost=cost,
        )

    # --- Fold rule 2: running_unconfirmed (tool-budget shape) → unverifiable. ---
    if isinstance(result, dict) and result.get("state") == "running_unconfirmed":
        return EvalReport(
            verdict=UNVERIFIABLE,
            score=0.0,
            checks=[Check(
                kind="structure.confirmed_state", expect="confirmed",
                observed="running_unconfirmed", ok=None, source="structure")],
            violations=["unconfirmed_execution"],
            blast_radius=blast,
            cost=cost,
        )

    # --- Fold rule 3: gather checks, classify by world-grounding. ---
    checks: list[Check] = derive_checks(tool_name, args, result)
    if extra_checks:
        checks = checks + list(extra_checks)

    violations = _collect_violations(tool_name, args, result, checks)

    decided = [c for c in checks if c.ok is not None]
    grounded = [c for c in checks if c.source in _WORLD_GROUNDED and c.ok is not None]
    grounded_true = [c for c in grounded if c.ok is True]
    grounded_false = [c for c in grounded if c.ok is False]
    # A grounded-False check that nonetheless witnessed PARTIAL progress (some
    # of N done) downgrades a fail to partial — distinct from a zero/wrong write.
    grounded_partial = [c for c in grounded_false if c.partial]

    if grounded_false and not grounded_true:
        # all grounded witnesses failed: fail unless every failed one was
        # merely partial-progress (then the world DID move → partial).
        verdict = PARTIAL if (grounded_partial and len(grounded_partial) == len(grounded_false)) else FAIL
    elif grounded_true and grounded_false:
        verdict = PARTIAL
    elif grounded:  # all grounded decided are True (none False) and at least one exists
        # pass requires every DECIDED check True, not just the grounded ones.
        verdict = PASS if all(c.ok for c in decided) else PARTIAL
    else:
        # No world-grounded check decidable → honest unverifiable (the v1
        # answer for raw-C# / family writes — never inflated to pass).
        verdict = UNVERIFIABLE

    # --- Fold rule 4: score = passed decided / total decided. ---
    if decided:
        score = sum(1 for c in decided if c.ok) / len(decided)
    else:
        score = 0.0

    return EvalReport(
        verdict=verdict,
        score=score,
        checks=checks,
        violations=violations,
        blast_radius=blast,
        cost=cost,
    )


def _collect_violations(
    tool_name: str, args: dict, result: Any, checks: list[Check]
) -> list[str]:
    """Map decided-False / suspicious checks to stable violation tokens.

    Pure, order-stable, de-duplicated. Tokens are part of the row schema
    (bump ``EVALUATOR_VERSION`` on any semantic change).
    """
    violations: list[str] = []
    n = _n_targets(args)
    rd: dict = result if isinstance(result, dict) else {}
    op = _op_of(tool_name, args)

    if op == "set_parameter":
        verified = _as_int(rd.get("verified"))
        total = _as_int(rd.get("total"))
        failed = _as_int(rd.get("failed"))
        if _impossible(verified, n, total, also_nonneg=(failed,)):
            violations.append("impossible_counts")
        elif verified is not None:
            if verified == 0 and (total is None or total > 0) and (n is None or n > 0):
                violations.append("verified_zero")
            elif total is not None and verified < total:
                violations.append("verified_below_total")
            elif n is not None and total is not None and total < n:
                violations.append("verified_below_total")

    elif op == "delete_elements":
        deleted = _as_int(rd.get("deleted"))
        if _impossible(deleted, n):
            violations.append("impossible_counts")
        elif deleted is not None and n is not None and deleted < n:
            violations.append("deleted_below_requested")

    elif op == "copy_elements":
        copied = _as_int(rd.get("copied_count"))
        if _impossible(copied, n):
            violations.append("impossible_counts")
        elif copied is not None and n is not None and copied < n:
            violations.append("copied_below_requested")

    elif op == "rename_entities":
        failed = _as_int(rd.get("failed"))
        total = _as_int(rd.get("total"))
        if _impossible(failed, None, total):
            violations.append("impossible_counts")
        elif failed is not None and failed > 0:
            violations.append("rename_failed")

    elif op == "create_schedule":
        if "schedule_id" in rd:
            sid = rd.get("schedule_id")
            if sid is None or sid == "":
                violations.append("schedule_not_created")

    # Probe-sourced violations (extra_checks folded in by the orchestrator).
    for c in checks:
        if c.source == "probe" and c.ok is False:
            if c.kind == "probe.inspect_absent":
                violations.append("deleted_id_still_resolves")
            elif c.kind == "probe.warnings_delta":
                violations.append("warnings_increased")
            elif c.kind == "probe.expects_count_delta":
                # The witnessed category delta fell short of the model's own
                # declared postcondition (create/delete count contract).
                violations.append("expects_count_mismatch")

    # Empty-result suspicion (never alone a fail; recorded for the row).
    if _is_empty_result(result):
        violations.append("empty_result")

    # De-duplicate, preserve first-seen order.
    return list(dict.fromkeys(violations))
