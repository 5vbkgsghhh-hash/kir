"""Persistent authored snapshots through the real KIR planning boundary."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math

import pytest

from kir.compiler import compile_program
from kir.diag import KirRefusal
from kir.project import (
    PROJECT_SCHEMA,
    ModuleDefinition,
    ModuleInstance,
    NamedOutput,
    ProjectError,
    ProjectRevision,
    RecipePin,
    RevisionConflict,
    output_id,
)
from kir.tests.fixtures import GROUND_SNAPSHOT


def level(name="L1", elevation=3300):
    return {"op": "create_level", "name": name, "elev_mm": elevation}


def revision(*, outputs=None, metadata=None):
    return ProjectRevision(
        "residential", (ModuleDefinition("storey"),),
        (ModuleInstance("tower_a.floor_01", "storey",
                        {"datum": level()} if outputs is None else outputs),),
        intent="Один сохраняемый этаж", metadata={} if metadata is None else metadata)


def referenced_revision():
    level_id = output_id("residential", "tower_a.floor_01", "datum")
    return revision(outputs={
        "datum": level(),
        "south_wall": {
            "op": "create_wall", "p0_mm": [0, 0], "p1_mm": [5000, 0],
            "level": {"by": "ref", "value": level_id},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3300,
        },
    })


def test_round_trip_is_canonical_and_detached():
    project = referenced_revision()
    encoded = project.dumps()
    restored = ProjectRevision.loads(encoded)
    assert restored.dumps() == encoded
    assert restored.revision_id == project.revision_id
    assert restored.to_program() == project.to_program()
    assert isinstance(restored.modules, tuple)
    assert isinstance(restored.instances, tuple)
    assert isinstance(restored.instances[0].outputs, tuple)
    assert restored.plan().plan_digest == project.plan().plan_digest

    detached = restored.to_dict()
    detached["instances"][0]["outputs"][0]["operation"]["elev_mm"] = 9000
    lowered = restored.to_program()
    lowered["ops"][1]["level"]["value"] = "other"
    assert restored.dumps() == encoded


def test_output_order_survives_canonical_object_key_sorting():
    project = revision(outputs={"z_first": level("first", 0),
                                "a_second": level("second", 3300)})
    restored = ProjectRevision.loads(project.dumps())
    assert [item.key for item in restored.instances[0].outputs] == ["z_first", "a_second"]
    assert [op["name"] for op in restored.plan().to_ops()] == ["first", "second"]


def test_mutating_inputs_cannot_change_a_revision():
    operation = level()
    parameters = {"spacing": [1, 2], "enabled": True}
    metadata = {"frame": {"origin_mm": [0, 0, 0]}}
    instance = ModuleInstance("floor", "module", {"datum": operation},
                              parameters=parameters, metadata=metadata)
    project = ProjectRevision("p", [ModuleDefinition("module")], [instance], metadata=metadata)
    encoded = project.dumps()
    operation["name"] = "mutated"
    parameters["spacing"].append(3)
    metadata["frame"]["origin_mm"][0] = 1000
    assert project.dumps() == encoded
    with pytest.raises(TypeError):
        instance.outputs[0].operation["name"] = "mutated"
    with pytest.raises(TypeError):
        instance.metadata["frame"]["origin_mm"][0] = 1000
    with pytest.raises(dataclasses.FrozenInstanceError):
        project.intent = "mutated"


def test_insertion_and_reordering_preserve_named_operation_identity():
    original = revision(outputs={"datum": level(), "roof": level("roof", 6600)})
    before = {op["name"]: op["id"] for op in original.plan().to_ops()}
    replacement = ModuleInstance("tower_a.floor_01", "storey", {
        "basement": level("basement", -3300),
        "roof": level("roof", 6600),
        "datum": level(),
    })
    changed = original.replace_instance(replacement, expected_revision=original.revision_id)
    after = {op["name"]: op["id"] for op in changed.plan().to_ops()}
    assert all(after[name] == identifier for name, identifier in before.items())
    assert len(set(after.values())) == 3
    assert changed.parent_revision == original.revision_id
    assert changed.revision_id != original.revision_id
    assert len(original.plan().ops) == 2


def test_same_definition_instances_have_distinct_stable_outputs():
    first = ModuleInstance("floor_01", "storey", {"datum": level("L1", 3300)})
    second = ModuleInstance("floor_02", "storey", {"datum": level("L2", 6600)})
    project = ProjectRevision("p", (ModuleDefinition("storey"),), (first, second))
    reordered = project.with_instances((second, first), expected_revision=project.revision_id)
    before = {op["name"]: op["id"] for op in project.plan().to_ops()}
    after = {op["name"]: op["id"] for op in reordered.plan().to_ops()}
    assert before == after
    assert before["L1"] != before["L2"]


def test_changed_parameters_replace_whole_snapshot_without_mutating_base():
    project = revision()
    changed = ModuleInstance("tower_a.floor_01", "storey", {"datum": level(elevation=3600)},
                             parameters={"height_mm": 3600})
    result = project.replace_instance(changed, expected_revision=project.revision_id)
    assert result.instances[0].outputs == changed.outputs
    assert changed.module_digest is None  # the caller's new assertion was not mutated
    assert result.instances[0].module_digest == result.modules[0].definition_digest
    assert result.to_program()["ops"][0]["elev_mm"] == 3600
    assert project.to_program()["ops"][0]["elev_mm"] == 3300
    assert result.to_program()["ops"][0]["id"] == project.to_program()["ops"][0]["id"]


def test_stale_revision_is_refused_and_neither_value_is_mutated():
    project = revision()
    changed = project.revise(expected_revision=project.revision_id, intent="new intent")
    before = changed.dumps()
    with pytest.raises(RevisionConflict, match="rebase"):
        changed.replace_instance(project.instances[0], expected_revision=project.revision_id)
    with pytest.raises(RevisionConflict):
        project.with_instances((), expected_revision="0" * 64)
    assert changed.dumps() == before
    assert project.intent == "Один сохраняемый этаж"


def test_unknown_replacement_refuses_instead_of_inserting():
    project = revision()
    other = ModuleInstance("other", "storey", {"datum": level()})
    with pytest.raises(ProjectError, match="unknown instance"):
        project.replace_instance(other, expected_revision=project.revision_id)


def test_revision_can_atomically_add_definition_and_instance():
    project = revision()
    module = ModuleDefinition("site")
    instance = ModuleInstance("site", "site", {"datum": level("site", 0)})
    changed = project.revise(expected_revision=project.revision_id,
                             modules=(*project.modules, module),
                             instances=(instance, *project.instances))
    assert len(changed.plan().ops) == 2
    assert len(project.modules) == 1


@pytest.mark.parametrize("key", ["", "../wall", "a/b", "a\\b", "a..b", "two words",
                                  "\nwall", "стена", "x" * 129, True, 42, None])
def test_unsafe_output_keys_are_refused(key):
    with pytest.raises(ProjectError, match="stable ASCII key"):
        NamedOutput(key, level())
    with pytest.raises(ProjectError):
        output_id("p", "instance", key)


def test_duplicate_outputs_modules_and_instances_are_refused():
    output = NamedOutput("datum", level())
    with pytest.raises(ProjectError, match="duplicate output"):
        ModuleInstance("i", "m", (output, output))
    module = ModuleDefinition("m")
    instance = ModuleInstance("i", "m", {"datum": level()})
    with pytest.raises(ProjectError, match="duplicate module"):
        ProjectRevision("p", (module, module), (instance,))
    with pytest.raises(ProjectError, match="duplicate instance"):
        ProjectRevision("p", (module,), (instance, instance))
    with pytest.raises(ProjectError, match="unknown module"):
        ProjectRevision("p", (), (instance,))


def test_named_output_rejects_a_second_owner_of_its_id():
    with pytest.raises(ProjectError, match="own id"):
        NamedOutput("datum", {**level(), "id": "legacy_auto_id"})


def test_lowering_detects_identifier_collisions(monkeypatch):
    import kir.project

    project = revision(outputs={"one": level("one"), "two": level("two")})
    monkeypatch.setattr(kir.project, "output_id", lambda *args: "same")
    with pytest.raises(ProjectError, match="identity collision"):
        project.to_program()


def test_output_id_fits_real_compiler_contract_and_namespaces_projects():
    identifier = output_id("p", "instance", "datum")
    assert len(identifier) == 64
    assert identifier == output_id("p", "instance", "datum")
    assert identifier != output_id("other", "instance", "datum")
    assert len(revision().plan().ops) == 1


def test_lowering_preserves_unknown_refs_and_plan_refuses_them():
    project = referenced_revision()
    operation = project.instances[0].outputs[1].to_dict()["operation"]
    operation["level"]["value"] = "missing_output"
    invalid = revision(outputs={"datum": level(), "wall": operation})
    assert invalid.to_program()["ops"][1]["level"]["value"] == "missing_output"
    with pytest.raises(KirRefusal) as caught:
        invalid.plan()
    assert any(diag.code == "KIR-L003" for diag in caught.value.diagnostics)


def test_project_does_not_silently_topologically_reorder_forward_refs():
    project = referenced_revision()
    outputs = project.instances[0].outputs
    invalid = revision(outputs=(outputs[1], outputs[0]))
    with pytest.raises(KirRefusal) as caught:
        invalid.plan()
    assert any(diag.code == "KIR-L003" for diag in caught.value.diagnostics)
    assert invalid.to_program()["ops"][0]["op"] == "create_wall"


def test_existing_compiler_enforces_reference_result_kind():
    project = referenced_revision()
    outputs = [output.to_dict() for output in project.instances[0].outputs]
    wall = outputs[1]["operation"]
    bad_wall = {**wall, "level": {
        "by": "ref", "value": output_id("residential", "tower_a.floor_01", "south_wall")}}
    invalid = revision(outputs={"datum": level(), "south_wall": wall, "other": bad_wall})
    with pytest.raises(KirRefusal) as caught:
        invalid.plan()
    assert any(diag.code == "KIR-L004" for diag in caught.value.diagnostics)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_real_compiler_lowers_reloaded_project_to_csharp(version):
    project = ProjectRevision.loads(referenced_revision().dumps())
    plan = project.plan()
    result = compile_program(plan, revit_version=version, snapshot=GROUND_SNAPSHOT, bulk=True)
    assert result.ok, [diag.as_dict() for diag in result.diagnostics]
    assert result.planned is plan
    assert "Level.Create" in result.csharp
    assert "Wall.Create" in result.csharp
    assert output_id("residential", "tower_a.floor_01", "south_wall") in result.csharp


def test_recipe_source_is_inert_and_sealed_parameters_do_not_execute(tmp_path):
    marker = tmp_path / "must_not_exist"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    dependencies = {"geometry": "b" * 64}
    pin = RecipePin(source, "a" * 64, dependencies=dependencies)
    module = ModuleDefinition("recipe", "sealed_evaluation", pin)
    instance = ModuleInstance("floor", "recipe", {"datum": level()}, parameters={"height": 10})
    project = ProjectRevision("p", (module,), (instance,))
    dependencies["geometry"] = "c" * 64
    restored = ProjectRevision.loads(project.dumps())
    restored.plan()
    assert not marker.exists()
    assert restored.modules[0].recipe.source == source
    assert pin.source_digest == hashlib.sha256(source.encode()).hexdigest()
    assert restored.modules[0].recipe.dependencies["geometry"] == "b" * 64
    assert restored.to_program()["ops"][0]["elev_mm"] == 3300  # not parameter 'height'


def test_explicit_module_cannot_also_claim_recipe_ownership():
    pin = RecipePin("def build(): pass", "a" * 64)
    with pytest.raises(ProjectError, match="also be owned"):
        ModuleDefinition("m", "explicit", pin)
    with pytest.raises(ProjectError, match="module.owner"):
        ModuleDefinition("m", "generated_and_editable")


def test_sealed_snapshot_can_name_unknown_recipe_provenance():
    project = ProjectRevision("p", (ModuleDefinition("m", "sealed_evaluation"),),
                              (ModuleInstance("i", "m", {"datum": level()}),))
    assert ProjectRevision.loads(project.dumps()).modules[0].recipe is None


def test_changed_recipe_cannot_rebind_unchanged_sealed_snapshot():
    old_module = ModuleDefinition("tower", "sealed_evaluation",
                                  RecipePin("def build(): return 3", "a" * 64))
    instance = ModuleInstance("tower_a", "tower", {"datum": level()}, parameters={"floors": 3})
    project = ProjectRevision("p", (old_module,), (instance,))
    new_module = ModuleDefinition("tower", "sealed_evaluation",
                                  RecipePin("def build(): return 30", "a" * 64))
    original = project.dumps()
    with pytest.raises(ProjectError, match="module digest mismatch"):
        project.revise(expected_revision=project.revision_id, modules=(new_module,))
    with pytest.raises(ProjectError, match="module digest mismatch"):
        ProjectRevision("other", (new_module,), project.instances)
    assert project.dumps() == original
    assert project.instances[0].module_digest == old_module.definition_digest


def test_new_whole_evaluation_can_pin_new_recipe_without_renaming_outputs():
    old = ModuleDefinition("tower", "sealed_evaluation", RecipePin("old source", "a" * 64))
    new = ModuleDefinition("tower", "sealed_evaluation", RecipePin("new source", "b" * 64))
    project = ProjectRevision("p", (old,),
                              (ModuleInstance("tower_a", "tower", {"datum": level()}),))
    evaluated = ModuleInstance("tower_a", "tower", {"datum": level(elevation=3600)},
                               parameters={"height_mm": 3600})
    changed = project.revise(expected_revision=project.revision_id, modules=(new,),
                             instances=(evaluated,))
    assert changed.instances[0].module_digest == new.definition_digest
    assert changed.instances[0].module_digest != project.instances[0].module_digest
    assert changed.to_program()["ops"][0]["id"] == project.to_program()["ops"][0]["id"]
    assert ProjectRevision.loads(changed.dumps()).plan().to_ops()[0]["elev_mm"] == 3600


@pytest.mark.parametrize("pin", [None, "0" * 64])
def test_loaded_snapshot_cannot_omit_or_forge_its_definition_pin(pin):
    data = revision().to_dict()
    data["instances"][0]["module_digest"] = pin
    with pytest.raises(ProjectError, match="module_digest|module digest mismatch"):
        ProjectRevision.from_dict(data)


@pytest.mark.parametrize("environment", ["", "A" * 64, "x" * 64, 123, True])
def test_recipe_environment_pin_must_be_an_exact_digest(environment):
    with pytest.raises(ProjectError, match="SHA-256"):
        RecipePin("def build(): pass", environment)


def test_scalar_types_units_and_frames_are_preserved_without_conversion():
    metadata = {"units": "mm", "frame": {"name": "site", "origin_mm": [1000000, -20.5, 0],
                                          "axes": [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]},
                "scalars": [None, True, False, 0, 0.0, -0.0, 9007199254740993],
                "label": "Секция А"}
    project = revision(metadata=metadata)
    restored = ProjectRevision.loads(project.dumps())
    values = restored.to_dict()["metadata"]["scalars"]
    assert [type(value) for value in values] == [type(None), bool, bool, int, float, float, int]
    assert math.copysign(1, values[5]) == -1
    assert restored.to_dict()["metadata"] == metadata
    assert restored.to_program()["ops"][0]["elev_mm"] == 3300
    assert restored.plan().to_ops()[0]["elev_mm"] == 3300


@pytest.mark.parametrize("scalar", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_refused_before_hashing(scalar):
    with pytest.raises(ProjectError, match="non-finite"):
        revision(metadata={"deep": [scalar]})
    with pytest.raises(ProjectError, match="non-finite"):
        revision(outputs={"datum": level(elevation=scalar)})


def test_non_json_keys_values_and_invalid_unicode_are_refused():
    with pytest.raises(ProjectError, match="keys must be strings"):
        revision(metadata={1: "not coerced"})
    with pytest.raises(ProjectError, match="not JSON"):
        revision(metadata={"arbitrary": object()})
    with pytest.raises(ProjectError, match="Unicode"):
        revision(metadata={"name": "\ud800"})


def test_cyclic_constructor_metadata_refuses_as_non_json():
    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ProjectError, match="cyclic"):
        revision(metadata=cycle)


def test_boolean_numeric_operation_remains_draft_until_real_plan_refuses():
    project = revision(outputs={"datum": level(elevation=True)})
    restored = ProjectRevision.loads(project.dumps())
    assert restored.to_program()["ops"][0]["elev_mm"] is True
    with pytest.raises(KirRefusal):
        restored.plan()


def test_canonical_digest_is_sensitive_to_content_not_object_key_order():
    first = revision(metadata={"b": 2, "a": {"d": 4, "c": 3}})
    second = revision(metadata={"a": {"c": 3, "d": 4}, "b": 2})
    assert first.revision_id == second.revision_id
    assert first.dumps() == second.dumps()
    body = first.to_dict()
    body.pop("revision_id")
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                           allow_nan=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == first.revision_id
    assert revision(metadata={"a": 1}).revision_id != first.revision_id


@pytest.mark.parametrize("field,value", [("intent", "tampered"), ("metadata", {"x": 1}),
                                         ("parent_revision", "a" * 64)])
def test_tampered_load_refuses_content_change(field, value):
    data = revision().to_dict()
    data[field] = value
    with pytest.raises(ProjectError, match="integrity mismatch"):
        ProjectRevision.loads(json.dumps(data))


def test_tampered_recipe_source_digest_is_not_hidden_by_project_hash():
    pin = RecipePin("def build(): pass", "a" * 64)
    project = ProjectRevision("p", (ModuleDefinition("m", "sealed_evaluation", pin),), ())
    data = project.to_dict()
    data["modules"][0]["recipe"]["source"] = "changed source"
    with pytest.raises(ProjectError, match="source_digest"):
        ProjectRevision.loads(json.dumps(data))


@pytest.mark.parametrize("schema", ["kir-authoring-project/3", "", 1, True, None])
def test_unknown_schema_refused(schema):
    data = revision().to_dict()
    assert data["schema"] == PROJECT_SCHEMA
    data["schema"] = schema
    with pytest.raises(ProjectError, match="unsupported project schema"):
        ProjectRevision.loads(json.dumps(data))


def test_unknown_fields_and_missing_integrity_refused():
    data = revision().to_dict()
    data["execute"] = "anything"
    with pytest.raises(ProjectError, match="unexpected/missing fields"):
        ProjectRevision.from_dict(data)
    data.pop("execute")
    data.pop("revision_id")
    with pytest.raises(ProjectError, match="unexpected/missing fields"):
        ProjectRevision.from_dict(data)


@pytest.mark.parametrize("source", [
    '{"schema": "a", "schema": "b"}',
    '{"nested": {"name": "a", "name": "b"}}',
    '{"number": NaN}', '{"number": Infinity}', '{"number": -Infinity}',
    "[]", "null", "true", "{", "",
])
def test_ambiguous_or_malformed_json_is_rejected(source):
    with pytest.raises(ProjectError):
        ProjectRevision.loads(source)


def test_duplicate_named_outputs_in_loaded_sequence_refuse_even_before_digest_check():
    data = revision().to_dict()
    outputs = data["instances"][0]["outputs"]
    outputs.append(outputs[0])
    with pytest.raises(ProjectError, match="duplicate output"):
        ProjectRevision.loads(json.dumps(data))


def test_huge_exponent_is_not_silently_accepted_as_infinity():
    source = revision(metadata={"number": 1.0}).dumps().replace('"number":1.0',
                                                                            '"number":1e9999')
    with pytest.raises(ProjectError, match="non-finite"):
        ProjectRevision.loads(source)


def test_empty_project_is_persistable_but_not_an_executable_program():
    project = ProjectRevision("empty", (), ())
    assert ProjectRevision.loads(project.dumps()).instances == ()
    with pytest.raises(KirRefusal):
        project.plan()


def test_saved_ir_version_is_not_silently_replaced_by_current_registry(monkeypatch):
    import kir.registry_base

    original = revision()
    source = original.dumps()
    monkeypatch.setattr(kir.registry_base, "IR_VERSION", "future-version")
    restored = ProjectRevision.loads(source)
    changed = restored.revise(expected_revision=restored.revision_id, intent="updated")
    assert restored.to_program()["ir_version"] == original.ir_version
    assert changed.ir_version == original.ir_version
    assert restored.dumps() == source


def test_unsupported_operation_language_version_is_archivable_but_not_plannable():
    original = revision()
    project = ProjectRevision(original.project_id, original.modules, original.instances,
                              ir_version="future-version")
    restored = ProjectRevision.loads(project.dumps())
    assert restored.to_program()["ir_version"] == "future-version"
    with pytest.raises(KirRefusal):
        restored.plan()


@pytest.mark.parametrize("version", [None, True, 1, ""])
def test_operation_language_version_is_not_coerced(version):
    with pytest.raises(ProjectError, match="ir_version"):
        ProjectRevision("p", (), (), ir_version=version)


def test_bulk_policy_is_not_a_truthy_string():
    with pytest.raises(ProjectError, match="bulk: expected bool"):
        revision().plan(bulk="false")
