"""The existing sandbox carrier emits detached full IR, not ops-only IR."""
from __future__ import annotations

import copy
from dataclasses import replace
import json

import pytest

from kir.compiler import compile_program
from kir.sandbox import (
    SandboxPolicy, SandboxResult, SandboxResultContradiction, execute_author_script,
)


PROGRAM = {
    "ir_version": "1.0",
    "intent": "Exact level",
    "defaults": {"level": {"by": "element_id", "value": 123}},
    "allow_destructive": False,
    "units": [{"id": "u0", "name": "Apartment", "ops": ["w"]}],
    "ops": [{"op": "create_wall", "id": "w", "p0_mm": [0, 0],
             "p1_mm": [5000, 0]}],
}


@pytest.fixture(scope="module")
def authored():
    result = execute_author_script(f"result = {PROGRAM!r}", policy=SandboxPolicy())
    assert result.ok, result.refusal
    return result


def test_complete_program_reaches_real_compiler(authored):
    assert authored.to_program() == PROGRAM
    for version in ("2023", "2026"):
        output = compile_program(authored.to_program(), revit_version=version)
        assert output.ok, output.diagnostics
        assert output.units == PROGRAM["units"]
    # Negative control: the original ops-only adapter loses the required level.
    broken = compile_program({"ops": authored.ops}, revit_version="2026")
    assert not broken.ok
    assert "KIR-P005" in str(broken.diagnostics)


def test_program_and_receipt_are_deeply_detached(authored):
    result = copy.deepcopy(authored)
    result.model_digest = "model-input"
    result.building_digest = "building-input"
    result.params = [{"choices": ["a", "b"], "value": "a"}]
    result.lineage = {"w": [1, 4]}
    result.left_behind = [{"intent": "previous", "ops": 3}]
    before = copy.deepcopy(result)
    program = result.to_program()
    program["defaults"]["level"]["value"] = 999
    program["ops"][0]["p0_mm"][0] = 333
    program["units"][0]["ops"].append("fake")
    receipt = result.as_dict()
    assert receipt["model_digest"] == "model-input"
    assert receipt["building_digest"] == "building-input"
    receipt["ops"][0]["p0_mm"].append(777)
    receipt["envelope"]["defaults"]["level"]["value"] = 0
    receipt["params"][0]["choices"].clear()
    receipt["lineage"]["w"].append(999)
    receipt["left_behind"][0]["ops"] = 0
    receipt["isolation"]["invented"] = True
    receipt["environment"].clear()
    assert result == before
    assert result.to_program() == PROGRAM
    json.dumps(result.as_dict(), allow_nan=False)


@pytest.mark.parametrize("mutate", [
    lambda r: r.ops[0]["p0_mm"].append(999),
    lambda r: r.envelope.update(intent="different"),
    lambda r: r.envelope.update(ops=[]),
    lambda r: r.envelope.update(intent=float("nan")),
])
def test_mutable_carrier_cannot_emit_changed_program_under_old_digest(authored, mutate):
    result = copy.deepcopy(authored)
    mutate(result)
    with pytest.raises(SandboxResultContradiction):
        result.to_program()


def test_evidence_stamping_and_real_replay_still_work():
    result = execute_author_script(
        "create_level(id='l', name='L', elev_mm=0)",
        policy=replace(SandboxPolicy(), replay_check=True))
    assert result.ok, result.refusal
    assert result.isolation["replay_checked"] is True
    result.lineage["l"] = [1]
    result.duration_s += 0.001
    assert result.to_program()["ops"][0]["id"] == "l"


def test_refused_program_cannot_be_extracted_and_receipt_is_detached():
    result = execute_author_script("raise ValueError('broken')", policy=SandboxPolicy())
    assert not result.ok
    with pytest.raises(SandboxResultContradiction, match="refused"):
        result.to_program()
    receipt = result.as_dict()
    receipt["refusal"]["message_ru"] = "changed"
    assert result.refusal.message_ru != "changed"


def test_undigested_legacy_constructor_remains_supported():
    result = SandboxResult(ok=True, ops=copy.deepcopy(PROGRAM["ops"]),
                           envelope={k: copy.deepcopy(v) for k, v in PROGRAM.items()
                                     if k != "ops"})
    assert result.to_program() == PROGRAM
