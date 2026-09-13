"""Explicit CLI recipe step under the actual required sandbox policy."""
from dataclasses import asdict
import json

import pytest

from kir import __main__ as cli
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.project_tasks import begin_task_tool
from kir.task_recipe_runner import RECIPE_POLICY, TOOL_NAME
from kir.tests.test_project_cli_lifecycle import _fresh, _successful
from kir.tests.test_project_tasks_cli import command, mutation


SOURCE = '''pid = param('project_id', 'unused')
iid = param('instance_key', 'unused')
envelope(intent='Recipe CLI')
h = param('height', 3000)
create_level(id=project_output_id(pid, iid, 'level'), name='L1', elev_mm=h)
'''


def prepared(tmp_path):
    base = ProjectRevision("recipe-cli", [ModuleDefinition("m")], [ModuleInstance("a", "m", {
        "level": {"op": "create_level", "elev_mm": 0}})], intent="Recipe CLI")
    store = ProjectStore.create(tmp_path / "project.sqlite", base, schema=TASK_STORE_SCHEMA)
    task = _successful(_fresh(command(store, "create", "design", "--base", base.revision_id,
        "--actor", "agent", "--objective", "Evaluate recipe", "--allow-instance", "a", "--allow-module", "m",
        "--tool", TOOL_NAME, "--max-tool-calls", "2")))["task"]
    source_file = tmp_path / "source.py"
    source_file.write_text(SOURCE, encoding="utf-8")
    return base, store, task, source_file


def evaluation_command(store, task, source, *extra):
    return mutation(store, "evaluate", task, "evaluate-1", str(source), "--instance", "a", "--module", "m",
                    "--output", "level", *extra)


def test_actual_required_recipe_retained_then_explicitly_submitted(tmp_path):
    base, store, task, source = prepared(tmp_path)
    params = tmp_path / "params.json"
    params.write_text('{"height":3300}', encoding="utf-8")
    evaluate = evaluation_command(store, task, source, "--parameters", str(params))
    result = _successful(_fresh(evaluate))
    assert result["recorded"] is True
    call = result["call"]
    output = call["output"]
    assert output["proposal"] is not None and output["projection_refusal"] is None
    evaluation = output["evaluation"]
    assert evaluation["source"] == SOURCE
    assert evaluation["parameters"]["height"] == 3300
    assert evaluation["program"]["ops"][0]["elev_mm"] == 3300
    assert evaluation["sandbox_receipt"]["ok"] is True
    assert call["arguments"]["policy"]["network"] == "required"
    assert call["arguments"]["policy"]["filesystem_isolation"] is True
    assert store.head().revision_id == base.revision_id
    assert result["task"]["state"] == "assigned"
    before = store.path.read_bytes()
    replay = _successful(_fresh(evaluate))
    assert replay["invoked"] is False and replay["call"] == call
    assert store.path.read_bytes() == before
    submitted = _successful(_fresh(mutation(store, "submit-evaluation", result["task"], "submit",
        "--tool-request-id", "evaluate-1")))
    assert submitted["task"]["proposal"] == output["proposal"]
    assert submitted["event"]["body"]["source_tool"] == "evaluate-1"
    assert store.head().revision_id == base.revision_id
    accepted = _successful(_fresh(mutation(store, "decide", submitted["task"], "decide", "--proposal-id",
        output["proposal"]["proposal_id"], "--expected", base.revision_id, actor="coordinator")))
    assert accepted["task"]["state"] == "accepted" and accepted["native_published"] is False


def test_full_program_metadata_retained_when_projection_refuses(tmp_path):
    base, store, task, source = prepared(tmp_path)
    program = {"ir_version": base.ir_version, "intent": base.intent, "metadata": {"future": "keep me"},
        "ops": [{"op": "create_level", "id": output_id(base.project_id, "a", "level"), "elev_mm": 4500}]}
    source.write_text("param('project_id', 'unused')\nparam('instance_key', 'unused')\nresult = " + repr(program), encoding="utf-8")
    evaluate = evaluation_command(store, task, source)
    code, raw, error = _fresh(evaluate)
    assert code == cli.NOT_DONE, error
    result = json.loads(raw)
    output = result["call"]["output"]
    assert output["evaluation"]["program"] == program
    assert output["evaluation"]["sandbox_receipt"]["ok"] is True
    assert output["proposal"] is None
    assert output["projection_refusal"]["code"] == "recipe_envelope_unsupported"
    assert store.head().revision_id == base.revision_id
    replay_code, replay_raw, _ = _fresh(evaluate)
    assert replay_code == cli.NOT_DONE and json.loads(replay_raw)["invoked"] is False
    code, raw, error = _fresh(mutation(store, "submit-evaluation", result["task"], "submit",
                                      "--tool-request-id", "evaluate-1"))
    assert code == cli.NOT_DONE and not raw and "no retained" in error


def test_reserved_attempt_is_not_reexecuted_and_can_be_abandoned(tmp_path):
    base, store, task, source = prepared(tmp_path)
    # Simulate crash after durable reservation, before any Python invocation.
    # Exact runner-owned arguments let the CLI identify it, never infer replay authority.
    arguments = {"source": SOURCE, "parameters": {"project_id": base.project_id, "instance_key": "a"},
        "instance_key": "a", "module_key": "m", "output_bindings": {"level": output_id(base.project_id, "a", "level")},
        "reason": "Explicit recipe evaluation", "policy": json.loads(json.dumps(asdict(RECIPE_POLICY)))}
    reserved = begin_task_tool(store, "design", request_id="evaluate-1", expected_version=task["version"],
        generation=0, actor="agent", tool=TOOL_NAME, arguments=arguments)
    before = store.path.read_bytes()
    code, raw, error = _fresh(evaluation_command(store, task, source))
    assert code == cli.NOT_DONE, error
    result = json.loads(raw)
    assert result["invoked"] is False and result["call"]["state"] == "reserved"
    assert store.path.read_bytes() == before
    abandoned = _successful(_fresh(mutation(store, "abandon-tool", reserved["task"], "abandon",
        "--tool-request-id", "evaluate-1", "--reason", "outcome unresolved", actor="coordinator")))
    assert abandoned["task"]["tool_calls"][0]["state"] == "abandoned_unresolved"
    assert abandoned["task"]["pending_tool"] is None
    code, raw, _ = _fresh(evaluation_command(store, task, source))
    assert code == cli.NOT_DONE and json.loads(raw)["invoked"] is False


@pytest.mark.parametrize("params", ["[]", "null", '{"height":1,"height":2}', '{"height":NaN}', "{"])
def test_invalid_parameters_do_not_reserve(tmp_path, params):
    _, store, task, source = prepared(tmp_path)
    path = tmp_path / "params.json"
    path.write_text(params, encoding="utf-8")
    before = store.path.read_bytes()
    code, raw, error = _fresh(evaluation_command(store, task, source, "--parameters", str(path)))
    assert code == cli.NOT_DONE and not raw and "Traceback" not in error
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("flag", [["--network", "off"], ["--filesystem-isolation", "false"]])
def test_cli_cannot_weaken_trusted_policy(tmp_path, flag):
    _, store, task, source = prepared(tmp_path)
    before = store.path.read_bytes()
    code, raw, error = _fresh(evaluation_command(store, task, source, *flag))
    assert code == cli.NOT_DONE and not raw and "unrecognized arguments" in error
    assert store.path.read_bytes() == before


def test_source_bounded_before_reservation(tmp_path):
    _, store, task, source = prepared(tmp_path)
    source.write_text("#" * (RECIPE_POLICY.max_source_bytes + 1), encoding="utf-8")
    before = store.path.read_bytes()
    code, raw, error = _fresh(evaluation_command(store, task, source))
    assert code == cli.NOT_DONE and not raw and "byte budget" in error
    assert store.path.read_bytes() == before
