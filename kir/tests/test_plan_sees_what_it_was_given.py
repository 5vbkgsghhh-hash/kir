"""THE PLAN IS THE MODEL'S EYES, AND ON BAD INPUT THEY LIED.

Three measurements from 04.08, each reproduced here BEFORE the fix:

1. `preview(ops_list)` landed POSITIONALLY in the `level` parameter, `ops`
   stayed `None`, and the function printed "PLAN: the program is empty — not
   a single operation. Nothing to draw" — with three operations in hand.
   There was no refusal: the model read "empty" and went to add what it had
   already written. Meanwhile `design_check(ops)` DOES work positionally:
   the signatures `preview(level=None, *, ops=None)` and
   `design_check(ops=None)` diverged at one seam, and diverged silently.

2. `preview(ops=<a batch>)` printed "operations considered 2, drawn 0 (0%)"
   and NOT A WORD about why. A batch is a shape we PRESCRIBE to the model
   (`design_check([body, stairs])`, `tool_doc.NOTES`); the plan did not know
   about it at all.

3. A level's elevation was resolved ONLY by `$id`: by name it printed "elev.
   None mm". And addressing BY NAME is exactly what the batch's own law
   prescribes (`create_stairs.base_level` does not accept `ref`). The eyes
   went blind on precisely the shape we told people to use.

WHAT IS DELIBERATELY ABSENT HERE: a refusal on L1 nodes. The model in the
sandbox cannot produce them (it only has the op registry), and "a refusal on
an input the door does not even have" costs more than a missing one. Instead
of a refusal, what is checked is that ZERO coverage names ITSELF and its
cause — one rule for any kind of garbage.

Run: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_plan_sees_what_it_was_given.py -q
"""
from __future__ import annotations

import contextlib
import io
import os

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import course  # noqa: E402
from kir import preview as P  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# Material
# ═════════════════════════════════════════════════════════════════════════

def body_ops(*, by_name: bool) -> list[dict]:
    """Two walls on the declared level. The level is addressed either by ref
    or by NAME."""
    level = ({"by": "name", "value": "Этаж 1"} if by_name
             else {"by": "ref", "value": "L1"})
    return [
        {"op": "create_level", "id": "L1", "name": "Этаж 1", "elev_mm": 3300.0},
        {"op": "create_wall", "id": "w1", "level": level, "height_mm": 3000,
         "p0_mm": [0, 0], "p1_mm": [6000, 0]},
        {"op": "create_wall", "id": "w2", "level": level, "height_mm": 3000,
         "p0_mm": [6000, 0], "p1_mm": [6000, 5000]},
    ]


def stairs_ops() -> list[dict]:
    return [{"op": "create_stairs", "id": "s1", "width_mm": 1200,
             "p0_mm": [1000, 1000], "p1_mm": [1000, 4000],
             "base_level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "name", "value": "Этаж 2"}}]


def say(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════
# 1. THE SIGNATURE SEAM: the plan and the verdict are called THE SAME WAY
# ═════════════════════════════════════════════════════════════════════════

def test_the_plan_takes_its_program_positionally_like_the_verdict() -> None:
    """THE FILE'S MAIN CLAIM. `preview(ops)` and `design_check(ops)` are a
    pair, and the model calls them the same way. Before 04.08 the first one
    silently lost the program."""
    ops = body_ops(by_name=False)
    text = say(course.preview, ops)
    assert "программа пуста" not in text, text
    assert "нарисовано 2 из 2" in text, text


def test_a_string_first_argument_is_named_not_guessed() -> None:
    """The flip side of the swap: `preview("Этаж 1")` no longer means "filter
    by level". Silently accepting the string as a level would be a guess;
    the refusal must name what was seen AND the fix in one line."""
    text = say(course.preview, "Этаж 1")
    assert "ПЛАН ОТКАЗ" in text, text
    assert "level=" in text, text
    assert "str" in text or "строка" in text, text


def test_the_level_filter_still_works_by_name_of_the_parameter() -> None:
    ops = body_ops(by_name=False)
    text = say(course.preview, ops, level="Этаж 1")
    assert "«Этаж 1»" in text and "нарисовано 2 из 2" in text, text
    missing = say(course.preview, ops, level="Этаж 7")
    assert "уровня «Этаж 7» в программе нет" in missing, missing


# ═════════════════════════════════════════════════════════════════════════
# 2. THE BATCH — A SHAPE WE OURSELVES PRESCRIBED
# ═════════════════════════════════════════════════════════════════════════

def test_the_plan_draws_a_bundle_and_says_it_was_one() -> None:
    """The batch gets MERGED by the renderer — one sheet, and this is
    already the stream's own law (`plan_stream._slice_for`: "the renderer
    needs the merge"). Refusing on it would blind the model on exactly the
    unit a building actually is.
    """
    pack = [{"ops": body_ops(by_name=False)}, {"ops": stairs_ops()}]
    text = say(course.preview, pack)
    assert "нарисовано 0 (0%)" not in text, text
    assert "пачка" in text.lower(), text
    assert "2 программ" in text, text
    # And this is not an empty sheet: the body and the stairs both got drawn
    # ON ONE floor.
    assert "нарисовано 3 из 3" in text, text


def test_one_storey_addressed_two_ways_is_one_sheet() -> None:
    """ONE FLOOR — ONE SHEET, whatever it is addressed by.

    The body addresses the level by reference (`$L1`), the stairs must
    address THE SAME ONE by name — `create_stairs.base_level` does not
    accept a reference at all. So in the batch both forms stand side by
    side ALWAYS, and before 04.08 one floor came out as TWO sheets with THE
    SAME name: exactly the split `live/journal.py`'s header warns about.
    """
    pack = [{"ops": body_ops(by_name=False)}, {"ops": stairs_ops()}]
    text = say(course.preview, pack)
    assert text.count("«Этаж 1»") == 1, text
    assert "нарисовано 3 из 3" in text, text


def test_zero_drawn_names_itself_and_its_reason() -> None:
    """ANY input that produced NOTHING drawn must say so in words and name
    the cause. Before 04.08 "considered 1, drawn 0 (0%)" was all the model
    ever got: not one line about WHY zero."""
    junk = [{"kind": "op", "op_name": "create_wall", "params": {}}]
    text = say(course.preview, junk)
    assert "НЕ НАРИСОВАНО НИЧЕГО" in text, text
    assert "не операция KIR" in text, text


def test_the_reason_for_a_non_op_is_not_blamed_on_a_selector() -> None:
    """The cause is addressable: "this element has no `op` key" and "the
    level selector does not resolve to a plan" are different fixes, and the
    second sends the fix to the wrong place."""
    census = P.build_program_preview(
        [{"kind": "op", "op_name": "create_wall", "params": {}}]).census
    reasons = {group.reason for group in census.omitted}
    assert P.OmitReason.NOT_AN_OP in reasons, reasons
    assert P.OmitReason.SELECTOR_UNRESOLVED not in reasons, reasons


# ═════════════════════════════════════════════════════════════════════════
# 3. ELEVATION BY NAME
# ═════════════════════════════════════════════════════════════════════════

def test_the_elevation_resolves_for_a_level_addressed_by_name() -> None:
    """Measured 04.08: by ref — 3300.0, by name — None. The program declares
    `create_level(name="Этаж 1", elev_mm=3300)` in both cases; the elevation
    is present in the program, and not returning it is a loss, not an
    unknown."""
    by_ref = say(course.preview, body_ops(by_name=False))
    by_name = say(course.preview, body_ops(by_name=True))
    assert "отм. 3300.0 мм" in by_ref, by_ref
    assert "отм. None мм" not in by_name, by_name
    assert "отм. 3300.0 мм" in by_name, by_name


def test_an_ambiguous_name_stays_unknown_rather_than_guessing() -> None:
    """The flip side: two `create_level` calls with one name and DIFFERENT
    elevations is an unknown, not "take the first one". A plausible-looking
    number here costs more than an honest gap.

    THIS IS ALSO THE ONE CASE WHERE THE NAME BRANCH DECIDES THE OUTCOME, and
    a mutation run showed it: with an UNAMBIGUOUS name the level key
    resolves to `$id` earlier (`build_program_preview`, alias), so "elev. by
    name" holds by resolution, not by lookup. What is left is exactly this
    fork — the name is used twice, resolution honestly refuses, and the
    elevation is known only when BOTH declarations say the same thing.
    """
    ops = body_ops(by_name=True)
    ops.insert(1, {"op": "create_level", "id": "L1b", "name": "Этаж 1",
                   "elev_mm": 9999.0})
    assert P._program_level_elevation(ops, "Этаж 1") is None
    # And matching elevations create no ambiguity.
    ops[1]["elev_mm"] = 3300.0
    assert P._program_level_elevation(ops, "Этаж 1") == 3300.0
    # And this is exactly what the model sees: the sheet prints the number,
    # not "None".
    assert "отм. 3300.0 мм" in say(course.preview, ops)
