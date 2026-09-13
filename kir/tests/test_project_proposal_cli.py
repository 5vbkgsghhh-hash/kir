"""Actual CLI proposal transport and stored CAS, without native publication."""
import json

import pytest

from kir import __main__ as cli
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_store import ProjectStore
from kir.tests.test_project_cli_lifecycle import _call, _fresh


def project():
    return ProjectRevision("proposal-cli", [ModuleDefinition("m")], [
        ModuleInstance(key, "m", {"level": {"op": "create_level", "elev_mm": 0}}) for key in ("a", "b")])


def change(base, key, elevation):
    return base.replace_instance(ModuleInstance(key, "m", {"level": {"op": "create_level", "elev_mm": elevation}}),
                                 expected_revision=base.revision_id)


def proposal(base, key="a", elevation=3000):
    return ChangeProposal(base, change(base, key, elevation), ProposalScope(instances=(key,)), "agent", "Raise level")


def test_inspect_is_inert_and_cannot_claim_authentication_or_native_success():
    value = proposal(project())
    code, output, error = _fresh(["project", "proposal-inspect", "-"], value.dumps())
    assert code == cli.ANSWERED, error
    result = json.loads(output)
    assert result["proposal_id"] == value.proposal_id
    assert result["declared_scope"] == value.scope.to_dict()
    assert result["author_authenticated"] is False and result["native_published"] is False
    assert result["semantic_validation"] == "not_run"


def test_two_agents_proposals_merge_through_fresh_cli_and_preserve_history(tmp_path):
    base = project()
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    first, second = proposal(base, "a", 3000), proposal(base, "b", 4000)
    for value, expected in ((first, base.revision_id), (second, first.candidate.revision_id)):
        code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", expected,
                                     "--allow-instance", value.scope.instances[0]], value.dumps())
        assert code == cli.ANSWERED, error
        result = json.loads(output)
        assert result["commit"]["inserted"] is True
        assert result["merge"]["ancestry"] == "verified_stored_history"
        assert result["native_published"] is False and result["proposal_log_persisted"] is False
    assert [item.outputs[0].operation["elev_mm"] for item in store.head().instances] == [3000, 4000]
    assert len(store.history()) == 3
    assert store.get(base.revision_id).dumps() == base.dumps()


@pytest.mark.parametrize("grant", [[], ["--allow-instance", "b"], ["--allow-module", "m"]])
def test_proposal_cannot_supply_its_own_caller_grant(tmp_path, grant):
    base = project()
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    before = store.path.read_bytes()
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", base.revision_id,
                                  *grant], proposal(base).dumps())
    assert code == cli.REFUSED and not output and error
    assert store.path.read_bytes() == before


def test_overlapping_proposal_returns_machine_readable_conflict_without_writing(tmp_path):
    base = project()
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    winner = change(base, "a", 4200)
    store.commit(winner, expected_revision=base.revision_id)
    before = store.path.read_bytes()
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", winner.revision_id,
                                 "--allow-instance", "a"], proposal(base).dumps())
    assert code == cli.REFUSED, error
    result = json.loads(output)
    assert result["commit"] is None and result["merge"]["status"] == "conflict"
    assert result["merge"]["conflicts"] and result["merge"]["result_revision"] is None
    assert store.path.read_bytes() == before


def test_stale_expected_head_is_not_replaced_by_cli_observation(tmp_path):
    base = project()
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    store.commit(change(base, "b", 1000), expected_revision=base.revision_id)
    before = store.path.read_bytes()
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", base.revision_id,
                                 "--allow-instance", "a"], proposal(base).dumps())
    assert code == cli.REFUSED and not output and error
    assert store.path.read_bytes() == before


def test_exact_redelivery_at_current_head_is_not_another_revision(tmp_path):
    base = project()
    value = proposal(base)
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    store.commit(value.candidate, expected_revision=base.revision_id)
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", value.candidate.revision_id,
                                 "--allow-instance", "a"], value.dumps())
    assert code == cli.ANSWERED, error
    assert json.loads(output)["commit"]["inserted"] is False and len(store.history()) == 2


@pytest.mark.parametrize("raw", ["not JSON", "null", "{}", '{"schema": 1, "schema": 2}'])
def test_malformed_proposal_never_creates_database(tmp_path, raw):
    path = tmp_path / "missing.sqlite"
    code, output, error = _call(["project", "proposal-accept", str(path), "-", "--expected", "0" * 64], raw)
    assert code == cli.NOT_DONE and not output and error
    assert not path.exists()


def test_valid_proposal_cannot_implicitly_create_missing_store(tmp_path):
    base = project()
    path = tmp_path / "missing.sqlite"
    code, output, error = _fresh(["project", "proposal-accept", str(path), "-", "--expected", base.revision_id,
                                 "--allow-instance", "a"], proposal(base).dumps())
    assert code == cli.NOT_DONE and not output and error
    assert not path.exists()


@pytest.mark.parametrize("asset", ["missing.json", "malformed.json"])
def test_bad_explicit_asset_does_not_commit(tmp_path, asset):
    base = project()
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    path = tmp_path / asset
    if asset == "malformed.json":
        path.write_text("{}", encoding="utf-8")
    before = store.path.read_bytes()
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", base.revision_id,
                                 "--allow-instance", "a", "--asset", str(path)], proposal(base).dumps())
    assert code == cli.NOT_DONE and not output and error
    assert "Traceback" not in error
    assert store.path.read_bytes() == before


def test_empty_grant_can_only_accept_a_proposal_declaring_no_scope(tmp_path):
    base = project()
    value = ChangeProposal(base, base, ProposalScope(), "agent", "No changes")
    store = ProjectStore.create(tmp_path / "project.sqlite", base)
    code, output, error = _fresh(["project", "proposal-accept", str(store.path), "-", "--expected", base.revision_id], value.dumps())
    assert code == cli.ANSWERED, error
    assert json.loads(output)["commit"]["inserted"] is False and len(store.history()) == 1


def test_actual_geometry_asset_and_revision_are_accepted_together_without_native_reexecution(tmp_path):
    pytest.importorskip("OCP")
    from kir.project_store import GEOMETRY_STORE_SCHEMA
    from kir.tests.test_geometry_materialization import capture, project_for

    asset = capture(1000)
    base = project_for(asset)
    changed_asset = capture(1500, source_lineage=(asset.digest,))
    candidate = base.replace_instance(project_for(changed_asset).instances[0], expected_revision=base.revision_id)
    key = candidate.instances[0].key
    value = ChangeProposal(base, candidate, ProposalScope(instances=(key,)), "geometry-agent", "Resize body")
    store = ProjectStore.create(tmp_path / "geometry.sqlite", base, schema=GEOMETRY_STORE_SCHEMA, assets=[asset])
    asset_path = tmp_path / "changed-bundle.json"
    asset_path.write_text(changed_asset.dumps(), encoding="utf-8")
    command = ["project", "proposal-accept", str(store.path), "-", "--expected", base.revision_id,
               "--allow-instance", key]
    before = store.path.read_bytes()
    code, output, error = _fresh(command, value.dumps())
    assert code == cli.NOT_DONE and not output and "missing" in error
    assert store.path.read_bytes() == before
    code, output, error = _fresh([*command, "--asset", str(asset_path)], value.dumps())
    assert code == cli.ANSWERED, error
    assert json.loads(output)["native_published"] is False
    assert store.head().dumps() == candidate.dumps()
    assert store.get_asset(changed_asset.digest).dumps() == changed_asset.dumps()
    assert store.get_asset(asset.digest).dumps() == asset.dumps()
    assert len(store.history()) == 2
