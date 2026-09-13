"""Saved residential pilot: parallel recipe workers, reviewed merge and resume.

Recipes were authored by the development agents. The reproducible worker driver
is deterministic, not an autonomous LLM scheduler. This is authored geometry/XY
acceptance, never a complete BIM design or live Revit acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from examples import residential_refinement as refinement
from examples.residential_recipes import section_recipe, tower_recipe
from kir.project import ModuleDefinition, _canonical, _thaw, output_id
from kir.compiler import plan_program
from kir.diag import KirRefusal
from kir.project_diff import diff_projects
from kir.project_merge import ChangeProposal, ProposalScope, merge_proposal
from kir.project_store import ProjectStore, StoreConflict, TASK_STORE_SCHEMA
from kir.project_tasks import create_task, checkpoint_task, read_task, task_history, decide_task
from kir.section_plan_acceptance import assess_section_plan_change
from kir.project_selection import selected_instance_program
from kir.task_recipe_runner import evaluate_task_recipe, submit_evaluated_recipe


MODULES = {"tower-a": "agent-section-a", "tower-b": "agent-tower-b"}
CHAIN = tuple(f"storey-{n:02d}-slab" for n in (1, 2, 3))


class PilotRefusal(ValueError):
    def __init__(self, code, message, report=None):
        self.code, self.report = code, report
        super().__init__(f"{code}: {message}")


def initialize(path) -> ProjectStore:
    """Build the existing real podium/refinement first; create a NEW DB only."""
    store = refinement.create_store(path)
    head = store.head()
    store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head.revision_id)
    # Allocate independent module slots once. Workers will not race to invent
    # a global module ordering while independently replacing instance bodies.
    prepared = head.revise(expected_revision=head.revision_id,
        modules=[*head.modules, *(ModuleDefinition(key) for key in MODULES.values())])
    store.commit(prepared, expected_revision=head.revision_id)
    return store


def assign_recipe_task(store, task_id, descriptor, *, actor, expected_revision):
    base = store.head()
    if base.revision_id != expected_revision:
        raise StoreConflict("pilot assignment requires the expected authored head")
    descriptor = json.loads(_canonical(descriptor))
    instance = descriptor["instance_key"]
    if MODULES.get(instance) != descriptor["module_key"]:
        raise PilotRefusal("pilot_scope", "expected one of the preallocated residential recipe modules")
    assigned = create_task(store, task_id=task_id, base_revision=expected_revision, actor=actor,
        objective=f"Explicit residential recipe change for {instance}; retain the other instances",
        scope=ProposalScope(instances=(instance,), modules=(descriptor["module_key"],)),
        tools=("author.python",), budgets={"max_tool_calls": 1})
    # The descriptor is now durable input, not regenerated from today's files
    # when a worker resumes. Exact repeated preparation uses the initial event.
    return checkpoint_task(store, task_id, request_id="recipe-input",
        expected_version=assigned["event"]["digest"], generation=0, actor=actor,
        notes={"recipe": descriptor})["task"]


def _instructions(store, task_id):
    events = task_history(store, task_id)
    instruction = next((e for e in events if e["request_id"] == "recipe-input" and e["kind"] == "checkpoint"), None)
    if instruction is None:
        raise PilotRefusal("pilot_input_missing", "no retained recipe-input checkpoint")
    return instruction, events


def run_worker(database, task_id):
    store = ProjectStore.open(database, readonly=False)
    instruction, _ = _instructions(store, task_id)
    descriptor = instruction["body"]["notes"]["recipe"]
    evaluated = evaluate_task_recipe(store, task_id, **descriptor, request_id="evaluate",
        expected_version=instruction["digest"], generation=instruction["generation"], actor=instruction["actor"])
    summary = {"task_id": task_id, "pid": os.getpid(), "evaluation_invoked": evaluated["invoked"],
               "call_state": evaluated["call"]["state"], "native_execution": "not_run"}
    output = evaluated["call"]["output"]
    if evaluated["call"]["state"] != "recorded" or output.get("proposal") is None:
        return {**summary, "state": "needs_review", "projection_refusal": None if output is None else output.get("projection_refusal")}
    _, events = _instructions(store, task_id)
    completion = next(e for e in events if e["kind"] == "tool_finish" and e["body"]["tool_request_id"] == "evaluate")
    submitted = submit_evaluated_recipe(store, task_id, tool_request_id="evaluate", request_id="submit",
        expected_version=completion["digest"], generation=instruction["generation"], actor=instruction["actor"])
    return {**summary, "state": submitted["task"]["state"], "proposal_id": output["proposal"]["proposal_id"]}


def _instances(project):
    return {instance.key: instance for instance in project.instances}


def _request_geometry(proposed, descriptor):
    """Small independent analytic oracle for this explicit pilot request."""
    p = descriptor["parameters"]
    instance = _instances(proposed)[descriptor["instance_key"]]
    if tuple(output.key for output in instance.outputs) != tuple(descriptor["output_keys"]):
        raise PilotRefusal("request_output_coverage_mismatch", "named outputs/order differ from the explicit recipe request")
    ops = {output.key: _thaw(output.operation) for output in instance.outputs}
    expected, actual = {}, {}
    if instance.key == "tower-a":
        for n in (1, 2, 3):
            prefix = f"storey-{n:02d}"
            expected[prefix + "-elevation"] = (n - 1) * p["storey_height_mm"]
            actual[prefix + "-elevation"] = ops[prefix + "-level"]["elev_mm"]
            for side in range(4):
                expected[f"{prefix}-wall-{side}-height"] = p["storey_height_mm"]
                actual[f"{prefix}-wall-{side}-height"] = ops[f"{prefix}-wall-{side}"]["height_mm"]
            width = p["width_mm"] - (p["terrace_setback_mm"] if n == 3 else 0)
            expected[prefix + "-outline"] = [[p["x_mm"], 0.], [p["x_mm"] + width, 0.],
                [p["x_mm"] + width, p["depth_mm"]], [p["x_mm"], p["depth_mm"]]]
            actual[prefix + "-outline"] = ops[prefix + "-slab"]["contour"]["outer"]["points_mm"]
    else:
        op = ops["concept-volume"]
        expected.update(height=p["storeys"] * p["storey_height_mm"], base_z=0.)
        actual.update(height=op["height_mm"], base_z=op["base_z_mm"])
        x, width, depth = p["x_mm"], p["width_mm"], p["depth_mm"]
        expected["bottom"] = [[x, 0.], [x + width, 0.], [x + width, depth], [x, depth]]
        angle = math.radians(p["twist_deg"])
        cx, cy = x + width / 2, depth / 2
        expected["top"] = [[cx + .82 * ((a-cx)*math.cos(angle) - (b-cy)*math.sin(angle)),
                            cy + .82 * ((a-cx)*math.sin(angle) + (b-cy)*math.cos(angle))]
                           for a, b in expected["bottom"]]
        actual["bottom"] = op["profile"]["outer"]["points_mm"]
        actual["top"] = op["profile_top"]["outer"]["points_mm"]
    def equal(a, b):
        if isinstance(a, list):
            return isinstance(b, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        return type(b) in (int, float) and math.isclose(a, b, abs_tol=1e-7, rel_tol=1e-12)
    rows = [{"predicate": key, "status": "evaluated" if equal(value, actual[key]) else "violated",
             "expected": value, "actual": actual[key]} for key, value in expected.items()]
    return {"scope": "pilot_authored_request_geometry_not_native_body", "rows": rows,
            "revision_id": proposed.revision_id, "instance_key": instance.key}


def _section_gate(store, current, candidate):
    section = _instances(current)["tower-a"]
    source = store.get(section.metadata["refinement"]["source"]["revision_id"])
    protected = [key for key in _instances(current) if key != "tower-a"]
    report = assess_section_plan_change(current, candidate, source=source, instance_key="tower-a",
        required_void_chain=CHAIN, protected_instances=protected).to_dict()
    expected = {
        "named_subject_retained": [output.key for output in section.outputs],
        "room_axis_enclosure": [f"storey-{n:02d}-space" for n in (1, 2, 3)],
        "room_seed_in_slab_xy_region": [f"storey-{n:02d}-space" for n in (1, 2, 3)],
        "selected_void_footprint_retained": list(CHAIN),
        "selected_void_chain_xy_continuity": [[a, b] for a, b in zip(CHAIN, CHAIN[1:])],
        "protected_instance_snapshot": protected,
    }
    for predicate, subjects in expected.items():
        rows = [row for row in report["rows"] if row["predicate"] == predicate]
        if (len(rows) != len(subjects) or {_canonical(row["subject"]) for row in rows} != {_canonical(s) for s in subjects}
                or any(row["status"] != "evaluated" for row in rows)):
            raise PilotRefusal("section_xy_not_qualified", predicate, report)
    return report


def accept_task(store, task_id, *, expected_revision):
    task = read_task(store, task_id)
    if task["state"] != "submitted":
        raise PilotRefusal("pilot_task_not_submitted", task["state"])
    current = store.head()
    if current.revision_id != expected_revision:
        raise StoreConflict("pilot review requires the expected authored head")
    change = ChangeProposal.from_dict(task["proposal"])
    merged = merge_proposal(change, current, authorized_scope=ProposalScope.from_dict(task["assignment"]["scope"]))
    section_report, geometry_report, selected_plan = None, None, None
    if merged.clean:
        instruction, _ = _instructions(store, task_id)
        descriptor = instruction["body"]["notes"]["recipe"]
        try:
            instance = _instances(merged.revision)[descriptor["instance_key"]]
            if any(output.geometry is not None for output in instance.outputs):
                raise PilotRefusal("pilot_program_not_interpretable", "recipe target unexpectedly owns external bodies")
            selected_plan = plan_program(selected_instance_program(merged.revision, instance.key))
            geometry_report = _request_geometry(merged.revision, descriptor)
            if any(row["status"] != "evaluated" for row in geometry_report["rows"]):
                raise PilotRefusal("request_geometry_not_qualified", "authored outputs differ from the explicit request", geometry_report)
            if descriptor["instance_key"] == "tower-a":
                section_report = _section_gate(store, current, merged.revision)
        except PilotRefusal:
            raise
        except (KirRefusal, KeyError, TypeError, ValueError, IndexError, OverflowError) as error:
            raise PilotRefusal("pilot_geometry_not_interpretable", type(error).__name__) from error
    # No automatic retry if either task or project changed during review.
    decision = decide_task(store, task_id, request_id="decision", expected_version=task["version"],
        generation=task["generation"], actor="pilot-coordinator", proposal_id=change.proposal_id,
        expected_revision=expected_revision)
    if merged.clean and decision["task"]["decision"]["accepted_revision"] != merged.revision.revision_id:
        raise PilotRefusal("reviewed_result_mismatch", "decision did not retain the reviewed authored result")
    return {"decision": decision, "section_assessment": section_report, "request_geometry": geometry_report,
            "selected_plan_digest": None if selected_plan is None else selected_plan.plan_digest}


def _process(args, *, stdin=None):
    return subprocess.Popen([sys.executable, "-m", "examples.residential_agent_workflow", *map(str, args)],
        stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def _parallel_workers(path, task_ids):
    workers = [_process(["worker", path, task_id, "--wait-start"], stdin=subprocess.PIPE) for task_id in task_ids]
    ready = []
    try:
        # Both real worker processes must be alive at the release barrier.
        with selectors.DefaultSelector() as selector:
            for worker in workers:
                selector.register(worker.stdout, selectors.EVENT_READ, worker)
            deadline = time.monotonic() + 20
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PilotRefusal("worker_start_timeout", "workers did not reach the release barrier")
                for key, _ in selector.select(remaining):
                    line = key.fileobj.readline()
                    if not line:
                        raise PilotRefusal("worker_start_failed", "worker exited before readiness")
                    ready.append(json.loads(line))
                    selector.unregister(key.fileobj)
        if not all(worker.poll() is None for worker in workers):
            raise PilotRefusal("worker_not_live", "readiness is not a current liveness observation")
        for worker in workers:
            worker.stdin.write("go\n"); worker.stdin.flush()
        results = []
        for worker in workers:
            output, error = worker.communicate(timeout=60)
            if worker.returncode:
                raise PilotRefusal("worker_failed", error[-4000:])
            results.append(json.loads(output))
        return {"ready": ready, "both_alive_at_release": True, "results": results}
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill(); worker.wait(timeout=5)


def _fresh(args):
    process = _process(args)
    try:
        output, error = process.communicate(timeout=60)
        if process.returncode:
            raise PilotRefusal("pilot_process_failed", error[-4000:])
        return json.loads(output)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)


def run_demo(path):
    store = initialize(path)
    base = store.head()
    assign_recipe_task(store, "section-a", section_recipe(base), actor="section-worker", expected_revision=base.revision_id)
    assign_recipe_task(store, "tower-b", tower_recipe(base), actor="tower-worker", expected_revision=base.revision_id)
    assign_recipe_task(store, "section-conflict", section_recipe(base, height_mm=4700.), actor="conflicting-worker", expected_revision=base.revision_id)
    workers = _parallel_workers(store.path, ("section-a", "tower-b"))
    accepted = _fresh(["accept", store.path, "tower-b", "section-a"])
    concurrent = store.head()
    _fresh(["worker", store.path, "section-conflict"])
    conflict = _fresh(["accept", store.path, "section-conflict"])
    if read_task(store, "section-conflict")["state"] != "conflicted" or store.head().revision_id != concurrent.revision_id:
        raise PilotRefusal("missing_expected_conflict", "overlapping proposal did not remain unaccepted")
    assign_recipe_task(store, "section-resume", section_recipe(concurrent, height_mm=4800., setback_mm=1600.),
                       actor="resumed-worker", expected_revision=concurrent.revision_id)
    resumed_worker = _fresh(["worker", store.path, "section-resume"])
    resumed = _fresh(["accept", store.path, "section-resume"])
    final = store.head()
    return {"schema": "kir-residential-agent-pilot/1", "database": str(store.path),
        "baseline_revision": base.revision_id, "concurrent_revision": concurrent.revision_id,
        "final_revision": final.revision_id, "source_revision": base.instances[0].metadata["refinement"]["source"]["revision_id"],
        "workers": workers, "coordinator": accepted, "conflict": conflict,
        "resumed_worker": resumed_worker, "resumed_coordinator": resumed,
        "concurrent_diff": diff_projects(base, concurrent).to_dict(),
        "resume_diff": diff_projects(concurrent, final).to_dict(),
        "tasks": {key: read_task(store, key)["state"] for key in ("section-a", "tower-b", "section-conflict", "section-resume")},
        "history_length": len(store.history()), "native_execution": "not_run",
        "limitations": ["deterministic worker driver, not an LLM scheduler", "section remains schematic redesign",
            "XY and declared geometry predicates, not native BIM/body or engineering acceptance"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("demo", "worker", "accept"):
        command = sub.add_parser(action)
        command.add_argument("database")
        if action == "worker":
            command.add_argument("task_id")
            command.add_argument("--wait-start", action="store_true")
        elif action == "accept":
            command.add_argument("task_ids", nargs="+")
    args = parser.parse_args(argv)
    if args.action == "demo":
        result = run_demo(args.database)
    elif args.action == "worker":
        if args.wait_start:
            print(json.dumps({"state": "ready", "pid": os.getpid(), "task_id": args.task_id}), flush=True)
            if sys.stdin.readline().strip() != "go":
                raise PilotRefusal("worker_not_released", "expected explicit parent barrier release")
        result = run_worker(args.database, args.task_id)
    else:
        store = ProjectStore.open(args.database, readonly=False)
        result = {"pid": os.getpid(), "results": [accept_task(store, task_id, expected_revision=store.head().revision_id)
                                                   for task_id in args.task_ids]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
