"""Typed section dependency closure -> actual policy/compiler, never Revit.

Uses the same explicitly configured, prebuilt CompilerConformance runner as the
type-factory lane. Revit 2021 must refuse the existing floor holes; preserving
those holes is more important than manufacturing a green compatibility claim.
"""
from collections import Counter

import pytest

from kir import compile_program
from kir.project_selection import selected_instance_program
from kir.revit_connector import wrap_connector_source
from kir.tests.fixtures import GROUND_SNAPSHOT
from kir.tests.test_type_creation_conformance import VERSIONS, type_conformance_runner


@pytest.fixture(scope="module")
def typed_section_program():
    from examples.residential_project import concept
    from examples.residential_refinement import develop_section
    from examples.residential_typed_section import add_section_types

    source = concept()
    base = develop_section(source, height_mm=4200., setback_mm=1800.)
    typed = add_section_types(base, source=source, expected_revision=base.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id", "value": GROUND_SNAPSHOT["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id", "value": GROUND_SNAPSHOT["floor_types"][0]["id"]})
    program = selected_instance_program(typed, "tower-a")
    assert len(program["ops"]) == 23
    assert Counter(op["op"] for op in program["ops"]) == {
        "create_wall_type": 2, "create_level": 3, "create_wall": 12,
        "create_floor_by_contour": 3, "create_room": 3,
    }
    types = {op["host_kind"]: op for op in program["ops"] if op["op"] == "create_wall_type"}
    assert [op["host_kind"] for op in program["ops"][:2]] == ["wall", "floor"]
    for op in program["ops"]:
        if op["op"] in ("create_wall", "create_floor_by_contour"):
            kind = "wall" if op["op"] == "create_wall" else "floor"
            assert op["type"] == {"by": "ref", "value": types[kind]["id"]}
        if op["op"] == "create_floor_by_contour":
            assert len(op["contour"]["holes"]) == 1
    return program


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_complete_typed_section_under_real_compiler_policy(version, isolation, type_conformance_runner,
                                                         typed_section_program):
    result = compile_program(typed_section_program, revit_version=version,
                             snapshot=GROUND_SNAPSHOT, isolation=isolation)
    if version == "2021":
        assert result.ok is False and result.csharp is None
        floors = {op["id"] for op in typed_section_program["ops"] if op["op"] == "create_floor_by_contour"}
        assert result.diagnostics
        assert all(d.code == "KIR-E003" and d.field_name == "contour.holes" and d.op_id in floors
                   for d in result.diagnostics), result.diagnostics
        return
    assert result.ok, (version, isolation, result.diagnostics)
    assert result.txn_isolation == isolation
    row, = type_conformance_runner(version, [wrap_connector_source(result.csharp)])
    assert row["ok"] is True and row["assembly_bytes"] > 0, (version, isolation, row)
