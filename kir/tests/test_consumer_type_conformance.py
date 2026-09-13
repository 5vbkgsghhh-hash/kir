"""Consumer type-assignment stages compile against real 2021–2026 API refs.

No generated assembly is loaded/executed. Runtime acceptance of requested and
observed type IDs belongs to the separate behavioral/live test lanes.
"""
from copy import deepcopy

import pytest

from kir import compile_program
from kir.revit_connector import wrap_connector_source
from kir.tests.fixtures import GROUND_SNAPSHOT
from kir.tests.test_emitter_scope_contract import PROGRAMS
from kir.tests.test_type_creation_conformance import VERSIONS, type_conformance_runner


def consumer_programs():
    wall_type = GROUND_SNAPSHOT["wall_types"][0]
    other_wall = GROUND_SNAPSHOT["wall_types"][1]
    floor_type = GROUND_SNAPSHOT["floor_types"][0]
    level = {"by": "element_id", "value": GROUND_SNAPSHOT["levels"][0]["id"]}
    wall = {"op": "create_wall", "id": "wall", "p0_mm": [0, 0], "p1_mm": [6000, 0],
            "height_mm": 3000, "level": level}
    floor = {"op": "create_floor", "id": "floor", "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "level": level, "height_offset_mm": 50}
    for selection in ("default", "name", "element_id", "ref"):
        w, f = deepcopy(wall), deepcopy(floor)
        prefix = []
        if selection == "ref":
            for kind, source in (("wall", wall_type), ("floor", floor_type)):
                prefix.append({"op": "create_wall_type", "id": kind + "-type", "host_kind": kind,
                    "source_type": {"by": "element_id", "value": source["id"]},
                    "new_name": "KIR consumer " + kind,
                    "layers": [{"width_mm": 200, "function": "Structure", "material": "Бетон М300"}]})
            w["type"], f["type"] = ({"by": "ref", "value": kind + "-type"} for kind in ("wall", "floor"))
        elif selection != "default":
            key = "name" if selection == "name" else "id"
            w["type"] = {"by": selection, "value": wall_type[key]}
            f["type"] = {"by": selection, "value": floor_type[key]}
        yield "wall-floor-" + selection, {"ops": [*prefix, w, f]}
    w = deepcopy(wall)
    w["type"] = {"by": "element_id", "value": wall_type["id"]}
    yield "change-type-chain", {"ops": [w,
        {"op": "change_type", "id": "change-1", "target": {"by": "ref", "value": "wall"},
         "type": {"by": "element_id", "value": other_wall["id"]}},
        # change_type is not a ref-producing CREATE operation in this language.
        {"op": "change_type", "id": "change-2", "target": {"by": "ref", "value": "wall"},
         "type": {"by": "element_id", "value": wall_type["id"]}}]}
    # Reuse the existing trusted pre-grounded group fixture unchanged.
    yield "native-group-existing-fixture", deepcopy(PROGRAMS["native_group"])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_consumer_selection_change_chain_and_group_compile(version, isolation, type_conformance_runner):
    cases = list(consumer_programs())
    sources = []
    for name, program in cases:
        result = compile_program(program, revit_version=version, snapshot=GROUND_SNAPSHOT, isolation=isolation)
        assert result.ok, (name, version, isolation, result.diagnostics)
        assert result.txn_isolation == isolation
        assert "type assignment mismatch or unavailable (operation)" in result.csharp
        assert '"operation_end_before_commit"' in result.csharp
        if name.startswith("wall-floor-") and version == "2021":
            assert "doc.Create.NewFloor(" in result.csharp
        sources.append(wrap_connector_source(result.csharp))
    failures = [(name, row) for (name, _), row in zip(cases, type_conformance_runner(version, sources), strict=True)
                if row["ok"] is not True or row["assembly_bytes"] <= 0]
    assert not failures, (version, isolation, failures)


@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_2021_hole_free_floor_contour_type_assignment_compiles(isolation, type_conformance_runner):
    program = {"ops": [{"op": "create_floor_by_contour", "id": "legacy-contour-floor",
        "contour": {"outer": {"shape": "poly", "points_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}},
        "level": {"by": "element_id", "value": GROUND_SNAPSHOT["levels"][0]["id"]},
        "type": {"by": "element_id", "value": GROUND_SNAPSHOT["floor_types"][0]["id"]}}]}
    result = compile_program(program, revit_version="2021", snapshot=GROUND_SNAPSHOT, isolation=isolation)
    assert result.ok, (isolation, result.diagnostics)
    assert result.txn_isolation == isolation
    assert "doc.Create.NewFloor(" in result.csharp
    assert "type assignment mismatch or unavailable (operation)" in result.csharp
    assert '"operation_end_before_commit"' in result.csharp
    row, = type_conformance_runner("2021", [wrap_connector_source(result.csharp)])
    assert row["ok"] is True and row["assembly_bytes"] > 0, (isolation, row)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_room_original_identity_capture_compiles_without_floor_hole_version_gate(version, isolation, type_conformance_runner):
    program = {"ops": [{"op": "create_room", "id": "room-capture", "xy": [2500, 2000],
        "name": "Room capture reference-compile control",
        "level": {"by": "element_id", "value": GROUND_SNAPSHOT["levels"][0]["id"]}}]}
    result = compile_program(program, revit_version=version, snapshot=GROUND_SNAPSHOT, isolation=isolation)
    assert result.ok, (version, isolation, result.diagnostics)
    assert "doc.Create.NewRoom(" in result.csharp
    assert '"element_identity_status"' in result.csharp
    assert result.csharp.index("__t.Commit()") < result.csharp.index('"element_identity_status"')
    row, = type_conformance_runner(version, [wrap_connector_source(result.csharp)])
    assert row["ok"] is True and row["assembly_bytes"] > 0, (version, isolation, row)
