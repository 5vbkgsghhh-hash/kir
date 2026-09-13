# -*- coding: utf-8 -*-
"""Mandate F7: a long-running task, delegation, "no progress," a reading tool.

🔴 WHAT EXACTLY IS CHECKED HERE, AND WHY IT WASN'T BEFORE. Recon of the code
on 07.09 showed: the bureau holds ONE turn (`assign` -> `work` ->
`coordinate`), Stop, a team budget, and replanning on conflict. It held
none of the following:

* **memory** — the model's context was built ONLY from the current
  revision (`_project_context`): previously accepted decisions — neither the
  project's `refinement_decisions` nor the bureau's earlier accepted turns —
  went into it. Turn 2 "remembered" turn 1 only to the extent that turn 1
  had managed to change the geometry;
* **a long-running task** — the notion of a turn did not exist at all;
  after a process crash, another process had nothing to continue: it knew
  neither how many turns were planned nor which had already been made;
* **delegation** — `assign` doesn't know about dependencies, `coordinate`
  takes ALL `submitted` ones in a row; there was no way to express "the
  second subtask waits for the first";
* **no progress** — stalling in place was stopped only by an exhausted
  budget, that is, after `max_calls` useless calls;
* **tools** — the model could not ask the bureau to read the project: any
  answer that wasn't a program was called `answer_is_not_a_program`.

The provider here is a deterministic stub, not a paid model: the mechanism
is checked offline, and not one test passes the stub off as a live
responder.
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
PROJECT = "bureau-long"


def _source():
    return ProjectRevision(PROJECT, [ModuleDefinition("explicit")], [
        ModuleInstance("datum", "explicit", {"level": {"op": "create_level", "elev_mm": 0}}),
        ModuleInstance("section", "explicit", {
            "wall": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [6000, 0],
                     "height_mm": 3000, "level": {"by": "ref", "value": output_id(
                         PROJECT, "datum", "level")}}})])


@pytest.fixture
def store(tmp_path):
    return ProjectStore.create(tmp_path / "project.sqlite", _source(), schema=TASK_STORE_SCHEMA)


class Stub:
    """A deterministic "author": a number from the assignment's text -> the same program.

    A stub, not a model: `lookup` returns an answer already given, so
    continuing after a restart cannot secretly ask again.
    """

    provider_id = "synthetic-test"

    def __init__(self, mode="height"):
        self.calls, self.mode, self._given = 0, mode, {}

    def _text(self, request):
        objective = request.messages[0]["content"]
        if self.mode == "silent":
            return "мне нечего предложить"
        if self.mode == "read_first" and "tool_results" not in "".join(
                message["content"] for message in request.messages):
            return json.dumps({"kir_read": ["datum/level", "section"]}, ensure_ascii=False)
        found = re.search(r"(\d{4})", objective)
        height = int(found.group(1)) if found else 3500
        return ("program={'ops':[{'op':'create_wall','id':'wall','height_mm':%d}]}" % height)

    def complete(self, request):
        self.calls += 1
        response = CompletionResponse(self._text(request),
                                      {"input_tokens": 4, "output_tokens": 12, "calls": 1},
                                      self.provider_id)
        self._given[request_key(request)] = response
        return response

    def lookup(self, request):
        return self._given.get(request_key(request))


class LevelStub(Stub):
    """A level worker: writes an elevation, not a wall."""

    def _text(self, request):
        found = re.search(r"(\d{3,5})", request.messages[0]["content"])
        return ("program={'ops':[{'op':'create_level','id':'level','elev_mm':%d}]}"
                % int(found.group(1)))


def _budget(calls=20):
    return R.TeamBudget(max_calls=calls, max_tokens=200000)


def _turns():
    return ({"text": "ход 1: поднять стену до 4100", "worker_id": "worker-a",
             "instance_key": "section", "outputs": ("wall",)},
            {"text": "ход 2: поднять стену до 4600", "worker_id": "worker-a",
             "instance_key": "section", "outputs": ("wall",), "depends_on": (0,)},
            {"text": "ход 3: поднять стену до 5100", "worker_id": "worker-a",
             "instance_key": "section", "outputs": ("wall",), "depends_on": (1,)})


def _context_of(store, task_id):
    task = R._configured_task(store, read_task(store, task_id))
    request = R._request_for(task, store).to_dict()
    return json.loads(request["messages"][1]["content"].removeprefix("проект: "))


# ── (1) long-running task: decision memory and continuation after a crash ──
def test_the_second_turn_reads_the_first_decision_from_saved_state(store):
    """🔴 MEMORY IS A SAVED DECISION, NOT CORRESPONDENCE.

    Turn 2 must name: which revision was accepted by turn 1, by which
    assignment, and which clarification decisions have already been accepted
    in the project. Before, the context knew only current values —
    "what was decided" and "why" were not part of it.
    """
    provider, budget = Stub(), _budget()
    M.plan(store, "long-1", _turns())
    first = M.advance(store, "long-1", provider=provider, budget=budget)
    assert first["state"] == "accepted", first
    # A human's clarification decision lives IN THE PROJECT and must reach the model.
    head = store.head()
    section = next(item for item in head.instances if item.key == "section")
    decision = {"question_id": "q1", "choice": "keep_height", "address": "section/wall",
                "source_output_id": output_id(PROJECT, "datum", "level"),
                "change_kind": "elevation", "requested_mm": [[0, 0], [0, 4600]],
                "applied_mm": [[0, 0], [0, 4100]], "conceded_mm": 500.0}
    store.commit(head.replace_instance(
        ModuleInstance(section.key, section.module_key, {k.key: dict(k.operation) for k in section.outputs},
                       dict(section.parameters),
                       metadata={**dict(section.metadata), "refinement_decisions": [decision]}),
        expected_revision=head.revision_id), expected_revision=head.revision_id)

    second = M.advance(store, "long-1", provider=provider, budget=budget)
    context = _context_of(store, second["task_id"])
    memory = context.get("memory")
    assert memory, "F7: ход 2 обязан получить сохранённую память, а не только текущие значения"
    turns = memory.get("accepted_turns") or ()
    assert [row["revision_id"] for row in turns] == [first["revision_id"]], turns
    assert turns[0]["objective"] == _turns()[0]["text"]
    assert memory["refinement_decisions"] == [decision], memory["refinement_decisions"]
    assert second["state"] == "accepted"


def test_a_crash_between_turns_resumes_at_the_third_without_reasking(store, tmp_path):
    """🔴 THE OTHER PROCESS CONTINUES FROM TURN 3, NOT FROM THE START.

    Turns 1 and 2 are an accomplished fact of the journal. The second
    process must make EXACTLY one provider call (turn 3) and must not
    re-ask on behalf of turn 2.
    """
    provider, budget = Stub(), _budget()
    M.plan(store, "long-2", _turns())
    M.advance(store, "long-2", provider=provider, budget=budget)
    M.advance(store, "long-2", provider=provider, budget=budget)
    assert provider.calls == 2
    before = R.spend(store)["calls"]

    script = f'''
import json, re, sys
sys.path.insert(0, {str(ROOT)!r})
from kir.bureau import mission as M, runner as R
from kir.bureau.provider import CompletionResponse, request_key
from kir.project_store import ProjectStore
sys.path.insert(0, {str(Path(__file__).parent)!r})
from test_a_long_task_continues_from_its_memory import Stub
store = ProjectStore.open({str(tmp_path / "project.sqlite")!r}, readonly=False)
provider = Stub()
state = M.plan_state(store, "long-2")
record = M.advance(store, "long-2", provider=provider, budget=R.TeamBudget(20, 200000))
print(json.dumps({{"done_before": [row["state"] for row in state["steps"]],
                  "next_before": state["next"], "record": record,
                  "calls": provider.calls, "spend": R.spend(store)["calls"],
                  "complete": M.plan_state(store, "long-2")["complete"]}}))
'''
    child = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=CHILD_ENV, timeout=300)
    assert child.returncode == 0, child.stderr[-3000:]
    result = json.loads(child.stdout.strip().splitlines()[-1])
    assert result["done_before"][:2] == ["accepted", "accepted"], result
    assert result["next_before"] == 2, "продолжать надо С ХОДА 3, а не с начала"
    assert result["calls"] == 1, f"ход 2 переспрошен: {result['calls']} вызовов вместо одного"
    assert result["spend"] == before + 1
    assert result["record"]["step"] == 2 and result["record"]["state"] == "accepted"
    assert result["complete"] is True


# ── (2) delegation: two subtasks, an explicit dependency, merging ──────────
def test_a_delegated_pair_waits_for_the_first_result(store):
    """🔴 THE SECOND SUBTASK STARTS FROM THE HEAD AFTER THE FIRST.

    An explicit dependency is not the order of calls in the test: until the
    first is accepted, the second has neither an assignment nor a provider
    call, and once it does, its `base_revision` equals the head AFTER the
    first was accepted.
    """
    level, wall = LevelStub(), Stub()
    budget = _budget()
    M.plan(store, "split-1", (
        {"text": "подзадача A: отметка уровня 600", "worker_id": "worker-a",
         "instance_key": "datum", "outputs": ("level",)},
        {"text": "подзадача B: стена 4400 от нового уровня", "worker_id": "worker-b",
         "instance_key": "section", "outputs": ("wall",), "depends_on": (0,)}))
    state = M.plan_state(store, "split-1")
    assert [row["state"] for row in state["steps"]] == ["ready", "waiting"], state
    assert state["steps"][1]["task_id"] is None, "зависимая подзадача не заводится заранее"

    base = store.head().revision_id
    first = M.advance(store, "split-1", provider=level, budget=budget)
    assert first["step"] == 0 and first["state"] == "accepted"
    assert wall.calls == 0, "второй работник не вызывался, пока первый не принят"

    second = M.advance(store, "split-1", provider=wall, budget=budget)
    assert second["step"] == 1 and second["state"] == "accepted", second
    assigned = read_task(store, second["task_id"])["assignment"]["base_revision"]
    assert assigned == first["revision_id"], "зависимая подзадача считает от старой головы"
    assert assigned != base
    # The result is merged: BOTH changes are in the head, neither is lost.
    head = store.head()
    datum = next(item for item in head.instances if item.key == "datum")
    section = next(item for item in head.instances if item.key == "section")
    assert datum.outputs[0].operation["elev_mm"] == 600
    assert section.outputs[0].operation["height_mm"] == 4400
    assert M.plan_state(store, "split-1")["complete"] is True


# ── (3) "no progress": a named stop instead of an exhausted budget ─────────
def test_three_turns_without_a_change_stop_by_name(store):
    """🔴 STALLING IS STOPPED ON THE THIRD TURN, NOT ON THE TWENTIETH CALL."""
    provider, budget = Stub(mode="silent"), _budget(calls=20)
    steps = tuple({"text": f"ход {n}: поднять стену до 4{n}00", "worker_id": "worker-a",
                   "instance_key": "section", "outputs": ("wall",)} for n in range(1, 6))
    M.plan(store, "stuck-1", steps)
    head = store.head().revision_id
    for _ in range(2):
        record = M.advance(store, "stuck-1", provider=provider, budget=budget)
        assert record["state"] == "no_change", record
    with pytest.raises(R.BureauRefusal) as halted:
        M.advance(store, "stuck-1", provider=provider, budget=budget)
    assert halted.value.code == "no_progress", halted.value.code
    assert provider.calls == 3, f"вызовов {provider.calls}: продолжали до исчерпания бюджета"
    assert R.spend(store)["calls"] == 3 and budget.max_calls == 20
    assert store.head().revision_id == head
    assert R.is_stopped(store) and R.stop_reason(store) == "no_progress"
    # A named stop does NOT lift itself: the next turn refuses under the same name.
    with pytest.raises(R.BureauRefusal) as again:
        M.advance(store, "stuck-1", provider=provider, budget=budget)
    assert again.value.code in ("no_progress", "team_stopped")
    assert provider.calls == 3


def test_a_user_stop_in_the_middle_stays_a_user_stop(store):
    """A human's Stop in the middle of a long-running task is not renamed by the detector."""
    provider, budget = Stub(mode="silent"), _budget(calls=20)
    steps = tuple({"text": f"ход {n}: поднять стену до 4{n}00", "worker_id": "worker-a",
                   "instance_key": "section", "outputs": ("wall",)} for n in range(1, 6))
    M.plan(store, "stuck-2", steps)
    M.advance(store, "stuck-2", provider=provider, budget=budget)
    M.advance(store, "stuck-2", provider=provider, budget=budget)
    R.stop(store)
    with pytest.raises(R.BureauRefusal) as stopped:
        M.advance(store, "stuck-2", provider=provider, budget=budget)
    assert stopped.value.code == "team_stopped"
    assert R.stop_reason(store) == "user", "Stop пользователя переименован детектором"
    assert provider.calls == 2, "остановленная команда всё равно спросила модель"
    R.resume(store, reason="владелец разобрался")
    assert R.stop_reason(store) is None and not R.is_stopped(store)


# ── (4) tool: reading the project does not spend the provider call budget ──
def test_a_model_read_request_is_served_without_spending_a_call(store):
    """🔴 READING IS A SEPARATE BUREAU STEP, NOT A PROVIDER CALL.

    The model asks for addresses — the bureau answers with values in the
    NEXT context. The answer to the request itself costs not a single call
    and does not break the budget.
    """
    provider, budget = Stub(mode="read_first"), _budget()
    M.plan(store, "tools-1", ({"text": "ход 1: поднять стену до 4700", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    record = M.advance(store, "tools-1", provider=provider, budget=budget)
    assert record["state"] == "accepted", record
    assert record["reads"] == 1, "просьба прочитать проект не была обслужена"
    # Two answers from the model — two calls. Reading did NOT add to them.
    assert provider.calls == 2 and R.spend(store)["calls"] == 2
    served = M.reads(store, "tools-1")
    assert [row["address"] for row in served[0]["values"]] == ["datum/level", "section"]
    context = _context_of(store, record["task_id"])
    read = context.get("tool_results")
    assert read, "прочитанное не доехало до следующего контекста"
    values = {row["address"]: row for row in read[0]["values"]}
    assert values["datum/level"]["operation"]["op"] == "create_level"
    assert values["datum/level"]["output_id"] == output_id(PROJECT, "datum", "level")
    assert values["section"]["outputs"][0]["key"] == "wall"
    assert store.head().instances[1].outputs[0].operation["height_mm"] == 4700


def test_an_unknown_read_address_is_named_not_guessed(store):
    """An unknown address is named by a refusal, not by a silent void."""
    M.plan(store, "tools-2", ({"text": "ход 1: стена 4300", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    task_id = R.assign(store, "проба чтения", worker_id="worker-a",
                       base_revision=store.head().revision_id, instance_key="section")
    task = R._configured_task(store, read_task(store, task_id))
    served = R.serve_read(store, task, ["datum/level", "нет-такого", "section/нет"])
    rows = {row["address"]: row for row in served["values"]}
    assert rows["datum/level"].get("operation")
    assert rows["нет-такого"]["error"] == "unknown_address"
    assert rows["section/нет"]["error"] == "unknown_address"
    assert R.spend(store)["calls"] == 0, "чтение потратило вызов провайдера"


# ══ SELF-REVIEW AS A STRANGER (07.09, after the first submission) ═════════
class SameAnswerStub(Stub):
    """A model that rewrites the SAME value over and over."""

    def _text(self, request):
        return "program={'ops':[{'op':'create_wall','id':'wall','height_mm':4000}]}"


class AlwaysReadStub(Stub):
    """A model that asks to read, and asks again."""

    def _text(self, request):
        return json.dumps({"kir_read": ["datum/level"]}, ensure_ascii=False)


def test_turns_accepted_but_the_head_never_moves_are_not_progress(store):
    """🔴 PROGRESS IS MOVEMENT OF THE HEAD, NOT THE SUCCESS OF A TURN (decided 07.09).

    A turn can be accepted and still not change the project by A SINGLE
    BYTE: the model rewrote the same value, the merge accepted it, the
    revision's sha stayed the same. Counting such a turn as progress would
    mean allowing calls to be spent forever on a motionless project — exactly
    what mandate F7 forbids. So the detector looks at the HEAD, not at the
    word `accepted`.
    """
    provider, budget = SameAnswerStub(), _budget(calls=20)
    steps = tuple({"text": f"ход {n}: та же стена", "worker_id": "worker-a",
                   "instance_key": "section", "outputs": ("wall",)} for n in range(1, 7))
    M.plan(store, "same-1", steps)
    first = M.advance(store, "same-1", provider=provider, budget=budget)
    assert first["state"] == "accepted" and first["revision_id"] != first["head_before"]
    moved = first["revision_id"]
    states = []
    for _ in range(2):
        record = M.advance(store, "same-1", provider=provider, budget=budget)
        states.append(record["state"])
        # 🔴 A SELF-REVIEW FINDING: the head CHANGED sha (the bureau stamps
        # its own metadata), while the design intent did not move a single
        # byte. A detector built on the revision would be blind exactly
        # here.
        assert record["revision_id"] != record["head_before"], record
        assert record["authored_after"] == record["authored_before"], record
    with pytest.raises(R.BureauRefusal) as halted:
        M.advance(store, "same-1", provider=provider, budget=budget)
    assert halted.value.code == "no_progress", (halted.value.code, states)
    assert provider.calls == 4, f"вызовов {provider.calls}: топтание не остановлено"
    assert store.head().instances[1].outputs[0].operation["height_mm"] == 4000
    assert R.stop_reason(store) == "no_progress"
    assert moved != store.head().revision_id


def test_a_third_read_request_is_refused_by_name(store):
    """A third request in a row — a NAMED refusal, not silent ignoring."""
    provider, budget = AlwaysReadStub(), _budget()
    M.plan(store, "reads-1", ({"text": "ход 1: стена 4200", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    record = M.advance(store, "reads-1", provider=provider, budget=budget)
    assert record["state"] == "no_change"
    assert record["refusal"]["code"] == "read_budget_exhausted", record["refusal"]
    assert record["refusal"]["reads"] == M.MAX_READS_PER_STEP == 2
    assert record["reads"] == 2
    # A third ANSWER was never asked for: the limit cuts the call, it doesn't hide the request.
    assert provider.calls == 2 and R.spend(store)["calls"] == 2
    assert len(M.reads(store, "reads-1")) == 2


def test_a_read_never_leaks_secrets_or_another_project(tmp_path):
    """Reading returns the values of THIS project and says nothing about secrets."""
    source = ProjectRevision(PROJECT, [ModuleDefinition("explicit")], [
        ModuleInstance("datum", "explicit", {"level": {"op": "create_level", "elev_mm": 0}},
                       {"client_secret": "s3cr3t-НЕ-ПОКАЗЫВАТЬ", "grid_mm": 6000})])
    store = ProjectStore.create(tmp_path / "p.sqlite", source, schema=TASK_STORE_SCHEMA)
    task_id = R.assign(store, "проба", worker_id="worker-a",
                       base_revision=store.head().revision_id, instance_key="datum")
    task = R._configured_task(store, read_task(store, task_id))
    served = R.serve_read(store, task, [
        "datum", "../datum", "other-project/datum", output_id("other-proj", "datum", "level")])
    rows = {row["address"]: row for row in served["values"]}
    assert rows["datum"]["parameters"]["client_secret"] == "<redacted>"
    assert rows["datum"]["parameters"]["grid_mm"] == 6000
    assert "s3cr3t" not in json.dumps(served, ensure_ascii=False)
    for address in ("../datum", "other-project/datum", output_id("other-proj", "datum", "level")):
        assert rows[address]["error"] == "unknown_address", address


def test_memory_of_fifty_turns_stays_a_window_not_a_transcript(tmp_path):
    """🔴 MEMORY IS A WINDOW WITH A SUMMARY, NOT A GROWING TRANSCRIPT.

    Fifty accepted turns have no right to bloat the context: `assign` would
    receive ever more bytes, and `context_budget_exceeded` would fire for a
    target with two dozen outputs — meaning the long-running task would kill
    itself all the more successfully the longer it ran.
    """
    outputs = {"level": {"op": "create_level", "elev_mm": 0}}
    outputs.update({f"w{n}": {"op": "create_wall", "p0_mm": [0, n + 1], "p1_mm": [9000, n + 1],
                              "height_mm": 3000, "level": {"by": "ref", "value": output_id(
                                  PROJECT, "wide", "level")}} for n in range(20)})
    store = ProjectStore.create(tmp_path / "wide.sqlite", ProjectRevision(
        PROJECT, [ModuleDefinition("explicit")],
        [ModuleInstance("wide", "explicit", outputs)]), schema=TASK_STORE_SCHEMA)
    steps = tuple({"text": f"ход {n}: стена {4000 + n}", "worker_id": "worker-a",
                   "instance_key": "wide", "outputs": ("w0",)} for n in range(50))
    M.plan(store, "long-50", steps)
    for index in range(49):
        R._note(store, {M._STEP: {"plan_id": "long-50", "step": index, "state": "accepted",
                                  "task_id": f"t{index:04d}" * 4, "proposal_id": f"p{index:04d}" * 4,
                                  "revision_id": f"{index:064d}", "head_before": f"{index - 1:064d}",
                                  "reads": 0}})
    memory = M._memory(store, "long-50", 49)
    assert len(memory) <= M.MEMORY_WINDOW <= 12, len(memory)
    summary = next(row for row in memory if row.get("summary"))
    assert summary["accepted_total"] == 49 and summary["shown"] == M.MEMORY_WINDOW - 1
    assert summary["omitted"] == 49 - summary["shown"]
    assert memory[-1]["step"] == 48, "последний принятый ход обязан быть в окне"

    task_id = R.assign(store, "ход 50: стена 4050", worker_id="worker-a",
                       base_revision=store.head().revision_id, instance_key="wide",
                       memory=memory)
    encoded = R._project_context(store, R._configured_task(store, read_task(store, task_id)))
    context = json.loads(encoded)
    assert len(context["target_instance"]["outputs"]) == 21
    assert len(encoded.encode()) < 32 * 1024, len(encoded.encode())


def test_a_crash_inside_one_turn_does_not_buy_a_second_call(store, tmp_path):
    """🔴 A CRASH MID-TURN: the provider's answer is ALREADY recorded — there is nothing to ask again.

    The first process dies EXACTLY after the durable attempt has saved the
    answer, and before the turn is written. The second must finish the same
    turn without spending a single call: a reservation is not permission to
    ask again.
    """
    M.plan(store, "crash-1", ({"text": "ход 1: поднять стену до 4800", "worker_id": "worker-a",
                               "instance_key": "section", "outputs": ("wall",)},))
    script = f'''
import os, sys
sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(Path(__file__).parent)!r})
import kir.bureau.attempt as A
from kir.bureau import mission as M, runner as R
from kir.project_store import ProjectStore
from test_a_long_task_continues_from_its_memory import Stub
original = A._finish
def finish(store, task, identifier, output):
    result = original(store, task, identifier, output)
    if identifier.startswith("bureau-provider-"):
        os._exit(9)                      # крах РОВНО после записи ответа провайдера
    return result
A._finish = finish
store = ProjectStore.open({str(tmp_path / "project.sqlite")!r}, readonly=False)
M.advance(store, "crash-1", provider=Stub(), budget=R.TeamBudget(20, 200000))
'''
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                             env=CHILD_ENV, timeout=300)
    assert crashed.returncode == 9, (crashed.returncode, crashed.stderr[-2000:])
    spent = R.spend(store)
    assert spent["calls"] == 1, spent
    state = M.plan_state(store, "crash-1")
    # 🔴 THE TURN IS TAKEN, NOT FREE (fix 07.09 about booking): picking up
    # someone else's unfinished turn is a separate decision, otherwise a
    # parallel worker would silently do its neighbor's work.
    assert state["steps"][0]["state"] == "claimed", state
    assert state["steps"][0]["task_id"], "заведённое поручение обязано быть видно другому процессу"
    assert M.advance(store, "crash-1", provider=Stub(), budget=_budget())["state"] == "claim_lost"

    survivor = Stub()
    record = M.advance(store, "crash-1", provider=survivor, budget=_budget(),
                       resume_claimed=True)
    assert record["state"] == "accepted", record
    assert survivor.calls == 0, f"второй процесс переспросил модель {survivor.calls} раз"
    assert R.spend(store)["calls"] == 1, "один ход — один вызов, даже через крах"
    assert store.head().instances[1].outputs[0].operation["height_mm"] == 4800


# ══ LIVE RUN run-4: item (b) turned into NO — analysis ═════════════════════
def test_a_patch_may_point_at_an_output_it_did_not_rewrite(tmp_path):
    """🔴 ANALYSIS OF run-4, ITEM (b). The responder referenced an output it did not change.

    The file `responses/fe749819b898….json` (assignment "Tower B: change the
    earlier decision — a 7200 mm wall") sent ONE op — a patch to wall `BW`
    with `level: {'by':'ref','value':'B0'}`. `B0` is an existing output of
    the same target, its address is printed in the context, but in THIS
    answer it is not being rewritten. The reference rewriter only looked at
    the `id` of the RESPONSE (`local_ids`), so the address was never
    substituted, the reference stayed the name `B0`, the design intent
    stopped assembling — and "the next assignment changes the earlier
    decision" turned into NO on a perfectly legitimate answer.

    The bureau knows this address: the `id` in the response IS THE OUTPUT
    KEY, and the bureau has the target's keys. The refusal was not a
    safeguard, it was an inability to substitute its own.
    """
    project = "bureau-ref"
    source = ProjectRevision(project, [ModuleDefinition("explicit")], [
        ModuleInstance("tower", "explicit", {
            "B0": {"op": "create_level", "elev_mm": 600},
            "BW": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                   "level": {"by": "ref", "value": output_id(project, "tower", "B0")}}})])
    store = ProjectStore.create(tmp_path / "ref.sqlite", source, schema=TASK_STORE_SCHEMA)

    class Live:
        """The exact text that came from the live responder in run-4."""

        provider_id = "claude-code-agent"

        def __init__(self):
            self.calls, self._given = 0, {}

        def complete(self, request):
            self.calls += 1
            text = ("program = {'ir_version': '1.0', 'intent': 'bureau: стена 7200', 'ops': [\n"
                    "    {'op': 'create_wall', 'id': 'BW', 'p0_mm': [0, 0], 'p1_mm': [7200, 0],\n"
                    "     'height_mm': 3000, 'level': {'by': 'ref', 'value': 'B0'}},\n"
                    "]}\n")
            response = CompletionResponse(text, {"input_tokens": 703, "output_tokens": 110,
                                                 "calls": 1}, self.provider_id)
            self._given[request_key(request)] = response
            return response

        def lookup(self, request):
            return self._given.get(request_key(request))

    provider = Live()
    task_id = R.assign(store, "Башня B: изменить прежнее решение — стена 7200 мм",
                       worker_id="worker-b", base_revision=store.head().revision_id,
                       instance_key="tower")
    result = R.work(store, task_id, provider=provider, budget=_budget())
    assert result.refusal is None, f"живой ответ отвергнут: {result.refusal}"
    assert result.proposal_id
    decisions = R.coordinate(store)
    assert task_id in decisions.accepted, decisions.to_dict()
    tower = next(item for item in store.head().instances if item.key == "tower")
    wall = next(item for item in tower.outputs if item.key == "BW")
    assert list(wall.operation["p1_mm"]) == [7200, 0], wall.operation["p1_mm"]
    # The reference is substituted by ADDRESS, not left as a local name.
    assert wall.operation["level"]["value"] == output_id(project, "tower", "B0")
    assert provider.calls == 1
