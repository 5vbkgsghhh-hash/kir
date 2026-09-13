# -*- coding: utf-8 -*-
"""A RECIPE RESUMES FROM A SAVED STEP, NOT FROM THE START.

🔴 THE NUMBER THAT SET UP THIS FILE (07.09.2026). `evaluate_task_recipe`
could handle EXACTLY ONE step: stopping mid-computation left a reservation
that no one could carry forward, and not a single run had a continuation.
The registry called this "Partial: persisted Python recipe step" (P05) and
"continuing computations not yet accepted." Here a PLAN is set up: an
ordering of steps whose identity pins down the seed, the inputs, and the
dependency on the previous step, and whose `result_digest` IS THE SAME FOR
AN INTERRUPTED RUN AND AN UNINTERRUPTED ONE.

The second number (the same shift): a recipe over a 2000-instance project
was paying **5.0 full model decompiles and 7.2 full traversals PER
ELEMENT** — the count did not grow with N, but EVERY decompile cost the
whole model, and the time per element grew from 0.25 s (N=250) to 1.51 s
(N=2000). This is exactly "a long-running operation re-reads the whole
model for every element." The fix does not weaken the check: a decompile
is handed out from the handle's guarantee ONLY when the ENTIRE revision
row matches (number, identity, project, parent, and bytes), and the
reference set only when the `revision_id` of an already byte-verified
payload matches.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
import subprocess
import sys
import time

import pytest

from kir import sdk
from kir import task_recipe_runner as runner
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision
from kir.project_merge import ProposalScope
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.project_tasks import (TaskError, abandon_task_tool, create_task, read_task,
                               task_history)
import kir.project_store as storage


POLICY = replace(runner.RECIPE_POLICY, probe_network=False)
KEYS = ("a", "b", "c")


def base_project():
    return ProjectRevision("plan-project", [ModuleDefinition("explicit")], [
        ModuleInstance(key, "explicit", {"level": sdk.create_level(elev_mm=i * 3000., name=key)},
                       metadata={"decision": "preserve-" + key})
        for i, key in enumerate(KEYS)], metadata={"units": "mm"})


def source_for(base):
    return "\n".join([
        "p = param('project_id', 'missing')", "i = param('instance_key', 'missing')",
        "h = param('height_mm', 0.0)", "d = param('depends_on', 'unpinned')",
        "program = " + repr({"ir_version": base.ir_version, "intent": base.intent}),
        "program['ops'] = [{'op':'create_level','id':project_output_id(p,i,'level'),"
        "'elev_mm':h,'name':'plan ' + i + ' after ' + d[:8]}]",
    ])


def plan_for(base, *, seed="seed-0007"):
    text = source_for(base)
    return runner.recipe_plan([
        {"instance_key": key, "module_key": "recipe-" + key, "output_keys": ("level",),
         "source": text, "parameters": {"height_mm": 500. + 100 * index, "depends_on": ""}}
        for index, key in enumerate(KEYS)], seed=seed)


def case(tmp_path, name, *, calls=8):
    base = base_project()
    store = ProjectStore.create(tmp_path / name, base, schema=TASK_STORE_SCHEMA)
    create_task(store, task_id="t", base_revision=base.revision_id, actor="w",
        objective="Evaluate an ordered recipe plan", tools=("author.python",),
        budgets={"max_tool_calls": calls},
        scope=ProposalScope(instances=KEYS, modules=tuple("recipe-" + k for k in KEYS),
                            project_fields=("module_order",)))
    return store, base


CHILD = """
import json, os, sys
from dataclasses import replace
from kir.project_store import ProjectStore
from kir import task_recipe_runner as r

store = ProjectStore.open(sys.argv[1], readonly=False)
plan = json.loads(sys.argv[2])
seen = {"finish": 0}
crash = os.environ.get("KIR_PLAN_CRASH_AT")
if crash:
    index, where = crash.split(":")
    index, original = int(index), r.finish_task_tool

    def hooked(*args, **kwargs):
        if seen["finish"] == index and where == "before_ack":
            # Python отработал, результат ЕЩЁ НЕ записан.
            assert kwargs["output"]["proposal"] is not None, kwargs["output"]
            print("computed_step_%d" % index, flush=True)
            os._exit(77)
        answer = original(*args, **kwargs)
        if seen["finish"] == index and where == "after_ack":
            # Результат ЗАПИСАН, подтверждение до вызывающего не доехало.
            print("acked_step_%d" % index, flush=True)
            os._exit(78)
        seen["finish"] += 1
        return answer

    r.finish_task_tool = hooked
budget = os.environ.get("KIR_PLAN_MAX_STEPS")
run = r.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w", generation=0,
    policy=replace(r.RECIPE_POLICY, probe_network=False),
    max_steps=None if budget is None else int(budget))
tight = dict(separators=(",", ":"), sort_keys=True)
print("RESULT " + json.dumps(run["result"], **tight), flush=True)
print("REPORT " + json.dumps({"delivery": run["delivery"], "invoked": run["invoked"],
    "attempted": run["attempted"], "stopped": run["stopped"],
    "complete": run["complete"]}, **tight), flush=True)
"""


def other_process(store, plan, **environment):
    done = subprocess.run([sys.executable, "-c", CHILD, str(store.path), json.dumps(plan)],
        capture_output=True, text=True, timeout=180,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **environment))
    lines = {l.split(" ", 1)[0]: l.split(" ", 1)[1] for l in done.stdout.splitlines()
             if l.startswith(("RESULT ", "REPORT "))}
    if "RESULT" not in lines:
        return done, None, None
    return done, json.loads(lines["RESULT"]), json.loads(lines["REPORT"])


def whole(store, plan, *, monkeypatch=None):
    return runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
                                            generation=0, policy=POLICY)


# ─────────────────────────── 1. stopping and resuming ─────────────────────────

def test_a_run_budget_stops_at_a_step_boundary_and_another_process_finishes_it(tmp_path):
    """An exhausted run budget: two processes give THE SAME signature as one."""
    reference, base = case(tmp_path, "reference.sqlite")
    plan = plan_for(base)
    continuous = whole(reference, plan)
    assert continuous["complete"] and continuous["invoked"] == 3, continuous

    store, _ = case(tmp_path, "stopped.sqlite")
    first = runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
                                             generation=0, policy=POLICY, max_steps=1)
    assert first["stopped"] == "run_step_budget_exhausted" and first["invoked"] == 1
    assert first["result"]["completed"] == 1 and not first["complete"]

    _, result, report = other_process(store, plan)
    assert report is not None and report["complete"], report
    assert report["invoked"] == 2, report
    assert [d["delivered"] for d in report["delivery"]] == [
        "already_delivered", "evaluated", "evaluated"]
    # The content is byte-for-byte the same as an uninterrupted run's.
    assert result["content_digest"] == continuous["result"]["content_digest"]
    assert [s["program_sha256"] for s in result["steps"]] == [
        s["program_sha256"] for s in continuous["result"]["steps"]]
    assert len([e for e in task_history(store, "t") if e["kind"] == "tool_begin"]) == 3
    # The JOURNAL's identity is reproduced byte-for-byte by a third process.
    _, again, report3 = other_process(store, plan)
    assert again == result and report3["invoked"] == 0
    assert [d["delivered"] for d in report3["delivery"]] == ["already_delivered"] * 3


def test_a_crash_between_result_and_acknowledgement_restores_from_the_journal(tmp_path):
    """Recorded but not confirmed: the resume takes the step FROM THE JOURNAL, not from memory."""
    reference, base = case(tmp_path, "reference.sqlite")
    plan = plan_for(base)
    continuous = whole(reference, plan)

    store, _ = case(tmp_path, "crashed.sqlite")
    done, _, _ = other_process(store, plan, KIR_PLAN_CRASH_AT="1:after_ack")
    assert done.returncode == 78, done.stderr
    assert "acked_step_1" in done.stdout
    task = read_task(store, "t")
    assert task["pending_tool"] is None and len(task["tool_calls"]) == 2
    assert [c["state"] for c in task["tool_calls"]] == ["recorded", "recorded"]

    calls = {"n": 0}
    real = runner.execute_author_script

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    runner.execute_author_script = counted
    try:
        resumed = whole(store, plan)
    finally:
        runner.execute_author_script = real
    assert calls["n"] == 1, "продолжение пересчитало уже записанные шаги"
    assert resumed["complete"]
    assert resumed["result"]["content_digest"] == continuous["result"]["content_digest"]
    # The recorded steps are taken FROM THE JOURNAL byte-for-byte, not recomputed.
    _, again, _ = other_process(store, plan)
    assert again == resumed["result"]
    assert [d["delivered"] for d in resumed["delivery"]] == [
        "already_delivered", "already_delivered", "evaluated"]


def test_a_crash_inside_a_step_never_reinvokes_and_needs_an_explicit_abandon(tmp_path):
    """A crash IN THE MIDDLE of a step: the outcome is unknown, the step does not repeat itself on its own."""
    reference, base = case(tmp_path, "reference.sqlite")
    plan = plan_for(base)
    continuous = whole(reference, plan)

    store, _ = case(tmp_path, "mid.sqlite")
    done, _, _ = other_process(store, plan, KIR_PLAN_CRASH_AT="1:before_ack")
    assert done.returncode == 77, done.stderr
    assert "computed_step_1" in done.stdout
    assert read_task(store, "t")["pending_tool"] == runner._step_request_id(plan, 1, 1)

    original = runner.execute_author_script
    runner.execute_author_script = lambda *a, **k: pytest.fail("неразрешённая бронь позвала Python")
    try:
        blocked = runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
                                                   generation=0, policy=POLICY)
    finally:
        runner.execute_author_script = original
    assert blocked["stopped"] == "step_outcome_unresolved" and blocked["invoked"] == 0
    assert blocked["result"]["completed"] == 1

    task = read_task(store, "t")
    abandon_task_tool(store, "t", request_id="drop-1", expected_version=task["version"],
        generation=0, actor="coordinator", tool_request_id=task["pending_tool"],
        reason="worker process died with an unknown Python outcome")
    resumed = whole(store, plan)
    assert resumed["complete"]
    assert resumed["result"]["content_digest"] == continuous["result"]["content_digest"]
    assert [d["attempt"] for d in resumed["delivery"]] == [1, 2, 1]
    assert [d["delivered"] for d in resumed["delivery"]] == [
        "already_delivered", "evaluated", "evaluated"]


# ─────────────────────── 2. repeated delivery to two processes ────────────────

def test_two_processes_delivering_the_same_step_leave_exactly_one_effect(tmp_path):
    """at-least-once: the second deliverer receives the NAME "already delivered", not the effect."""
    store, base = case(tmp_path, "twice.sqlite")
    plan = plan_for(base)
    stale = read_task(store, "t")
    _, result, report = other_process(store, plan, KIR_PLAN_MAX_STEPS="1")
    assert report["invoked"] == 1 and report["stopped"] == "run_step_budget_exhausted"
    before = task_history(store, "t")

    original = runner.execute_author_script
    runner.execute_author_script = lambda *a, **k: pytest.fail("повтор доставки позвал Python")
    try:
        # The same task snapshot that the first process had BEFORE its step.
        replayed = runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
            generation=0, policy=POLICY, max_steps=1, task=stale)
    finally:
        runner.execute_author_script = original
    assert replayed["delivery"] == [{"index": 0, "attempt": 1,
                                     "delivered": "already_delivered_on_replay"}]
    assert replayed["invoked"] == 0 and replayed["result"]["steps"] == result["steps"]
    assert task_history(store, "t") == before
    assert len(read_task(store, "t")["tool_calls"]) == 1


def test_a_plan_step_pins_seed_inputs_and_the_previous_step(tmp_path):
    """seed/inputs/dependency live IN THE STEP ITSELF, not in the process's memory."""
    store, base = case(tmp_path, "pinned.sqlite")
    plan = plan_for(base)
    other = plan_for(base, seed="seed-0008")
    assert plan["plan_digest"] != other["plan_digest"]
    assert runner._step_request_id(plan, 0, 1) != runner._step_request_id(other, 0, 1)

    run = whole(store, plan)
    assert run["complete"]
    arguments = {c["request_id"]: c["arguments"] for c in run["task"]["tool_calls"]}
    first = arguments[runner._step_request_id(plan, 0, 1)]
    second = arguments[runner._step_request_id(plan, 1, 1)]
    assert first["pins"] == {"recipe_seed": "seed-0007", "plan_digest": plan["plan_digest"],
                             "step_index": 0, "depends_on": ""}
    assert second["pins"]["depends_on"] == runner._hash(
        runner._step_content(run["result"]["steps"][0]))
    assert second["pins"]["step_index"] == 1
    # Only the name DECLARED by the step reaches the script; it did not declare seed.
    assert second["parameters"]["depends_on"] == second["pins"]["depends_on"]
    assert "recipe_seed" not in second["parameters"]

    # The same step address with A DIFFERENT input is not "the same delivered" — it's a refusal.
    with pytest.raises(TaskError, match="request ID reused"):
        runner.evaluate_task_recipe(store, "t", source=source_for(base), instance_key="a",
            module_key="recipe-a", output_keys=("level",),
            request_id=runner._step_request_id(plan, 0, 1),
            expected_version=read_task(store, "t")["version"], generation=0, actor="w",
            parameters={"height_mm": 500., "depends_on": ""},
            pins={**first["pins"], "recipe_seed": "forged"}, policy=POLICY)


# ───────────────────── 3. model reads per element: O(1), not O(N) ─────────────

class _Reads:
    """Full model parses/traversals and asset reads. A counter, not a verdict."""

    def __enter__(self):
        self.loads = self.walks = self.assets = 0
        counter = self
        self.parse = ProjectRevision.loads.__func__
        self.walk = ProjectRevision.addressed_outputs
        self.read = storage._read_asset

        def loads(cls, payload):
            counter.loads += 1
            return counter.parse(cls, payload)

        def outputs(revision):
            counter.walks += 1
            return counter.walk(revision)

        def asset(*args, **kwargs):
            counter.assets += 1
            return counter.read(*args, **kwargs)

        ProjectRevision.loads = classmethod(loads)
        ProjectRevision.addressed_outputs = outputs
        storage._read_asset = asset
        return self

    def __exit__(self, *error):
        ProjectRevision.loads = classmethod(self.parse)
        ProjectRevision.addressed_outputs = self.walk
        storage._read_asset = self.read


def _wide(tmp_path, count):
    return ProjectRevision("wide", [ModuleDefinition("explicit")], [
        ModuleInstance("i%05d" % index, "explicit",
                       {"level": sdk.create_level(elev_mm=float(index * 100), name="i%05d" % index)})
        for index in range(count)], metadata={"units": "mm"})


def _steps_over(tmp_path, count, steps, monkeypatch):
    base = _wide(tmp_path, count)
    store = ProjectStore.create(tmp_path / ("wide%d.sqlite" % count), base, schema=TASK_STORE_SCHEMA)
    keys = tuple("i%05d" % index for index in range(steps))
    task = create_task(store, task_id="t", base_revision=base.revision_id, actor="w",
        objective="wide", tools=("author.python",), budgets={"max_tool_calls": steps + 2},
        scope=ProposalScope(instances=keys))["task"]
    # The store's READ PATH is measured, so Python is not called at all.
    monkeypatch.setattr(runner, "execute_author_script",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("stub")))
    version, started = task["version"], time.perf_counter()
    with _Reads() as counter:
        for index, key in enumerate(keys):
            step = runner.evaluate_task_recipe(store, "t", source="program = {}", instance_key=key,
                module_key="m", output_keys=("level",), request_id="s%d" % index,
                expected_version=version, generation=0, actor="w", policy=runner.RECIPE_POLICY)
            version = step["task"]["version"]
    return {"N": count, "steps": steps, "loads": counter.loads, "walks": counter.walks,
            "assets": counter.assets, "seconds": time.perf_counter() - started}


@pytest.mark.parametrize("count", [250, 2000])
def test_a_recipe_step_does_not_reread_the_whole_model_for_every_element(tmp_path, monkeypatch, count):
    """Full model parses/traversals PER ELEMENT are a constant, and it equals zero."""
    measured = _steps_over(tmp_path, count, 5, monkeypatch)
    assert measured["assets"] == 0, measured
    # One head is parsed once per handle; per ELEMENT — nothing.
    assert measured["loads"] <= 2, measured
    assert measured["walks"] <= 4, measured


# ───────── self-review: did the substitution pins weaken the guarantees ───────

def test_a_swapped_stored_revision_is_refused_after_the_guarantee_was_issued(tmp_path):
    """`_find_revision` now remembers the parse — it is still obligated to catch a SUBSTITUTION as before."""
    import sqlite3
    from kir.project_store import StoreCorrupt

    store, base = case(tmp_path, "swap.sqlite")
    assert store.get(base.revision_id).revision_id == base.revision_id  # guarantee issued
    forged = ProjectRevision("plan-project", [ModuleDefinition("explicit")], [
        ModuleInstance(key, "explicit", {"level": sdk.create_level(elev_mm=-777., name=key)})
        for key in KEYS], metadata={"units": "mm"}).dumps()
    connection = sqlite3.connect(str(store.path))
    with connection:
        connection.execute("UPDATE revisions SET payload=? WHERE revision_id=?",
                           (forged, base.revision_id))
    connection.close()
    with pytest.raises(StoreCorrupt):
        store.get(base.revision_id)
    with pytest.raises(StoreCorrupt):
        store.head()


def test_a_swapped_asset_is_refused_on_the_write_sweep_after_the_guarantee(tmp_path):
    """`_check_revision_assets` takes REFERENCES from memory, but the body's BYTES — from disk."""
    import sqlite3
    from kir.project_store import StoreCorrupt

    OCP = pytest.importorskip("OCP", reason="телу нужен настоящий OCCT")  # noqa: F841
    import examples.podium_passage as example
    from kir.project_store import ProjectStore as Store

    path = tmp_path / "bodies.sqlite"
    example.save(path)
    store = Store.open(path, readonly=False)
    head = store.head()
    digest = next(iter({output.geometry.bundle_sha256
                        for _, output, _ in head.geometry_references()}))
    assert store.get_asset(digest).digest == digest  # guarantee issued
    connection = sqlite3.connect(str(path))
    with connection:
        row = connection.execute("SELECT payload FROM geometry_assets WHERE digest<>? LIMIT 1",
                                 (digest,)).fetchone()
        if row is None:
            pytest.skip("в сцене одно тело; подменять нечем")
        connection.execute("UPDATE geometry_assets SET payload=? WHERE digest=?", (row[0], digest))
    connection.close()
    with pytest.raises(StoreCorrupt):
        store.get_asset(digest)
    with pytest.raises(StoreCorrupt):
        store.history()


# ───────── self-review: a race between two processes over one step ────────────

TAKER = """
import json, sys
from dataclasses import replace
from kir.project_store import ProjectStore
from kir.project_tasks import abandon_task_tool, read_task
from kir import task_recipe_runner as r

store = ProjectStore.open(sys.argv[1], readonly=False)
plan = json.loads(sys.argv[2])
task = read_task(store, "t")
abandon_task_tool(store, "t", request_id="taken", expected_version=task["version"],
    generation=0, actor="coordinator", tool_request_id=task["pending_tool"],
    reason="another worker takes this step")
run = r.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w", generation=0,
    policy=replace(r.RECIPE_POLICY, probe_network=False), max_steps=1)
print("TAKER " + json.dumps({"invoked": run["invoked"], "stopped": run["stopped"],
    "delivery": run["delivery"]}, separators=(",", ":"), sort_keys=True), flush=True)
"""


def test_a_live_reservation_taken_by_another_process_refuses_the_first_result_by_name(tmp_path):
    """Process 1 is alive, process 2 took the step: one effect, and the refusal is NAMED."""
    store, base = case(tmp_path, "race.sqlite")
    plan = plan_for(base)
    taken = {}
    real = runner.execute_author_script

    def hand_over(*args, **kwargs):
        answer = real(*args, **kwargs)          # process 1 really is computing
        done = subprocess.run([sys.executable, "-c", TAKER, str(store.path), json.dumps(plan)],
            capture_output=True, text=True, timeout=180,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        taken["stdout"], taken["stderr"] = done.stdout, done.stderr
        return answer

    runner.execute_author_script = hand_over
    try:
        first = runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
                                                 generation=0, policy=POLICY, max_steps=1)
    finally:
        runner.execute_author_script = real
    line = next(l for l in taken["stdout"].splitlines() if l.startswith("TAKER "))
    second = json.loads(line.split(" ", 1)[1])
    assert second["invoked"] == 1 and second["delivery"][0]["attempt"] == 2, second
    assert first["stopped"] == "step_taken_by_another_attempt" and first["result"]["completed"] == 0
    task = read_task(store, "t")
    states = [c["state"] for c in task["tool_calls"]]
    assert states == ["abandoned_unresolved", "recorded"], states
    assert len([e for e in task_history(store, "t") if e["kind"] == "tool_finish"]) == 1


# ───────── self-review: the journal's capacity is named BEFORE the start ──────

def test_a_plan_that_cannot_fit_is_named_before_any_python_runs(tmp_path, monkeypatch):
    """Truncating the plan midway leaves half the effect without a name."""
    store, base = case(tmp_path, "full.sqlite", calls=8)
    plan = plan_for(base)
    monkeypatch.setattr(runner, "execute_author_script",
                        lambda *a, **k: pytest.fail("отказ по ёмкости обязан быть ДО Python"))
    narrow, _ = case(tmp_path, "narrow.sqlite", calls=2)
    short = runner.evaluate_task_recipe_plan(narrow, "t", plan=plan, actor="w",
                                             generation=0, policy=POLICY)
    assert short["stopped"] == "plan_exceeds_tool_call_budget"
    assert short["result"]["completed"] == 0 and len(read_task(narrow, "t")["tool_calls"]) == 0

    monkeypatch.setattr(runner, "MAX_EVENTS", 6)
    refused = runner.evaluate_task_recipe_plan(store, "t", plan=plan, actor="w",
                                               generation=0, policy=POLICY)
    assert refused["stopped"] == "plan_exceeds_task_journal"
    assert refused["result"]["completed"] == 0 and refused["invoked"] == 0
    assert len(read_task(store, "t")["tool_calls"]) == 0


# ───────── self-review: two signatures are computed from THE DATA ─────────────

def test_the_two_digests_separate_content_from_history(tmp_path):
    """Identical content under different history: content matches, result does not."""
    reference, base = case(tmp_path, "reference.sqlite")
    plan = plan_for(base)
    continuous = whole(reference, plan)

    store, _ = case(tmp_path, "retried.sqlite")
    done, _, _ = other_process(store, plan, KIR_PLAN_CRASH_AT="0:before_ack")
    assert done.returncode == 77, done.stderr
    task = read_task(store, "t")
    abandon_task_tool(store, "t", request_id="drop-0", expected_version=task["version"],
        generation=0, actor="coordinator", tool_request_id=task["pending_tool"],
        reason="unknown outcome")
    retried = whole(store, plan)
    assert retried["complete"] and [d["attempt"] for d in retried["delivery"]] == [2, 1, 1]
    # The CONTENT is the same, the HISTORY differs — and the signatures tell them apart.
    assert retried["result"]["content_digest"] == continuous["result"]["content_digest"]
    assert retried["result"]["result_digest"] != continuous["result"]["result_digest"]

    # The signature is computed from THE DATA: one changed digit — a different signature.
    steps = retried["result"]["steps"]
    tampered = [dict(step) for step in steps]
    tampered[1]["program_sha256"] = "0" * 64
    assert runner._hash([runner._step_content(s) for s in steps]) != \
        runner._hash([runner._step_content(s) for s in tampered])
    # The chain hangs on the CONTENT of the previous step, not on its receipt.
    arguments = {c["request_id"]: c["arguments"] for c in retried["task"]["tool_calls"]}
    for index in (1, 2):
        pins = arguments[runner._step_request_id(plan, index, 1)]["pins"]
        assert pins["depends_on"] == runner._hash(runner._step_content(steps[index - 1]))
        assert pins["depends_on"] != steps[index - 1]["evaluation_digest"]
