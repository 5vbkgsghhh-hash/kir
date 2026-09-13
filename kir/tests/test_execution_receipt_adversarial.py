"""Independent D1 counterexamples: controls cannot vanish behind readback IDs.

These are real compiled plans and in-memory wire values, not Revit execution.
They test evidence classification, not independent geometric acceptance.
"""
from __future__ import annotations

import pytest

from kir.bridge_result import assess_write_result
from kir.compiler import compile_program
from kir.outcome import ExecutionState, WitnessState


def _plan(identifier="L"):
    compiled = compile_program({"ops": [{
        "op": "create_level", "id": identifier, "elev_mm": 0,
    }]}, revit_version="2026")
    assert compiled.ok, compiled.diagnostics
    assert compiled.planned is not None
    return compiled.planned


@pytest.mark.parametrize("identifier", [
    "L", "result", "error",
])
def test_typed_operation_names_are_not_failed_transport_control_fields(identifier):
    assessment = assess_write_result(
        {"ok": True, identifier: {"id": "123"}}, _plan(identifier))
    assert assessment.ok, assessment
    assert assessment.outcome.witness is WitnessState.SATISFIED
    assert assessment.outcome.acceptance.value == "not_run"


@pytest.mark.parametrize("wrapper_evidence", [
    {"postcondition_violations": ["L: wrong elevation"]},
    {"postcondition_violations": None},
])
def test_known_witness_evidence_on_a_wrapper_is_not_silently_dropped(wrapper_evidence):
    result = {"result": {"ok": True, "L": {"id": "123"}},
              **wrapper_evidence}
    assessment = assess_write_result(result, _plan())
    assert not assessment.ok, assessment
    assert assessment.outcome.witness is not WitnessState.SATISFIED


@pytest.mark.parametrize("nested_control", [
    {"state": "running_unknown"},
    {"status": "receipt"},
    {"commit_status": "RolledBack"},
    {"result_truncated": True},
])
def test_result_named_operation_does_not_hide_ambiguous_execution_control(nested_control):
    # Without a discriminator this can also be a transport-success wrapper
    # around a failed/unknown execution response containing its own id.
    receipt = {"ok": True, "result": {"id": "123", **nested_control}}
    assessment = assess_write_result(receipt, _plan("result"))
    assert not assessment.ok, assessment
    assert assessment.outcome.execution is not ExecutionState.ROLLED_BACK
    assert assessment.outcome.retry_safety.value != "safe"


def test_actual_typed_result_remains_valid_through_a_transport_wrapper():
    receipt = {"ok": True, "result": {"ok": True, "result": {"id": "123"}}}
    assessment = assess_write_result(receipt, _plan("result"))
    assert assessment.ok, assessment


def test_witnesses_accumulate_without_erasing_a_confirmed_commit():
    receipt = {
        "postcondition_violations": ["outer violation", None],
        "result": {
            "postcondition_violations": ["middle violation"],
            "result": {"ok": True, "L": {"id": "123"},
                       "postcondition_violations": ["inner violation"]},
        },
    }
    assessment = assess_write_result(receipt, _plan())
    assert not assessment.ok
    assert assessment.outcome.execution is ExecutionState.COMMITTED
    assert assessment.outcome.witness is WitnessState.VIOLATED
    assert assessment.violations == (
        "outer violation", "middle violation", "inner violation")


def test_malformed_wrapper_witness_preserves_commit_but_not_satisfaction():
    receipt = {"postcondition_violations": None,
               "result": {"ok": True, "L": {"id": "123"}}}
    assessment = assess_write_result(receipt, _plan())
    assert not assessment.ok
    assert assessment.outcome.execution is ExecutionState.COMMITTED
    assert assessment.outcome.witness is WitnessState.INCOMPLETE


def test_explicit_empty_wrapper_witness_remains_legal():
    receipt = {"postcondition_violations": [],
               "result": {"ok": True, "L": {"id": "123"}}}
    assert assess_write_result(receipt, _plan()).ok


def test_no_plan_and_cyclic_wrappers_do_not_manufacture_a_verdict():
    receipt = {"ok": True, "L": {"id": "123"}}
    assert not assess_write_result(receipt, None).ok
    cyclic = {}
    cyclic["result"] = cyclic
    assessment = assess_write_result(cyclic, _plan())
    assert not assessment.ok
    assert assessment.outcome.execution is ExecutionState.UNCONFIRMED
