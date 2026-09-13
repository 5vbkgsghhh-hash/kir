"""D1: real compiler and public MCP dispatch, simulated transport evidence.

These tests do not execute Revit. They prove that a supplied receipt cannot
turn absent readback, an unknown outcome or a violated witness into success.
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from kir import ports
from kir.mcp import handles, live, server


PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]}
GOOD = {"ok": True, "L": {"id": "123456"}}


def write_receipt(receipt, monkeypatch, program=None):
    class Transport:
        writes = 0

        async def read(self, _source, *, timeout_ms):
            return {"title": "D1.rvt", "version": "2026", "path": "C:/D1.rvt"}

        async def write(self, _source, *, timeout_ms):
            self.writes += 1
            return copy.deepcopy(receipt)

    transport = Transport()
    ports.register(ports.MCP_REVIT, lambda: transport)
    handles._reset_for_tests()
    monkeypatch.setenv(live.WRITE_FLAG, "on")
    monkeypatch.setenv("KIR_MCP_CONFIRM", "off")
    try:
        opened, crashed = asyncio.run(server.dispatch("kir_open", {}))
        assert not crashed and opened["ok"], opened
        result, crashed = asyncio.run(server.dispatch("kir_write", {
            "building": opened["building"], "program": program or PROGRAM,
        }))
        assert not crashed, result
        return result, transport.writes
    finally:
        ports.unregister(ports.MCP_REVIT)
        handles._reset_for_tests()


@pytest.mark.parametrize("receipt", [
    None, {}, [], "ok", {"state": "running_unknown"},
    {"ok": True, "state": "running_unknown", "L": {"id": "123"}},
    {"ok": True, "status": "receipt", "receipt": {
        "state": "failed_after_observed_change", "started": True, "error": "boom"}},
    {"ok": True, "status": "receipt", "receipt": {
        "state": "invocation_completed", "result_json": "null"}},
    {"ok": 1, "L": {"id": "123"}},
    {"ok": "true", "L": {"id": "123"}},
    {"result": GOOD, "result_truncated": True},
    {**GOOD, "result_error": "serialization failed"},
    {"result": GOOD, "state": []},
    {"result": GOOD, "err": {"code": "arbitrary.failure"}},
    {"result": GOOD, "outcome": {"execution": "unconfirmed"}},
    {"result": None}, {"result": {"result": {"result": GOOD}}},
])
def test_missing_or_unknown_evidence_is_not_success(receipt, monkeypatch):
    result, writes = write_receipt(receipt, monkeypatch)
    assert writes == 1
    assert result["ok"] is False
    assert result["wrote_nothing"] is False
    assert result["outcome"]["execution"] == "unconfirmed"
    assert result["outcome"]["retry"] == "verify_first"
    assert result["outcome"]["acceptance"] == "not_run"


@pytest.mark.parametrize("receipt", [
    {"ok": True}, {"ok": True, "created": 4},
    {"ok": True, "L": {}}, {"ok": True, "L": None},
    {"ok": True, "L": {"id": True}}, {"ok": True, "L": {"id": -1}},
    {"ok": True, "L": {"id": "not-an-id"}},
    {"ok": True, "L": {"id": "123"}, "postcondition_violations": None},
    {"ok": True, "L": {"id": "123"}, "postcondition_violations": "bad"},
    {"ok": True, "L": {"id": "123"}, "postcondition_violations": [None]},
])
def test_commit_can_be_confirmed_while_readback_is_incomplete(receipt, monkeypatch):
    result, writes = write_receipt(receipt, monkeypatch)
    assert writes == 1 and result["ok"] is False
    assert result["outcome"] == {
        "schema_version": "kir-program-outcome/1", "execution": "committed",
        "witness": "incomplete", "acceptance": "not_run", "retry": "forbidden",
    }
    assert result["wrote_nothing"] is False


@pytest.mark.parametrize("receipt", [GOOD, {"result": GOOD},
                                      {"ok": True, "result": GOOD}])
def test_complete_execution_is_not_independent_acceptance(receipt, monkeypatch):
    result, writes = write_receipt(receipt, monkeypatch)
    assert writes == 1 and result["ok"] is True
    assert result["outcome"]["execution"] == "committed"
    assert result["outcome"]["witness"] == "satisfied"
    assert result["outcome"]["acceptance"] == "not_run"
    assert result["intent_verified"] is False
    assert result["success_scope"] == "execution_contract"
    assert result["receipt"] == receipt


@pytest.mark.parametrize("receipt,execution,witness,retry", [
    ({"error": "stale_or_failed"}, "unconfirmed", "incomplete", "verify_first"),
    ({"error": "postconditions_violated"}, "unconfirmed", "incomplete", "verify_first"),
    ({"error": "stale_or_failed", "commit_status": "Pending"},
     "unconfirmed", "incomplete", "verify_first"),
    ({"error": "postconditions_violated", "commit_status": "Committed",
      "violations": ["L missing"]}, "committed", "violated", "forbidden"),
    ({**GOOD, "postcondition_violations": ["L: wrong elevation"]},
     "committed", "violated", "forbidden"),
    ({"error": "postconditions_violated", "commit_status": "RolledBack",
      "violations": ["L missing"]}, "rolled_back", "violated", "safe"),
    ({"error": "stale_or_failed", "commit_status": "RolledBack"},
     "rolled_back", "incomplete", "safe"),
    ({**GOOD, "commit_status": "RolledBack"},
     "unconfirmed", "incomplete", "verify_first"),
    ({**GOOD, "commit_status": "Pending"},
     "unconfirmed", "incomplete", "verify_first"),
    ({"commit_status": "RolledBack", "result": {
        "error": "stale_or_failed", "commit_status": "Committed"}},
     "unconfirmed", "incomplete", "verify_first"),
])
def test_execution_witness_and_retry_do_not_collapse(
        receipt, execution, witness, retry, monkeypatch):
    result, writes = write_receipt(receipt, monkeypatch)
    assert writes == 1 and result["ok"] is False
    assert result["outcome"]["execution"] == execution
    assert result["outcome"]["witness"] == witness
    assert result["outcome"]["retry"] == retry
    assert result["wrote_nothing"] is (execution == "rolled_back")


def test_query_is_not_dispatched_as_a_mutating_program(monkeypatch):
    result, writes = write_receipt({"q": {"count": 0}}, monkeypatch, {
        "ops": [{"op": "query_count", "id": "q", "kind": "wall"}],
    })
    assert writes == 0
    assert result["ok"] is False and result["wrote_nothing"] is True
    assert result["err"]["code"] == "write_family_required"
