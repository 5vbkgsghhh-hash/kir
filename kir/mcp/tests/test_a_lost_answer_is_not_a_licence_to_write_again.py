"""E6: A LOST RESPONSE IS NOT PERMISSION TO WRITE AGAIN.

Measured before the fix (public door, fake transport): `kir_write` went
out, the transport failed AFTER dispatch, the same `kir_write` repeated —
`writes=2, ok=True`. A second element in the model, and not one carrier
that would notice it; the `next_ru` text "read the model" was the only
obstacle, and text stops nothing.

THE BOUNDARY OF HONESTY. There is no Revit here. What is real is the
public dispatcher (`server.dispatch`), the real compiler inside the door,
and the real receipt check; the transport is fake and COUNTS dispatches.
"Loss of response" is an exception raised AFTER the dispatch is counted:
the send happened, there is no response.

WHAT THIS PIN DOES NOT ASSERT: that the marker survives a server restart.
It lives in the handle, and the handle lives in the process's memory, ON
PURPOSE (`handles.py`). After a restart the old handle is rejected
outright, so a blind repeat never reaches it; the remainder — a new
`kir_open` after a restart — is named in `live.py` at `UNRESOLVED` and is
not closed.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir import ports
from kir.mcp import handles, live, server

PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]}
OTHER = {"ops": [{"op": "create_level", "id": "L2", "elev_mm": 3000}]}
RECEIPT = {"ok": True, "L": {"id": "123456"}}
RECEIPT_OTHER = {"ok": True, "L2": {"id": "123457"}}


class Transport:
    """Counts dispatches. `lose` — the numbers of dispatches whose response is lost."""

    def __init__(self, lose=(), title="D1.rvt"):
        self.writes = 0
        self.lose = set(lose)
        self.title = title

    async def read(self, _source, *, timeout_ms):
        return {"title": self.title, "version": "2026", "path": f"C:/{self.title}"}

    async def write(self, source, *, timeout_ms):
        self.writes += 1
        if self.writes in self.lose:
            raise TimeoutError("ответ потерян: мост оборвался после отправки")
        return copy.deepcopy(RECEIPT_OTHER if "L2" in source else RECEIPT)


@pytest.fixture
def wired(monkeypatch):
    """A door with a fake transport; write confirmation is lifted by the operator."""
    made = []

    def install(transport):
        ports.register(ports.MCP_REVIT, lambda: transport)
        made.append(transport)
        return transport

    monkeypatch.setenv(live.WRITE_FLAG, "on")
    monkeypatch.setenv("KIR_MCP_CONFIRM", "off")
    handles._reset_for_tests()
    try:
        yield install
    finally:
        if made:
            ports.unregister(ports.MCP_REVIT)
        handles._reset_for_tests()


def call(name, args, **kw):
    body, crashed = asyncio.run(server.dispatch(name, args, **kw))
    assert not crashed, body
    return body


def opened():
    body = call("kir_open", {})
    assert body["ok"], body
    return body["building"]


def ask_of(body):
    return body.get(live.INPUT_REQUIRED) if isinstance(body, dict) else None


def test_a_repeat_after_a_lost_answer_does_not_reach_the_host(wired):
    transport = wired(Transport(lose={1}))
    handle = opened()
    first = call("kir_write", {"building": handle, "program": PROGRAM})
    assert first["ok"] is False and first["err"]["code"] == "transport"
    assert first["wrote_nothing"] is False, "исход НЕИЗВЕСТЕН, а не «не писали»"
    assert transport.writes == 1

    repeat = call("kir_write", {"building": handle, "program": PROGRAM})
    ask = ask_of(repeat)
    assert ask is not None, "повтор ушёл в модель молча"
    assert transport.writes == 1, "второй отправки быть не должно"
    assert "НЕИЗВЕСТЕН" in ask["message"]
    # The answer is tied to the OPERATION'S NAME, not to the program's signature.
    pending = live._unresolved_write(handles._REGISTRY[handle].fingerprint,
                                     digest=live.program_digest(PROGRAM))
    assert pending is not None
    assert ask["state"]["unresolved"] == pending["operation_id"]
    assert pending["program_digest"] == live.program_digest(PROGRAM)


def test_a_fresh_handle_does_not_wash_the_unknown_outcome_away(wired):
    """A bypass via one `kir_open` call would cost exactly the same second element."""
    transport = wired(Transport(lose={1}))
    call("kir_write", {"building": opened(), "program": PROGRAM})
    assert transport.writes == 1

    again = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert ask_of(again) is not None
    assert transport.writes == 1


def test_a_different_program_into_the_same_unknown_document_also_stops(wired):
    """What is unknown is the DOCUMENT's state, not one program's."""
    transport = wired(Transport(lose={1}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    other = call("kir_write", {"building": handle, "program": OTHER})
    assert ask_of(other) is not None
    assert transport.writes == 1


def test_declining_the_question_writes_nothing_and_keeps_the_mark(wired):
    transport = wired(Transport(lose={1}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    ask = ask_of(call("kir_write", {"building": handle, "program": PROGRAM}))

    declined = call("kir_write", {"building": handle, "program": PROGRAM},
                    confirmed=False, state=ask["state"])
    assert declined["ok"] is True and declined["wrote_nothing"] is True
    assert declined["declined"] is True
    assert transport.writes == 1
    # The marker is in place: the next attempt asks again, rather than writing.
    assert ask_of(call("kir_write", {"building": handle, "program": PROGRAM})) is not None
    assert transport.writes == 1


def test_an_explicit_resolution_lets_the_next_write_through_once(wired):
    transport = wired(Transport(lose={1}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    ask = ask_of(call("kir_write", {"building": handle, "program": PROGRAM}))

    allowed = call("kir_write", {"building": handle, "program": PROGRAM},
                   confirmed=True, state=ask["state"])
    assert allowed["ok"] is True, allowed
    assert transport.writes == 2
    # The marker is cleared — and cleared ONCE: the next write proceeds
    # normally because its outcome is known, not because the gate got
    # switched off.
    more = call("kir_write", {"building": handle, "program": OTHER})
    assert more["ok"] is True and transport.writes == 3


def test_a_stale_answer_cannot_resolve_a_different_unknown_write(wired):
    """The answer is tied to a SPECIFIC unknown dispatch, not to the door."""
    transport = wired(Transport(lose={1, 3}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    first_ask = ask_of(call("kir_write", {"building": handle, "program": PROGRAM}))
    call("kir_write", {"building": handle, "program": PROGRAM},
         confirmed=True, state=first_ask["state"])          # dispatch 2, has a response
    call("kir_write", {"building": handle, "program": OTHER})  # dispatch 3, response lost
    assert transport.writes == 3

    stale = call("kir_write", {"building": handle, "program": OTHER},
                 confirmed=True, state=first_ask["state"])
    assert ask_of(stale) is not None, "старый ответ снял чужую отметку"
    assert transport.writes == 3


def test_a_known_refusal_is_not_an_unknown_outcome(wired):
    """A refusal BY RECEIPT — the outcome is known; the next write is not delayed."""
    class Refusing(Transport):
        async def write(self, source, *, timeout_ms):
            self.writes += 1
            return {"ok": True}          # D1: success without a typed identity

    transport = wired(Refusing())
    handle = opened()
    refused = call("kir_write", {"building": handle, "program": PROGRAM})
    assert refused["ok"] is False and transport.writes == 1
    following = call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(following) is None, "известный отказ задержал следующую запись"
    assert transport.writes == 2


def test_two_different_writes_still_pass(wired):
    """Anti-Goodhart: a gate that refuses everything would pass the tests above."""
    transport = wired(Transport())
    handle = opened()
    assert call("kir_write", {"building": handle, "program": PROGRAM})["ok"] is True
    assert call("kir_write", {"building": handle, "program": OTHER})["ok"] is True
    assert transport.writes == 2


@pytest.mark.parametrize("receipt", [None, {}, {"state": "running_unknown"},
                                     {"ok": True}])
def test_the_d1_controls_stay_red_with_the_gate_in_place(wired, receipt):
    class Fixed(Transport):
        async def write(self, source, *, timeout_ms):
            self.writes += 1
            return copy.deepcopy(receipt)

    transport = wired(Fixed())
    body = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert transport.writes == 1
    assert body["ok"] is False
    assert body["outcome"]["execution"] in ("unconfirmed", "committed")
    assert body["outcome"]["acceptance"] == "not_run"


def test_the_mark_lives_in_a_durable_file_named_by_the_operator(wired):
    """The link is named so a move breaks LOUDLY, rather than weakening quietly."""
    transport = wired(Transport(lose={1}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    store = live.pending_path()
    assert store is not None and store.is_file(), "durable-записи нет на диске"
    body = json.loads(store.read_text(encoding="utf-8"))
    assert body["schema"] == live.PENDING_SCHEMA
    (record,) = body["records"].values()
    assert record["program_digest"] == live.program_digest(PROGRAM)
    assert record["fingerprint"] == handles._REGISTRY[handle].fingerprint
    assert record["csharp_sha256"] and record["operation_id"]
    assert live._unresolved_write("отпечаток другого документа",
                                  digest="подпись другой программы") is None
    assert transport.writes == 1


# ─────────────────────────────────────────────────────────────────────────────
# Nitpicks from SELF-REVIEW 06.09.2026. Each was RED before its own fix.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_transport_that_cannot_write_leaves_no_mark_behind(wired):
    """b1: a refusal BEFORE dispatch has no right to leave the document
    "unknown."

    It used to be: `transport.write` was read AFTER the marker, and a
    provider without that method locked the document over a dispatch that
    never happened.
    """
    class ReadOnly:
        async def read(self, _source, *, timeout_ms):
            return {"title": "D1.rvt", "version": "2026", "path": "C:/D1.rvt"}

    wired(ReadOnly())
    body = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert body["ok"] is False and body["err"]["code"] == "no_transport"
    assert body["wrote_nothing"] is True
    assert [b.extra.get(live.UNRESOLVED) for b in handles._REGISTRY.values()] == [None]


def test_an_answer_that_says_unknown_keeps_the_mark(wired):
    """b2: an answer arriving ≠ a known outcome.

    `running_unknown` is a receipt that plainly says "I don't know."
    Clearing the marker on it would mean treating the word "I don't know"
    as the answer "all is well"; before the fix this gave `writes=2` on
    the same document.
    """
    class Unknown(Transport):
        async def write(self, source, *, timeout_ms):
            self.writes += 1
            return {"ok": True, "state": "running_unknown", "L": {"id": "1"}}

    transport = wired(Unknown())
    handle = opened()
    first = call("kir_write", {"building": handle, "program": PROGRAM})
    assert first["outcome"]["execution"] == "unconfirmed"
    assert transport.writes == 1
    again = call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(again) is not None, "неизвестный исход не задержал следующую запись"
    assert transport.writes == 1


def test_concurrent_writes_into_one_document_send_once(wired):
    """b3: the window between checking the marker and setting it is closed
    structurally.

    Between them there stood an `await` (the document check), meaning the
    event loop was entitled to let a second call in. A control inside the
    test shows the window is REAL: with the gate disarmed, the same four
    calls give four dispatches.
    """
    class Yielding(Transport):
        async def read(self, _source, *, timeout_ms):
            await asyncio.sleep(0)
            return {"title": self.title, "version": "2026", "path": f"C:/{self.title}"}

        async def write(self, source, *, timeout_ms):
            self.writes += 1
            await asyncio.sleep(0.01)
            raise TimeoutError("ответ потерян")

    async def four(handle):
        await asyncio.gather(*[server.dispatch(
            "kir_write", {"building": handle, "program": PROGRAM}) for _ in range(4)])

    transport = wired(Yielding())
    asyncio.run(four(opened()))
    assert transport.writes == 1, "две отправки в один документ разом"

    # Control: without the gate, the window gives four dispatches —
    # meaning the test is not a tautology.
    gate = live._blocking_records
    live._blocking_records = lambda records, *, fingerprint, digest: {}
    try:
        handles._reset_for_tests()
        transport.writes = 0
        asyncio.run(four(opened()))
        assert transport.writes == 4
    finally:
        live._blocking_records = gate


def test_a_renamed_document_no_longer_walks_away_from_the_mark(wired):
    """b4 CLOSED (round 3): the record is looked up by TWO keys, not one.

    The fingerprint `sha256(title\\0version\\0path)` changes on a rename
    and on `Save As` — it is not the document's identity (audit E:
    D2/F6). So the durable record also carries the program's signature,
    and a repeat of THE SAME program after a rename is still blocked.
    """
    transport = wired(Transport(lose={1}))
    call("kir_write", {"building": opened(), "program": PROGRAM})
    assert transport.writes == 1
    transport.title = "D1-renamed.rvt"
    body = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert ask_of(body) is not None, "переименование увело от записи"
    assert transport.writes == 1


# ─────────────────────────────────────────────────────────────────────────────
# ROUND 3: operation identity in the port's contract. A durable record
# survives a server restart, and a host with `lookup` resolves the
# question without a human.
# ─────────────────────────────────────────────────────────────────────────────

#: The tree's root — from ITS OWN file (kir/mcp/tests → 3 levels up), not
#: as a machine-specific literal.
_TREE = Path(__file__).resolve().parents[3]

_RESTART = '''
import asyncio, json, os, sys
sys.path.insert(0, os.environ["KIR_TEST_ROOT"])  # корень — от теста, не от машины
os.environ["KIR_MCP_WRITE"] = "on"
os.environ["KIR_MCP_CONFIRM"] = "off"
os.environ["KIR_MCP_PENDING_DIR"] = sys.argv[1]
from kir import ports
from kir.mcp import handles, live, server

PROGRAM = json.loads(sys.argv[2])

class Fresh:
    writes = 0
    async def read(self, _s, *, timeout_ms):
        return {"title": sys.argv[3], "version": "2026", "path": "C:/" + sys.argv[3]}
    async def write(self, _s, *, timeout_ms, operation_id=None):
        Fresh.writes += 1
        return {"ok": True, "L": {"id": "9"}}

ports.register(ports.MCP_REVIT, lambda: Fresh())
opened, _ = asyncio.run(server.dispatch("kir_open", {}))
body, _ = asyncio.run(server.dispatch(
    "kir_write", {"building": opened["building"], "program": PROGRAM}))
print(json.dumps({"asks": live.INPUT_REQUIRED in body, "writes": Fresh.writes,
                  "handles": handles.count()}))
'''


def _second_process(pending_dir, program, title="D1.rvt"):
    """A GENUINE second process: it has neither the handles nor the memory of the first."""
    out = subprocess.run(
        [sys.executable, "-c", _RESTART, str(pending_dir), json.dumps(program), title],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
             "KIR_TEST_ROOT": str(_TREE)})
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_refusal_survives_a_restart_of_the_server(wired, mcp_pending_dir):
    """A restart is not a pardon: the record is durable and outlives the process."""
    transport = wired(Transport(lose={1}))
    call("kir_write", {"building": opened(), "program": PROGRAM})
    assert transport.writes == 1
    fresh = _second_process(mcp_pending_dir, PROGRAM)
    assert fresh["handles"] == 1, "второй процесс должен был начать с нуля"
    assert fresh["asks"] is True, "после перезапуска повтор ушёл в модель"
    assert fresh["writes"] == 0


def test_a_resolved_write_does_not_haunt_the_next_process(wired, mcp_pending_dir):
    """Control: a known outcome clears the record, and a restart does NOT delay a write."""
    transport = wired(Transport())
    assert call("kir_write", {"building": opened(), "program": PROGRAM})["ok"] is True
    assert transport.writes == 1
    fresh = _second_process(mcp_pending_dir, PROGRAM)
    assert fresh["asks"] is False and fresh["writes"] == 1


def test_a_host_that_can_look_up_resolves_without_asking_a_human(wired):
    """A host that can name an operation's outcome resolves the question itself."""
    class Lookup(Transport):
        def __init__(self):
            super().__init__(lose={1})
            self.asked = []
            self.answer = {"ok": True, "L": {"id": "777"}}

        async def write(self, source, *, timeout_ms, operation_id=None):
            self.writes += 1
            self.sent = operation_id
            if self.writes in self.lose:
                raise TimeoutError("ответ потерян")
            return copy.deepcopy(RECEIPT_OTHER if "L2" in source else RECEIPT)

        async def lookup(self, operation_id):
            self.asked.append(operation_id)
            return copy.deepcopy(self.answer)

    transport = wired(Lookup())
    handle = opened()
    first = call("kir_write", {"building": handle, "program": PROGRAM})
    assert first["ok"] is False and transport.writes == 1
    assert transport.sent, "имя операции хозяину не отдано"

    again = call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(again) is None, "человека спросили при живом lookup"
    assert again["ok"] is True and again["recovered"] is True
    assert again["operation_id"] == transport.sent
    assert transport.asked == [transport.sent]
    assert transport.writes == 1, "восстановление сделало вторую отправку"
    # The record is cleared: the next write proceeds normally.
    assert call("kir_write", {"building": handle, "program": OTHER})["ok"] is True
    assert transport.writes == 2


def test_a_lookup_that_proves_it_never_started_lets_the_write_through(wired):
    """`None` from lookup is the PROVEN "did not start," and nothing else."""
    class NeverStarted(Transport):
        def __init__(self):
            super().__init__(lose={1})

        async def write(self, source, *, timeout_ms, operation_id=None):
            self.writes += 1
            if self.writes in self.lose:
                raise TimeoutError("ответ потерян")
            return copy.deepcopy(RECEIPT)

        async def lookup(self, operation_id):
            return None

    transport = wired(NeverStarted())
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    body = call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(body) is None and body["ok"] is True
    assert transport.writes == 2, "доказанное «не начиналась» обязано пропустить"


@pytest.mark.parametrize("answer,asks", [
    ({"state": "running_unknown"}, True),      # the host does not know — the question remains
    ("не квитанция", True),                    # garbage is also unknown
])
def test_a_lookup_that_does_not_know_keeps_the_question(wired, answer, asks):
    class Vague(Transport):
        def __init__(self):
            super().__init__(lose={1})

        async def write(self, source, *, timeout_ms, operation_id=None):
            self.writes += 1
            raise TimeoutError("ответ потерян")

        async def lookup(self, operation_id):
            return copy.deepcopy(answer) if isinstance(answer, dict) else answer

    transport = wired(Vague())
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    body = call("kir_write", {"building": handle, "program": PROGRAM})
    assert bool(ask_of(body)) is asks
    assert transport.writes == 1


def test_a_lookup_that_throws_is_not_an_answer(wired):
    class Broken(Transport):
        def __init__(self):
            super().__init__(lose={1})

        async def write(self, source, *, timeout_ms, operation_id=None):
            self.writes += 1
            raise TimeoutError("ответ потерян")

        async def lookup(self, operation_id):
            raise RuntimeError("журнал недоступен")

    transport = wired(Broken())
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(call("kir_write", {"building": handle, "program": PROGRAM})) is not None
    assert transport.writes == 1


def test_a_host_without_operation_id_still_gets_a_durable_record(wired):
    """An old host works as before — but the record is durable regardless."""
    transport = wired(Transport(lose={1}))          # write(csharp, *, timeout_ms)
    assert live._writer_takes_operation_id(transport.write) is False
    handle = opened()
    body = call("kir_write", {"building": handle, "program": PROGRAM})
    assert body["err"]["code"] == "transport" and transport.writes == 1
    store = live.pending_path()
    (record,) = json.loads(store.read_text(encoding="utf-8"))["records"].values()
    assert record["operation_id_sent"] is False
    assert ask_of(call("kir_write", {"building": handle, "program": PROGRAM})) is not None
    assert transport.writes == 1


def test_a_host_that_takes_kwargs_is_recognised(wired):
    async def flexible(csharp, **kwargs):
        return copy.deepcopy(RECEIPT)

    assert live._writer_takes_operation_id(flexible) is True


def test_an_unwritable_store_refuses_before_any_effect(wired, monkeypatch, tmp_path):
    """No directory — no promise that "a repeat will not duplicate" — so no write either."""
    transport = wired(Transport())
    blocked = tmp_path / "нет-прав"
    # A file cannot contain the store directory, even for a root test process.
    # chmod(0500) is not an unwritable-path fixture when root bypasses DAC.
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(live.PENDING_DIR_ENV, str(blocked / "mcp"))
    body = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert body["ok"] is False and body["err"]["code"] == "pending_store"
    assert body["wrote_nothing"] is True
    assert transport.writes == 0, "отказ обязан быть ПРЕД-эффектным"
    assert "KIR_MCP_PENDING_DIR" in body["next_ru"]


# ─────────────────────────────────────────────────────────────────────────────
# ROUND 4: the write directory belongs to the USER, not to the host.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_pypi_like_install_writes_without_any_configuration(wired, monkeypatch, tmp_path):
    """A stranger's environment: no `KIR_INSTALL_ROOT`, no marker, none of
    our env variables.

    Before round 4 the door refused here by default — that is, it
    demanded of that very "stranger who installs it and builds" a setup
    they know nothing about.
    """
    monkeypatch.delenv(live.PENDING_DIR_ENV, raising=False)
    monkeypatch.delenv("KIR_INSTALL_ROOT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    transport = wired(Transport(lose={1}))
    handle = opened()
    body = call("kir_write", {"building": handle, "program": PROGRAM})
    assert body["err"]["code"] == "transport" and transport.writes == 1

    store = tmp_path / "share" / "kir" / "mcp" / "pending_writes.json"
    assert store.is_file(), "durable-запись не легла в каталог пользователя"
    assert live.pending_path() == store
    assert oct(store.parent.stat().st_mode)[-3:] == "700"
    (record,) = json.loads(store.read_text(encoding="utf-8"))["records"].values()
    assert record["program_digest"] == live.program_digest(PROGRAM)
    # And the gate works out of this directory the same way: a repeat asks again.
    assert ask_of(call("kir_write", {"building": handle, "program": PROGRAM})) is not None
    assert transport.writes == 1


def test_the_host_tree_is_never_used_for_this_record(monkeypatch, tmp_path):
    """The LANGUAGE's data is not placed inside the PRODUCT's tree — the boundary of three projects."""
    monkeypatch.delenv(live.PENDING_DIR_ENV, raising=False)
    monkeypatch.setenv("KIR_INSTALL_ROOT", str(tmp_path / "kukai-tree"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    resolved = live.pending_path()
    assert str(tmp_path / "kukai-tree") not in str(resolved)
    assert resolved == tmp_path / "share" / "kir" / "mcp" / "pending_writes.json"
    # Control: the host authority DOES have a directory — and it is still not taken.
    from kir.install_paths import install_data_path
    assert install_data_path("mcp") == tmp_path / "kukai-tree" / "backend" / "data" / "mcp"


def test_the_operator_override_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv(live.PENDING_DIR_ENV, str(tmp_path / "мой-каталог"))
    assert live.pending_path() == tmp_path / "мой-каталог" / "pending_writes.json"


def test_without_a_home_the_door_names_the_reason(monkeypatch):
    monkeypatch.delenv(live.PENDING_DIR_ENV, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "")
    with pytest.raises(live.PendingStoreError, match="HOME"):
        live.pending_path()


def test_a_corrupt_store_is_a_refusal_not_an_empty_store(wired):
    """A corrupted file is "the outcome is unknown all the more," not "no records."""
    transport = wired(Transport())
    store = live.pending_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{не json", encoding="utf-8")
    body = call("kir_write", {"building": opened(), "program": PROGRAM})
    assert body["err"]["code"] == "pending_store" and transport.writes == 0


def test_removing_the_durable_record_makes_the_gate_red(wired):
    """MUTATION: clear the record — and a repeat goes back into the model."""
    transport = wired(Transport(lose={1}))
    handle = opened()
    call("kir_write", {"building": handle, "program": PROGRAM})
    assert ask_of(call("kir_write", {"building": handle, "program": PROGRAM})) is not None
    assert transport.writes == 1
    live.pending_path().unlink()                     # exactly what the mutation does
    assert call("kir_write", {"building": handle, "program": PROGRAM})["ok"] is True
    assert transport.writes == 2
