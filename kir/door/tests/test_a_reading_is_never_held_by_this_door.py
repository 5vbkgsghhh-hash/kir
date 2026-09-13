"""The new door must not acquire the defect the old one had.

🔴 THE DEFECT, MEASURED ON A LIVE TURN 13.09.2026 21:10Z. The product's door
held a program of four `query_types` — a pure READING — at «Одобрить» in the
KIR window. The hold asked "is there a plan", never "does it write". The
reading waited for a human; the model did not wait and built by defaults
blindly. Fixed in `kir/serving.py` (`_plan_writes`), and this file makes sure
the door built after it cannot repeat it.

THE LAW, stated once: **only a tool that writes may ever wait for a human.**
`kir_read` writes nothing, therefore it never waits, therefore it needs
neither an executor nor an approval.
"""
from __future__ import annotations

from kir.door import registry as R
from kir.door.read import kir_read

#: Any key by which an answer could say "I am waiting for a person".
HOLD_MARKS = ("held_in_kir", "held", "awaiting_approval", "approval_required",
              "stage")


def _reading_answers() -> list[dict]:
    """Every reading this door can answer offline, plus its refusals: a
    refusal that quietly waits is the same defect wearing a different word."""
    expert = R.Ctx(role="expert")
    return [
        kir_read({"what": "language"}, expert),
        kir_read({"what": "language", "section": "КР"}, expert),
        kir_read({"what": "help", "op": "create_wall"}, expert),
        kir_read({"what": "level_plan"}, expert),
        kir_read({"what": "building"}, expert),
        kir_read({}, expert),
        R.call("kir_read", {"what": "language"}, expert),
        R.call("kir_read", {"what": "building"}, R.Ctx(role="lead")),
    ]


def test_no_reading_answer_carries_a_hold():
    for answer in _reading_answers():
        for mark in HOLD_MARKS:
            assert mark not in answer, (mark, answer)
        assert answer.get("waiting") is not True


def test_a_reading_needs_no_executor_at_all():
    """The live defect was a reading that could not proceed. A reading that
    depends on an executor is a reading that can be made to wait."""
    ctx = R.Ctx(role="expert", executor=None)
    answer = kir_read({"what": "language", "section": "АР"}, ctx)
    assert answer["ok"] is True and answer["text"].strip()


def test_the_reading_tool_is_declared_as_not_writing():
    read = R.tool("kir_read")
    assert read.reads is True and read.writes is False


def test_only_a_writing_tool_may_ever_wait():
    """The law as a set, not as a habit: of the six records, exactly one
    writes, and it is the only one a human may be asked about."""
    writers = {t.name for t in R.TOOLS if t.writes}
    assert writers == {"kir_build"}
    for t in R.TOOLS:
        if t.writes:
            continue
        assert t.name != "kir_build"


def test_a_reading_refusal_still_names_a_move_and_does_not_wait():
    """`level_plan` has no carrier yet (op `query_level_plan`, N). It refuses
    BY NAME and hands over a move — it does not park the turn."""
    out = kir_read({"what": "level_plan"}, R.Ctx(role="expert"))
    assert out["ok"] is False
    assert out["err"]["code"] == "no_level_plan_op"
    assert out["next"]["do"] in {t.name for t in R.TOOLS}
    assert out.get("waiting") is not True


def test_preview_is_the_only_way_a_build_writes_nothing_and_it_says_so():
    """A build asked to preview must be explicit, not silently held: the
    difference between «показано» and «построено» is what the human approves."""
    from kir.project_pack import OfflineExecutor

    ctx = R.Ctx(role="expert", executor=OfflineExecutor())
    src = 'program = [create_level(id="L1", elev_mm=0, name="Этаж 1")]'
    out = R.call("kir_build", {"source": src, "preview": True}, ctx)
    assert out["built"] is False and out["wrote_nothing"] is True
    assert "не записано" in out["words"]


def test_control_marking_the_reading_as_writing_goes_red():
    read = R.tool("kir_read")
    assert read.writes is False
    # If someone flips it, `test_only_a_writing_tool_may_ever_wait` breaks,
    # because the set of writers would stop being exactly {kir_build}.
    pretend_writers = {t.name for t in R.TOOLS if t.writes} | {"kir_read"}
    assert pretend_writers != {"kir_build"}
