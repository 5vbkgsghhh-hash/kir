"""Durable authored task events in ProjectStore's transaction, not an agent runner.

The host assigns grants and exposes worker/coordinator operations separately.
Actor strings are NOT authentication. Policy budgets are declared, not enforced
LLM/tool limits. Reading/replaying events never runs recipes, kernels or Revit.
"""
from dataclasses import replace
from collections.abc import Mapping
import json

from kir.project import ProjectError, _canonical, _digest, _fields, _hash, _key, _object, _thaw
from kir.project_merge import ChangeProposal, ProposalScope, merge_proposal
from kir.project_store import (ProjectStore, ProjectStoreError, StoreConflict, StoreCorrupt,
    StoreNotFound, StoreUpgradeRequired, _check_revision_assets, _find_revision,
    _insert_assets, _provided_assets)


TASK_SCHEMA = "kir-authoring-task/1"
EVENT_SCHEMA = "kir-authoring-task-event/1"
MAX_EVENTS = 1000
MAX_EVENT_BYTES = 32 * 1024 * 1024
MAX_TASK_BYTES = 160 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024
TASK_TABLES = {
    "task_heads": """CREATE TABLE task_heads (
        task_id TEXT NOT NULL PRIMARY KEY,
        last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0),
        last_digest TEXT NOT NULL REFERENCES task_events(digest) DEFERRABLE INITIALLY DEFERRED
    )""",
    "task_events": """CREATE TABLE task_events (
        task_id TEXT NOT NULL REFERENCES task_heads(task_id),
        sequence INTEGER NOT NULL CHECK (sequence >= 0),
        digest TEXT NOT NULL UNIQUE CHECK (length(digest) = 64),
        request_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (task_id, sequence),
        UNIQUE (task_id, request_id)
    )""",
}


class TaskError(ProjectStoreError):
    """Invalid task request; no native execution is implied."""


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _supported(state):
    from kir.project_store import _TASK_SCHEMAS
    if state.schema not in _TASK_SCHEMAS:
        raise StoreUpgradeRequired("authoring tasks require explicit kir-project-store/5 upgrade")


def _store(store):
    _require(type(store) is ProjectStore, "expected exact ProjectStore")


def tool_result_request_id(request_id):
    """Deterministic adapter completion key, checked before a new reservation."""
    _key(request_id, "request_id")
    return "tool-result-" + _hash(request_id)


def _text(value, name, limit=16000):
    _require(type(value) is str and bool(value.strip()) and len(value) <= limit,
             f"{name}: expected nonempty bounded text")
    _canonical(value)
    return value


def _assignment(value):
    _fields(value, {"base_revision", "objective", "scope", "tools", "budgets"}, "assignment")
    _digest(value["base_revision"], "base_revision")
    _text(value["objective"], "objective")
    scope = ProposalScope.from_dict(value["scope"])
    tools = value["tools"]
    _require(type(tools) is list and len(tools) <= 100 and tools == sorted(set(tools)), "tools must be unique sorted keys")
    for name in tools:
        _key(name, "tool")
    budgets = value["budgets"]
    _require(type(budgets) is dict and not set(budgets) - {"max_tokens", "max_tool_calls"}, "unknown declared budget")
    _require(all(type(v) is int and 0 <= v <= 2**63 - 1 for v in budgets.values()), "budgets must be nonnegative integers")
    _require(scope.to_dict() == value["scope"], "scope is not canonical")


def _proposal(value, task):
    proposal = ChangeProposal.from_dict(value)
    _require(proposal.author == task["actor"], "proposal author differs from assigned actor")
    _require(proposal.base.revision_id == task["assignment"]["base_revision"], "proposal base differs from assigned base")
    _require(ProposalScope.from_dict(task["assignment"]["scope"]).covers(proposal.scope), "proposal exceeds assigned grant")
    return proposal


def _apply(task, event):
    """Validate one transition, also used when reading retained events."""
    kind, body = event["kind"], event["body"]
    _require(type(body) is dict, "event body must be an object")
    if kind == "assign":
        _require(task is None and event["sequence"] == 0 and event["previous"] is None
                 and event["generation"] == 0 and event["result"] is None, "invalid initial assignment")
        _assignment(body)
        task = {"schema": TASK_SCHEMA, "store_id": event["store_id"], "project_id": event["project_id"],
            "task_id": event["task_id"], "generation": 0, "actor": event["actor"],
            "assignment": body, "state": "assigned", "checkpoint": None, "proposal": None,
            "decision": None, "execution": "not_observed", "execution_scope": "assigned_worker_liveness",
            "budget_enforcement": "not_established",
            "tool_calls": [], "pending_tool": None}
    else:
        _require(task is not None and event["previous"] == task["version"]
                 and event["sequence"] == task["sequence"] + 1
                 and event["generation"] == task["generation"], "task event ancestry/generation differs")
        task = {**task, "tool_calls": [dict(call) for call in task["tool_calls"]]}
        if kind in ("checkpoint", "submit", "tool_begin", "tool_finish"):
            _require(task["state"] == "assigned" and event["actor"] == task["actor"], "worker no longer owns an assigned attempt")
        if kind in ("checkpoint", "submit", "tool_begin"):
            _require(task["pending_tool"] is None, "task has an unresolved tool reservation")
        if kind != "decide":
            _require(event["result"] is None, "non-decision has a result")
        if kind == "checkpoint":
            _fields(body, {"notes"}, "checkpoint")
            _object(body["notes"], "checkpoint notes")
            _require(len(_canonical(body).encode()) <= MAX_CHECKPOINT_BYTES, "checkpoint exceeds byte budget")
            task["checkpoint"] = {"generation": task["generation"], "sequence": event["sequence"], "notes": body["notes"]}
            # 🔴 `budget_enforcement` STOPS BEING `not_established` EXACTLY
            # WHEN SPENDING STARTS BEING WRITTEN TO THIS JOURNAL. The field
            # has stood here from the very start and NEVER changed — an
            # honest self-declaration that the token budget is guarded by no
            # one. Now the bureau records spending as a `checkpoint` event
            # (`bureau_spend`), and the journal's running total survives a
            # restart exactly the way the call count already did. The stop
            # flag (`bureau_stop`) travels the same way: two facts, not a
            # single new schema.
            if isinstance(body["notes"], dict) and "bureau_spend" in body["notes"]:
                task["budget_enforcement"] = "established"
        elif kind == "submit":
            _fields(body, {"proposal", "source_tool"} if "source_tool" in body else {"proposal"}, "submission")
            _proposal(body["proposal"], task)
            if "source_tool" in body:
                call = next((c for c in task["tool_calls"] if c["request_id"] == body["source_tool"]), None)
                _require(call is not None and call["state"] == "recorded" and call["generation"] == task["generation"]
                         and _canonical(call["output"].get("proposal")) == _canonical(body["proposal"]),
                         "proposal does not match this attempt's retained tool output")
            task.update(state="submitted", proposal=body["proposal"], decision=None)
        elif kind == "tool_begin":
            _fields(body, {"tool", "arguments"}, "tool request")
            _key(body["tool"], "tool")
            _object(body["arguments"], "tool arguments")
            limit = task["assignment"]["budgets"].get("max_tool_calls")
            _require(body["tool"] in task["assignment"]["tools"], "tool is outside assigned allowlist")
            _require(type(limit) is int and len(task["tool_calls"]) < limit, "explicit tool-call budget missing or exhausted")
            task["tool_calls"].append({"request_id": event["request_id"], "generation": task["generation"],
                "actor": event["actor"], "tool": body["tool"], "arguments": body["arguments"],
                "begin_version": event["digest"], "state": "reserved", "output": None})
            task["pending_tool"] = event["request_id"]
        elif kind in ("tool_finish", "tool_abandon"):
            fields = {"tool_request_id", "output"} if kind == "tool_finish" else {"tool_request_id", "reason"}
            _fields(body, fields, "tool completion")
            _require(task["state"] == "assigned" and task["pending_tool"] is not None
                     and body["tool_request_id"] == task["pending_tool"], "completion targets no matching pending tool")
            call = next(c for c in task["tool_calls"] if c["request_id"] == task["pending_tool"])
            if kind == "tool_finish":
                _object(body["output"], "tool output")
                call.update(state="recorded", output=body["output"])
            else:
                _text(body["reason"], "reason")
                call.update(state="abandoned_unresolved", resolution_reason=body["reason"])
            task["pending_tool"] = None
        elif kind == "reassign":
            _fields(body, {"new_actor", "reason"}, "reassignment")
            _require(task["state"] != "accepted", "accepted task cannot be reassigned")
            _key(body["new_actor"], "new_actor")
            _text(body["reason"], "reason")
            task.update(state="assigned", actor=body["new_actor"], generation=task["generation"] + 1,
                        proposal=None, decision=None)
        elif kind == "revoke":
            _fields(body, {"reason"}, "revocation")
            _require(task["state"] not in ("accepted", "revoked"), "task cannot be revoked in this state")
            _text(body["reason"], "reason")
            task.update(state="revoked", generation=task["generation"] + 1)
        elif kind == "decide":
            _fields(body, {"proposal_id", "expected_revision"}, "decision request")
            _require(task["state"] == "submitted" and body["proposal_id"] == task["proposal"]["proposal_id"], "decision targets another proposal/state")
            _digest(body["expected_revision"], "expected_revision")
            result = event["result"]
            _fields(result, {"merge", "accepted_revision", "head_at_decision"}, "decision result")
            report = result["merge"]
            _require(type(report) is dict and report.get("proposal_id") == body["proposal_id"]
                     and report.get("current_revision") == body["expected_revision"]
                     and report.get("result_revision") == result["accepted_revision"]
                     and report.get("ancestry") == "verified_stored_history"
                     and report.get("scope") == "authoring_only"
                     and report.get("native_execution") == "not_run", "decision report binding differs")
            accepted = result["accepted_revision"]
            if accepted is not None:
                _digest(accepted, "accepted_revision")
                _require(report.get("status") in ("merged", "unchanged") and report.get("conflicts") == []
                         and result["head_at_decision"] == accepted, "invalid accepted decision")
            else:
                _require(report.get("status") == "conflict" and bool(report.get("conflicts"))
                         and result["head_at_decision"] == body["expected_revision"], "invalid conflict decision")
            task.update(state="accepted" if accepted is not None else "conflicted", decision=result)
        else:
            raise TaskError("unsupported task event kind")
        if kind in ("reassign", "revoke") and task["pending_tool"] is not None:
            call = next(c for c in task["tool_calls"] if c["request_id"] == task["pending_tool"])
            call.update(state="superseded_unresolved", resolution_reason=body["reason"])
            task["pending_tool"] = None
    task.update(sequence=event["sequence"], version=event["digest"])
    return task


def _load(connection, state, task_id, *, asset_cache=None):
    _supported(state)
    _key(task_id, "task_id")
    head = connection.execute("SELECT last_sequence,last_digest FROM task_heads WHERE task_id=?", (task_id,)).fetchone()
    stats = connection.execute("SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0),coalesce(max(length(CAST(payload AS BLOB))),0) FROM task_events WHERE task_id=?", (task_id,)).fetchone()
    if head is None:
        if stats[0]:
            raise StoreCorrupt("task events lost their owning head")
        raise StoreNotFound("task is not in this store")
    if not (1 <= stats[0] <= MAX_EVENTS and stats[1] <= MAX_TASK_BYTES and stats[2] <= MAX_EVENT_BYTES):
        raise StoreCorrupt("task event history exceeds bounds or is empty")
    task, events = None, []
    try:
        for sequence, digest, request_id, payload in connection.execute(
                "SELECT sequence,digest,request_id,payload FROM task_events WHERE task_id=? ORDER BY sequence", (task_id,)):
            event = json.loads(payload)
            _fields(event, {"schema", "store_id", "project_id", "task_id", "sequence", "digest", "request_id",
                "previous", "generation", "actor", "kind", "body", "result"}, "task event")
            _require(event["schema"] == EVENT_SCHEMA and event["store_id"] == state.store_id
                     and event["project_id"] == state.project_id and event["task_id"] == task_id,
                     "event owner/schema differs")
            _require(type(event["sequence"]) is int and event["sequence"] == sequence == len(events)
                     and event["digest"] == digest and event["request_id"] == request_id
                     and type(event["generation"]) is int and event["generation"] >= 0,
                     "event row/sequence differs")
            _key(event["actor"], "actor")
            _key(request_id, "request_id")
            _require(_canonical(event) == payload and _hash({k: v for k, v in event.items() if k != "digest"}) == digest,
                     "event hash/canonical payload differs")
            task = _apply(task, event)
            if event["kind"] == "assign":
                _require(_find_revision(connection, state, task["assignment"]["base_revision"]) is not None,
                         "assigned revision is missing")
            if event["kind"] == "submit":
                proposal = _proposal(event["body"]["proposal"], task)
                base = _find_revision(connection, state, proposal.base.revision_id)
                _require(base is not None and base.dumps() == proposal.base.dumps(), "stored proposal base differs")
                _check_revision_assets(connection, proposal.candidate, state.schema, stored=True, cache=asset_cache)
            if event["kind"] == "decide":
                before = _find_revision(connection, state, event["body"]["expected_revision"])
                _require(before is not None, "decision current revision disappeared")
                accepted = event["result"]["accepted_revision"]
                if accepted is not None:
                    revision = _find_revision(connection, state, accepted)
                    _require(revision is not None and (accepted == before.revision_id
                             or revision.parent_revision == before.revision_id), "decision accepted revision is missing or has another parent")
            events.append(event)
        _require(head == (task["sequence"], task["version"]), "task head is not its complete event tail")
    except (TaskError, ProjectError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise StoreCorrupt(f"invalid task history: {exc}") from exc
    return task, events, stats[1]


def audit_tasks(connection, state, *, asset_cache):
    """Called by the SAME owner's history audit, never recursively reads history."""
    _supported(state)
    if connection.execute("SELECT 1 FROM task_events e LEFT JOIN task_heads h ON h.task_id=e.task_id WHERE h.task_id IS NULL LIMIT 1").fetchone():
        raise StoreCorrupt("orphaned task events")
    for (task_id,) in connection.execute("SELECT task_id FROM task_heads ORDER BY task_id"):
        _load(connection, state, task_id, asset_cache=asset_cache)


def read_task(store, task_id):
    _store(store)
    reader = store if store.readonly else replace(store, readonly=True)
    with reader._transaction() as (connection, state):
        task, _, _ = _load(connection, state, task_id)
        return task


def task_history(store, task_id):
    _store(store)
    reader = store if store.readonly else replace(store, readonly=True)
    with reader._transaction() as (connection, state):
        _, events, _ = _load(connection, state, task_id)
        return events


def list_tasks(store, *, limit=20, after_task=None):
    _store(store)
    _require(type(limit) is int and 1 <= limit <= 100, "task page limit must be 1..100")
    if after_task is not None:
        _key(after_task, "task cursor")
    reader = store if store.readonly else replace(store, readonly=True)
    with reader._transaction() as (connection, state):
        _supported(state)
        if connection.execute("SELECT 1 FROM task_events e LEFT JOIN task_heads h ON h.task_id=e.task_id WHERE h.task_id IS NULL LIMIT 1").fetchone():
            raise StoreCorrupt("orphaned task events")
        rows = connection.execute("SELECT task_id FROM task_heads WHERE task_id>? ORDER BY task_id LIMIT ?", (after_task or "", limit + 1)).fetchall()
        summaries = []
        for (task_id,) in rows[:limit]:
            task, _, _ = _load(connection, state, task_id)
            summaries.append({k: task[k] for k in ("task_id", "generation", "actor", "state", "sequence", "version")})
        return {"store_id": state.store_id, "project_id": state.project_id, "tasks": summaries,
            "has_more": len(rows) > limit, "next_cursor": rows[limit-1][0] if len(rows) > limit else None,
            "snapshot_scope": "one_local_read_transaction", "continuation_consistency": "new_read_snapshot_each_call"}


def _mutate(store, task_id, *, request_id, expected_version, generation, actor, kind, body, assets=(),
            expected_task_versions=None):
    _store(store)
    _key(task_id, "task_id")
    _key(request_id, "request_id")
    _key(actor, "actor")
    _require(type(generation) is int and generation >= 0, "generation must be a nonnegative integer")
    # Transient optimistic guards, NOT authorization or a new event format.
    # Exact replay below has no effect and intentionally ignores stale guards.
    guards = {} if expected_task_versions is None else expected_task_versions
    _require(isinstance(guards, Mapping) and len(guards) <= 8, "expected task versions require a bounded mapping")
    guards = dict(guards)
    for key, digest in guards.items():
        _key(key, "guard_task_id")
        _require(type(digest) is str, "guard version must be an exact SHA256 string")
        _digest(digest, "guard_task_version")
    if expected_version is not None:
        _digest(expected_version, "expected_version")
    _require((kind == "assign") == (expected_version is None), "explicit task version required")
    body = json.loads(_canonical(body))
    supplied = _provided_assets(assets)
    _require(kind == "submit" or not supplied, "only submit accepts candidate assets")
    with store._transaction(write=True) as (connection, state):
        _supported(state)
        try:
            task, events, used_bytes = _load(connection, state, task_id)
        except StoreNotFound:
            if kind != "assign":
                raise
            task, events, used_bytes = None, [], 0
        command = {"request_id": request_id, "previous": expected_version, "generation": generation,
                   "actor": actor, "kind": kind, "body": body}
        previous = next((event for event in events if event["request_id"] == request_id), None)
        if previous is not None:
            _require(all(_canonical(previous[k]) == _canonical(v) for k, v in command.items()), "request ID reused for different input")
            if kind == "submit":
                proposal = ChangeProposal.from_dict(body["proposal"])
                _check_revision_assets(connection, proposal.candidate, state.schema, supplied, stored=True)
            return {"task": task, "event": previous, "inserted": False,
                    "head_revision": state.head.revision_id, "native_published": False}
        if kind == "assign":
            if task is not None:
                raise StoreConflict("task already exists")
        elif task["version"] != expected_version or task["generation"] != generation:
            raise StoreConflict("stale task version or assignment generation")
        for guarded_task, digest in guards.items():
            found = connection.execute("SELECT last_digest FROM task_heads WHERE task_id=?", (guarded_task,)).fetchone()
            if found != (digest,):
                raise StoreConflict("guarded task version changed")
        if kind == "tool_begin" and connection.execute(
                "SELECT 1 FROM task_events WHERE task_id=? AND request_id=?",
                (task_id, tool_result_request_id(request_id))).fetchone():
            raise TaskError("tool completion request ID is already occupied; evaluator was not invoked")
        reserve = (3 if kind == "tool_begin" else 2 if kind in
                   ("assign", "checkpoint", "reassign", "tool_finish", "tool_abandon") else 1 if kind == "submit" else 0)
        _require(len(events) < MAX_EVENTS - reserve, "task event budget exhausted; terminal capacity is reserved")
        event = {"schema": EVENT_SCHEMA, "store_id": state.store_id, "project_id": state.project_id,
                 "task_id": task_id, "sequence": len(events), **command, "result": None}
        head_revision = state.head.revision_id
        if kind == "decide":
            from kir.project_store import _read_history, _commit_revision
            _fields(body, {"proposal_id", "expected_revision"}, "decision request")
            _require(task["state"] == "submitted" and task["proposal"]["proposal_id"] == body["proposal_id"], "no matching submitted proposal")
            if state.head.revision_id != body["expected_revision"]:
                raise StoreConflict("decision expected a different authored head")
            history = _read_history(connection, state)
            proposal = ChangeProposal.from_dict(task["proposal"])
            _require(any(r.dumps() == proposal.base.dumps() for r in history), "proposal base not in stored history")
            merged = merge_proposal(proposal, state.head, authorized_scope=ProposalScope.from_dict(task["assignment"]["scope"]))
            report = merged.to_dict()
            report["ancestry"] = "verified_stored_history"
            if merged.clean:
                committed = _commit_revision(connection, state, merged.revision, expected_revision=merged.revision.parent_revision)
                head_revision = committed.head_revision
            event["result"] = {"merge": report, "accepted_revision": report["result_revision"], "head_at_decision": head_revision}
        event["digest"] = _hash(event)
        candidate = _apply(task, event)
        if kind == "assign":
            _require(_find_revision(connection, state, body["base_revision"]) is not None, "assigned base is not stored")
        if kind == "submit":
            proposal = _proposal(body["proposal"], candidate)
            base = _find_revision(connection, state, proposal.base.revision_id)
            _require(base is not None and base.dumps() == proposal.base.dumps(), "proposal base not stored")
            _insert_assets(connection, _check_revision_assets(connection, proposal.candidate, state.schema, supplied))
        payload = _canonical(event)
        size = len(payload.encode("utf-8"))
        _require(size <= MAX_EVENT_BYTES and used_bytes + size <= MAX_TASK_BYTES - reserve * MAX_EVENT_BYTES,
                 "task byte budget exhausted; terminal capacity is reserved")
        if task is None:
            connection.execute("INSERT INTO task_heads VALUES (?,?,?)", (task_id, event["sequence"], event["digest"]))
        connection.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (task_id, event["sequence"], event["digest"], request_id, payload))
        if task is not None:
            updated = connection.execute("UPDATE task_heads SET last_sequence=?,last_digest=? WHERE task_id=? AND last_digest=?",
                (event["sequence"], event["digest"], task_id, expected_version))
            if updated.rowcount != 1:
                raise StoreConflict("task head CAS failed")
        return {"task": candidate, "event": event, "inserted": True,
                "head_revision": head_revision, "native_published": False}


def create_task(store, *, task_id, base_revision, actor, objective, scope, tools=(), budgets=None, expected_task_versions=None):
    """Coordinator-only: persist a grant; this does not start an agent."""
    _require(type(scope) is ProposalScope, "expected typed coordinator ProposalScope")
    _require(type(tools) in (list, tuple) and all(type(t) is str for t in tools), "tools must be a key sequence")
    return _mutate(store, task_id, request_id="assignment", expected_version=None, generation=0,
        actor=actor, kind="assign", body={"base_revision": base_revision, "objective": objective,
        "scope": scope.to_dict(), "tools": sorted(set(tools)), "budgets": {} if budgets is None else budgets},
        expected_task_versions=expected_task_versions)


def checkpoint_task(store, task_id, *, request_id, expected_version, generation, actor, notes, expected_task_versions=None):
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
                   generation=generation, actor=actor, kind="checkpoint", body={"notes": notes},
                   expected_task_versions=expected_task_versions)


def submit_task(store, task_id, proposal, *, request_id, expected_version, generation, actor, assets=(), source_tool=None,
                expected_task_versions=None):
    _require(type(proposal) is ChangeProposal, "expected typed ChangeProposal")
    # Reparse canonical bytes so caller-mutated frozen objects cannot confer a grant.
    checked = ChangeProposal.loads(proposal.dumps())
    body = {"proposal": checked.to_dict()}
    if source_tool is not None:
        _key(source_tool, "source_tool")
        body["source_tool"] = source_tool
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
                   generation=generation, actor=actor, kind="submit", body=body, assets=assets,
                   expected_task_versions=expected_task_versions)


def reassign_task(store, task_id, *, request_id, expected_version, generation, actor, new_actor, reason):
    """Coordinator-only, explicit fencing; never claims the former worker stopped."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
                   generation=generation, actor=actor, kind="reassign", body={"new_actor": new_actor, "reason": reason})


def revoke_task(store, task_id, *, request_id, expected_version, generation, actor, reason):
    """Coordinator-only, no external process cancellation or native rollback."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
                   generation=generation, actor=actor, kind="revoke", body={"reason": reason})


def decide_task(store, task_id, *, request_id, expected_version, generation, actor, proposal_id, expected_revision,
                expected_task_versions=None):
    """Coordinator-only: durable merge decision and authored head in one commit."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
        generation=generation, actor=actor, kind="decide", body={"proposal_id": proposal_id, "expected_revision": expected_revision},
        expected_task_versions=expected_task_versions)


def begin_task_tool(store, task_id, *, request_id, expected_version, generation, actor, tool, arguments, expected_task_versions=None):
    """Trusted adapter reservation; a duplicate NEVER authorizes another invoke."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
        generation=generation, actor=actor, kind="tool_begin", body={"tool": tool, "arguments": arguments},
        expected_task_versions=expected_task_versions)


def finish_task_tool(store, task_id, *, request_id, expected_version, generation, actor, tool_request_id, output,
                     expected_task_versions=None):
    """Trusted adapter, not a worker-authored assertion of execution evidence."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
        generation=generation, actor=actor, kind="tool_finish", body={"tool_request_id": tool_request_id, "output": output},
        expected_task_versions=expected_task_versions)


def abandon_task_tool(store, task_id, *, request_id, expected_version, generation, actor, tool_request_id, reason):
    """Coordinator-only unresolved outcome, not proof the external process stopped."""
    return _mutate(store, task_id, request_id=request_id, expected_version=expected_version,
        generation=generation, actor=actor, kind="tool_abandon", body={"tool_request_id": tool_request_id, "reason": reason})
