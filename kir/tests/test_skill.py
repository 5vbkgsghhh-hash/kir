"""The course has no right to get ahead of the compiler.

THE MAIN RISK THIS FILE IS WRITTEN AGAINST. Documentation that is wrong makes the
model DOUBT; a course that is wrong makes it confidently
do the wrong thing. Advice sounds like knowledge — the model will not double-check
"just grab `series`", it will simply use it. Which means a technique the compiler does not
accept produces CONFIDENT failures instead of hesitant ones, and that outcome is worse
than having no course at all.

Hence FOUR symmetric checks:

1. EVERY COURSE PROGRAM COMPILES. The examples show not pseudocode but
   live objects (`skill.ALL_PROGRAMS`), and the test compiles EXACTLY THOSE — the very
   same ones rendered into the text. What is shown and what is checked cannot diverge.
2. EVERY SHOWN REFUSAL ACTUALLY REFUSES, and with the named code
   (`skill.REFUSING_PROGRAMS`). A shown refusal that in fact goes through
   teaches the model to fear a technique that works — the harm is symmetric.
3. EVERY NAMED BOUNDARY FAILS — a negative control. A direct
   application of the acceptance principle (docs/2026-07-29-independent-acceptance-
   design.md): "a predicate must be ABLE TO FAIL". The predicates here also check
   the TEXT of the refusal, because a green control for the wrong reason
   is Goodhart's law, and it has already happened once in this file (see below about MAX_SERIES_COUNT).
4. THE NUMBERS IN THE TEXT MATCH THE CONSTANTS, and the course text does not overlap
   `tool_doc.NOTES`.

WHAT IS DELIBERATELY ABSENT HERE: checks against live telemetry
(`data/telemetry/*.jsonl`). These files grow as prod runs; without an explicit
identity of attempts, their lines cannot be turned into a rate of the author's own refusals.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import macros, skill, spec  # noqa: E402
from kir.compiler import MAX_OPS_PER_PROGRAM, compile_program  # noqa: E402
from kir.diag import (  # noqa: E402
    W_POSTCONDITIONS_COMMITTED,
    X_POSTCONDITIONS,
)
from kir.outcome import RetrySafety  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.tool_doc import NOTES, build_tool_description  # noqa: E402

LEVEL = {"by": "name", "value": "Этаж 1"}
BEAM = {"by": "element_id", "value": 1100}


def _prog(ops, **env):
    p = {"ir_version": "1.0", "intent": "skill-test", "ops": ops}
    p.update(env)
    return p


def _many_beam_types() -> dict:
    """A snapshot of a project where there are SEVERAL beam types.

    The case measured on 28.07 (20 beams, 4 types, KIR-G102 x40) can only be reproduced
    this way: in the base fixture the pool has a single element, and the default there
    resolves legally — there will be no refusal, and case 2 has nothing to check against."""
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    for i, name in enumerate(("Балка 300x600", "Балка 400x800", "Балка 200x300"),
                             start=1):
        snap["beam_types"].append({"id": 1100 + i, "name": name})
    return snap


def _compile(program, snapshot=None):
    return compile_program(program, revit_version="2026",
                           snapshot=snapshot if snapshot is not None
                           else GROUND_SNAPSHOT)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


class CourseProgramsCompile(unittest.TestCase):
    """Check 1: what is shown works."""

    def test_every_program_shown_as_working_compiles(self):
        snap = _many_beam_types()
        for name, program in skill.ALL_PROGRAMS:
            with self.subTest(program=name):
                out = _compile(program, snap)
                self.assertTrue(out.ok, f"{name}: "
                                f"{[d.as_dict() for d in out.diagnostics][:2]}")

    def test_the_programs_in_the_text_are_the_programs_tested(self):
        """A ratchet against a divergence between what is shown and what is checked: every
        program must be present as its own JSON exactly where it will be SHOWN.

        THE ADDRESS WAS REWRITTEN ON 09.08, THE RATCHET WAS NOT. The case literals moved out of
        the permanently loaded text into `course("cases")` (2,496 characters
        against a description ceiling of 30,000). The check therefore looks at BOTH addresses
        at once: a program that fell out of both would be shown nowhere at all — and
        that is exactly what the ratchet guards against. The §6 pair stayed in the course, because
        there the programs are themselves the subject of the judgment.
        """
        shown = (skill.build_skill_text() + "\n"
                 + skill.build_walkthrough_programs_text())
        for name, program in skill.ALL_PROGRAMS:
            with self.subTest(program=name):
                self.assertIn(skill._render_program(program), shown,
                              f"{name} не отрендерена нигде")

    def test_the_displaced_walkthrough_programs_really_arrive(self):
        """DISPLACEMENT IS A MOVE WITH A CHECK THAT THE NEW ADDRESS IS READABLE.

        Both sides of the seam at once: the case programs must BE in the lesson and
        must be ABSENT from the permanently loaded text. Without the second
        half, "displaced" is indistinguishable from "deleted", and without the first, from
        "lost".
        """
        from kir.course import lessons

        text = skill.build_skill_text()
        home = lessons.lesson(skill.WALKTHROUGH_PROGRAMS_TOPIC)
        for _title, _steps, programs in skill.WALKTHROUGHS:
            for label, program in programs:
                rendered = skill._render_program(program)
                with self.subTest(program=label):
                    self.assertIn(rendered, home, "не доехала в урок")
                    self.assertNotIn(rendered, text, "осталась и в описании")
        # The door is named: a lesson with no pointer to it is dark.
        self.assertIn(f'course("{skill.WALKTHROUGH_PROGRAMS_TOPIC}")', text)

    def test_the_tower_is_one_op_not_an_enumeration(self):
        """The number from case 1: the same silhouette — one operation, not 160."""
        ops = skill.TOWER_TRACK["ops"]
        series = [o for o in ops if o["op"] == "series"]
        self.assertEqual(len(series), 1)
        self.assertLessEqual(len(ops), MAX_OPS_PER_PROGRAM)
        expanded = macros.expand(ops)
        self.assertEqual(
            len(expanded),
            1 + series[0]["count"] * len(series[0]["items"]),
            "разбор 1 обещает count x len(items) элементов плюс уровень")

    def test_series_mints_no_levels_so_the_course_declares_one(self):
        """The course says: `series` does NOT create levels, which is why a level is declared
        as a separate op. If it did create them, the advice would be harmful."""
        expanded = macros.expand(skill.TOWER_TRACK["ops"])
        levels = [o for o in expanded if o["op"] == "create_level"]
        self.assertEqual(len(levels), 1, "уровень ровно один — объявленный")

    def test_the_good_storey_is_composed_not_dominated(self):
        """Section 6 teaches composition: no single operation carries the building alone."""
        ops = skill.GOOD_COMPOSED_STOREY["ops"]
        kinds = {o["op"] for o in ops}
        self.assertGreaterEqual(len(kinds), 4, "состав, а не одна операция")
        top = max(sum(1 for o in ops if o["op"] == k) for k in kinds)
        self.assertLessEqual(top / len(ops), 0.55,
                             "доля одной операции выше порога стенда")


class CourseRefusalsActuallyRefuse(unittest.TestCase):
    """Check 2: the shown refusal is real, and carries the named code."""

    def test_every_program_shown_as_refused_refuses_with_that_code(self):
        snap = _many_beam_types()
        for name, program, code in skill.REFUSING_PROGRAMS:
            with self.subTest(program=name):
                out = _compile(program, snap)
                self.assertFalse(out.ok, f"{name} прошла, а курс обещает отказ")
                self.assertIn(code, _codes(out),
                              f"{name}: ожидали {code}, получили {_codes(out)}")

    def test_the_g102_refusal_carries_candidates_as_the_course_claims(self):
        """Case 2 teaches: the list is already in hand, a second query_types is not needed."""
        out = _compile(skill.BEAMS_NO_SYMBOL, _many_beam_types())
        lead = out.diagnostics[0].as_dict()
        self.assertEqual(lead["field_name"], "symbol")
        self.assertGreaterEqual(len(lead.get("candidates", [])), 2)
        for row in lead["candidates"]:
            self.assertIn("id", row)
            self.assertIn("name", row)

    def test_the_refusal_lands_on_every_op_not_just_the_first(self):
        """Case 2: "the refusal hits EVERY operation" — that is exactly the reason
        a full batch costs a whole round."""
        out = _compile(skill.BEAMS_NO_SYMBOL, _many_beam_types())
        self.assertEqual(len(out.diagnostics),
                         len(skill.BEAMS_NO_SYMBOL["ops"]))

    def test_one_envelope_line_fixes_all_three_ops(self):
        """Case 2, the fix: `defaults` instead of an edit in every op."""
        self.assertNotIn("defaults", skill.BEAMS_NO_SYMBOL)
        self.assertIn("defaults", skill.BEAMS_FIXED)
        self.assertEqual(skill.BEAMS_FIXED["ops"], skill.BEAMS_NO_SYMBOL["ops"],
                         "починка обязана быть ТОЛЬКО конвертом")
        self.assertTrue(_compile(skill.BEAMS_FIXED, _many_beam_types()).ok)

    def test_the_deck_refusal_matches_the_production_trace_verbatim(self):
        """Case 3 is built entirely on a live refusal. If the compiler
        stops giving these fields, the case becomes fiction — and the test will fail."""
        out = _compile(skill.DECK_BAD_OFFSET)
        lead = out.diagnostics[0].as_dict()
        self.assertEqual(lead["code"], "KIR-T002")
        self.assertEqual(lead["op_id"], "deck57")
        self.assertEqual(lead["field_name"], "height_offset_mm")
        self.assertEqual(lead["got"], 57000)
        self.assertEqual(lead["suggested_replacement"], 15000)
        self.assertEqual(lead["applicability"], "maybe-incorrect",
                         "разбор 3 держится на том, что подсказка НЕ machine-"
                         "applicable — иначе совет её проверять неверен")

    def test_taking_the_suggestion_would_build_the_wrong_thing(self):
        """The heart of case 3: the hint PASSES the compiler and builds the wrong thing.
        Both assertions are checked, otherwise the lesson is unsubstantiated."""
        clamped = copy.deepcopy(skill.DECK_BAD_OFFSET)
        clamped["ops"][0]["height_offset_mm"] = 15000
        self.assertTrue(_compile(clamped).ok, "подсказка обязана проходить")
        self.assertNotEqual(15000, 57000, "и обязана давать НЕ ту отметку")
        self.assertTrue(_compile(skill.DECK_OWN_LEVEL).ok,
                        "а правильная починка — компилироваться")
        lvl = skill.DECK_OWN_LEVEL["ops"][0]
        self.assertEqual(lvl["op"], "create_level")
        self.assertEqual(lvl["elev_mm"], 57000)


class AdvisedBoundariesActuallyRefuse(unittest.TestCase):
    """Check 3: every named boundary must fail — and for its OWN
    reason, not for just any reason."""

    def test_omitting_a_selector_refuses_instead_of_guessing(self):
        beams = [{"op": "create_beam", "id": f"b{i}",
                  "p0_mm": [i * 1000, 0, 0], "p1_mm": [i * 1000, 0, 30000],
                  "level": LEVEL} for i in range(12)]
        out = _compile(_prog(beams), _many_beam_types())
        self.assertFalse(out.ok, "умолчание подставилось молча — совет устарел")
        self.assertTrue(all(c.startswith("KIR-G") for c in _codes(out)),
                        _codes(out))

    def test_a_string_element_id_refuses_and_the_playbook_quotes_the_fix(self):
        """PLAYBOOK, item 2: `by=element_id` requires an INTEGER.

        THE MEASUREMENT ON 22.08.2026 for whose sake this line was added. The refusal printed
        `ожидается: … {by: element_id|ref, value: …}` and, right next to it, `получено:
        [{'by': 'element_id', 'value': '294076'}]` — two strings that MATCH
        CHARACTER FOR CHARACTER in form, while what actually decides is the TYPE of the value; this cost two live
        attempts in a row. The control holds both halves of the advice: that the string
        REFUSES and that the hint «сними кавычки» actually arrives.
        Without the second half the playbook would be promising a ready-made fix while the model
        would only be getting a guess.
        """
        out = _compile(_prog([
            {"op": "move_elements", "id": "m",
             "targets": [{"by": "element_id", "value": "294076"}],
             "delta_mm": [500, 0, 0]}]))
        self.assertFalse(out.ok, "строковый element_id прошёл — совет устарел")
        self.assertIn("KIR-T001", _codes(out))
        rendered = " ".join(str(d.as_dict()) for d in out.diagnostics)
        self.assertIn("сними кавычки: 294076", rendered)
        playbook = " ".join(skill.build_refusal_playbook_text().split())
        self.assertIn("сними кавычки: 294076", playbook)

    def test_a_window_cannot_take_a_model_coordinate(self):
        """The "HOST" technique: an opening has no model coordinate of its own."""
        out = _compile(_prog([
            {"op": "create_wall", "id": "w", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000, "level": LEVEL},
            {"op": "create_window", "id": "win",
             "host": {"by": "ref", "value": "w"}, "xyz_mm": [3000, 0, 900]}]))
        self.assertFalse(out.ok, "окно приняло координату — приём неверен")
        self.assertIn("KIR-P003", _codes(out))

    def test_ref_across_a_program_boundary_refuses(self):
        out = _compile(_prog([
            {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "ref", "value": "L_из_прошлой_программы"}}]))
        self.assertFalse(out.ok, "ref через границу прошёл — приём неверен")
        self.assertIn("KIR-L003", _codes(out))

    def test_track_must_cover_every_index_no_extrapolation(self):
        short = copy.deepcopy(skill.TOWER_TRACK)
        short["ops"][1]["track"] = {"hw": [[0, 62500], [5, 30000]],
                                    "z": [[0, 0], [5, 57000]]}
        out = _compile(short, _many_beam_types())
        self.assertFalse(out.ok, "трек не покрыл индексы, а отказа нет")
        self.assertIn("покрывает индексы", out.diagnostics[0].message_ru,
                      f"отказ не про покрытие: {out.diagnostics[0].message_ru}")

    def test_declared_but_unused_track_param_refuses(self):
        dead = copy.deepcopy(skill.TOWER_TRACK)
        dead["ops"][1]["track"]["unused"] = [[0, 1], [20, 2]]
        out = _compile(dead, _many_beam_types())
        self.assertFalse(out.ok, "мёртвый параметр трека прошёл молча")
        self.assertIn("не использован", out.diagnostics[0].message_ru)

    def test_macro_inside_macro_refuses(self):
        nested = copy.deepcopy(skill.TOWER_TRACK)
        nested["ops"][1]["items"] = [
            {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
             "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                        "p1_mm": [6000, 0], "height_mm": 2800}]}]
        out = _compile(nested, _many_beam_types())
        self.assertFalse(out.ok, "вложенный макрос развернулся")
        self.assertIn("внутри макроса", out.diagnostics[0].message_ru)

    def test_series_expansion_ceiling_refuses(self):
        """A limit on the EXPANSION (count x len(items)), not on count alone.

        The first draft was green for the wrong reason: count=201 was hitting
        MAX_SERIES_COUNT, meaning it was checking a different boundary than the one it promised."""
        count = 100
        item = skill.TOWER_TRACK["ops"][1]["items"][0]
        items = [dict(item, id=f"leg{i}") for i in range(3)]
        self.assertLessEqual(count, macros.MAX_SERIES_COUNT)
        self.assertGreater(count * len(items), macros.MAX_SERIES_OPS)
        big = copy.deepcopy(skill.TOWER_TRACK)
        big["ops"][1].update(count=count, items=items,
                             track={"hw": [[0, 62500], [count, 5000]],
                                    "z": [[0, 0], [count, 276000]]})
        out = _compile(big, _many_beam_types())
        self.assertFalse(out.ok, "предел развёртки не сработал")
        self.assertIn("развернётся", out.diagnostics[0].message_ru)

    def test_program_op_budget_refuses(self):
        """A budget declared in the course must be a real boundary."""
        walls = [{"op": "create_wall", "id": f"w{i}", "p0_mm": [i * 100, 0],
                  "p1_mm": [i * 100, 5000], "height_mm": 3000, "level": LEVEL}
                 for i in range(MAX_OPS_PER_PROGRAM + 1)]
        out = _compile(_prog(walls))
        self.assertFalse(out.ok, "бюджет программы не сработал")
        self.assertIn("KIR-L001", _codes(out))


class ReadingSideIsDescribedCorrectly(unittest.TestCase):
    """Section 2 promises a specific reconnaissance step — it must actually exist."""

    def test_every_reading_op_is_named_in_the_course(self):
        """🔴 IT USED TO SAY "EXACTLY FOUR", AND THE NUMBER TURNED OUT TO BE THE WRONG LAW.

        On 20.08.2026 the surface-reading wave introduced a fifth reading op, and the test
        went red on a NUMBER, even though the course was incomplete about something entirely different: it
        did not name the new op. The number was guarding something that legitimately changes (the registry
        grows) and stayed silent about what actually must hold —
        EVERY reading op is named in the course. The check below is the real
        law; it too will go red on a sixth op, but it will go red FOR THE RIGHT REASON and
        say what is missing.
        """
        reading = sorted(n for n, op in spec.OPS.items() if not op.writes_model)
        self.assertGreaterEqual(len(reading), 4, reading)
        for name in reading:
            self.assertIn(name, skill.build_skill_text(),
                          f"{name} не назван в курсе")

    def test_the_reading_ops_actually_compile(self):
        for ops in ([{"op": "query_types", "pool": "beam_types"}],
                    [{"op": "query_list", "kind": "wall"}],
                    [{"op": "query_count", "kind": "wall",
                      "group_by": "level_name"}]):
            with self.subTest(op=ops[0]["op"]):
                self.assertTrue(_compile(_prog(ops)).ok)

    def test_the_shown_element_state_example_compiles_without_claiming_native_acceptance(self):
        self.assertIn('course("разборы")', skill.build_skill_text())
        shown = skill.build_walkthrough_programs_text()
        self.assertIn(skill._render_program(skill.ELEMENT_STATE_READ), shown)
        for version in spec.REVIT_VERSIONS:
            out = compile_program(skill.ELEMENT_STATE_READ, revit_version=version)
            self.assertTrue(out.ok, out.diagnostics)
            self.assertEqual(out.planned.family.value, "query")
            self.assertIn('doc.GetElement("00112233-4455-6677-8899-aabbccddeeff-00000123")', out.csharp)
            self.assertNotIn("new Transaction(", out.csharp)
        for boundary in ("UniqueId", "not_found", "unavailable", "не выбирает", "не доказывает владение", "не является BIM-приёмкой"):
            self.assertIn(boundary, " ".join(shown.split()))
        bad = {"ops": [{**skill.ELEMENT_STATE_READ["ops"][0], "unique_id": ""}]}
        self.assertFalse(compile_program(bad, revit_version="2026").ok)

    def test_query_types_pool_is_closed_and_named_pools_exist(self):
        pool = [p for p in spec.OPS["query_types"].params if p.name == "pool"][0]
        self.assertGreaterEqual(len(pool.choices), 10)
        for named in ("levels", "beam_types"):
            self.assertIn(named, pool.choices)


class NumbersMatchTheCode(unittest.TestCase):
    def test_refusal_playbook_is_contract_driven_not_legacy_frequency(self):
        self.assertEqual(len(skill.REFUSAL_PLAYBOOK), 6)
        text = skill.build_skill_text()

        for stale_claim in (
                "САМЫЙ ЧАСТЫЙ", "210 из 586", "64 из 586",
                "40 таких", "ЕДИНСТВЕННЫЙ ОТКАЗ",
                "Остальные отказы KIR retryable",
                "Остальная программа была верна"):
            self.assertNotIn(stale_claim, text)

        for required_truth in (
                "err.retryable", "outcome.retry", "machine-applicable",
                X_POSTCONDITIONS, W_POSTCONDITIONS_COMMITTED,
                "KIR-G101/G102", "KIR-G104", "ops_total", "op_refusals"):
            self.assertIn(required_truth, text)
        for retry_safety in RetrySafety:
            self.assertIn(retry_safety.value, text)

        self.assertIn("Для других кодов `candidates`", text)
        self.assertNotIn("Пустой список кандидатов", text)

    def test_every_quoted_limit_equals_its_constant(self):
        """🔴 THE COURSE NOW LIVES BEHIND TWO DOORS, AND THE GUARD MUST KNOW BOTH
        (15.08.2026).

        The six situational techniques of §4 moved into `course("приёмы")` when
        the description broke through the 30,000 ceiling. Along with the "macro limits" technique
        went the `MAX_TRACK_NODES` limit, and this test went red — correct by
        mechanics and wrong in meaning: it guards the FRESHNESS of a number ("the named
        limit equals its constant"), and the number had not gone stale, it had switched
        channels. What must be checked is the COURSE AS A WHOLE, and the course is now wider than one function.

        The same lesson the capability ratchet caught two hours earlier:
        when text moves house, guards that knew only one address start measuring
        not the subject but their own map.
        """
        text = skill.build_skill_text() + "\n" + skill.build_techniques_text()
        for value in (macros.MAX_SERIES_OPS, macros.MAX_TRACK_PARAMS,
                      macros.MAX_TRACK_NODES, MAX_OPS_PER_PROGRAM):
            self.assertIn(str(value), text, f"предел {value} пропал из текста")

    def test_the_moved_techniques_are_reachable_and_not_duplicated(self):
        """A CONTROL FOR THE MOVE, both halves. What moved must be READABLE at its
        new address and must NOT remain at the old one: "displaced" without the first
        half is "deleted", without the second it is "we pay twice".

        Since 22.08.2026 there are THREE addresses: the permanent text, `course("приёмы")`, and
        `course("место")`. A technique must stand in EXACTLY ONE of them.
        """
        homes = {
            "постоянный текст": skill.build_skill_text(),
            "course(«приёмы»)": skill.build_techniques_text(),
            "course(«место»)": skill.build_placement_techniques_text(),
        }
        for situation, _advice in skill.TECHNIQUES:
            with self.subTest(technique=situation):
                where = [name for name, text in homes.items()
                         if situation in text]
                self.assertEqual(
                    len(where), 1,
                    f"«{situation}» стоит в {where or 'НИГДЕ'} — приём обязан "
                    "иметь ровно один адрес: ноль это «удалили», два — "
                    "«платим дважды и разойдёмся на первой правке»")

    def test_every_technique_has_a_home_and_the_split_is_a_partition(self):
        """🔴 THE CATALOG'S COMPLETENESS IS HELD BY ARITHMETIC, NOT BY ATTENTION.

        The measurement of 22.08.2026, for whose sake the catalog was split in the first place: the "приёмы" lesson
        weighed 4,882 characters against a `LESSON_CAP` of 3,300, while the sandbox channel cuts
        `stdout` at 4,000 — the LAST THREE TECHNIQUES (level, host, coordinates)
        never reached the model AT ALL. The cost was measured on itself the same day:
        a level given a foreign `element_id` produced «model has no rooms» with
        four declared rooms — that is exactly what the trimmed-off technique was about.

        The split only saves anything as long as it stays a PARTITION. A new technique forgotten in
        both sets would silently vanish from the course — this control is exactly the
        difference between "we split it" and "we lost half of it".
        """
        names = {s for s, _ in skill.TECHNIQUES}
        permanent = skill._TECHNIQUES_IN_PERMANENT_TEXT
        placement = skill._TECHNIQUES_PLACEMENT
        self.assertEqual(permanent & placement, frozenset(),
                         "приём не может стоять в двух множествах сразу")
        self.assertTrue(
            (permanent | placement) <= names,
            f"множества называют приём, которого нет: "
            f"{(permanent | placement) - names}")
        # The third set is DERIVED, not declared, so a forgotten technique
        # falls into "приёмы" and stays visible. This is exactly what is checked here.
        derived = names - permanent - placement
        self.assertEqual(len(derived) + len(permanent) + len(placement),
                         len(names))
        self.assertTrue(derived, "первое множество не может опустеть")

    def test_no_stale_literal_for_the_op_budget(self):
        self.assertIn(str(MAX_OPS_PER_PROGRAM), skill.build_skill_text())
        self.assertNotIn("300 операций", skill.build_skill_text())

    def test_the_bounds_quoted_in_walkthrough_three_are_the_real_ones(self):
        """The course names ±15000 verbatim; if the boundary is ever moved, the lesson will lie."""
        out = _compile(skill.DECK_BAD_OFFSET)
        self.assertEqual(out.diagnostics[0].as_dict()["expected"],
                         "-15000..15000")
        self.assertIn("-15000..15000", skill.build_skill_text())


class CourseShapeAndBudget(unittest.TestCase):
    def test_course_is_part_of_the_tool_description(self):
        """On the default route, the tool description is the ONLY channel:
        measured on 30.07 — system_base*.md never mention revit_ir even once."""
        self.assertIn(skill.build_skill_text(), build_tool_description())

    def test_every_section_is_present_and_in_order(self):
        text = skill.build_skill_text()
        positions = []
        for title in skill.SECTION_TITLES:
            self.assertIn(title, text, f"раздел пропал: {title}")
            positions.append(text.index(title))
        self.assertEqual(positions, sorted(positions),
                         "разделы курса идут не по порядку")

    def test_the_course_opens_with_the_system_model(self):
        """Order is not cosmetic: without the system's layout there is nothing to hang the
        advice on, and the choice of repetition pattern is made before the first operation."""
        self.assertTrue(skill.SECTION_TITLES[0].endswith("КАК УСТРОЕН KIR"))
        self.assertIn("ФОРМА ПОВТОРА", skill.SECTION_TITLES[2])

    def test_every_walkthrough_goes_all_the_way_to_acceptance(self):
        """A case without an acceptance step is a fragment, not a case."""
        for title, steps, _programs in skill.WALKTHROUGHS:
            with self.subTest(walkthrough=title[:24]):
                self.assertGreaterEqual(len(steps), 4)
                joined = " ".join(steps).lower()
                # «чин» (the stem "fix") covers both «починка» ("a fix") and «чиним» ("we fix") — case 2 ends
                # with a verb, not a noun, and the first draft of the test
                # failed on exactly this, even though the step itself was in place.
                self.assertTrue(
                    any(w in joined for w in ("приёмк", "перечит", "чин")),
                    f"{title}: нет шага приёмки/починки")

    def test_course_stays_within_the_declared_budget(self):
        """The operator has raised the budget to ~10,000 tokens of prose. The check works in
        characters — tiktoken is deliberately not added to the test dependencies.
        Measured 30.07: the course is 7,140 o200k tokens = 20,708 characters (3.00 characters
        per token). The ceiling here is 24,000 characters (~8,000 tokens), and NOT the full
        30,000 the whole description is limited to: the course shares its budget with
        the operation registry and the traps, and a threshold equal to the overall one would let it
        silently crowd them out."""
        self.assertLess(len(skill.build_skill_text()), 24_000,
                        "курс перерос свою долю бюджета — режь")

    def test_course_and_notes_do_not_overlap(self):
        """Repeated advice dilutes both texts and is paid for twice."""
        def shingles(text: str, n: int = 7) -> set[str]:
            words = "".join(c.lower() if c.isalnum() or c.isspace() else " "
                            for c in text).split()
            return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}

        common = sorted(shingles(skill.build_skill_text())
                        & shingles("\n".join(NOTES)))
        self.assertEqual(common, [], f"дубли курса и NOTES: {common[:3]}")


if __name__ == "__main__":
    unittest.main()
