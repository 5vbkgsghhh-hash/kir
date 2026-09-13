"""A READING is never held at the window. Only a write waits for a human.

🔴 BOUGHT BY A LIVE TURN, 13.09.2026 21:10Z, owner's device. The model first
sent a program of four `query_types` and nothing else — a pure reading. The
product HELD it at «Одобрить» in the KIR window: the hold asked only "is
there a plan", never "does it write". The reading waited for a human's word;
the model did not wait and built by defaults BLINDLY.

Reading is the cheapest move an agent has for not guessing. Holding it turns
the cheap move into the expensive one and then punishes the agent for
skipping it.
"""
from __future__ import annotations

import inspect

import pytest

from kir import serving
from kir.compiler import plan_program
from kir.midend import ProgramFamily

QUERY_OPS = [{"op": "query_types", "pool": "wall_types"}] * 4
WRITE_OPS = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "Этаж 1"}]


def _plan(ops: list) -> object:
    return plan_program({"ir_version": "1.0", "ops": ops})


def test_the_language_has_exactly_two_families():
    """The binary is the reason the mixed case needs no policy of ours."""
    assert {m.value for m in ProgramFamily} == {"query", "write"}


def test_a_reading_plan_does_not_write():
    plan = _plan(QUERY_OPS)
    assert plan.family is ProgramFamily.QUERY
    assert serving._plan_writes(plan) is False


def test_a_writing_plan_writes():
    plan = _plan(WRITE_OPS)
    assert plan.family is ProgramFamily.WRITE
    assert serving._plan_writes(plan) is True


def test_an_unreadable_plan_counts_as_writing():
    """The two errors are not the same size: holding a reading costs a delay,
    not holding a write puts an unapproved change into the document. So doubt
    means hold."""
    class Opaque:
        def __getattr__(self, name):  # noqa: D105
            raise RuntimeError("opaque")

    assert serving._plan_writes(Opaque()) is True
    assert serving._plan_writes(None) is True
    assert serving._plan_writes({}) is True


def test_the_hold_branch_asks_whether_the_plan_writes():
    """The guard itself, read from the source.

    The branch returns BEFORE any execution and is only reachable with a live
    turn context, an admitted device and the flag; the CHEAP way to hold the
    decision is to require the question to be in the guard. Its control is
    real: delete the call and this goes red.
    """
    # The branch lives in `_handle_revit_ir_inner`, where `handle_revit_ir`
    # routes; the test reads the whole module so a move between the two does
    # not silently pass.
    source = inspect.getsource(serving)
    guards = [line for line in source.splitlines()
              if "_kir_hold_active()" in line
              and not line.lstrip().startswith(("def ", "return ", "#"))]
    assert guards, "ветвь удержания исчезла из kir/serving.py"
    for line in guards:
        assert "_plan_writes(" in line, (
            "удержание не спрашивает, пишет ли программа: "
            "чтение снова будет ждать человека — " + line.strip())


def test_a_mixed_program_is_refused_by_the_language_with_a_next_move():
    """🔴 THE MIXED CASE IS NOT OURS TO DECIDE. The compiler already refuses a
    mix by name, before the hold is reached, and the refusal carries exactly
    the move the agent needs — so there is no writing half to hold inside a
    reading program, and no policy for us to invent."""
    from kir.diag import KirRefusal

    with pytest.raises(KirRefusal) as caught:
        _plan(QUERY_OPS + WRITE_OPS)
    text = str(caught.value)
    assert "KIR-L002" in text
    assert "смешение query и write" in text
    assert "СЛЕДУЮЩИЙ ХОД" in text
    # the next move is "ask the readings in a separate turn", not a variable
    assert "ОТДЕЛЬНЫМ ходом" in text


def test_control_the_old_guard_would_have_held_a_reading():
    """The defect, reproduced as arithmetic: the condition that shipped asked
    only whether a plan existed."""
    plan = _plan(QUERY_OPS)
    held_by_old_guard = plan is not None
    held_by_new_guard = plan is not None and serving._plan_writes(plan)
    assert held_by_old_guard is True
    assert held_by_new_guard is False
