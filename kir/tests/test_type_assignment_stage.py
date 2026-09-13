"""Operation-stage certificate and scheduling through the public compiler."""
from dataclasses import replace

import pytest

from kir import compile_program
from kir.authoring import _EMITTERS
from kir.tests.fixtures import GROUND_SNAPSHOT
from kir.translation_cert import certify_op


def program(kind="create_wall"):
    level = {"by": "element_id", "value": 42}
    if kind == "create_wall":
        op = {"op": kind, "id": "made", "p0_mm": [0, 0], "p1_mm": [6000, 0], "level": level}
    elif kind == "create_floor":
        op = {"op": kind, "id": "made", "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "level": level}
    elif kind == "create_floor_by_contour":
        op = {"op": kind, "id": "made", "contour": {"outer": {"shape": "poly",
              "points_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}}, "level": level}
    else:
        op = {"op": "change_type", "id": "made", "target": {"by": "element_id", "value": 9000},
              "type": {"by": "element_id", "value": 100}}
    return {"ir_version": "1.0", "ops": [op]}


@pytest.mark.parametrize("kind", ["create_wall", "create_floor", "create_floor_by_contour", "change_type"])
@pytest.mark.parametrize("mutation", ["delete", "wrong_stage"])
def test_certificate_requires_assignment_on_the_operation_stage(monkeypatch, kind, mutation):
    result = compile_program(program(kind), snapshot=GROUND_SNAPSHOT, revit_version="2023")
    assert result.ok, result.diagnostics
    op = result.grounded_ops[0]
    assert certify_op(op, "2023").proven
    original = _EMITTERS[kind]

    def changed(*args, **kwargs):
        decl, create, checks, readback = original(*args, **kwargs)
        if mutation == "delete":
            checks = [check for check in checks if check.obligation_key != "type_assignment"]
            # Sole-stage change_type still has to return a nonempty checked
            # carrier. Keep an unrelated real predicate rather than relaxing
            # the renderer's empty-list refusal for this mutation control.
            if not checks:
                witness = original(*args, **kwargs)[2][0]
                checks = [replace(witness, obligation_key="unrelated")]
        else:
            checks = [replace(check, stage="final") if check.obligation_key == "type_assignment"
                      else check for check in checks]
        return decl, create, checks, readback

    monkeypatch.setitem(_EMITTERS, kind, changed)
    certificate = certify_op(op, "2023")
    assert not certificate.proven
    assert any(clause.required and not clause.discharged and "type" in clause.clause for clause in certificate.clauses)


@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_actual_program_checks_each_assignment_before_later_change(isolation):
    data = program()
    data["ops"] += [{"op": "change_type", "id": key, "target": {"by": "ref", "value": "made"},
                     "type": {"by": "element_id", "value": value}}
                    for key, value in (("first", 100), ("second", 101))]
    result = compile_program(data, snapshot=GROUND_SNAPSHOT, revit_version="2023", isolation=isolation)
    assert result.ok, result.diagnostics
    code = result.csharp
    assert (code.index("// create_wall made") < code.index("// operation made")
            < code.index("// change_type first") < code.index("// operation first")
            < code.index("// change_type second") < code.index("// operation second")
            < code.index("// post made") < code.index("// witness made"))
    assert "// post first" not in code and "// post second" not in code
    for key in ("made", "first", "second"):
        assert code.count("// operation " + key) == 1
        if isolation == "per_op":
            assert code.index("// operation " + key) < code.index("__st_" + key + ".Commit()")
        assert certify_op(next(op for op in result.grounded_ops if op["id"] == key), "2023").proven
