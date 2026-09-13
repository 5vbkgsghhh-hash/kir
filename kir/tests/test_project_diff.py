"""Authoring comparison and conservative explicit-ref impact, without Revit."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from kir import faceref, sdk
from kir.diag import KirRefusal
from kir.project import ModuleDefinition, ModuleInstance, ProjectError, ProjectRevision, RecipePin, output_id
from kir.project_diff import DIFF_SCHEMA, diff_projects


def oid(key, instance="a"):
    return output_id("p", instance, key)


def level(elevation=0, name="Level"):
    return sdk.create_level(elev_mm=elevation, name=name)


def wall(level_key="level", **changes):
    return {**sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                             height_mm=3000, level=sdk.ref(oid(level_key))), **changes}


def project(outputs=None, *, parameters=None, instance_metadata=None, **changes):
    instance = ModuleInstance("a", "m", {"level": level()} if outputs is None else outputs,
                              parameters or {}, instance_metadata or {})
    return ProjectRevision("p", [ModuleDefinition("m")], [instance], **changes)


def next_outputs(before, outputs, **changes):
    return before.replace_instance(ModuleInstance("a", "m", outputs, **changes),
                                   expected_revision=before.revision_id)


def issue_kinds(report, side="after"):
    return {issue["kind"] for issue in report["dependency_issues"][side]}


def test_identical_snapshot_has_no_effects_and_result_is_detached():
    before = project({"level": level(), "wall": wall()})
    plan = diff_projects(before, ProjectRevision.loads(before.dumps()))
    assert plan.added == plan.removed == plan.changed == plan.affected == ()
    assert plan.unchanged == (oid("level"), oid("wall"))
    report = plan.to_dict()
    assert report["schema"] == DIFF_SCHEMA
    assert report["scope"] == "authoring_only"
    assert report["analysis"]["semantic_validation"] == "not_run"
    assert all("before" not in entry for entry in report["outputs"])
    report["outputs"][0]["reasons"].append("not an actual reason")
    assert plan.to_dict()["outputs"][0]["reasons"] == []
    with pytest.raises(FrozenInstanceError):
        plan._data = {}


def test_level_change_affects_unchanged_wall_slab_room_and_transitive_door():
    outputs = {
        "level": level(), "wall": wall(),
        "slab": sdk.create_floor_by_contour(
            contour={"outer": {"shape": "rect", "origin_mm": [0, 0],
                               "width_mm": 6000, "height_mm": 4000}},
            level=sdk.ref(oid("level"))),
        "room": sdk.create_room(xy=[1000, 1000], level=sdk.ref(oid("level"))),
        "door": sdk.create_door(host=sdk.ref(oid("wall")), offset_mm=1000),
        "unrelated": level(9000, "Unrelated"),
    }
    before = project(outputs)
    after = next_outputs(before, {**outputs, "level": level(300)})
    before.plan()
    after.plan()
    plan = diff_projects(before, after)
    assert plan.changed == (oid("level"),)
    assert set(plan.affected) == {oid(key) for key in ("wall", "slab", "room", "door")}
    assert plan.unchanged == (oid("unrelated"),)
    affected = next(x for x in plan.to_dict()["outputs"] if x["op_id"] == oid("door"))
    assert affected["payload_status"] == "unchanged"
    assert affected["impact"] == "reconsider"
    assert "dependency_changed" in affected["reasons"]


def test_cross_instance_references_follow_named_output_ids():
    before = ProjectRevision("p", [ModuleDefinition("m")], [
        ModuleInstance("a", "m", {"level": level()}),
        ModuleInstance("b", "m", {"wall": wall()}),
        ModuleInstance("c", "m", {"unrelated": level(9000, "Other")}),
    ])
    after = before.replace_instance(ModuleInstance("a", "m", {"level": level(500)}),
                                    expected_revision=before.revision_id)
    after.plan()
    plan = diff_projects(before, after)
    assert plan.affected == (oid("wall", "b"),)
    assert plan.unchanged == (oid("unrelated", "c"),)


def test_deletion_closes_over_before_edges_and_names_unresolved_after_refs():
    before = project({"level": level(), "wall": wall()})
    after = next_outputs(before, {"wall": wall()})
    plan = diff_projects(before, after)
    assert plan.removed == (oid("level"),)
    assert plan.affected == (oid("wall"),)
    assert "unresolved_reference" in issue_kinds(plan.to_dict())
    with pytest.raises(KirRefusal):
        after.plan()


def test_retarget_preserves_both_edge_sets_and_affects_downstream():
    door = sdk.create_door(host=sdk.ref(oid("wall")), offset_mm=1000)
    before = project({"level": level(), "next": level(3000, "Next"),
                      "wall": wall(), "door": door})
    after = next_outputs(before, {"next": level(3000, "Next"),
                                  "wall": wall("next"), "door": door})
    after.plan()
    plan = diff_projects(before, after)
    report = plan.to_dict()
    assert plan.changed == (oid("wall"),)
    assert plan.affected == (oid("door"),)
    assert any(edge["source"] == oid("level") for edge in report["dependencies"]["before"])
    assert any(edge["source"] == oid("next") for edge in report["dependencies"]["after"])


def test_insertion_does_not_misclassify_retained_order():
    before = project({"one": level(0, "One"), "two": level(3000, "Two")})
    after = next_outputs(before, {"inserted": level(-3000, "Inserted"),
                                  "one": level(0, "One"), "two": level(3000, "Two")})
    plan = diff_projects(before, after)
    assert plan.added == (oid("inserted"),)
    assert plan.affected == ()
    assert plan.unchanged == (oid("one"), oid("two"))
    assert plan.to_dict()["operation_order"]["reordered"] == []


def test_reordering_reports_all_inversion_participants_including_stationary_middle():
    outputs = {"one": level(0, "One"), "two": level(3000, "Two"), "three": level(6000, "Three"),
               "four": level(9000, "Four")}
    before = project(outputs)
    after = next_outputs(before, {key: outputs[key] for key in ("three", "two", "one", "four")})
    plan = diff_projects(before, after)
    assert plan.changed == ()
    assert plan.affected == tuple(oid(key) for key in ("three", "two", "one"))
    assert plan.unchanged == (oid("four"),)
    assert plan.to_dict()["operation_order"]["reordered"] == list(plan.affected)


def test_cycle_in_draft_is_bounded_and_not_called_valid():
    before = project({"first": wall("second"), "second": wall("first")})
    after = next_outputs(before, {"first": wall("second", height_mm=3200),
                                  "second": wall("first")})
    plan = diff_projects(before, after)
    assert plan.affected == (oid("second"),)
    assert {"reference_not_earlier", "incompatible_reference_kind"} <= issue_kinds(plan.to_dict())
    assert plan.to_dict()["analysis"]["semantic_validation"] == "not_run"


@pytest.mark.parametrize("old,new", [(True, 1), (1, 1.0), (False, 0), (-0.0, 0.0)])
def test_authoring_scalar_types_and_signed_zero_are_not_python_equality(old, new):
    before = project({"level": level(old)}, metadata={"units": old})
    after = ProjectRevision("p", before.modules,
                            [ModuleInstance("a", "m", {"level": level(new)})],
                            metadata={"units": new})
    plan = diff_projects(before, after)
    assert plan.changed == (oid("level"),)
    assert "metadata" in plan.to_dict()["project_changes"]


def test_metadata_units_change_does_not_convert_operations():
    before = project(metadata={"units": "mm", "frame": {"origin": [100, 0, 0]}})
    after = before.revise(expected_revision=before.revision_id,
                          metadata={"units": "m", "frame": {"origin": [100, 0, 0]}})
    plan = diff_projects(before, after)
    assert plan.changed == ()
    assert plan.affected == (oid("level"),)
    assert before.to_program()["ops"] == after.to_program()["ops"]
    assert plan.to_dict()["project_changes"]["metadata"]["before"]["units"] == "mm"


def test_opaque_source_metadata_and_parameters_do_not_create_runtime_ref_edges():
    fake = {"by": "ref", "value": oid("level")}
    before = project({"level": level(), "other": level(9000, oid("level"))},
                     parameters={"opaque": fake}, instance_metadata={"refines": [fake]})
    after = next_outputs(before, {"level": level(100), "other": level(9000, oid("level"))},
                         parameters={"opaque": fake}, metadata={"refines": [fake]})
    plan = diff_projects(before, after)
    assert plan.affected == ()
    assert plan.to_dict()["dependencies"] == {"before": [], "after": []}


def test_parameter_only_change_marks_retained_outputs_for_reconsideration():
    before = project(parameters={"storey_height_mm": 3000})
    after = next_outputs(before, {"level": level()}, parameters={"storey_height_mm": 3600})
    plan = diff_projects(before, after)
    assert plan.changed == ()
    assert plan.affected == (oid("level"),)
    assert "parameters" in plan.to_dict()["instances"]["entries"][0]["fields"]


def test_source_pin_change_preserves_both_sources_and_requires_new_snapshot_review():
    first = ModuleDefinition("m", "sealed_evaluation", RecipePin("def build(): return 1", "a" * 64))
    before = ProjectRevision("p", [first], [ModuleInstance("a", "m", {"level": level()})])
    second = ModuleDefinition("m", "sealed_evaluation", RecipePin("def build(): return 2", "a" * 64))
    after = before.revise(expected_revision=before.revision_id, modules=[second],
                          instances=[ModuleInstance("a", "m", {"level": level()})])
    report = diff_projects(before, after).to_dict()
    recipe = report["modules"]["entries"][0]["fields"]["recipe"]
    assert recipe["before"]["source"].endswith("1")
    assert recipe["after"]["source"].endswith("2")
    assert report["affected"] == [oid("level")]
    assert report["base_revision"] == before.revision_id
    assert report["project_changes"]["parent_revision"]["after"] == before.revision_id


def test_parent_only_new_revision_has_no_implied_realization_effect():
    before = project()
    after = before.revise(expected_revision=before.revision_id)
    plan = diff_projects(before, after)
    assert plan.affected == ()
    assert set(plan.to_dict()["project_changes"]) == {"parent_revision"}


def test_cross_project_comparison_is_refused():
    before = project()
    with pytest.raises(ProjectError, match="different projects"):
        diff_projects(before, replace(before, project_id="different"))


def test_unknown_ir_is_not_interpreted_with_current_registry():
    before = replace(project({"level": level(), "wall": wall()}), ir_version="future/9")
    after = next_outputs(before, {"level": level(100), "wall": wall()})
    plan = diff_projects(before, after)
    assert plan.to_dict()["dependencies"] == {"before": [], "after": []}
    assert "uninterpreted_ir_version" in issue_kinds(plan.to_dict())
    assert plan.affected == (oid("wall"),)


@pytest.mark.parametrize("operation", [
    {"op": "future_operation", "opaque": {"by": "ref", "value": oid("level")}},
    {"op": "stack", "count": 2, "items": []},
    {"op": "create_group", "name": "Group", "members": [
        {"op": "create_level", "id": "local-level", "elev_mm": 0, "name": "Local"},
        {"op": "create_wall", "id": "local-wall", "level": {"by": "ref", "value": "local-level"}}]},
])
def test_unknown_macro_and_nested_scopes_are_named_not_recursively_scraped(operation):
    before = project({"level": level(), "special": operation})
    after = next_outputs(before, {"level": level(100), "special": operation})
    plan = diff_projects(before, after)
    assert plan.to_dict()["dependencies"]["after"] == []
    assert not plan.to_dict()["analysis"]["explicit_reference_analysis_complete"]
    assert plan.affected == (oid("special"),)


def test_typed_face_and_target_refs_are_found_without_scraping_opaque_dicts(monkeypatch):
    monkeypatch.setenv(faceref.FACE_REF_FLAG, "1")
    first = wall()
    second = wall(p0_mm=[0, 1000], p1_mm=[6000, 1000])
    dimension = {"op": "create_dimension", "in_view": {"by": "element_id", "value": 900},
                 "refs": [{"by": "face", "of": {"by": "ref", "value": oid("wall")},
                           "predicate": {"side": "exterior"}},
                          {"by": "ref", "value": oid("other-wall")}],
                 "line_at": [3000, 500]}
    moved = {"op": "move_elements", "targets": [{"by": "ref", "value": oid("wall")}],
             "delta_mm": [10, 0, 0]}
    outputs = {"level": level(), "wall": first, "other-wall": second,
               "dimension": dimension, "move": moved}
    before = project(outputs)
    after = next_outputs(before, {**outputs, "wall": wall(height_mm=3100)})
    before.plan()
    after.plan()
    report = diff_projects(before, after).to_dict()
    assert {oid("dimension"), oid("move")} <= set(report["affected"])
    assert any(e["field"] == "refs[0].of" and e["source"] == oid("wall")
               for e in report["dependencies"]["after"])
    assert any(e["field"] == "targets[0]" for e in report["dependencies"]["after"])


def test_element_address_uses_compiler_walker_including_ref_whitespace():
    column = sdk.create_column(xy={"at_element": sdk.ref(" " + oid("wall") + " "),
                                    "point": "center"}, level=sdk.ref(oid("level")))
    before = project({"level": level(), "wall": wall(), "column": column})
    after = next_outputs(before, {"level": level(), "wall": wall(height_mm=3300), "column": column})
    before.plan()
    after.plan()
    plan = diff_projects(before, after)
    assert plan.affected == (oid("column"),)
    assert any(e["field"] == "xy.at_element" and e["source"] == oid("wall")
               for e in plan.to_dict()["dependencies"]["after"])


def test_direct_ref_whitespace_matches_semantic_planner_normalization():
    outputs = {"level": level(), "wall": wall(level={"by": "ref", "value": " " + oid("level") + " "})}
    before = project(outputs)
    after = next_outputs(before, {**outputs, "level": level(100)})
    after.plan()
    plan = diff_projects(before, after)
    assert plan.affected == (oid("wall"),)
    assert plan.to_dict()["analysis"]["explicit_reference_analysis_complete"]


def test_bad_scalar_reference_is_a_named_limitation_not_a_string_match():
    before = project({"level": level(), "wall": wall(level={"by": "ref", "value": 123})})
    after = next_outputs(before, {"level": level(100), "wall": wall(level={"by": "ref", "value": 123})})
    plan = diff_projects(before, after)
    assert "malformed_reference" in issue_kinds(plan.to_dict())
    assert plan.to_dict()["dependencies"]["after"] == []


@pytest.mark.parametrize("host_kind", [[], {}, "unknown", True, 1, None])
def test_draft_discriminator_does_not_crash_or_silently_choose_result_fallback(host_kind):
    before = project({
        "level": level(),
        "type": {"op": "create_wall_type", "name": "Type", "host_kind": host_kind},
        "wall": wall(type={"by": "ref", "value": oid("type")}),
    })
    report = diff_projects(before, ProjectRevision.loads(before.dumps())).to_dict()
    assert "producer_contract_unresolved" in issue_kinds(report)
    assert not report["analysis"]["explicit_reference_analysis_complete"]


def test_target_w_reference_uses_the_registered_result_kind():
    setting = sdk.set_param(target=sdk.ref(oid("wall")), param="Comments", value="Review")
    before = project({"level": level(), "wall": wall(), "setting": setting})
    after = next_outputs(before, {"level": level(), "wall": wall(height_mm=3100), "setting": setting})
    before.plan()
    after.plan()
    plan = diff_projects(before, after)
    assert plan.affected == (oid("setting"),)
    assert {"source": oid("wall"), "dependent": oid("setting"), "field": "target"} in (
        plan.to_dict()["dependencies"]["after"])


def test_named_output_rename_is_remove_add_not_guessed_identity_rewrite():
    before = project({"level": level(), "wall": wall()})
    after = next_outputs(before, {"renamed": level(), "wall": wall()})
    plan = diff_projects(before, after)
    assert plan.removed == (oid("level"),)
    assert plan.added == (oid("renamed"),)
    assert plan.changed == ()
    assert plan.affected == (oid("wall"),)
    assert "unresolved_reference" in issue_kinds(plan.to_dict())
    assert after.to_program()["ops"][1]["level"]["value"] == oid("level")


def test_module_order_is_reported_separately_from_executable_output_order():
    before = ProjectRevision("p", [ModuleDefinition("m"), ModuleDefinition("unused")],
                             [ModuleInstance("a", "m", {"level": level()})])
    after = before.revise(expected_revision=before.revision_id, modules=list(reversed(before.modules)))
    report = diff_projects(before, after).to_dict()
    assert report["modules"]["order"]["reordered"] == ["unused", "m"]
    assert not report["operation_order"]["changed"]
    assert report["affected"] == []


def test_instance_reorder_changes_real_operation_order_even_when_payloads_equal():
    before = ProjectRevision("p", [ModuleDefinition("m")], [
        ModuleInstance("a", "m", {"level": level()}),
        ModuleInstance("b", "m", {"level": level(3000, "Other")}),
    ])
    after = before.revise(expected_revision=before.revision_id,
                          instances=list(reversed(before.instances)))
    plan = diff_projects(before, after)
    assert plan.changed == ()
    assert plan.affected == (oid("level", "b"), oid("level"))
    assert plan.to_dict()["instances"]["order"]["reordered"] == ["b", "a"]


def test_intent_and_instance_lineage_changes_are_named_context_not_operation_rewrites():
    before = project(instance_metadata={"refines": ["concept-a"]}, intent="Concept")
    after = before.revise(expected_revision=before.revision_id, intent="Detailed", instances=[
        ModuleInstance("a", "m", {"level": level()}, metadata={"refines": ["concept-b"]})])
    plan = diff_projects(before, after)
    report = plan.to_dict()
    assert plan.changed == ()
    assert plan.affected == (oid("level"),)
    assert report["project_changes"]["intent"] == {"before": "Concept", "after": "Detailed"}
    assert report["instances"]["entries"][0]["fields"]["metadata"] == {
        "before": {"refines": ["concept-a"]}, "after": {"refines": ["concept-b"]}}


def test_json_object_key_order_does_not_change_payload_or_revision():
    payload = level()
    before = project({"level": payload})
    after = project({"level": dict(reversed(list(payload.items())))})
    assert before.revision_id == after.revision_id
    assert diff_projects(before, after).unchanged == (oid("level"),)


@pytest.mark.parametrize("selector", [None, {"by": "ref", "value": 123},
                                     {"by": "element_id", "value": 900}])
def test_unresolved_element_address_is_not_reported_as_complete_explicit_analysis(selector):
    before = project({"level": level(), "column": {
        "op": "create_column", "level": {"by": "ref", "value": oid("level")},
        "xy": {"at_element": selector, "point": "center"}}})
    report = diff_projects(before, before).to_dict()
    assert not report["analysis"]["explicit_reference_analysis_complete"]
    assert any(issue["field"] == "xy.at_element" for issue in report["dependency_issues"]["after"])


def test_null_list_selector_is_not_confused_with_an_omitted_optional_selector():
    before = project({"move": {"op": "move_elements", "targets": [None], "delta_mm": [10, 0, 0]}})
    report = diff_projects(before, before).to_dict()
    assert "malformed_selector" in issue_kinds(report)
    assert not report["analysis"]["explicit_reference_analysis_complete"]


def test_long_explicit_chain_uses_iterative_closure():
    outputs = {"level": level(), "wall": wall()}
    previous = "wall"
    for index in range(1100):
        key = f"column-{index}"
        outputs[key] = sdk.create_column(
            xy={"at_element": sdk.ref(oid(previous)), "point": "center"},
            level=sdk.ref(oid("level")))
        previous = key
    before = project(outputs)
    after = next_outputs(before, {**outputs, "wall": wall(height_mm=3200)})
    plan = diff_projects(before, after)
    assert len(plan.affected) == 1100
    assert plan.unchanged == (oid("level"),)
    assert plan.affected[-1] == oid(previous)


def test_real_residential_change_keeps_other_towers_and_lineage():
    from examples.residential_project import workflow

    concept, developed, changed = workflow()
    developed.plan()
    changed.plan()
    plan = diff_projects(developed, changed)
    report = plan.to_dict()
    assert len(plan.changed) == 15
    assert len(plan.affected) == 6
    assert len(plan.unchanged) == 2
    assert {entry["instance_key"] for entry in report["outputs"]
            if entry["op_id"] in plan.unchanged} == {"tower-b", "tower-c"}
    assert report["instances"]["changed"] == ["tower-a"]
    first = diff_projects(concept, developed).to_dict()
    instance_change = first["instances"]["entries"][0]["fields"]
    assert instance_change["metadata"]["after"]["refines"]
    assert first["removed"]
    assert first["added"]


def test_serialized_report_is_deterministic_and_does_not_repeat_equal_bodies():
    before = project({"level": level(), "wall": wall()})
    after = next_outputs(before, {"level": level(100), "wall": wall()})
    one = diff_projects(before, after).to_dict()
    two = diff_projects(ProjectRevision.loads(before.dumps()), ProjectRevision.loads(after.dumps())).to_dict()
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    affected = next(entry for entry in one["outputs"] if entry["op_id"] == oid("wall"))
    assert "before" not in affected and "after" not in affected
