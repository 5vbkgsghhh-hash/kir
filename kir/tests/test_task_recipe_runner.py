"""Actual Python recipe -> retained proposal -> restart -> authored decision."""
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from kir import task_recipe_runner as runner
from kir.project_merge import ProposalScope
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA, StoreCommitUnknown
from kir.project_tasks import create_task, read_task, task_history, decide_task, reassign_task, TaskError
from kir.tests.test_project_merge import root, bodies


POLICY = replace(runner.RECIPE_POLICY, probe_network=False)


def case(tmp_path, *, calls=3, grant_module=True):
    base = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", base, schema=TASK_STORE_SCHEMA)
    task = create_task(store, task_id="a", base_revision=base.revision_id, actor="worker",
        objective="Evaluate the parametrized level recipe", tools=("author.python",), budgets={"max_tool_calls": calls},
        scope=ProposalScope(instances=("a",), modules=("recipe-a",) if grant_module else (),
                            project_fields=("module_order",) if grant_module else ()))["task"]
    source = "\n".join([
        "p = param('project_id', 'missing')", "i = param('instance_key', 'missing')",
        "h = param('height_mm', 500.0)",
        "program = " + repr({"ir_version": base.ir_version, "intent": base.intent}),
        "program['ops'] = [{'op':'create_level','id':project_output_id(p,i,'level'),'elev_mm':h,'name':'Recipe level'}]",
    ])
    kwargs = dict(source=source, instance_key="a", module_key="recipe-a", output_keys=("level",),
        request_id="evaluate", expected_version=task["version"], generation=0, actor="worker",
        parameters={"height_mm": 700.0}, policy=POLICY)
    return store, base, kwargs


def test_actual_recipe_is_retained_once_and_new_process_submits_exact_result(tmp_path, monkeypatch):
    store, base, kwargs = case(tmp_path)
    evaluated = runner.evaluate_task_recipe(store, "a", **kwargs)
    output = evaluated["call"]["output"]
    assert evaluated["invoked"] and evaluated["recorded"], evaluated
    assert output["projection_refusal"] is None, output
    assert output["proposal"] is not None and len(store.history()) == 1
    receipt = output["evaluation"]["sandbox_receipt"]
    assert receipt["isolation"]["namespaces"] == "user+mount+net"
    assert receipt["isolation"]["filesystem"] == "chroot"
    assert output["evaluation"]["program"]["ops"][0]["elev_mm"] == 700
    assert output["evaluation"]["source"] == kwargs["source"]
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: pytest.fail("replay invoked Python"))
    replayed = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert not replayed["invoked"] and replayed["call"] == evaluated["call"]
    resumed = subprocess.run([sys.executable, "-c", """
import json,sys
from kir.project_store import ProjectStore
from kir.project_tasks import read_task,decide_task
from kir.task_recipe_runner import submit_evaluated_recipe
s=ProjectStore.open(sys.argv[1],readonly=False); t=read_task(s,'a')
t=submit_evaluated_recipe(s,'a',tool_request_id='evaluate',request_id='submit',expected_version=t['version'],generation=0,actor='worker')['task']
r=decide_task(s,'a',request_id='decide',expected_version=t['version'],generation=0,actor='coordinator',proposal_id=t['proposal']['proposal_id'],expected_revision=s.head().revision_id)
print(json.dumps(r))
""", str(store.path)], capture_output=True, text=True, timeout=30,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["task"]["state"] == "accepted"
    head = store.head()
    assert bodies(head)["b"] == bodies(base)["b"] and bodies(head)["c"] == bodies(base)["c"]
    assert head.instances[0].outputs[0].operation["elev_mm"] == 700
    assert head.instances[0].parameters["height_mm"] == 700
    assert head.modules[-1].recipe.source == kwargs["source"]
    assert head.plan().ops


def test_same_source_repeated_parameter_change_preserves_other_instances_and_recipe_pin(tmp_path):
    store, base, kwargs = case(tmp_path)
    first = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert first["call"]["output"]["projection_refusal"] is None, first
    task = runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="submit",
        expected_version=first["task"]["version"], generation=0, actor="worker")["task"]
    decide_task(store, "a", request_id="decide", expected_version=task["version"], generation=0,
        actor="coordinator", proposal_id=task["proposal"]["proposal_id"], expected_revision=base.revision_id)
    r1 = store.head()
    assigned = create_task(store, task_id="a-next", base_revision=r1.revision_id, actor="second-worker",
        objective="Change only the existing recipe parameter", tools=("author.python",), budgets={"max_tool_calls": 1},
        scope=ProposalScope(instances=("a",)))["task"]
    second = runner.evaluate_task_recipe(store, "a-next", **{**kwargs, "actor": "second-worker",
        "expected_version": assigned["version"], "parameters": {"height_mm": 1400.0}})
    assert second["call"]["output"]["projection_refusal"] is None, second
    task = runner.submit_evaluated_recipe(store, "a-next", tool_request_id="evaluate", request_id="submit",
        expected_version=second["task"]["version"], generation=0, actor="second-worker")["task"]
    decide_task(store, "a-next", request_id="decide", expected_version=task["version"], generation=0,
        actor="coordinator", proposal_id=task["proposal"]["proposal_id"], expected_revision=r1.revision_id)
    r2 = store.head()
    assert r2.instances[0].outputs[0].operation["elev_mm"] == 1400
    assert r2.modules[-1].definition_digest == r1.modules[-1].definition_digest
    for key in ("b", "c"):
        assert bodies(r2)[key] == bodies(base)[key]
    assert len(store.history()) == 3


@pytest.mark.parametrize("phase", ["before_execution", "after_execution"])
def test_pending_resume_after_hard_process_exit_never_invokes_again(tmp_path, monkeypatch, phase):
    store, _, kwargs = case(tmp_path)
    serial = {key: value for key, value in kwargs.items() if key != "policy"}
    stopped = subprocess.run([sys.executable, "-c", """
import json,os,sys
from dataclasses import replace
from kir.project_store import ProjectStore
from kir import task_recipe_runner as r
s=ProjectStore.open(sys.argv[1],readonly=False)
# The second branch really executes Python, then dies before saving the result.
if sys.argv[3]=='before_execution':
 r.execute_author_script=lambda *a,**k: os._exit(77)
else:
 def die_before_finish(*a,**k):
  assert k['output']['proposal'] is not None,k['output']
  print('computed_actual_recipe',flush=True)
  os._exit(77)
 r.finish_task_tool=die_before_finish
args=json.loads(sys.argv[2]); args['policy']=replace(r.RECIPE_POLICY,probe_network=False)
r.evaluate_task_recipe(s,'a',**args)
""", str(store.path), json.dumps(serial), phase], capture_output=True, text=True, timeout=20)
    assert stopped.returncode == 77, stopped.stderr
    if phase == "after_execution":
        assert "computed_actual_recipe" in stopped.stdout
    assert read_task(store, "a")["pending_tool"] == "evaluate"
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: pytest.fail("unknown prior outcome invoked again"))
    replayed = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert not replayed["invoked"] and replayed["call"]["state"] == "reserved"
    assert len(read_task(store, "a")["tool_calls"]) == 1


def test_finish_commit_ack_loss_replays_recorded_output_without_execution(tmp_path, monkeypatch):
    from kir import project_store as storage
    store, _, kwargs = case(tmp_path)
    commit = storage._commit
    commits = []
    def lose_result_ack(connection):
        commit(connection)
        commits.append(True)
        if len(commits) == 2:
            raise StoreCommitUnknown("result saved but acknowledgement lost")
    with monkeypatch.context() as m:
        m.setattr(storage, "_commit", lose_result_ack)
        with pytest.raises(StoreCommitUnknown):
            runner.evaluate_task_recipe(store, "a", **kwargs)
    current = read_task(store, "a")
    assert current["pending_tool"] is None and current["tool_calls"][0]["output"]["proposal"] is not None
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: pytest.fail("saved output must not execute again"))
    replayed = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert not replayed["invoked"] and replayed["call"]["state"] == "recorded"
    assert len(current["tool_calls"]) == 1


def test_soft_adapter_failure_is_retained_and_charged(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path, calls=1)
    def fail(*args, **kwargs):
        raise OSError("synthetic preparation failure")
    monkeypatch.setattr(runner, "execute_author_script", fail)
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert result["call"]["output"]["projection_refusal"]["code"] == "recipe_adapter_failed"
    task = result["task"]
    with pytest.raises(TaskError, match="budget"):
        runner.evaluate_task_recipe(store, "a", **{**kwargs, "request_id": "retry-new", "expected_version": task["version"]})


def test_source_and_profile_changes_are_not_the_same_request(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: (_ for _ in ()).throw(OSError("stub")))
    runner.evaluate_task_recipe(store, "a", **kwargs)
    for change in ({"source": kwargs["source"] + "\n# different source"}, {"policy": replace(POLICY, replay_check=True)},
                   {"parameters": {"height_mm": 701.0}}):
        with pytest.raises(TaskError, match="request ID reused"):
            runner.evaluate_task_recipe(store, "a", **{**kwargs, **change})


def test_reassignment_during_execution_does_not_attach_late_result(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    def supersede(*args, **kwargs):
        task = read_task(store, "a")
        reassign_task(store, "a", request_id="new-attempt", expected_version=task["version"], generation=0,
            actor="coordinator", new_actor="other-worker", reason="explicit new owner")
        raise OSError("old computation ended later")
    monkeypatch.setattr(runner, "execute_author_script", supersede)
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert result["invoked"] and not result["recorded"]
    assert result["call"]["state"] == "superseded_unresolved" and result["call"]["output"] is None
    assert read_task(store, "a")["actor"] == "other-worker" and len(task_history(store, "a")) == 3


@pytest.mark.parametrize("failure", ["envelope", "grant"])
def test_unprojectable_success_retains_full_evaluated_program(tmp_path, failure):
    store, _, kwargs = case(tmp_path, grant_module=failure != "grant")
    if failure == "envelope":
        kwargs["source"] += "\nprogram['defaults'] = {'scope_marker': 'retained, not stripped'}"
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    output = result["call"]["output"]
    assert output["evaluation"]["sandbox_receipt"]["ok"], output
    assert output["proposal"] is None and output["projection_refusal"] is not None
    if failure == "envelope":
        assert output["evaluation"]["program"]["defaults"]["scope_marker"] == "retained, not stripped"
    else:
        assert output["projection_refusal"]["code"] == "assigned_grant_insufficient"
    assert len(store.history()) == 1
