"""Flat emitter metadata must not erase an authored result's identity."""
import pytest
from dataclasses import replace
from jsonschema import Draft202012Validator

from kir import schema_gen, spec
from kir.compiler import KirRefusal, compile_program, plan_program


@pytest.mark.parametrize("oid", [
    "ok", "postcondition_violations", "revit_warnings",
    "revit_errors_resolved", "post", "residual_effect",
])
@pytest.mark.parametrize("op", [
    {"op": "create_level", "elev_mm": 0},
    {"op": "query_count", "kind": "wall"},
])
def test_reserved_result_id_is_a_named_refusal_before_lowering(oid, op):
    program = {"ops": [{**op, "id": oid}]}
    out = compile_program(program)
    assert not out.ok and not out.csharp
    assert any(d.field_name == "id" and d.got == oid for d in out.diagnostics)
    with pytest.raises(KirRefusal):
        plan_program(program)
    validator = Draft202012Validator(schema_gen._op_schema(spec.OPS[op["op"]]))
    assert not validator.is_valid(program["ops"][0])


@pytest.mark.parametrize("oid", ["OK", "level_ok", "result", "receipt", "state", "error"])
def test_other_names_are_not_rewritten_or_banned(oid):
    program = {"ops": [{"op": "create_level", "id": oid, "elev_mm": 0}]}
    out = compile_program(program)
    assert out.ok, out.diagnostics
    assert out.planned.ops[0].op_id == oid
    assert Draft202012Validator(schema_gen._op_schema(spec.OPS["create_level"])).is_valid(program["ops"][0])


def test_generated_schemas_consume_one_metadata_contract():
    expected = sorted(spec.PROGRAM_RESULT_METADATA_KEYS)
    for operation in spec.OPS.values():
        assert schema_gen._op_schema(operation)["properties"]["id"]["not"]["enum"] == expected


def test_preexisting_typed_plan_cannot_bypass_the_wire_correction():
    from kir.midend import PlannedOp
    valid = plan_program({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]})
    op = valid.ops[0]
    old_op = PlannedOp.from_dict(
        {**op.to_dict(), "id": "ok"}, family=op.family, effect=op.effect,
        result=op.result, contract_digest=op.contract_digest, provenance=op.provenance,
    )
    archived = replace(valid, ops=(old_op,), plan_digest="")
    with pytest.raises(KirRefusal):
        plan_program(archived)
    result = compile_program(archived)
    assert not result.ok and not result.csharp
    assert archived.ops[0].op_id == "ok"  # archival identity is never rewritten
