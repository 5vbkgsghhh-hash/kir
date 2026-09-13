"""A refusal about a write target is obligated to name the REASON, not the form that was sent in the first place.

🔴 MEASUREMENT ON THE LIVE CORPUS OF REFUSALS, 2026-08-25. Over one week,
1672 refusals before execution; 670 of them — 40% OF ALL OF THEM — are
`join_elements`, the `first`/`second` fields, and all 670 fell on ONE day,
08.23. The model was sending:

    {"by": "element_id", "value": "743932"}

and getting back:

    first — селектор element_id или ref
        first  target_w: element_id|ref(element)
      получено: {'by': 'element_id', 'value': '743932'}
    СЛЕДУЮЩИЙ ХОД: приведи first к виду выше.

It had already sent "the form above." The mistake is in the TYPE of the
value: for `element_id` it must be an INTEGER, and a string arrived instead.
The refusal does not say this — and the model repeats the exact same thing,
because there is nothing in the text to fix.

🔴 AND THE EXACT REASON HAD BEEN WRITTEN A DAY EARLIER, AND WAS THROWN AWAY.
`_target_w_why` was set up on 2026-08-22 for exactly this case, and its
docstring says, verbatim: "these two lines MATCH CHARACTER FOR CHARACTER in
form, and what decides is the TYPE of the value... I spent two live attempts
on this in a row." It knows how to answer:

    by=element_id требует ЦЕЛОЕ значение, пришло '743932' (str)
      — сними кавычки: 743932

but the call site called the NEIGHBORING boolean `_target_w_ok` instead, and
wrote the generic text. The reason was computed and thrown away. A named
defect of the tree: two values exist, and the wrong one gets read.

THIS IS EXACTLY THE CONSTITUTION'S HEADLINE METRIC — "how many times
checkability changed the model's decision." Here it changed nothing, across
670 refusals.
"""
from __future__ import annotations

import unittest

from kir import compiler


def _диагностики(first, second):
    out = compiler.compile_program({"ops": [{
        "op": "join_elements", "id": "j1",
        "first": first, "second": second}]})
    return out.ok, [(getattr(d, "field_name", ""),
                     getattr(d, "message_ru", "") or "")
                    for d in (out.diagnostics or [])]


ЦЕЛЫЙ = {"by": "element_id", "value": 743932}
СТРОКОЙ = {"by": "element_id", "value": "743932"}


class ЦельЗаписиНазываетПричину(unittest.TestCase):

    def test_строка_вместо_целого_названа_дословно(self) -> None:
        ok, диаг = _диагностики(СТРОКОЙ, ЦЕЛЫЙ)
        self.assertFalse(ok)
        текст = "\n".join(m for f, m in диаг if f == "first")
        self.assertIn("ЦЕЛОЕ", текст, msg=(
            "отказ не называет ПРИЧИНУ — модель прислала ровно ту форму, "
            f"которую он ей и описывает. Текст: {текст[:200]}"))
        self.assertIn("743932", текст, "готовое исправление не показано")

    def test_совет_снять_кавычки_доезжает(self) -> None:
        """A ready answer is cheaper than a rule: digits in quotes — one turn."""
        _, диаг = _диагностики(ЦЕЛЫЙ, СТРОКОЙ)
        текст = "\n".join(m for f, m in диаг if f == "second")
        self.assertIn("кавычки", текст)

    def test_чужой_by_назван(self) -> None:
        ok, диаг = _диагностики({"by": "name", "value": "стена"}, ЦЕЛЫЙ)
        self.assertFalse(ok)
        текст = "\n".join(m for f, m in диаг if f == "first")
        self.assertIn("name", текст, "неверное by обязано быть названо")

    def test_значение_вне_границ_названо_числом(self) -> None:
        ok, диаг = _диагностики({"by": "element_id", "value": 0}, ЦЕЛЫЙ)
        self.assertFalse(ok)
        текст = "\n".join(m for f, m in диаг if f == "first")
        self.assertIn("1..", текст, "граница обязана быть названа числом")

    # ── controls: the guard must be able to STAY SILENT ───────────────────

    def test_целые_значения_проходят(self) -> None:
        ok, диаг = _диагностики(ЦЕЛЫЙ, {"by": "element_id", "value": 743933})
        self.assertTrue(ok, f"законная программа отвергнута: {диаг}")

    def test_ссылка_внутри_программы_проходит(self) -> None:
        """`by=ref` is a legitimate second form, and a fix has no right to break it."""
        out = compiler.compile_program({"ops": [
            {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "default"}},
            {"op": "join_elements", "id": "j1",
             "first": {"by": "ref", "value": "w1"}, "second": ЦЕЛЫЙ}]})
        тексты = [getattr(d, "message_ru", "") or "" for d in (out.diagnostics or [])]
        self.assertFalse(any("селектор element_id или ref" in t for t in тексты),
                         f"законная ссылка отвергнута: {тексты}")


if __name__ == "__main__":
    unittest.main()
