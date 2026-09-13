"""Independent task-tool admission and recipe-result association controls.

Real SQLite stores; only named positive cases invoke benign sandbox scripts.
Every sandbox policy used here requires isolation and disables network probing.
No Revit, LLM, network request or worker-process orchestration is exercised.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from kir import project_tasks as tasks
from kir import task_recipe_runner as runner
from kir.project import _canonical
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_store import ProjectStore, StoreConflict
from kir.tests.test_project_merge import edit
from kir.tests.test_task_recipe_runner import case, POLICY


def no_execute(monkeypatch):
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: pytest.fail("unexpected Python invocation"))


@pytest.mark.parametrize("fault", ["no_budget", "actor", "generation", "namespace", "language", "invalid_policy"])
def test_invalid_admission_never_reaches_the_evaluator_or_charges_a_call(tmp_path, monkeypatch, fault):
    store, _, kwargs = case(tmp_path, calls=0 if fault == "no_budget" else 2)
    if fault == "actor":
        kwargs["actor"] = "other-worker"
    elif fault == "generation":
        kwargs["generation"] = 1
    elif fault == "namespace":
        kwargs["parameters"] = {"project_id": "other-project"}
    elif fault == "language":
        kwargs["policy"] = replace(POLICY, dsl_module="kir.dsl")
    elif fault == "invalid_policy":
        bad = replace(POLICY)
        object.__setattr__(bad, "network", "requred")
        kwargs["policy"] = bad
    before = store.path.read_bytes()
    no_execute(monkeypatch)
    with pytest.raises((tasks.TaskError, StoreConflict, ValueError)):
        runner.evaluate_task_recipe(store, "a", **kwargs)
    assert store.path.read_bytes() == before
    assert tasks.read_task(store, "a")["tool_calls"] == []


def test_executed_inputs_and_policy_match_the_durable_tool_request(tmp_path):
    store, _, kwargs = case(tmp_path)
    kwargs["source"] += "\n# Exact Unicode source: башня 🏢\n"
    kwargs["parameters"]["height_mm"] = 701.5
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert result["invoked"] and result["recorded"]
    call = result["call"]
    evaluation = call["output"]["evaluation"]
    assert call["arguments"]["source"] == evaluation["source"] == kwargs["source"]
    assert evaluation["source_sha256"] == hashlib.sha256(kwargs["source"].encode()).hexdigest()
    assert call["arguments"]["parameters"] == evaluation["parameters"]
    assert call["arguments"]["parameters"]["height_mm"] == 701.5
    assert call["arguments"]["policy"] == json.loads(_canonical(asdict(kwargs["policy"])))
    assert call["arguments"]["policy"]["network"] == "required"
    assert call["arguments"]["policy"]["filesystem_isolation"] is True
    assert call["arguments"]["policy"]["probe_network"] is False
    assert evaluation["program"]["ops"][0]["elev_mm"] == 701.5
    assert evaluation["sandbox_receipt"]["author_digest"] == evaluation["source_sha256"]
    assert tasks.read_task(ProjectStore.open(store.path), "a")["tool_calls"][0] == call


def test_full_unprojectable_envelope_survives_recording_and_readback(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    kwargs["source"] += "\nprogram['units'] = [{'id':'u','name':'retain entire envelope','ops':[]}]\n"
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    output = result["call"]["output"]
    assert output["evaluation"]["sandbox_receipt"]["ok"] is True
    assert output["evaluation"]["program"]["units"] == [{"id": "u", "name": "retain entire envelope", "ops": []}]
    assert output["proposal"] is None and output["projection_refusal"]["code"] == "recipe_envelope_unsupported"
    no_execute(monkeypatch)
    repeated = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert repeated["invoked"] is False and repeated["call"]["output"] == output
    with pytest.raises(tasks.TaskError, match="no retained"):
        runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="submit",
            expected_version=result["task"]["version"], generation=0, actor="worker")


def test_mismatched_source_evidence_is_retained_but_never_projected(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    actual = runner.execute_author_script
    def wrong_receipt(source, **options):
        result = actual(source, **options)
        assert result.ok
        result.author_digest = "f" * 64  # Controlled wrong-result injection.
        return result
    monkeypatch.setattr(runner, "execute_author_script", wrong_receipt)
    result = runner.evaluate_task_recipe(store, "a", **kwargs)
    output = result["call"]["output"]
    assert output["proposal"] is None and output["projection_refusal"]["code"] == "recipe_source_mismatch"
    assert output["evaluation"]["program"]["ops"][0]["elev_mm"] == 700
    assert output["evaluation"]["sandbox_receipt"]["author_digest"] == "f" * 64
    assert len(store.history()) == 1


@pytest.mark.parametrize("resolution", ["abandon", "reassign"])
def test_unknown_attempt_is_charged_and_exact_redelivery_never_reinvokes(tmp_path, monkeypatch, resolution):
    store, _, kwargs = case(tmp_path, calls=1)
    # Capture the real runner's arguments/reservation, then stop before the
    # evaluator. This is intentionally NOT evidence that Python had executed.
    class StopBeforeEvaluator(BaseException):
        pass
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: (_ for _ in ()).throw(StopBeforeEvaluator()))
    with pytest.raises(StopBeforeEvaluator):
        runner.evaluate_task_recipe(store, "a", **kwargs)
    pending = tasks.read_task(store, "a")
    command = dict(request_id="resolve", expected_version=pending["version"], generation=0,
                   actor="coordinator", reason="Explicit unknown outcome")
    if resolution == "abandon":
        current = tasks.abandon_task_tool(store, "a", tool_request_id="evaluate", **command)["task"]
    else:
        current = tasks.reassign_task(store, "a", new_actor="worker", **command)["task"]
    no_execute(monkeypatch)
    replayed = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert replayed["invoked"] is False
    assert replayed["call"]["state"] in {"abandoned_unresolved", "superseded_unresolved"}
    before = store.path.read_bytes()
    with pytest.raises(tasks.TaskError, match="budget"):
        runner.evaluate_task_recipe(store, "a", **{**kwargs, "request_id": "new-evaluation",
            "expected_version": current["version"], "generation": current["generation"]})
    assert store.path.read_bytes() == before


def recorded_proposal(store, base, task):
    change = ChangeProposal(base, edit(base, "a", 600), ProposalScope(instances=("a",)), "worker", "evaluated")
    reserved = tasks.begin_task_tool(store, "a", request_id="evaluate", expected_version=task["version"],
        generation=0, actor="worker", tool=runner.TOOL_NAME, arguments={"controlled": "no actual evaluator"})
    done = tasks.finish_task_tool(store, "a", request_id="result", expected_version=reserved["task"]["version"],
        generation=0, actor="worker", tool_request_id="evaluate", output={"proposal": change.to_dict(),
            "evaluation": {"fixture": "trusted adapter input, not actual execution"}})
    return change, done["task"]


def test_same_actor_label_in_new_generation_cannot_submit_old_tool_result(tmp_path, monkeypatch):
    store, base, _ = case(tmp_path)
    change, completed = recorded_proposal(store, base, tasks.read_task(store, "a"))
    current = tasks.reassign_task(store, "a", request_id="new-generation", expected_version=completed["version"],
        generation=0, actor="coordinator", new_actor="worker", reason="Fenced attempt")["task"]
    no_execute(monkeypatch)
    before = store.path.read_bytes()
    with pytest.raises(tasks.TaskError, match="retained tool output"):
        runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="submit-new-attempt",
            expected_version=current["version"], generation=1, actor="worker")
    assert store.path.read_bytes() == before and tasks.read_task(store, "a")["proposal"] is None


def test_source_tool_matches_full_proposal_not_only_candidate_revision(tmp_path):
    store, base, _ = case(tmp_path)
    original, completed = recorded_proposal(store, base, tasks.read_task(store, "a"))
    altered = replace(original, reason="Different decision rationale attached to same candidate")
    assert altered.candidate.revision_id == original.candidate.revision_id
    assert altered.proposal_id != original.proposal_id
    before = store.path.read_bytes()
    with pytest.raises(tasks.TaskError, match="retained tool output"):
        tasks.submit_task(store, "a", altered, request_id="mismatched-result",
            expected_version=completed["version"], generation=0, actor="worker", source_tool="evaluate")
    assert store.path.read_bytes() == before
    submitted = runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="exact-result",
        expected_version=completed["version"], generation=0, actor="worker")
    assert submitted["event"]["body"]["proposal"] == original.to_dict()


def test_insufficient_lifecycle_capacity_refuses_before_python(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENTS", 4)
    store, _, kwargs = case(tmp_path)
    no_execute(monkeypatch)
    before = store.path.read_bytes()
    with pytest.raises(tasks.TaskError, match="event budget"):
        runner.evaluate_task_recipe(store, "a", **kwargs)
    assert store.path.read_bytes() == before and tasks.read_task(store, "a")["pending_tool"] is None


def test_five_events_allow_complete_tool_submit_decision_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENTS", 5)
    store, base, _ = case(tmp_path)
    change, completed = recorded_proposal(store, base, tasks.read_task(store, "a"))
    submitted = runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="submit",
        expected_version=completed["version"], generation=0, actor="worker")["task"]
    result = tasks.decide_task(store, "a", request_id="decision", expected_version=submitted["version"], generation=0,
        actor="coordinator", proposal_id=change.proposal_id, expected_revision=base.revision_id)
    assert result["task"]["state"] == "accepted" and len(tasks.task_history(store, "a")) == 5


def test_tool_output_bytes_reserve_later_submission_and_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_EVENT_BYTES", 32000)
    monkeypatch.setattr(tasks, "MAX_TASK_BYTES", 160000)
    store, base, _ = case(tmp_path)
    initial = tasks.read_task(store, "a")
    change = ChangeProposal(base, edit(base, "a", 600), ProposalScope(instances=("a",)), "worker", "evaluated")
    reserved = tasks.begin_task_tool(store, "a", request_id="evaluate", expected_version=initial["version"],
        generation=0, actor="worker", tool=runner.TOOL_NAME, arguments={"bounded": "x" * 27000})["task"]
    completed = tasks.finish_task_tool(store, "a", request_id="finish", expected_version=reserved["version"],
        generation=0, actor="worker", tool_request_id="evaluate", output={"proposal": change.to_dict()})["task"]
    submitted = runner.submit_evaluated_recipe(store, "a", tool_request_id="evaluate", request_id="submit",
        expected_version=completed["version"], generation=0, actor="worker")["task"]
    result = tasks.decide_task(store, "a", request_id="decision", expected_version=submitted["version"], generation=0,
        actor="coordinator", proposal_id=change.proposal_id, expected_revision=base.revision_id)
    assert result["task"]["state"] == "accepted"
