"""Real public author/compile routes preserve the sandbox's full envelope.

No Revit calls, fabricated sandbox results, or semantic-success claims from
authoring alone. Invalid JSON and compiler refusals retain their own stages.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from kir.compiler import compile_program
from kir.diag import SANDBOX_BAD_RESULT
from kir.mcp import server
from kir.mcp.policy import author_policy
from kir.sandbox import execute_author_script


BASE = {
    "ir_version": "1.0", "intent": "Exact level",
    "defaults": {"level": {"by": "element_id", "value": 123}},
    "allow_destructive": False,
    "units": [{"id": "u0", "name": "Apartment", "ops": ["w"]}],
    "ops": [{"op": "create_wall", "id": "w", "p0_mm": [0, 0],
             "p1_mm": [5000, 0]}],
}


def call(name, args):
    body, crashed = asyncio.run(server.dispatch(name, args))
    assert not crashed, body
    return body


def test_full_envelope_public_author_then_real_compile():
    source = f"result = {BASE!r}"
    direct = execute_author_script(source, policy=author_policy())
    assert direct.ok, direct.refusal
    body = call("kir_author", {"program_py": source})
    assert body["ok"] and body["wrote_nothing"]
    assert body["program"] == direct.to_program() == BASE
    receipt = body["authorship"]
    assert receipt["program_py"] == source
    assert receipt["author_digest"] == hashlib.sha256(source.encode()).hexdigest()
    assert receipt["program_digest"] == direct.program_digest
    assert receipt["environment"]["digest"] == direct.env_digest
    assert receipt["params"] == []
    assert "ops" not in receipt and "envelope" not in receipt
    assert "authorship" not in body["program"]
    compiled = call("kir_compile", {"program": body["program"],
                                     "versions": ["2023", "2026"]})
    assert compiled["ok"], compiled
    assert compiled["versions"]["green"] == ["2023", "2026"]
    json.dumps(body, allow_nan=False)


@pytest.mark.parametrize("override,code", [
    ({"ir_version": "2.0"}, "KIR-P004"),
    ({"intent": True}, "KIR-T001"),
    ({"defaults": []}, "KIR-T001"),
    ({"allow_destructive": "yes"}, "KIR-T001"),
    ({"unsupported_field": {"meaning": "must not disappear"}}, "KIR-P003"),
    ({"phases": [{"name": "foundation", "ops": ["w"]}]}, "KIR-P003"),
])
def test_invalid_envelope_is_not_sanitized_or_flattened(override, code):
    program = {**BASE, **override}
    source = f"result = {program!r}"
    direct = execute_author_script(source, policy=author_policy())
    assert direct.ok, direct.refusal  # authoring success is not compilation
    body = call("kir_author", {"program_py": source})
    assert body["ok"]
    assert body["program"] == direct.to_program() == program
    expected = compile_program(direct.to_program(), revit_version="2026")
    assert not expected.ok
    diagnostics = [str(item) for item in expected.diagnostics]
    assert code in " ".join(diagnostics)
    actual = call("kir_compile", {"program": body["program"], "versions": ["2026"]})
    assert not actual["ok"]
    assert actual["per_version"]["2026"]["diagnostics"] == diagnostics
    if "phases" in override:
        assert "split_phases" in " ".join(diagnostics)


@pytest.mark.parametrize("invalid", ["set([1])", "float('nan')", "{1: 'not a string key'}"])
def test_non_json_unknown_envelope_is_named_sandbox_refusal(invalid):
    source = f"result = {BASE!r}\nresult['unsupported_field'] = {invalid}"
    direct = execute_author_script(source, policy=author_policy())
    assert not direct.ok
    assert direct.refusal.code == SANDBOX_BAD_RESULT
    body = call("kir_author", {"program_py": source})
    assert not body["ok"] and body["wrote_nothing"]
    assert body["err"]["code"] == direct.refusal.code
    assert body["err"]["message_ru"] == direct.refusal.message_ru
    assert "program" not in body
    assert body["authorship"]["program_py"] == source


def test_real_dsl_harvest_keeps_parameters_units_and_source_lineage():
    source = (
        "span = param('span', 4000, min=1000, max=10000, doc='Wall span')\n"
        "envelope(intent='Parametric apartment')\n"
        "with unit('Apartment'):\n"
        "    create_wall(id='w', p0_mm=[0, 0], p1_mm=[span, 0], "
        "level={'by': 'element_id', 'value': 123})\n"
        "print('authoring finished')\n"
    )
    body = call("kir_author", {"program_py": source, "params": {"span": 6500}})
    assert body["ok"], body
    assert body["program"]["intent"] == "Parametric apartment"
    group = body["program"]["ops"][0]
    assert group["op"] == "create_group"
    assert group["members"][0]["p1_mm"] == [6500, 0]
    assert body["program"]["units"][0]["name"] == "Apartment"
    receipt = body["authorship"]
    assert receipt["isolation"]["harvest"] == "dsl.take_ops()"
    assert receipt["params"][0]["value"] == 6500
    assert receipt["params"][0]["default"] == 4000
    assert receipt["params"][0]["used_default"] is False
    assert receipt["params_digest"] == body["params_digest"]
    assert receipt["lineage"]["members[w]"][-1] == 4
    assert receipt["stdout"] == "authoring finished\n"
    assert receipt["program_py"] == source
    compiled = call("kir_compile", {"program": body["program"], "versions": ["2026"]})
    assert compiled["ok"], compiled


def test_dsl_execution_phases_remain_explicit():
    source = (
        "with phase('foundation'):\n"
        "    create_level(id='l1', name='L1', elev_mm=0)\n"
        "with phase('structure'):\n"
        "    create_level(id='l2', name='L2', elev_mm=3000)\n"
    )
    body = call("kir_author", {"program_py": source})
    assert body["ok"], body
    assert len(body["program"]["phases"]) == 2
    assert len(body["program"]["ops"]) == 2
    compiled = call("kir_compile", {"program": body["program"], "versions": ["2026"]})
    assert not compiled["ok"]
    assert "split_phases" in str(compiled["per_version"]["2026"])


def test_loss_receipt_names_previous_reset_program():
    body = call("kir_author", {"program_py": (
        "envelope(intent='Previous')\n"
        "create_level(name='A', elev_mm=0)\n"
        "reset(intent='Current')\n"
        "create_level(name='B', elev_mm=3000)\n")})
    assert body["ok"], body
    assert body["authorship"]["left_behind"] == [{"intent": "Previous", "ops": 1}]
    assert body["program"]["intent"] == "Current"
    assert len(body["program"]["ops"]) == 1


def test_runtime_refusal_preserves_real_source_line():
    source = "value = 3\nraise ValueError('named failure')\n"
    direct = execute_author_script(source, policy=author_policy())
    body = call("kir_author", {"program_py": source})
    assert not body["ok"]
    assert body["line"] == direct.refusal.line == 2
    assert body["source_line"] == direct.refusal.line_text == "raise ValueError('named failure')"
    assert body["authorship"]["refusal"]["code"] == direct.refusal.code


def test_plain_ops_variable_still_gets_default_ir_version():
    source = "ops = [{'op': 'create_level', 'id': 'l', 'name': 'L', 'elev_mm': 0}]"
    body = call("kir_author", {"program_py": source})
    assert body["ok"], body
    assert body["program"]["ir_version"] == "1.0"
    assert body["authorship"]["isolation"]["harvest"] == "ns.ops"
    assert call("kir_compile", {"program": body["program"], "versions": ["2026"]})["ok"]
