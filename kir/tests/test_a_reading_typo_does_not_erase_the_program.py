"""A question to REFERENCE DOCS has no right to erase a program already written.

🔴 MEASURED 25.08.2026, BY RUNNING THROUGH THE SANDBOX. A script builds
three walls and, on its last line, asks a reference lookup with ONE wrong
letter:

    control: without a lookup       ok=True   ops 3
    control: spec correct name      ok=True   ops 3
    EXPERIMENT: spec("create_walll")   ok=False  ops 0   KIR-P002
    EXPERIMENT: course("стеныy")       ok=False  ops 0   KIR-B006
    EXPERIMENT: recipe("однушкаа")     ok=False  ops 0   KIR-B006

Three already-built walls are erased by a question to DOCUMENTATION. At
`program_py`'s budget of 300 operations, the cost of a miss is the turn's
entire program.

THE ARGUMENT HAD ALREADY BEEN WRITTEN BY THE AUTHOR AND NEVER CARRIED
THROUGH. The `_op_spec_of` docstring, verbatim: "the cost of a refusal here
is HIGH: `spec` raises a refusal, the refusal drops the whole turn, and the
program assembled up to this line never goes out. Dropping the turn on a
reference-lookup question because of the ARGUMENT'S SHAPE is a bad trade."
Exactly the same trade applies to a NAME too, and it is worse: a typo is
more likely than a malformed argument.

WHY PRINTING IS SAFE, AND NOT MERELY "SOFTER." All three calls PRINT and
return `None` — this is recorded in their docstrings as the design. So
further down the script there is NO VALUE that could turn out wrong: a
successful lookup and a miss return the same thing. What changes is only
whether the program gets through.

WHAT DOES NOT CHANGE, AND IS CHECKED RIGHT HERE:
  · the miss's text reaches the model IN FULL, with the list of names;
  · the name is not guessed at — a "similar op" is not silently substituted;
  · the miss is visible IN THE STRUCTURE of the receipt (`course_reads`),
    not only in prose: printed text and a printed REFUSAL are otherwise
    indistinguishable to a machine;
  · an error in a BUILDING call still drops the turn — "soft" did not
    become everything.
"""
from __future__ import annotations

import unittest

from kir.sandbox import execute_author_script

СТЕНЫ = (
    'create_wall(p0_mm=[0,0], p1_mm=[6000,0], height_mm=3000, level="default")\n'
    'create_wall(p0_mm=[6000,0], p1_mm=[6000,4000], height_mm=3000, level="default")\n'
    'create_wall(p0_mm=[6000,4000], p1_mm=[0,4000], height_mm=3000, level="default")\n'
)


class ПромахИмениНеСтираетПрограмму(unittest.TestCase):

    def _прогон(self, хвост: str):
        return execute_author_script(СТЕНЫ + хвост)

    # ── controls: the instrument must tell the pair apart ────────────────

    def test_контроль_без_чтения_программа_доезжает(self) -> None:
        r = self._прогон("")
        self.assertTrue(r.ok)
        self.assertEqual(len(r.ops), 3)

    def test_контроль_верное_имя_программа_доезжает(self) -> None:
        r = self._прогон('spec("create_wall")\n')
        self.assertTrue(r.ok, msg=getattr(r.refusal, "message_ru", ""))
        self.assertEqual(len(r.ops), 3)
        self.assertIn("create_wall", r.stdout)

    # ── the subject: three read-only calls ────────────────────────────────

    def test_spec_с_опечаткой_не_стирает_программу(self) -> None:
        r = self._прогон('spec("create_walll")\n')
        self.assertTrue(r.ok, msg=(
            "промах ИМЕНИ в справке снял весь ход: "
            + (getattr(r.refusal, "message_ru", "") or "")[:200]))
        self.assertEqual(len(r.ops), 3, "три стены обязаны доехать")
        self.assertIn("create_walll", r.stdout, "промах назван дословно")
        self.assertIn("create_wall", r.stdout, "кандидаты названы")

    def test_course_с_опечаткой_не_стирает_программу(self) -> None:
        r = self._прогон('course("стеныy")\n')
        self.assertTrue(r.ok, msg=(
            "промах ИМЕНИ урока снял весь ход: "
            + (getattr(r.refusal, "message_ru", "") or "")[:200]))
        self.assertEqual(len(r.ops), 3)
        self.assertIn("квартира", r.stdout, "список уроков назван")

    def test_recipe_с_опечаткой_не_стирает_программу(self) -> None:
        r = self._прогон('recipe("однушкаа")\n')
        self.assertTrue(r.ok, msg=(
            "промах ИМЕНИ рецепта снял весь ход: "
            + (getattr(r.refusal, "message_ru", "") or "")[:200]))
        self.assertEqual(len(r.ops), 3)
        self.assertIn("санузел", r.stdout, "список рецептов назван")

    # ── a miss must be visible to the MACHINE, not only to the eye ────────

    def test_промах_помечен_в_ведомости_чтения(self) -> None:
        r = self._прогон('spec("create_walll")\n')
        промахи = [с for с in r.course_reads if с.get("refused")]
        self.assertEqual(len(промахи), 1, msg=(
            "напечатанный ОТВЕТ и напечатанный ПРОМАХ обязаны различаться в "
            f"структуре, а не только прозой. Ведомость: {r.course_reads}"))
        self.assertEqual(промахи[0]["call"], "spec")

    def test_верное_чтение_промахом_не_помечено(self) -> None:
        """A control on the previous one: the marker must be able to NOT be present."""
        r = self._прогон('spec("create_wall")\n')
        self.assertEqual([с for с in r.course_reads if с.get("refused")], [])

    # ── the boundary: "soft" did NOT become everything ────────────────────

    def test_ошибка_в_строящем_вызове_по_прежнему_снимает_ход(self) -> None:
        """FAIL CONTROL on the fix itself.

        If the fix had softened ANY error, it would have turned a
        partially executed script into "success" with a truncated
        program — exactly the silent-and-wrong outcome the language was
        written to forbid. A read-only call is special in that it has no
        OUTPUT VALUE; a building call does.
        """
        r = self._прогон('create_wall(p0_mm=[0,0])\n')
        self.assertFalse(r.ok, "неполный СТРОЯЩИЙ вызов обязан снимать ход")


if __name__ == "__main__":
    unittest.main()
