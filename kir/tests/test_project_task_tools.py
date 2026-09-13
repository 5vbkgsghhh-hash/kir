"""Durable pre-invocation admission, exact results and explicit unknown handling."""
import pytest

from kir import project_tasks as tasks
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA, StoreConflict
from kir.tests.test_project_merge import root, edit


def case(tmp_path, *, budget=2, tools=("author.python",)):
    base = root()
    store = ProjectStore.create(tmp_path / "tasks.sqlite", base, schema=TASK_STORE_SCHEMA)
    task = tasks.create_task(store, task_id="a", base_revision=base.revision_id, actor="worker",
        objective="Evaluate a recipe", scope=ProposalScope(instances=("a",)), tools=tools,
        budgets={} if budget is None else {"max_tool_calls": budget})["task"]
    return store, base, task


def begin(store, task, request_id="eval"):
    return tasks.begin_task_tool(store, "a", request_id=request_id, expected_version=task["version"],
        generation=task["generation"], actor=task["actor"], tool="author.python", arguments={"source": "ops=[]"})


def finish(store, task, output=None, request_id="eval"):
    return tasks.finish_task_tool(store, "a", request_id="finish-" + request_id,
        expected_version=task["version"], generation=task["generation"], actor=task["actor"],
        tool_request_id=request_id, output={"ok": True} if output is None else output)


@pytest.mark.parametrize("budget,tools", [(0, ("author.python",)), (None, ("author.python",)), (3, ())])
def test_no_implicit_tool_or_call_budget(tmp_path, budget, tools):
    store, _, task = case(tmp_path, budget=budget, tools=tools)
    before = store.path.read_bytes()
    with pytest.raises(tasks.TaskError):
        begin(store, task)
    assert store.path.read_bytes() == before


def test_one_charge_per_request_and_no_new_work_until_result(tmp_path):
    store, _, task = case(tmp_path, budget=1)
    started = begin(store, task)
    assert started["inserted"] and started["task"]["pending_tool"] == "eval"
    assert started["task"]["tool_calls"][0]["state"] == "reserved"
    repeated = begin(store, task)
    assert not repeated["inserted"] and len(repeated["task"]["tool_calls"]) == 1
    with pytest.raises(tasks.TaskError, match="unresolved"):
        begin(store, started["task"], "parallel")
    with pytest.raises(tasks.TaskError, match="unresolved"):
        tasks.checkpoint_task(store, "a", request_id="checkpoint", expected_version=started["task"]["version"], generation=0, actor="worker", notes={})
    completed = finish(store, started["task"])
    assert completed["task"]["pending_tool"] is None
    assert completed["task"]["tool_calls"][0]["output"] == {"ok": True}
    with pytest.raises(tasks.TaskError, match="budget"):
        begin(store, completed["task"], "second")
    assert len(tasks.task_history(store, "a")) == 3


@pytest.mark.parametrize("resolution", ["reassign", "revoke", "abandon"])
def test_explicit_supersession_never_means_stopped_or_refunds_budget(tmp_path, resolution):
    store, _, initial = case(tmp_path, budget=1)
    reserved = begin(store, initial)["task"]
    kwargs = dict(request_id="resolve", expected_version=reserved["version"], generation=0, actor="coordinator", reason="explicit unresolved outcome")
    if resolution == "reassign":
        result = tasks.reassign_task(store, "a", new_actor="worker", **kwargs)
    elif resolution == "revoke":
        result = tasks.revoke_task(store, "a", **kwargs)
    else:
        result = tasks.abandon_task_tool(store, "a", tool_request_id="eval", **kwargs)
    current = result["task"]
    assert current["pending_tool"] is None
    assert current["tool_calls"][0]["state"] in ("superseded_unresolved", "abandoned_unresolved")
    assert current["tool_calls"][0]["output"] is None
    replay = begin(store, initial)
    assert not replay["inserted"] and replay["task"] == current
    with pytest.raises(StoreConflict):
        finish(store, reserved)
    if resolution != "revoke":
        with pytest.raises(tasks.TaskError, match="budget"):
            begin(store, current, "new")


def test_project_submit_can_name_only_exact_retained_tool_proposal(tmp_path):
    store, base, task = case(tmp_path)
    change = ChangeProposal(base, edit(base, "a", 400), ProposalScope(instances=("a",)), "worker", "from evaluation")
    reserved = begin(store, task)["task"]
    completed = finish(store, reserved, {"proposal": change.to_dict()})["task"]
    other = ChangeProposal(base, edit(base, "a", 800), change.scope, "worker", "not the output")
    kwargs = dict(request_id="submit", expected_version=completed["version"], generation=0, actor="worker", source_tool="eval")
    with pytest.raises(tasks.TaskError, match="retained tool output"):
        tasks.submit_task(store, "a", other, **kwargs)
    submitted = tasks.submit_task(store, "a", change, **kwargs)
    assert submitted["event"]["body"]["source_tool"] == "eval"
    assert len(store.history()) == 1


def test_capacity_reserves_finish_submit_and_decide(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENTS", 5)
    store, base, task = case(tmp_path)
    change = ChangeProposal(base, edit(base, "a", 400), ProposalScope(instances=("a",)), "worker", "from evaluation")
    reserved = begin(store, task)["task"]
    completed = finish(store, reserved, {"proposal": change.to_dict()})["task"]
    submitted = tasks.submit_task(store, "a", change, request_id="submit", expected_version=completed["version"], generation=0, actor="worker", source_tool="eval")["task"]
    accepted = tasks.decide_task(store, "a", request_id="decide", expected_version=submitted["version"], generation=0,
        actor="coordinator", proposal_id=change.proposal_id, expected_revision=base.revision_id)
    assert accepted["task"]["state"] == "accepted" and len(tasks.task_history(store, "a")) == 5
