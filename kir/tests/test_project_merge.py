"""Public proposal -> three-way merge -> real SQLite CAS, without native work."""
from dataclasses import FrozenInstanceError, replace
import json
import multiprocessing

import pytest

from kir import sdk
from kir.project import (
    BodyRepresentation, ModuleDefinition, ModuleInstance, NamedOutput, ProjectError,
    ProjectRevision, RecipePin, PROJECT_SCHEMA_V2, output_id,
)
from kir.project_merge import (
    ChangeProposal, ProposalError, ProposalScope, accept_proposal, merge_proposal,
)
from kir.project_store import ProjectStore, StoreConflict


def root():
    return ProjectRevision("merge", [ModuleDefinition("explicit")], [
        ModuleInstance(key, "explicit", {"level": sdk.create_level(elev_mm=i * 3000, name=key)},
                       metadata={"decision": "preserve-" + key})
        for i, key in enumerate(("a", "b", "c"))],
        metadata={"design_note": "Keep the courtyard", "units": "mm"})


def edit(base, key, elevation):
    original = next(instance for instance in base.instances if instance.key == key)
    return base.replace_instance(replace(original, outputs={
        "level": sdk.create_level(elev_mm=elevation, name=key)}), expected_revision=base.revision_id)


def proposal(base, candidate, *keys, scope=None):
    return ChangeProposal(base, candidate, scope or ProposalScope(instances=keys),
                          "architecture-agent", "Raise the selected level")


def merge(change, current, scope=None):
    return merge_proposal(change, current, authorized_scope=scope or change.scope)


def kinds(result):
    return {conflict["kind"] for conflict in result.to_dict()["conflicts"]}


def bodies(project):
    return {instance.key: instance.to_dict() for instance in project.instances}


def test_independent_agents_merge_complete_snapshots_and_preserve_identity_decisions():
    base = root()
    ours, theirs = edit(base, "a", 500), edit(base, "b", 4500)
    result = merge(proposal(base, theirs, "b"), ours)
    assert result.clean
    assert bodies(result.revision) == {"a": bodies(ours)["a"], "b": bodies(theirs)["b"], "c": bodies(base)["c"]}
    assert result.revision.metadata == base.metadata
    assert result.revision.parent_revision == ours.revision_id
    assert result.revision.plan().ops
    assert [oid for _, _, oid in result.revision.addressed_outputs()] == [oid for _, _, oid in base.addressed_outputs()]
    report = result.to_dict()
    assert report["ancestry"] == "caller_asserted"
    assert report["semantic_validation"] == report["native_execution"] == "not_run"
    assert report["impact"]["changed"] == [output_id("merge", "b", "level")]
    report["conflicts"].append({"kind": "invented"})
    assert result.to_dict()["conflicts"] == []


def test_disjoint_merge_is_payload_symmetric_but_parent_tracks_current():
    base = root()
    a, b = edit(base, "a", 500), edit(base, "b", 4500)
    left = merge(proposal(base, a, "a"), b).revision
    right = merge(proposal(base, b, "b"), a).revision
    assert bodies(left) == bodies(right)
    assert left.parent_revision == b.revision_id
    assert right.parent_revision == a.revision_id
    assert left.revision_id != right.revision_id


def test_fast_forward_and_identical_edits_are_exact_and_idempotent():
    base = root()
    change = proposal(base, edit(base, "a", 500), "a")
    forward = merge(change, base)
    assert forward.revision.dumps() == change.candidate.dumps()
    repeated = merge(change, forward.revision)
    assert repeated.revision is forward.revision
    assert repeated.to_dict()["status"] == "unchanged"
    noop = merge(proposal(base, base), change.candidate)
    assert noop.revision is change.candidate


@pytest.mark.parametrize("part", ["output", "parameters", "metadata"])
def test_instance_is_atomic_even_if_two_agents_change_different_internal_fields(part):
    base = root()
    current = edit(base, "a", 500)
    original = base.instances[0]
    update = (replace(original, outputs={"level": sdk.create_level(elev_mm=800, name="a")})
              if part == "output" else replace(original, **{part: {"changed": True}}))
    candidate = base.replace_instance(update, expected_revision=base.revision_id)
    result = merge(proposal(base, candidate, "a"), current)
    assert not result.clean and result.revision is None
    assert "modify_modify" in kinds(result)
    assert result.to_dict()["conflicts"][0]["path"] == "instances/a"


def test_caller_grant_is_distinct_from_proposal_self_declared_scope():
    base = root()
    change = proposal(base, edit(base, "b", 9000), "b")
    with pytest.raises(ProposalError, match="caller.*grant"):
        merge(change, base, ProposalScope(instances=("a",)))
    with pytest.raises(ProposalError, match="declared write scope"):
        proposal(base, change.candidate, "a")


@pytest.mark.parametrize("value", [True, 1, 1.0, -0.0])
def test_json_scalars_in_instance_inputs_do_not_coalesce(value):
    base = root()
    candidate = base.replace_instance(replace(base.instances[0], parameters={"value": value}),
                                      expected_revision=base.revision_id)
    change = proposal(base, candidate, "a")
    assert ChangeProposal.loads(change.dumps()).proposal_id == change.proposal_id
    other = base.replace_instance(replace(base.instances[0], parameters={"value": 0.0}),
                                  expected_revision=base.revision_id)
    assert not merge(change, other).clean


def test_serialized_proposal_is_detached_hash_bound_and_inert(monkeypatch):
    base = root()
    change = proposal(base, edit(base, "a", 500), "a")
    monkeypatch.setattr(ProjectRevision, "plan", lambda *a, **k: pytest.fail("load ran compiler"))
    assert ChangeProposal.loads(change.dumps()).dumps() == change.dumps()
    data = change.to_dict()
    data["reason"] = "Altered decision"
    with pytest.raises(ProposalError, match="integrity"):
        ChangeProposal.from_dict(data)
    with pytest.raises(FrozenInstanceError):
        change.reason = "bad"
    with pytest.raises(FrozenInstanceError):
        change.scope.instances = ("c",)


@pytest.mark.parametrize("source", ["null", "[]", '{"x":0,"x":1}', '{"x":NaN}', '{"x":Infinity}',
                                    '{"x":"\\ud800"}', '{"x":1e400}'])
def test_strict_loader_refuses_malformed_claims(source):
    with pytest.raises(ProjectError):
        ChangeProposal.loads(source)


def test_duplicate_known_key_is_refused_even_when_last_wins_would_validate():
    base = root()
    change = proposal(base, edit(base, "a", 500), "a")
    encoded = change.dumps()
    duplicate = encoded.replace('"author":"architecture-agent"',
                                '"author":"ignored","author":"architecture-agent"')
    assert json.loads(duplicate) == json.loads(encoded)  # Ordinary JSON accepts it.
    with pytest.raises(ProposalError, match="duplicate"):
        ChangeProposal.loads(duplicate)


@pytest.mark.parametrize("scope", [lambda: ProposalScope(instances="a"),
                                   lambda: ProposalScope(instances=("a", "a")),
                                   lambda: ProposalScope(project_fields=("schema",)),
                                   lambda: ProposalScope(modules=("../m",))])
def test_scope_is_explicit_and_closed(scope):
    with pytest.raises(ProjectError):
        scope()


def test_branch_binding_and_versions_cannot_be_relabelled():
    base = root()
    child = edit(base, "a", 500)
    with pytest.raises(ProposalError, match="direct authored child"):
        proposal(base, edit(child, "a", 800), "a")
    with pytest.raises(ProposalError, match="project_id"):
        proposal(base, replace(child, project_id="another"), "a")
    with pytest.raises(ProposalError, match="ir_version"):
        proposal(base, replace(child, ir_version="future"), "a")
    upgraded = base.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=base.revision_id)
    with pytest.raises(ProposalError, match="schema"):
        proposal(base, upgraded)
    assert kinds(merge(proposal(base, child, "a"), upgraded)) == {"version_diverged"}


def test_shared_level_edit_conflicts_with_dependents_even_on_disjoint_instance_grants():
    base = root()
    wall = sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                           level=sdk.ref(output_id("merge", "a", "level")))
    base = base.replace_instance(ModuleInstance("b", "explicit", {"wall": wall}),
                                 expected_revision=base.revision_id)
    current = edit(base, "a", 500)
    candidate = base.replace_instance(ModuleInstance("b", "explicit", {"wall": {**wall, "height_mm": 3500}}),
                                      expected_revision=base.revision_id)
    current.plan()
    candidate.plan()
    result = merge(proposal(base, candidate, "b"), current)
    assert kinds(result) == {"dependency_overlap"}
    assert result.to_dict()["conflicts"][0]["op_ids"] == [output_id("merge", "b", "wall")]


def test_shared_transitive_downstream_is_a_conflict_not_only_direct_edit_intersection():
    base = root()
    both = sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                           level=sdk.ref(output_id("merge", "a", "level")),
                           top_level=sdk.ref(output_id("merge", "b", "level")))
    base = base.replace_instance(ModuleInstance("c", "explicit", {"wall": both}),
                                 expected_revision=base.revision_id)
    current, candidate = edit(base, "a", 500), edit(base, "b", 4500)
    current.plan()
    candidate.plan()
    assert kinds(merge(proposal(base, candidate, "b"), current)) == {"dependency_overlap"}


@pytest.mark.parametrize("source_change", ["remove", "move"])
def test_new_dependency_from_other_branch_closes_over_both_branch_graphs(source_change):
    base = root()
    current = (base.with_instances(base.instances[1:], expected_revision=base.revision_id)
               if source_change == "remove" else edit(base, "a", 500))
    wall = sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                           level=sdk.ref(output_id("merge", "a", "level")))
    candidate = base.replace_instance(ModuleInstance("b", "explicit", {"wall": wall}),
                                      expected_revision=base.revision_id)
    # Each input is valid on its own. Only combining the branch graphs reveals
    # either the dangling new ref or the new wall's changed supporting level.
    current.plan()
    candidate.plan()
    result = merge(proposal(base, candidate, "b"), current)
    assert not result.clean
    assert kinds(result) == {"dependency_overlap"}
    assert output_id("merge", "b", "wall") in result.to_dict()["conflicts"][0]["op_ids"]


@pytest.mark.parametrize("op", [{"op": "future_unknown"},
                               {"op": "create_wall", "level": {"by": "name", "value": "External"}}])
def test_incomplete_dependency_analysis_blocks_divergent_merge_but_not_claimed_draft_load(op):
    base = root()
    base = base.replace_instance(ModuleInstance("c", "explicit", {"unknown": op}),
                                 expected_revision=base.revision_id)
    change = proposal(base, edit(base, "b", 4500), "b")
    assert merge(ChangeProposal.loads(change.dumps()), base).clean
    assert kinds(merge(change, edit(base, "a", 500))) == {"dependency_analysis_incomplete"}


def test_global_context_change_is_owned_and_conflicts_with_parallel_geometry_edit():
    base = root()
    candidate = base.revise(expected_revision=base.revision_id, metadata={"units": "m"})
    with pytest.raises(ProposalError, match="scope"):
        proposal(base, candidate, "a")
    change = proposal(base, candidate, scope=ProposalScope(project_fields=("metadata",)))
    assert kinds(merge(change, edit(base, "a", 500))) == {"dependency_overlap"}


def test_order_is_not_sorted_to_resolve_concurrent_insertions():
    base = root()
    additions = [ModuleInstance(key, "explicit", {"level": sdk.create_level(elev_mm=9000, name=key)})
                 for key in ("d", "e")]
    current = base.with_instances((*base.instances, additions[0]), expected_revision=base.revision_id)
    candidate = base.with_instances((*base.instances, additions[1]), expected_revision=base.revision_id)
    with pytest.raises(ProposalError, match="scope"):
        proposal(base, candidate, "e")
    change = proposal(base, candidate, scope=ProposalScope(instances=("e",), project_fields=("instance_order",)))
    result = merge(change, current)
    assert not result.clean
    assert any(row["path"] == "instance_order" for row in result.to_dict()["conflicts"])


def test_single_insertion_merges_with_unrelated_existing_instance_edit():
    base = root()
    new = ModuleInstance("d", "explicit", {"level": sdk.create_level(elev_mm=9000, name="d")})
    candidate = base.with_instances((*base.instances, new), expected_revision=base.revision_id)
    change = proposal(base, candidate, scope=ProposalScope(instances=("d",), project_fields=("instance_order",)))
    result = merge(change, edit(base, "a", 500))
    assert result.clean
    assert [instance.key for instance in result.revision.instances] == ["a", "b", "c", "d"]


def test_delete_modify_conflict_and_disjoint_deletion_preservation():
    base = root()
    candidate = base.with_instances(base.instances[1:], expected_revision=base.revision_id)
    change = proposal(base, candidate, scope=ProposalScope(instances=("a",), project_fields=("instance_order",)))
    assert "delete_modify" in kinds(merge(change, edit(base, "a", 500)))
    result = merge(change, edit(base, "b", 4500))
    assert result.clean
    assert set(bodies(result.revision)) == {"b", "c"}


def test_recipe_definition_and_evaluation_are_never_synthesized_from_different_sides():
    pin = RecipePin("def build(): raise RuntimeError('never execute on load')", "a" * 64)
    definition = ModuleDefinition("recipe", "sealed_evaluation", pin)
    base = ProjectRevision("merge", [definition], [ModuleInstance("a", "recipe", {"level": sdk.create_level(elev_mm=0)})])
    changed_definition = replace(definition, recipe=replace(pin, source=pin.source + "\n# new"))
    candidate = base.revise(expected_revision=base.revision_id, modules=(changed_definition,),
                            instances=(replace(base.instances[0], module_digest=None),))
    grant = ProposalScope(instances=("a",), modules=("recipe",))
    change = proposal(base, candidate, scope=grant)
    loaded = ChangeProposal.loads(change.dumps())
    current = base.replace_instance(replace(base.instances[0], parameters={"height": 500}), expected_revision=base.revision_id)
    assert not merge(loaded, current).clean
    assert merge(loaded, base).revision.modules[0].recipe.source == changed_definition.recipe.source


def test_body_references_remain_inert_and_only_changed_instance_is_replaced(monkeypatch):
    base = root().upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root().revision_id)
    body = ModuleInstance("a", "explicit", (NamedOutput("body", {"op": "create_directshape", "category": "mass"},
                                                  BodyRepresentation("a" * 64, "b" * 64)),))
    base = base.replace_instance(body, expected_revision=base.revision_id)
    updated = replace(body, outputs=(replace(body.outputs[0], geometry=BodyRepresentation("c" * 64, "d" * 64)),))
    candidate = base.replace_instance(updated, expected_revision=base.revision_id)
    monkeypatch.setattr(ProjectRevision, "to_program", lambda *_: pytest.fail("merge resolved bodies"))
    result = merge(proposal(base, candidate, "a"), edit(base, "b", 4500))
    assert result.clean
    assert result.revision.instances[0].outputs[0].geometry.bundle_sha256 == "c" * 64


def test_store_acceptance_proves_ancestry_persists_merged_parent_and_retries_without_rewind(tmp_path):
    base = root()
    store = ProjectStore.create(tmp_path / "project.db", base)
    change = ChangeProposal.loads(proposal(base, edit(base, "b", 4500), "b").dumps())
    current = edit(base, "a", 500)
    store.commit(current, expected_revision=base.revision_id)
    result = accept_proposal(store, change, expected_revision=current.revision_id, authorized_scope=change.scope)
    assert result.commit.inserted
    assert result.merge.to_dict()["ancestry"] == "verified_stored_history"
    assert store.head().dumps() == result.merge.revision.dumps()
    assert len(store.history()) == 3
    repeated = accept_proposal(store, change, expected_revision=store.head().revision_id, authorized_scope=change.scope)
    assert not repeated.commit.inserted
    assert len(store.history()) == 3


def test_stale_head_or_unstored_base_refuses_without_data_loss(tmp_path):
    base = root()
    store = ProjectStore.create(tmp_path / "project.db", base)
    child = edit(base, "a", 500)
    change = proposal(child, edit(child, "b", 4500), "b")
    with pytest.raises(StoreConflict, match="history"):
        accept_proposal(store, change, expected_revision=base.revision_id, authorized_scope=change.scope)
    store.commit(child, expected_revision=base.revision_id)
    with pytest.raises(StoreConflict, match="head"):
        accept_proposal(store, change, expected_revision=base.revision_id, authorized_scope=change.scope)
    assert store.head().dumps() == child.dumps()


def test_conflict_never_creates_a_partial_stored_revision(tmp_path):
    base = root()
    store = ProjectStore.create(tmp_path / "project.db", base)
    current = edit(base, "a", 500)
    store.commit(current, expected_revision=base.revision_id)
    change = proposal(base, edit(base, "a", 800), "a")
    result = accept_proposal(store, change, expected_revision=current.revision_id, authorized_scope=change.scope)
    assert result.commit is None and result.merge.revision is None
    assert store.head().dumps() == current.dumps()
    assert len(store.history()) == 2


def test_writer_between_ancestry_read_and_commit_is_still_refused_by_real_cas(tmp_path, monkeypatch):
    base = root()
    path = tmp_path / "project.db"
    store = ProjectStore.create(path, base)
    change = proposal(base, edit(base, "b", 4500), "b")
    neighbor = edit(base, "a", 500)
    original_history = ProjectStore.history
    def history_then_race(self):
        observed = original_history(self)
        ProjectStore.open(path, readonly=False).commit(neighbor, expected_revision=base.revision_id)
        return observed
    monkeypatch.setattr(ProjectStore, "history", history_then_race)
    with pytest.raises(StoreConflict):
        accept_proposal(store, change, expected_revision=base.revision_id, authorized_scope=change.scope)
    assert store.head().dumps() == neighbor.dumps()
    assert len(original_history(store)) == 2


def test_stored_ancestry_can_span_multiple_independent_revisions(tmp_path):
    base = root()
    store = ProjectStore.create(tmp_path / "project.db", base)
    change = proposal(base, edit(base, "b", 4500), "b")
    for key, elevation in (("a", 500), ("c", 6500)):
        head = store.head()
        store.commit(edit(head, key, elevation), expected_revision=head.revision_id)
    result = accept_proposal(store, change, expected_revision=store.head().revision_id, authorized_scope=change.scope)
    assert result.commit.inserted
    assert [instance.outputs[0].operation["elev_mm"] for instance in store.head().instances] == [500, 4500, 6500]
    assert len(store.history()) == 4


def test_exact_concurrent_redelivery_reports_later_head_without_rewinding(tmp_path, monkeypatch):
    base = root()
    path = tmp_path / "project.db"
    store = ProjectStore.create(path, base)
    change = proposal(base, edit(base, "b", 4500), "b")
    later = edit(change.candidate, "c", 6500)
    original_history = ProjectStore.history
    def history_then_identical_delivery(self):
        observed = original_history(self)
        other = ProjectStore.open(path, readonly=False)
        other.commit(change.candidate, expected_revision=base.revision_id)
        other.commit(later, expected_revision=change.candidate.revision_id)
        return observed
    monkeypatch.setattr(ProjectStore, "history", history_then_identical_delivery)
    result = accept_proposal(store, change, expected_revision=base.revision_id, authorized_scope=change.scope)
    assert result.merge.clean
    assert result.merge.revision.revision_id == change.candidate.revision_id
    assert result.commit.inserted is False
    assert result.commit.head_revision == later.revision_id
    assert store.head().dumps() == later.dumps()
    assert len(original_history(store)) == 3


def _racing_writer(path, serialized, expected, barrier, results):
    change = ChangeProposal.loads(serialized)
    store = ProjectStore.open(path, readonly=False)
    barrier.wait(timeout=15)
    try:
        accepted = accept_proposal(store, change, expected_revision=expected, authorized_scope=change.scope)
        results.put(("accepted", accepted.commit.revision_id))
    except StoreConflict:
        results.put(("conflict", None))


def test_two_actual_processes_cannot_overwrite_the_same_expected_head(tmp_path):
    base = root()
    path = str(tmp_path / "project.db")
    store = ProjectStore.create(path, base)
    changes = [proposal(base, edit(base, key, value), key) for key, value in (("a", 500), ("b", 4500))]
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    workers = [context.Process(target=_racing_writer, args=(path, item.dumps(), base.revision_id, barrier, results))
               for item in changes]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    outcomes = [results.get(timeout=2)[0] for _ in workers]
    assert sorted(outcomes) == ["accepted", "conflict"]
    assert len(store.history()) == 2
    # Deliberate rebase on the new expected head combines both independent edits.
    missing = next(item for item in changes if bodies(store.head())[item.scope.instances[0]]
                   != bodies(item.candidate)[item.scope.instances[0]])
    accepted = accept_proposal(store, missing, expected_revision=store.head().revision_id, authorized_scope=missing.scope)
    assert accepted.commit.inserted
    assert bodies(store.head())["a"] == bodies(changes[0].candidate)["a"]
    assert bodies(store.head())["b"] == bodies(changes[1].candidate)["b"]
    assert len(store.history()) == 3
