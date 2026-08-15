"""Fail-closed contracts across nested planning, grounding and acceptance."""
from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest import mock

import pytest

from kukai.ir import compiler as compiler_module
from kukai.ir.acceptance_evidence import AcceptanceEvidenceError, AcceptanceRegistration
from kukai.ir.compiler import compile_program, plan_program
from kukai.ir.ground import ground as legacy_ground
from kukai.ir.ground import ground_program
from kukai.ir.midend import GroundedProgram
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _wall(member_id: str = "W1") -> dict:
    return {
        "op": "create_wall",
        "id": member_id,
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "element_id", "value": 42},
        "height_mm": 3000,
    }


def _group(member: dict | None = None) -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "create_group",
            "id": "G1",
            "members": [member or _wall()],
            "placements": [[0, 0, 3000]],
        }],
    }


@pytest.mark.parametrize("bad_value", ["evil", True, float("inf")])
def test_nested_numeric_is_fully_validated_before_ground(bad_value):
    program = _group()
    program["ops"][0]["members"][0]["height_mm"] = bad_value

    out = compile_program(program, snapshot=GROUND_SNAPSHOT)

    assert not out.ok
    assert any(
        item.field_name == "members[W1].height_mm"
        and item.code in {"KIR-T001", "KIR-T002"}
        for item in out.diagnostics
    )
    assert out.grounded is None


@pytest.mark.parametrize("member", [
    {
        "op": "set_param", "id": "M1",
        "target": {"by": "element_id", "value": 10},
        "parameter": "Comments", "value": "changed",
    },
    {
        "op": "delete", "id": "D1",
        "target": {"by": "element_id", "value": 10},
    },
])
def test_modify_and_delete_cannot_masquerade_as_group_members(member):
    out = compile_program(
        {**_group(member), "allow_destructive": True},
        snapshot=GROUND_SNAPSHOT,
    )

    assert not out.ok
    assert any(
        item.field_name == "members[0].op"
        for item in out.diagnostics
    )


def test_nested_contract_change_changes_parent_plan_digest():
    program = _group()
    baseline = plan_program(copy.deepcopy(program))
    real_contract_for = compiler_module.contract_for

    def changed_contract(op_name: str):
        contract = real_contract_for(op_name)
        if op_name == "create_wall":
            return SimpleNamespace(digest="f" * 64)
        return contract

    with mock.patch(
            "kukai.ir.compiler.contract_for", side_effect=changed_contract):
        changed = plan_program(copy.deepcopy(program))

    baseline_nested = baseline.ops[0].nested_contracts[0]
    changed_nested = changed.ops[0].nested_contracts[0]
    assert baseline_nested.payload_digest == changed_nested.payload_digest
    assert baseline_nested.contract_digest != changed_nested.contract_digest
    assert baseline.plan_digest != changed.plan_digest


@pytest.mark.parametrize("mutation", [
    lambda op: op.__setitem__("height_mm", 9999.0),
    lambda op: op.__setitem__("category", "OST_Doors"),
    lambda op: op.__setitem__("__foo", {"looks": "internal"}),
    lambda op: op["level"]["__grounded__"].__setitem__("id", 9999),
])
def test_buggy_grounder_cannot_change_semantics_or_add_private_fields(mutation):
    planned = plan_program(_group())

    def corrupted(ops, snapshot):
        grounded = legacy_ground(ops, snapshot)
        # ``ground`` recursively processes the validated member list.  Leave
        # that inner call intact and corrupt only the enclosing group result,
        # exactly where an implementation bug could otherwise escape.
        if grounded and grounded[0].get("op") == "create_group":
            mutation(grounded[0]["members"][0])
        return grounded

    with mock.patch("kukai.ir.ground.ground", side_effect=corrupted):
        with pytest.raises(ValueError, match="illegal grounding refinement"):
            ground_program(planned, GROUND_SNAPSHOT)


def test_valid_group_selector_lowering_is_recursive_and_accounted():
    planned = plan_program(_group())
    grounded = ground_program(planned, GROUND_SNAPSHOT)
    member = grounded.to_ops()[0]["members"][0]

    assert member["level"] == {
        "__grounded__": {"id": 42, "name": None, "via": "element_id"}
    }
    assert any(
        row["field_name"] == "members[0].level"
        for row in grounded.resolution_report()
    )


def test_ground_digest_is_mandatory_acceptance_identity():
    planned = plan_program(_group())
    grounded = ground_program(planned, GROUND_SNAPSHOT)
    assert len(grounded.ground_digest) == 64

    # The evidence boundary checks this identity before it can accept any
    # predicate/baseline payload or grant journal authority.
    with pytest.raises(AcceptanceEvidenceError, match="ground_digest"):
        AcceptanceRegistration(
            run_id="a" * 32,
            plan_digest=planned.plan_digest,
            ground_digest="not-a-digest",
            revit_version="2026",
            expectation=None,  # type: ignore[arg-type]
            mutation_expectation=None,  # type: ignore[arg-type]
            document=None,  # type: ignore[arg-type]
            categories=(),
            before=None,
            mutation_before=None,
        )


def test_grounded_program_rejects_another_exact_payload_under_old_digest():
    planned = plan_program(_group())
    grounded = ground_program(planned, GROUND_SNAPSHOT)
    tampered = grounded.to_ops()
    tampered[0]["members"][0]["height_mm"] = 3100.0

    with pytest.raises(ValueError, match="ordinary planned value changed"):
        GroundedProgram.from_ops(planned, tampered)


def _floor_program() -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "create_floor_by_contour",
            "id": "F1",
            "contour": {
                "outer": {
                    "shape": "rect",
                    "origin": [0, 0],
                    "size_mm": [8000, 6000],
                },
            },
            "level": {"by": "element_id", "value": 42},
        }],
    }


def _route_program() -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "route_pipe_system",
            "id": "R1",
            "level": {"by": "element_id", "value": 42},
            "nodes": [
                {"id": "A", "xyz_mm": [0, 0, 0]},
                {"id": "B", "xyz_mm": [5000, 0, 100]},
            ],
            "segments": [{
                "from": "A",
                "to": "B",
                "diameter_mm": 100,
                "slope_min_pct": 1,
            }],
        }],
    }


@pytest.mark.parametrize("artifact,mutate", [
    ("__region__", lambda value: value["outer"][0][0].__setitem__(0, 777)),
    ("__graph__", lambda value: value["nodes"]["A"].__setitem__(0, 777)),
    ("__slope_reqs__", lambda value: value.__setitem__(
        next(iter(value)), 99.0)),
])
def test_derived_artifact_mutation_is_recomputed_and_refused(artifact, mutate):
    program = _floor_program() if artifact == "__region__" else _route_program()
    out = compile_program(program, snapshot=GROUND_SNAPSHOT)
    assert out.ok and out.grounded is not None and out.planned is not None
    tampered = out.grounded.to_ops()
    mutate(tampered[0][artifact])

    with pytest.raises(ValueError, match="undeclared lowering field added"):
        GroundedProgram.from_ops(
            out.planned,
            tampered,
            context=out.grounded.context,
            snapshot=GROUND_SNAPSHOT,
        )


@pytest.mark.parametrize("artifact", [
    "__region__", "__graph__", "__slope_reqs__",
])
def test_required_derived_artifact_cannot_disappear(artifact):
    program = _floor_program() if artifact == "__region__" else _route_program()
    out = compile_program(program, snapshot=GROUND_SNAPSHOT)
    assert out.ok and out.grounded is not None and out.planned is not None
    tampered = out.grounded.to_ops()
    tampered[0].pop(artifact)

    with pytest.raises(ValueError, match="required lowering artifacts missing"):
        GroundedProgram.from_ops(
            out.planned,
            tampered,
            context=out.grounded.context,
            snapshot=GROUND_SNAPSHOT,
        )


def test_grounded_evidence_does_not_overclaim_selector_replay():
    out = compile_program(_floor_program(), snapshot=GROUND_SNAPSHOT)
    assert out.ok and out.grounded is not None
    evidence = out.grounded.to_evidence_dict()["validation"]

    assert evidence == {
        "derived_artifacts_verified": True,
        "selector_resolution_replayed": False,
    }
