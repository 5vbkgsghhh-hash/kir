"""THE RECEIPT IS READ, NOT JUST RELAYED (RT-04).

`live.write_program` used to assemble the response like this:

    receipt = await transport.write(out.csharp, timeout_ms=WRITE_TIMEOUT_MS)
    return {"ok": True, …, "receipt": receipt}

Not one line looked at the receipt's contents. A transport that returned
a SUBSTANTIVE refusal looked like success from the outside: `ok:true`,
`wrote_nothing:false`, no `err` block at all. For a model reading the
door's response, that is the statement "written" — and its next move is
built on top of a building that does not exist.

🔴 THE REFUSAL SHAPES ARE NOT INVENTED, THEY ARE OUR OWN. They are printed
by this same tree's emitter, and they are visible in the goldens:
`__Refuse` returns `{"error": "stale_or_failed", "op_id": …, "message":
…}` BEFORE `Commit`, and a postcondition check returns
`{"error": "postconditions_violated", "violations": […],
"commit_status": …}` AFTER an explicit `RollBack`. Success carries
`__results["ok"] = true`.

🔴 PARSING IS ASKED OF `kir.bridge_result`, NOT REWRITTEN HERE FROM
SCRATCH: this module exists precisely so that no dispatcher would set up
ITS OWN semantics for a bridge refusal. A separate instrument below
guards that the door asks exactly that module.

The transport is fake for the same reason as in the neighboring file: a
live Revit would verify that the write went through, while what is
checked here is something that costs more and is checkable without it —
that the door does not call someone else's refusal a success.
"""
from __future__ import annotations

import asyncio

import pytest

from kir import ports
from kir.mcp import handles, live, server


class _Receipting:
    """A host that returns a GIVEN receipt. It counts round trips."""

    def __init__(self, receipt):
        self.receipt = receipt
        self.reads: list[str] = []
        self.writes: list[str] = []

    async def read(self, csharp: str, *, timeout_ms: int):
        self.reads.append(csharp)
        return {"title": "Проект1.rvt", "version": "2026", "path": "C:/п.rvt"}

    async def write(self, csharp: str, *, timeout_ms: int):
        self.writes.append(csharp)
        return self.receipt


def _program() -> dict:
    from kir import sdk
    p = sdk.program(intent="коробка для ворот квитанции")
    level = p.add(sdk.create_level(elev_mm=0, name="Этаж 1"))
    pts = [(0, 0), (8000, 0), (8000, 5000), (0, 5000)]
    for i in range(4):
        p.add(sdk.create_wall(p0_mm=pts[i], p1_mm=pts[(i + 1) % 4],
                              level=level, height_mm=3000))
    return p.to_dict()


def _write_with(receipt, monkeypatch):
    """Open the door, write, return (response, host)."""
    fake = _Receipting(receipt)
    ports.register(ports.MCP_REVIT, lambda: fake)
    handles._reset_for_tests()
    monkeypatch.setenv(live.WRITE_FLAG, "on")
    monkeypatch.setenv("KIR_MCP_CONFIRM", "off")
    try:
        opened, crashed = asyncio.run(server.dispatch("kir_open", {}))
        assert not crashed, opened
        body, crashed = asyncio.run(server.dispatch(
            "kir_write", {"building": opened["building"],
                          "program": _program()}))
        assert not crashed, "дверь СЛОМАЛАСЬ — это не отказ, а поломка"
        return body, fake
    finally:
        ports.unregister(ports.MCP_REVIT)
        handles._reset_for_tests()


# ═══════════════════════════════════════════════════════════════════════════

def test_postconditions_violated_is_not_a_success(monkeypatch):
    """POSITIVE. A postcondition rollback comes out as a REFUSAL.

    Measured on this very receipt:
        BEFORE  ok True   wrote_nothing False  no err
        AFTER   ok False  wrote_nothing True   err.code write_refused
    """
    body, fake = _write_with(
        {"error": "postconditions_violated",
         "violations": ["W1: стена не создана"],
         "commit_status": "RolledBack"}, monkeypatch)
    assert len(fake.writes) == 1, "рейс не состоялся — меряем не то"
    assert body["ok"] is False
    assert body["err"]["code"] == "write_refused"
    assert "postconditions_violated" in body["err"]["message_ru"]
    # "nothing went into the model" is asserted ONLY where this is
    # known: this marker is printed by our own emitter after an explicit
    # RollBack.
    assert body["wrote_nothing"] is True
    assert "откатена" in body["err"]["message_ru"]
    # THE RECEIPT STAYS WHOLE: a refusal has no right to consume it
    assert body["receipt"]["violations"] == ["W1: стена не создана"]
    assert body["program_digest"] == live.program_digest(_program())


def test_a_stale_refusal_from_the_emitter_is_not_a_success(monkeypatch):
    """The error marker alone does not confirm Transaction.RollBack."""
    body, _ = _write_with(
        {"error": "stale_or_failed", "op_id": "W1",
         "message": "элемент исчез после grounding"}, monkeypatch)
    assert body["ok"] is False
    assert body["err"]["code"] == "write_refused"
    assert body["wrote_nothing"] is False
    assert body["outcome"]["execution"] == "unconfirmed"
    assert "элемент исчез после grounding" in body["err"]["message_ru"]


def test_a_flat_ok_false_is_not_a_success(monkeypatch):
    """A foreign host is entitled to say `ok:false` without our marker.

    Then a "rollback" is NOT asserted: the port's promise ("either
    whole, or nothing") is a promise, not evidence, and the door will not
    sign it with its own word.
    """
    body, _ = _write_with({"ok": False, "message": "хост отказал"}, monkeypatch)
    assert body["ok"] is False
    assert body["err"]["code"] == "write_refused"
    assert body["wrote_nothing"] is False, "непроверенный откат объявлен фактом"
    # 🔴 ПИН НА СЛОВАХ СТАЛ ПИНОМ НА ФАКТЕ (13.09.2026, Р1.2 аудита H §3).
    # Пинилась фраза «прочитай модель» — то есть ровно тот ход, которого у
    # агента НЕТ: у двери семь инструментов и ни одного читающего, и этот пин
    # ТРЕБОВАЛ несуществующего хода от отказа. Теперь утверждается свойство:
    # следующий ход назван и назван ТЕМ, ЧТО ЕСТЬ, а отсутствие чтения названо
    # вслух одним носителем (`live.NO_READER_RU`).
    assert body["next_ru"].strip(), "отказ обязан назвать следующий ход"
    assert live.NO_READER_RU in body["next_ru"], (
        "отказ снова умалчивает, что читать модель этой двери нечем")
    assert "прочитай модель" not in body["next_ru"], (
        "отказ снова велит ход, которого у агента нет")


def test_an_unconfirmed_outcome_is_not_called_a_refusal(monkeypatch):
    """THE THIRD OUTCOME. "We don't know" does not collapse into either
    "written" or "not written."

    A blind repeat after an unknown outcome duplicates whatever might have
    applied — so it has its own code and its own "read the model."
    """
    body, _ = _write_with(
        {"error": True, "state": "RunningUnknown",
         "err": {"code": "transport.execution_unknown"}}, monkeypatch)
    assert body["ok"] is False
    assert body["err"]["code"] == "execution_unknown"
    assert body["wrote_nothing"] is False
    assert "удво" in body["next_ru"], "цена слепого повтора не названа"
    assert live.NO_READER_RU in body["next_ru"], (
        "отказ снова умалчивает, что читать модель этой двери нечем")


def test_a_good_receipt_still_passes_through_untouched(monkeypatch):
    """FAIL CONTROL. A successful receipt must stay a success.

    Without this, "ok:false" would be a property of the instrument, not
    of the receipt: a door that always refuses would pass all four checks
    above.
    """
    receipt = {"ok": True, **{
        op["id"]: {"id": str(1000 + i)}
        for i, op in enumerate(_program()["ops"])
    }}
    body, fake = _write_with(receipt, monkeypatch)
    assert len(fake.writes) == 1
    assert body["ok"] is True
    assert body["wrote_nothing"] is False
    assert "err" not in body
    assert body["receipt"] == receipt
    assert body["outcome"]["acceptance"] == "not_run"


def test_a_receipt_without_all_planned_results_is_incomplete(monkeypatch):
    """D1: absence of an error cannot prove the other four result identities."""
    body, _ = _write_with({"W1": {"id": "123456"}, "ok": True}, monkeypatch)
    assert body["ok"] is False and "err" in body
    assert body["outcome"]["execution"] == "committed"
    assert body["outcome"]["witness"] == "incomplete"


def test_absent_negative_signal_does_not_replace_positive_evidence(monkeypatch):
    """A disabled negative detector must not bypass positive result contracts."""
    from kir import bridge_result

    real = bridge_result.extract_error
    monkeypatch.setattr(bridge_result, "extract_error", lambda _r: None)
    try:
        body, _ = _write_with(
            {"error": "postconditions_violated", "violations": ["x"]},
            monkeypatch)
    finally:
        monkeypatch.setattr(bridge_result, "extract_error", real)
    assert body["ok"] is False
    assert body["outcome"]["execution"] == "unconfirmed"


def test_the_transport_exception_branch_is_untouched(monkeypatch):
    """A failure of the transport ITSELF stays as before: the outcome is UNKNOWN."""
    class _Boom(_Receipting):
        async def write(self, csharp, *, timeout_ms):
            self.writes.append(csharp)
            raise TimeoutError("мост молчит")

    fake = _Boom(None)
    ports.register(ports.MCP_REVIT, lambda: fake)
    handles._reset_for_tests()
    monkeypatch.setenv(live.WRITE_FLAG, "on")
    monkeypatch.setenv("KIR_MCP_CONFIRM", "off")
    try:
        opened, _ = asyncio.run(server.dispatch("kir_open", {}))
        body, crashed = asyncio.run(server.dispatch(
            "kir_write", {"building": opened["building"],
                          "program": _program()}))
        assert not crashed
    finally:
        ports.unregister(ports.MCP_REVIT)
        handles._reset_for_tests()
    assert body["ok"] is False
    assert body["err"]["code"] == "transport"
    assert body["wrote_nothing"] is False
