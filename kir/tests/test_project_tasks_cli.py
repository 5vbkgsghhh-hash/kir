"""Restarted CLI task lifecycle is durable authoring, not an agent runner."""
import json

import pytest

from kir import __main__ as cli
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.tests.test_project_cli_lifecycle import _call, _fresh, _successful
from kir.tests.test_project_proposal_cli import project, proposal, change


def command(store, action, *args):
    return ["project", "task-" + action, str(store.path), *args]


def setup_task(tmp_path, *, grant=True):
    base = project()
    store = ProjectStore.create(tmp_path / "tasks.sqlite", base)
    upgraded = _successful(_fresh(command(store, "upgrade", "--expected", base.revision_id)))
    assert upgraded["upgraded"] and upgraded["schema"] == TASK_STORE_SCHEMA
    result = _successful(_fresh(command(store, "create", "design", "--base", base.revision_id,
        "--actor", "agent", "--objective", "Raise a level", "--tool", "read", "--max-tokens", "5000",
        *(["--allow-instance", "a"] if grant else []))))
    return base, store, result["task"]


def mutation(store, action, task, request_id, *args, actor="agent"):
    return command(store, action, task["task_id"], *args, "--expected-task-version", task["version"],
        "--generation", str(task["generation"]), "--actor", actor, "--request-id", request_id)


def test_restart_checkpoint_submit_decide_read_history(tmp_path):
    base, store, assigned = setup_task(tmp_path)
    assert assigned["assignment"]["budgets"] == {"max_tokens": 5000}
    checkpoint = _successful(_fresh(mutation(store, "checkpoint", assigned, "check-1", "-"),
                                    '{"next":"submit proposal","source":"inert.py"}'))
    checked = checkpoint["task"]
    value = proposal(base)
    submitted = _successful(_fresh(mutation(store, "submit", checked, "submit-1", "-"), value.dumps()))
    assert store.head().revision_id == base.revision_id
    decide = mutation(store, "decide", submitted["task"], "decide-1", "--proposal-id", value.proposal_id,
                      "--expected", base.revision_id, actor="coordinator")
    accepted = _successful(_fresh(decide))
    assert accepted["task"]["state"] == "accepted" and accepted["native_published"] is False
    assert store.head().revision_id == value.candidate.revision_id
    assert _successful(_fresh(decide))["inserted"] is False
    before = store.path.read_bytes()
    read = _successful(_fresh(command(store, "read", "design")))
    assert read == accepted["task"]
    assert read["execution"] == "not_observed" and read["budget_enforcement"] == "not_established"
    events = _successful(_fresh(command(store, "history", "design")))["events"]
    assert [e["kind"] for e in events] == ["assign", "checkpoint", "submit", "decide"]
    assert len(_successful(_fresh(command(store, "list")))["tasks"]) == 1
    assert store.path.read_bytes() == before


def test_conflicted_decision_is_persisted_but_returns_one(tmp_path):
    base, store, task = setup_task(tmp_path)
    value = proposal(base)
    submitted = _successful(_fresh(mutation(store, "submit", task, "submit", "-"), value.dumps()))["task"]
    winner = change(base, "a", 4200)
    store.commit(winner, expected_revision=base.revision_id)
    code, output, error = _fresh(mutation(store, "decide", submitted, "decide", "--proposal-id",
        value.proposal_id, "--expected", winner.revision_id, actor="coordinator"))
    assert code == cli.REFUSED, error
    result = json.loads(output)
    assert result["task"]["state"] == "conflicted" and result["inserted"]
    assert store.head().revision_id == winner.revision_id
    assert _successful(_fresh(command(store, "read", "design")))["decision"]["merge"]["status"] == "conflict"


def test_reassign_and_revoke_fence_old_worker(tmp_path):
    _, store, task = setup_task(tmp_path)
    reassigned = _successful(_fresh(mutation(store, "reassign", task, "move", "--new-actor", "new-agent",
        "--reason", "handoff", actor="coordinator")))["task"]
    assert reassigned["generation"] == 1 and reassigned["actor"] == "new-agent"
    before = store.path.read_bytes()
    code, output, _ = _fresh(mutation(store, "checkpoint", task, "old", "-"), "{}")
    assert code == cli.REFUSED and not output and store.path.read_bytes() == before
    revoked = _successful(_fresh(mutation(store, "revoke", reassigned, "stop", "--reason", "cancel work",
                                           actor="coordinator")))["task"]
    assert revoked["state"] == "revoked" and revoked["generation"] == 2


def test_no_implicit_upgrade_or_grant(tmp_path):
    base = project()
    store = ProjectStore.create(tmp_path / "old.sqlite", base)
    before = store.path.read_bytes()
    code, output, _ = _fresh(command(store, "create", "design", "--base", base.revision_id,
                                     "--actor", "agent", "--objective", "test"))
    assert code == cli.NOT_DONE and not output and store.path.read_bytes() == before
    base, store, task = setup_task(tmp_path, grant=False)
    before = store.path.read_bytes()
    code, output, _ = _fresh(mutation(store, "submit", task, "self-grant", "-"), proposal(base).dumps())
    assert code == cli.NOT_DONE and not output and store.path.read_bytes() == before


@pytest.mark.parametrize("action,extra", [("read", ["missing"]), ("list", []), ("history", ["missing"]),
    ("upgrade", ["--expected", "0" * 64])])
def test_missing_database_never_created(tmp_path, action, extra):
    path = tmp_path / "missing.sqlite"
    code, output, error = _fresh(["project", "task-" + action, str(path), *extra])
    assert code == cli.NOT_DONE and not output and error and "Traceback" not in error
    assert not path.exists()


@pytest.mark.parametrize("source", ["null", "[]", '{"x":1,"x":2}', "{", '{"x":NaN}'])
def test_invalid_checkpoint_preserves_history(tmp_path, source):
    _, store, task = setup_task(tmp_path)
    before = store.path.read_bytes()
    code, output, error = _fresh(mutation(store, "checkpoint", task, "bad", "-"), source)
    assert code == cli.NOT_DONE and not output and error and "Traceback" not in error
    assert store.path.read_bytes() == before


def test_checkpoint_input_is_bounded_before_json_parse(tmp_path, monkeypatch):
    from kir import project_tasks
    _, store, task = setup_task(tmp_path)
    monkeypatch.setattr(project_tasks, "MAX_CHECKPOINT_BYTES", 20)
    code, output, error = _call(mutation(store, "checkpoint", task, "large", "-"), '{"note":"' + "я" * 30 + '"}')
    assert code == cli.NOT_DONE and not output and "byte budget" in error


def test_wrong_expected_head_does_not_decide(tmp_path):
    base, store, task = setup_task(tmp_path)
    value = proposal(base)
    submitted = _successful(_fresh(mutation(store, "submit", task, "submit", "-"), value.dumps()))["task"]
    before = store.path.read_bytes()
    code, output, _ = _fresh(mutation(store, "decide", submitted, "decide", "--proposal-id", value.proposal_id,
                                     "--expected", "0" * 64, actor="coordinator"))
    assert code == cli.REFUSED and not output and store.path.read_bytes() == before


def test_geometry_submission_retains_asset_for_later_decision(tmp_path):
    pytest.importorskip("OCP")
    from kir.project_merge import ChangeProposal, ProposalScope
    from kir.project_store import GEOMETRY_STORE_SCHEMA
    from kir.tests.test_geometry_materialization import capture, project_for

    original, changed = capture(1000), capture(1500)
    base = project_for(original)
    candidate = base.replace_instance(project_for(changed).instances[0], expected_revision=base.revision_id)
    key = candidate.instances[0].key
    value = ChangeProposal(base, candidate, ProposalScope(instances=(key,)), "geometry-agent", "resize")
    store = ProjectStore.create(tmp_path / "geometry.sqlite", base, schema=GEOMETRY_STORE_SCHEMA, assets=[original])
    _successful(_fresh(command(store, "upgrade", "--expected", base.revision_id)))
    task = _successful(_fresh(command(store, "create", "geometry", "--base", base.revision_id,
        "--actor", "geometry-agent", "--objective", "resize", "--allow-instance", key)))["task"]
    asset_file = tmp_path / "asset.json"
    asset_file.write_text(changed.dumps(), encoding="utf-8")
    submit = mutation(store, "submit", task, "submit", "-", actor="geometry-agent")
    before = store.path.read_bytes()
    code, output, error = _fresh(submit, value.dumps())
    assert code == cli.NOT_DONE and not output and "missing" in error
    assert store.path.read_bytes() == before
    submitted = _successful(_fresh([*submit, "--asset", str(asset_file)], value.dumps()))["task"]
    assert store.head().revision_id == base.revision_id
    assert store.get_asset(changed.digest).dumps() == changed.dumps()
    accepted = _successful(_fresh(mutation(store, "decide", submitted, "decide", "--proposal-id", value.proposal_id,
        "--expected", base.revision_id, actor="coordinator")))
    assert accepted["task"]["state"] == "accepted" and store.head().revision_id == candidate.revision_id


def test_mutations_require_explicit_fences(tmp_path):
    _, store, task = setup_task(tmp_path)
    before = store.path.read_bytes()
    code, output, error = _fresh(command(store, "checkpoint", task["task_id"], "-"), "{}")
    assert code == cli.NOT_DONE and not output and "required" in error
    assert store.path.read_bytes() == before
