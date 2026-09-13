# -*- coding: utf-8 -*-
"""The bureau: assignment -> the model writes a program -> sandbox -> proposal -> CAS.

🔴 WHAT IS NEW HERE AND WHAT IS REUSED. What's new is exactly three things:
a TEAM budget, cooperative Stop, and a loop in which the program's text
comes from the model, not from a repository file. Everything else was
built before us and is called as it is: `project_tasks` (journal,
generation fencing, CAS, per-task call budget),
`task_recipe_runner.evaluate_task_recipe` (sandbox + reservation),
`project_merge` (merging and conflict). Recon showed, by the numbers, that
five of the pilot's seven steps already work; touching them would mean
rewriting what works.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

from kir.project import _canonical, _hash, _thaw, output_id
from kir.project_merge import ProposalScope
from kir.project_store import StoreNotFound
from kir.project_tasks import (TaskError, checkpoint_task, create_task, decide_task, list_tasks,
                               read_task, task_history)

__all__ = ["Decisions", "TeamBudget", "WorkResult", "assign", "conflict_payload", "coordinate",
           "is_stopped", "read_request", "replan_text", "resume", "serve_read", "spend", "stop",
           "stop_reason", "work"]

#: The team's book-task. It is NOT a project task: not a single proposal
#: lives in it, it holds only spending and the Stop flag — using the same
#: `checkpoint` events the journal already knows. No new schema needs to be
#: created for two facts.
TEAM_TASK = "bureau-team"
_SPEND = "bureau_spend"
_STOP = "bureau_stop"
#: Lifting Stop is a SEPARATE event, not a `False` value in the same key.
#: Review A3-4: `is_stopped` took the LAST `bureau_stop` record, and anyone
#: who could call the public `checkpoint_task` could lift the stop with
#: `{bureau_stop: False}`. A stop must be MONOTONIC: only whoever names the
#: CAUSE can lift it, and this is visible in the journal as its own line.
_RESUME = "bureau_resume"
#: How many times a budget reservation is allowed to lose the CAS race
#: before refusing by name. The loser does not "write later" — it re-reads
#: the journal.
_RESERVE_ATTEMPTS = 8
#: What the assignment is ALLOWED to write and what it ran into. Placed
#: with the same `checkpoint` used for the team's spending: no new schema
#: is created for two facts.
_OUTPUTS = "bureau_outputs"
_CONFLICT = "bureau_conflict"
#: A TURN's memory and a served read. Both live in the assignment's
#: configuration under the same `bureau-config` event as the declared
#: outputs: no new schema is created for two lists, and `task_id` (a digest
#: of the text and notes) stays different for turns with different memory —
#: otherwise a second turn would reuse the first turn's assignment.
_MEMORY = "bureau_memory"
_TOOL_RESULTS = "bureau_tool_results"
#: The cause of the stop. It lives IN THE SAME event as the stop itself:
#: otherwise "who stopped it" would be read from neighboring records rather
#: than from one line.
_STOP_REASON = "bureau_stop_reason"
#: A served project read is a trace in the team's book. It is NOT a
#: provider call and does not count against the call budget; the record
#: exists so that "the bureau answered with data" is a fact of the journal,
#: not just a word in a report.
_READ = "bureau_read"
# Explicit key policy only; arbitrary strings may still contain user-authored
# sensitive text. This is not a universal secret detector or a prompt firewall.
SENSITIVE_CONTEXT_FIELDS = frozenset({
    'token', 'api_key', 'api_token', 'password', 'authorization', 'credentials', 'secret',
    'access_token', 'refresh_token', 'session_token', 'bearer_token', 'oauth_token',
    'client_secret', 'client_assertion', 'private_key', 'secret_key',
    'openai_api_key', 'anthropic_api_key', 'azure_openai_api_key', 'google_api_key',
    'gemini_api_key', 'cohere_api_key', 'mistral_api_key', 'groq_api_key', 'together_api_key',
    'aws_secret_access_key', 'aws_session_token', 'aws_access_key_id'})


class BureauRefusal(TaskError):
    """A bureau refusal: it has a code, and it happens BEFORE the provider call.

    `calls`/`tokens` are non-empty only for a refusal that happened AFTER
    the call (`stopped_during_call`): the spending is already in the
    journal, and staying silent about it in the result would mean reporting
    zero for what was spent.
    """

    def __init__(self, code: str, message: str, *, calls: int = 0, tokens: int = 0):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.calls, self.tokens = calls, tokens


@dataclass(frozen=True)
class TeamBudget:
    """A TEAM limit, not a task limit. The per-task limit already exists and remains."""

    max_calls: int
    max_tokens: int

    def __post_init__(self):
        for name in ("max_calls", "max_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise BureauRefusal("bad_team_budget", f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class WorkResult:
    task_id: str
    proposal_id: str | None
    refusal: dict | None
    calls: int
    tokens: int
    author_digest: str | None = None
    answer_sha256: str | None = None
    #: WHO answered. Appended at the tail with a default value.
    #:
    #: 🔴 THIS USED TO BE A HARDCODED "tape" STRING IN THE INSTANCE'S
    #: METADATA, and in live-agent mode the accepted revision WOULD CLAIM
    #: "stand-in" even though `claude-code-agent` had answered. A lie in the
    #: project's history is more expensive than any savings: `provider_id`
    #: is taken from the ANSWER and rides into both the result and the
    #: metadata — one value, two readers.
    provider_id: str | None = None
    usage_basis: str | None = None
    replayed: bool = False

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "proposal_id": self.proposal_id,
                "refusal": self.refusal, "calls": self.calls, "tokens": self.tokens,
                "author_digest": self.author_digest, "answer_sha256": self.answer_sha256,
                "provider_id": self.provider_id, "usage_basis": self.usage_basis,
                "replayed": self.replayed}


@dataclass(frozen=True)
class Decisions:
    accepted: tuple
    conflicted: tuple
    replanned: tuple
    #: Coordination interrupted by a Stop MIDWAY. Appended at the tail with
    #: a default value: decisions already accepted are durable, and they
    #: must not be lost for the sake of a neat exception — but staying
    #: silent about the rest not having been considered is not allowed
    #: either.
    stopped: bool = False

    def to_dict(self) -> dict:
        return {"accepted": list(self.accepted), "conflicted": list(self.conflicted),
                "replanned": list(self.replanned), "stopped": self.stopped}


# ── team book: spending and Stop through one journal ───────────────────────
def _team(store):
    try:
        return read_task(store, TEAM_TASK)
    except StoreNotFound:
        return None


def _ensure_team(store):
    task = _team(store)
    if task is not None:
        return task
    head = store.head()
    return create_task(store, task_id=TEAM_TASK, base_revision=head.revision_id,
                       actor="bureau-coordinator",
                       objective="книга команды: расход провайдера и флаг Stop",
                       scope=ProposalScope(), tools=(), budgets={"max_tool_calls": 0})["task"]


def _ticket() -> str:
    """A one-time request number. It MUST be unique, and here is why.

    🔴 THE JOURNAL IS IDEMPOTENT ON `request_id`: an event with an
    already-seen number and the same body is NOT inserted, it is returned
    as the earlier one — and the caller cannot tell "I wrote it" from
    "someone wrote the same thing." A number computed from CONTENT and
    version would coincide for two processes in exactly the race the
    reservation exists to guard against: the second would silently "reuse"
    someone else's record and spend a call for free.
    """
    return _hash([time.time_ns(), os.getpid(), os.urandom(8).hex()])[:32]


def _append(store, notes: dict, *, attempts: int = _RESERVE_ATTEMPTS) -> None:
    """Append an event to the team book, RE-READING the head when CAS is lost."""
    from kir.project_store import StoreConflict

    last = None
    for _ in range(max(1, attempts)):
        task = _ensure_team(store)
        try:
            checkpoint_task(store, TEAM_TASK, request_id=_ticket(),
                            expected_version=task["version"], generation=task["generation"],
                            actor="bureau-coordinator", notes=notes)
            return
        except StoreConflict as clash:  # a neighboring writer got there first
            last = clash
    raise BureauRefusal("journal_contended",
                        f"книга команды занята {attempts} попыток подряд: {last}")


def _note(store, notes: dict) -> None:
    _append(store, notes)


def spend(store) -> dict:
    """Reported, estimated, reserved and unknown exposure; never an invoice."""
    from kir.bureau.budget import spend as read_spend
    return read_spend(store)


def stop(store, *, reason: str = "user") -> None:
    """Cooperative Stop. It STOPS things, not merely forbids writing.

    🔴 A STOP HAS A NAME (mandate F7). Previously a stop was a single bit,
    and "a human stopped it" was indistinguishable from "the bureau ran
    into itself." The difference matters operationally: no detector lifts
    a human's stop, while a bureau's named stop (`no_progress`) must name
    WHAT exactly failed to move. The name is written IN THE SAME event as
    the bit: two events can drift apart, one cannot.
    """
    if type(reason) is not str or not reason.strip():
        raise BureauRefusal("stop_needs_reason", "остановка называет свою причину")
    _note(store, {_STOP: True, _STOP_REASON: reason.strip()})


def resume(store, *, reason: str) -> None:
    """Lift Stop — EXPLICITLY and with a cause. There is no other door for a stop.

    Review A3-4 measured: `{bureau_stop: False}`, written by the public
    `checkpoint_task`, lifted the stop silently. Now `False` in that key
    lifts nothing: the stop is monotonic up to this event, and the journal
    shows WHO lifted it and WHY.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise BureauRefusal("resume_needs_reason", "снятие Stop называет причину")
    _note(store, {_RESUME: {"reason": reason.strip()}})


def stop_reason(store) -> str | None:
    """Whose Stop this is. `None` — the team is not stopped."""
    if _team(store) is None:
        return None
    reason = None
    for event in task_history(store, TEAM_TASK):
        notes = (event.get("body") or {}).get("notes") or {}
        if not isinstance(notes, Mapping):
            continue
        if notes.get(_STOP) is True:
            value = notes.get(_STOP_REASON)
            reason = value.strip() if isinstance(value, str) and value.strip() else "user"
        elif _RESUME in notes:
            reason = None
    return reason


def is_stopped(store) -> bool:
    """Whether the team is stopped. A stop is MONOTONIC: only `resume` lifts it."""
    if _team(store) is None:
        return False
    stopped = False
    for event in task_history(store, TEAM_TASK):
        notes = (event.get("body") or {}).get("notes") or {}
        if not isinstance(notes, Mapping):
            continue
        if notes.get(_STOP) is True:
            stopped = True
        elif _RESUME in notes:
            stopped = False
    return stopped


def _gate(store, budget: TeamBudget, planned_tokens: int) -> None:
    """A budget CHECK. By itself it is not a limit — see `_reserve`.

    The order of checks is not accidental: Stop first, then money. A
    stopped team does not spend even what is allowed.
    """
    if is_stopped(store):
        raise BureauRefusal("team_stopped",
                            "the team is stopped; no provider call is made")
    used = spend(store)
    if used["calls"] + 1 > budget.max_calls:
        raise BureauRefusal("call_budget_exhausted",
                            f"team calls {used['calls']}/{budget.max_calls}")
    if used["tokens"] + planned_tokens > budget.max_tokens:
        raise BureauRefusal("token_budget_exhausted",
                            f"team tokens {used['tokens']}+{planned_tokens} > {budget.max_tokens}")


def _reserve(store, budget: TeamBudget, planned_tokens: int) -> None:
    from kir.bureau.budget import reserve
    reserve(store, budget, planned_tokens, attempt_id=_ticket())


def _ask(store, provider, request, budget: TeamBudget):
    from kir.bureau.budget import ask
    return ask(store, provider, request, budget)


# ── assignment, work, coordination ──────────────────────────────────────────
def assign(store, text: str, *, worker_id: str, base_revision: str,
           instance_key: str = "tower-a", outputs=None, conflict=None, remove_fields=None,
           memory=None, tool_results=None, _expected_task_versions=None) -> str:
    """Assign an explicit output patch; omissions preserve authored fields.

    Removing an existing top-level field needs an explicit coordinator decision.
    Legacy assigned tasks are not silently given new tool grants.
    Direct assign is an explicit administrative queue action permitted while
    stopped: it neither computes/applies a proposal nor clears Stop. Automatic
    replanning additionally uses the team-epoch guard.
    """
    from kir.project import _key, _object
    if type(text) is not str or not text.strip():
        raise BureauRefusal("empty_objective", "an assignment requires text")
    _key(instance_key, "instance_key")
    notes = {"bureau_profile": "durable_work/1", "bureau_remove_fields": {}}
    if outputs is not None:
        if not isinstance(outputs, (tuple, list)) or not outputs:
            raise BureauRefusal("no_declared_outputs", "explicit output list must be nonempty")
        if any(type(key) is not str for key in outputs) or len(set(outputs)) != len(outputs):
            raise BureauRefusal("bad_declared_outputs", "distinct output keys required")
        for key in outputs:
            _key(key, "output_key")
        notes[_OUTPUTS] = list(outputs)
    if remove_fields is not None:
        removals = _thaw(_object(remove_fields, "field_removal_decisions"))
        for key, fields in removals.items():
            _key(key, "output_key")
            if (type(fields) is not list or not fields or len(set(fields)) != len(fields)
                    or any(type(name) is not str or name in ("id", "op") for name in fields)
                    or outputs is not None and key not in outputs):
                raise BureauRefusal("bad_field_removal", "named fields within the declared output scope required")
        notes["bureau_remove_fields"] = removals
    if conflict is not None:
        notes[_CONFLICT] = _thaw(_object(conflict, "conflict"))
    if memory is not None:
        if not isinstance(memory, (tuple, list)):
            raise BureauRefusal("bad_memory", "память хода — список сохранённых решений")
        notes[_MEMORY] = [_thaw(_object(row, "memory_entry")) for row in memory]
    if tool_results is not None:
        if not isinstance(tool_results, (tuple, list)):
            raise BureauRefusal("bad_tool_results", "прочитанное — список ответов бюро")
        notes[_TOOL_RESULTS] = [_thaw(_object(row, "tool_result")) for row in tool_results]
    task_id = _hash([text, worker_id, base_revision, instance_key, notes])[:16]
    assigned = create_task(store, task_id=task_id, base_revision=base_revision, actor=worker_id,
        objective=text, scope=ProposalScope(instances=(instance_key,)),
        tools=("llm.complete", "author.python"), budgets={"max_tool_calls": 2},
        expected_task_versions=_expected_task_versions)
    checkpoint_task(store, task_id, request_id="bureau-config",
        expected_version=assigned["event"]["digest"], generation=0, actor=worker_id, notes=notes,
        expected_task_versions=_expected_task_versions)
    return task_id


def _configured_task(store, task):
    result = dict(task)
    event = next((row for row in task_history(store, task["task_id"])
                  if row["request_id"] == "bureau-config" and row["kind"] == "checkpoint"), None)
    result["_bureau_config"] = event["body"]["notes"] if event is not None else {}
    return result


def _task_notes(task) -> dict:
    return task.get("_bureau_config", ((task.get("checkpoint") or {}).get("notes") or {}))


def _declared_outputs(task):
    value = _task_notes(task).get(_OUTPUTS)
    return tuple(value) if isinstance(value, (list, tuple)) else None


def _context_data(value):
    """Only authored data is exposed; runtime secrets/recipe source are not read."""
    if isinstance(value, Mapping):
        return {key: "<redacted>" if key.lower() in SENSITIVE_CONTEXT_FIELDS else _context_data(item)
                for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_context_data(item) for item in value]
    return value


def _saved_decisions(store, revision) -> list:
    """Human decisions ALREADY recorded in the project. Empty means there were none."""
    try:
        from kir.project_refinement import answered_decisions
        return [dict(row) for row in answered_decisions(store, revision)]
    except Exception:  # a foreign module is not obliged to understand every bureau project
        return []


def _project_context(store, task) -> str:
    from kir.project_selection import select_project_instances
    task = _configured_task(store, task)
    revision = store.get(task["assignment"]["base_revision"])
    instance_key = task["assignment"]["scope"]["instances"][0]
    target = next((item for item in revision.instances if item.key == instance_key), None)
    if target is None:
        raise BureauRefusal("unknown_instance", "target is absent from assigned source")
    selection = select_project_instances(revision, instance_keys=(instance_key,))
    addresses = revision.addressed_outputs()
    dependencies = []
    for index in selection.project_source_indices:
        instance, output, oid = addresses[index]
        if instance.key != instance_key:
            dependencies.append({"instance_key": instance.key, "output_key": output.key,
                "output_id": oid, "operation": _thaw(output.operation)})
    context = {"project_id": revision.project_id, "intent": revision.intent,
        "base_revision": revision.revision_id,
        "instances": [{"key": item.key, "module": item.module_key, "outputs": len(item.outputs),
                       "role": "цель" if item.key == instance_key else "сосед"} for item in revision.instances],
        "target_instance": {"key": target.key, "module": target.module_key,
            "parameters": _thaw(target.parameters),
            "outputs": [{"key": output.key, "op": output.operation.get("op"),
                         "output_id": output_id(revision.project_id, target.key, output.key),
                         "operation": _thaw(output.operation)} for output in target.outputs]},
        "dependencies": dependencies,
        "you_may_write": list(_declared_outputs(task)) if _declared_outputs(task) is not None
                        else f"список не объявлен: разрешены любые выходы {instance_key}",
        "field_preservation": "patch_by_output_key; omitted fields and outputs remain unchanged; arrays explicitly replace",
        "remove_fields": _task_notes(task).get("bureau_remove_fields", {}),
        # 🔴 MEMORY IS A SAVED DECISION, NOT CORRESPONDENCE (mandate F7). One
        # half of it comes from the PROJECT (clarification decisions live in
        # instance metadata and survive any process), the other from the
        # team's journal (which turns have already been accepted and at
        # which revision). Neither is derived from the text of past
        # messages: the bureau has no correspondence at all.
        "memory": {"accepted_turns": _task_notes(task).get(_MEMORY, []),
                   "refinement_decisions": _saved_decisions(store, revision)}}
    served = _task_notes(task).get(_TOOL_RESULTS)
    if served:
        context["tool_results"] = served
    if _CONFLICT in _task_notes(task):
        context["conflict"] = _task_notes(task)[_CONFLICT]
    encoded = _canonical(_context_data(context))
    if len(encoded.encode()) > 256 * 1024:
        raise BureauRefusal("context_budget_exceeded", "selected context exceeds 256KiB; choose a smaller instance")
    return encoded


def _request_for(task, store=None) -> Any:
    from kir.bureau.provider import CompletionRequest
    objective = task["assignment"]["objective"]
    messages = [{"role": "user", "content": f"поручение: {objective}"}]
    if store is not None:
        messages.append({"role": "user", "content": f"проект: {_project_context(store, task)}"})
    return CompletionRequest(messages=tuple(messages), max_tokens=2048,
        tags=(objective, f"task:{task['task_id']}:generation:{task['generation']}"))


def _rebind_refs(value, local_ids: set, project_id: str, instance_key: str):
    """A reference INSIDE the model's answer -> an output address IN THE PROJECT.

    🔴 THIS IS EXACTLY WHAT KEPT TWO WORKERS FROM BEING ACCEPTED AT ONCE, AND
    THE CAUSE WAS NOT IN THE DATABASE. Measured: `tower-b` and `tower-c`
    don't intersect at all, yet the second went into `conflict`. The merge
    report named the issue verbatim:
    `dependency_analysis_incomplete` + `unresolved_reference` on the
    `level` field on both sides. The model writes the program with its OWN
    ids (`{'by':'ref','value':'B0'}`), while `project_diff` resolves
    references by the output's ADDRESS
    (`output_id(project_id, instance_key, output_key)`) — and finds `B0` in
    neither. An incomplete dependency analysis forbids ANY divergent merge,
    which is why the first (non-divergent) one went through and the second
    didn't.

    Recipe scripts in `examples/recipes/*` have long written references by
    address (`project_output_id(...)`); the model cannot be required to know
    addresses — it does not see them. The translation happens HERE, and only
    for the values that are declared as outputs in its own answer: a
    foreign name is left untouched and is still honestly named unresolved.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref" and str(value.get("value")) in local_ids:
            return {**{key: item for key, item in value.items()},
                    "value": output_id(project_id, instance_key, str(value["value"]))}
        return {key: _rebind_refs(item, local_ids, project_id, instance_key)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rebind_refs(item, local_ids, project_id, instance_key) for item in value]
    return value


def work(store, task_id: str, *, provider, budget: TeamBudget) -> WorkResult:
    """Resume one existing task-tool attempt, never an unjournaled invocation."""
    from kir.bureau.attempt import work as run_attempt
    return run_attempt(store, task_id, provider=provider, budget=budget)


def conflict_payload(store, task) -> dict:
    """The content of a conflict FOR THE MODEL: three named sides with addresses.

    🔴 ONE TRUTH FOR TWO READERS. This body used to live inside `coordinate`,
    and replanning WITHIN a plan (`kir.bureau.mission`) would have had to
    either call through coordination of the whole journal or write a second,
    identical parser. The second parser would have diverged from the first
    on the very first edit, and the model would have gotten a different
    conflict depending on who called it.

    A live run-3 measurement: `conflict` arrived, but its three sides were
    UNNAMED — which won and which was rejected could only be read from key
    order — and the outputs went out WITHOUT a project address, even though
    `target_instance` prints an address. The model answers with a patch by
    output key and refers to things by address: an unnamed side and an
    addressless output are an invitation to guess, and F7 requires CONTENT.
    """
    from kir.project_merge import ChangeProposal
    report = task.get("decision") or {}
    rows = (report.get("merge") or {}).get("conflicts") or []
    proposed = ChangeProposal.from_dict(task["proposal"])
    target_key = task["assignment"]["scope"]["instances"][0]

    def values(revision):
        instance = next((item for item in revision.instances if item.key == target_key), None)
        if instance is None:
            return None
        return {"instance_key": target_key, "revision_id": revision.revision_id,
                "parameters": _thaw(instance.parameters),
                "outputs": [{**output.to_dict(),
                             "output_id": output_id(revision.project_id, target_key, output.key)}
                            for output in instance.outputs]}

    return _context_data({"issues": rows, "before": values(proposed.base),
                          "current": values(store.head()), "proposed": values(proposed.candidate)})


def replan_text(task, after, rows) -> str:
    """The text of the new assignment. It NAMES the subject, not a request to "just decide again.\""""
    return (f"перепланирование: поручение {task['assignment']['objective']} столкнулось с "
            f"уже принятым решением; голова стала {after.revision_id[:12]}; не сошлось: "
            f"{json.dumps(rows, ensure_ascii=False)} — предложи изменение заново от неё")


def coordinate(store, *, provider=None, budget: TeamBudget | None = None,
               replan: bool = True, only=None) -> Decisions:
    """Accept the non-overlapping ones, name the conflict, and CREATE A NEW ASSIGNMENT.

    🔴 REPLANNING IS A NEW ASSIGNMENT, NOT A REPEAT OF THE OLD ONE. The new
    one has different text (naming the conflict in it), a different
    `task_id` by construction (it is the digest of the text), and a
    `base_revision` that is the head AFTER the conflict, not the one the
    worker made a mistake on. Repeating the old one would mean asking the
    model to solve a task that no longer exists.
    """
    # 🔴 STOP IS CHECKED HERE TOO, NOT ONLY BEFORE CALLING THE MODEL.
    # Accepting a proposal is an action on the PROJECT, and a stopped team
    # does not perform it: "stopped" must mean "nothing more is happening,"
    # not "the model is silent, but the project keeps changing anyway."
    if is_stopped(store):
        raise BureauRefusal("team_stopped",
                            "команда остановлена: координация не принимает и не заводит ничего")
    accepted, conflicted, replanned, halted = [], [], [], False
    listing = list_tasks(store, limit=100)
    rows = listing.get("tasks", listing) if isinstance(listing, dict) else listing
    for row in rows:
        task = _configured_task(store, read_task(store, row["task_id"] if isinstance(row, dict) else row))
        if task["task_id"] == TEAM_TASK or task["state"] != "submitted":
            continue
        # 🔴 COORDINATING SOMEONE ELSE'S IS ANSWERING FOR SOMEONE ELSE. `only`
        # narrows the turn to named tasks: a parallel plan worker has
        # nothing to decide for its neighbor, and without the narrowing two
        # processes fought over the same task (measured 07.09:
        # `request ID reused for different input`).
        if only is not None and task["task_id"] not in only:
            continue
        if is_stopped(store):
            halted = True
            break
        head = store.head()
        from kir.bureau.attempt import guarded
        try:
            decision = guarded(store, {**task, "actor": "bureau-coordinator"}, decide_task,
                refresh=lambda arguments: {**arguments,
                                           "expected_revision": store.head().revision_id},
                request_id=f"decide-{task['version'][:16]}", expected_revision=head.revision_id,
                proposal_id=task["proposal"]["proposal_id"])
        except BureauRefusal as refusal:
            if refusal.code != "team_stopped":
                raise
            halted = True
            break
        except TaskError as clash:
            # The same turn is being decided by a neighboring process: the
            # decision's `request_id` is the same (it comes from the task's
            # version), but our heads already differ. The journal honestly
            # refuses with "request ID reused for different input" — but
            # that is not a failure, it is SOMEONE ELSE'S DECISION. We read
            # the task's state and take it.
            current = read_task(store, task["task_id"])
            if current["state"] == "accepted":
                accepted.append(task["task_id"])
                continue
            if current["state"] == "conflicted":
                conflicted.append(task["task_id"])
                continue
            raise BureauRefusal("decision_contended",
                                f"решение по {task['task_id'][:12]} не состоялось: {clash}")
        state = decision["task"]["state"]
        if state == "accepted":
            accepted.append(task["task_id"])
            continue
        conflicted.append(task["task_id"])
        if not replan:
            continue
        after = store.head()
        conflict = conflict_payload(store, {**task, "decision":
            (decision.get("task") or {}).get("decision")})
        rows = conflict["issues"]
        target_key = task['assignment']['scope']['instances'][0]
        text = replan_text(task, after, rows)
        team = _ensure_team(store)
        if is_stopped(store):
            halted = True
            break
        new_id = assign(store, text, worker_id=task["actor"], base_revision=after.revision_id,
                        instance_key=target_key, outputs=_declared_outputs(task), conflict=conflict,
                        remove_fields=_task_notes(task).get('bureau_remove_fields') or None,
                        _expected_task_versions={TEAM_TASK: team['version']})
        replanned.append(new_id)
    return Decisions(tuple(accepted), tuple(conflicted), tuple(replanned), halted)


# ── model tool: read the project by address ─────────────────────────────────
#: How many addresses are served per request. The limit isn't there for
#: politeness: without it, an answer of "read everything" would return the
#: whole project and hit the context ceiling only AFTER a provider call had
#: already been spent.
MAX_READ_ADDRESSES = 16
READ_KEY = "kir_read"


def read_request(text) -> list | None:
    """Is the model's answer a request to read the project? Then its addresses; otherwise `None`.

    🔴 WHY A REQUEST IS ONLY READ FROM THE WHOLE ANSWER. The model's program
    is ordinary Python, and `{"kir_read": [...]}` can occur inside it as a
    dict. Treating a fragment as a request would mean voiding a perfectly
    working program on a substring match. A request is the WHOLE answer: one
    JSON object with exactly one key, `kir_read`.
    """
    if not isinstance(text, str) or "{" not in text:
        return None
    try:
        parsed = json.loads(text.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {READ_KEY}:
        return None
    addresses = parsed[READ_KEY]
    if not isinstance(addresses, list) or not addresses or len(addresses) > MAX_READ_ADDRESSES:
        return None
    if any(type(item) is not str or not item.strip() for item in addresses):
        return None
    return [item.strip() for item in addresses]


def _read_one(revision, address: str) -> dict:
    """Values at one address: `экземпляр` or `экземпляр/выход`."""
    parts = address.split("/")
    if len(parts) not in (1, 2):
        return {"address": address, "error": "unknown_address"}
    instance = next((item for item in revision.instances if item.key == parts[0]), None)
    if instance is None:
        return {"address": address, "error": "unknown_address"}
    if len(parts) == 1:
        return {"address": address, "instance_key": instance.key, "module": instance.module_key,
                "parameters": _thaw(instance.parameters),
                "outputs": [{"key": output.key,
                             "output_id": output_id(revision.project_id, instance.key, output.key),
                             "operation": _thaw(output.operation)} for output in instance.outputs]}
    output = next((item for item in instance.outputs if item.key == parts[1]), None)
    if output is None:
        return {"address": address, "error": "unknown_address"}
    return {"address": address, "instance_key": instance.key, "output_key": output.key,
            "output_id": output_id(revision.project_id, instance.key, output.key),
            "operation": _thaw(output.operation)}


def serve_read(store, task, addresses) -> dict:
    """Answer the model with project DATA. This is NOT a provider call and does not spend the budget.

    🔴 WHAT IS HONEST HERE, AND WHAT IS NOT. Honest: reading asks no one
    outside, so there is neither a reservation nor spending in the team
    book — `spend()['calls']` does not change after a served read, and this
    is checked by a number. It would NOT be honest to call the read "free,
    period": the model's next turn is an ordinary call, and it costs exactly
    one call, like any other.
    """
    if not isinstance(addresses, (list, tuple)) or not addresses:
        raise BureauRefusal("empty_read_request", "просьба прочитать называет адреса")
    if len(addresses) > MAX_READ_ADDRESSES:
        raise BureauRefusal("read_request_too_wide",
                            f"адресов {len(addresses)} > {MAX_READ_ADDRESSES}; назови нужные")
    revision = store.get(task["assignment"]["base_revision"])
    values = [_read_one(revision, str(item)) for item in addresses]
    served = {"tool": "project.read", "revision_id": revision.revision_id,
              "task_id": task["task_id"], "values": _context_data(values)}
    _note(store, {_READ: served})
    return served
