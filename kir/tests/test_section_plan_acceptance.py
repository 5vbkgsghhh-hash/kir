"""Actual planned/lineage-bound mistakes detected by independent XY predicates."""
from dataclasses import replace
import json
import math
from pathlib import Path

import pytest

from examples import residential_project as towers, residential_refinement as workflow
from kir.compiler import plan_program
from kir.project import NamedOutput, ProjectRevision, _canonical, _thaw, output_id
from kir.project_refinement import refinement_view
from kir.project_store import ProjectStore
from kir.section_plan_acceptance import SectionPlanError, assess_section_plan_change


CHAIN = [f"storey-{index:02d}-slab" for index in (1, 2, 3)]
PROTECTED = ["tower-b", "tower-c"]
ROLES = {"create_level": "level", "create_floor_by_contour": "slab", "create_wall": "wall", "create_room": "space"}


@pytest.fixture(scope="module")
def snapshots():
    source = towers.concept()
    before = workflow.develop_section(source)
    proposed = workflow.develop_section(before, source=source, height_mm=4500., setback_mm=1200.)
    return source, before, proposed


def assess(snapshots, proposed=None, **kwargs):
    source, before, normal = snapshots
    args = dict(source=source, instance_key="tower-a", required_void_chain=CHAIN, protected_instances=PROTECTED)
    args.update(kwargs)
    return assess_section_plan_change(before, proposed or normal, **args).to_dict()


def mutate(project, key, update):
    instance = project.instances[0]
    outputs = []
    for out in instance.outputs:
        operation = _thaw(out.operation)
        if out.key == key:
            update(operation)
        outputs.append(replace(out, operation=operation))
    return project.replace_instance(replace(instance, outputs=outputs), expected_revision=project.revision_id)


def replace_outputs(project, outputs):
    instance = project.instances[0]
    metadata = _thaw(instance.metadata)
    metadata["refinement"]["members"] = [{"output_key": output.key, "role": ROLES[output.operation["op"]]} for output in outputs]
    return project.replace_instance(replace(instance, outputs=outputs, metadata=metadata), expected_revision=project.revision_id)


def rows(data, predicate, status=None):
    return [row for row in data["rows"] if row["predicate"] == predicate and (status is None or row["status"] == status)]


def actual_plan(project):
    return plan_program({"ir_version": project.ir_version, "ops": [dict(_thaw(out.operation),
        id=output_id(project.project_id, "tower-a", out.key)) for out in project.instances[0].outputs]})


def test_real_height_setback_change_measures_only_named_xy_predicates(snapshots):
    source, before, proposed = snapshots
    result = assess(snapshots)
    assert result["before_revision_id"] == before.revision_id
    assert result["proposed_revision_id"] == proposed.revision_id
    assert result["source"]["revision_id"] == source.revision_id
    assert result["chain_elevations_mm"] == {"before": [0, 3600, 7200], "proposed": [0, 4500, 9000]}
    assert len(result["expected_subjects"]["outputs"]) == 21
    assert len(result["expected_subjects"]["rooms"]) == 3
    assert len(rows(result, "room_axis_enclosure", "evaluated")) == 3
    assert len(rows(result, "room_seed_in_slab_xy_region", "evaluated")) == 3
    assert len(rows(result, "selected_void_footprint_retained", "evaluated")) == 3
    assert len(rows(result, "selected_void_chain_xy_continuity", "evaluated")) == 2
    assert not [row for row in result["rows"] if row["status"] == "violated"]
    assert len([row for row in result["rows"] if row["status"] == "not_evaluated"]) == 6
    assert not any(key in result for key in ("ok", "pass", "accepted", "safe"))
    assert result["native_execution"] == result["recipe_execution"] == "not_run"
    assert result["ancestry"] == "not_checked"


@pytest.mark.parametrize("case,predicate", [("wall_gap", "room_axis_enclosure"),
    ("room_in_shaft", "room_seed_in_slab_xy_region"), ("shaft_shift", "selected_void_chain_xy_continuity")])
def test_three_actual_geometry_counterexamples_pass_planner_and_lineage_but_fail_predicates(snapshots, case, predicate):
    source, _, proposed = snapshots
    if case == "wall_gap":
        bad = mutate(proposed, "storey-02-wall-0", lambda op: op["p1_mm"].__setitem__(0, 13000.))
    elif case == "room_in_shaft":
        bad = mutate(proposed, "storey-02-space", lambda op: op.update(xy=[6000., 4000.]))
    else:
        bad = mutate(proposed, "storey-02-slab", lambda op: [p.__setitem__(0, p[0] + 3000.)
            for p in op["contour"]["holes"][0]["points_mm"]])
    assert actual_plan(bad).ops
    assert refinement_view(bad, "tower-a", source=source)["binding_status"] == "exact_supplied_source"
    result = assess(snapshots, bad)
    assert rows(result, predicate, "violated")
    assert len(result["expected_subjects"]["rooms"]) == 3
    assert result["expected_subjects"]["void_chain"] == CHAIN
    if case == "wall_gap":
        assert len(rows(result, predicate, "evaluated")) == 2
    elif case == "room_in_shaft":
        assert len(rows(result, "room_axis_enclosure", "evaluated")) == 3
        assert rows(result, predicate, "violated")[0]["evidence"]["floor_key"] == "storey-02-slab"
    else:
        assert len(rows(result, "room_axis_enclosure", "evaluated")) == 3
        assert len(rows(result, "room_seed_in_slab_xy_region", "evaluated")) == 3
        assert [row["evidence"]["symmetric_difference_mm2"] for row in rows(result, predicate)] == [8000000., 8000000.]


@pytest.mark.parametrize("key,offset", [("storey-02-wall-0", 500.), ("storey-02-slab", -250.)])
def test_nonzero_offsets_cannot_qualify_vertical_or_native_axes(snapshots, key, offset):
    field = "base_offset_mm" if "wall" in key else "height_offset_mm"
    proposed = mutate(snapshots[2], key, lambda op: op.update({field: offset}))
    result = assess(snapshots, proposed)
    assert len(rows(result, "room_axis_enclosure", "evaluated")) == 3  # XY-only, not absolute Z evidence.
    for predicate in ("vertical_placement", "room_boundary_excludes_slab_holes", "native_realization", "structural_safety"):
        assert [row["status"] for row in rows(result, predicate)] == ["not_evaluated"]


@pytest.mark.parametrize("key", ["storey-02-space", "storey-02-slab", "storey-02-wall-0"])
def test_missing_proposed_subject_never_disappears_from_denominator(snapshots, key):
    bad = replace_outputs(snapshots[2], [out for out in snapshots[2].instances[0].outputs if out.key != key])
    result = assess(snapshots, bad)
    assert key in result["expected_subjects"]["outputs"]
    assert next(row for row in rows(result, "named_subject_retained") if row["subject"] == key)["status"] == "violated"
    assert len(result["expected_subjects"]["rooms"]) == 3
    if "space" in key:
        assert next(row for row in rows(result, "room_axis_enclosure") if row["subject"] == key)["reason"] == "expected_room_missing"
    if "slab" in key:
        assert rows(result, "selected_void_chain_xy_continuity", "violated")


@pytest.mark.parametrize("kind", ["room", "floor", "wall"])
def test_unknown_level_selectors_do_not_guess_by_name_or_skip_geometry(snapshots, kind):
    key = {"room": "storey-02-space", "floor": "storey-02-slab", "wall": "storey-02-wall-0"}[kind]
    # This name actually names an authored level. The qualified consumer still
    # requires an exact by:ref, not the spatial reader's name lookup fallback.
    proposed = mutate(snapshots[2], key, lambda op: op.update(level={"by": "name", "value": "tower-a: этаж 2"}))
    result = assess(snapshots, proposed)
    if kind == "floor":
        assert len(rows(result, "room_seed_in_slab_xy_region", "not_evaluated")) == 3
        assert len(rows(result, "selected_void_chain_xy_continuity", "not_evaluated")) == 2
    else:
        assert len(rows(result, "room_axis_enclosure", "not_evaluated")) == 3
    assert len(result["expected_subjects"]["rooms"]) == 3


def test_wrong_room_level_association_is_seen_from_actual_refs_not_output_name(snapshots):
    proposed = mutate(snapshots[2], "storey-02-space", lambda op: op.update(level={"by": "ref",
        "value": output_id(snapshots[2].project_id, "tower-a", "storey-01-level")}))
    result = assess(snapshots, proposed)
    assert len(rows(result, "room_axis_enclosure", "violated")) == 2
    row = next(r for r in rows(result, "room_seed_in_slab_xy_region") if r["subject"] == "storey-02-space")
    assert row["evidence"]["floor_key"] == "storey-01-slab"


def test_multiple_slabs_on_same_level_are_not_arbitrarily_chosen(snapshots):
    proposed = snapshots[2]
    floor = next(out for out in proposed.instances[0].outputs if out.key == "storey-02-slab")
    bad = replace_outputs(proposed, [*proposed.instances[0].outputs, replace(floor, key="extra-floor")])
    result = assess(snapshots, bad)
    row = next(r for r in rows(result, "room_seed_in_slab_xy_region") if r["subject"] == "storey-02-space")
    assert row["status"] == "not_evaluated" and row["reason"] == "slab_association_not_unique"
    assert set(row["evidence"]["candidate_floor_keys"]) == {"storey-02-slab", "extra-floor"}


def test_room_point_on_slab_hole_boundary_is_not_interior(snapshots):
    bad = mutate(snapshots[2], "storey-02-space", lambda op: op.update(xy=[5000., 4000.]))
    assert len(rows(assess(snapshots, bad), "room_seed_in_slab_xy_region", "violated")) == 1


def test_multiple_holes_do_not_become_an_implicitly_chosen_shaft(snapshots):
    bad = mutate(snapshots[2], "storey-02-slab", lambda op: op["contour"]["holes"].append({
        "shape": "poly", "points_mm": [[9000, 3000], [10000, 3000], [10000, 4000], [9000, 4000]]}))
    result = assess(snapshots, bad)
    assert len(rows(result, "selected_void_chain_xy_continuity", "not_evaluated")) == 2
    assert rows(result, "selected_void_footprint_retained", "not_evaluated")[0]["reason"] == "exactly_one_explicit_void_required"


def test_removing_a_known_required_shaft_is_a_violation_not_an_unknown(snapshots):
    source, _, proposed = snapshots
    bad = mutate(proposed, "storey-02-slab", lambda op: op["contour"].update(holes=[]))
    assert actual_plan(bad).ops
    assert refinement_view(bad, "tower-a", source=source)
    result = assess(snapshots, bad)
    retained = next(row for row in rows(result, "selected_void_footprint_retained") if row["subject"] == "storey-02-slab")
    assert retained["status"] == "violated" and retained["reason"] == "selected_void_missing"
    adjacent = rows(result, "selected_void_chain_xy_continuity")
    assert len(adjacent) == 2
    assert all(row["status"] == "violated" and row["reason"] == "selected_void_missing" for row in adjacent)


def test_absent_baseline_void_is_unqualified_not_invented(snapshots):
    source, before, proposed = snapshots
    before = mutate(before, "storey-02-slab", lambda op: op["contour"].update(holes=[]))
    proposed = mutate(proposed, "storey-02-slab", lambda op: op["contour"].update(holes=[]))
    result = assess((source, before, proposed))
    retained = next(row for row in rows(result, "selected_void_footprint_retained") if row["subject"] == "storey-02-slab")
    assert retained["status"] == "not_evaluated" and retained["reason"] == "no_void_in_floor"
    assert all(row["status"] == "not_evaluated" for row in rows(result, "selected_void_chain_xy_continuity"))


@pytest.mark.parametrize("kind", ["wall", "floor"])
def test_legal_curves_are_named_unqualified_not_straightened(snapshots, kind):
    if kind == "wall":
        bad = mutate(snapshots[2], "storey-02-wall-0", lambda op: op.update(
            p0_mm=[0., 0.], p1_mm=[14000., 0.], arc={"curve_type": "Arc", "center_mm": [7000., 0., 0.],
                "radius_mm": 7000., "x_axis": [1., 0., 0.], "y_axis": [0., 1., 0.],
                "start_angle_rad": math.pi, "end_angle_rad": 2 * math.pi}))
    else:
        bad = mutate(snapshots[2], "storey-02-slab", lambda op: op["contour"]["holes"][0].update(
            arcs=[{"edge": 0, "bulge": .2}]))
    assert actual_plan(bad).ops
    result = assess(snapshots, bad)
    if kind == "wall":
        assert len(rows(result, "room_axis_enclosure", "not_evaluated")) == 3
    else:
        assert len(rows(result, "room_seed_in_slab_xy_region", "not_evaluated")) == 1
        assert len(rows(result, "selected_void_chain_xy_continuity", "not_evaluated")) == 2


def test_fifty_mm_gap_is_not_silently_healed_by_existing_default_extension(snapshots):
    bad = mutate(snapshots[2], "storey-02-wall-0", lambda op: op["p1_mm"].__setitem__(0, 13950.))
    assert len(rows(assess(snapshots, bad), "room_axis_enclosure", "violated")) == 1


def test_generator_parameters_are_not_the_geometric_oracle(snapshots):
    proposed = snapshots[2]
    before = assess(snapshots)
    instance = proposed.instances[0]
    changed = proposed.replace_instance(replace(instance, parameters=dict(instance.parameters,
        width_mm=999., depth_mm=998., storey_height_mm=777.)), expected_revision=proposed.revision_id)
    # These intentionally inconsistent recipe assertions remain possible drafts.
    # XY predicates read actual outputs, not what the recipe would regenerate.
    after = assess(snapshots, changed)
    assert after["rows"] == before["rows"]
    assert after["section_program_digests"] == before["section_program_digests"]
    assert after["recipe_execution"] == "not_run"


def test_no_room_subjects_are_unevaluated_not_vacuously_successful(snapshots):
    source, before, proposed = snapshots
    before = replace_outputs(before, [out for out in before.instances[0].outputs if out.operation["op"] != "create_room"])
    proposed = replace_outputs(proposed, [out for out in proposed.instances[0].outputs if out.operation["op"] != "create_room"])
    result = assess((source, before, proposed))
    assert result["expected_subjects"]["rooms"] == []
    for predicate in ("room_axis_enclosure", "room_seed_in_slab_xy_region"):
        assert rows(result, predicate)[0]["status"] == "not_evaluated"
        assert rows(result, predicate)[0]["reason"] == "no_expected_room_subjects"


def test_equivalent_ring_order_is_geometric_equality_not_vertex_string_equality(snapshots):
    def rotate_reverse(op):
        ring = op["contour"]["holes"][0]["points_mm"]
        op["contour"]["holes"][0]["points_mm"] = list(reversed(ring[1:] + ring[:1]))
    bad = mutate(snapshots[2], "storey-02-slab", rotate_reverse)
    result = assess(snapshots, bad)
    assert not rows(result, "selected_void_footprint_retained", "violated")
    assert not rows(result, "selected_void_chain_xy_continuity", "violated")


@pytest.mark.parametrize("chain", [[], CHAIN[:1], [CHAIN[0], CHAIN[0]], list(reversed(CHAIN)),
    [CHAIN[0], "storey-02-space"], [CHAIN[0], "absent"], "not-a-sequence", [None, CHAIN[1]]])
def test_malformed_caller_void_policy_has_named_refusal(snapshots, chain):
    with pytest.raises(SectionPlanError, match="invalid_section_policy"):
        assess(snapshots, required_void_chain=chain)


@pytest.mark.parametrize("value", [[], ["tower-a"], ["unknown"], ["tower-b", "tower-b"]])
def test_protected_policy_does_not_guess_or_protect_edited_instance(snapshots, value):
    if value == []:
        assert rows(assess(snapshots, protected_instances=value), "protected_instance_snapshot") == []
    else:
        with pytest.raises(SectionPlanError, match="invalid_section_policy"):
            assess(snapshots, protected_instances=value)


@pytest.mark.parametrize("case", ["missing", "metadata", "geometry"])
def test_protected_instance_whole_snapshot_changes_are_visible(snapshots, case):
    proposed = snapshots[2]
    if case == "missing":
        bad = proposed.with_instances([item for item in proposed.instances if item.key != "tower-b"], expected_revision=proposed.revision_id)
    else:
        tower = proposed.instances[1]
        changed = replace(tower, metadata={"changed": True}) if case == "metadata" else towers.instance(tower.key, dict(tower.parameters, twist_deg=20))
        bad = proposed.replace_instance(changed, expected_revision=proposed.revision_id)
    bad_rows = rows(assess(snapshots, bad), "protected_instance_snapshot", "violated")
    assert [row["subject"] for row in bad_rows] == ["tower-b"]


def test_actual_planner_rejects_invalid_wall_even_if_lineage_remains_valid(snapshots):
    source, _, proposed = snapshots
    bad = mutate(proposed, "storey-02-wall-0", lambda op: op.update(height_mm=-5))
    assert refinement_view(bad, "tower-a", source=source)
    with pytest.raises(SectionPlanError, match="invalid_section_program"):
        assess(snapshots, bad)


def test_same_level_or_reversed_elevation_cannot_qualify_void_chain(snapshots):
    bad = mutate(snapshots[2], "storey-02-level", lambda op: op.update(elev_mm=0))
    with pytest.raises(SectionPlanError, match="strictly ascend"):
        assess(snapshots, bad)


def test_same_named_output_changing_role_does_not_count_as_retained_room(snapshots):
    proposed = snapshots[2]
    outputs = []
    for output in proposed.instances[0].outputs:
        if output.key == "storey-02-space":
            output = NamedOutput(output.key, {"op": "create_wall", "p0_mm": [100, 100], "p1_mm": [1000, 100],
                "height_mm": 4500, "level": {"by": "ref", "value": output_id(proposed.project_id, "tower-a", "storey-02-level")}})
        outputs.append(output)
    bad = replace_outputs(proposed, outputs)
    result = assess(snapshots, bad)
    retained = next(row for row in rows(result, "named_subject_retained") if row["subject"] == "storey-02-space")
    assert retained["status"] == "violated" and retained["reason"] == "subject_kind_changed"
    assert next(row for row in rows(result, "room_axis_enclosure") if row["subject"] == "storey-02-space")["reason"] == "expected_room_missing"


@pytest.mark.parametrize("stage", ["polygon", "partition"])
def test_geometry_library_failures_have_named_boundary_refusal(snapshots, monkeypatch, stage):
    from shapely.errors import GEOSException
    from kir import section_plan_acceptance as module
    def fail(*args, **kwargs):
        raise GEOSException("controlled malformed geometry failure")
    monkeypatch.setattr(module, "Polygon" if stage == "polygon" else "spatial_model_from_ops", fail)
    with pytest.raises(SectionPlanError, match="plan_geometry_failed"):
        assess(snapshots)


def test_real_saved_proposal_is_evaluated_before_commit_without_writing_store_or_assets(tmp_path):
    pytest.importorskip("OCP")
    store = workflow.create_store(tmp_path / "section.sqlite")
    reopened = ProjectStore.open(tmp_path / "section.sqlite")
    before = reopened.head()
    source = reopened.get(before.instances[0].metadata["refinement"]["source"]["revision_id"])
    proposed = workflow.develop_section(before, source=source, height_mm=4500., setback_mm=1200.)
    bad = mutate(proposed, "storey-02-space", lambda op: op.update(xy=[6000., 4000.]))
    database = Path(tmp_path / "section.sqlite").read_bytes()
    saved_revisions = [revision.dumps() for revision in reopened.history()]
    result = assess_section_plan_change(before, bad, source=source, instance_key="tower-a",
        required_void_chain=CHAIN, protected_instances=[*PROTECTED, "podium"])
    report = result.to_dict()
    assert rows(report, "room_seed_in_slab_xy_region", "violated")
    assert len(rows(report, "protected_instance_snapshot", "evaluated")) == 3
    assert reopened.head().revision_id == before.revision_id
    assert [revision.dumps() for revision in reopened.history()] == saved_revisions
    assert Path(tmp_path / "section.sqlite").read_bytes() == database
    report["rows"][0]["status"] = "forged"
    assert "forged" not in result.dumps()
    assert json.loads(result.dumps())["proposed_revision_id"] == bad.revision_id
