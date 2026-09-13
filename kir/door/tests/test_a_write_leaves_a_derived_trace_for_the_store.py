"""A write leaves a DERIVED trace, in a form W can put into the store.

This is the precondition for moving ДОК-C4's twenty tests (`writes 2 → 1`,
survives a server restart) from `kir_write` to `kir_build`. The door does NOT
grow a store of its own — `kir/mcp/live.py` says why in its own header — so the
trace has to be complete enough that somebody else can persist it without
parsing our internals.
"""
from __future__ import annotations

from kir.door import registry as R
from kir.door.build import TRACE_SCHEMA, TRACE_STATES, kir_build

SOURCE = 'program = [create_level(id="L1", elev_mm=0, name="Этаж 1")]'
BAD_SOURCE = 'program = [create_wall(id="W1")]'


def _ctx(**kw):
    from kir.project_pack import OfflineExecutor

    base = dict(role="expert", executor=OfflineExecutor(), turn_id="t7",
                tool_call_id="c3", document_fingerprint="doc-abc")
    base.update(kw)
    return R.Ctx(**base)


def test_a_committed_write_carries_the_whole_trace():
    out = kir_build({"source": SOURCE}, _ctx())
    trace = out["trace"]
    assert trace["schema"] == TRACE_SCHEMA == "kir-door-write-trace/1"
    assert set(trace) == {"schema", "operation_id", "document_fingerprint",
                          "program_digest", "state", "attempt", "resolved_by"}
    assert trace["state"] == "committed"
    assert trace["resolved_by"] == "answer"
    assert trace["attempt"] == 1


def test_the_operation_id_is_derived_and_therefore_stable_on_repeat():
    """🔴 A RANDOM id GIVES A SECOND EFFECT ON REPEAT. The product's bridge
    says it in its own words: a replay must "reconcile or return unknown,
    never acquire a fresh random operation id and execute twice"."""
    first = kir_build({"source": SOURCE}, _ctx())["trace"]
    second = kir_build({"source": SOURCE}, _ctx())["trace"]
    assert first["operation_id"] == second["operation_id"]
    assert first["program_digest"] == second["program_digest"]


def test_a_different_program_gets_a_different_operation_id():
    same_turn = _ctx()
    one = kir_build({"source": SOURCE}, same_turn)["trace"]
    other_src = 'program = [create_level(id="L2", elev_mm=3000, name="Этаж 2")]'
    other = kir_build({"source": other_src}, same_turn)["trace"]
    assert one["operation_id"] != other["operation_id"]
    assert one["program_digest"] != other["program_digest"]


def test_a_different_turn_gets_a_different_operation_id():
    one = kir_build({"source": SOURCE}, _ctx(turn_id="t7"))["trace"]
    two = kir_build({"source": SOURCE}, _ctx(turn_id="t8"))["trace"]
    assert one["operation_id"] != two["operation_id"]


def test_the_pair_the_store_searches_by_travels_in_the_receipt():
    """`kir/mcp/live.py::_blocking_records(records, fingerprint=…, digest=…)`
    searches by exactly this pair. Both halves must be IN the receipt, or W
    cannot persist the trace without reading our internals."""
    trace = kir_build({"source": SOURCE}, _ctx())["trace"]
    assert trace["document_fingerprint"] == "doc-abc"
    assert isinstance(trace["program_digest"], str)
    assert len(trace["program_digest"]) >= 32


def test_a_lost_answer_is_unknown_and_unknown_is_legal():
    """ДОК-A18: a door answered `started: true` twice and produced nothing —
    «ложно-зелёная квитанция». A receipt must be able to say "I do not know"
    and still be a receipt."""
    class Lost:
        def execute(self, link_key, program):  # noqa: D102
            raise TimeoutError("ответа не было")

    out = kir_build({"source": SOURCE}, _ctx(executor=Lost()))
    assert out["ok"] is False
    assert out["trace"]["state"] == "unknown"
    assert out["trace"]["resolved_by"] is None
    assert "unknown" in TRACE_STATES


def test_nothing_dispatched_is_refused_pre_effect():
    no_executor = kir_build({"source": SOURCE}, _ctx(executor=None))
    assert no_executor["ok"] is False
    assert no_executor["trace"]["state"] == "refused_pre_effect"


def test_a_program_that_never_existed_has_no_trace_at_all():
    """🔴 AN IDENTITY OF WHAT? A source the sandbox refused produced no
    program, so there is nothing to derive an `operation_id` FROM. An empty
    trace here would be an identity for a program that does not exist — the
    same class as a receipt that says `started: true` and means nothing."""
    refused = kir_build({"source": BAD_SOURCE}, _ctx())
    assert refused["ok"] is False
    assert "trace" not in refused
    assert refused["next"]["do"] in {t.name for t in R.TOOLS}


def test_an_executor_that_says_it_wrote_nothing_is_believed():
    """Only an EXPLICIT «ничего не записано» earns `refused_pre_effect`;
    silence about the effect is `unknown`, not optimism."""
    class Refuses:
        def __init__(self, extra):
            self.extra = extra

        def execute(self, link_key, program):  # noqa: D102
            return {"ok": False, "message_ru": "отказ", **self.extra}

    said = kir_build({"source": SOURCE}, _ctx(executor=Refuses({"wrote_nothing": True})))
    assert said["trace"]["state"] == "refused_pre_effect"
    silent = kir_build({"source": SOURCE}, _ctx(executor=Refuses({})))
    assert silent["trace"]["state"] == "unknown"


def test_the_attempt_counter_is_carried_so_a_repeat_is_provable():
    """`attempt` and `resolved_by` are what make the migration of the twenty
    tests checkable: they tell "handed back the SAME receipt" from "went out a
    second time"."""
    second = kir_build({"source": SOURCE}, _ctx(attempt=2))
    assert second["trace"]["attempt"] == 2


def test_only_the_three_named_states_exist():
    assert TRACE_STATES == ("committed", "unknown", "refused_pre_effect")


def test_the_build_schema_did_not_grow_for_this():
    """G1 is untouched: the trace lives in the RECEIPT, never in the input."""
    import json

    schema = R.tool("kir_build").schema("expert")
    size = len(json.dumps(schema, ensure_ascii=False).encode())
    assert size <= 700
    assert "trace" not in schema["properties"]
