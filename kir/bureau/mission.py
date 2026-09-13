# -*- coding: utf-8 -*-
"""A long-running bureau task: turns, dependencies, decision memory, "no progress."

🔴 WHAT IS NEW HERE AND WHAT IS REUSED. A second runtime is not being
built: an assignment is still created by `runner.assign`, a turn is made
by `runner.work`, accepted by `runner.coordinate`, and state still lives in
the same `checkpoint` events of the team book as spending and Stop. Exactly
four things are new, and each closes a gap named by mandate F7:

* **a turn plan** — the bureau had no notion of a "turn." After a process
  crash, another process had nothing to continue: it knew neither how many
  turns were planned nor which had already been made. The plan and turn
  records are durable, so ANY process continues by reading the journal, not
  its own object's memory;
* **dependencies** — `assign` doesn't know about other assignments,
  `coordinate` takes every `submitted` one in a row. A dependent subtask now
  does not exist as an assignment until the one it depends on has been
  accepted: its `base_revision` is taken AFTER acceptance, not before;
* **memory** — `runner._project_context` shows current values; it didn't
  know how earlier turns ended. A turn's memory is its saved decisions: the
  accepted revisions of earlier turns from the journal and the clarification
  decisions from the project. The bureau has no correspondence at all, and
  there is nothing from which to reconstruct it;
* **a stalling detector** — previously the only thing that stopped useless
  turns was an exhausted budget, i.e. `max_calls` empty calls. Three turns
  in a row with no movement of the head now produce a NAMED stop,
  `no_progress`.

What is NOT here, and must not be added: a planner that invents turns on
its own. Turns are named by whoever sets the task; the bureau executes
them, remembers them, and knows how to stop honestly.
"""
from __future__ import annotations

from typing import Mapping

from kir.bureau import runner as R
from kir.project import _thaw

__all__ = ["DEFAULT_LIMITS", "LIMIT_BOUNDS", "MAX_READS_PER_STEP", "MEMORY_WINDOW",
           "NO_PROGRESS_TURNS", "REPLAN_ATTEMPTS", "advance", "limits_of", "plan", "plan_state",
           "reads", "steps_of"]

_PLAN = "bureau_plan"
_STEP = "bureau_step"
#: How many times a single turn may ask the bureau to read the project.
#: Reading does not spend provider calls, but every next ANSWER from the
#: model does: without a limit, "read again" would become a perpetual
#: motion machine running on someone else's money.
MAX_READS_PER_STEP = 2
#: How many turns in a row with no movement of the DESIGN INTENT count as stalling.
NO_PROGRESS_TURNS = 3
#: How many lines of memory ride out to the model. A window, not a
#: transcript: at fifty accepted turns a full list would grow together with
#: the task and would kill it all the more surely the longer it runs. The
#: window's first line is a summary of what was cut.
MEMORY_WINDOW = 8
#: How many times a conflicting turn is replanned WITHIN the plan. One
#: attempt is "show the model what didn't match, and let it decide from the
#: new head"; a second failure means the dispute isn't about phrasing, and
#: calling the model a third time would be spending someone else's money on
#: the same wall.
REPLAN_ATTEMPTS = 1
#: Defaults and bounds for the limits. 🔴 A LIMIT IS A PROPERTY OF THE PLAN,
#: NOT OF THE MODULE: one design intent is entitled to be stricter than
#: another, and "adjust the constant" for the sake of one plan would mean
#: changing the rules for everyone at once, including plans already under
#: way.
DEFAULT_LIMITS = {"memory_window": MEMORY_WINDOW, "max_reads_per_step": MAX_READS_PER_STEP,
                  "no_progress_turns": NO_PROGRESS_TURNS, "replan_attempts": REPLAN_ATTEMPTS}
LIMIT_BOUNDS = {"memory_window": (2, 64), "max_reads_per_step": (0, 8),
                "no_progress_turns": (2, 32), "replan_attempts": (0, 4)}
_TERMINAL = ("accepted", "conflicted", "no_change")


def _entries(store, key):
    from kir.project_store import StoreNotFound
    try:
        events = R.task_history(store, R.TEAM_TASK)
    except StoreNotFound:
        return []
    rows = []
    for event in events:
        notes = (event.get("body") or {}).get("notes") or {}
        if isinstance(notes, Mapping) and key in notes:
            rows.append(_thaw(notes[key]))
    return rows


def _plan_record(store, plan_id):
    for row in _entries(store, _PLAN):
        if row.get("plan_id") == plan_id:
            return row
    return None


def _step_records(store, plan_id):
    return [row for row in _entries(store, _STEP) if row.get("plan_id") == plan_id]


def _checked_steps(steps):
    if not isinstance(steps, (tuple, list)) or not steps:
        raise R.BureauRefusal("empty_plan", "план длительной задачи называет хотя бы один ход")
    checked = []
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise R.BureauRefusal("bad_step", f"ход {index}: ожидается объект")
        text, worker = step.get("text"), step.get("worker_id")
        instance = step.get("instance_key")
        for name, value in (("text", text), ("worker_id", worker), ("instance_key", instance)):
            if type(value) is not str or not value.strip():
                raise R.BureauRefusal("bad_step", f"ход {index}: поле `{name}` — непустой текст")
        outputs = step.get("outputs")
        if outputs is not None and (not isinstance(outputs, (tuple, list)) or not outputs):
            raise R.BureauRefusal("bad_step", f"ход {index}: `outputs` — непустой список")
        depends = step.get("depends_on") or ()
        if not isinstance(depends, (tuple, list)):
            raise R.BureauRefusal("bad_step", f"ход {index}: `depends_on` — список номеров")
        for dependency in depends:
            # A dependency ONLY points backward: a cycle in the plan is not
            # a "complex plan," it's a promise that no one can be first to
            # keep.
            if type(dependency) is not int or not 0 <= dependency < index:
                raise R.BureauRefusal("bad_dependency",
                                      f"ход {index}: зависимость {dependency!r} не назад")
        checked.append({"text": text, "worker_id": worker, "instance_key": instance,
                        "outputs": list(outputs) if outputs is not None else None,
                        "depends_on": [int(item) for item in depends]})
    return checked


def _checked_limits(limits):
    """Plan limits: only known names, integers, within bounds. Otherwise — refuse by name."""
    if limits is None:
        return {}
    if not isinstance(limits, Mapping):
        raise R.BureauRefusal("bad_limit", "пределы плана — объект имя->целое")
    checked = {}
    for name, value in limits.items():
        if name not in LIMIT_BOUNDS:
            raise R.BureauRefusal("bad_limit", f"{name!r}: неизвестный предел; "
                                               f"есть {sorted(LIMIT_BOUNDS)}")
        low, high = LIMIT_BOUNDS[name]
        # `bool` is a subclass of `int`: `True` would pass as 1 and silently change the rule.
        if type(value) is not int or not low <= value <= high:
            raise R.BureauRefusal("bad_limit",
                                  f"{name}={value!r}: ожидается целое в [{low}, {high}]")
        checked[name] = value
    return checked


def limits_of(store, plan_id: str) -> dict:
    """Limits of THIS plan. Records without `limits` are read with defaults."""
    record = _plan_record(store, plan_id)
    if record is None:
        raise R.BureauRefusal("unknown_plan", f"план {plan_id} не записан")
    return {**DEFAULT_LIMITS, **(record.get("limits") or {})}


def plan(store, plan_id: str, steps, *, limits=None) -> dict:
    """Record the turn plan. A repeat with the same plan is not an error; with a different one, a refusal."""
    if type(plan_id) is not str or not plan_id.strip():
        raise R.BureauRefusal("bad_plan_id", "у плана есть имя")
    record = {"plan_id": plan_id, "steps": _checked_steps(steps)}
    checked = _checked_limits(limits)
    if checked:
        # The key appears ONLY when limits are named: otherwise a plan
        # record made before this fix would stop equaling its own copy, and
        # a repeated `plan()` would refuse with `plan_already_exists` out of
        # nowhere.
        record["limits"] = checked
    existing = _plan_record(store, plan_id)
    if existing is not None:
        if existing != record:
            raise R.BureauRefusal("plan_already_exists",
                                  f"план {plan_id} уже записан другим составом ходов")
        return existing
    R._note(store, {_PLAN: record})
    return record


def steps_of(store, plan_id: str) -> list:
    record = _plan_record(store, plan_id)
    if record is None:
        raise R.BureauRefusal("unknown_plan", f"план {plan_id} не записан")
    return list(record["steps"])


def _authored(store, revision_id, instance_key):
    """Fingerprint of the target's DESIGN INTENT: parameters and operations without bureau metadata.

    🔴 WHY NOT THE REVISION'S sha. Self-review 07.09 measured: the model
    rewrote the SAME value, the merge accepted it — and the head's sha
    changed anyway, because the bureau stamps its own
    `field_preservation.base_revision`, the answer's fingerprint, and the
    provider into the instance's metadata. That means by revision, "motion"
    is ALWAYS present, and a stalling detector built on it is blind to
    exactly the case it was made for. Progress is measured by what the
    human ordered — the author's own values.
    """
    from kir.project import _hash
    try:
        revision = store.get(revision_id)
    except Exception:
        return None
    instance = next((item for item in revision.instances if item.key == instance_key), None)
    if instance is None:
        return None
    return _hash([_thaw(instance.parameters),
                  [[output.key, _thaw(output.operation)] for output in instance.outputs]])[:32]


def _latest(records, index):
    terminal = [row for row in records if row.get("step") == index and row.get("state") in _TERMINAL]
    return terminal[-1] if terminal else None


def _open_assignment(records, index):
    """A turn taken but not completed: a booking and/or an assignment already created."""
    rows = [row for row in records if row.get("step") == index]
    open_row = None
    for row in reversed(rows):
        if row.get("state") in _TERMINAL:
            break
        if row.get("state") == "assigned":
            return row
        if row.get("state") == "claimed" and open_row is None:
            open_row = row
    return open_row


def _claim(store, plan_id, index, attempt, head_before, nonce=None) -> bool:
    """Take a turn. Atomically, with the existing journal, no new lock.

    🔴 WHY NOT `create_task`. The first edit took a turn by relying on
    `task_id` being the digest of the assignment, and counted on
    `StoreConflict("task already exists")`. Measured with two processes
    (6 runs): for two workers the assignment MATCHES BYTE FOR BYTE, and the
    journal is idempotent on `request_id` — the second `create_task` does
    not collide, it comes back as the same earlier event, as a successful
    delivery. The booking built on that was false: both took turn 0.

    Here it is exactly the reverse: the ticket (`request_id`) is the SAME
    for both — `plan:turn:attempt` — but the body is DIFFERENT (its own
    one-time number). The journal answers this with
    `TaskError("request ID reused for different input")` inside its own
    transaction — and that is the booking's loss. One's own retry with the
    same number remains idempotent, as it should.
    """
    from kir.project_store import StoreConflict
    from kir.project_tasks import TaskError

    nonce = nonce or R._ticket()
    # 🔴 ONE'S OWN RETRY IS NOT A FOREIGN CLAIM. The journal's idempotency
    # also accounts for `expected_version`, and after MY OWN write it is
    # already different: a repeated booking with the same number would get
    # "ticket taken by a foreign body" and the process would lose its own
    # turn. One's own booking is recognized by the number in the journal,
    # not by luck.
    if any(row.get("step") == index and row.get("state") == "claimed"
           and row.get("claim") == nonce for row in _step_records(store, plan_id)):
        return True
    notes = {_STEP: {"plan_id": plan_id, "step": index, "state": "claimed",
                     "head_before": head_before, "claim": nonce}}
    # The ticket is a journal key (ASCII, no ":"), so the plan name is taken
    # as a digest: it is the same for both processes, and foreign
    # characters in the name don't break the record.
    from kir.project import _hash
    request_id = "bureau-claim-" + _hash([plan_id, index, attempt])[:32]
    import random
    import time

    last = None
    for _ in range(R._RESERVE_ATTEMPTS * 3):
        team = R._ensure_team(store)
        try:
            R.checkpoint_task(store, R.TEAM_TASK, request_id=request_id,
                              expected_version=team["version"], generation=team["generation"],
                              actor="bureau-coordinator", notes=notes)
            return True
        except StoreConflict as clash:      # a neighboring write to the book — re-read the version
            last = clash
            time.sleep(random.uniform(0.004, 0.02))
        except TaskError:                   # the same turn is already taken by a FOREIGN ticket
            return False
    raise R.BureauRefusal("claim_contended",
                          f"бронь хода {index} не состоялась за {R._RESERVE_ATTEMPTS} попыток: {last}")


def plan_state(store, plan_id: str) -> dict:
    """Plan state from the JOURNAL: what's done, what's taken, what's waiting.

    🔴 "READY" AND "TAKEN" ARE DIFFERENT THINGS, AND BOTH USED TO BE CALLED
    `ready`. Two processes would read the same "free" and take ONE turn. A
    taken turn is called `claimed`, and `next` does not offer it: the
    neighbor gets the next free one, and picking up someone else's is a
    separate decision (`resume_claimed`).
    """
    steps = steps_of(store, plan_id)
    limits = limits_of(store, plan_id)
    records = _step_records(store, plan_id)
    rows, following, computed = [], None, {}
    for index, step in enumerate(steps):
        done = _latest(records, index)
        served = [row for row in records if row.get("step") == index and row.get("state") == "read"]
        conflicts = [row for row in records
                     if row.get("step") == index and row.get("state") == "conflicted"]
        open_row = _open_assignment(records, index)
        if done is not None and done["state"] == "conflicted" \
                and len(conflicts) <= limits["replan_attempts"]:
            state = "replan_due"
        elif done is not None:
            state = done["state"]
        elif open_row is not None:
            state = "claimed"
        else:
            dependencies = [computed[item] for item in step["depends_on"]]
            if all(item == "accepted" for item in dependencies):
                state = "ready"
            elif any(item in ("blocked", "conflicted", "no_change") for item in dependencies):
                state = "blocked"
            else:
                state = "waiting"
        computed[index] = state
        rows.append({"step": index, "state": state, "objective": step["text"],
                     "worker_id": step["worker_id"], "instance_key": step["instance_key"],
                     "depends_on": list(step["depends_on"]), "reads": len(served),
                     "replans": len(conflicts),
                     "task_id": (done or open_row or {}).get("task_id"),
                     "revision_id": (done or {}).get("revision_id"),
                     "proposal_id": (done or {}).get("proposal_id")})
        if following is None and state in ("ready", "replan_due"):
            following = index
    return {"plan_id": plan_id, "steps": rows, "next": following, "limits": limits,
            "complete": all(row["state"] in ("accepted", "conflicted", "no_change", "blocked")
                            for row in rows),
            "stopped": R.is_stopped(store), "stop_reason": R.stop_reason(store)}


def reads(store, plan_id: str) -> list:
    """What the bureau read from the project at the model's request. Not a single read is a call."""
    return [row["served"] for row in _step_records(store, plan_id) if row.get("state") == "read"]


def _memory(store, plan_id, upto, limits=None):
    """Saved decisions of PREVIOUS turns — from the journal, not from correspondence."""
    records = _step_records(store, plan_id)
    steps = steps_of(store, plan_id)
    memory = []
    for index in range(len(steps)):
        if index == upto:
            continue
        done = _latest(records, index)
        if done is None or done["state"] != "accepted":
            continue
        memory.append({"step": index, "objective": steps[index]["text"],
                       "worker_id": steps[index]["worker_id"], "task_id": done["task_id"],
                       "revision_id": done["revision_id"], "proposal_id": done["proposal_id"]})
    window = (limits or DEFAULT_LIMITS)["memory_window"]
    if len(memory) <= window:
        return memory
    shown = memory[-(window - 1):]
    return [{"summary": True, "accepted_total": len(memory), "shown": len(shown),
             "omitted": len(memory) - len(shown), "first_step": memory[0]["step"],
             "first_objective": memory[0]["objective"],
             "first_revision_id": memory[0]["revision_id"],
             "note": "показаны последние ходы; срезанное живёт в журнале команды"}] + shown


def _no_progress(store, plan_id, limits=None) -> bool:
    """Three completed turns in a row that did not move the DESIGN INTENT — that is stalling.

    An accepted turn also counts as stalling if the target's author values
    are the same after it: "accepted" speaks about the merge, not about the
    project.
    """
    turns = (limits or DEFAULT_LIMITS)["no_progress_turns"]
    terminal = [row for row in _step_records(store, plan_id) if row.get("state") in _TERMINAL]
    tail = terminal[-turns:]
    if len(tail) < turns:
        return False
    return all(row.get("authored_after", row.get("revision_id"))
               == row.get("authored_before", row.get("head_before")) for row in tail)


def advance(store, plan_id: str, *, provider, budget, resume_claimed: bool = False) -> dict:
    """Make ONE next FREE turn of the plan. Completed ones are not re-asked.

    🔴 WHY ONE TURN, NOT A LOOP TO THE END. A loop inside a single function
    lives exactly as long as the process does: a crash in the middle of it
    leaves no trace to continue from. A turn is a unit the journal knows how
    to name, and that is exactly why another process continues from turn 3,
    not from the start.

    🔴 THE BOOKING IS `create_task`, NOT A NEW LOCK. An assignment's
    `task_id` is the digest of its text, worker, head, and notes, so for two
    processes on the same turn it is THE SAME, and
    `project_tasks.create_task` on a taken id throws `StoreConflict` inside
    its own transaction. The loser does not wait and does not do someone
    else's work: it takes the next free turn, and if none are free, it
    honestly returns `claim_lost`.

    `resume_claimed=True` is a separate door for PICKING UP someone else's
    unfinished turn (the process crashed midway). It is closed by default:
    otherwise a parallel worker would silently do its neighbor's work.

    Reading the project at the model's request happens INSIDE the turn and
    does not cost a call.
    """
    if R.is_stopped(store):
        raise R.BureauRefusal("team_stopped",
                              f"команда остановлена ({R.stop_reason(store)}): ход не делается")
    limits = limits_of(store, plan_id)
    steps = steps_of(store, plan_id)
    lost = set()
    while True:
        state = plan_state(store, plan_id)
        index = next((row["step"] for row in state["steps"]
                      if row["state"] in ("ready", "replan_due") and row["step"] not in lost), None)
        resumed_claim = False
        if index is None:
            taken = [row["step"] for row in state["steps"] if row["state"] == "claimed"]
            if taken and resume_claimed:
                index, resumed_claim = taken[0], True
            elif taken or lost:
                return {"plan_id": plan_id, "step": (taken or sorted(lost))[0],
                        "state": "claim_lost", "revision_id": store.head().revision_id,
                        "detail": "свободных ходов нет: остальные взяты другими процессами; "
                                  "подхватить чужой — resume_claimed=True"}
            else:
                return {"plan_id": plan_id, "step": None, "state": "complete",
                        "revision_id": store.head().revision_id}
        step = steps[index]
        head_before = store.head().revision_id
        authored_before = _authored(store, head_before, step["instance_key"])
        records = _step_records(store, plan_id)
        previous = [row for row in records
                    if row.get("step") == index and row.get("state") == "conflicted"]
        replan, conflict, text = len(previous), None, step["text"]
        if replan:
            # Replanning WITHIN the plan: the model must have a subject of
            # dispute, not a request to "just decide again." The same
            # comparison used for coordination is reused here — a second,
            # different one would diverge from the first on the very first
            # edit, and the model would get a different conflict depending
            # on who called.
            failed = R.read_task(store, previous[-1]["task_id"])
            conflict = R.conflict_payload(store, failed)
            text = R.replan_text(failed, store.head(), conflict["issues"])
        held = _open_assignment(records, index) if resumed_claim else None
        if held is not None and held.get("task_id"):
            task_id = held["task_id"]
            break
        if not resumed_claim and not _claim(store, plan_id, index, replan, head_before):
            # 🔴 THE LOSER TAKES THE NEXT FREE ONE, AND DOES NOT WAIT OR DO
            # SOMEONE ELSE'S WORK. The booking happened inside a foreign
            # transaction; this process's turn is the neighboring one, and
            # only if none are left free does it honestly say `claim_lost`
            # instead of a silent standstill.
            lost.add(index)
            continue
        # The assignment for a taken turn is idempotent: the body is the
        # same, so a retry after a crash between booking and creation will
        # return THE SAME assignment.
        task_id = R.assign(store, text, worker_id=step["worker_id"],
                           base_revision=head_before, instance_key=step["instance_key"],
                           outputs=tuple(step["outputs"]) if step["outputs"] else None,
                           memory=_memory(store, plan_id, index, limits), conflict=conflict)
        R._note(store, {_STEP: {"plan_id": plan_id, "step": index, "state": "assigned",
                                "task_id": task_id, "head_before": head_before}})
        break
    served, count, result = [], 0, None
    while True:
        if served:
            task_id = R.assign(store, text, worker_id=step["worker_id"],
                               base_revision=head_before, instance_key=step["instance_key"],
                               outputs=tuple(step["outputs"]) if step["outputs"] else None,
                               memory=_memory(store, plan_id, index, limits), conflict=conflict,
                               tool_results=served)
            R._note(store, {_STEP: {"plan_id": plan_id, "step": index, "state": "assigned",
                                    "task_id": task_id, "head_before": head_before}})
        result = R.work(store, task_id, provider=provider, budget=budget)
        refusal = result.refusal or {}
        if refusal.get("code") != "read_requested":
            break
        count += 1
        R._note(store, {_STEP: {"plan_id": plan_id, "step": index, "state": "read",
                                "task_id": task_id, "served": refusal["read"]}})
        served = served + [refusal["read"]]
        if count >= limits["max_reads_per_step"]:
            refusal = {"code": "read_budget_exhausted", "reads": count}
            result = None
            break
    common = {"plan_id": plan_id, "step": index, "task_id": task_id, "reads": count,
              "replan": replan, "head_before": head_before, "authored_before": authored_before}
    if result is not None and result.refusal is None:
        R.coordinate(store, replan=False, only=(task_id,))
        # 🔴 THE OUTCOME IS READ FROM ONE'S OWN TASK, NOT FROM MEMBERSHIP IN
        # `Decisions`. `coordinate` takes ALL `submitted` ones in a row: a
        # neighboring process accepts my proposal first, and my `task_id` no
        # longer makes it into MY OWN response. Recording `no_change` then
        # would mean lying about the accepted project.
        mine = R.read_task(store, task_id)["state"]
        outcome = mine if mine in ("accepted", "conflicted") else "no_change"
        record = {**common, "state": outcome, "proposal_id": result.proposal_id,
                  "revision_id": store.head().revision_id,
                  "authored_after": _authored(store, store.head().revision_id,
                                              step["instance_key"])}
    else:
        record = {**common, "state": "no_change", "proposal_id": None,
                  "revision_id": store.head().revision_id,
                  "authored_after": _authored(store, store.head().revision_id,
                                              step["instance_key"]),
                  "refusal": (result.refusal if result is not None else refusal)}
    R._note(store, {_STEP: record})
    if record["state"] == "conflicted" and replan >= limits["replan_attempts"]:
        # A named stop, not a silent continuation until the budget runs
        # out: the unspent calls are visible as a number.
        R.stop(store, reason="replan_exhausted")
        raise R.BureauRefusal("replan_exhausted",
                              f"ход {index} столкнулся снова после "
                              f"{limits['replan_attempts']} перепланирования; спор не про "
                              f"формулировку — нужно решение человека")
    if _no_progress(store, plan_id, limits):
        R.stop(store, reason="no_progress")
        raise R.BureauRefusal("no_progress",
                              f"ходов подряд без движения замысла: "
                              f"{limits['no_progress_turns']}; авторские значения "
                              f"`{step['instance_key']}` те же ({str(authored_before)[:12]})")
    return record
