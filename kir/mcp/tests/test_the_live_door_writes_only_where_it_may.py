"""GATE FOR THE LIVE DOOR: not one byte to the model where it wasn't told to go.

🔴 FILE RENAMED 03.09.2026. It used to be called `..._asks_before_it_writes`, and
with the owner's decision ("make `off` the default" — yes) that became UNTRUE: by
default the door does not ask. An instrument's name that promises retired
behavior lies more convincingly than a missing instrument: it gets read as the
law currently in force. Confirmation remains a CONTRACT and is checked right
here — but it is turned on explicitly, `KIR_MCP_CONFIRM=call`.

The transport here is FAKE, and that is not a simplification but a condition of
the measurement: a real Revit would check that the write ARRIVED, while here what
is checked is something more valuable and checkable without it — that the write
does NOT go out where it should not. The negative claim is stronger: it is about
all branches at once, not about one lucky one.

🔴 WHY A FAKE COUNTS, AND VISIBILITY DOES NOT. The fake port RECORDS every call.
The claim "nothing went to the model" is not checked by the door returning
`wrote_nothing`, but by the transport's counter NOT MOVING. A door that lied in
its field cannot fool the counter.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from kir import ports
from kir.mcp import handles, live, server


class _FakeRevit:
    """A host that doesn't exist. Counts trips and remembers what it was sent."""

    def __init__(self, title="Проект1.rvt", version="2026"):
        self.title, self.version = title, version
        self.reads: list[str] = []
        self.writes: list[str] = []

    async def read(self, csharp: str, *, timeout_ms: int):
        self.reads.append(csharp)
        return {"title": self.title, "version": self.version, "path": "C:/п.rvt"}

    async def write(self, csharp: str, *, timeout_ms: int):
        self.writes.append(csharp)
        return {"ok": True, **{
            op["id"]: {"id": str(1000 + i)}
            for i, op in enumerate(_program()["ops"])
        }}


def _program() -> dict:
    from kir import sdk
    p = sdk.program(intent="коробка для ворот живой двери")
    level = p.add(sdk.create_level(elev_mm=0, name="Этаж 1"))
    pts = [(0, 0), (8000, 0), (8000, 5000), (0, 5000)]
    for i in range(4):
        p.add(sdk.create_wall(p0_mm=pts[i], p1_mm=pts[(i + 1) % 4],
                              level=level, height_mm=3000))
    return p.to_dict()


@pytest.fixture
def revit(monkeypatch):
    fake = _FakeRevit()
    ports.register(ports.MCP_REVIT, lambda: fake)
    handles._reset_for_tests()
    yield fake
    ports.unregister(ports.MCP_REVIT)
    handles._reset_for_tests()


@pytest.fixture
def writing(monkeypatch):
    monkeypatch.setenv(live.WRITE_FLAG, "on")


@pytest.fixture
def asking(monkeypatch):
    """Confirmation is now the host's CHOICE, not the default.

    An instrument that wants to judge the confirmation mechanism is required to
    TURN IT ON. It used to rely on the default silently — and on the day the
    default changed, seven instruments turned red at once, even though the
    behavior under test had not changed by a single line. Dependence on the
    default is an instrument's hidden input.
    """
    monkeypatch.setenv("KIR_MCP_CONFIRM", "call")


def _call(name, args, **kw):
    return asyncio.run(server.dispatch(name, args, **kw))


def test_open_gives_a_handle_that_names_the_document(revit):
    body, crashed = _call("kir_open", {})
    assert not crashed and body["ok"]
    assert body["document"] == "Проект1.rvt" and body["revit_version"] == "2026"
    assert body["building"].startswith("bld_")
    assert body["write_enabled"] is False, "запись обязана быть выключена по умолчанию"
    assert len(revit.reads) == 1 and not revit.writes


def test_the_flag_is_fail_closed(revit):
    """Without the flag the door does not write — and this is checked by the
    COUNTER, not by a field."""
    opened, _ = _call("kir_open", {})
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": _program()})
    assert body["err"]["code"] == "write_off"
    assert revit.writes == [], "транспорт двинулся при выключенной записи"


def test_a_bad_flag_value_is_not_a_yes(revit, monkeypatch):
    """"1", "true", "yes", "ON" — NOT "on". A door with many ways to open opens
    by accident.

    🔴 WHITESPACE AROUND THE VALUE IS AN EXCEPTION, AND IT IS NAMED. The
    instrument at first demanded a refusal on "` on `" too, and the code accepted
    it. THE CODE turned out to be right: surrounding whitespace is a FORMATTING
    typo, not a second word of consent; a host who wrote `KIR_MCP_WRITE=" on "`
    meant "on". A refusal here would have looked like a broken door, not
    strictness.
    """
    opened, _ = _call("kir_open", {})
    for value in ("1", "true", "yes", "ON", "on1", ""):
        monkeypatch.setenv(live.WRITE_FLAG, value)
        body, _ = _call("kir_write", {"building": opened["building"],
                                      "program": _program()})
        assert body["err"]["code"] == "write_off", f"«{value}» открыло дверь"
    assert revit.writes == []
    monkeypatch.setenv(live.WRITE_FLAG, "  on  ")
    assert live.write_enabled(), "обрамляющий пробел не должен закрывать дверь"


def test_the_first_call_never_writes_it_asks(revit, writing, asking):
    opened, _ = _call("kir_open", {})
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": _program()})
    ask = body[live.INPUT_REQUIRED]
    assert "Проект1.rvt" in ask["message"], "человек обязан видеть КУДА пишут"
    assert "confirm" in ask["schema"]["properties"]
    assert revit.writes == [], "первый ход написал в модель"


def test_confirmation_writes_and_the_csharp_reaches_the_host(revit, writing, asking):
    opened, _ = _call("kir_open", {})
    program = _program()
    first, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})
    state = first[live.INPUT_REQUIRED]["state"]
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": program},
                    confirmed=True, state=state)
    assert body["ok"] and body["wrote_nothing"] is False
    assert len(revit.writes) == 1
    assert "Wall" in revit.writes[0], "до хоста доехал не тот C#"


def test_a_decline_is_not_an_error(revit, writing, asking):
    opened, _ = _call("kir_open", {})
    program = _program()
    first, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})
    body, crashed = _call("kir_write", {"building": opened["building"],
                                        "program": program},
                          confirmed=False,
                          state=first[live.INPUT_REQUIRED]["state"])
    assert not crashed and body["ok"] and body["wrote_nothing"] is True
    assert body["declined"] is True
    assert revit.writes == []


def test_consent_is_bound_to_the_program_not_to_the_door(revit, writing, asking):
    """🔴 LOAD-BEARING. One thing was confirmed — another was sent: the write does
    not go through.

    Otherwise it would be the DOOR that ended up confirmed, not what travels
    through it, and a person's consent would turn into permission for any
    subsequent call.
    """
    from kir import sdk
    opened, _ = _call("kir_open", {})
    program = _program()
    first, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})
    state = first[live.INPUT_REQUIRED]["state"]

    # 🔴 A SECOND PROGRAM — WITH THE SAME CONSTRUCTOR. A hand-written selector
    # used to be here and already lied once (02.09.2026, the second time in one
    # shift): the selector's shape is knowledge that belongs to the registry, and
    # copying it into the instrument means checking its own memory.
    other_p = sdk.program(intent="другая программа, того же вида")
    level = other_p.add(sdk.create_level(elev_mm=0, name="Этаж 1"))
    pts = [(0, 0), (9000, 0), (9000, 5000), (0, 5000)]
    for i in range(4):
        other_p.add(sdk.create_wall(p0_mm=pts[i], p1_mm=pts[(i + 1) % 4],
                                    level=level, height_mm=3000))
    other = other_p.to_dict()
    assert live.program_digest(other) != live.program_digest(program)
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": other},
                    confirmed=True, state=state)
    assert body["err"]["code"] == "confirmation_mismatch"
    assert revit.writes == [], "чужое согласие пропустило запись"


def test_an_expired_handle_refuses_by_name(revit, writing, monkeypatch):
    opened, _ = _call("kir_open", {})
    b = handles.resolve(opened["building"])
    object.__setattr__(b, "issued_at", time.time() - b.ttl_s - 1)
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": _program()})
    assert body["err"]["code"] == "handle"
    assert "истекла" in body["err"]["message_ru"]
    assert revit.writes == []


def test_a_program_that_does_not_compile_never_reaches_the_host(revit, writing):
    opened, _ = _call("kir_open", {})
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": {"ops": [{"op": "нет_такого"}]}})
    assert not body["ok"] and revit.writes == []


def test_a_transport_failure_says_the_outcome_is_unknown(revit, writing, asking):
    """A refusal AFTER sending is not "did not get written". Lying in this
    direction is not allowed: a blind retry doubles whatever might have already
    applied."""
    opened, _ = _call("kir_open", {})
    program = _program()
    first, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})

    async def _boom(csharp, *, timeout_ms):
        raise RuntimeError("мост оборвался")

    revit.write = _boom
    body, crashed = _call("kir_write", {"building": opened["building"],
                                        "program": program},
                          confirmed=True,
                          state=first[live.INPUT_REQUIRED]["state"])
    assert not crashed, "отказ транспорта не есть крах сервера"
    assert body["wrote_nothing"] is False, "исход НЕИЗВЕСТЕН, а не «не писали»"
    assert "НЕИЗВЕСТЕН" in body["next_ru"]


# ─────────────────────────────────────────────────────────────────────────────
# THE DOOR'S ALLOWANCES (the owner's word 02.09.2026: "give MCP more than the base")
# ─────────────────────────────────────────────────────────────────────────────

def test_the_door_is_actually_wider_than_the_product():
    """Wider — BY COMPARISON with the authority, not by literals in the
    instrument.

    An instrument that repeats the door's numbers would stay green even after
    they were made equal to the product's: it would be checking that a number
    equals itself.
    """
    from kir.mcp import policy
    from kir.sandbox import (DEFAULT_CPU_SECONDS, DEFAULT_MEMORY_MB,
                             DEFAULT_WALL_SECONDS)
    p = policy.author_policy()
    assert p.cpu_seconds > DEFAULT_CPU_SECONDS
    assert p.wall_seconds > DEFAULT_WALL_SECONDS
    assert p.memory_mb > DEFAULT_MEMORY_MB


def test_geometry_libs_are_open_here_and_closable():
    from kir.mcp import policy
    from kir.sandbox import ALLOWED_IMPORTS
    assert "numpy" not in ALLOWED_IMPORTS, "прибор негоден: продукт их уже даёт"
    assert {"numpy", "shapely"} <= set(policy.author_policy().allowed_imports)
    os.environ["KIR_MCP_GEOMETRY_LIBS"] = "0"
    try:
        assert "numpy" not in policy.author_policy().allowed_imports, (
            "выключатель не выключает — послабление без обратного хода")
    finally:
        os.environ.pop("KIR_MCP_GEOMETRY_LIBS", None)


def test_the_latitudes_reach_the_model():
    """An allowance the model doesn't know about spends a turn on reconnaissance."""
    from kir.mcp import surface
    text = surface.instructions()
    assert "ДОПУЩЕНИЯ ЭТОЙ ДВЕРИ" in text
    assert "geometry_libs" in text and "confirm_scope" in text


def test_confirm_off_writes_without_asking(revit, writing, monkeypatch):
    monkeypatch.setenv("KIR_MCP_CONFIRM", "off")
    opened, _ = _call("kir_open", {})
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": _program()})
    assert body["ok"] and body["wrote_nothing"] is False
    assert len(revit.writes) == 1


def test_confirm_session_asks_once_per_handle(revit, writing, monkeypatch):
    """Consent is held BY A HANDLE: one document, its lifetime is not "forever"."""
    monkeypatch.setenv("KIR_MCP_CONFIRM", "session")
    opened, _ = _call("kir_open", {})
    program = _program()
    first, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})
    assert live.INPUT_REQUIRED in first, "первый раз обязан спросить"
    ok1, _ = _call("kir_write", {"building": opened["building"], "program": program},
                   confirmed=True, state=first[live.INPUT_REQUIRED]["state"])
    assert ok1["ok"] and len(revit.writes) == 1

    again, _ = _call("kir_write", {"building": opened["building"],
                                   "program": program})
    assert live.INPUT_REQUIRED not in again, "второй раз спросил при scope=session"
    assert again["ok"] and len(revit.writes) == 2

    # A NEW HANDLE — NEW CONSENT: otherwise "for the session" would mean
    # "forever".
    other, _ = _call("kir_open", {})
    fresh, _ = _call("kir_write", {"building": other["building"], "program": program})
    assert live.INPUT_REQUIRED in fresh, "согласие пережило свою ручку"


def test_off_is_the_default_and_asking_is_opt_in(revit, writing, monkeypatch):
    """The `off` default is the owner's decision from 03.09.2026, and it is
    checked.

    The second half of the instrument matters just as much: a retired default is
    not a retired capability. "The host turned confirmation on" is required to
    work, otherwise the decision would have been a removal of the mechanism, not
    a change of default.
    """
    from kir.mcp import policy

    monkeypatch.delenv("KIR_MCP_CONFIRM", raising=False)
    assert policy.confirm_scope() == "off"
    opened = _call("kir_open", {})[0]
    program = _program()
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": program})
    assert live.INPUT_REQUIRED not in body, "спросил при умолчании off"
    assert body["ok"] and len(revit.writes) == 1

    monkeypatch.setenv("KIR_MCP_CONFIRM", "call")
    assert policy.confirm_scope() == "call"
    ask, _ = _call("kir_write", {"building": opened["building"],
                                 "program": program})
    assert live.INPUT_REQUIRED in ask, "хозяин включил вопрос, а его не задали"
    assert len(revit.writes) == 1, "вопрос задан, а записал всё равно"
    done, _ = _call("kir_write", {"building": opened["building"], "program": program},
                    confirmed=True, state=ask[live.INPUT_REQUIRED]["state"])
    assert done["ok"] and len(revit.writes) == 2


# ─────────────────────────────────────────────────────────────────────────────
# FIXES FROM THE 02.09.2026 REVIEW. Every instrument below reproduces a SCENARIO.
# ─────────────────────────────────────────────────────────────────────────────

class _Switching(_FakeRevit):
    """A host where the person switches windows between the question and the
    answer."""

    async def read(self, csharp, *, timeout_ms):
        self.reads.append(csharp)
        return {"title": self.title, "version": self.version, "path": ""}


def test_a_document_switched_between_ask_and_answer_refuses(writing, asking):
    """🔴 THE REVIEW'S MAIN FINDING. Confirmed "A.rvt" — would have written to
    "B.rvt".

    The fingerprint in the handle was set up for exactly this ("notice the
    mismatch instead of writing blind," header of `handles.py`) and had NEVER
    BEEN CHECKED. This house already paid for the same shape by reading, when the
    admin door picked up the wrong title on two open Revit instances; here the
    price would have been a write.
    """
    host = _Switching()
    ports.register(ports.MCP_REVIT, lambda: host)
    handles._reset_for_tests()
    try:
        opened, _ = _call("kir_open", {})
        program = _program()
        ask, _ = _call("kir_write", {"building": opened["building"],
                                     "program": program})
        assert "Проект1.rvt" in ask[live.INPUT_REQUIRED]["message"]

        host.title = "Другой.rvt"          # the person switched windows
        body, _ = _call("kir_write", {"building": opened["building"],
                                      "program": program},
                        confirmed=True, state=ask[live.INPUT_REQUIRED]["state"])
        assert body["err"]["code"] == "document_changed"
        assert "Другой.rvt" in body["err"]["message_ru"]
        assert host.writes == [], "запись ушла в ЧУЖОЙ документ"
    finally:
        ports.unregister(ports.MCP_REVIT)
        handles._reset_for_tests()


def test_the_human_sees_destructive_kinds_not_zero_elements():
    """500 deletions are required to look like 500 deletions, not like "0
    elements"."""
    summary = live.write_summary(
        {"ops": [{"op": "delete", "id": f"d{i}",
                  "target": {"by": "element_id", "value": i}}
                 for i in range(500)]})
    assert summary["writing_ops"] == 500
    assert summary["kinds"] == {"delete": 500}
    assert "delete×500" in summary["kinds_ru"]


def test_a_malformed_request_state_is_a_refusal_not_a_crash(revit, writing, asking):
    """`requestState` comes from someone else's JSON and can be anything at all.

    The previous code called `.get` on a list, caught an AttributeError, and
    turned a CLEAN refusal into "the server broke" — that is, into a category
    that reads as our own defect rather than as a confirmation mismatch.
    """
    opened, _ = _call("kir_open", {})
    for bad in ([1], "строка", 42, None):
        body, crashed = _call("kir_write",
                              {"building": opened["building"],
                               "program": _program()},
                              confirmed=True, state=bad)
        assert not crashed, f"состояние {bad!r} уронило сервер"
        assert body["err"]["code"] == "confirmation_mismatch"
    assert revit.writes == []


def test_both_halves_of_the_digest_message_are_comparable(revit, writing, asking):
    """A reader cannot verify a comparison whose two halves are of different
    length."""
    opened, _ = _call("kir_open", {})
    body, _ = _call("kir_write", {"building": opened["building"],
                                  "program": _program()},
                    confirmed=True,
                    state={"building": opened["building"], "digest": "f" * 64})
    left, right = body["err"]["message_ru"].split(" против ")
    assert left.rstrip("… ").endswith("f" * 12)
    assert len(right.strip().rstrip("…")) == 12


def test_the_mrtr_fields_are_asserted_at_build_time():
    """The absence of a mechanism is required to be loud and happen ONCE, not
    quiet and on every turn: a lenient `getattr` was buying an endless
    confirmation loop."""
    pytest.importorskip("mcp_types", reason="дополнение [mcp] не поставлено")
    import mcp_types as t
    for field in ("input_responses", "request_state"):
        assert field in t.CallToolRequestParams.model_fields
