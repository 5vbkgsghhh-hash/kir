# -*- coding: utf-8 -*-
"""Mandate F7, next turn: turn reservation, replanning inside the plan, limits.

🔴 WHAT THE CODE RECON OF 07.09 SHOWED, AND WHAT DID NOT HOLD.

* **reservation** — `advance` read `plan_state`, took `next`, and reused an
  already-issued assignment. Two processes took ONE turn. An atomic primitive existed in
  the tree (`project_tasks.create_task` throws `StoreConflict` on an occupied
  `task_id`, and `task_id` is a digest of the assignment, meaning it is the same
  for both processes), but nobody consulted it;
* **the turn's outcome** — was determined by membership in the `Decisions` of the CURRENT
  `coordinate` call. But `coordinate` takes ALL `submitted` tasks, not only its own: a neighbouring
  process would accept my proposal, and my turn would be recorded as `no_change` for an
  accepted project. A lie in the journal about a project that succeeded;
* **replanning inside the plan** — `advance` called `coordinate(replan=False)`,
  and a conflicted turn stayed conflicted forever; anything dependent on it got
  `blocked`, while `plan_state.complete` still declared the plan done;
* **limits** — `MEMORY_WINDOW`/`MAX_READS_PER_STEP`/`NO_PROGRESS_TURNS` were
  module-level constants: one plan could not be stricter than another.

The provider here is a deterministic stub, not a paid model.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from kir.bureau import mission as M
from kir.bureau import runner as R
from kir.bureau.provider import CompletionResponse, request_key
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.project_tasks import read_task

ROOT = Path(__file__).resolve().parents[3]
CHILD_ENV = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
PROJECT = "bureau-plan"


def _wing(key):
    """A self-contained wing: its own level and its own wall onto that level.

    🔴 TWO WORKERS MUST BE INDEPENDENT IN DATA, NOT ONLY IN TURNS.
    The first edition of the scene gave one a `datum` and the other a `section` whose wall
    REFERENCES that `datum`: the second one went into `conflict` not because of the reservation,
    but because of a real dependency. The reservation is checked on something that is truly parallel.
    """
    return ModuleInstance(key, "explicit", {
        "level": {"op": "create_level", "elev_mm": 0},
        "wall": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                 "level": {"by": "ref", "value": output_id(PROJECT, key, "level")}}})


def _source():
    return ProjectRevision(PROJECT, [ModuleDefinition("explicit")], [
        _wing("wing-a"), _wing("wing-b"),
        ModuleInstance("datum", "explicit", {"level": {"op": "create_level", "elev_mm": 0}}),
        ModuleInstance("section", "explicit", {
            "wall": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [6000, 0],
                     "height_mm": 3000, "level": {"by": "ref", "value": output_id(
                         PROJECT, "datum", "level")}}})])


@pytest.fixture
def store(tmp_path):
    return ProjectStore.create(tmp_path / "plan.sqlite", _source(), schema=TASK_STORE_SCHEMA)


class Stub:
    """A number from the assignment -> a program. `lookup` returns an already-given answer."""

    provider_id = "synthetic-test"

    def __init__(self, mode="auto", pause=0.0):
        self.calls, self.mode, self.pause, self._given = 0, mode, pause, {}

    def _text(self, request):
        objective = request.messages[0]["content"]
        if self.mode == "silent":
            return "мне нечего предложить"
        found = re.search(r"(\d{3,4})", objective)
        value = int(found.group(1)) if found else 3500
        # 🔴 THE KIND OF PROGRAM COMES FROM THE ASSIGNMENT, NOT FROM THE PROCESS: which turn
        # this worker gets is decided by the RESERVATION, and a stub tied to the
        # process would answer `create_level` to an assignment about a wall.
        if self.mode == "level" or (self.mode == "auto" and "отметка" in objective):
            return "program={'ops':[{'op':'create_level','id':'level','elev_mm':%d}]}" % value
        return "program={'ops':[{'op':'create_wall','id':'wall','height_mm':%d}]}" % value

    def complete(self, request):
        import time
        self.calls += 1
        if self.pause:
            time.sleep(self.pause)
        response = CompletionResponse(self._text(request),
                                      {"input_tokens": 4, "output_tokens": 12, "calls": 1},
                                      self.provider_id)
        self._given[request_key(request)] = response
        return response

    def lookup(self, request):
        return self._given.get(request_key(request))


def _budget(calls=20):
    return R.TeamBudget(max_calls=calls, max_tokens=200000)


def _two_free_steps():
    return ({"text": "ход A: стена 4400", "worker_id": "worker-a", "instance_key": "wing-a",
             "outputs": ("wall",)},
            {"text": "ход B: стена 4600", "worker_id": "worker-b", "instance_key": "wing-b",
             "outputs": ("wall",)})


# ── (2) turn reservation and honest outcome ──────────────────────────────
def test_two_processes_take_different_free_steps(store, tmp_path):
    """🔴 TWO PROCESSES — TWO DIFFERENT TURNS, NOT ONE TWICE."""
    M.plan(store, "par-1", _two_free_steps())
    script = '''
import json, sys, time
sys.path.insert(0, {root!r})
sys.path.insert(0, {here!r})
from kir.bureau import mission as M, runner as R
from kir.project_store import ProjectStore
from test_two_workers_share_one_plan import Stub
store = ProjectStore.open({path!r}, readonly=False)
provider = Stub(pause=1.2)
t0 = time.time()
record = M.advance(store, "par-1", provider=provider, budget=R.TeamBudget(20, 200000))
print(json.dumps({{"step": record["step"], "state": record["state"], "calls": provider.calls,
                   "t0": t0, "t1": time.time()}}))
'''.format(root=str(ROOT), here=str(Path(__file__).parent), path=str(tmp_path / "plan.sqlite"))
    children = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=CHILD_ENV)
                for _ in range(2)]
    rows = []
    for child in children:
        out, err = child.communicate(timeout=300)
        assert child.returncode == 0, err[-2500:]
        rows.append(json.loads(out.strip().splitlines()[-1]))
    steps = sorted(row["step"] for row in rows)
    assert steps == [0, 1], f"процессы взяли {steps}, а ходов свободных было два"
    assert all(row["state"] == "accepted" for row in rows), rows
    assert all(row["calls"] == 1 for row in rows), rows
    overlap = min(rows[0]["t1"], rows[1]["t1"]) - max(rows[0]["t0"], rows[1]["t0"])
    assert overlap > 0, f"процессы не пересеклись во времени: {overlap:.3f}s"
    assert R.spend(store)["calls"] == 2
    state = M.plan_state(store, "par-1")
    assert [row["state"] for row in state["steps"]] == ["accepted", "accepted"]
    assert state["complete"] is True


def test_one_step_cannot_be_claimed_twice(store):
    """🔴 THE RESERVATION PRIMITIVE ITSELF, NOT ITS LUCKY TIMING OUTCOME.

    The parallel probe above depends on timing: the second process reads the
    state already AFTER the other reservation and honestly takes the neighbouring turn — the ticket
    is not checked at all in that case (measured: the "same number" mutation did not
    turn it red, 4 green out of 4). Here the reservation is checked head-on: a foreign number under
    the same ticket must lose, while ONE'S OWN repeat must stay idempotent,
    otherwise a process that crashed between the reservation and the assignment could not come back.
    """
    M.plan(store, "ticket-1", _two_free_steps())
    head = store.head().revision_id
    assert M._claim(store, "ticket-1", 0, 0, head, nonce="мой") is True
    assert M._claim(store, "ticket-1", 0, 0, head, nonce="мой") is True, "свой повтор не идемпотентен"
    assert M._claim(store, "ticket-1", 0, 0, head, nonce="чужой") is False, "ход взят дважды"
    # A neighbouring turn and the next attempt at the same turn are different tickets.
    assert M._claim(store, "ticket-1", 1, 0, head, nonce="чужой") is True
    assert M._claim(store, "ticket-1", 0, 1, head, nonce="чужой") is True
    state = M.plan_state(store, "ticket-1")
    assert [row["state"] for row in state["steps"]] == ["claimed", "claimed"]
    assert state["next"] is None and state["complete"] is False


def test_a_claimed_step_is_not_taken_twice(store, tmp_path):
    """🔴 A CLAIMED TURN IS NOT TAKEN A SECOND TIME; resuming someone else's — a SEPARATE DOOR.

    The first process dies after the provider's answer is recorded — the turn stays
    claimed. A plain `advance` does NOT pick it up (otherwise a parallel worker
    would do someone else's work), and instead names it `claim_lost`. Resuming it is an explicit
    `resume_claimed=True`, and it costs no call: the answer is already recorded.
    """
    M.plan(store, "claim-1", ({"text": "ход 1: стена 4800", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    script = '''
import os, sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {here!r})
import kir.bureau.attempt as A
from kir.bureau import mission as M, runner as R
from kir.project_store import ProjectStore
from test_two_workers_share_one_plan import Stub
original = A._finish
def finish(store, task, identifier, output):
    result = original(store, task, identifier, output)
    if identifier.startswith("bureau-provider-"):
        os._exit(9)
    return result
A._finish = finish
store = ProjectStore.open({path!r}, readonly=False)
M.advance(store, "claim-1", provider=Stub(), budget=R.TeamBudget(20, 200000))
'''.format(root=str(ROOT), here=str(Path(__file__).parent), path=str(tmp_path / "plan.sqlite"))
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                             env=CHILD_ENV, timeout=300)
    assert crashed.returncode == 9, (crashed.returncode, crashed.stderr[-2000:])
    state = M.plan_state(store, "claim-1")
    assert state["steps"][0]["state"] == "claimed", state
    assert state["complete"] is False

    idle = Stub()
    lost = M.advance(store, "claim-1", provider=idle, budget=_budget())
    assert lost["state"] == "claim_lost", lost
    assert idle.calls == 0 and R.spend(store)["calls"] == 1

    survivor = Stub()
    record = M.advance(store, "claim-1", provider=survivor, budget=_budget(),
                       resume_claimed=True)
    assert record["state"] == "accepted", record
    assert survivor.calls == 0, "подхват взятого хода переспросил модель"
    assert R.spend(store)["calls"] == 1


def test_the_outcome_is_read_from_my_own_task_not_from_the_decisions(store, monkeypatch):
    """🔴 A FOREIGN COORDINATOR ACCEPTED — THE RECORD IS STILL `accepted`.

    `coordinate` takes ALL `submitted` tasks. A neighbouring process accepts my
    proposal, and my `task_id` no longer appears in MY `Decisions`. The outcome
    must be read from the state of ONE'S OWN task, otherwise the journal will say
    `no_change` about a project that was accepted.
    """
    provider = Stub()
    M.plan(store, "steal-1", ({"text": "ход 1: стена 4900", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    real = R.coordinate

    def foreign(*args, **kwargs):
        real(*args, **kwargs)                 # "the neighbouring process" accepted first
        return R.Decisions((), (), ())        # I get an empty answer

    monkeypatch.setattr(M.R, "coordinate", foreign)
    record = M.advance(store, "steal-1", provider=provider, budget=_budget())
    assert record["state"] == "accepted", record
    assert read_task(store, record["task_id"])["state"] == "accepted"
    section = next(item for item in store.head().instances if item.key == "section")
    assert section.outputs[0].operation["height_mm"] == 4900


# ── (1) replanning inside the plan ────────────────────────────────────────
def _conflicting(store, monkeypatch, times=1):
    """Force a turn into conflict: a foreign edit to the same target before acceptance."""
    real, seen = R.coordinate, {"n": 0}

    def wrapper(*args, **kwargs):
        if seen["n"] < times:
            seen["n"] += 1
            head = store.head()
            section = next(item for item in head.instances if item.key == "section")
            store.commit(head.replace_instance(ModuleInstance(
                "section", section.module_key,
                {"wall": {**{k: v for k, v in dict(section.outputs[0].operation).items()},
                          "height_mm": 3300 + seen["n"]}}, dict(section.parameters),
                metadata=dict(section.metadata)), expected_revision=head.revision_id),
                expected_revision=head.revision_id)
        return real(*args, **kwargs)

    monkeypatch.setattr(M.R, "coordinate", wrapper)
    return seen


def test_a_conflicted_step_gets_exactly_one_replan_inside_the_plan(store, monkeypatch):
    """🔴 ONE REPLANNING ATTEMPT, AND THE DEPENDENT IS NOT `blocked` FOREVER."""
    provider = Stub()
    M.plan(store, "conf-1", (
        {"text": "ход 1: стена 5100", "worker_id": "worker-a", "instance_key": "section",
         "outputs": ("wall",)},
        {"text": "ход 2: отметка 800", "worker_id": "worker-b", "instance_key": "datum",
         "outputs": ("level",), "depends_on": (0,)}))
    _conflicting(store, monkeypatch, times=1)
    first = M.advance(store, "conf-1", provider=provider, budget=_budget())
    assert first["state"] == "conflicted", first
    state = M.plan_state(store, "conf-1")
    assert state["steps"][0]["state"] == "replan_due", state["steps"][0]
    assert state["steps"][1]["state"] == "waiting", "зависимый заперт до исчерпания попыток"
    assert state["complete"] is False, "план не готов, пока положена попытка"
    assert state["next"] == 0

    retry = M.advance(store, "conf-1", provider=provider, budget=_budget())
    assert retry["step"] == 0 and retry["state"] == "accepted", retry
    assert retry["replan"] == 1
    task = R._configured_task(store, read_task(store, retry["task_id"]))
    context = json.loads(R._request_for(task, store).to_dict()["messages"][1]["content"]
                         .removeprefix("проект: "))
    conflict = context.get("conflict")
    assert conflict and conflict["issues"], "перепланирование без содержания конфликта"
    assert conflict["current"]["revision_id"] == first["revision_id"]
    assert task["assignment"]["base_revision"] == first["revision_id"], "считали от старой головы"

    last = M.advance(store, "conf-1", provider=Stub(mode="level"), budget=_budget())
    assert last["step"] == 1 and last["state"] == "accepted", last
    assert M.plan_state(store, "conf-1")["complete"] is True


def test_a_second_conflict_stops_by_name_not_by_budget(store, monkeypatch):
    """A second failure is `replan_exhausted`, not a silent continuation."""
    provider, budget = Stub(), _budget(calls=20)
    M.plan(store, "conf-2", ({"text": "ход 1: стена 5200", "worker_id": "worker-a",
                              "instance_key": "section", "outputs": ("wall",)},))
    _conflicting(store, monkeypatch, times=2)
    assert M.advance(store, "conf-2", provider=provider, budget=budget)["state"] == "conflicted"
    with pytest.raises(R.BureauRefusal) as halted:
        M.advance(store, "conf-2", provider=provider, budget=budget)
    assert halted.value.code == "replan_exhausted", halted.value.code
    assert provider.calls == 2, f"вызовов {provider.calls}: продолжали до исчерпания бюджета"
    assert R.stop_reason(store) == "replan_exhausted" and R.is_stopped(store)
    state = M.plan_state(store, "conf-2")
    assert state["steps"][0]["state"] == "conflicted" and state["complete"] is True


# ── (3) limits — plan parameters ─────────────────────────────────────────
def test_limits_belong_to_the_plan_and_defaults_stay_put(store):
    """🔴 ONE PLAN STRICTER THAN ANOTHER. A default is not shifted by someone else's plan."""
    strict = M.plan(store, "lim-1", tuple(
        {"text": f"ход {n}: стена 4{n}00", "worker_id": "worker-a", "instance_key": "section",
         "outputs": ("wall",)} for n in range(1, 6)), limits={"no_progress_turns": 2})
    assert strict["limits"]["no_progress_turns"] == 2
    assert M.limits_of(store, "lim-1")["memory_window"] == M.MEMORY_WINDOW
    provider = Stub(mode="silent")
    assert M.advance(store, "lim-1", provider=provider, budget=_budget())["state"] == "no_change"
    with pytest.raises(R.BureauRefusal) as halted:
        M.advance(store, "lim-1", provider=provider, budget=_budget())
    assert halted.value.code == "no_progress"
    assert provider.calls == 2, "строгий предел плана не применён"
    R.resume(store, reason="проверяем умолчание соседнего плана")
    M.plan(store, "lim-2", tuple(
        {"text": f"ход {n}: стена 4{n}00", "worker_id": "worker-c", "instance_key": "section",
         "outputs": ("wall",)} for n in range(1, 6)))
    assert M.limits_of(store, "lim-2")["no_progress_turns"] == M.NO_PROGRESS_TURNS == 3


def test_a_limit_outside_its_bounds_is_refused_by_name(store):
    steps = ({"text": "ход 1: стена 4100", "worker_id": "worker-a",
              "instance_key": "section", "outputs": ("wall",)},)
    for bad in ({"no_progress_turns": 1}, {"no_progress_turns": 10_000}, {"memory_window": 0},
                {"max_reads_per_step": -1}, {"replan_attempts": True},
                {"memory_window": "8"}, {"неизвестный": 3}):
        with pytest.raises(R.BureauRefusal) as refused:
            M.plan(store, f"bad-{sorted(bad)[0]}-{list(bad.values())[0]}", steps, limits=bad)
        assert refused.value.code == "bad_limit", (bad, refused.value.code)


def test_a_plan_without_limits_stays_compatible(store):
    """A record without `limits` does not turn into a different plan from a single read."""
    steps = ({"text": "ход 1: стена 4100", "worker_id": "worker-a",
              "instance_key": "section", "outputs": ("wall",)},)
    first = M.plan(store, "old-1", steps)
    assert "limits" not in first or first["limits"] == {}
    again = M.plan(store, "old-1", steps)                 # idempotent
    assert again == first
    assert M.limits_of(store, "old-1") == M.DEFAULT_LIMITS
    with pytest.raises(R.BureauRefusal) as changed:
        M.plan(store, "old-1", steps, limits={"no_progress_turns": 2})
    assert changed.value.code == "plan_already_exists"
