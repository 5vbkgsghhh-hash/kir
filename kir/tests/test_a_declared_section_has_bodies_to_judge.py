"""Bodies for clash come from the program's own declarations, not only a document.

🔴 WHAT THE TEAM REHEARSAL ACTUALLY MEASURED (13.09.2026). Its report said
`bodies_in_program: 0` and concluded "walls and columns are not materialised in
OCCT". Both halves were wrong, and the second one mattered: that number was
produced by the rehearsal's OWN harness counting four op names
(`create_directshape`, `create_solid_blend`, `create_solid_boolean`,
`create_solid_extrusion`); `kir/clash` was never called. The product says
otherwise — `body_making_ops()` names 32 ops of 83 and BOTH `create_wall` and
`create_column` are among them.

What was really missing had a name the product printed all along, and it moved
as each cause was removed:

    no snapshot                 -> {"no_snapshot": 3}
    with a snapshot             -> {"level_elevation_unknown": 2, "symbol_not_declared": 1}
    after the fix below         -> {"wall_type_not_in_snapshot": 2, "symbol_not_declared": 1}
    with a type that has a section -> {} and the bodies exist

THE FIX THIS FILE GUARDS: elevations were read ONLY from the snapshot, so a wall
standing on a `create_level` of the SAME pack came back `level_elevation_unknown`
and got no body. A program declaring its own levels was carrying the number the
geometry needed the whole time.
"""
import copy

import pytest

from kir import clash_bundle
from kir.tests.fixtures import GROUND_SNAPSHOT


def _snapshot_with_wall_section():
    snapshot = copy.deepcopy(GROUND_SNAPSHOT)
    snapshot["wall_types"][1]["section"] = {"kind": "plate", "thickness_mm": 200.0,
                                            "uniform": True, "source": "test"}
    return snapshot, snapshot["wall_types"][1]["name"]


def _wall(index, p0, p1, type_name):
    return {"op": "create_wall", "id": f"w{index}", "p0_mm": p0, "p1_mm": p1,
            "height_mm": 3000, "level": {"by": "ref", "value": "L"},
            "type": {"by": "name", "value": type_name}}


def test_walls_on_a_level_the_program_declares_get_bodies():
    """The regression this fix exists for: `{by: ref}` to the pack's own level."""
    snapshot, type_name = _snapshot_with_wall_section()
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Этаж 1"},
                       _wall(0, [0, 0], [6000, 0], type_name),
                       _wall(1, [3000, -2000], [3000, 2000], type_name)]}
    geometry = clash_bundle.bundle_elements([program], snapshot=snapshot)
    bodies = [e for e in geometry.elements if "prism" in e or "bbox_min_mm" in e]
    assert len(bodies) == 2, geometry.no_geometry
    assert geometry.no_geometry == {}, geometry.no_geometry
    assert "level_elevation_unknown" not in geometry.no_geometry


def test_a_level_declared_by_the_program_is_enough_even_without_a_snapshot():
    """"There is no document" and "the document is silent about this level" are
    different facts, and a program that declares its own level has answered the
    second one itself."""
    _, type_name = _snapshot_with_wall_section()
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Этаж 1"},
                       _wall(0, [0, 0], [6000, 0], type_name)]}
    geometry = clash_bundle.bundle_elements([program], snapshot=None)
    assert "no_snapshot" not in geometry.no_geometry, geometry.no_geometry
    assert "level_elevation_unknown" not in geometry.no_geometry, geometry.no_geometry


def test_the_document_wins_when_both_name_the_same_level():
    """A program cannot redefine an elevation the document already owns."""
    snapshot, type_name = _snapshot_with_wall_section()
    existing = snapshot["levels"][0]
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 999999.0,
                        "name": existing["name"]},
                       _wall(0, [0, 0], [6000, 0], type_name)]}
    context = clash_bundle._with_program_levels(
        clash_bundle.SnapshotSections.from_snapshot(snapshot), [program])
    assert context.level_mm({"by": "name", "value": existing["name"]}) == \
        pytest.approx(existing["elevation_mm"])


def test_both_walls_and_columns_are_body_making_ops():
    """The rehearsal's conclusion, checked against the registry instead of a
    hand-written list of four op names."""
    making = clash_bundle.body_making_ops()
    assert "create_wall" in making and "create_column" in making
    assert len(making) + len(clash_bundle.OP_NO_BODY) == 83


@pytest.mark.parametrize("missing,expected", [
    ({}, "symbol_not_declared"),
    ({"symbol": {"by": "name", "value": "нет такого"}}, "symbol_not_in_snapshot"),
])
def test_a_column_names_the_next_thing_it_lacks(missing, expected):
    """A column's body needs data only a type carries, and the refusal names WHICH.

    Walked live 13.09 one step at a time: `symbol_not_declared` →
    `symbol_not_in_snapshot` → `symbol_has_no_structural_section` →
    `column_top_unbound` → `symbol_local_extent_unknown`. Each is a real missing
    datum, and naming them one at a time is the product working, not failing:
    inventing a cross-section would put a body in the model that Revit will not
    build.
    """
    snapshot, _ = _snapshot_with_wall_section()
    column = {"op": "create_column", "id": "c0", "xy": [3000, 0],
              "level": {"by": "ref", "value": "L"}, **missing}
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Этаж 1"},
                       column]}
    geometry = clash_bundle.bundle_elements([program], snapshot=snapshot)
    assert expected in geometry.no_geometry, geometry.no_geometry


def _clash(program, snapshot):
    """The real judge, not the body builder.

    `bundle_elements` gathers BODIES; whether two of them overlap is decided by
    `bundle_clash_report`. The rehearsal never reached either, and its
    `bodies_in_program: 0` was read as "clash has nothing to look at". It has.
    """
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"KIR_CLASH": "1"}):
        return clash_bundle.bundle_clash_report([program], snapshot=snapshot)


def _two_walls(second_axis):
    snapshot, type_name = _snapshot_with_wall_section()
    program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Этаж 1"},
                       _wall(0, [0, 0], [6000, 0], type_name),
                       _wall(1, second_axis[0], second_axis[1], type_name)]}
    return program, snapshot


def test_a_provoked_crossing_is_found_and_both_elements_are_addressed():
    """Two 200 mm walls crossing at (3000, 0): one finding, both ids named."""
    program, snapshot = _two_walls(([3000, -2000], [3000, 2000]))
    report = _clash(program, snapshot)
    assert report is not None and report["status"] == "ok", report
    assert report["bodies_bundle"] == 2 and report["without_body"] == 0
    assert report["pairs_compared"] == 1
    assert report["overlaps"] == 1 and report["total_findings"] == 1
    finding, = report["findings"]
    assert {finding["a_element_id"], finding["b_element_id"]} == {"p1/w0", "p1/w1"}, finding
    assert finding["finding_id"] == "p1/w0~p1/w1"
    assert finding["rule_id"] == "structure_meets_structure_overlap"
    # The rule is NAMED and its action is named too: two structures overlapping
    # is ordinary in cast-in-place work, so the finding asks the author to say
    # more, it does not order anyone to move anything.
    assert report["rules"][finding["rule_id"]]
    assert report["rung_actions"][finding["rung"]]


def test_walls_that_do_not_touch_produce_no_finding():
    """The control. Without it "one finding" proves only that findings exist."""
    program, snapshot = _two_walls(([0, 5000], [6000, 5000]))
    report = _clash(program, snapshot)
    assert report is not None and report["status"] == "ok", report
    assert report["bodies_bundle"] == 2 and report["pairs_compared"] == 1
    assert report["overlaps"] == 0 and report["total_findings"] == 0
    assert report["findings"] == []


def test_the_judge_is_silent_when_the_flag_is_off():
    """`None` means exactly one thing — the switch is off — and nothing else."""
    program, snapshot = _two_walls(([3000, -2000], [3000, 2000]))
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"KIR_CLASH": "0"}):
        assert clash_bundle.bundle_clash_report([program], snapshot=snapshot) is None

