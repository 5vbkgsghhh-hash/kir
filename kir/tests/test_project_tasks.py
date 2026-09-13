"""Real durable worker proposals, restart and atomic authoring decisions."""
from dataclasses import replace
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from kir import project_store as storage
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA, StoreConflict, StoreReadOnly, StoreCommitUnknown
from kir.project_tasks import (create_task, read_task, task_history, list_tasks, checkpoint_task,
    submit_task, decide_task, reassign_task, revoke_task, TaskError)
from kir.tests.test_project_merge import root, edit, bodies


def case(tmp_path, key="a"):
    base = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", base, schema=TASK_STORE_SCHEMA)
    task = create_task(store, task_id=key, base_revision=base.revision_id, actor="worker-" + key,
        objective="Raise selected level", scope=ProposalScope(instances=(key,)),
        tools=("project.read", "author.python"), budgets={"max_tokens": 50000, "max_tool_calls": 100})["task"]
    return store, base, task


def submit(store, base, task, elevation=500):
    change = ChangeProposal(base, edit(base, task["task_id"], elevation),
        ProposalScope.from_dict(task["assignment"]["scope"]), task["actor"], "Raise the selected instance")
    result = submit_task(store, task["task_id"], change, request_id="submit",
        expected_version=task["version"], generation=task["generation"], actor=task["actor"])
    return result["task"], change


def decide(store, task, head):
    return decide_task(store, task["task_id"], request_id="decide", expected_version=task["version"],
        generation=task["generation"], actor="coordinator", proposal_id=task["proposal"]["proposal_id"], expected_revision=head)


def fresh(code, *args):
    return subprocess.run([sys.executable, "-c", code, *map(str, args)], text=True,
                          capture_output=True, timeout=30, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def test_saved_grant_checkpoint_branch_and_decision_are_distinct(tmp_path):
    store, base, task = case(tmp_path)
    assert task["execution"] == "not_observed" and task["budget_enforcement"] == "not_established"
    saved = checkpoint_task(store, "a", request_id="note-1", expected_version=task["version"],
        generation=0, actor=task["actor"], notes={"done": ["checked levels"], "next": "raise level"})
    task, change = submit(store, base, saved["task"])
    assert len(store.history()) == 1 and store.head() == base
    assert task["state"] == "submitted"
    assert read_task(ProjectStore.open(store.path), "a")["proposal"] == change.to_dict()
    result = decide(store, task, base.revision_id)
    assert result["task"]["state"] == "accepted" and not result["native_published"]
    assert result["head_revision"] == change.candidate.revision_id
    assert len(store.history()) == 2
    history = task_history(store, "a")
    assert [e["kind"] for e in history] == ["assign", "checkpoint", "submit", "decide"]
    assert history[-1]["result"]["merge"]["ancestry"] == "verified_stored_history"
    history[0]["body"]["objective"] = "mutated detached copy"
    assert read_task(store, "a")["assignment"]["objective"] == "Raise selected level"


WORKER = """
import json,sys
from kir.project_store import ProjectStore
from kir.project_tasks import read_task,checkpoint_task,submit_task
from kir.project_merge import ChangeProposal,ProposalScope
from kir.tests.test_project_merge import edit
s=ProjectStore.open(sys.argv[1],readonly=False)
t=read_task(s,sys.argv[2]); base=s.get(t['assignment']['base_revision'])
print('loaded',flush=True); assert sys.stdin.readline().strip()=='go'
t=checkpoint_task(s,t['task_id'],request_id='checkpoint',expected_version=t['version'],generation=t['generation'],actor=t['actor'],notes={'done':'read exact base','next':'submit'})['task']
q=ChangeProposal(base,edit(base,t['task_id'],int(sys.argv[3])),ProposalScope.from_dict(t['assignment']['scope']),t['actor'],'independent change')
r=submit_task(s,t['task_id'],q,request_id='submit',expected_version=t['version'],generation=t['generation'],actor=t['actor'])
print(json.dumps({'state':r['task']['state'],'pid':__import__('os').getpid()}))
"""


def test_two_simultaneous_workers_and_new_coordinator_preserve_independent_changes(tmp_path):
    store, base, _ = case(tmp_path)
    create_task(store, task_id="b", base_revision=base.revision_id, actor="worker-b",
        objective="Raise B", scope=ProposalScope(instances=("b",)))
    workers = [subprocess.Popen([sys.executable, "-c", WORKER, str(store.path), key, str(elev)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")) for key, elev in (("a", 500), ("b", 4500))]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "loaded"
        for worker in workers:
            worker.stdin.write("go\n"); worker.stdin.flush()
        pids = []
        for worker in workers:
            output, error = worker.communicate(timeout=30)
            assert worker.returncode == 0, error
            value = json.loads(output)
            assert value["state"] == "submitted"
            pids.append(value["pid"])
        assert len(set(pids)) == 2 and store.head() == base
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill(); worker.wait(timeout=5)
    result = fresh("""
import json,sys,os
from kir.project_store import ProjectStore
from kir.project_tasks import read_task,decide_task
s=ProjectStore.open(sys.argv[1],readonly=False)
for key in ('a','b'):
 t=read_task(s,key)
 r=decide_task(s,key,request_id='accept',expected_version=t['version'],generation=t['generation'],actor='coordinator',proposal_id=t['proposal']['proposal_id'],expected_revision=s.head().revision_id)
 assert r['task']['state']=='accepted'
print(json.dumps({'pid':os.getpid(),'history':len(s.history())}))
""", store.path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pid"] not in pids
    assert json.loads(result.stdout)["history"] == 3
    head = store.head()
    assert bodies(head) == {"a": bodies(edit(base, "a", 500))["a"], "b": bodies(edit(base, "b", 4500))["b"], "c": bodies(base)["c"]}
    assert head.metadata == base.metadata
    assert {t["state"] for t in list_tasks(store)["tasks"]} == {"accepted"}


def test_two_processes_cannot_both_advance_the_same_task_version(tmp_path):
    store, base, _ = case(tmp_path)
    workers = [subprocess.Popen([sys.executable, "-c", WORKER, str(store.path), "a", str(elev)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")) for elev in (500, 900)]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "loaded"
        for worker in workers:
            worker.stdin.write("go\n"); worker.stdin.flush()
        outcomes = []
        for worker in workers:
            output, error = worker.communicate(timeout=30)
            outcomes.append((worker.returncode, output, error))
        assert sum(code == 0 for code, _, _ in outcomes) == 1
        loser = next(row for row in outcomes if row[0] != 0)
        # Both use identical request IDs; differing checkpoint ancestry/input
        # or submit contents cannot overwrite the first retained event.
        assert "request ID reused" in loser[2] or "stale task" in loser[2] or "worker no longer" in loser[2]
        assert read_task(store, "a")["state"] == "submitted"
        assert [e["kind"] for e in task_history(store, "a")] == ["assign", "checkpoint", "submit"]
        assert store.head() == base and len(store.history()) == 1
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill(); worker.wait(timeout=5)


@pytest.mark.parametrize("phase", ["INSERT INTO revisions", "INSERT INTO task_events", "COMMIT"])
def test_process_death_never_separates_accepted_revision_from_task_decision(tmp_path, phase):
    store, base, task = case(tmp_path)
    task, change = submit(store, base, task)
    result = fresh("""
import os,sys
from kir import project_store as storage
from kir.project_tasks import read_task,decide_task
s=storage.ProjectStore.open(sys.argv[1],readonly=False); t=read_task(s,'a'); h=s.head().revision_id
original=storage._connect
class Crash:
 def __init__(self,c): self.c=c
 def __getattr__(self,n): return getattr(self.c,n)
 def execute(self,sql,*args):
  value=self.c.execute(sql,*args)
  if sql.startswith(sys.argv[2]): os._exit(77)
  return value
storage._connect=lambda *a,**k: Crash(original(*a,**k))
decide_task(s,'a',request_id='decide',expected_version=t['version'],generation=0,actor='coordinator',proposal_id=t['proposal']['proposal_id'],expected_revision=h)
""", store.path, phase)
    assert result.returncode == 77, result.stderr
    # Explicit writable recovery, never deleting a hot journal.
    recovered = ProjectStore.open(store.path, readonly=False)
    actual = read_task(recovered, "a")
    committed = phase == "COMMIT"
    assert actual["state"] == ("accepted" if committed else "submitted")
    assert recovered.head().revision_id == (change.candidate.revision_id if committed else base.revision_id)
    assert len(recovered.history()) == (2 if committed else 1)


def test_lost_commit_ack_readback_and_exact_retry_preserve_later_head(tmp_path, monkeypatch):
    store, base, task = case(tmp_path)
    task, change = submit(store, base, task)
    original = storage._commit
    def lost_ack(connection):
        original(connection)
        raise StoreCommitUnknown("injected acknowledgement loss")
    with monkeypatch.context() as m:
        m.setattr(storage, "_commit", lost_ack)
        with pytest.raises(StoreCommitUnknown):
            decide(store, task, base.revision_id)
    assert read_task(store, "a")["state"] == "accepted"
    later = edit(store.head(), "b", 8000)
    store.commit(later, expected_revision=change.candidate.revision_id)
    replay = decide(store, task, base.revision_id)
    assert not replay["inserted"] and replay["head_revision"] == later.revision_id
    assert replay["event"]["result"]["accepted_revision"] == change.candidate.revision_id
    assert len(store.history()) == 3 and len(task_history(store, "a")) == 3


def test_readonly_and_read_detachment_do_not_mutate_store(tmp_path):
    store, base, task = case(tmp_path)
    before = store.path.read_bytes()
    reader = ProjectStore.open(store.path)
    detached = read_task(reader, "a")
    detached["assignment"]["budgets"]["max_tokens"] = 0
    assert read_task(reader, "a")["assignment"]["budgets"]["max_tokens"] == 50000
    with pytest.raises(StoreReadOnly):
        checkpoint_task(reader, "a", request_id="no", expected_version=task["version"], generation=0, actor=task["actor"], notes={})
    assert store.path.read_bytes() == before


def test_body_candidate_is_retained_outside_linear_history_and_reads_without_kernel(tmp_path):
    from kir.tests.test_geometry_materialization import capture, project_for
    from kir.project import ProjectRevision
    bundle = capture()
    shape = project_for(bundle)
    base = ProjectRevision(shape.project_id, shape.modules, [], schema=shape.schema)
    candidate = base.revise(expected_revision=base.revision_id, instances=shape.instances)
    store = ProjectStore.create(tmp_path / "body.sqlite", base, schema=TASK_STORE_SCHEMA)
    grant = ProposalScope(instances=("body",), project_fields=("instance_order",))
    t = create_task(store, task_id="shape", base_revision=base.revision_id, actor="sculptor", objective="Add body", scope=grant)["task"]
    q = ChangeProposal(base, candidate, grant, "sculptor", "retained CAD form")
    submit_task(store, "shape", q, request_id="submit", expected_version=t["version"], generation=0, actor="sculptor", assets=[bundle])
    assert len(store.history()) == 1 and store.get_asset(bundle.digest).dumps() == bundle.dumps()
    result = fresh("""
import importlib.abc,sys,json
class NoKernel(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='OCP' or fullname.startswith('OCP.'): raise AssertionError('unexpected kernel load')
sys.meta_path.insert(0,NoKernel())
from kir.project_store import ProjectStore
from kir.project_tasks import read_task
s=ProjectStore.open(sys.argv[1]); t=read_task(s,'shape')
assert t['state']=='submitted' and len(s.history())==1
print(t['proposal']['candidate']['revision_id'])
""", store.path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == candidate.revision_id


def test_conflicted_body_submission_remains_owned_and_recoverable(tmp_path):
    from kir.tests.test_geometry_materialization import capture, project_for
    from kir.project import ProjectRevision
    from kir.project_store import StoreAssetMissing, StoreCorrupt
    bundle = capture()
    shape = project_for(bundle)
    base = ProjectRevision(shape.project_id, shape.modules, [], schema=shape.schema)
    candidate = base.revise(expected_revision=base.revision_id, instances=shape.instances)
    store = ProjectStore.create(tmp_path / "body.sqlite", base, schema=TASK_STORE_SCHEMA)
    grant = ProposalScope(instances=("body",), project_fields=("instance_order",))
    task = create_task(store, task_id="shape", base_revision=base.revision_id, actor="sculptor", objective="Add body", scope=grant)["task"]
    change = ChangeProposal(base, candidate, grant, "sculptor", "retained form")
    kwargs = dict(request_id="submit", expected_version=task["version"], generation=0, actor="sculptor")
    with pytest.raises(StoreAssetMissing):
        submit_task(store, "shape", change, **kwargs)
    assert read_task(store, "shape")["state"] == "assigned" and len(task_history(store, "shape")) == 1
    task = submit_task(store, "shape", change, assets=[bundle], **kwargs)["task"]
    competitor = base.revise(expected_revision=base.revision_id,
        instances=[replace(shape.instances[0], metadata={"other_agent": "different decision"})])
    store.commit(competitor, expected_revision=base.revision_id)
    outcome = decide(store, task, competitor.revision_id)
    assert outcome["task"]["state"] == "conflicted" and outcome["task"]["decision"]["accepted_revision"] is None
    assert store.head().dumps() == competitor.dumps() and len(store.history()) == 2
    assert read_task(ProjectStore.open(store.path), "shape")["proposal"] == change.to_dict()
    assert store.get_asset(bundle.digest).dumps() == bundle.dumps()
    # Corruption is not repaired by replaying supplied bytes.
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM geometry_assets WHERE digest=?", (bundle.digest,))
    with pytest.raises(StoreCorrupt):
        submit_task(store, "shape", change, assets=[bundle], **kwargs)
