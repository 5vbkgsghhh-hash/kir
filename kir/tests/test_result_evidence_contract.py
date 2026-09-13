"""Shared result contracts use the compiler's typed obligations, not counts."""
import pytest

from kir import bridge_result
from kir.compiler import compile_program, plan_program


def level(oid="L"):
    out = compile_program({"ops": [{"op": "create_level", "id": oid, "elev_mm": 0}]})
    assert out.ok, out.diagnostics
    return out.planned


@pytest.mark.parametrize("planned", [None, {}, {"ops": []}, [], "plan"])
def test_missing_exact_plan_never_becomes_zero_obligations(planned):
    with pytest.raises(ValueError):
        bridge_result.expected_results(planned)
    assert bridge_result.result_contract_diagnostic({"ok": True}, "write", planned)
    verdict = bridge_result.assess_write_result({"ok": True}, planned)
    assert not verdict.ok
    assert verdict.outcome.execution.value == "unconfirmed"


@pytest.mark.parametrize("oid", ["result", "receipt", "state", "commit_status", "error"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_legal_output_names_are_not_transport_control_fields(oid, wrapped):
    plan = level(oid)
    payload = {"ok": True, oid: {"id": "700"}}
    wire = {"result": payload} if wrapped else payload
    assert bridge_result.result_contract_diagnostic(wire, "write", plan) is None
    assert bridge_result.assess_write_result(wire, plan).ok


@pytest.mark.parametrize("value,valid", [
    (["100", "101"], True), ([], False), ([True], False),
    ([0], False), ([None], False), ("100", False), (["100", "x"], False),
])
def test_many_element_identity_comes_from_registered_result_spec(value, valid):
    plan = plan_program({"ops": [{
        "op": "move_elements", "id": "move",
        "targets": [{"by": "element_id", "value": 100}], "delta_mm": [0, 0, 500],
    }]})
    payload = {"ok": True, "move": {"moved_ids": value, "count": 2}}
    assessment = bridge_result.assess_write_result(payload, plan)
    assert assessment.ok is valid
    assert assessment.outcome.committed


def test_result_family_must_match_plan():
    assert bridge_result.result_contract_diagnostic({"L": {"id": "1"}}, "query", level())


def test_cyclic_envelope_is_unknown_not_recursion_or_rollback():
    envelope = {"commit_status": "RolledBack"}
    envelope["result"] = envelope
    assert bridge_result.explicit_commit_status(envelope) is None
    assert not bridge_result.assess_write_result(envelope, level()).ok


@pytest.mark.parametrize("wire,expected", [
    ({"commit_status": "RolledBack"}, "RolledBack"),
    ({"commit_status": "RolledBack", "result": {"commit_status": "RolledBack"}}, "RolledBack"),
    ({"commit_status": "RolledBack", "result": {"commit_status": "Committed"}}, None),
    ({"commit_status": None}, None), ({"commit_status": 1}, None),
    ({"error": "stale_or_failed"}, None),
])
def test_explicit_status_does_not_infer_or_choose_between_contradictions(wire, expected):
    assert bridge_result.explicit_commit_status(wire) == expected


def test_serving_reexports_the_same_pure_contracts():
    from kir import serving
    assert serving._result_contract_diagnostic is bridge_result.result_contract_diagnostic
    assert serving._expected_results is bridge_result.expected_results
    assert serving._explicit_commit_status is bridge_result.explicit_commit_status
    assert serving._postcondition_violations is bridge_result.postcondition_violations
