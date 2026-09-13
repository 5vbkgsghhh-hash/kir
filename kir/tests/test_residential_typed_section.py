"""Explicit authored type-library + preserved section lineage; no native run."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from examples import residential_project as original
from examples import residential_refinement as workflow
from examples import residential_typed_section as typed
from kir.compiler import compile_program, plan_program
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, _canonical, output_id
from kir.project_diff import diff_projects
from kir.project_refinement import refinement_view
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore, StoreConflict


WALL_LAYERS = [{"width_mm": 15., "function": "Finish1"}, {"width_mm": 200., "function": "Structure"},
               {"width_mm": 0., "function": "Membrane"}, {"width_mm": 12.5, "function": "Finish2"}]
FLOOR_LAYERS = [{"width_mm": 200., "function": "Structure"}, {"width_mm": 50., "function": "Substrate"},
                {"width_mm": 10., "function": "Finish1"}]


def inputs():
    return dict(wall_name="KIR_Section_Wall_227.5", wall_layers=deepcopy(WALL_LAYERS),
                wall_source_type={"by": "element_id", "value": 100},
                floor_name="KIR_Section_Floor_260", floor_layers=deepcopy(FLOOR_LAYERS),
                floor_source_type={"by": "element_id", "value": 400})


def instances(project):
    return {instance.key: instance for instance in project.instances}


@pytest.fixture(scope="module")
def values():
    source = original.concept()
    base = workflow.develop_section(source, height_mm=4200., setback_mm=1800.)
    candidate = typed.add_section_types(base, source=source, expected_revision=base.revision_id, **inputs())
    return source, base, candidate


def test_type_library_is_a_separate_earlier_owner_with_explicit_seed_inputs(values):
    source, base, candidate = values
    assert candidate.parent_revision == base.revision_id
    # +`tower-a-concept`: the preserved original volume (2026-09-07). The
    # type library is still FIRST and still a separate owner — the pin's
    # subject has not changed, the scene's composition has.
    assert [instance.key for instance in candidate.instances] == [
        typed.TYPE_INSTANCE, "tower-a", "tower-b", "tower-c", "tower-a-concept"]
    library = instances(candidate)[typed.TYPE_INSTANCE]
    assert library.module_key == typed.TYPE_MODULE
    assert [output.key for output in library.outputs] == [typed.WALL_TYPE_OUTPUT, typed.FLOOR_TYPE_OUTPUT]
    assert library.parameters == {"backend_seed_selectors": {
        "wall": {"by": "element_id", "value": 100}, "floor": {"by": "element_id", "value": 400}}}
    for kind, output, layers in zip(("wall", "floor"), library.outputs, (WALL_LAYERS, FLOOR_LAYERS), strict=True):
        assert output.operation["op"] == "create_wall_type" and output.operation["host_kind"] == kind
        assert output.to_dict()["operation"]["layers"] == layers
        assert output.operation["source_type"] == library.parameters["backend_seed_selectors"][kind]
    assert library.metadata["backend_seed_identity"] == "not_verified"
    assert candidate.modules[:len(base.modules)] == base.modules
    definition = next(item for item in candidate.modules if item.key == typed.SECTION_MODULE)
    assert definition.owner == "sealed_evaluation"
    assert definition.recipe.entrypoint == "generate_outputs"
    assert definition.recipe.source == Path(typed.__file__).read_text(encoding="utf-8")
    assert definition.recipe.dependencies["examples.residential_project"] == hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest()
    assert definition.recipe.source_digest != base.modules[0].recipe.source_digest


def test_all_21_members_keep_geometry_ids_lineage_and_receive_only_their_typed_ref(values):
    source, base, candidate = values
    before, after = instances(base)["tower-a"], instances(candidate)["tower-a"]
    assert len(after.outputs) == 21 and [output.key for output in after.outputs] == [output.key for output in before.outputs]
    refs = {"create_wall": output_id(base.project_id, typed.TYPE_INSTANCE, typed.WALL_TYPE_OUTPUT),
            "create_floor_by_contour": output_id(base.project_id, typed.TYPE_INSTANCE, typed.FLOOR_TYPE_OUTPUT)}
    counts = {key: 0 for key in refs}
    for old, new in zip(before.outputs, after.outputs, strict=True):
        expected = old.to_dict()
        if old.operation["op"] in refs:
            expected["operation"]["type"] = {"by": "ref", "value": refs[old.operation["op"]]}
            counts[old.operation["op"]] += 1
        assert _canonical(new.to_dict()) == _canonical(expected)
        assert output_id(base.project_id, before.key, old.key) == output_id(candidate.project_id, after.key, new.key)
    assert counts == {"create_wall": 12, "create_floor_by_contour": 3}
    # 🔴 REFINED 2026-09-07. Previously the metadata had to match IN FULL.
    # Now the type pass also TAKES THEM UNDER LINEAGE: two `create_wall_type`
    # live as a separate instance, and without this two of the section
    # program's twenty-three outputs stayed UNADDRESSABLE (an
    # instrument-measurable hole). The pin is not lifted but sharpened: the
    # record is allowed to change by EXACTLY two adopted members, everything
    # else byte for byte, including the source and the losses.
    from kir.project import _thaw as _thaw_meta
    old_record = _thaw_meta(before.metadata)["refinement"]
    new_record = _thaw_meta(after.metadata)["refinement"]
    adopted = [m for m in new_record["members"] if m not in old_record["members"]]
    assert len(adopted) == 2 and {m["instance_key"] for m in adopted} == {typed.TYPE_INSTANCE}
    assert {m["role"] for m in adopted} == {"wall_type"}
    assert new_record["members"][:len(old_record["members"])] == old_record["members"]
    assert new_record["source"] == old_record["source"]
    assert {k: v for k, v in new_record.items() if k not in ("members", "schema")} == \
           {k: v for k, v in old_record.items() if k not in ("members", "schema")}
    assert _canonical({k: v for k, v in _thaw_meta(after.metadata).items() if k != "refinement"}) == \
           _canonical({k: v for k, v in _thaw_meta(before.metadata).items() if k != "refinement"})
    assert after.parameters["twist_deg"] == before.parameters["twist_deg"]
    report = refinement_view(candidate, "tower-a", source=source)
    assert len(report["members"]) == 23 and report["geometry_preservation"] == "not_claimed"
    for key in ("tower-b", "tower-c"):
        assert instances(candidate)[key].to_dict() == instances(base)[key].to_dict()


def test_real_selected_dependency_context_includes_types_and_keeps_backend_selectors(values):
    _, _, candidate = values
    selected = selected_instance_program(candidate, "tower-a")
    assert len(selected["ops"]) == 23
    assert [operation["op"] for operation in selected["ops"][:2]] == ["create_wall_type", "create_wall_type"]
    assert [operation["source_type"] for operation in selected["ops"][:2]] == [
        {"by": "element_id", "value": 100}, {"by": "element_id", "value": 400}]
    planned = plan_program(selected)
    assert [operation.result.reference_kind.value for operation in planned.ops[:2]] == ["wall_type", "floor_type"]
    for version in ("2023", "2026"):
        output = compile_program(planned, revit_version=version)
        assert output.ok, output.diagnostics
        assert "CompoundStructure.CreateSimpleCompoundStructure" in output.csharp
        assert "FloorType __ft_" in output.csharp and "WallType __wt_" in output.csharp
    old = compile_program(planned, revit_version="2021")
    assert not old.ok and any(item.code == "KIR-E003" for item in old.diagnostics)


def test_explicit_name_seeds_remain_unresolved_external_dependencies(values):
    source, base, _ = values
    args = inputs()
    args.update(wall_source_type={"by": "name", "value": "Explicit wall seed"},
                floor_source_type={"by": "name", "value": "Explicit floor seed"})
    candidate = typed.add_section_types(base, source=source, expected_revision=base.revision_id, **args)
    selected = selected_instance_program(candidate, "tower-a")
    assert selected["ops"][0]["source_type"] == args["wall_source_type"]
    assert plan_program(selected).ops  # An authored plan is not successful grounding.
    compiled = compile_program(selected)
    assert not compiled.ok  # No document catalog was invented by the helper.


@pytest.mark.parametrize("case", ["default_seed", "ref_seed", "extra_seed_field", "empty_seed_name", "bool_seed_id",
                                  "negative_layer", "unknown_function", "extra_layer_field", "empty_layers", "empty_name"])
def test_bad_design_or_seed_inputs_refuse_without_mutating_prior_revision(values, case):
    source, base, _ = values
    args = inputs()
    if case == "default_seed": args["wall_source_type"] = {"by": "default"}
    if case == "ref_seed": args["wall_source_type"] = {"by": "ref", "value": "type"}
    if case == "extra_seed_field": args["wall_source_type"]["guessed"] = True
    if case == "empty_seed_name": args["wall_source_type"] = {"by": "name", "value": ""}
    if case == "bool_seed_id": args["wall_source_type"] = {"by": "element_id", "value": True}
    if case == "negative_layer": args["wall_layers"][0]["width_mm"] = -1
    if case == "unknown_function": args["wall_layers"][0]["function"] = "custom-function"
    if case == "extra_layer_field": args["wall_layers"][0]["density"] = 100
    if case == "empty_layers": args["floor_layers"] = []
    if case == "empty_name": args["floor_name"] = ""
    before = base.dumps()
    with pytest.raises(ValueError):
        typed.add_section_types(base, source=source, expected_revision=base.revision_id, **args)
    assert base.dumps() == before


@pytest.mark.parametrize("collision", [typed.TYPE_MODULE, typed.SECTION_MODULE, "instance"])
def test_existing_named_owners_are_not_reused_or_overwritten(values, collision):
    source, base, _ = values
    if collision == "instance":
        changed = base.revise(expected_revision=base.revision_id, instances=(*base.instances,
            ModuleInstance(typed.TYPE_INSTANCE, base.modules[0].key, [])))
    else:
        changed = base.revise(expected_revision=base.revision_id, modules=(*base.modules, ModuleDefinition(collision)))
    with pytest.raises(typed.TypedSectionError, match="typed_section_key_collision"):
        typed.add_section_types(changed, source=source, expected_revision=changed.revision_id, **inputs())


def test_custom_legal_fields_and_altered_type_refs_are_not_silently_dropped(values):
    source, base, candidate = values
    section = instances(base)["tower-a"]
    outputs = list(section.outputs)
    old = outputs[2]
    outputs[2] = NamedOutput(old.key, {**old.to_dict()["operation"], "location_line": "finish_face_exterior"})
    changed = base.replace_instance(replace(section, outputs=outputs), expected_revision=base.revision_id)
    with pytest.raises(typed.TypedSectionError, match="unsupported_section_snapshot"):
        typed.add_section_types(changed, source=source, expected_revision=changed.revision_id, **inputs())
    section = instances(candidate)["tower-a"]
    outputs = list(section.outputs)
    old = outputs[2]
    outputs[2] = NamedOutput(old.key, {**old.to_dict()["operation"], "type": {"by": "name", "value": "Other type"}})
    changed = candidate.replace_instance(replace(section, outputs=outputs), expected_revision=candidate.revision_id)
    with pytest.raises(typed.TypedSectionError, match="unsupported_section_snapshot"):
        typed.edit_section(changed, source=source, expected_revision=changed.revision_id, height_mm=4500, setback_mm=1200)


def test_layer_edit_marks_equal_payload_walls_as_affected_through_real_refs(values):
    _, _, candidate = values
    library = instances(candidate)[typed.TYPE_INSTANCE]
    outputs = list(library.outputs)
    body = outputs[0].to_dict()["operation"]
    body["layers"][1]["width_mm"] = 210
    outputs[0] = NamedOutput(outputs[0].key, body)
    changed = candidate.replace_instance(replace(library, outputs=outputs), expected_revision=candidate.revision_id)
    report = diff_projects(candidate, changed).to_dict()
    expected = {output_id(candidate.project_id, "tower-a", output.key)
                for output in instances(candidate)["tower-a"].outputs if output.operation["op"] == "create_wall"}
    assert expected <= set(report["affected"])


@pytest.mark.parametrize("changed_file", ["host_source", "original_dependency"])
def test_changed_source_or_dependency_refuses_before_generator(values, monkeypatch, changed_file):
    source, _, candidate = values
    old_read_text, old_read_bytes = Path.read_text, Path.read_bytes
    if changed_file == "host_source":
        def changed(path, *args, **kwargs):
            text = old_read_text(path, *args, **kwargs)
            return text + "\n# controlled source change\n" if path == Path(typed.__file__) else text
        monkeypatch.setattr(Path, "read_text", changed)
    else:
        def changed(path, *args, **kwargs):
            data = old_read_bytes(path, *args, **kwargs)
            return data + b"\n# controlled dependency change\n" if path == Path(original.__file__) else data
        monkeypatch.setattr(Path, "read_bytes", changed)
    monkeypatch.setattr(original, "generate_outputs", lambda *_a, **_kw: pytest.fail("generator executed after pin drift"))
    with pytest.raises(typed.TypedSectionError, match="typed_section_recipe_changed"):
        typed.edit_section(candidate, source=source, expected_revision=candidate.revision_id, height_mm=4500, setback_mm=1200)


def test_saved_real_podium_continuation_preserves_types_refs_and_all_other_snapshots(tmp_path):
    pytest.importorskip("OCP")
    store = workflow.create_store(tmp_path / "project.sqlite")
    before_history = [revision.dumps() for revision in store.history()]
    base = store.head()
    source = store.get(instances(base)["tower-a"].metadata["refinement"]["source"]["revision_id"])
    assets = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
              for _, output, _ in base.geometry_references()}
    asset_bytes = {key: bundle.dumps() for key, bundle in assets.items()}
    candidate = typed.add_section_types(base, source=source, expected_revision=base.revision_id, **inputs())
    store.commit(candidate, expected_revision=base.revision_id)
    resumed = ProjectStore.open(store.path, readonly=False)
    changed = typed.continue_section(resumed, expected_revision=candidate.revision_id, height_mm=4500., setback_mm=1200.)
    assert resumed.head().dumps() == changed.dumps()
    assert [revision.dumps() for revision in resumed.history()[:len(before_history)]] == before_history
    for key in (typed.TYPE_INSTANCE, "tower-b", "tower-c", "podium"):
        assert _canonical(instances(changed)[key].to_dict()) == _canonical(instances(candidate)[key].to_dict())
    assert changed.modules == candidate.modules
    assert _canonical(instances(changed)["tower-a"].metadata) == _canonical(instances(candidate)["tower-a"].metadata)
    assert refinement_view(changed, "tower-a", source=source)["geometry_preservation"] == "not_claimed"
    assert len(selected_instance_program(changed, "tower-a")["ops"]) == 23
    for key, data in asset_bytes.items():
        assert resumed.get_asset(key).dumps() == data
    compiled = compile_program(materialize_project(changed, assets).planned, revit_version="2026")
    assert compiled.ok, compiled.diagnostics
    saved_bytes = store.path.read_bytes()
    with pytest.raises(StoreConflict):
        typed.continue_section(resumed, expected_revision=candidate.revision_id, height_mm=4800., setback_mm=1600.)
    with pytest.raises(ValueError):
        typed.continue_section(resumed, expected_revision=changed.revision_id, height_mm=-1, setback_mm=1200.)
    assert store.path.read_bytes() == saved_bytes
