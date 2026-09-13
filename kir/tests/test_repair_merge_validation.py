"""A repair must validate the merged revision that its CAS will save.

These are small, real ProjectStore/OCP scenes. Interleavings use a second store
handle so the failure is deterministic instead of depending on thread timing.
No native model or external service is involved.
"""
from dataclasses import replace

import pytest

pytest.importorskip("OCP")

from examples import podium_passage as example
from kir.clash import project_analysis
from kir.project import BodyRepresentation, output_id
from kir import project_fix
from kir.project_store import ProjectStore, StoreConflict


FAR_BOX = ((100000., 100000., 100000.), (101000., 101000., 101000.))


@pytest.fixture
def scene(tmp_path):
    return example.save(tmp_path / "repair.sqlite", extra=(("canopy", FAR_BOX),))


def _instance(revision, key):
    return next(item for item in revision.instances if item.key == key)


def _propose(store):
    before = project_analysis.analyze_project(store, exact=True)
    podium = output_id(example.PROJECT_ID, "podium", "podium")
    passage = output_id(example.PROJECT_ID, "passage", "passage")
    hit = next(f for f in before.findings
               if {f.a_output_id, f.b_output_id} == {podium, passage})
    proposal, asset = project_fix.propose_fix(
        store, before, hit.finding_id, move=passage,
        rebuild=example.rebuild_body)
    return before, proposal, asset


def _move_canopy(store, bounds):
    other = ProjectStore.open(store.path, readonly=False)
    head = other.head()
    previous = _instance(head, "canopy")
    parameters = {"canopy": [list(bounds[0]), list(bounds[1])]}
    bundle = example.rebuild_body("canopy", parameters["canopy"], parameters)
    output = replace(previous.outputs[0],
                     geometry=BodyRepresentation(bundle.digest, bundle.body_digest))
    changed = replace(previous, parameters=parameters, outputs=(output,))
    revision = head.replace_instance(changed, expected_revision=head.revision_id)
    other.commit(revision, expected_revision=head.revision_id, assets=[bundle])
    return revision


def _above_passage():
    (x0, y0, _z0), (x1, y1, z1) = example.PASSAGE
    return ((x0 - 500., y0 - 500., z1 + 200.),
            (x1 + 500., y1 + 500., z1 + 900.))


def test_new_neighbour_since_proposal_is_checked_before_commit(scene):
    _before, proposal, asset = _propose(scene)
    intervening = _move_canopy(scene, _above_passage())
    passage_before = _instance(intervening, "passage").to_dict()

    with pytest.raises(project_fix.FixError, match="fix_creates_new_conflict"):
        project_fix.apply_fix(scene, proposal, assets=[asset])

    assert scene.head().revision_id == intervening.revision_id
    assert _instance(scene.head(), "passage").to_dict() == passage_before


def test_safe_concurrent_change_is_merged_and_the_saved_result_was_analyzed(
        scene, monkeypatch):
    _before, proposal, asset = _propose(scene)
    intervening = _move_canopy(
        scene, ((110000., 100000., 100000.), (111000., 101000., 101000.)))
    analyzed = []
    original = project_analysis.analyze_revision

    def observe(revision, *args, **kwargs):
        analyzed.append(revision.revision_id)
        return original(revision, *args, **kwargs)

    monkeypatch.setattr(project_analysis, "analyze_revision", observe)
    saved = project_fix.apply_fix(scene, proposal, assets=[asset])
    head = scene.head()
    assert saved == head.revision_id
    assert saved in analyzed, "the merged saved payload, not the old candidate, must be checked"
    assert intervening.revision_id in analyzed, "the baseline must include the current neighbour"
    assert _instance(head, "canopy").to_dict() == _instance(intervening, "canopy").to_dict()
    assert _instance(head, "passage").to_dict() == _instance(proposal.revision, "passage").to_dict()


def test_existing_conflict_in_current_head_is_not_blame_for_the_repair(scene):
    _before, proposal, asset = _propose(scene)
    # This adds a conflict with the pier, away from the repaired passage.
    intervening = _move_canopy(
        scene, ((41000., 1000., -2500.), (41500., 2000., -1500.)))
    current_report = project_analysis.analyze_project(scene, exact=True)
    canopy = output_id(example.PROJECT_ID, "canopy", "canopy")
    assert any(canopy in (f.a_output_id, f.b_output_id)
               and project_fix._is_conflict(f) for f in current_report.findings)

    saved = project_fix.apply_fix(scene, proposal, assets=[asset])
    assert saved == scene.head().revision_id
    assert _instance(scene.head(), "canopy").to_dict() == _instance(intervening, "canopy").to_dict()


def test_head_change_after_analysis_cannot_be_silently_merged(scene, monkeypatch):
    _before, proposal, asset = _propose(scene)
    interleaving = {}
    original = project_fix._verify_no_new_conflicts

    def advance_after_check(*args, **kwargs):
        original(*args, **kwargs)
        interleaving["head"] = _move_canopy(scene, _above_passage())

    monkeypatch.setattr(project_fix, "_verify_no_new_conflicts", advance_after_check)
    with pytest.raises(StoreConflict):
        project_fix.apply_fix(scene, proposal, assets=[asset])

    assert scene.head().revision_id == interleaving["head"].revision_id
    assert _instance(scene.head(), "passage").to_dict() == _instance(proposal.change.base, "passage").to_dict()


def test_explicit_stale_expected_revision_refuses_before_geometry(scene, monkeypatch):
    before, proposal, asset = _propose(scene)
    intervening = _move_canopy(scene, _above_passage())

    def unexpected_analysis(*args, **kwargs):
        pytest.fail("known stale input must refuse before kernel work")

    monkeypatch.setattr(project_fix, "_verify_no_new_conflicts", unexpected_analysis)
    with pytest.raises(StoreConflict):
        project_fix.apply_fix(scene, proposal, expected_revision=before.revision,
                              assets=[asset])
    assert scene.head().revision_id == intervening.revision_id


def test_exact_redelivery_returns_checked_revision_not_a_later_head(scene, monkeypatch):
    _before, proposal, asset = _propose(scene)
    original_commit = ProjectStore.commit
    raced = {}

    def commit_same_then_advance(store, revision, *, expected_revision, assets=()):
        if not raced and store.path == scene.path:
            raced["checked"] = revision.revision_id
            other = ProjectStore.open(store.path, readonly=False)
            original_commit(other, revision, expected_revision=expected_revision, assets=assets)
            raced["head"] = _move_canopy(
                other, ((110000., 100000., 100000.), (111000., 101000., 101000.)))
        return original_commit(store, revision, expected_revision=expected_revision, assets=assets)

    monkeypatch.setattr(ProjectStore, "commit", commit_same_then_advance)
    saved = project_fix.apply_fix(scene, proposal, assets=[asset])

    assert saved == raced["checked"]
    assert saved != raced["head"].revision_id
    assert scene.get(saved).revision_id == saved
    assert scene.head().revision_id == raced["head"].revision_id


def test_one_pass_asset_iterable_is_shared_by_validation_and_commit(scene):
    _before, proposal, asset = _propose(scene)
    supplied = []

    def once():
        supplied.append(asset.digest)
        yield asset

    saved = project_fix.apply_fix(scene, proposal, assets=once())
    assert supplied == [asset.digest]
    assert scene.get(saved).revision_id == saved
    assert scene.get_asset(asset.digest).body_digest == asset.body_digest
