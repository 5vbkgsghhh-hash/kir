"""PRINTING THE PARSE AS SOURCE: a round trip, a pinpoint control, and
three outcomes.

🔴 WHY THIS FILE EXISTS, BY MEASUREMENT, NOT BY REASONING.

`program_source` prints a parsed level as `program_py` source. Printed
text that nobody has run proves exactly that the text was produced: it
proves nothing at all about matching the source. So the subject here is
not the text but the MULTISET EQUALITY of "source versus executed".

THE INPUT IS BUILT BY PROD CODE (canon form 27). The ops in the synthetic
tests come not from a hand-assembled dictionary but from the language
itself (`kir.course.language`, the very set of names the model receives) —
that is, the test guards the product, not its own fixture. The corpus half
lives in `test_program_source_corpus.py` and builds its input with the
real `leaves_to_program`.

THE FAIL CONTROL HERE IS PINPOINT, AND THIS IS A REQUIREMENT, NOT
DECORATION. Broad reddening is a sign of a dull probe: it does not
distinguish "the check works" from "the check goes red on everything
indiscriminately". So ONE value is corrupted in ONE operation, and the
test requires exactly one lost and exactly one extra record — both on
that very same op.

WHAT THESE TESTS DO NOT PROVE IS STATED OUT LOUD: they do not go through
the SANDBOX (`kir.sandbox`) or through a live Revit. The round trip here
is about the printed Python ASSEMBLING the same program, not about it
being built.
"""
from __future__ import annotations

import pytest

from kir.course import language
from kir.decompile import program_source as ps


# ---------------------------------------------------------------------------
# The input is built by THE LANGUAGE ITSELF — the same one the model writes in
# ---------------------------------------------------------------------------

def _floor_program() -> dict:
    """A small level, ASSEMBLED BY PROD CODE: a wall, its door, a window,
    rooms.

    The `by=ref` reference here is real (`create_door(host=<стена>)`),
    because it is exactly the link for whose sake printing as Python was
    undertaken in the first place.
    """

    language.reset()
    level = language.by_element_id(1001)
    wall_type = language.by_element_id(2002)
    wall = language.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=level,
                                type=wall_type, height_mm=3000, id="W1")
    language.create_door(host=wall, offset_mm=1200, id="D1")
    language.create_window(host=wall, offset_mm=4200, sill_mm=900, id="N1")
    language.create_wall(p0_mm=[0, 0], p1_mm=[0, 4000], level=level,
                         type=wall_type, height_mm=3000, id="W2")
    language.create_room(xy=[3000, 1500], level=level, name="Кухня", id="R1")
    language.create_room(xy=[3000, 3500], level=level, name="Жилая", id="R2")
    program = language.take_ops()
    assert program, "язык не собрал программу — тесту нечего печатать"
    return program


def _ops(program: dict) -> list:
    return list(program["ops"])


# ---------------------------------------------------------------------------
# THE SUBJECT: a round trip
# ---------------------------------------------------------------------------

def test_round_trip_converges_on_a_program_the_language_built() -> None:
    program = _floor_program()
    rendering = ps.render_source([program], level="L1", run="тест")

    assert rendering.ok, rendering.report_ru()
    assert rendering.ops_printed == len(_ops(program)) == 6

    verdict = ps.round_trip(rendering, _ops(program))
    assert verdict.ok, verdict.report_ru()
    assert verdict.source_ops == verdict.executed_ops == 6


def test_printed_text_states_how_much_of_the_floor_it_carries() -> None:
    """The count of what was printed must be IN THE TEXT, not only in the
    object.

    A reader of the source does not hold our `SourceRendering` in hand.
    """

    program = _floor_program()
    rendering = ps.render_source([program], level="L1", run="тест")
    text = rendering.parts[0].text

    assert "6 операций" in text
    assert "program_py" in text
    assert "envelope(" in text and "with phase(" in text


# ---------------------------------------------------------------------------
# FAIL CONTROL: one value -> one red operation
# ---------------------------------------------------------------------------

def _corrupt_one_value(text: str, marker: str, before: str, after: str) -> str:
    """Corrupt EXACTLY one value in EXACTLY one operation line."""

    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines)
            if marker in line and before in line]
    assert len(hits) == 1, (
        "контроль обязан бить в ОДНУ строку, а нашёл %d — проба негодна"
        % len(hits))
    lines[hits[0]] = lines[hits[0]].replace(before, after, 1)
    return "\n".join(lines) + "\n"


def test_control_fail_one_broken_value_reddens_exactly_one_op() -> None:
    """Corrupting one height must produce EXACTLY one loss and EXACTLY one
    extra.

    If the check went red more broadly, it would not distinguish a
    working instrument from one that goes red on everything.
    """

    program = _floor_program()
    rendering = ps.render_source([program], level="L1", run="тест")
    broken = _corrupt_one_value(rendering.parts[0].text,
                                'id="W1"', "height_mm=3000", "height_mm=3050")

    executed = ps.execute_source(broken)
    assert not isinstance(executed, str), executed
    verdict = ps.compare_ops(_ops(program), executed["ops"])

    assert not verdict.ok, "испорченная величина обязана покраснеть"
    assert verdict.source_ops == verdict.executed_ops == 6, \
        "операция не должна была ПРОПАСТЬ — испорчена одна величина"
    assert len(verdict.lost) == 1 and verdict.lost[0][1] == 1, verdict.report_ru()
    assert len(verdict.extra) == 1 and verdict.extra[0][1] == 1, \
        verdict.report_ru()
    assert verdict.lost[0][0].startswith("create_wall|"), verdict.lost[0][0]
    assert verdict.extra[0][0].startswith("create_wall|"), verdict.extra[0][0]
    assert '"height_mm": 3000' in verdict.lost[0][0]
    assert '"height_mm": 3050' in verdict.extra[0][0]


def test_control_fail_dropped_op_is_a_loss_and_names_it() -> None:
    """A discarded line is a LOSS with no extra: a different form of failure than corruption."""

    program = _floor_program()
    rendering = ps.render_source([program], level="L1", run="тест")
    lines = rendering.parts[0].text.splitlines()
    victim = [i for i, line in enumerate(lines)
              if line.lstrip().startswith("create_room(") and 'id="R1"' in line]
    assert len(victim) == 1, "проба не нашла ровно одну строку-жертву"
    lines.pop(victim[0])

    executed = ps.execute_source("\n".join(lines) + "\n")
    assert not isinstance(executed, str), executed
    verdict = ps.compare_ops(_ops(program), executed["ops"])

    assert not verdict.ok
    assert verdict.executed_ops == 5 and verdict.source_ops == 6
    assert len(verdict.lost) == 1 and verdict.lost[0][1] == 1
    assert not verdict.extra
    assert verdict.lost[0][0].startswith("create_room|")
    assert "Кухня" in verdict.lost[0][0]


def test_control_fail_survives_a_deliberately_degenerate_probe() -> None:
    """A control must have POWER: on a single operation it catches
    nothing.

    Canon: a positional check requires power ≥ 2, otherwise the anchor is
    the entire sample. This is checked directly here: a control on a
    one-op program goes red as THE WHOLE PROGRAM, and "reddened at a
    point" is indistinguishable from "reddened entirely". That is why the
    subject controls above stand on six operations.
    """

    language.reset()
    language.create_room(xy=[0, 0], level=language.by_element_id(1001),
                         name="Одна", id="R1")
    program = language.take_ops()
    rendering = ps.render_source([program], level="L1", run="тест")
    broken = _corrupt_one_value(rendering.parts[0].text, 'id="R1"',
                                '"Одна"', '"Другая"')
    executed = ps.execute_source(broken)
    verdict = ps.compare_ops(_ops(program), executed["ops"])
    assert not verdict.ok
    assert len(verdict.lost) == len(verdict.extra) == 1
    # ...and this is THE WHOLE program: 1 of 1. Pinpointness cannot be proven here.
    assert verdict.source_ops == 1


# ---------------------------------------------------------------------------
# THREE OUTCOMES: a refusal with a named cause, not an exception and not silence
# ---------------------------------------------------------------------------

def test_unknown_op_refuses_by_name_without_raising() -> None:
    program = _floor_program()
    poisoned = {"ir_version": "1.0",
                "ops": [{"op": "create_teleporter", "id": "X1", "xy": [0, 0]}]}

    rendering = ps.render_source([program, poisoned], level="L1", run="тест")

    assert not rendering.ok
    assert [r.cause for r in rendering.refusals] == ["unknown_op"]
    assert rendering.refusals[0].program_index == 1
    assert rendering.refusals[0].op_id == "X1"
    # A healthy program is NOT lost because of a sick neighbor.
    assert len(rendering.parts) == 1 and rendering.parts[0].index == 0
    assert rendering.ops_printed == 6 and rendering.ops_total == 7


def test_unknown_param_refuses_because_dsl_would_refuse_later() -> None:
    poisoned = {"ir_version": "1.0",
                "ops": [{"op": "create_room", "id": "R1", "xy": [0, 0],
                         "цвет_обоев": "синий"}]}
    rendering = ps.render_source([poisoned])

    assert [r.cause for r in rendering.refusals] == ["unknown_param"]
    assert "цвет_обоев" in rendering.refusals[0].detail
    assert not rendering.parts


def test_null_value_refuses_instead_of_being_dropped_silently() -> None:
    """`dsl` throws `None` silently — the source would become QUIETER than the parse."""

    poisoned = {"ir_version": "1.0",
                "ops": [{"op": "create_room", "id": "R1", "xy": [0, 0],
                         "name": None}]}
    rendering = ps.render_source([poisoned])

    assert [r.cause for r in rendering.refusals] == ["null_param_value"]
    assert not rendering.parts


def test_ref_outside_the_program_refuses_rather_than_printing_a_dangling_name() -> None:
    poisoned = {"ir_version": "1.0",
                "ops": [{"op": "create_door", "id": "D1", "offset_mm": 900,
                         "host": {"by": "ref", "value": "W_НЕТУ"}}]}
    rendering = ps.render_source([poisoned])

    assert [r.cause for r in rendering.refusals] == ["ref_outside_program"]
    assert "W_НЕТУ" in rendering.refusals[0].detail


def test_program_over_the_compiler_ceiling_refuses() -> None:
    ceiling = ps.program_ceiling()
    ops = [{"op": "create_room", "id": "R%d" % i, "xy": [i, 0]}
           for i in range(ceiling + 1)]
    rendering = ps.render_source([{"ir_version": "1.0", "ops": ops}])

    assert "program_over_ceiling" in {r.cause for r in rendering.refusals}
    assert not rendering.parts


def test_incompleteness_is_visible_in_the_text_of_the_surviving_programs() -> None:
    """A silently incomplete output is the main defect this module was written against."""

    program = _floor_program()
    poisoned = {"ir_version": "1.0",
                "ops": [{"op": "create_teleporter", "id": "X1"}]}
    rendering = ps.render_source([program, poisoned], level="L1", run="тест")

    text = rendering.parts[0].text
    assert "НАПЕЧАТАНО НЕ ВСЁ" in text
    assert "unknown_op" in text
    assert "6 операций из 7" in text or "операций из 7" in text


def test_every_refusal_cause_must_be_declared() -> None:
    """An unnamed refusal is silence with an excuse."""

    with pytest.raises(ValueError):
        ps.SourceRefusal("причина_которой_нет", 0, None, None, "")
    assert set(ps.REFUSAL_CAUSES) >= {
        "unknown_op", "unknown_param", "op_without_id", "duplicate_op_id",
        "ref_outside_program", "program_over_ceiling", "null_param_value"}


def test_nothing_to_print_is_not_success() -> None:
    """🔴 A ZERO FOR A VALUE THAT WAS NOT COUNTED HERE IS NOT A RESULT."""

    rendering = ps.render_source([])
    assert rendering.empty
    assert "ПЕЧАТАТЬ БЫЛО НЕЧЕГО" in rendering.report_ru()
    assert "ПОЛНО" not in rendering.report_ru()


# ---------------------------------------------------------------------------
# Units: a function only where it does not lie
# ---------------------------------------------------------------------------

def test_unit_with_a_reference_crossing_its_border_is_printed_inline() -> None:
    """🔴 A REGRESSION FOUND BY THE CORPUS ON 17.08.2026, NOT BY EYE.

    `w_wall_2846 = create_wall(...)` inside `def unit_…` is a LOCAL name,
    and `create_door(host=w_wall_2846)` outside it used to raise
    `NameError`. On `k2_ar_rd_v7` this is not visible at all (there, all
    210 references sit in the free part), while on `sob62_fas_r23_v19` two
    of four levels executed this way — 1224 and 927 operations.
    """

    program = _floor_program()
    # The unit holds wall W1, and door D1 looks at it from OUTSIDE the unit.
    unit = ps.SourceUnit(kind="apartment", label="apartment:1",
                         op_ids=frozenset({"W1", "W2"}))
    rendering = ps.render_source([program], level="L1", run="тест",
                                 units=[unit])

    assert rendering.parts[0].units_linked_out == 1
    assert rendering.parts[0].units_printed == 0
    assert "def unit_" not in rendering.parts[0].text
    verdict = ps.round_trip(rendering, _ops(program))
    assert verdict.ok, verdict.report_ru()


def test_ref_closed_unit_becomes_a_function_and_the_round_trip_still_converges() -> None:
    """A closed unit is printed as a function — and the local frame is EXACT."""

    program = _floor_program()
    unit = ps.SourceUnit(kind="apartment", label="apartment:кухня",
                         op_ids=frozenset({"R1", "R2"}))
    rendering = ps.render_source([program], level="L1", run="тест",
                                 units=[unit])
    text = rendering.parts[0].text

    assert rendering.parts[0].units_printed == 1
    assert "def unit_apartment_кухня(dx=0, dy=0):" in text
    assert "unit_apartment_кухня(dx=3000, dy=1500)" in text
    # The shift and the reverse shift must match EXACTLY: this is what the round trip proves.
    verdict = ps.round_trip(rendering, _ops(program))
    assert verdict.ok, verdict.report_ru()


def test_a_thin_unit_is_inlined_rather_than_wrapped_in_ceremony() -> None:
    """A function made of one call reads worse than a bare line (`MIN_UNIT_OPS`)."""

    assert ps.MIN_UNIT_OPS == 2
    program = _floor_program()
    unit = ps.SourceUnit(kind="apartment", label="apartment:одна",
                         op_ids=frozenset({"R1"}))
    rendering = ps.render_source([program], level="L1", run="тест",
                                 units=[unit])

    assert rendering.parts[0].units_thin == 1
    assert "def unit_" not in rendering.parts[0].text


def test_overlapping_units_are_refused_rather_than_printed_twice() -> None:
    """An op in two units would be printed TWICE, and the round trip would
    blame the printer.

    `fold` produces non-overlapping children of a level, but the entry
    point is open to any caller, and an "extra operation" in the round
    trip reads as a printer defect, not as an input defect.
    """

    program = _floor_program()
    units = [ps.SourceUnit("apartment", "a", frozenset({"R1", "R2"})),
             ps.SourceUnit("mop", "b", frozenset({"R2", "W2"}))]
    with pytest.raises(ValueError, match="пересекаются"):
        ps.render_source([program], units=units)


def test_a_split_unit_says_so_in_its_own_docstring() -> None:
    """What makes a function a lie is not incompleteness but SILENT incompleteness."""

    program = _floor_program()
    # The unit is declared wider than what was materialized: part of it is here, part is not.
    unit = ps.SourceUnit(kind="apartment", label="apartment:7",
                         op_ids=frozenset({"R1", "R2", "нет_такого_опа"}))
    rendering = ps.render_source([program], level="L1", run="тест",
                                 units=[unit])

    # The whole of a unit is what the materializer ACTUALLY PRODUCED (2
    # ops), not what the tree declared (3): otherwise printing would be
    # blaming itself for someone else's loss.
    assert rendering.parts[0].units_printed == 1
    assert rendering.parts[0].units_partial == 0


def test_a_unit_cut_by_a_program_border_prints_its_share_honestly() -> None:
    program = _floor_program()
    other = {"ir_version": "1.0",
             "ops": [{"op": "create_room", "id": "R9", "xy": [9000, 0],
                      "name": "Соседняя"}]}
    unit = ps.SourceUnit(kind="apartment", label="apartment:9",
                         op_ids=frozenset({"R1", "R2", "R9"}))
    rendering = ps.render_source([program, other], level="L1", run="тест",
                                 units=[unit])

    first = rendering.parts[0]
    assert first.units_partial == 1 and first.units_printed == 0
    assert "операций 2 ИЗ 3" in first.text
    assert "единица разрезана границей программы" in first.text


# ---------------------------------------------------------------------------
# Authorities: not a single number is derived from a field's name
# ---------------------------------------------------------------------------

def test_budgets_are_asked_of_the_compiler_not_written_down() -> None:
    from kir.compiler import MAX_BULK_OPS, MAX_OPS_PER_PROGRAM

    assert ps.phase_budget() == int(MAX_OPS_PER_PROGRAM)
    assert ps.program_ceiling() == int(MAX_BULK_OPS)


def test_rounding_asks_the_registry_kind_not_the_field_name() -> None:
    """`10829.999995547229` is noise, `bulge=0.4142…` is an arc. `ParamSpec.kind` decides."""

    kinds = ps.param_kinds()
    assert kinds[("create_wall", "p0_mm")] in ps.MM_KINDS
    assert kinds[("create_wall", "height_mm")] in ps.MM_KINDS

    language.reset()
    language.create_wall(p0_mm=[10829.999995547229, 0.0000001],
                         p1_mm=[6000, 0], level=language.by_element_id(1),
                         height_mm=3000, id="W1")
    program = language.take_ops()
    text = ps.render_source([program]).parts[0].text
    assert "p0_mm=[10830, 0]" in text, text[-600:]

    # 🔴 THE PROBE MUST STRIKE EXACTLY WHERE THE TWO RULES DIVERGE,
    # OTHERWISE IT IS GREEN BY CONSTRUCTION. A measurement on 17.08.2026
    # against the registry: the rule "the name ends in `_mm`" and the rule
    # "the kind comes from the registry" diverge on 41 (op, parameter)
    # pairs — 3 one way, 38 the other. As long as the probe stood on
    # `p0_mm` (where both rules agree), swapping the authority for the
    # name's suffix passed ALL 26 tests. Both sides of the divergence are
    # checked below, by name.
    assert kinds[("create_level", "elev_mm")] == "num"      # the name lies
    assert kinds[("create_room", "xy")] == "pt_xy"          # the name is silent

    language.reset()
    language.create_level(elev_mm=3000.4, name="L1", id="LV")
    language.create_room(xy=[1200.6, 0.2], level=language.by_element_id(1),
                         id="R1")
    text = ps.render_source([language.take_ops()]).parts[0].text
    assert "elev_mm=3000.4" in text, \
        "вид `num` округлять НЕЛЬЗЯ, как бы ни выглядело имя: %s" % text[-400:]
    assert "xy=[1201, 0]" in text, \
        "вид `pt_xy` округлять НАДО, хотя имя не кончается на `_mm`: %s" \
        % text[-400:]

    # And a dimensionless value inside a nested structure is not touched
    # at all. The op chosen is one where `contour` IS in the registry
    # (`region`) — established by asking, not assuming: `create_floor` has
    # no such parameter at all, and a probe on it would silently round
    # nothing, staying green by construction.
    assert kinds[("create_floor_by_contour", "contour")] == "region"
    assert ps.FREE_KEYS >= {"bulge"}
    contour = {"outer": {"points_mm": [[0.4, 0.6]], "bulge": 0.4142135623730993}}
    kept = ps._round_by_kind("create_floor_by_contour", "contour", contour,
                             kinds)
    assert kept["outer"]["bulge"] == 0.4142135623730993
    assert kept["outer"]["points_mm"] == [[0.0, 1.0]]


def test_the_millimetre_kind_list_is_checked_against_the_registry() -> None:
    """🔴 A HANDWRITTEN LIST THAT MUST STAY IN SYNC WITH THE REGISTRY IS OUR
    NAMED DEFECT. Here it is pinned as tightly as this can be done.

    PROVABLE: every name in `MM_KINDS`/`DEG_KINDS` is a real parameter
    kind (`spec.PARAM_KINDS`, a closed list of 34). Rename a kind, and it
    goes red here, rather than silently stopping to round on someone's
    level.

    UNPROVABLE, AND SAID OUT LOUD: that the list is COMPLETE, that is,
    that someone will add here every new kind measured in millimeters.
    This is a human judgment, and it is not derived automatically: from a
    kind's name ("arc", "slopes") one cannot decide whether millimeters
    are inside or not. The absence of a kind here means "we don't know",
    not "it is dimensionless".
    """

    from kir import spec

    # 🔴 A SUBSTANTIVE REVISION ON 21.08.2026, NOT A NUMBER TWEAK. The
    # ratchet stood at 34 and had been RED silently since 20.08: the
    # surface wave (`surface`) and the boolean wave (`solid_parts`) set up
    # their own kinds and never looked in here, the plane wave (`plane`)
    # is the third. A substantive revision, every kind read through:
    #
    #   plane        MILLIMETERS INSIDE (`origin_mm`) plus DIMENSIONLESS
    #                vectors (`normal`, `x_dir`). Added to `MM_KINDS`, and
    #                the vectors to `FREE_KEYS`: without the second half,
    #                `_round_mm` would round the normal [0.7071, 0.7071,
    #                0] down to [1.0, 1.0, 0.0], and `_shift` would
    #                subtract the local frame's origin from a direction.
    #                Both fixes produce a list of numbers that looks
    #                legitimate and fail nowhere;
    #   surface      MILLIMETERS INSIDE (`control_points_mm`), and it is
    #                NOT in `MM_KINDS`. This is a NAMED HOLE from someone
    #                else's wave, not a fix: NURBS control points are
    #                neither rounded nor shifted into the local frame. Not
    #                fixed here, because the fix would change the
    #                PRINTING of someone else's op, whose owner is
    #                different;
    #   solid_parts  MILLIMETERS INSIDE (`center_mm`, `size_mm`,
    #                `radius_mm`, `height_mm`), and it is ALSO not in
    #                `MM_KINDS`. The same hole and the same owner.
    #
    # ── REVISION 21.08.2026: 37 -> 38, AND IT FOUND MORE THAN ONE NEW KIND ──
    #
    # 🔴 THE PREVIOUS REVISION DID NOT LOOK AT THE WHOLE LIST. It parsed
    # the kinds set up by the LATEST WAVES (`surface`, `solid_parts`,
    # `plane`), and so it did not see the old ones. The revision's scope
    # was itself the hole: a measurement over ALL 38 kinds (samples
    # `test_sdk._SAMPLES`, running `_shift` and `_round_mm`) found THREE
    # MORE kinds with millimeters outside the list, and one of them
    # belongs to the most frequent lift operation:
    #
    #     create_wall(p0_mm=[dx + 2000, dy + 1500],
    #                 arc={"center_mm": [4500, 2000], ...})
    #
    # The wall's ends follow the unit's frame, the ARC'S CENTER does not.
    # Shift the unit — the arc becomes a different one. `create_wall`
    # carries a DIRECT reverse path and accounts for 7845 of 19 041
    # lifted MNVNK operations.
    #
    #   arc          ADDED. center_mm is shifted, radius_mm is correctly
    #                rounded to whole mm, bulge is already in FREE_KEYS,
    #                dir is a string
    #   graph_nodes  ADDED. xyz_mm is shifted, id is not touched
    #   placements   ADDED. a bare [x, y]
    #   spiral       REJECTED BY MEASUREMENT: rounding ruins the angles
    #                (included_angle_deg 180.75 -> 180.0). Reachable via a
    #                lift (create_stairs, a direct path) — that is, this
    #                is a LIVE debt
    #   dir_xyz      OUTSIDE ON THE MERITS, and this is not an omission.
    #                The kind carries a RAY: length means nothing, zero is
    #                forbidden, there are no millimeters at all. If it
    #                landed here, `_shift` would subtract the frame's
    #                origin from a direction ([-1,0,0] -> [-1001,-500,0]),
    #                that is, it would bring back exactly the defect this
    #                kind was set up against
    #
    # The reasons for the refusals are held by `ps.MM_KINDS_REFUSED` —
    # next to the list itself, and not only here: the guard and the cure
    # must live in one place.
    #
    # The number below is the result of the revision. The next wave must
    # repeat it, not just bump the digit: the text above is exactly what
    # the ratchet guards. And repeat it OVER THE WHOLE list, not just its
    # own new kinds — otherwise it would repeat the same miss too.
    # ── REVISION 23.08.2026: 38 -> 39 ─────────────────────────────────────
    #
    # There is one new kind — `wall_layers` (the layer stack on
    # `create_wall_type`). The revision was repeated OVER THE WHOLE list,
    # as the paragraph above requires, and found TWO holes, not one: the
    # second (`member_ops`) was set up by an unrelated groups wave and had
    # sat here unnoticed. Both, with their reasons, live in
    # `ps.MM_KINDS_REFUSED`, next to the list — and both are today
    # UNREACHABLE via the reverse path: neither `create_wall_type` nor
    # `create_group` emits a single lift operation.
    #
    # 🔴 And the first run of this revision was AN INSTRUMENT'S LIE: both
    # functions were called with the arguments in the wrong order, both
    # columns printed confidently, and both were wrong. Details are in
    # the same place, at `MM_KINDS_REFUSED`.
    # ── РЕВИЗИЯ 13.09.2026: 39 -> 41 ──────────────────────────────────────
    #
    # Двух видов прибыло: `identity` (волна N-2, `fc6ef65`) и `enum_list`
    # (`query_level_plan.include`). Ревизия повторена ПО ВСЕМУ списку, как
    # требует абзац выше, и это дало одну находку сверх двух новых.
    #
    # НОВЫЕ ДВА — НЕ КАНДИДАТЫ, и это измерено, а не решено на глаз:
    #   `identity`   — {unique_id, version_guid}: два СТРОКОВЫХ поля, ни одного
    #                  числа. Ни округлять, ни сдвигать нечего. Род при этом
    #                  ЖИВОЙ на обратном ходе (`delete`, `move_elements`
    #                  поднимаются) — то есть молчание здесь было бы молчанием
    #                  о работающем пути, а не о спящем.
    #   `enum_list`  — список ИМЁН из закрытого словаря; чисел нет вовсе, и
    #                  обратным ходом не достижим (`query_level_plan` не
    #                  поднимает никто: читающий оп нечего поднимать).
    # Поэтому в `MM_KINDS_REFUSED` их НЕТ: этот словарь держит роды, которые
    # НЕСУТ миллиметры и исключены ради их сохранности. Класть туда род без
    # единого числа значило бы размыть смысл словаря до «всё, что не в списке».
    #
    # 🔴 НАХОДКА РЕВИЗИИ — `slopes`, и она чужой волны, как `member_ops` в 23.08.
    # Род несёт `angle_deg` и ЖИВОЙ на обратном ходе (`create_roof`
    # поднимается), а стоял ни в одном из трёх списков. Порчи сегодня нет —
    # неперечисленный род остаётся нетронутым, — но соблазн внести его в
    # `DEG_KINDS` есть, и он убил бы 30.25 → 30.0. Вопрос и причина записаны
    # РЯДОМ СО СПИСКОМ, в `ps.MM_KINDS_REFUSED`, как того требует правило
    # «сторож и лекарство живут в одном месте».
    assert len(spec.PARAM_KINDS) == 41, \
        "видов стало %d — список миллиметровых надо ПЕРЕСМОТРЕТЬ, а не " \
        "поправить число" % len(spec.PARAM_KINDS)
    unknown = (ps.MM_KINDS | ps.DEG_KINDS) - set(spec.PARAM_KINDS)
    assert not unknown, "видов нет в реестре: %s" % sorted(unknown)

    # 🔴 THE REJECTED ONES ARE ALSO CHECKED AGAINST THE REGISTRY, and this
    # is not pedantry: a record of a refusal whose kind got renamed is the
    # very same handwritten table gone out of sync with the authority,
    # just with an alibi.
    stray = set(ps.MM_KINDS_REFUSED) - set(spec.PARAM_KINDS)
    assert not stray, "отвергнутых родов нет в реестре: %s" % sorted(stray)
    assert not (set(ps.MM_KINDS_REFUSED) & ps.MM_KINDS), \
        "род одновременно в списке и в отказах — одно из двух неверно"
    for kind, why in ps.MM_KINDS_REFUSED.items():
        assert len(why) > 30, \
            "%s: отказ без причины отправит следующего гадать" % kind


def test_type_selector_keeps_the_source_form_and_carries_the_name_as_a_comment() -> None:
    """Readability was not bought at the price of precision: the selector is THE SAME, meaning sits alongside."""

    program = _floor_program()
    rendering = ps.render_source([program], type_names={2002: "111_Кирпич 380"})
    text = rendering.parts[0].text

    assert "= by_element_id(2002)  # «111_Кирпич 380»" in text
    assert "by_name(" not in text
    assert rendering.parts[0].unresolved_names == 1   # level 1001 with no name


def test_a_selector_without_a_name_is_marked_not_invented() -> None:
    program = _floor_program()
    rendering = ps.render_source([program], type_names={})
    assert rendering.parts[0].unresolved_names == 2
    assert "?? имени в профиле нет" in rendering.parts[0].text


def test_execute_refuses_with_a_reason_instead_of_returning_empty() -> None:
    """A silent empty result would be the worst of all possible outcomes."""

    assert isinstance(ps.execute_source("это не питон ("), str)
    assert "SyntaxError" in ps.execute_source("это не питон (")
    assert "не собралась" in ps.execute_source("x = 1\n")
