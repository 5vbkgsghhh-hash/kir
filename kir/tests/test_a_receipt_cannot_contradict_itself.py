""""EITHER OPERATIONS OR A REFUSAL. THERE IS NO THIRD OPTION" — WAS A PROMISE, BECAME A CONSTRUCTION.

🔴 MEASURED 02.09.2026. The `SandboxResult` docstring asserted "there is no
third," while a third was being built silently — all FOUR impossible shapes:

    ok=True  + a refusal          a green receipt WITH A REFUSAL INSIDE
    ok=True  + zero operations    "succeeded," having built NOTHING
    ok=False + no refusal         "failed," without naming a CAUSE
    a refusal + operations        a failed turn hands back a PROGRAM

The first is a false-green receipt in pure form, and it is the costliest
kind in this tree: it labels 31 of 75 open P0s ("silent_wrong_result",
"false-green witness", "false_green_instrument").

WHAT IS LEGITIMATE WAS MEASURED, NOT DERIVED. Fifteen real scripts (nine
course recipes, empty, read-only, a forbidden import, broken syntax, a
language refusal) produced EXACTLY TWO shapes: `(ok, no refusal, with
operations)` and `(not ok, with a refusal, no operations)`. Neither an
empty program nor a reconnaissance turn turned out to be an exception —
they have THEIR OWN named refusals (`KIR-B007` "the program is empty,"
`KIR-B013` "a reconnaissance turn"), and a silent green here would
substitute for both of them.

THE CHECK STANDS IN THE CONSTRUCTOR, NOT AT THE CONSUMER. There are many
consumers of the receipt (`serving`, the `program_py` door, tests, other
doors), and a rule living at one of them does not help another.
"""
from __future__ import annotations

import unittest

from kir.sandbox import (SandboxRefusal, SandboxResult,
                         SandboxResultContradiction)


def _отказ(code: str = "KIR-B004") -> SandboxRefusal:
    return SandboxRefusal(code=code, message_ru="проба", kind="Проба",
                          blame="author", line=1, line_text="",
                          script_frames=(), detail={})


class ЧетыреНевозможныеФормыНеСтроятся(unittest.TestCase):

    def test_зелёная_с_отказом_внутри(self) -> None:
        with self.assertRaises(SandboxResultContradiction) as e:
            SandboxResult(ok=True, ops=[{"op": "create_level"}],
                          refusal=_отказ())
        self.assertIn("ложно-зелёная", str(e.exception))
        self.assertIn("KIR-B004", str(e.exception),
                      "отказ обязан НАЗВАТЬ код, который прятался внутри")

    def test_получилось_построив_ничего(self) -> None:
        with self.assertRaises(SandboxResultContradiction) as e:
            SandboxResult(ok=True, ops=[])
        self.assertIn("KIR-B007", str(e.exception),
                      "отказ обязан назвать НАЗВАННЫЕ отказы, которые эта "
                      "форма подменяет")

    def test_красная_без_причины(self) -> None:
        with self.assertRaises(SandboxResultContradiction) as e:
            SandboxResult(ok=False, ops=[])
        self.assertIn("НЕ НАЗЫВАЕТ причины", str(e.exception))

    def test_отказавший_ход_не_отдаёт_программу(self) -> None:
        with self.assertRaises(SandboxResultContradiction) as e:
            SandboxResult(ok=False, ops=[{"op": "create_level"}],
                          refusal=_отказ())
        self.assertIn("не отдаёт программу", str(e.exception))


class ДвеЗаконныеФормыСТРОЯТСЯ(unittest.TestCase):
    """PASS control: a guard that rejects everything guards itself, not the shape."""

    def test_построено(self) -> None:
        r = SandboxResult(ok=True, ops=[{"op": "create_level"}])
        self.assertTrue(r.ok)
        self.assertEqual(len(r.ops), 1)

    def test_отказано(self) -> None:
        r = SandboxResult(ok=False, refusal=_отказ("KIR-B007"))
        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, "KIR-B007")


class ЖивойХодДаётТОЛЬКОЭТИДВЕФОРМЫ(unittest.TestCase):
    """The measurement on which the invariant is built — by running, not by reasoning."""

    СКРИПТЫ = (
        ("построено", 'create_level(elev_mm=0, name="Этаж 1")\n'),
        ("пустой", "pass\n"),
        ("только чтение", 'course("геометрия")\n'),
        ("запрещённый импорт", "import socket\n"),
        ("сломанный синтаксис", "def (\n"),
    )

    def test_ни_один_живой_ход_не_даёт_третьей_формы(self) -> None:
        from kir import sandbox

        формы = set()
        for имя, src in self.СКРИПТЫ:
            r = sandbox.execute_author_script(src)
            формы.add((r.ok, r.refusal is None, bool(r.ops)))
        # THE DENOMINATOR: an empty set would pass the check vacuously
        self.assertGreaterEqual(len(self.СКРИПТЫ), 5)
        self.assertEqual(
            формы, {(True, True, True), (False, False, False)},
            "живой ход дал форму, которой конструктор не допускает — значит "
            "инвариант поставлен НЕ по замеру")


class ПротиворечивыйОтветРебёнкаСТАНОВИТСЯОТКАЗОМ(unittest.TestCase):
    """🔴 A BRANCH NO TEST EVER ENTERED, AND THAT IS ITS COST.

    The receipt's invariant forbade the kind `ok=True, ops=[]`. The parent
    must turn such a child response into a NAMED refusal — otherwise a
    live turn would crash with an exception instead of an answer.

    The first draft of this branch called `digest` and `started`, which
    DO NOT EXIST in `_result_from_payload`'s scope: the signature and the
    clock live with the caller. This would have been a `NameError` the
    first time a child said "ok" without operations. It was caught by a
    GUARD (`test_names_are_bound_where_they_are_called`), not by a run:
    execution never reached here — not in the tests, not in the three live
    trials.

    Hence the test's rule: the branch must be EXECUTED, not read.
    """

    def test_ребёнок_сказал_ok_без_операций(self) -> None:
        from kir.sandbox import SandboxPolicy, _result_from_payload

        r = _result_from_payload(
            {"ok": True, "ops": [], "stdout": "разведочный ход"},
            SandboxPolicy())
        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, "KIR-B007")
        self.assertIn("не собрал ни одной операции", r.refusal.message_ru)
        self.assertEqual(r.stdout, "разведочный ход",
                         "печать автора обязана доехать: разведочный ход её и "
                         "есть весь результат")

    def test_ребёнок_с_операциями_проходит_как_прежде(self) -> None:
        """PASS control: the branch must not swallow a legitimate answer."""
        from kir.sandbox import SandboxPolicy, _result_from_payload

        r = _result_from_payload(
            {"ok": True, "ops": [{"op": "create_level", "id": "L1",
                                  "elev_mm": 0, "name": "Э"}]},
            SandboxPolicy())
        self.assertTrue(r.ok)
        self.assertEqual(len(r.ops), 1)


if __name__ == "__main__":
    unittest.main()
