"""G03 authored bindings, never geometry-preservation/native/ancestry proof."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples import residential_project as towers
from examples import residential_refinement as workflow
from kir import spec
from kir.project import NamedOutput, ProjectRevision, _canonical, _hash, _thaw, output_id
from kir.project_merge import ChangeProposal, ProposalError, ProposalScope, accept_proposal, merge_proposal
from kir.project_refinement import (REFINEMENT_SCHEMA_V2, REFINEMENT_SCHEMA, RefinementError, annotate_schematic_refinement,
                                    carry_schematic_refinement, refinement_view)
from kir.project_store import ProjectStore, StoreConflict
from kir.registry_base import ReferenceKind


ROOT = Path(__file__).resolve().parents[2]
ROLES = {"create_level": "level", "create_floor_by_contour": "slab", "create_wall": "wall", "create_room": "space"}



def _canonical_ops(project):
    """Project ops with addresses — for a piece-by-piece comparison of programs."""
    return project.to_program()["ops"]


@pytest.fixture(scope="module")
def values():
    source = towers.concept()
    loose = towers.develop_section(source)
    refined = workflow.develop_section(source)
    changed = workflow.develop_section(refined, source=source, height_mm=4500., setback_mm=1200.)
    return source, loose, refined, changed


def annotate(source, target, **kw):
    args = dict(source_instance_key="tower-a", source_output_key="concept-volume",
        roles={output.key: ROLES[output.operation["op"]] for output in target.outputs},
        losses=["concept_twist_removed", "concept_top_taper_removed"], inactive_parameters=["twist_deg"])
    args.update(kw)
    return annotate_schematic_refinement(source, target, **args)


def changed_record(project, mutation):
    metadata = _thaw(project.instances[0].metadata)
    mutation(metadata)
    return project.replace_instance(replace(project.instances[0], metadata=metadata), expected_revision=project.revision_id)


def test_exact_one_to_many_roles_and_history_do_not_claim_geometry(values):
    source, loose, refined, changed = values
    report = refinement_view(changed, "tower-a", source=source)
    record = _thaw(refined.instances[0].metadata["refinement"])
    # 🔴 `/1` -> `/2` (07.09.2026): the historical source pin STAYED
    # UNCHANGED (the same five fields and the same digest), a LIVE
    # address was added — where that same output sits RIGHT NOW. Without
    # it, the concept would vanish from the head, and there would be
    # nobody to address "change the source shape after detailing" to.
    assert record["schema"] == REFINEMENT_SCHEMA_V2
    assert record["source"] == {"project_id": source.project_id, "revision_id": source.revision_id,
        "instance_key": "tower-a", "output_key": "concept-volume",
        "output_digest": _hash(source.instances[0].outputs[0].to_dict()),
        "live_instance_key": "tower-a-concept"}
    assert record["members"] == changed.instances[0].to_dict()["metadata"]["refinement"]["members"]
    assert len(record["members"]) == 21
    assert {role: sum(m["role"] == role for m in record["members"]) for role in ROLES.values()} == {
        "level": 3, "slab": 3, "wall": 12, "space": 3}
    assert "target_revision_id" not in record
    assert changed.parent_revision == refined.revision_id != source.revision_id
    assert report["target_revision_id"] == changed.revision_id
    assert report["source_op_id"] == output_id(source.project_id, "tower-a", "concept-volume")
    assert report["binding_status"] == "exact_supplied_source" and report["ancestry"] == "not_checked"
    assert report["geometry_preservation"] == "not_claimed"
    assert report["roles_and_losses"] == "authored_assertions" and report["loss_inventory"] == "not_proven_exhaustive"
    assert report["recipe_execution"] == report["compiler_validation"] == report["native_execution"] == "not_run"
    for member, output in zip(report["members"], changed.instances[0].outputs, strict=True):
        assert member["output_digest"] == _hash(output.to_dict())
    report["members"][0]["role"] = "wall"
    assert refined.instances[0].metadata["refinement"]["members"][0]["role"] == "level"


def test_annotation_preserves_outputs_parameters_pins_and_does_not_run_recipe(values, monkeypatch):
    source, loose, _, _ = values
    target = loose.instances[0]
    before = target.to_dict()
    def forbidden(*args, **kwargs):
        raise AssertionError("annotation executed a recipe")
    monkeypatch.setattr(towers, "generate_outputs", forbidden)
    result = annotate(source, target)
    for name in ("key", "module_key", "outputs", "parameters", "module_digest"):
        assert _canonical(result.to_dict()[name]) == _canonical(before[name])
    assert target.to_dict() == before
    assert _thaw(result.metadata["refines"]) == [output_id(source.project_id, "tower-a", "concept-volume")]
    assert annotate(source, result).to_dict() == result.to_dict()  # Exact repeat, not reassigned provenance.


@pytest.mark.parametrize("case", ["boolean_true", "integer_zero", "float_zero", "extra", "unknown_schema", "missing_schema",
    "member_missing", "member_extra", "member_duplicate", "member_reorder", "role_level_as_wall", "role_unknown",
    "source_project", "source_revision", "source_digest", "source_extra", "alias_wrong", "alias_missing",
    "loss_duplicate", "loss_empty", "inactive_unknown", "wrong_kind"])
def test_rehashed_draft_metadata_never_bypasses_typed_reader(values, case):
    source, _, refined, _ = values
    def mutate(metadata):
        record = metadata["refinement"]
        if case in ("boolean_true", "integer_zero", "float_zero"):
            record["geometry_preserved"] = {"boolean_true": True, "integer_zero": 0, "float_zero": 0.}[case]
        elif case == "extra": record["proof"] = "native"
        elif case == "unknown_schema": record["schema"] = "kir-schematic-refinement/999"
        elif case == "missing_schema": record.pop("schema")
        elif case == "member_missing": record["members"].pop()
        elif case == "member_extra": record["members"].append({"output_key": "not-an-output", "role": "wall"})
        elif case == "member_duplicate": record["members"][-1] = record["members"][0]
        elif case == "member_reorder": record["members"].reverse()
        elif case == "role_level_as_wall": record["members"][0]["role"] = "wall"
        elif case == "role_unknown": record["members"][0]["role"] = ["wall"]
        elif case.startswith("source_"):
            key = {"source_project": "project_id", "source_revision": "revision_id", "source_digest": "output_digest", "source_extra": "extra"}[case]
            record["source"][key] = "other" if key in ("project_id", "extra") else "0" * 64
        elif case == "alias_wrong": metadata["refines"] = ["0" * 64]
        elif case == "alias_missing": metadata.pop("refines")
        elif case == "loss_duplicate": record["losses"] *= 2
        elif case == "loss_empty": record["losses"] = []
        elif case == "inactive_unknown": record["inactive_parameters"] = ["not_present"]
        else: record["kind"] = "faithful_conversion"
    bad = changed_record(refined, mutate)
    # Project and storage still admit inert drafts; qualification is explicit.
    assert ProjectRevision.loads(bad.dumps()).dumps() == bad.dumps()
    with pytest.raises(RefinementError):
        refinement_view(bad, "tower-a", source=source)


@pytest.mark.parametrize("case", ["missing", "extra", "wrong_role"])
def test_annotation_requires_complete_and_compatible_roles(values, case):
    source, loose, _, _ = values
    roles = {output.key: ROLES[output.operation["op"]] for output in loose.instances[0].outputs}
    if case == "missing": roles.pop("storey-01-level")
    elif case == "extra": roles["extra"] = "wall"
    else: roles["storey-01-level"] = "wall"
    with pytest.raises(RefinementError):
        annotate(source, loose.instances[0], roles=roles)


@pytest.mark.parametrize("alias", [None, [], ["0" * 64]])
def test_annotation_does_not_overwrite_a_conflicting_alias_even_without_a_record(values, alias):
    source, loose, _, _ = values
    target = replace(loose.instances[0], metadata={"refines": alias})
    with pytest.raises(RefinementError, match="source_alias_mismatch"):
        annotate(source, target)
    assert _canonical(target.metadata["refines"]) == _canonical(alias)


@pytest.mark.parametrize("kw", [{"losses": "not-a-sequence"}, {"losses": [True]},
    {"source_instance_key": None}, {"source_output_key": "missing"}, {"inactive_parameters": ["unknown"]}])
def test_bad_public_arguments_have_named_refusal(values, kw):
    source, loose, _, _ = values
    with pytest.raises(RefinementError):
        annotate(source, loose.instances[0], **kw)


@pytest.mark.parametrize("contract_part", ["reference_kind", "category"])
def test_roles_recheck_current_registry_not_just_operation_name(values, monkeypatch, contract_part):
    source, _, refined, _ = values
    if contract_part == "reference_kind":
        contract = spec.OPS["create_wall"]
        monkeypatch.setitem(spec.OPS, "create_wall", replace(contract, result=replace(contract.result, reference_kind=ReferenceKind.LEVEL)))
    else:
        actual = spec.op_result_categories
        monkeypatch.setattr(spec, "op_result_categories", lambda op: ("OST_Levels",) if op["op"] == "create_wall" else actual(op))
    with pytest.raises(RefinementError, match="role_contract_mismatch"):
        refinement_view(refined, "tower-a", source=source)


def test_same_stable_source_id_does_not_accept_another_revision_or_payload(values):
    source, _, refined, _ = values
    other = source.replace_instance(towers.instance("tower-a", dict(source.instances[0].parameters, twist_deg=20)),
                                    expected_revision=source.revision_id)
    assert source.addressed_outputs()[0][2] == other.addressed_outputs()[0][2]
    with pytest.raises(RefinementError, match="source_binding_mismatch"):
        refinement_view(refined, "tower-a", source=other)
    bad = changed_record(refined, lambda meta: meta["refinement"]["source"].update(revision_id=other.revision_id))
    with pytest.raises(RefinementError, match="payload differs"):
        refinement_view(bad, "tower-a", source=other)


@pytest.mark.parametrize("case", ["key", "module", "pin", "output_key", "output_role", "conflicting_typed", "conflicting_loose", "alias"])
def test_carry_refuses_changed_owner_members_or_conflicting_annotation(values, case):
    source, _, previous, changed = values
    replacement = changed.instances[0]
    if case == "key": replacement = replace(replacement, key="tower-b")
    elif case == "module": replacement = replace(replacement, module_key="other")
    elif case == "pin": replacement = replace(replacement, module_digest="0" * 64)
    elif case == "output_key":
        replacement = replace(replacement, outputs=[replace(replacement.outputs[0], key="renamed"), *replacement.outputs[1:]])
    elif case == "output_role":
        replacement = replace(replacement, outputs=[NamedOutput(replacement.outputs[0].key,
            {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [1000, 0], "height_mm": 3000, "level": {"by": "name", "value": "L"}}),
            *replacement.outputs[1:]])
    else:
        metadata = _thaw(replacement.metadata)
        if case == "conflicting_typed": metadata["refinement"]["source"]["revision_id"] = "0" * 64
        elif case == "conflicting_loose":
            metadata["refinement"] = {k: v for k, v in metadata["refinement"].items() if k in {"kind", "geometry_preserved", "losses", "inactive_parameters"}}
            metadata["refinement"]["losses"] = ["another_loss"]
        else: metadata["refines"] = ["0" * 64]
        replacement = replace(replacement, metadata=metadata)
    original = previous.dumps()
    with pytest.raises(RefinementError):
        carry_schematic_refinement(previous.instances[0], replacement)
    assert previous.dumps() == original


def test_old_generator_cannot_auto_qualify_or_silently_carry_typed_lineage(values):
    source, loose, refined, _ = values
    with pytest.raises(RefinementError, match="legacy_unbound_refinement"):
        refinement_view(loose, "tower-a", source=source)
    legacy_changed = towers.develop_section(refined, height_mm=4500.)
    with pytest.raises(RefinementError, match="legacy_unbound_refinement"):
        refinement_view(legacy_changed, "tower-a", source=source)
    with pytest.raises(RefinementError, match="legacy_unbound_refinement"):
        carry_schematic_refinement(loose.instances[0], legacy_changed.instances[0])
    with pytest.raises(RefinementError, match="source_snapshot_required"):
        workflow.develop_section(refined)


@pytest.mark.parametrize("foreign", ["wrong_type", "wrong_revision"])
def test_wrapper_refuses_wrong_source_before_generator(values, monkeypatch, foreign):
    source = values[0]
    supplied = {} if foreign == "wrong_type" else source.revise(expected_revision=source.revision_id, intent="another source snapshot")
    def forbidden(*args, **kwargs):
        raise AssertionError("wrong source reached generator")
    monkeypatch.setattr(towers, "develop_section", forbidden)
    with pytest.raises(RefinementError, match="source_binding_mismatch"):
        workflow.develop_section(source, source=supplied)


def test_annotation_leaves_program_and_plan_exactly_as_evaluated(values):
    """🔴 REFINED ON 07.09.2026, AND THE REFINEMENT IS NAMED, NOT HIDDEN.

    It used to be asserted that "the program does NOT change at all".
    With the concept being preserved, this stopped being true, and
    pretending it was still true would mean guarding something already
    void. EXACTLY one thing changes: an op for the preserved concept is
    added to the program. Everything else — the section's composition,
    its order, the section's plan digest, and the modules — must match
    byte-for-byte, and this is checked here EXPLICITLY, rather than
    inferred from overall equality.
    """
    _, loose, refined, _ = values
    before = {op["id"]: op for op in _canonical_ops(loose)}
    after = {op["id"]: op for op in _canonical_ops(refined)}
    added = set(after) - set(before)
    assert set(before) - set(after) == set(), "ни один оп не имеет права исчезнуть"
    assert len(added) == 1, "добавиться вправе РОВНО сохранённый концепт"
    assert after[next(iter(added))]["op"] == "create_solid_blend"
    assert all(_canonical(before[oid]) == _canonical(after[oid]) for oid in before), \
        "существующие опы обязаны совпасть побайтно"
    assert [module.to_dict() for module in refined.modules] == [module.to_dict() for module in loose.modules]


def test_atomic_proposal_and_caller_grant_include_the_same_refinement_snapshot(tmp_path, values):
    # The holding grew by `tower-a-concept`: detailing now WRITES two
    # instances — the section and the preserved concept. The grant must
    # name both: silently expanding the holding behind the issuer's back
    # is exactly what `ProposalError` refuses to let through.
    source, _, refined, _ = values
    # `instance_order` — because an instance is ADDED, and an addition
    # changes the order; the holding must name this too. Measurement:
    # `_changed_scope` gives
    # `instances=('tower-a','tower-a-concept'), project_fields=('instance_order',)`.
    grant = ProposalScope(instances=("tower-a", "tower-a-concept"),
                          project_fields=("instance_order",))
    proposal = ChangeProposal(source, refined, grant, "design-agent", "Explicit schematic section A")
    store = ProjectStore.create(tmp_path / "proposal.sqlite", source)
    with pytest.raises(ProposalError, match="grant"):
        accept_proposal(store, proposal, expected_revision=source.revision_id,
                        authorized_scope=ProposalScope(instances=("tower-b",)))
    assert store.head().dumps() == source.dumps()
    accepted = accept_proposal(store, proposal, expected_revision=source.revision_id, authorized_scope=grant)
    assert accepted.merge.clean and store.head().dumps() == refined.dumps()
    refinement_view(store.head(), "tower-a", source=store.get(source.revision_id))
    different = workflow.develop_section(source, height_mm=4100.)
    conflict = merge_proposal(proposal, different, authorized_scope=grant)
    assert not conflict.clean and conflict.revision is None
    assert conflict.to_dict()["semantic_validation"] == "not_run"


def test_changed_recipe_pin_refuses_before_commit_without_rewriting_original_history(tmp_path, values):
    source, _, refined, _ = values
    store = ProjectStore.create(tmp_path / "changed-pin.sqlite", source)
    store.commit(refined, expected_revision=source.revision_id)
    definition = refined.modules[0]
    other = replace(definition, recipe=replace(definition.recipe, source=definition.recipe.source + "\n# different source"))
    repinned = refined.revise(expected_revision=refined.revision_id, modules=[other],
        instances=[replace(instance, module_digest=None) for instance in refined.instances])
    store.commit(repinned, expected_revision=refined.revision_id)
    before = [revision.dumps() for revision in store.history()]
    with pytest.raises(ValueError, match="generator definition"):
        workflow.continue_section(store, expected_revision=repinned.revision_id)
    assert [revision.dumps() for revision in store.history()] == before
    assert store.get(source.revision_id).dumps() == source.dumps()


def test_real_saved_podium_history_fresh_process_edit_preserves_all_other_bytes_and_pins(tmp_path):
    pytest.importorskip("OCP")
    from examples import residential_with_podium as composed
    store = composed.create_store(tmp_path / "saved.sqlite", stage="podium")
    source = store.head()
    asset = store.get_asset(source.geometry_references()[0][1].geometry.bundle_sha256)
    # 🔴 THE SAME INSTANCES ARE COMPARED, NOT "ALL BUT THE FIRST". As of
    # 07.09.2026 detailing ADDS the preserved concept, and the `[1:]`
    # slice started catching it as a "foreign byte". The pin's subject is
    # "the other snapshots are untouched", so the comparison goes BY THE
    # KEYS that existed before the fix; the appearance of the new
    # instance is checked in a separate line below.
    before_keys = [item.key for item in source.instances[1:]]
    before = _canonical([item.to_dict() for item in source.instances[1:]])
    refined = workflow.continue_section(store, expected_revision=source.revision_id, height_mm=3600., setback_mm=900.)
    child = subprocess.run([sys.executable, "-c", """
import json, sys
from examples.residential_refinement import continue_section
from kir.project_store import ProjectStore
from kir.project_refinement import refinement_view
store = ProjectStore.open(sys.argv[1], readonly=False)
changed = continue_section(store, expected_revision=sys.argv[2], height_mm=4500., setback_mm=1200.)
source_id = changed.instances[0].metadata['refinement']['source']['revision_id']
print(json.dumps(refinement_view(changed,'tower-a',source=store.get(source_id))))
""", str(tmp_path / "saved.sqlite"), refined.revision_id], capture_output=True, text=True, timeout=25,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    changed = store.head()
    report = json.loads(child.stdout)
    assert report["target_revision_id"] == changed.revision_id and report["source"]["revision_id"] == source.revision_id
    assert len(store.history()) == 5
    kept = {item.key: item for item in changed.instances}
    assert _canonical([kept[key].to_dict() for key in before_keys]) == before
    # And the concept itself must appear and carry the SAME output that was the source.
    assert "tower-a-concept" in kept
    assert [output.key for output in kept["tower-a-concept"].outputs] == ["concept-volume"]
    assert store.get_asset(asset.digest).dumps() == asset.dumps()
    assert [module.to_dict() for module in changed.modules] == [module.to_dict() for module in source.modules]
    assert _canonical(changed.instances[0].metadata["refinement"]) == _canonical(refined.instances[0].metadata["refinement"])
    operations = {output.key: output.operation for output in changed.instances[0].outputs}
    assert [operations[f"storey-{i:02d}-level"]["elev_mm"] for i in (1, 2, 3)] == [0., 4500., 9000.]
    assert operations["storey-03-wall-0"]["p1_mm"][0] == 12800.
    with pytest.raises(StoreConflict):
        workflow.continue_section(store, expected_revision=source.revision_id)
    assert store.head().dumps() == changed.dumps()


def test_reader_and_carry_are_inert_in_fresh_process(values):
    source, _, refined, changed = values
    child = subprocess.run([sys.executable, "-c", """
import importlib.abc, json, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname=='OCP' or fullname.startswith('OCP.'):
            raise AssertionError('inert lineage entered native backend')
sys.meta_path.insert(0,NoNative())
from kir.project import ProjectRevision
from kir.project_refinement import refinement_view, carry_schematic_refinement
source, previous, changed = [ProjectRevision.from_dict(row) for row in json.load(sys.stdin)]
carry_schematic_refinement(previous.instances[0], changed.instances[0])
assert refinement_view(changed,'tower-a',source=source)['native_execution']=='not_run'
assert not any(name=='OCP' or name.startswith('OCP.') for name in sys.modules)
print('inert')
"""], input=json.dumps([p.to_dict() for p in (source, refined, changed)]), capture_output=True, text=True,
        timeout=20, env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "inert"


def test_cli_new_store_has_exact_history_and_refuses_existing_path(tmp_path):
    pytest.importorskip("OCP")
    path = tmp_path / "cli.sqlite"
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, str(ROOT / "examples/residential_refinement.py"), "--store", str(path)]
    child = subprocess.run(command, text=True, capture_output=True, timeout=30, env=env)
    assert child.returncode == 0, child.stderr
    data = json.loads(child.stdout)
    store = ProjectStore.open(path)
    assert data["history_length"] == len(store.history()) == 5
    assert data["project_revision_id"] == store.head().revision_id
    assert data["refinement"]["geometry_preservation"] == "not_claimed"
    assert store.history()[0].dumps() == towers.concept().dumps()
    before = path.read_bytes()
    again = subprocess.run(command, text=True, capture_output=True, timeout=30, env=env)
    assert again.returncode == 2 and path.read_bytes() == before
