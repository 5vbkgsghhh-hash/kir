"""Public Python envelopes carry native identity without creating new semantics."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from kir import dsl, sdk
from kir.compiler import compile_program, plan_program
from kir.schema_gen import program_schema
from kir.tests.test_a_stable_address_is_not_permission import WALL_TYPE, owners


def program(lineage=None):
    value = {"ir_version": "1.0", "ops": [deepcopy(WALL_TYPE)]}
    if lineage is not None:
        value["lineage"] = lineage
    return value


def authored(kind, lineage):
    if kind == "sdk":
        value = sdk.program(lineage=lineage)
        value.add(deepcopy(WALL_TYPE))
        return value.to_dict()
    with dsl.program(lineage=lineage) as value:
        dsl.create_wall_type(**{k: v for k, v in WALL_TYPE.items() if k != "op"})
    return value.build()


@pytest.mark.parametrize("kind", ["sdk", "dsl"])
@pytest.mark.parametrize("lineage", [None, "residential"])
@pytest.mark.parametrize("version", ["2023", "2026"])
def test_python_dict_and_typed_plan_have_identical_native_source(kind, lineage, version):
    expected = program(lineage)
    actual = authored(kind, lineage)
    assert actual == expected
    direct = compile_program(expected, revit_version=version)
    typed = compile_program(plan_program(actual), revit_version=version)
    assert direct.ok and typed.ok
    assert direct.csharp == typed.csharp
    assert typed.planned.evidence_schema == ("kir-planned-program/5" if lineage else "kir-planned-program/4")
    if lineage:
        assert owners(typed.csharp) == ["kir:pae373ebf:WT1"]
    else:
        assert "lineage" not in typed.planned.to_evidence_dict()


@pytest.mark.parametrize("kind", ["sdk", "dsl"])
@pytest.mark.parametrize("bad", ["", 0, False, {}, [], "residential\n", "residential\r", "x" * 65])
def test_invalid_supplied_lineage_reaches_the_compiler_unchanged(kind, bad):
    value = authored(kind, bad)
    assert value["lineage"] == bad and type(value["lineage"]) is type(bad)
    compiled = compile_program(value)
    assert not compiled.ok
    assert any(d.code == "KIR-T001" and d.field_name == "lineage" for d in compiled.diagnostics)


def test_constructors_assignment_and_dsl_envelope_preserve_explicit_identity():
    raw = sdk.Program(lineage="initial")
    raw.add(deepcopy(WALL_TYPE))
    compiled = raw.compile(version="2023")
    assert compiled.ok and compiled.planned.lineage == "initial"
    raw.lineage = ""
    assert raw.to_dict()["lineage"] == "" and not raw.compile().ok
    raw.lineage = None
    assert "lineage" not in raw.to_dict()
    explicit = dsl.Program(lineage="initial")
    assert explicit.build()["lineage"] == "initial"
    explicit.envelope(lineage="next")
    assert explicit.build()["lineage"] == "next"
    explicit.envelope(lineage=None)
    assert "lineage" not in explicit.build()
    with dsl.program():
        dsl.envelope(lineage="residential")
        dsl.create_wall_type(**{k: v for k, v in WALL_TYPE.items() if k != "op"})
        assert dsl.build() == program("residential")


def test_dsl_plan_keeps_identity_through_its_default_bulk_boundary():
    with dsl.program(lineage="residential") as value:
        dsl.create_wall_type(**{k: v for k, v in WALL_TYPE.items() if k != "op"})
        planned = value.plan()
    assert planned.bulk and planned.lineage == "residential"
    compiled = compile_program(planned, bulk=True)
    assert compiled.ok and owners(compiled.csharp) == ["kir:pae373ebf:WT1"]


def test_schema_lineage_pattern_uses_portable_absolute_end_in_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the independent ECMAScript regexp check")
    schema = program_schema()["properties"]["lineage"]
    values = ["residential", "a.b:c-d_1", "", "owner\n", "owner\r", "owner\u2028", "a b"]
    result = subprocess.run([node, "-e", "const d=JSON.parse(process.argv[1]);"
        "process.stdout.write(JSON.stringify(d.values.map(x=>new RegExp(d.pattern).test(x))));",
        json.dumps({"pattern": schema["pattern"], "values": values})],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [True, True, False, False, False, False, False]
