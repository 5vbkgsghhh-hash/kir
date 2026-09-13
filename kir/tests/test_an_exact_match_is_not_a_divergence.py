"""AN EXACT MATCH IS NOT A DISCREPANCY, AND THE COUNTER MUST KNOW THIS.

🔴 PAID FOR LIVE ON 25.08.2026. Проект1, Revit 2026, an 80-wall program
with doors. The judge of the built printed to the model:

    расхождений вердикта 1 · геометрия расходится в 1 · первое: геометрия
    положение двери — ВДОЛЬ оси хозяина — заявлено совпало 80, макс 0.00 мм

The line refutes itself: «расходится» (diverges) against «совпало 80, макс
0.00 мм» (matched 80, max 0.00 mm). The reason recorded in the entry itself
said «ноль означает, что восстановление точное» (zero means the
reconstruction is exact). That is, an AGREEMENT REPORT was sitting in the
list of discrepancies, and `len(...)` was counting it as a discrepancy — a
named defect of this tree: the quantity is CLAIMED by a length counter and
READ from a list that also contains agreements.

THE COST IS NOT COSMETIC. `built_note` is a string the model reads on
EVERY turn. Having read «геометрия расходится» (the geometry diverges), it
would go fix coordinates that are correct to a hundredth of a millimeter,
and would spend a turn on something already sound.

WHAT IS PINNED DOWN HERE, AND WHY EXACTLY THIS. The existing
`test_geometry_gate_is_per_element_and_splits_along_from_across` checks
that the STRING exists and carries «совпало 2, макс 0.00 мм» (matched 2,
max 0.00 mm). It was green both before and after the fix — because it asks
about the TEXT, while what decides the outcome is the KIND. Here what is
asked is the kind, and whether the counter tells it apart: without this,
the fix is pinned down by nothing.
"""
from __future__ import annotations

import unittest

from kir import built_verdict, design_check
from kir.design_check import (
    Divergence, СВЕРКА, compare_geometry, spatial_model_from_l0,
    spatial_model_from_program,
)
from kir.tests.test_design_check import (
    _tiny_l0_document, _two_room_program,
)


class ТочноеСовпадениеНеРасхождение(unittest.TestCase):

    def _строки(self):
        model_a, _ = spatial_model_from_l0(_tiny_l0_document())
        model_b, _ = spatial_model_from_program(_two_room_program(),
                                                building_id="tiny-v1")
        return {row.subject: row for row in compare_geometry(model_a, model_b)}

    def test_согласие_несёт_род_сверки_а_не_геометрии(self):
        """Both checks, which used to always report, now report a MATCH when they agree."""
        rows = self._строки()
        for subject in ("положение двери — ВДОЛЬ оси хозяина",
                        "контур помещения (IoU)"):
            self.assertIn(subject, rows,
                          "сверка исчезла: «сошлось» стало неотличимо от "
                          "«не смотрели», а это другая беда, не починка")
            self.assertEqual(
                rows[subject].kind, СВЕРКА,
                f"{subject}: точное совпадение объявлено родом "
                f"«{rows[subject].kind}» — счётчик расхождений его посчитает")

    def test_расхождение_остаётся_геометрией(self):
        """A control in the other direction: the kind changes depending on the MEASUREMENT, not always."""
        rows = self._строки()
        # Neighboring checks of the same cycle stay silent on a match — so
        # their absence here is itself the proof that the rig MATCHED.
        self.assertNotIn("ось стены", rows)
        self.assertNotIn("положение двери — ПОПЕРЁК оси хозяина", rows)

    def test_судья_не_считает_согласие_расхождением(self):
        """🔴 THE DECISIVE ONE: the split is made by the READER, because it is the reader that counts."""
        block: dict = {"state": "judged", "elements_read": 2,
                       "elements_asked": 2}
        geometry = [
            Divergence(СВЕРКА, "положение двери — ВДОЛЬ оси хозяина",
                       "2 общих", "совпало 2, макс 0.00 мм", "точно"),
            Divergence("геометрия", "ось стены", "2 общих",
                       "совпало 1, макс 2000.0 мм, худшая `W2`", "дефект"),
        ]
        agreed = [d for d in geometry if d.kind == design_check.СВЕРКА]
        diverged = [d for d in geometry if d.kind != design_check.СВЕРКА]
        self.assertEqual(len(diverged), 1)
        self.assertEqual(len(agreed), 1)

        geo_rows, geo_total = built_verdict._divergence_rows(diverged, cap=8)
        agreed_rows, agreed_total = built_verdict._divergence_rows(agreed, cap=8)
        self.assertEqual(geo_total, 1, "разошедшихся ровно одна")
        self.assertEqual(agreed_total, 1, "сошедшихся ровно одна")
        block["geometry_divergences"] = geo_rows
        block["geometry_divergences_total"] = geo_total
        block["geometry_agreements_total"] = agreed_total
        note = built_verdict.note(block)
        self.assertIn("геометрия расходится в 1", note)
        self.assertIn("ось стены", note,
                      "названо должно быть НАСТОЯЩЕЕ расхождение, а не первое "
                      "попавшееся в списке")
        self.assertNotIn("ВДОЛЬ оси хозяина", note)

    def test_сошлось_и_не_смотрели_различимы_в_заметке(self):
        """An empty list for both — meaning it is the NUMBER of matches that discriminates, not emptiness."""
        сошлось = built_verdict.note(
            {"state": "judged", "elements_read": 2, "elements_asked": 2,
             "geometry_agreements_total": 2})
        не_смотрели = built_verdict.note(
            {"state": "judged", "elements_read": 2, "elements_asked": 2})
        self.assertIn("расхождений с заявленным НЕТ", сошлось)
        self.assertIn("сверок геометрии сошлось 2", сошлось)
        self.assertIn("расхождений с заявленным НЕТ", не_смотрели)
        self.assertNotIn("сверок геометрии", не_смотрели)

    def test_контроль_fail_вернуть_безусловный_род(self):
        """The instrument MUST be able to say NO: bring back the old behavior — red.

        What is mutated is not the text, but the decision about the KIND — the very thing that was being fixed.
        """
        rows = self._строки()
        подделка = {
            s: Divergence("геометрия", r.subject, r.parse, r.program, r.cause)
            for s, r in rows.items()
        }
        плохие = [s for s, r in подделка.items()
                  if r.kind != СВЕРКА
                  and ("макс 0.00 мм" in r.program
                       or "IoU медиана 1.000" in r.program)]
        self.assertTrue(
            плохие,
            "контроль вырожден: в стенде нет ни одной ТОЧНОЙ сверки, и "
            "утверждение о роде проверялось бы на пустом множестве")


if __name__ == "__main__":
    unittest.main()
