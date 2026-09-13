"""Foreign collisions ride as A NUMBER, not a list.

🔴 THE MEASUREMENT THAT BOUGHT THE RULE (27.08.2026, a live build on
AVT3_KR_MBPB). The model built 7 elements in an isolated zone and got, in
the receipt:

    building                 17 861 chars
      clash                  14 357   80.4 %
         of which findings    7 780   five findings at ~1 550 each
         of which message_ru  2 536
      the verdict itself        627    3.5 %  ← "the verdict wasn't counted"

And right next to it, in the same block, sat `introduced: 0` and
`by_origin: {"both_prior": 423}` — meaning for ALL 423 clashes both sides
were already in the model BEFORE this turn. The author introduced not a
single one and got fourteen kilobytes describing someone else's geometry.

The argument for why this is harmful was written into the header of
`kir/live/verdict.py` BEFORE this fix: a model that sees foreign clashes
either fixes what it did not break, or reports that it broke the building.
The `introduced` count was set up on 11.08 for exactly this reason — it
was read, and nothing was decided on it.
"""
import copy
import unittest

from kir.live.verdict import _with_clash, _без_чужих_находок


def _клеш(**правки):
    """The shape of the live block: the numbers are real, the details are
    trimmed down to their shape."""
    основа = {
        "schema": "kir-bundle-clash/1",
        "status": "ok",
        "total_findings": 423,
        "introduced": 0,
        "by_origin": {"both_prior": 423},
        "overlaps": 33,
        "disputes": 388,
        "duplicates": 388,
        "pairs_compared": 1588653,
        "elements_considered": 5747,
        "findings": [{"finding_id": "f%d" % i, "kind": "duplicate",
                      "a_element_id": "1%03d" % i, "b_element_id": "2%03d" % i,
                      "хвост": "п" * 1400} for i in range(5)],
        "rules": {"duplicate": {"текст": "п" * 700}},
        "rung_actions": {"1": "п" * 140},
        "text_budget": {"cap": 2700, "shown": 1, "of": 5},
        "message_ru": "с" * 2536,
    }
    основа.update(правки)
    return основа


class ЧужиеНаходкиСнимаются(unittest.TestCase):

    def test_при_нуле_внесённых_структуры_сняты_а_числа_целы(self):
        ур = _без_чужих_находок(_клеш())
        for поле in ("findings", "rules", "rung_actions"):
            self.assertNotIn(поле, ур, "структурная подробность чужой находки "
                                       "уехала автору")
        for поле, знач in (("total_findings", 423), ("introduced", 0),
                           ("overlaps", 33), ("disputes", 388),
                           ("pairs_compared", 1588653), ("status", "ok")):
            self.assertEqual(ур.get(поле), знач,
                             f"«{поле}» пропало: величина, которую перестали "
                             "печатать, читается как ноль")
        self.assertEqual(ур.get("by_origin"), {"both_prior": 423})

    def test_ПРОЗА_КЛЕША_СОХРАНЯЕТСЯ_ДОСЛОВНО(self):
        """🔴 A CONTROL BOUGHT BY ITS OWN REGRESSION.

        The first edition REPLACED `message_ru` in full. Two tests in
        `test_clash_in_the_receipt` turned red and showed that the clash
        text is NOT a retelling of the findings: the retelling takes up a
        fifth of it, the rest is honesty about COVERAGE («БЕЗ ТЕЛА 3964»,
        «СТЫКИ СТЕН ВНЕ ПРОВЕРКИ», «ТОЛЬКО НОМИНАЛ», «НЕ ВИДИТ СТОЯЩЕЕ»),
        and it applies to the AUTHOR's own geometry too. Erasing it to save
        space would mean buying size at the cost of truth."""
        исходный = _клеш(message_ru="БЕЗ ТЕЛА (НЕ ВИДЕЛИ): 3964\n"
                                    "НЕ ВИДИТ СТОЯЩЕЕ: только объявленное")
        ур = _без_чужих_находок(исходный)
        self.assertIn("БЕЗ ТЕЛА (НЕ ВИДЕЛИ): 3964", ур["message_ru"])
        self.assertIn("НЕ ВИДИТ СТОЯЩЕЕ", ур["message_ru"])
        self.assertTrue(ур["message_ru"].startswith(исходный["message_ru"]),
                        "проза обязана остаться ДОСЛОВНО и в начале")

    def test_снятие_названо_и_объяснено(self):
        ур = _без_чужих_находок(_клеш())
        self.assertEqual(ур.get("findings_withheld"),
                         ["findings", "rules", "rung_actions"],
                         "снятое обязано быть НАЗВАНО поимённо")
        текст = str(ур.get("message_ru") or "")
        self.assertIn("СНЯТЫ НАМЕРЕННО", текст,
                      "молчание без причины неотличимо от потери")
        self.assertIn("0 из 423", текст, "числа обязаны стоять в самой причине")

    def test_КОНТРОЛЬ_внесённые_показываются_целиком(self):
        """What the author broke, they must see. That is the boundary of
        this fix."""
        свои = _клеш(introduced=3, by_origin={"both_prior": 420, "introduced": 3})
        ур = _без_чужих_находок(свои)
        self.assertEqual(ур, свои, "блок с внесёнными спорами тронут")

    def test_КОНТРОЛЬ_без_посчитанной_дельты_не_трогаем(self):
        """"We don't know whose findings these are" is NOT the same as "not
        yours".

        `new_from=None` means the turn's delta was not computed at all, and
        the `introduced` key is then absent. Treating it as zero would mean
        passing off not-knowing as a fact — a named defect of this tree."""
        неизвестно = _клеш()
        неизвестно.pop("introduced")
        self.assertEqual(_без_чужих_находок(неизвестно), неизвестно)

    def test_КОНТРОЛЬ_когда_находок_нет_вовсе_блок_нетронут(self):
        """🔴 THIS EXACT CASE CAUGHT THE FIRST EDITION.

        At zero findings there is nothing to strip, yet the text carries
        something ELSE — «ни одного тела», «только номинал». The first
        edition fired on this case too, wiping out an honest coverage
        report for an empty batch."""
        пусто = _клеш(total_findings=0, findings=[], by_origin={},
                      message_ru="НИ ОДНОГО ТЕЛА не построено")
        ур = _без_чужих_находок(пусто)
        self.assertEqual(ур, пусто)
        self.assertIn("НИ ОДНОГО ТЕЛА", ур["message_ru"])

    def test_прибор_текста_остаётся_потому_что_текст_остался(self):
        """`text_budget` counts the clash prose. The prose is not replaced
        — so its numbers are still correct, and stripping it would be a
        loss for no reason.

        (In the first edition it WAS stripped — and correctly stripped
        THERE, because the text was being replaced. The fix changed, and so
        did the conclusion.)"""
        ур = _без_чужих_находок(_клеш())
        self.assertIn("text_budget", ур)

    def test_не_словарь_и_пустое_проходят_насквозь(self):
        for чужое in (None, {}, "строка", 5):
            self.assertIs(_без_чужих_находок(чужое), чужое)


class РезСлучаетсяВВоронкеКвитанции(unittest.TestCase):

    def test_with_clash_пересчитывает_свой_размер(self):
        стало = _with_clash({"message_ru": "вердикт"}, _клеш())
        self.assertEqual(стало["receipt_chars"], len(str(стало["message_ru"])),
                         "`receipt_chars` — ФУНКЦИЯ от текста и обязан "
                         "описывать текст, который уехал")

    def test_экономия_на_живой_форме_измерима(self):
        import json
        полный = _with_clash({"message_ru": "в" * 627}, _клеш(introduced=1))
        урезан = _with_clash({"message_ru": "в" * 627}, _клеш())
        n1 = len(json.dumps(полный, ensure_ascii=False))
        n2 = len(json.dumps(урезан, ensure_ascii=False))
        self.assertLess(n2, n1 * 0.6,
                        f"ожидалась экономия больше 40 %, вышло {n1} -> {n2}")


if __name__ == "__main__":
    unittest.main()
