"""A CROSS-FIELD RULE WAS ANNOUNCED TO THE AUTHOR — AND THE ANNOUNCEMENT
WAS CHECKED AGAINST BEHAVIOR.

WHY THIS FILE EXISTS. The registry expresses the requiredness of ONE field
(`ParamSpec.required`). Rules of the shape "`xyz` EITHER `p0_mm`/`p1_mm`,
and the choice decides whether `level` or `host` is needed" it cannot
express: `OpSpec` has eleven fields, and none of them describes relations
between parameters (measured 13.08.2026, an audit of the language's axes).
Such rules live in hand-written branches of
`compiler._parse_and_check_internal`.

WHAT IT WAS BEFORE. The rule reached the author through NOT ONE channel:

    the schema (carried every turn)   `place_family` → required: ['op']
    the tool description               the word `xyz` — 0 times across 28 218 characters
    `course.spec("place_family")`      all 14 parameters as "optional"

The third line is not a gap but a FALSE STATEMENT in the very text we call
a contract: it said the OPPOSITE of the rule. The author (and the main
author here is an LLM) only learned the rule from a refusal, a round trip
for every single one.

WHAT IS LOCKED IN HERE. The rule's prose moved into `tool_doc.OP_NOTES`,
from where `spec(<op>)` prints it under the heading «ЛОВУШКА ЭТОГО ОПА».
The prose is a SECOND instance of a rule that lives in the compiler, and
keeping it honest is not a human's job but this file's: **every rule must
REFUSE with a named code on a violating program AND LET a legitimate one
through.** The first proves the rule is alive; the second that the probe
is capable of being green for reasons other than construction (canon form
8: every probe has both halves).

THE BOUNDARY, IN WORDS. The file checks the PLAN (`compiler.plan_program`)
— that is, the stage these rules actually sit at. It does not check
grounding, emission, or Revit's behavior. And it does not claim there are
exactly six cross-field rules: six is how many were captured by the run on
13.08 and are therefore declared. The upper estimate from that same day is
23 ops and 47 refusal templates; there is a gap between them, and it is
named.

WHAT IS DELIBERATELY NOT HERE. `create_opening`: a program with
`variety="host_face"` and with NO shape at all PASSES the plan (measured
13.08). While there is no refusal, writing prose about it would mean
recording a note from memory instead of an excerpt from the code.
"""

from __future__ import annotations

import unittest

from kir import compiler, spec
from kir.dsl import OP_FUNCTIONS
from kir.tool_doc import OP_NOTES

_LVL = {"by": "element_id", "value": 100}
_LVL2 = {"by": "element_id", "value": 101}
_SYM = {"by": "element_id", "value": 200}
_WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": _LVL}

#: (op, violation label, refusal code, violating ops, legitimate ops).
#:
#: The codes and texts were CAPTURED BY A RUN on 13.08.2026, not written
#: from memory: every line below was run first, and only afterward did
#: prose about it get written into `OP_NOTES`. The order is exactly this
#: way because the reverse order already cost this house several
#: "measurements" that turned out to be retellings.
_RULES: tuple[tuple[str, str, str, list, list], ...] = (
    ("place_family", "положение не задано", "KIR-P007",
     [{"op": "place_family", "id": "P1", "symbol": _SYM}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "положение задано дважды", "KIR-P007",
     [{"op": "place_family", "id": "P1", "symbol": _SYM, "xyz": [0, 0, 0],
       "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0]}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "точка без уровня", "KIR-P005",
     [{"op": "place_family", "id": "P1", "symbol": _SYM, "xyz": [0, 0, 0]}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "кривая без хозяина", "KIR-P005",
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0], "level": _LVL}],
     [_WALL, {"op": "place_family", "id": "P1", "symbol": _SYM,
              "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
              "host": {"by": "ref", "value": "W1"}}]),
    ("create_ceiling", "форма не задана", "KIR-P007",
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL}],
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]]}]),
    ("create_ceiling", "форма задана дважды", "KIR-P007",
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
       "contour": {"of": [{"kind": "rect", "p0_mm": [0, 0],
                           "p1_mm": [5000, 5000]}]}}],
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]]}]),
    ("create_column", "top_xy без top_level", "KIR-T002",
     [{"op": "create_column", "id": "C1", "xy": [0, 0], "level": _LVL,
       "top_xy": [500, 500]}],
     [{"op": "create_column", "id": "C1", "xy": [0, 0], "level": _LVL,
       "top_xy": [500, 500], "top_level": _LVL2}]),
    ("create_stairs", "марш не задан", "KIR-P007",
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200}],
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0]}]),
    ("create_stairs", "марш задан дважды", "KIR-P007",
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0],
       "spiral": {"center_mm": [0, 0], "radius_mm": 1500,
                  "start_angle_deg": 0, "included_angle_deg": 180,
                  "clockwise": True}}],
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0]}]),
    ("create_window", "смещение за краем стены", "KIR-T002",
     [_WALL, {"op": "create_window", "id": "WD1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 99000}],
     [_WALL, {"op": "create_window", "id": "WD1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500}]),
    ("create_door", "смещение за краем стены", "KIR-T002",
     [_WALL, {"op": "create_door", "id": "D1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 99000}],
     [_WALL, {"op": "create_door", "id": "D1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500}]),
    # 🔴 ADDED ON 16.08.2026 AFTER AN EXTERNAL AUDIT. The `create_group`
    # note CLAIMED THE OPPOSITE of the law ("`by: ref` doesn't work inside
    # a group"), and there was nothing to catch it with: the note guard
    # checked the PRESENCE of text, not its truth. Here the rule is set up
    # from both poles, so flipping the note's meaning in either direction
    # now fails the run.
    ("create_group", "ссылка ВПЕРЁД внутри группы", "KIR-T001",
     [{"op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
       "members": [{"op": "create_door", "id": "D1", "symbol": _SYM,
                    "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500},
                   _WALL]}],
     [{"op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
       "members": [_WALL,
                   {"op": "create_door", "id": "D1", "symbol": _SYM,
                    "host": {"by": "ref", "value": "W1"},
                    "offset_mm": 2500}]}]),
    ("create_group", "ссылка НАРУЖУ группы", "KIR-T001",
     [_WALL,
      {"op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
       "members": [{"op": "create_door", "id": "D1", "symbol": _SYM,
                    "host": {"by": "ref", "value": "W1"},
                    "offset_mm": 2500}]}],
     [{"op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
       "members": [_WALL,
                   {"op": "create_door", "id": "D1", "symbol": _SYM,
                    "host": {"by": "ref", "value": "W1"},
                    "offset_mm": 2500}]}]),
)

#: NOTES THAT LIVE AS PROSE WITH NO BEHAVIORAL OVERSIGHT — AND WHY EACH ONE
#: IS HERE.
#:
#: The list is CLOSED and must stay SHORT: it is exactly the surface where
#: a note can lie and nobody notices. That is precisely where, on
#: 16.08.2026, the lie about `create_group` was found — it was NOT NAMED,
#: it simply went unchecked. Landing on this list is a decision with a
#: reason, not a dumping ground for anything too lazy to reconcile.
#:
#: Both entries share one reason by kind: a claim about REVIT, not about
#: our own decompile. It never occurs at any offline stage, so there is
#: nothing to carry it with a plan run; it is checked by live Revit or not
#: checked at all.
_PROSE_ONLY: dict[str, str] = {
    "create_pipe_system": (
        "требование семейства отвода — свойство ТИПА в открытом документе; "
        "офлайновая стадия его не видит, отказ приходит из Revit"),
    "create_area_reinforcement": (
        "три факта про Revit API (умолчание hook_type, род носителя, "
        "настройка документа HostStructuralRebar). Замерено 16.08: программа "
        "с носителем-СТЕНОЙ план ПРОХОДИТ — то есть на этой стадии правила "
        "нет, и писать про него прозу как про проверяемое было бы вторым "
        "экземпляром того же дефекта"),
}


def _plan(ops: list) -> tuple[bool, tuple[str, ...]]:
    """(passed?, refusal codes).

    ON SUCCESS `plan_program` returns a `PlannedProgram`, WHICH HAS NO
    `.diagnostics`. The first edition of this runner read the resulting
    `AttributeError` as a refusal and printed TWO ACCEPTED cases as
    rejected — exactly what almost got `create_opening` prose about a rule
    that doesn't exist at this stage.
    """
    try:
        compiler.plan_program({"ir_version": "1.0", "ops": ops})
    except Exception as exc:  # noqa: BLE001 — the subject being checked, not a nuisance
        diags = getattr(exc, "diagnostics", None) or ()
        return False, tuple(d.code for d in diags)
    return True, ()


class EveryDeclaredRuleStillRefuses(unittest.TestCase):
    """The rule's prose is checked against BEHAVIOR, not against anyone's memory."""

    def test_the_violating_program_is_refused_with_the_named_code(self) -> None:
        for op_name, label, code, bad, _good in _RULES:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _plan(bad)
                self.assertFalse(ok, f"{op_name} ({label}): план ПРИНЯЛ "
                                     f"программу, нарушающую объявленное "
                                     f"правило — проза разошлась с кодом")
                self.assertIn(code, codes, f"{op_name} ({label}): отказ есть, "
                                           f"но код другой: {codes}")

    def test_the_lawful_program_passes(self) -> None:
        """A PASS control. Without it the green above tells us nothing: a
        rule that rejects EVERYTHING would also reject the violator."""
        for op_name, label, _code, _bad, good in _RULES:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _plan(good)
                self.assertTrue(ok, f"{op_name} ({label}): законная программа "
                                    f"отвергнута {codes} — проверять нечем")


class TheRuleReachesTheAuthor(unittest.TestCase):
    """A rule the author cannot reach does not exist."""

    def test_every_op_with_a_rule_carries_it_in_its_own_contract(self) -> None:
        for op_name in sorted({r[0] for r in _RULES}):
            with self.subTest(op_name):
                self.assertIn(op_name, OP_NOTES,
                              f"{op_name}: правило проверяется прогоном, но "
                              f"автору не объявлено ничем")
                doc = OP_FUNCTIONS[op_name].__doc__ or ""
                for note in OP_NOTES[op_name]:
                    self.assertIn(note, doc,
                                  f"{op_name}: ловушка не доехала в докстроку")

    def test_an_op_with_no_required_param_says_so_instead_of_implying_freedom(
            self) -> None:
        """A conclusion, not a name: the condition is checked for EVERY op
        in the registry.

        Measured on 13.08: exactly one op out of 69 fits this
        (`place_family`). But what is locked in is the PROPERTY, not the
        name — the next such op will get its own line automatically.
        """
        marker = "РЕЕСТР НЕ ОБЪЯВЛЯЕТ У ЭТОГО ОПА НИ ОДНОГО ОБЯЗАТЕЛЬНОГО"
        without_required = {
            name for name, ospec in spec.OPS.items()
            if ospec.params and not any(p.required for p in ospec.params)}
        self.assertTrue(without_required,
                        "ни одного такого опа — проверка выродилась, и её "
                        "зелёный цвет ничего не значит")
        for name, ospec in sorted(spec.OPS.items()):
            with self.subTest(name):
                doc = OP_FUNCTIONS[name].__doc__ or ""
                if name in without_required:
                    self.assertIn(marker, doc)
                else:
                    # A FAIL CONTROL by the same line: for an op with a
                    # required parameter this phrase would be untrue.
                    self.assertNotIn(marker, doc)


#: RULES FOR WHICH THE PLAN IS NOT ENOUGH: one needs the program's
#: ENVELOPE, another needs a SNAPSHOT of the model. A separate table
#: because they have a different runner, not a different kind: they enter
#: the coverage census below on equal footing.
_RULES_STAGED: tuple[tuple[str, str, str, dict, dict], ...] = (
    ("delete", "требование конверта", "KIR-D001",
     {"ops": [{"op": "delete", "id": "d1",
               "target": {"by": "element_id", "value": 5}}]},
     {"ops": [{"op": "delete", "id": "d1",
               "target": {"by": "element_id", "value": 5}}],
      "envelope": {"allow_destructive": True}}),
    ("create_filled_region", "адрес от осей в контуре", "KIR-T001",
     {"ops": [{"op": "create_filled_region", "id": "f1",
               "in_view": {"by": "element_id", "value": 900},
               "contour": {"outer": {"shape": "rect",
                                     "origin": {"at_grid": ["Б", "2"]},
                                     "size_mm": [2000, 1000]}}}],
      "snapshot": True},
     {"ops": [{"op": "create_filled_region", "id": "f1",
               "in_view": {"by": "element_id", "value": 900},
               "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                     "size_mm": [2000, 1000]}}}],
      "snapshot": True}),
)


def _staged(case: dict) -> tuple[bool, tuple[str, ...]]:
    """The same question as `_plan`'s, but through the stage the rule
    actually lives at."""
    from kir.tests.fixtures import GROUND_SNAPSHOT

    prog = {"ir_version": "1.0", "ops": case["ops"]}
    prog.update(case.get("envelope") or {})
    if case.get("snapshot"):
        out = compiler.compile_program(prog, snapshot=GROUND_SNAPSHOT)
        if out.ok:
            return True, ()
        return False, tuple(d.code for d in (out.diagnostics or ()))
    try:
        compiler.plan_program(prog)
    except Exception as exc:  # noqa: BLE001 — the subject being checked
        return False, tuple(d.code for d in (getattr(exc, "diagnostics", None) or ()))
    return True, ()


class EveryStagedRuleStillRefuses(unittest.TestCase):
    """The same two poles for rules that live behind the envelope or the snapshot."""

    def test_the_violating_program_is_refused_with_the_named_code(self) -> None:
        for op_name, label, code, bad, _good in _RULES_STAGED:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _staged(bad)
                self.assertFalse(ok, f"{op_name} ({label}): нарушающая "
                                     f"программа ПРИНЯТА — проза разошлась "
                                     f"с кодом")
                self.assertIn(code, codes,
                              f"{op_name} ({label}): код другой: {codes}")

    def test_the_lawful_program_passes(self) -> None:
        for op_name, label, _code, _bad, good in _RULES_STAGED:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _staged(good)
                self.assertTrue(ok, f"{op_name} ({label}): законная программа "
                                    f"отвергнута {codes} — проверять нечем")


class NoNoteEscapesTheCensus(unittest.TestCase):
    """🔴 THE COVERAGE CENSUS — WHAT WAS MISSING, AND ITS COST.

    An external audit on 16.08.2026 found, in `OP_NOTES["create_group"]`, a
    claim that CONTRADICTED the law: the note said "`by: ref` doesn't work
    inside a group," while the validator only refuses a reference FORWARD
    and OUTWARD. There was nothing to catch this with — the note guard
    checked the PRESENCE of the text and its non-duplication, meaning it
    would go red on the lie's REMOVAL and could not go red on the lie
    itself.

    The defect was not in one line but in the absence of a census: the
    note was never declared either checked or unchecked — it simply went
    unchecked, and nothing reported that. There is no longer a third state
    here.
    """

    def test_every_note_is_either_driven_or_named_as_prose(self) -> None:
        driven = {r[0] for r in _RULES} | {r[0] for r in _RULES_STAGED}
        for op_name in sorted(OP_NOTES):
            with self.subTest(op_name):
                self.assertTrue(
                    op_name in driven or op_name in _PROSE_ONLY,
                    f"{op_name}: заметка читается МОДЕЛЬЮ и не проверена "
                    f"ничем. Либо заведи ей оба полюса в _RULES/_RULES_STAGED, "
                    f"либо внеси в _PROSE_ONLY С ПРИЧИНОЙ. Молчание здесь — "
                    f"это ровно та щель, в которой полтора месяца жила ложь "
                    f"про create_group")

    def test_the_prose_only_list_stays_honest(self) -> None:
        """A list with no oversight must be NARROW and REAL.

        Two checks pointing in opposite directions: an entry with no
        reason is a formality; an entry about an op that has no note is
        junk, making the list longer than its subject.
        """
        for op_name, reason in sorted(_PROSE_ONLY.items()):
            with self.subTest(op_name):
                self.assertIn(op_name, OP_NOTES,
                              f"{op_name}: в списке без надзора, но заметки у "
                              f"него нет вовсе")
                self.assertGreaterEqual(
                    len(reason), 40,
                    f"{op_name}: причина короче сорока символов — это не "
                    f"причина, а отписка")
                self.assertNotIn(
                    op_name, {r[0] for r in _RULES} | {r[0] for r in _RULES_STAGED},
                    f"{op_name}: объявлен и проверяемым, и непроверяемым")

    def test_the_census_cannot_be_green_by_construction(self) -> None:
        """A FAIL control for the census: it must have a subject.

        An empty `OP_NOTES` would make both checks above green, having
        checked nothing — exactly the "check that never reached its
        subject."
        """
        self.assertGreaterEqual(len(OP_NOTES), 8,
                                "заметок почти нет — перепись выродилась")
        self.assertTrue({r[0] for r in _RULES} & set(OP_NOTES),
                        "ни одна заметка не ведётся прогоном — перепись "
                        "зелена по построению")


class TheNoteAgreesWithTheMeasuredLaw(unittest.TestCase):
    """🔴 A GUARD FOR TRUTH, NOT FOR PLACEMENT.

    The classes above prove that the LAW is as declared. But they do not
    read the note's text: it could be rewritten back into a lie without
    failing a single one of them. That exact gap is what let `create_group`
    through.

    Here the check runs in the other direction: first three outcomes are
    MEASURED, then the note is required to agree with what was measured.
    The words that must appear in it are taken FROM THE REFUSALS
    THEMSELVES, not out of the test author's head — otherwise the test
    would become a third hand-written copy of the same rule.

    WHAT THIS GUARD CANNOT DO, AND IT IS NAMED: it catches the measured lie
    and its close retellings, not every possible phrasing. A note denying
    the capability in NEW words would pass. Closing this completely
    requires generating the text from the law itself, and the group's
    prose does not have that kind of authority yet.
    """

    _MEMBER_DOOR = {"op": "create_door", "id": "D1", "symbol": _SYM,
                    "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500}

    def _measure(self, ops: list) -> tuple[bool, str]:
        try:
            compiler.plan_program({"ir_version": "1.0", "ops": ops})
        except Exception as exc:  # noqa: BLE001 — the subject being checked
            diags = getattr(exc, "diagnostics", None) or ()
            return False, " ".join((d.message_ru or "") for d in diags)
        return True, ""

    def test_the_group_note_says_what_the_compiler_does(self) -> None:
        backward_ok, _ = self._measure([{
            "op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
            "members": [_WALL, self._MEMBER_DOOR]}])
        forward_ok, forward_msg = self._measure([{
            "op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
            "members": [self._MEMBER_DOOR, _WALL]}])
        outside_ok, outside_msg = self._measure([
            _WALL,
            {"op": "create_group", "id": "G1", "placements": [[0, 0, 3000]],
             "members": [self._MEMBER_DOOR]}])

        # The precondition: without it everything below is green by
        # construction.
        self.assertTrue(backward_ok,
                        "ссылка НАЗАД внутри группы отвергнута — предмет "
                        "проверки исчез, и согласие заметки ни о чём")
        self.assertFalse(forward_ok, "ссылка ВПЕРЁД принята")
        self.assertFalse(outside_ok, "ссылка НАРУЖУ принята")

        note = " ".join(OP_NOTES["create_group"])

        # 1. A capability proven above cannot be declared dead.
        for lie in ("`by: ref` внутри группы не работает",
                    "ref` внутри группы не работает",
                    "член не видит соседние опы"):
            self.assertNotIn(
                lie, note,
                f"заметка утверждает {lie!r}, а компилятор ТОЛЬКО ЧТО принял "
                f"эту самую программу. Ровно эта ложь стоила модели основного "
                f"механизма сжатия здания и была найдена внешним аудитом")

        # 2. Both genuine prohibitions must be named — in words FROM THE
        #    REFUSALS THEMSELVES, so the test doesn't become a second
        #    opinion about the rule. The compiler marks the direction in
        #    CAPITALS; that's what we take, dropping the boilerplate
        #    next-move header that appears in every refusal.
        service = {"СЛЕДУЮЩИЙ", "ХОД"}

        def _emphasised(msg: str) -> set[str]:
            return {w.strip(".,:;!?«»()[]'\"") for w in msg.split()
                    if len(w) > 3 and w.strip(".,:;!?«»()[]'\"").isupper()
                    } - service

        for msg, direction in ((forward_msg, "вперёд"),
                               (outside_msg, "наружу")):
            words = _emphasised(msg)
            self.assertTrue(
                words,
                f"отказ {direction} перестал выделять направление заглавными — "
                f"выводить требование к заметке стало не из чего")
            self.assertTrue(
                any(w.lower() in note.lower() for w in sorted(words)),
                f"заметка не называет запрет {direction} ни одним словом из "
                f"самого отказа ({sorted(words)}), а компилятор его "
                f"применяет: автор узнает правило только отказом")

        # 3. A refusal must carry the next move — otherwise it costs a
        #    whole round trip (measured 16.08: 4 round trips per floor,
        #    17-18 s per round trip).
        self.assertIn("СЛЕДУЮЩИЙ ХОД", note,
                      "заметка называет два запрета и не говорит, что делать")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
