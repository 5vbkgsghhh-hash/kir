"""Independent task lifecycle counterexamples on small real SQLite stores.

No LLM, native model, geometry kernel, network, or process spawning. The pytest
runner must supply its temporary directory under the worktree's .work directory.
"""
from dataclasses import replace
import sqlite3

import pytest

from kir import project_tasks as tasks
from kir.project import _canonical, _hash
from kir.project_merge import ProposalScope
from kir.project_store import ProjectStore, StoreConflict, StoreCorrupt, TASK_STORE_SCHEMA
from kir.tests.test_project_merge import root, edit, proposal


WORKER = "architecture-agent"
COORDINATOR = "coordinator"
TASK = "raise-a"


def assigned(tmp_path, *, scope=None):
    base = root()
    store = ProjectStore.create(tmp_path / "tasks.sqlite", base, schema=TASK_STORE_SCHEMA)
    created = tasks.create_task(store, task_id=TASK, base_revision=base.revision_id,
        actor=WORKER, objective="Raise one selected level without changing its neighbours",
        scope=scope or ProposalScope(instances=("a",)), tools=("python",), budgets={"max_tokens": 100})
    return store, base, created


def submit(store, change, task, request_id="submit"):
    return tasks.submit_task(store, TASK, change, request_id=request_id,
        expected_version=task["version"], generation=task["generation"], actor=task["actor"])


def decide(store, task, revision, *, request_id="decision"):
    return tasks.decide_task(store, TASK, request_id=request_id,
        expected_version=task["version"], generation=task["generation"], actor=COORDINATOR,
        proposal_id=task["proposal"]["proposal_id"], expected_revision=revision.revision_id)


def counts(store):
    with sqlite3.connect(f"file:{store.path}?mode=ro", uri=True) as connection:
        return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("revisions", "task_heads", "task_events"))


def test_decision_checks_authored_head_even_when_task_version_is_current(tmp_path):
    store, base, created = assigned(tmp_path)
    change = proposal(base, edit(base, "a", 600), "a")
    submitted = submit(store, change, created["task"])
    advanced = edit(base, "b", 4200)
    store.commit(advanced, expected_revision=base.revision_id)
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(StoreConflict, match="authored head"):
        decide(store, submitted["task"], base)
    assert (store.path.read_bytes(), counts(store)) == before
    assert tasks.read_task(store, TASK)["state"] == "submitted"
    accepted = decide(store, submitted["task"], advanced, request_id="review-new-head")
    assert accepted["task"]["state"] == "accepted"
    assert accepted["event"]["result"]["head_at_decision"] == store.head().revision_id
    assert {instance.key: instance.outputs[0].operation["elev_mm"] for instance in store.head().instances} == {
        "a": 600, "b": 4200, "c": 6000}


def test_decision_checks_task_version_even_when_authored_head_is_current(tmp_path):
    store, base, created = assigned(tmp_path)
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    reassigned = tasks.reassign_task(store, TASK, request_id="reassign", expected_version=submitted["task"]["version"],
        generation=0, actor=COORDINATOR, new_actor=WORKER, reason="Restart this attempt")
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(StoreConflict, match="task version|generation"):
        decide(store, submitted["task"], base)
    assert (store.path.read_bytes(), counts(store)) == before
    assert tasks.read_task(store, TASK) == reassigned["task"]


@pytest.mark.parametrize("already_applied", [False, True])
def test_noop_acceptance_records_a_decision_without_duplicate_revision(tmp_path, already_applied):
    store, base, created = assigned(tmp_path)
    candidate = edit(base, "a", 600) if already_applied else base
    change = proposal(base, candidate, "a")
    submitted = submit(store, change, created["task"])
    if already_applied:
        store.commit(candidate, expected_revision=base.revision_id)
    before = counts(store)
    result = decide(store, submitted["task"], candidate)
    assert result["inserted"] and result["task"]["state"] == "accepted"
    assert result["event"]["result"]["merge"]["status"] == "unchanged"
    assert result["event"]["result"]["accepted_revision"] == candidate.revision_id
    assert counts(store) == (before[0], before[1], before[2] + 1)
    assert tasks.read_task(ProjectStore.open(store.path), TASK)["state"] == "accepted"


@pytest.mark.parametrize("old_kind", ["checkpoint", "submit"])
def test_exact_old_ack_does_not_restore_a_superseded_generation(tmp_path, old_kind):
    store, base, created = assigned(tmp_path)
    initial = created["task"]
    change = proposal(base, edit(base, "a", 600), "a")
    command = dict(request_id="worker-event", expected_version=initial["version"], generation=0, actor=WORKER)
    if old_kind == "checkpoint":
        deliver = lambda: tasks.checkpoint_task(store, TASK, notes={"step": "draft"}, **command)
    else:
        deliver = lambda: tasks.submit_task(store, TASK, change, **command)
    first = deliver()
    reassigned = tasks.reassign_task(store, TASK, request_id="coordinator-reassign",
        expected_version=first["task"]["version"], generation=0, actor=COORDINATOR,
        new_actor=WORKER, reason="Same actor label, explicitly different generation")
    before = store.path.read_bytes(), counts(store)
    replayed = deliver()
    assert not replayed["inserted"] and replayed["event"] == first["event"]
    assert replayed["event"]["generation"] == 0
    assert replayed["task"] == reassigned["task"] and replayed["task"]["generation"] == 1
    assert replayed["task"]["state"] == "assigned" and replayed["task"]["proposal"] is None
    assert (store.path.read_bytes(), counts(store)) == before
    with pytest.raises(StoreConflict):
        tasks.checkpoint_task(store, TASK, request_id="late-new-event", expected_version=reassigned["task"]["version"],
            generation=0, actor=WORKER, notes={"late": True})


def test_request_id_reuse_cannot_change_content_or_assignment_parent(tmp_path):
    store, _, created = assigned(tmp_path)
    command = dict(request_id="checkpoint", expected_version=created["task"]["version"], generation=0, actor=WORKER)
    first = tasks.checkpoint_task(store, TASK, notes={"value": 1}, **command)
    before = store.path.read_bytes(), counts(store)
    for changed in ({**command}, {**command, "expected_version": first["task"]["version"]}):
        with pytest.raises(tasks.TaskError, match="request ID reused"):
            tasks.checkpoint_task(store, TASK, notes={"value": True}, **changed)
    assert (store.path.read_bytes(), counts(store)) == before


def test_accepted_ack_names_historical_event_and_current_head_separately(tmp_path):
    store, base, created = assigned(tmp_path)
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    first = decide(store, submitted["task"], base)
    accepted = store.head()
    advanced = edit(accepted, "b", 4200)
    store.commit(advanced, expected_revision=accepted.revision_id)
    before = store.path.read_bytes(), counts(store)
    replayed = decide(store, submitted["task"], base)
    assert not replayed["inserted"] and replayed["event"] == first["event"]
    assert replayed["event"]["result"]["accepted_revision"] == accepted.revision_id
    assert replayed["head_revision"] == advanced.revision_id
    assert replayed["head_revision"] != replayed["event"]["result"]["head_at_decision"]
    assert (store.path.read_bytes(), counts(store)) == before
    with pytest.raises(tasks.TaskError, match="request ID reused"):
        decide(store, submitted["task"], advanced)


@pytest.mark.parametrize("kind", ["read", "list", "assign"])
def test_orphaned_events_are_corruption_not_missing_or_new_task(tmp_path, kind):
    store, base, _ = assigned(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM task_heads WHERE task_id=?", (TASK,))
    before = store.path.read_bytes()
    with pytest.raises(StoreCorrupt):
        if kind == "read":
            tasks.read_task(store, TASK)
        elif kind == "list":
            tasks.list_tasks(store)
        else:
            tasks.create_task(store, task_id=TASK, base_revision=base.revision_id, actor=WORKER,
                              objective="Do not resurrect", scope=ProposalScope(instances=("a",)))
    assert store.path.read_bytes() == before


def test_stale_head_cannot_hide_a_later_submitted_event(tmp_path):
    store, base, created = assigned(tmp_path)
    submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE task_heads SET last_sequence=0,last_digest=? WHERE task_id=?",
                           (created["event"]["digest"], TASK))
    with pytest.raises(StoreCorrupt, match="complete event tail"):
        tasks.read_task(store, TASK)


@pytest.mark.parametrize("payload", ["[]", "null", "true"])
def test_nonobject_event_has_named_storage_refusal(tmp_path, payload):
    store, _, _ = assigned(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE task_events SET payload=? WHERE task_id=?", (payload, TASK))
    with pytest.raises(StoreCorrupt):
        tasks.read_task(store, TASK)


@pytest.mark.parametrize("fault", ["store", "task", "generation_bool", "previous"])
def test_rehashed_event_still_must_match_its_owner_and_transition(tmp_path, fault):
    store, _, created = assigned(tmp_path)
    event = created["event"]
    if fault == "store":
        event["store_id"] = "0" * 32
    elif fault == "task":
        event["task_id"] = "different-task"
    elif fault == "generation_bool":
        event["generation"] = False
    else:
        event["previous"] = "f" * 64
    event["digest"] = _hash({key: value for key, value in event.items() if key != "digest"})
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE task_events SET digest=?,payload=? WHERE task_id=?",
                           (event["digest"], _canonical(event), TASK))
        connection.execute("UPDATE task_heads SET last_digest=? WHERE task_id=?", (event["digest"], TASK))
    with pytest.raises(StoreCorrupt):
        tasks.read_task(store, TASK)


def test_minimum_three_events_can_complete_without_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENTS", 3)
    store, base, created = assigned(tmp_path)
    with pytest.raises(tasks.TaskError, match="event budget"):
        tasks.checkpoint_task(store, TASK, request_id="not-enough-room", expected_version=created["task"]["version"],
            generation=0, actor=WORKER, notes={"step": "would consume terminal capacity"})
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    assert decide(store, submitted["task"], base)["task"]["state"] == "accepted"
    assert len(tasks.task_history(store, TASK)) == 3


def test_accepted_task_is_terminal_and_readonly_handle_cannot_checkpoint(tmp_path):
    from kir.project_store import StoreReadOnly

    store, base, created = assigned(tmp_path)
    with pytest.raises(StoreReadOnly):
        tasks.checkpoint_task(ProjectStore.open(store.path), TASK, request_id="readonly",
            expected_version=created["task"]["version"], generation=0, actor=WORKER, notes={"step": "no write"})
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    accepted = decide(store, submitted["task"], base)["task"]
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(tasks.TaskError, match="accepted task"):
        tasks.reassign_task(store, TASK, request_id="after-accept", expected_version=accepted["version"],
            generation=accepted["generation"], actor=COORDINATOR, new_actor="other", reason="Must not reopen")
    with pytest.raises(tasks.TaskError, match="cannot be revoked"):
        tasks.revoke_task(store, TASK, request_id="revoke-accepted", expected_version=accepted["version"],
            generation=accepted["generation"], actor=COORDINATOR, reason="Must not relabel accepted history")
    assert (store.path.read_bytes(), counts(store)) == before


@pytest.mark.parametrize("finish", ["accept", "revoke"])
def test_worker_event_cap_leaves_terminal_capacity(tmp_path, monkeypatch, finish):
    monkeypatch.setattr(tasks, "MAX_EVENTS", 5)
    store, base, created = assigned(tmp_path)
    current = created["task"]
    for index in range(2):
        current = tasks.checkpoint_task(store, TASK, request_id=f"checkpoint-{index}",
            expected_version=current["version"], generation=0, actor=WORKER, notes={"step": index})["task"]
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(tasks.TaskError, match="event budget"):
        tasks.checkpoint_task(store, TASK, request_id="exhaust", expected_version=current["version"],
            generation=0, actor=WORKER, notes={"step": "too far"})
    with pytest.raises(tasks.TaskError, match="event budget"):
        tasks.reassign_task(store, TASK, request_id="reassign-too-late", expected_version=current["version"],
            generation=0, actor=COORDINATOR, new_actor="other", reason="Would strand a new attempt")
    assert (store.path.read_bytes(), counts(store)) == before
    if finish == "accept":
        submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), current)
        final = decide(store, submitted["task"], base)
        assert final["task"]["state"] == "accepted" and len(tasks.task_history(store, TASK)) == 5
    else:
        final = tasks.revoke_task(store, TASK, request_id="stop", expected_version=current["version"],
                                 generation=0, actor=COORDINATOR, reason="Explicit stop")
        assert final["task"]["state"] == "revoked"


def test_worker_byte_cap_leaves_submit_and_decision_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENT_BYTES", 32000)
    monkeypatch.setattr(tasks, "MAX_TASK_BYTES", 96000)
    store, base, created = assigned(tmp_path)
    used = len(_canonical(created["event"]).encode())
    note = "x" * (tasks.MAX_EVENT_BYTES - used - 1400)
    current = tasks.checkpoint_task(store, TASK, request_id="large-checkpoint",
        expected_version=created["task"]["version"], generation=0, actor=WORKER, notes={"text": note})["task"]
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(tasks.TaskError, match="byte budget"):
        tasks.checkpoint_task(store, TASK, request_id="extra-checkpoint", expected_version=current["version"],
            generation=0, actor=WORKER, notes={"text": "y" * 2000})
    assert (store.path.read_bytes(), counts(store)) == before
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), current)
    assert decide(store, submitted["task"], base)["task"]["state"] == "accepted"


def test_task_cap_is_checked_before_event_transition_decode(tmp_path, monkeypatch):
    store, _, _ = assigned(tmp_path)
    monkeypatch.setattr(tasks, "MAX_TASK_BYTES", 1)
    monkeypatch.setattr(tasks, "_apply", lambda *_: pytest.fail("over-budget history was reduced"))
    with pytest.raises(StoreCorrupt, match="exceeds bounds"):
        tasks.read_task(store, TASK)


@pytest.mark.parametrize("fault", ["grant", "actor", "base"])
def test_worker_proposal_cannot_replace_the_coordinator_assignment(tmp_path, fault):
    store, base, created = assigned(tmp_path)
    if fault == "grant":
        change = proposal(base, edit(base, "b", 4200), "b")
    elif fault == "actor":
        change = replace(proposal(base, edit(base, "a", 600), "a"), author="different-worker")
    else:
        child = edit(base, "b", 4200)
        store.commit(child, expected_revision=base.revision_id)
        change = proposal(child, edit(child, "a", 600), "a")
    before = store.path.read_bytes(), counts(store)
    with pytest.raises(tasks.TaskError):
        submit(store, change, created["task"])
    assert (store.path.read_bytes(), counts(store)) == before


def test_failed_decision_storage_rolls_back_the_revision_too(tmp_path, monkeypatch):
    store, base, created = assigned(tmp_path)
    submitted = submit(store, proposal(base, edit(base, "a", 600), "a"), created["task"])
    before = counts(store)
    # The merge and _commit_revision run before event encoding. Failure of the
    # final event budget must roll back their SQL writes in the same transaction.
    original_apply = tasks._apply
    def inflated(task, event):
        reduced = original_apply(task, event)
        if event["kind"] == "decide":
            monkeypatch.setattr(tasks, "MAX_EVENT_BYTES", 1)
        return reduced
    with monkeypatch.context() as local:
        local.setattr(tasks, "_apply", inflated)
        with pytest.raises(tasks.TaskError, match="byte budget"):
            decide(store, submitted["task"], base)
    monkeypatch.setattr(tasks, "MAX_EVENT_BYTES", 32 * 1024 * 1024)
    assert counts(store) == before and store.head().revision_id == base.revision_id
    assert tasks.read_task(store, TASK)["state"] == "submitted"
