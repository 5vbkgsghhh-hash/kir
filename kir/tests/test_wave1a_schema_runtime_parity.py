"""Regressions of the payload-bound plan and of schema/runtime parity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kir import authoring_validation, geom, spec
from kir.compiler import plan_program
from kir.midend import GROUND_SCHEMA, PLAN_SCHEMA
from kir.op_contract import OP_CONTRACT_SCHEMA, contract_for
from kir.schema_gen import _op_schema

jsonschema = pytest.importorskip("jsonschema")


_ARCHIVED_V3_HASH = "a9afed580e1ee9ffd3609b75651694b6a13c510b373be40960304de8369db715"
_ARCHIVED_V3_FIXTURE = Path(__file__).with_name("archived_plan_v3_floor_as_wall.json")


def _archived_v3_evidence(fixture=None):
    """Read exact historical UTF-8 bytes, never today's contract under an old tag."""
    if fixture is None:
        fixture = json.loads(_ARCHIVED_V3_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["source_commit"] == "0369326f7dbac1d1ec844d165344ace60ea77961"
    assert fixture["first_preservation_test_commit"] == "b3d60e11abbecba828051c110017f9f40e228f46"
    assert fixture["plan_digest"] == _ARCHIVED_V3_HASH
    raw = fixture["canonical_unsigned_plan_utf8"].encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == _ARCHIVED_V3_HASH
    payload = json.loads(raw)
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8") == raw
    return {**payload, "plan_digest": _ARCHIVED_V3_HASH}


def _prop(op_name: str, param_name: str) -> dict:
    return _op_schema(spec.OPS[op_name])["properties"][param_name]


def _valid(schema: dict, value) -> bool:
    return not list(jsonschema.Draft202012Validator(schema).iter_errors(value))


def _wall_type_program(host_kind: str | None) -> dict:
    op = {
        "op": "create_wall_type",
        "id": "T1",
        "source_type": {"by": "element_id", "value": 4001},
        "new_name": "KIR parity type",
        "layers": [{"width_mm": 80.0, "function": "Substrate"}],
    }
    if host_kind is not None:
        op["host_kind"] = host_kind
    return {"ir_version": spec.IR_VERSION, "ops": [op]}


@pytest.mark.parametrize(
    ("host_kind", "expected"),
    [(None, "wall_type"), ("wall", "wall_type"),
     ("floor", "floor_type"), ("roof", "roof_type"),
     ("ceiling", "ceiling_type")],
)
def test_planned_result_is_bound_to_the_normalised_payload(
    host_kind: str | None, expected: str,
) -> None:
    plan = plan_program(_wall_type_program(host_kind))
    planned = plan.ops[0]
    assert planned.result.reference_kind is not None
    assert planned.result.reference_kind.value == expected
    # Grounding already uses the same payload-dependent dispatch: the plan
    # and the grounder must now read one and the same decision.
    pools = dict((name, pool) for name, pool, _required in
                 spec.OPS["create_wall_type"].grounded_for(planned.to_dict()))
    assert pools["source_type"] == f"{expected}s"


def test_wrong_v3_result_remains_an_archived_digest() -> None:
    """An old false lead does not get a new interpretation under the same schema."""
    plan = plan_program(_wall_type_program("floor"))
    current = plan.to_evidence_dict()
    assert current["schema"] == PLAN_SCHEMA == "kir-planned-program/4"
    assert GROUND_SCHEMA == "kir-grounded-program/4"

    # Commit 0369326 really emitted this v3 payload; b3d60e1 preserved its hash.
    # 878947f later strengthened the signed ownership postcondition, correctly
    # changing OpContract.digest. Re-tagging today's plan cannot recreate that
    # older contract, even while OP_CONTRACT_SCHEMA still describes the same form.
    archived_v3 = _archived_v3_evidence()
    assert archived_v3["schema"] == "kir-planned-program/3"
    assert archived_v3["ops"][0]["payload"]["host_kind"] == "floor"
    assert archived_v3["ops"][0]["result"]["reference_kind"] == "wall_type"
    assert current["ops"][0]["result"]["reference_kind"] == "floor_type"
    assert archived_v3["plan_digest"] != plan.plan_digest

    # The OpContract shape did not change: `/2` already signed the whole
    # variant table.
    assert OP_CONTRACT_SCHEMA == "kir-op-contract/2"
    assert contract_for("create_wall_type").to_dict()["schema"] \
        == OP_CONTRACT_SCHEMA


def test_changing_one_archived_value_cannot_redefine_its_identity():
    fixture = json.loads(_ARCHIVED_V3_FIXTURE.read_text(encoding="utf-8"))
    changed = json.loads(fixture["canonical_unsigned_plan_utf8"])
    changed["ops"][0]["payload"]["layers"][0]["width_mm"] = 81.0
    fixture["canonical_unsigned_plan_utf8"] = json.dumps(
        changed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with pytest.raises(AssertionError):
        _archived_v3_evidence(fixture)
    # Re-signing the altered bytes is still not the retained historical identity.
    fixture["plan_digest"] = hashlib.sha256(fixture["canonical_unsigned_plan_utf8"].encode()).hexdigest()
    with pytest.raises(AssertionError):
        _archived_v3_evidence(fixture)


def test_current_archive_reader_refuses_the_original_v3_plan():
    from kir.revit_connector import ContextPrecondition, RuntimeTarget, prepare_execution
    from kir.saved_execution import SavedExecutionError, SavedExecutionRecord, _capture, _canonical, _hash

    prepared = prepare_execution(_wall_type_program("floor"),
        target=RuntimeTarget("835730cf-e0ba-4603-ad2b-613ae92f8dce",
                             "ca974323-cdfe-4fe6-88ac-2c16bcaa80ac", "2026"),
        precondition=ContextPrecondition("synthetic-archive-schema-control", 0),
        operation_id="39d6aa12-4860-4a64-b23b-59fd2e6d30a4")
    raw = _capture(prepared)
    assert SavedExecutionRecord._from_bytes(raw).digest
    old = json.loads(raw)
    old["plan_evidence"] = _archived_v3_evidence()
    old["record_digest"] = _hash({key: value for key, value in old.items() if key != "record_digest"})
    with pytest.raises(SavedExecutionError, match="expected retained plan evidence schema") as refusal:
        SavedExecutionRecord._from_bytes(_canonical(old).encode("utf-8"))
    assert refusal.value.code == "unsupported_saved_execution"


@pytest.mark.parametrize(
    ("op_name", "field", "lo", "hi", "reject_dupes"),
    [("create_dimension", "refs", 2, 16, True),
     ("create_angular_dimension", "refs", 2, 2, True),
     ("move_elements", "targets", 1, 500, False)],
)
def test_refs_w_schema_reads_the_runtime_contract(
    op_name: str, field: str, lo: int, hi: int, reject_dupes: bool,
) -> None:
    schema = _prop(op_name, field)
    assert (schema["minItems"], schema["maxItems"]) == (lo, hi)
    assert schema.get("uniqueItems", False) is reject_dupes
    assert _valid(schema, [
        {"by": "element_id", "value": index + 1}
        for index in range(lo)
    ])
    assert not _valid(schema, [
        {"by": "element_id", "value": index + 1}
        for index in range(hi + 1)
    ])


def test_long_text_schema_uses_the_runtime_limit() -> None:
    schema = _prop("create_text", "content")
    limit = authoring_validation._TEXT_CONTENT_MAX_CHARS
    assert schema["maxLength"] == limit
    assert _valid(schema, "x" * limit)
    assert not _valid(schema, "x" * (limit + 1))


@pytest.mark.parametrize(
    "op_name", ["create_floor", "create_ceiling", "create_foundation"],
)
def test_empty_flat_holes_are_legal_in_schema_and_runtime(op_name: str) -> None:
    schema = _prop(op_name, "holes")
    assert schema["minItems"] == 0
    assert schema["maxItems"] == geom.MAX_HOLES
    assert schema["items"]["minItems"] == geom.MIN_RING_POINTS
    assert schema["items"]["maxItems"] == geom.MAX_HOLE_RING_POINTS
    assert _valid(schema, [])
    diagnostics = []
    normalised = authoring_validation.validate(
        {"op": op_name, "id": "H1", "holes": []},
        op_name, 0, "H1", diagnostics,
    )
    assert "holes" not in normalised  # an explicit [] is canonicalized to absence
    assert not [item for item in diagnostics if item.field_name == "holes"]
