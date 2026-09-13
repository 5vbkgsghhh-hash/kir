"""THE ENVIRONMENT ANSWERS ON ITS OWN: a verdict on what was declared rides
in the receipt without being asked.

🔴 WHY THIS GATE WAS SET UP (01.09.2026).

The sandbox's guide tells the model, verbatim: "`preview()` is the plan as
text; `design_check()` is a verdict on the design's soundness without
Revit. Both are SELF-CHECKS, call them BEFORE submitting." A measurement
over the owner's live feed `kir_course_uptake.jsonl` (323 scripts, window
23–26.08.2026):

    spec          called in  49 scripts
    course                   58
    design_check              3        <- verdict before submission
    preview                   1
    score                     0

That is, the channel that is supposed to be CALLED does not work: the
capability is built, declared in the persistent text, and not consumed.
The constitution's main metric — "how many times did checkability CHANGE
the model's decision" — sits at 17 out of 560 turns on the same owner's
feeds.

Hence the fix: the environment answers ON ITS OWN, without being asked, and
puts the answer where the model already reads — in the receipt, at its
HEAD, next to the rehearsal.

═══ WHAT EXACTLY IS GUARDED, AND WHY FOUR ASSERTIONS, NOT ONE ═══

1. THERE IS AN ANSWER ON EVERY PROGRAM. Not "on average," but by name,
   across the corpus.
2. SILENCE IS NAMED. If there is no `verdict` key ⇒ there must be a
   `silent_because`. Otherwise "judged and found nothing" is
   indistinguishable from "did not judge" — a named defect of this tree
   (a false zero), and here it would sit right on the model's feedback.
3. THE ANSWER SURVIVES TRIMMING. The receipt gets trimmed; the line that
   gets trimmed first must not have changed any of the author's subsequent
   lines.
4. THE READ LEDGER STAYS THE AUTHOR'S. The auto-answer has no right to land
   in `course.reads_ledger()`: otherwise "3 out of 323" would become
   "323 out of 323" BY CONSTRUCTION, and the very subject of the
   measurement would vanish along with the finding.

═══ WHAT THIS TEST DOES NOT DO, AND THIS IS NAMED ═══

It does NOT replay those very same 323 live scripts. They cannot be
replayed by any instrument: the feed carries a `source_digest`, not the
source (the row's fields are `v, ts, source_digest, ok, code, op_count,
stdout_chars, calls, chars, reads, turn_id, query_id, origin`). The 3/323
measurement is reproducible as a NUMBER, but not as a run. So the corpus
here is the goldens (`test_golden.PROGRAMS`), that is, roughly one program
per registry operation, and this is a SUBSTITUTION, declared as a
substitution.

It does NOT assert that the verdict is CORRECT. The correctness of the
judge is guarded by `kir/checker`; here what is guarded is only that the
answer ARRIVES and that silence is named.
"""
from __future__ import annotations

import unittest

from kir import serving
from kir.tests.test_golden import PROGRAMS


def _program_of(entry) -> dict | None:
    """A program from a golden-corpus record, in whatever form it happens
    to be stored.

    We do not guess the form: the corpus has changed its shell twice over
    the year, and a test that knows exactly one would go red on a change of
    shell, not on a change of subject.
    """
    if isinstance(entry, dict):
        if isinstance(entry.get("program"), dict):
            return entry["program"]
        if isinstance(entry.get("ops"), list):
            return entry
    prog = getattr(entry, "program", None)
    if isinstance(prog, dict):
        return prog
    ops = getattr(entry, "ops", None)
    if isinstance(ops, list):
        return {"ops": ops}
    return None


def _corpus() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    items = PROGRAMS.items() if isinstance(PROGRAMS, dict) else enumerate(PROGRAMS)
    for name, entry in items:
        prog = _program_of(entry)
        if prog is not None:
            out.append((str(name), prog))
    return out


class СредаОтвечаетБезСпроса(unittest.TestCase):

    def setUp(self) -> None:
        self.corpus = _corpus()
        # THE DENOMINATOR FIRST. "0 without an answer out of 0 programs" and
        # "0 out of 70" print identically and mean the opposite.
        self.assertGreater(len(self.corpus), 40,
                           "корпус голденов не собрался — число ниже есть "
                           "факт О ТЕСТЕ, а не о продукте")

    def test_каждая_программа_корпуса_получает_ответ(self):
        """THE ANSWER IS EVERYWHERE. Counted by name, not as a fraction."""
        немые: list[str] = []
        с_вердиктом = 0
        for name, prog in self.corpus:
            квитанция = serving._stamp_self_check({"ok": True}, prog)
            блок = квитанция.get("self_check")
            if not isinstance(блок, dict):
                немые.append(f"{name}: блока нет вовсе")
                continue
            if блок.get("verdict"):
                с_вердиктом += 1
            elif not блок.get("silent_because"):
                немые.append(f"{name}: ни вердикта, ни названной причины")
            if not квитанция.get("self_check_note_ru"):
                немые.append(f"{name}: блок есть, строки модели нет")
        self.assertEqual(немые, [],
                         f"без ответа: {len(немые)} из {len(self.corpus)}")
        # The number is always printed: "everyone answered" without a
        # denominator is unreadable.
        self.assertGreater(с_вердиктом, 0,
                           f"вердикт не получила НИ ОДНА программа из "
                           f"{len(self.corpus)} — это отказ прибора, а не "
                           f"свойство корпуса")

    def test_читаемая_программа_получает_вердикт_а_не_молчание(self):
        """A DIFFERENTIATING CASE. Without it, "everyone answered" is green
        and empty.

        🔴 WHY EXACTLY THIS PAIR. A run on 01.09 over 73 goldens: ONE gets
        a verdict (`full_house_v1`), the other 72 get named silence, "the
        judge applied no rules." This is correct and not a defect: the
        goldens pin down the EMISSION of one operation at a time, not a
        building. But a test that sees only "there is an answer" would also
        pass if the judge fell silent ON EVERYTHING — that is, it would not
        distinguish a working instrument from a broken one.

        That is why there is here an apartment the judge KNOWS how to read:
        its own level and room are declared by the same program. It must
        get a NUMBER of applied rules greater than zero.
        """
        L = {"by": "name", "value": "Этаж 1"}
        квартира = {"ops": [
            {"op": "create_level", "id": "L1", "name": "Этаж 1", "elev_mm": 0},
            {"op": "create_wall", "id": "w1", "level": L,
             "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000},
            {"op": "create_wall", "id": "w2", "level": L,
             "p0_mm": [6000, 0], "p1_mm": [6000, 4000], "height_mm": 3000},
            {"op": "create_wall", "id": "w3", "level": L,
             "p0_mm": [6000, 4000], "p1_mm": [0, 4000], "height_mm": 3000},
            {"op": "create_wall", "id": "w4", "level": L,
             "p0_mm": [0, 4000], "p1_mm": [0, 0], "height_mm": 3000},
            {"op": "create_room", "id": "r1", "level": L,
             "xy": [3000, 2000], "name": "Кухня"},
        ]}
        блок = serving._self_check_block(квартира)
        self.assertIsInstance(блок, dict)
        self.assertNotIn("silent_because", блок,
                         "судья читает эту программу — молчать ему не о чем")
        self.assertGreater(блок.get("rules_applied") or 0, 0)
        self.assertEqual(блок.get("read", {}).get("walls"), 4,
                         "в ответе обязано стоять ПРОЧИТАННОЕ: без него "
                         "«правил N из 20» неотличимо от пустой программы")

    def test_немота_судьи_не_подаётся_приговором(self):
        """A PLAUSIBLE NUMBER IS MORE DANGEROUS THAN ZERO — and here it
        would have been a verdict.

        Before the 01.09 fix, a program of four walls with no level of its
        own got `blocking: HAB000` with `rules 0 out of 20`. HAB000 says
        "model has no rooms; nothing was verified" — the judge had NOT READ
        the program. The model builds a building IN PARTS per Revit's own
        law (`create_stairs` must be the sole op of its program), meaning a
        blocking verdict would have reached the author of a correct partial
        program — on the receipt's most readable line.
        """
        L = {"by": "name", "value": "чужой уровень открытой модели"}
        частичная = {"ops": [
            {"op": "create_wall", "id": "w1", "level": L,
             "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000}]}
        блок = serving._self_check_block(частичная)
        self.assertIn("silent_because", блок)
        self.assertEqual(блок.get("blocking"), None,
                         "немота судьи не имеет права ехать как блокирующая "
                         "находка")
        строка = serving._self_check_note_ru(блок)
        self.assertNotIn("блокирующие", строка)
        self.assertIn("не прочитал", строка)

    def test_контроль_различает_отсутствие_ответа(self):
        """THE FLIP SIDE. The gate must go red when there is no answer.

        Without this assertion, the previous one is green by construction:
        a test that cannot go red guards nothing. Here the patch ITSELF is
        removed — that is, the state of the tree BEFORE the fix is
        reproduced — and it is checked that the count of silent ones
        becomes equal to the corpus.
        """
        было = serving._self_check_block
        try:
            serving._self_check_block = lambda program: None   # the state BEFORE
            немые = [name for name, prog in self.corpus
                     if "self_check" not in serving._stamp_self_check(
                         {"ok": True}, prog)]
        finally:
            serving._self_check_block = было
        self.assertEqual(len(немые), len(self.corpus),
                         "снятый штамп обязан оставить БЕЗ ОТВЕТА весь корпус")
        # AND THE RETURN: the same program answers once the patch is
        # restored.
        имя, prog = self.corpus[0]
        self.assertIn("self_check",
                      serving._stamp_self_check({"ok": True}, prog),
                      f"штамп восстановлен, а ответа нет: {имя}")

    def test_молчание_называет_причину(self):
        """Three legitimate reasons to be silent — and all three SPEAK
        UP."""
        # 1. The ceiling is exceeded.
        блок = serving._self_check_block(
            {"ops": [{"op": "create_wall"}] * (serving._SELF_CHECK_OPS_CAP + 1)})
        self.assertIn("silent_because", блок)
        self.assertIn(str(serving._SELF_CHECK_OPS_CAP), блок["silent_because"])
        self.assertTrue(
            serving._self_check_note_ru(блок).startswith("САМОПРОВЕРКА НЕ СОСТОЯЛАСЬ"),
            "молчание обязано читаться как молчание, а не как вердикт")
        # 2. There is no program at all — there is no block either, and
        #    this is NOT silence: there is nothing to judge, and inventing
        #    a reason would be noise.
        self.assertIsNone(serving._self_check_block({"ops": []}))
        self.assertIsNone(serving._self_check_block(None))
        # 3. The judge crashed — the turn does not break, the reason is
        #    named.
        было = serving._SELF_CHECK_OPS_CAP
        try:
            блок = serving._self_check_block({"ops": [{"op": "нет_такого_опа"}]})
        finally:
            serving._SELF_CHECK_OPS_CAP = было
        self.assertIsInstance(блок, dict)
        self.assertTrue(блок.get("verdict") or блок.get("silent_because"),
                        "неизвестный оп обязан дать либо вердикт, либо "
                        "названную причину — но не пустоту")

    def test_ответ_стоит_в_голове_квитанции(self):
        """SURVIVES TRIMMING. Otherwise only someone who was not trimmed
        would ever read it."""
        for ключ in ("self_check", "self_check_note_ru", "verdict_silent_because"):
            self.assertIn(ключ, serving._RECEIPT_ORDER_HEAD, ключ)
        # And the order: the answer MUST come before `building`, which
        # weighs 86% of the receipt and is trimmed first.
        квитанция = serving._order_receipt(
            {"building": {"x": 1}, "self_check_note_ru": "с", "ok": True})
        ключи = list(квитанция)
        self.assertLess(ключи.index("self_check_note_ru"), ключи.index("building"))

    def test_штамп_стоит_на_каждой_двери(self):
        """WIRING, NOT A FUNCTION. Otherwise the gate cannot tell whether it
        is even present.

        🔴 FORM 33 OF THIS TREE, AND IT WAS BOUGHT ELSEWHERE. "Five tests of
        that gate were reading the lock. The gate's call was pulled out of
        `main()` — all five stayed green: the control did not distinguish
        its PRESENCE." All the checks above call `_stamp_self_check` BY
        HAND and so will survive its removal from all three door chains.

        THE RULE IS DERIVED, NOT ENUMERATED. The list of doors is not
        written here by name: it would drift out of sync with the code at
        the very first new door, and it would drift SILENTLY. What is
        asked is a PROPERTY: **wherever the rehearsal is placed on the
        receipt, the self-check must stand there too**. Both answer the
        same question from the author ("what's wrong with what I wrote")
        and both are available before submission; a door that got one
        without the other shows only half.
        """
        import ast
        import inspect

        дерево = ast.parse(inspect.getsource(serving))
        одинокие: list[str] = []
        for узел in ast.walk(дерево):
            if not isinstance(узел, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for ret in [n for n in ast.walk(узел) if isinstance(n, ast.Return)]:
                if ret.value is None:
                    continue
                имена = {n.id for n in ast.walk(ret.value)
                         if isinstance(n, ast.Name)}
                if "_stamp_rehearsal" in имена and "_stamp_self_check" not in имена:
                    одинокие.append(f"{узел.name}:{ret.lineno}")
        self.assertEqual(одинокие, [],
                         "репетиция ставится, самопроверка — нет: "
                         + ", ".join(одинокие))
        # THE DENOMINATOR. "0 lonely out of 0 spots" and "0 out of 3" print
        # identically.
        источник = inspect.getsource(serving)
        self.assertGreaterEqual(источник.count("_stamp_self_check("), 4,
                                "штамп обязан стоять в трёх цепочках дверей "
                                "плюс собственное определение")

    def test_автоответ_не_трогает_ведомость_автора(self):
        """THE NUMBER "3 OUT OF 323" STAYS COMPARABLE WITH TOMORROW'S.

        The most expensive possible outcome of this fix is not breakage but
        DESTROYING THE SUBJECT OF THE MEASUREMENT: an auto-answer that
        landed in the read ledger would make "design_check was called" true
        for every turn, and the finding "3 out of 323" would cease to exist
        along with the ability to check whether the fix helped.

        This holds BY CONSTRUCTION, not by discipline: the patch lives at
        the parent and calls `design_check.check_ops` directly, bypassing
        `kir.course`.
        """
        from kir import course
        course.reset_reads()
        _имя, prog = self.corpus[0]
        serving._stamp_self_check({"ok": True}, prog)
        self.assertEqual(course.reads_ledger(), [],
                         "автоответ попал в ведомость АВТОРА — предмет замера "
                         "уничтожен")


if __name__ == "__main__":
    unittest.main()
