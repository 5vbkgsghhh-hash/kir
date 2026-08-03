"""Production handler closes plan -> reread -> durable evidence loop."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from kukai.ir import serving
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


L1 = "Этаж 1"
L2 = "Этаж 2"
PROGRAM = {
    "ir_version": "1.0",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "name", "value": L1},
    }],
}


@pytest.fixture
def live_door(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    monkeypatch.setenv("KIR_ACCEPTANCE_EVIDENCE_DIR", str(tmp_path))
    client = mock.Mock()
    client._revit_version = "2026"
    with mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE):
        yield client, tmp_path


def _run_with(
    client,
    bridge: PassingAcceptanceBridge,
    *,
    door=serving.handle_revit_ir,
    program=PROGRAM,
    write_payload=None,
    inspect_write=None,
    after=None,
    mutation_before=None,
    mutation_after=None,
    invalid_before: bool = False,
    invalid_after: bool = False,
):
    calls = []

    def execute(_code, op):
        if op == "ground_snapshot":
            return {"result": GROUND_SNAPSHOT}
        if op == "write":
            if inspect_write is not None:
                inspect_write(_code)
            return {"result": (write_payload or {
                "ok": True, "W1": {"id": "9001"}})}
        raise AssertionError(op)

    async def fake_exec(_llm, _callback, code, op, _timeout):
        calls.append(op)
        if op == "acceptance_before" and invalid_before:
            return {"result": {"schema_version": "wrong"}}
        if op == "acceptance_after" and invalid_after:
            return {"result": {"schema_version": "wrong"}}
        if op == "acceptance_after" and after is not None:
            original = bridge._matching_after
            bridge._matching_after = lambda _expectation, _before: after(
                dict(_before))
            try:
                return bridge.dispatch(execute, code, op)
            finally:
                bridge._matching_after = original
        mutation_transform = (
            mutation_before if op == "acceptance_before" else mutation_after)
        if (op in {"acceptance_before", "acceptance_after"}
                and mutation_transform is not None):
            original_mutation = bridge._mutation_observation
            bridge._mutation_observation = lambda *args: mutation_transform(
                original_mutation(*args))
            try:
                return bridge.dispatch(execute, code, op)
            finally:
                bridge._mutation_observation = original_mutation
        return bridge.dispatch(execute, code, op)

    with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
        result = asyncio.run(door(
            {"program": program}, client, bridge_callback=None))
    return result, calls


def test_exact_live_delta_is_the_only_green_regular_write(live_door):
    client, evidence_root = live_door
    result, calls = _run_with(client, PassingAcceptanceBridge(PROGRAM))

    assert calls == [
        "ground_snapshot", "acceptance_before", "write", "acceptance_after",
    ]
    assert result["ok"] is True
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["witness"] == "satisfied"
    assert result["outcome"]["acceptance"] == "accepted"
    assert result["acceptance"]["state"] == "accepted"
    assert result["acceptance"]["journal"]["durable"] is True
    assert len(result["acceptance"]["evidence_digest"]) == 64
    journals = list(evidence_root.glob("*.jsonl"))
    assert len(journals) == 1
    assert journals[0].read_text(encoding="utf-8").count("\n") == 2


@pytest.mark.parametrize(("mutate", "mismatch"), [
    (lambda before: before, "category_shortfall"),
    (lambda before: {**before, ("OST_Walls", L1): before[
        ("OST_Walls", L1)] + 2}, "category_overshoot"),
    (lambda before: {**before, ("OST_Walls", L2): 1}, "level_shortfall"),
])
def test_negative_live_controls_commit_but_reject(
    live_door, mutate, mismatch,
):
    client, _root = live_door
    result, calls = _run_with(
        client, PassingAcceptanceBridge(PROGRAM), after=mutate)

    assert calls[-1] == "acceptance_after"
    assert result["ok"] is False
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["acceptance"] == "rejected"
    assert result["outcome"]["retry"] == "forbidden"
    assert result["handoff"] is None
    assert result["diagnostics"][0]["code"] == "KIR-A006"
    assert mismatch in {
        row["code"] for row in result["acceptance"]["verdict"]["mismatches"]
    }


def test_invalid_pre_read_refuses_before_write(live_door):
    client, evidence_root = live_door
    result, calls = _run_with(
        client, PassingAcceptanceBridge(PROGRAM), invalid_before=True)
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "KIR-A002"
    assert result["outcome"]["execution"] == "not_started"
    assert "write" not in calls
    assert list(evidence_root.iterdir()) == []


def test_invalid_post_read_never_turns_commit_green(live_door):
    client, evidence_root = live_door
    result, calls = _run_with(
        client, PassingAcceptanceBridge(PROGRAM), invalid_after=True)
    assert calls[-1] == "acceptance_after"
    assert result["ok"] is False
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["acceptance"] == "inconclusive"
    assert result["diagnostics"][0]["code"] == "KIR-A007"
    journal = next(evidence_root.glob("*.jsonl"))
    assert journal.read_text(encoding="utf-8").count("\n") == 2


def test_unexpected_post_commit_bug_cannot_forget_a_confirmed_effect(
    live_door,
):
    client, evidence_root = live_door
    with mock.patch.object(
            serving.AcceptanceSession,
            "assess_after",
            side_effect=RuntimeError("judge bug")):
        result, calls = _run_with(
            client, PassingAcceptanceBridge(PROGRAM))

    assert calls[-1] == "write"
    assert result["ok"] is False
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["retry"] == "forbidden"
    assert result["handoff"] is None
    journal = next(evidence_root.glob("*.jsonl"))
    terminal = json.loads(
        journal.read_text(encoding="utf-8").splitlines()[-1])
    assert terminal["terminal"]["outcome"]["execution"] == "committed"


def test_missing_private_evidence_sink_refuses_before_write(
    live_door, monkeypatch,
):
    client, _root = live_door
    monkeypatch.setenv("KIR_ACCEPTANCE_EVIDENCE_DIR", "")
    result, calls = _run_with(client, PassingAcceptanceBridge(PROGRAM))
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "KIR-A005"
    assert "write" not in calls


def test_direct_admin_bulk_write_has_the_same_acceptance_boundary(live_door):
    client, _root = live_door
    result, calls = _run_with(
        client,
        PassingAcceptanceBridge(PROGRAM, bulk=True),
        door=serving.handle_revit_ir_bulk,
    )

    assert calls == [
        "ground_snapshot", "acceptance_before", "write", "acceptance_after",
    ]
    assert result["ok"] is True
    assert result["outcome"]["acceptance"] == "accepted"


MOVE_PROGRAM = {
    "ir_version": "1.0",
    "ops": [{
        "op": "move_elements",
        "id": "M1",
        "targets": [{"by": "element_id", "value": 101}],
        "delta_mm": [0, 0, 500],
    }],
}

CHANGE_TYPE_PROGRAM = {
    "ir_version": "1.0",
    "ops": [{
        "op": "change_type",
        "id": "T1",
        "target": {"by": "element_id", "value": 101},
        "type": {"by": "element_id", "value": 900},
    }],
}


def _change_first_mutation(observation, **changes):
    return replace(
        observation,
        rows=(replace(observation.rows[0], **changes),
              *observation.rows[1:]),
    )


def test_wrong_independent_move_read_rejects_a_committed_write(live_door):
    client, _root = live_door
    result, calls = _run_with(
        client,
        PassingAcceptanceBridge(MOVE_PROGRAM),
        program=MOVE_PROGRAM,
        write_payload={
            "ok": True,
            "M1": {"moved_ids": ["101"], "count": 1},
        },
        mutation_after=lambda observation: _change_first_mutation(
            observation, point_mm=(0.0, 0.0, 0.0)),
    )

    assert calls[-1] == "acceptance_after"
    assert result["ok"] is False
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["acceptance"] == "rejected"
    assert result["diagnostics"][0]["code"] == "KIR-A006"
    assert result["diagnostics"][0]["mismatches"][0]["axis"] == "mutation"
    assert result["diagnostics"][0]["mismatches"][0]["code"] == (
        "location_mismatch")
    assert "mutation predicates differ" in result["diagnostics"][0]["detail"]
    assert result["handoff"] is None


def test_mutation_baseline_is_embedded_as_transaction_identity_guard(live_door):
    client, _root = live_door
    seen = []
    result, _calls = _run_with(
        client,
        PassingAcceptanceBridge(MOVE_PROGRAM),
        program=MOVE_PROGRAM,
        write_payload={
            "ok": True,
            "M1": {"moved_ids": ["101"], "count": 1},
        },
        inspect_write=seen.append,
    )

    assert result["ok"] is True
    assert len(seen) == 1
    assert "kir-test-uid-101" in seen[0]
    assert "VersionGuid" in seen[0]
    # Guarded both before opening the transaction and again inside it.
    assert seen[0].count("kir-model-binding-guard/1") >= 2


def test_change_type_guards_both_target_and_desired_type(live_door):
    client, _root = live_door
    seen = []
    result, _calls = _run_with(
        client,
        PassingAcceptanceBridge(CHANGE_TYPE_PROGRAM),
        program=CHANGE_TYPE_PROGRAM,
        write_payload={
            "ok": True,
            "T1": {
                "id": "101",
                "type_id": "900",
                "new_element_created": False,
            },
        },
        inspect_write=seen.append,
    )

    assert result["ok"] is True
    assert len(seen) == 1
    assert "kir-test-uid-101" in seen[0]
    assert "kir-test-uid-900" in seen[0]
    assert seen[0].count("new ElementId(900)") >= 2


def test_missing_exact_mutation_target_refuses_before_write(live_door):
    client, evidence_root = live_door
    result, calls = _run_with(
        client,
        PassingAcceptanceBridge(MOVE_PROGRAM),
        program=MOVE_PROGRAM,
        write_payload={
            "ok": True,
            "M1": {"moved_ids": ["101"], "count": 1},
        },
        mutation_before=lambda observation: _change_first_mutation(
            observation,
            exists=False,
            unique_id=None,
            version_guid=None,
            location_kind="missing",
            point_mm=None,
        ),
    )

    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "KIR-A002"
    assert "write" not in calls
    assert list(evidence_root.iterdir()) == []
