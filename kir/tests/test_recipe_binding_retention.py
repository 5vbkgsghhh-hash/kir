"""Independent recipe-completion identity controls on actual SQLite/sandbox.

The evaluator wrapper observes calls; it does not substitute a fake result.
No model execution or host scheduling authority is asserted by these tests.
"""
import pytest

from kir import task_recipe_runner as runner
from kir.project import _hash
from kir.project_tasks import TaskError, checkpoint_task, read_task
from kir.tests.test_task_recipe_runner import case


def _checkpoint(store, kwargs, request_id):
    return checkpoint_task(store, "a", request_id=request_id,
        expected_version=kwargs["expected_version"], generation=0, actor="worker",
        notes={"phase": "lawful caller-chosen checkpoint identifier"})["task"]


def test_preoccupied_completion_request_id_refuses_before_recipe_execution(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    completion_id = "tool-result-" + _hash(kwargs["request_id"])
    task = _checkpoint(store, kwargs, completion_id)
    kwargs["expected_version"] = task["version"]
    before = store.path.read_bytes()
    invocations = []
    actual_execute = runner.execute_author_script

    def observe_execute(*args, **options):
        result = actual_execute(*args, **options)
        assert result.ok, result.as_dict()
        invocations.append(result.to_program())
        return result

    monkeypatch.setattr(runner, "execute_author_script", observe_execute)
    with pytest.raises(TaskError):
        runner.evaluate_task_recipe(store, "a", **kwargs)
    assert invocations == [], "completion ID collision was detected only AFTER successful Python evaluation"
    assert store.path.read_bytes() == before
    assert read_task(store, "a")["tool_calls"] == []


def test_noncolliding_checkpoint_id_preserves_the_actual_result_and_exact_replay(tmp_path, monkeypatch):
    store, _, kwargs = case(tmp_path)
    task = _checkpoint(store, kwargs, "tool-result-" + _hash(kwargs["request_id"]) + "-other")
    kwargs["expected_version"] = task["version"]
    evaluated = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert evaluated["invoked"] and evaluated["recorded"]
    output = evaluated["call"]["output"]
    assert output["projection_refusal"] is None
    assert output["evaluation"]["program"]["ops"][0]["elev_mm"] == 700
    assert output == read_task(store, "a")["tool_calls"][0]["output"]
    monkeypatch.setattr(runner, "execute_author_script",
                        lambda *_a, **_k: pytest.fail("exact replay reinvoked Python"))
    replayed = runner.evaluate_task_recipe(store, "a", **kwargs)
    assert not replayed["invoked"] and replayed["call"]["output"] == output
