"""Transport-neutral parsing of declarative bridge result envelopes.

The bridge may wrap a result once, but execution-state classification must be
identical for ordinary KIR serving and the A5 live recovery adapter.  Keeping
that parser here prevents either orchestrator from inventing its own failure
semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from kir.outcome import (
    ProgramOutcome, WitnessState, execution_unconfirmed,
    write_committed, write_rolled_back,
)


def extract_error(exec_res: Any) -> Optional[dict]:
    """Return a failure signal from the top or first nested result layer."""

    nested = exec_res.get("result") if isinstance(exec_res, dict) else None
    for layer in (exec_res, nested):
        if not isinstance(layer, dict):
            continue
        err = layer.get("error")
        state = str(layer.get("state", "")).lower()
        if (err or layer.get("ok") is False or layer.get("success") is False
                or state in ("error", "failed")):
            return {"error": err if err else state or "error", "layer": layer}
        if state == "timeout_unconfirmed":
            return {"error": "timeout_unconfirmed", "layer": layer}
    return None


# Historical private spelling retained for compatibility with serving probes.
_extract_error = extract_error


#: 🔴 THREE SPELLINGS OF ONE UNKNOWN, AND NOT ONE MATCHED THE BRIDGE.
#: Measured 24.08.2026 on envelopes collected from LIVE builders:
#:
#:     the bridge sends       state='RunningUnknown'  err.code=transport.execution_unknown
#:                             (no state)              err.code=transport.bridge_timeout
#:     serving.py checked     the string "timeout_unconfirmed"      -> NEVER matched
#:     write/create_element checked state "running_unconfirmed"     -> did not match
#:
#: Both forms carry `error: True`, so `extract_error` takes the FIRST branch
#: and returns `True`; the string "timeout_unconfirmed" is only ever born
#: from a hand-built fixture without an `error` key — a shape the bridge
#: does not produce. The carrier of the unknown, `record.state`, never
#: reaches KIR at all: `revit_execution_pipeline.to_tool_result()` returns
#: only `result`.
#:
#: These are LEGACY spellings, kept for the sake of old receipts on disk.
#: The list is CLOSED AND NOT COMPLETE: an empty cell means "we do not know
#: of such a spelling," not "no such spelling exists."
_LEGACY_UNCONFIRMED_STATES = frozenset({
    "timeout_unconfirmed",
    "running_unconfirmed",
})


def unconfirmed_authority() -> tuple[frozenset[str], frozenset[str]]:
    """`(codes, states)` — ASKED of the place of definition, not copied.

    🔴 27.08.2026: `ErrCode` WAS ASKED OF THE PRODUCT, YET IT LIVES HERE.
    It used to say `from kir.envelope import ErrCode`, but
    `kukai/llm/envelope.py` is a pure re-export
    (`from kir.envelope import *`). That is, KIR was asking the product to
    hand back KIR's OWN definition, and the instrument read that as crossing
    the boundary. We ask the place of definition — `kir.envelope`. This is a
    correction, not an inversion: not a single value moved.

    `OperationOutcome` stays where it is declared — `kir/operations/` was
    measured into KIR's territory on 27.08 (796 lines, zero exits into the
    product, zero third parties): a typed execution outcome of a program
    belongs to the language, not the product.

    The import stays lazy: the invariant "zero top-level product imports"
    is held by an instrument, not by habit.
    """
    from kir.envelope import ErrCode
    from kir.operations.protocol import OperationOutcome

    codes = frozenset({
        ErrCode.TRANSPORT_EXECUTION_UNKNOWN.value,
        ErrCode.TRANSPORT_BRIDGE_TIMEOUT.value,
        ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED.value,
    })
    states = frozenset(
        {OperationOutcome.RUNNING_UNKNOWN.value.lower()}
    ) | _LEGACY_UNCONFIRMED_STATES
    return codes, states


def is_unconfirmed(exec_res: Any) -> bool:
    """The outcome is UNKNOWN: Revit may have committed, and there is no
    proof either way.

    A TYPED CODE is asked for, not a message substring. Matching by phrase
    already failed once: `write/create_element.py:1112` looks for "не
    подтвержд", while the bridge writes "не подтверди**л**" — a
    look-alike match missed exactly the envelope it was written for
    (measured 24.08.2026).

    WHAT I DO NOT SEE. I answer "is it unknown," and I do NOT answer "what
    was built": after `True` the caller must leave the effect hanging and
    check the stamp's prefix on the next run. Forms whose code the bridge
    has not yet typed (`bridge_frozen` — a debt named in
    `bridge_protocol.py:1650`) are invisible to me: they will arrive as
    `bridge_timeout` and be counted correctly, but under someone else's
    code.
    """
    if not isinstance(exec_res, dict):
        return False
    codes, states = unconfirmed_authority()
    nested = exec_res.get("result")
    for layer in (exec_res, nested):
        if not isinstance(layer, dict):
            continue
        err = layer.get("err")
        if isinstance(err, dict) and str(err.get("code", "")) in codes:
            return True
        if str(layer.get("state", "")).lower() in states:
            return True
    return False


def expected_results(planned: Any) -> list[tuple[str, Any]]:
    """Obligations belong to the exact lowered plan, never an empty fallback."""
    from kir.midend import PlannedProgram
    if not isinstance(planned, PlannedProgram):
        raise ValueError("exact PlannedProgram is required for result evidence")
    return [(op.op_id, op.result) for op in planned.ops]


def _result_layers(exec_res: Any, planned: Any = None) -> tuple[Mapping, ...]:
    """Unwrap at most two legacy result envelopes, without cycles.

    An operation may legally be named ``result``. A typed per-op identity
    under that name is not a transport wrapper. Connector/2 receipts must be
    bound and decoded by its adapter; they are not legacy KIR payloads.
    """
    try:
        expected = dict(expected_results(planned))
    except ValueError:
        expected = {}
    return _result_layers_for(exec_res, expected)


def _result_layers_for(exec_res: Any, expected: Mapping) -> tuple[Mapping, ...]:
    """Result-only obligations; never a reconstructed executable plan."""
    result_spec = expected.get("result")
    layers: list[Mapping] = []
    layer = exec_res
    for _depth in range(3):
        if not isinstance(layer, Mapping) or any(layer is old for old in layers):
            return ()
        layers.append(layer)
        if "result" not in layer:
            return tuple(layers)
        nested = layer["result"]
        if (result_spec is not None and result_spec.identity_field is not None
                and isinstance(nested, Mapping)
                and result_spec.identity_present(nested)):
            # With this unframed legacy format an id alone cannot prove that
            # the object is a per-op row rather than an execution response.
            # Do not hide explicit execution control behind the legal op name
            # "result"; nor claim rollback from one ambiguous interpretation.
            if any(key in nested for key in (
                    "state", "status", "commit_status", "ok", "success",
                    "error", "err", "receipt", "result_json", "result_error",
                    "result_truncated", "truncated", "serialization_error",
                    "postcondition_violations")):
                return ()
            return tuple(layers)
        layer = nested
    return ()


def explicit_commit_status(exec_res: Any, planned: Any = None) -> str | None:
    """One non-conflicting typed status, or unknown. No inference from prose."""
    layers = _result_layers(exec_res, planned)
    try:
        ids = dict(expected_results(planned))
    except ValueError:
        ids = {}
    return _commit_status_for(layers, ids)


def _commit_status_for(layers: tuple[Mapping, ...], ids: Mapping) -> str | None:
    statuses = []
    for layer in layers:
        if "commit_status" not in layer:
            continue
        if layer is layers[-1] and "commit_status" in ids:
            continue
        status = layer["commit_status"]
        if not isinstance(status, str) or not status:
            return None
        statuses.append(status)
    return statuses[0] if statuses and len(set(statuses)) == 1 else None


def postcondition_violations(payload: Any) -> list[str]:
    """Report-mode violations. Malformed evidence is checked separately."""
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("postcondition_violations")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _witness_violations(layers: tuple[Mapping, ...]) -> tuple[tuple[str, ...], bool]:
    """Retain explicit violations from every parsed layer, naming malformed data.

    A wrapper cannot erase a witness by putting an otherwise complete result
    beneath it. Invalid entries never become a satisfied witness; valid
    violations remain evidence even alongside an invalid entry.
    """
    violations: list[str] = []
    valid = True
    for layer in layers:
        if "postcondition_violations" not in layer:
            continue
        raw = layer["postcondition_violations"]
        if not isinstance(raw, list):
            valid = False
            continue
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                valid = False
            else:
                violations.append(item)
    return tuple(violations), valid


def _diagnostic(detail: str) -> dict:
    return {"code": "KIR-X008",
            "message_ru": "результат исполнения не подтверждён полностью — проверь модель query-запросом",
            "detail": detail}


def result_contract_diagnostic(exec_res: Any, family: str,
                               planned: Any) -> Optional[dict]:
    """Typed result completeness shared by serving and standalone callers.

    It checks execution readback, not independent geometric acceptance.
    """
    try:
        expected = expected_results(planned)
    except ValueError as exc:
        return _diagnostic(str(exc))
    if family not in ("query", "write") or planned.family.value != family:
        return _diagnostic("result family does not match exact plan")
    return _contract_diagnostic_for(_result_layers_for(exec_res, dict(expected)), family, expected)


def _contract_diagnostic_for(layers: tuple[Mapping, ...], family: str,
                             expected: list[tuple[str, Any]]) -> Optional[dict]:
    if not layers:
        return _diagnostic("result payload is not an object or wrappers are invalid")
    payload = layers[-1]
    if family == "write" and payload.get("ok") is not True:
        return _diagnostic("write result lacks exact ok=true")
    missing = [oid for oid, _ in expected
               if not isinstance(payload.get(oid), Mapping)]
    if missing:
        return _diagnostic("missing/non-object result keys: " + ", ".join(missing[:10]))
    if family == "write":
        unidentified = [oid for oid, spec in expected
                        if not spec.identity_present(payload[oid])]
        if unidentified:
            return _diagnostic("result keys without typed identity: " +
                               ", ".join(unidentified[:10]))
        if not _witness_violations(layers)[1]:
            return _diagnostic("malformed postcondition_violations evidence")
    return None


@dataclass(frozen=True)
class WriteResultAssessment:
    """Assessment of a legacy KIR payload, not a durable execution receipt."""
    outcome: ProgramOutcome
    diagnostic: dict | None = None
    violations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome.committed and self.outcome.witness is WitnessState.SATISFIED


def assess_write_result(exec_res: Any, planned: Any) -> WriteResultAssessment:
    """Classify existing KIR result evidence without claiming intent success.

    Exact inner ``ok=true`` is the compiler's post-Commit marker. Missing
    identities after that marker mean committed/incomplete, not rollback.
    Unknown transport states, contradictory statuses and unbound Connector/2
    envelopes remain unconfirmed; their adapters must first establish which
    execution the result belongs to. Error names never prove rollback.

    A per-op ``{"refused": …}`` row is the ORDINARY way a ``per_op`` program
    reports one rolled back operation among committed neighbours. It reaches
    the outcome as committed/INCOMPLETE — the refused row carries no typed
    identity, so ``_contract_diagnostic_for`` names it — and NOT as VIOLATED.
    ``VIOLATED`` is reserved for ``postcondition_violations``: an assertion
    about elements that SURVIVED the commit. Until C-1 (2026-09-06) the
    per_op operation-stage gate left the refused operation's message in that
    program-wide list, so one rolled back operation turned a legitimate
    partial rebuild into a violated witness; the message now travels in the
    refusal itself. ``__ok=false`` (or any refused row) still does not prove
    a rollback of anything but that operation's own SubTransaction.
    """
    unknown = execution_unconfirmed()
    try:
        expected = dict(expected_results(planned))
    except ValueError as exc:
        return WriteResultAssessment(unknown, _diagnostic(str(exc)))
    if planned.family.value != "write":
        return WriteResultAssessment(unknown, _diagnostic("write plan required"))
    return _assess_write_result_for(exec_res, expected)


def _assess_write_result_for(exec_res: Any, expected: Mapping) -> WriteResultAssessment:
    """The shared D1 classifier consumes only result obligations, not code."""
    unknown = execution_unconfirmed()
    layers = _result_layers_for(exec_res, expected)
    if not layers:
        return WriteResultAssessment(unknown, _diagnostic("missing or malformed result envelope"))
    payload = layers[-1]
    for layer in layers:
        # Per-op result names are not transport control fields.
        control = {k: v for k, v in layer.items()
                   if layer is not payload or k not in expected}
        if any(key in control for key in ("receipt", "result_json")):
            return WriteResultAssessment(unknown, _diagnostic("unbound Connector receipt; adapter required"))
        if ("state" in control or "status" in control
                or any(key in control and control[key] is not False
                       for key in ("truncated", "result_truncated"))
                or any(key in control and control[key] is not None
                       for key in ("serialization_error", "result_error", "err", "outcome"))
                or is_unconfirmed(control)):
            return WriteResultAssessment(unknown, _diagnostic("unclassified/incomplete transport state"))
        if layer is not payload and extract_error({k: v for k, v in control.items()
                                                  if k != "result"}) is not None:
            return WriteResultAssessment(unknown, _diagnostic("transport refusal conflicts with execution evidence"))

    status = _commit_status_for(layers, expected)
    has_status = any("commit_status" in layer for layer in layers
                     if layer is not payload or "commit_status" not in expected)
    if has_status and status not in ("Committed", "RolledBack"):
        return WriteResultAssessment(unknown, _diagnostic("unknown or contradictory commit_status"))
    if status == "RolledBack" and payload.get("ok") is True:
        return WriteResultAssessment(unknown, _diagnostic("ok=true conflicts with RolledBack"))

    failure = extract_error({k: v for k, v in payload.items() if k not in expected})
    violations, violations_valid = _witness_violations(layers)
    violation_marker = payload.get("error") == "postconditions_violated"
    if violation_marker:
        reported = payload.get("violations")
        if isinstance(reported, list):
            violations += tuple(v for v in reported if isinstance(v, str) and v.strip())
    if status == "RolledBack":
        witness = WitnessState.VIOLATED if violations or violation_marker else WitnessState.INCOMPLETE
        return WriteResultAssessment(write_rolled_back(witness=witness),
                                     _diagnostic("transaction explicitly RolledBack"), violations)

    committed = status == "Committed" or payload.get("ok") is True
    if not committed:
        return WriteResultAssessment(unknown, _diagnostic("commit was not confirmed"), violations)
    contract = _contract_diagnostic_for(layers, "write", list(expected.items()))
    if violations or violation_marker:
        return WriteResultAssessment(write_committed(witness=WitnessState.VIOLATED),
                                     _diagnostic("postconditions violated after commit"), violations)
    if failure is not None or contract is not None or not violations_valid:
        return WriteResultAssessment(write_committed(witness=WitnessState.INCOMPLETE),
                                     contract or _diagnostic("execution result is incomplete or refused"))
    return WriteResultAssessment(write_committed(witness=WitnessState.SATISFIED))


def saved_create_result_contract(record: Any) -> dict:
    """Closed flat CREATE result obligations from a checked input archive.

    This qualifies retained contracts against the current registry, without
    rebuilding a PlannedProgram or replaying source. Native birth/UID/reuse
    qualification is separate from this D1 result-completeness contract.
    """
    from kir.saved_execution import SavedExecutionRecord, PROJECT_ARCHIVE_SCHEMA
    from kir.op_contract import contract_for
    from kir.spec import OPS, IR_VERSION, PROGRAM_RESULT_METADATA_KEYS

    if type(record) is not SavedExecutionRecord:
        raise ValueError("checked project execution archive required")
    checked = SavedExecutionRecord._from_bytes(record._raw)
    if checked.digest != record.digest:
        raise ValueError("archive identity differs from its retained bytes")
    data = checked.to_dict()
    if data["schema"] != PROJECT_ARCHIVE_SCHEMA:
        raise ValueError("Archive/2 project publication required")
    plan = data["plan_evidence"]
    if (plan["ir_version"] != IR_VERSION or plan["family"] != "write"
            or plan["allow_destructive"] is not False or data["planned_units"]
            or plan["source_op_count"] != len(plan["ops"])):
        raise ValueError("initial publication requires flat CREATE operations without units or destructive effects")
    expected = {}
    for index, retained in enumerate(plan["ops"]):
        payload, origin = retained.get("payload"), retained.get("provenance")
        if not isinstance(payload, dict) or not isinstance(origin, dict):
            raise ValueError("retained operation/provenance is malformed")
        name, oid = payload.get("op"), payload.get("id")
        operation = OPS.get(name)
        if operation is None or not isinstance(oid, str) or oid in expected or oid in PROGRAM_RESULT_METADATA_KEYS:
            raise ValueError("retained operation identity is unsupported or repeated")
        if operation.result_by_param is not None:
            discriminator, _ = operation.result_by_param
            parameter = next(item for item in operation.params if item.name == discriminator)
            value = payload.get(discriminator, parameter.default)
            if type(value) is not str or value not in parameter.choices:
                raise ValueError("retained result discriminator is unsupported")
        result = operation.result_for(payload)
        claim = {"identity_cardinality": result.identity_cardinality.value,
                 "identity_field": result.identity_field,
                 "reference_kind": result.reference_kind.value if result.reference_kind is not None else None}
        if (operation.effect.value != "create" or retained.get("effect") != "create"
                or retained.get("family") != operation.family
                or result.identity_cardinality.value != "one" or result.identity_field != "id"
                or retained.get("result") != claim or retained.get("nested_contracts") != []
                or retained.get("contract_digest") != contract_for(name).digest
                or origin.get("macro_name") is not None or origin.get("source_op") != name
                or origin.get("source_id") != oid or type(origin.get("source_index")) is not int
                or origin["source_index"] != index):
            raise ValueError("retained initial CREATE result contract is unsupported or changed")
        expected[oid] = result
    if not expected:
        raise ValueError("initial publication has no CREATE results")
    return expected


def assess_saved_create_result(exec_res: Any, record: Any) -> WriteResultAssessment:
    """Reuse D1 for retained flat CREATE; never infer native ownership from ok."""
    try:
        expected = saved_create_result_contract(record)
    except (ValueError, TypeError, KeyError) as error:
        diagnostic = _diagnostic(str(error))
        diagnostic["code"] = "unsupported_saved_create_profile"
        return WriteResultAssessment(execution_unconfirmed(), diagnostic)
    return _assess_write_result_for(exec_res, expected)


def assess_saved_level_update_result(exec_res: Any, record: Any) -> WriteResultAssessment:
    """Classify the closed Archive/3 profile without reconstructing a plan.

    The Connector adapter must bind the receipt first. A checked archive is
    retained caller evidence, not authentication of historical compiler output.
    Different registry/IR contracts remain inspectable via saved lookup, but
    cannot silently inherit today's result semantics. No compilation or retry.
    """
    from kir.saved_execution import SavedExecutionRecord, UPDATE_ARCHIVE_SCHEMA
    from kir.op_contract import contract_for
    from kir.spec import OPS, IR_VERSION, PROGRAM_RESULT_METADATA_KEYS

    unknown = execution_unconfirmed()
    if type(record) is not SavedExecutionRecord:
        return WriteResultAssessment(unknown, _diagnostic("checked update archive required"))
    data = record.to_dict()
    if data["schema"] != UPDATE_ARCHIVE_SCHEMA:
        return WriteResultAssessment(unknown, _diagnostic("Archive/3 level update required"))
    plan = data["plan_evidence"]
    retained = plan["ops"][0]
    payload = retained["payload"]  # /3 validator already checks this closed profile.
    provenance = retained.get("provenance")
    report = data["update_submission"]["update"]
    spec = OPS["set_param"]
    result = spec.result_for(payload)
    result_claim = {"identity_cardinality": result.identity_cardinality.value,
        "identity_field": result.identity_field,
        "reference_kind": result.reference_kind.value if result.reference_kind is not None else None}
    if (plan["ir_version"] != IR_VERSION or plan["source_op_count"] != 1
        or payload["id"] in PROGRAM_RESULT_METADATA_KEYS
        or plan["allow_destructive"] is not False or plan["bulk"] is not False
        or retained.get("family") != spec.family or retained.get("effect") != spec.effect.value
        or retained.get("result") != result_claim or retained.get("nested_contracts") != []
        or retained.get("contract_digest") != contract_for("set_param").digest
        or not isinstance(provenance, dict) or provenance.get("macro_name") is not None
        or provenance.get("source_op") != "set_param" or provenance.get("source_id") != payload["id"]
        or type(provenance.get("source_index")) is not int or provenance["source_index"] != 0
        or report["setter_tolerance_mm"] != spec.tolerances["length_mm"]
        or report["baseline_tolerance_mm"] != OPS["create_level"].tolerances["elevation_mm"]):
        diagnostic = _diagnostic("retained update result contract is unsupported or changed")
        diagnostic["code"] = "unsupported_saved_update_profile"
        return WriteResultAssessment(unknown, diagnostic)
    return _assess_write_result_for(exec_res, {payload["id"]: result})
