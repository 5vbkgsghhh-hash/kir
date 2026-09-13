"""Authored ownership handoff, not recipe execution or native re-publication."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance, NamedOutput,
                         ProjectRevision, RecipePin, RevisionConflict, _canonical, _hash, _thaw)
from kir.project_handoff import HANDOFF_SCHEMA, HandoffError, handoff_instance_to_explicit


ROOT = Path(__file__).resolve().parents[2]


def project(*, schema="kir-authoring-project/1", recipe=True, outputs=None, metadata=None):
    pin = RecipePin("raise AssertionError('handoff must never execute source')", "a" * 64,
                    dependencies={"fixture": "b" * 64}) if recipe else None
    module = ModuleDefinition("evaluated", "sealed_evaluation", pin)
    parameters = {"height_mm": 3600.0, "literal": {"bool": True, "int": 1, "float": 1.0,
                                                  "positive_zero": 0.0, "negative_zero": -0.0}}
    return ProjectRevision("handoff-project", [module], [
        ModuleInstance("section", module.key, outputs if outputs is not None else [
            NamedOutput("upper", {"op": "create_level", "elev_mm": 3600.0, "name": "Upper"}),
            NamedOutput("lower", {"op": "create_level", "elev_mm": 0.0, "name": "Lower"}),
        ], parameters, metadata={"refines": ["historic-address"], "refinement": {"inert": "unchanged"},
                                 **(metadata or {})}),
        ModuleInstance("other", module.key, [NamedOutput("volume", {"op": "future_op", "data": 42})]),
    ], metadata={"units": "mm", "frame": "project-local"}, schema=schema)


def handoff(value, **kwargs):
    options = {"new_module_key": "explicit-section", "expected_revision": value.revision_id}
    options.update(kwargs)
    return handoff_instance_to_explicit(value, "section", **options)


@pytest.mark.parametrize("schema", ["kir-authoring-project/1", "kir-authoring-project/2"])
def test_handoff_is_one_child_with_identical_outputs_inputs_and_old_definitions(schema):
    before = project(schema=schema)
    original = before.dumps()
    after = handoff(before)
    selected, released = before.instances[0], after.instances[0]
    assert before.dumps() == original
    assert after.parent_revision == before.revision_id and after.revision_id != before.revision_id
    assert after.schema == before.schema and after.ir_version == before.ir_version
    assert after.intent == before.intent and _canonical(after.metadata) == _canonical(before.metadata)
    assert after.modules[:-1] == before.modules
    assert _canonical(after.instances[1].to_dict()) == _canonical(before.instances[1].to_dict())
    explicit = after.modules[-1]
    assert explicit.owner == "explicit" and explicit.recipe is None
    assert released.key == selected.key and released.module_key == explicit.key
    assert released.module_digest == explicit.definition_digest != selected.module_digest
    assert _canonical(released.parameters) == _canonical(selected.parameters)
    assert _canonical([o.to_dict() for o in released.outputs]) == _canonical([o.to_dict() for o in selected.outputs])
    assert [o.key for o in released.outputs] == ["upper", "lower"]  # no sorting
    assert [oid for _, _, oid in after.addressed_outputs()] == [oid for _, _, oid in before.addressed_outputs()]
    assert _canonical(after.to_program()) == _canonical(before.to_program())
    assert {k: _thaw(v) for k, v in released.metadata.items() if k != "ownership_handoff"} == _thaw(selected.metadata)
    record = _thaw(released.metadata["ownership_handoff"])
    assert record["schema"] == HANDOFF_SCHEMA
    assert record["source"] == {"project_id": before.project_id, "revision_id": before.revision_id,
        "instance_key": selected.key, "instance_snapshot_digest": _hash(selected.to_dict()),
        "module_key": selected.module_key, "module_definition_digest": selected.module_digest,
        "outputs_digest": _hash([o.to_dict() for o in selected.outputs])}
    assert record["target"] == {"module_key": explicit.key, "module_definition_digest": explicit.definition_digest,
                                 "owner": "explicit"}
    assert record["parameters_role"] == "historical_inputs_not_generation_controls"
    assert record["claims"] == {"preserved": "authored_output_payloads_and_order_at_handoff",
        "recipe_execution": "not_run", "compiler_validation": "not_run", "geometry_evaluation": "not_run",
        "native_execution": "not_run", "history_persistence": "not_established"}
    assert after.revision_id not in _canonical(record)  # no content-hash self reference
    assert ProjectRevision.loads(after.dumps()).dumps() == after.dumps()
    with pytest.raises(TypeError):
        released.metadata["ownership_handoff"]["source"]["revision_id"] = "forged"


def test_missing_recipe_remains_unknown_in_historical_definition():
    before = project(recipe=False)
    after = handoff(before)
    assert after.modules[0].recipe is None and after.modules[-1].recipe is None
    assert after.instances[0].metadata["ownership_handoff"]["source"]["module_definition_digest"] == before.modules[0].definition_digest


def test_explicit_output_draft_and_future_ir_are_not_silently_planned():
    before = replace(project(outputs=[NamedOutput("draft", {"op": "unknown_future_operation", "value": None})]),
                     ir_version="future-ir")
    after = handoff(before)
    assert after.ir_version == "future-ir" and after.instances[0].outputs == before.instances[0].outputs
    assert after.instances[0].metadata["ownership_handoff"]["claims"]["compiler_validation"] == "not_run"


@pytest.mark.parametrize("occupied", [None, False, {}, {"schema": HANDOFF_SCHEMA}, "old declaration"])
def test_occupied_metadata_is_never_overwritten(occupied):
    before = project(metadata={"ownership_handoff": occupied})
    old = before.dumps()
    with pytest.raises(HandoffError, match="handoff_metadata_occupied"):
        handoff(before)
    assert before.dumps() == old


@pytest.mark.parametrize("module_key", ["evaluated", "already-explicit"])
def test_existing_module_name_is_not_adopted_even_if_it_is_explicit(module_key):
    before = project()
    before = before.revise(expected_revision=before.revision_id,
                           modules=(*before.modules, ModuleDefinition("already-explicit")))
    with pytest.raises(HandoffError, match="handoff_module_exists"):
        handoff(before, new_module_key=module_key)


@pytest.mark.parametrize("bad", [None, True, 1, "", "has space", "../escaped"])
def test_bad_module_or_instance_key_refuses(bad):
    before = project()
    with pytest.raises(HandoffError, match="invalid_handoff"):
        handoff(before, new_module_key=bad)
    with pytest.raises(HandoffError, match="invalid_handoff"):
        handoff_instance_to_explicit(before, bad, new_module_key="explicit", expected_revision=before.revision_id)


def test_missing_instance_and_wrong_input_are_named_refusals():
    before = project()
    with pytest.raises(HandoffError, match="handoff_instance_missing"):
        handoff_instance_to_explicit(before, "missing", new_module_key="explicit", expected_revision=before.revision_id)
    with pytest.raises(HandoffError, match="invalid_handoff"):
        handoff_instance_to_explicit(before.to_dict(), "section", new_module_key="explicit", expected_revision=before.revision_id)


def test_stale_revision_and_repeated_handoff_are_not_rebased_automatically():
    before = project()
    after = handoff(before)
    with pytest.raises(RevisionConflict):
        handoff(before, expected_revision=after.revision_id)
    with pytest.raises(HandoffError, match="handoff_owner_not_sealed"):
        handoff(after, new_module_key="another-explicit")


def test_body_owned_output_refuses_without_loading_the_body():
    before = project(schema="kir-authoring-project/2", outputs=[NamedOutput("body", {
        "op": "create_directshape", "category": "mass", "name": "inert body"},
        BodyRepresentation("a" * 64, "b" * 64))])
    original = before.dumps()
    with pytest.raises(HandoffError, match="handoff_body_owned_unsupported"):
        handoff(before)
    assert before.dumps() == original


def test_handoff_does_not_import_or_execute_geometry_compiler_or_runtime_in_fresh_process():
    before = project()
    script = r'''
import importlib.abc, json, sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.') or fullname in {
            'kir.compiler', 'kir.geometry_materialization', 'kir.revit_connector', 'kir.sandbox'}:
            raise AssertionError('unexpected execution dependency: ' + fullname)
sys.meta_path.insert(0, Deny())
from kir.project import ProjectRevision
from kir.project_handoff import handoff_instance_to_explicit
source = ProjectRevision.loads(sys.stdin.read())
target = handoff_instance_to_explicit(source, 'section', new_module_key='explicit-section', expected_revision=source.revision_id)
print(target.dumps())
'''
    child = subprocess.run([sys.executable, "-c", script], input=before.dumps(), text=True,
                           capture_output=True, timeout=20,
                           env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == handoff(before).dumps()


def test_real_saved_residential_handoff_reopen_then_one_level_edit_keeps_other_sources(tmp_path, monkeypatch):
    pytest.importorskip("OCP")
    from examples import residential_with_podium as composed
    from examples import residential_refinement as refinement
    from examples import residential_project as towers
    from kir.project_diff import diff_projects
    from kir.project_refinement import refinement_view
    from kir.project_store import ProjectStore, StoreConflict

    path = tmp_path / "residential.sqlite"
    store = composed.create_store(path, stage="podium")
    concept_source = store.head()
    sealed = refinement.develop_section(concept_source)
    store.commit(sealed, expected_revision=concept_source.revision_id)
    old_bytes = path.read_bytes()
    old_assets = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256).dumps()
                  for _, output, _ in sealed.geometry_references()}

    def forbidden(*args, **kwargs):
        pytest.fail("handoff ran the old recipe")
    monkeypatch.setattr(towers, "generate_outputs", forbidden)
    explicit = handoff_instance_to_explicit(sealed, "tower-a", new_module_key="tower-a-explicit",
                                           expected_revision=sealed.revision_id)
    assert path.read_bytes() == old_bytes and store.head().revision_id == sealed.revision_id
    assert [oid for _, _, oid in explicit.addressed_outputs()] == [oid for _, _, oid in sealed.addressed_outputs()]
    assert not diff_projects(sealed, explicit).changed
    assert _canonical([o.to_dict() for o in explicit.instances[0].outputs]) == _canonical(
        [o.to_dict() for o in sealed.instances[0].outputs])
    for key in ("refinement", "refines"):
        assert _canonical(explicit.instances[0].metadata[key]) == _canonical(sealed.instances[0].metadata[key])
    assert refinement_view(explicit, "tower-a", source=concept_source)["binding_status"] == "exact_supplied_source"
    # Existing generator cannot silently reclaim an explicit snapshot's outputs.
    with pytest.raises(Exception, match="saved generator definition differs"):
        towers.develop_section(explicit)
    store.commit(explicit, expected_revision=sealed.revision_id)
    competing = handoff_instance_to_explicit(sealed, "tower-a", new_module_key="competing-owner",
                                             expected_revision=sealed.revision_id)
    with pytest.raises(StoreConflict):
        store.commit(competing, expected_revision=sealed.revision_id)
    assert store.head().revision_id == explicit.revision_id

    script = r'''
from dataclasses import replace
import importlib.abc, sys
class NoKernel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('native kernel loaded during explicit field edit')
sys.meta_path.insert(0, NoKernel())
from kir.project_store import ProjectStore
store = ProjectStore.open(sys.argv[1], readonly=False)
base = store.head()
section = next(i for i in base.instances if i.key == 'tower-a')
outputs = tuple(replace(o, operation={**dict(o.operation), 'elev_mm': 3800.0})
                if o.key == 'storey-02-level' else o for o in section.outputs)
proposed = base.replace_instance(replace(section, outputs=outputs), expected_revision=base.revision_id)
store.commit(proposed, expected_revision=base.revision_id)
print(proposed.revision_id)
'''
    child = subprocess.run([sys.executable, "-c", script, str(path)], text=True,
                           capture_output=True, timeout=30,
                           env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    reopened = ProjectStore.open(path)
    proposed = reopened.head()
    assert proposed.revision_id == child.stdout.strip() and proposed.parent_revision == explicit.revision_id
    assert reopened.get(sealed.revision_id).dumps() == sealed.dumps()
    assert reopened.get(explicit.revision_id).dumps() == explicit.dumps()
    diff = diff_projects(explicit, proposed)
    addressed = {oid: (instance.key, output.key)
                 for instance, output, oid in proposed.addressed_outputs()}
    target_id = next(oid for oid, address in addressed.items()
                     if address == ("tower-a", "storey-02-level"))
    # 🔴 THE COUNT OF UNTOUCHED WENT 17 → 18, AND THIS IS NOT A
    # REGRESSION. As of 81bc166, the `tower-a` concept is no longer
    # REPLACED by the section, but stays alive as its own instance
    # `tower-a-concept` (`live_instance_key` of record
    # `kir-schematic-refinement/2`, `examples/residential_refinement.py`).
    # So the snapshot now has 25 outputs instead of the previous 24, and
    # exactly one added output — the preserved concept — landed in
    # `unchanged`. `changed` and `affected` did not move: 1 and 6.
    # The test's property is not in the count but in the ADDRESSES, so
    # they are pinned alongside it: editing ONE level's mark touches
    # exactly its own level (slab, four walls, room) and NOT A SINGLE
    # foreign source — neither concepts B and C, nor the podium's atrium,
    # nor A's own preserved concept.
    assert diff.changed == (target_id,)
    assert {addressed[oid] for oid in diff.affected} == {("tower-a", key) for key in (
        "storey-02-slab", "storey-02-space", *(f"storey-02-wall-{n}" for n in range(4)))}
    assert {addressed[oid] for oid in diff.unchanged} >= {
        ("tower-b", "concept-volume"), ("tower-c", "concept-volume"),
        ("podium", "atrium-volume"), ("tower-a-concept", "concept-volume")}
    assert len(addressed) == 25 and len(diff.affected) == 6 and len(diff.unchanged) == 18
    assert len(diff.changed) + len(diff.affected) + len(diff.unchanged) == len(addressed)
    assert _canonical(proposed.instances[0].parameters) == _canonical(sealed.instances[0].parameters)
    assert _canonical(proposed.instances[0].metadata) == _canonical(explicit.instances[0].metadata)
    assert _canonical([m.to_dict() for m in proposed.modules]) == _canonical([m.to_dict() for m in explicit.modules])
    for before, after in zip(sealed.instances[1:], proposed.instances[1:], strict=True):
        assert _canonical(before.to_dict()) == _canonical(after.to_dict())  # B/C/podium and pins
    for digest, original in old_assets.items():
        assert reopened.get_asset(digest).dumps() == original
    assert refinement_view(proposed, "tower-a", source=reopened.get(concept_source.revision_id))["binding_status"] == "exact_supplied_source"
