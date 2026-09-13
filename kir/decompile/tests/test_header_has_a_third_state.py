"""THE L0 HEADER MUST HAVE A "NOT MEASURED" STATE, NOT JUST "NO".

🔴 WHAT THIS FILE IS PAID FOR BY, THE MEASUREMENT OF 25.08.2026 ACROSS 44
LIVE SNAPSHOTS.

This whole file fanatically holds a third state: `LineOwner.NONE` against the
absence of the key, `curve_kind=None`, `host_source=None`, `section_receipts`
as `None` against `()`. Two fields lack it, and both answer "all is well"
exactly where the correct answer is "we did not look".

1. THE CENSUS. The field's comment (:2224) says verbatim: "An empty tuple =
   there WAS NO census … not 'zero elements in the document' … otherwise the
   absence of a denominator looks like full coverage." The `UnloadedElements`
   guard's docstring says the OPPOSITE: "An empty document (census 0) is
   passed over silently and legitimately in this case." Two carriers of one
   law in one file, and they contradict each other.

   Consequence: a guard set up for the sake of "0 walls on a building with
   15 323 walls" CANNOT trigger on a snapshot without a census. Measurement by
   the live reader:

       readable snapshots 40 · census present 36 · census ZERO with a
       non-empty stream 4  (sklnk_eom_r26_20260727 — 1916 elements in the
                  stream; sob62_r23_v3/v4/v6)

   On these, `len(md.elements) == 0` passes SILENTLY — exactly the outcome the
   type was written to forbid.

2. SEPARATION. `worksharing: bool = False` and `worksets_closed: int = 0` are
   declared with defaults, `from_dict` substitutes the same defaults, and for
   a stream WITHOUT these keys the answer is "the model is complete."
   Verified on sklnk_eom_r26_20260727 — THE SAME document whose 27.07
   measurement (17 of 18 closed worksets, 11 elements instead of 2016)
   justified these fields in the comment at :2215-2220. Its header has none
   of these keys.

   Meanwhile the fix was carried OUTSIDE: serving.py adds
   `measured=bool(metadata.worksharing)`, which makes a single-user model
   (worksharing=False, honestly measured) also become "unmeasured." Two
   carriers of one quantity silently diverge.

BOUNDARY. `is_partial_read` retains its previous meaning — "the snapshot is
KNOWN to be incomplete" — and its previous type: it is read in forty places
in a boolean context, and turning it ternary would mean changing forty places
at once. What is added here is the missing NAME for the second question
("was it measured at all"), because the tree had already named this gap:
`ground.py:1814` — "`is_partial_read` measures closed worksets, yet is read
as 'is the snapshot complete'."
"""

from __future__ import annotations

import unittest

from kir.decompile.schema import L0Document


def _шапка(**ещё) -> dict:
    строка = {
        "doc_name": "Проверка", "revit_version": "2024", "units": "mm",
        "change_stamp": "third-state-probe", "elements": [],
        "levels": [], "grids": [], "rooms": [], "project_info": {},
        "category_status": [],
    }
    строка.update(ещё)
    return строка


class Перепись(unittest.TestCase):

    def test_шапка_без_переписи_отличима_от_переписи_в_ноль(self):
        нет = L0Document.from_dict(_шапка())
        пуста = L0Document.from_dict(_шапка(census=[]))
        self.assertFalse(нет.census_taken,
                         "перепись НЕ снималась, а шапка говорит, что снята")
        self.assertTrue(пуста.census_taken,
                        "перепись снята и дала ноль — это ИЗМЕРЕНИЕ, "
                        "и оно обязано отличаться от отсутствия")

    def test_КОНТРОЛЬ_снятая_непустая_перепись_считается(self):
        есть = L0Document.from_dict(_шапка(
            census=[{"key": "OST_Walls", "count": 15323}]))
        self.assertTrue(есть.census_taken)
        self.assertEqual(есть.census_total, 15323)


class Разделённость(unittest.TestCase):

    def test_шапка_без_ключей_не_называется_измеренной(self):
        нет = L0Document.from_dict(_шапка())
        self.assertFalse(
            нет.partial_read_measured,
            "разделённость не мерили, а шапка отвечает «модель полная»")

    def test_однопользовательская_модель_ИЗМЕРЕНА(self):
        """🔴 Exactly what the external fix `measured=bool(worksharing)` was
        breaking: a document WITHOUT worksharing is honestly measured, and
        calling it unmeasured is a second lie on top of the first."""
        одиночная = L0Document.from_dict(
            _шапка(worksharing=False, worksets_closed=0))
        self.assertTrue(одиночная.partial_read_measured)
        self.assertFalse(одиночная.is_partial_read)

    def test_КОНТРОЛЬ_заведомо_неполный_слепок_по_прежнему_виден(self):
        """The meaning of `is_partial_read` did not change, and its forty
        readers must not notice a thing."""
        неполный = L0Document.from_dict(
            _шапка(worksharing=True, worksets_closed=17))
        self.assertTrue(неполный.is_partial_read)
        self.assertTrue(неполный.partial_read_measured)

    def test_КОНТРОЛЬ_неизмеренная_шапка_не_объявляется_неполной(self):
        """"Not measured" is NOT "incomplete". Conflating them would mean
        replacing a false green with a false red."""
        нет = L0Document.from_dict(_шапка())
        self.assertFalse(нет.is_partial_read)


if __name__ == "__main__":
    unittest.main()


class ВнешнийНосительСнят(unittest.TestCase):
    """The fix lived OUTSIDE the schema and therefore diverged from it.

    `serving._partial_read_state` was writing
    `measured=bool(metadata.worksharing)`. This answers the question "is
    there worksharing", while the field is named "was it measured". A
    single-user model — measured and not separated — was getting
    `measured=false`, i.e. our incompleteness instead of its completeness.
    """

    def test_измеренность_берётся_из_шапки_а_не_выводится_из_значения(self):
        import ast
        import inspect

        from kir import serving
        дерево = ast.parse(
            inspect.getsource(serving._partial_read_state))
        источники = {
            ast.unparse(узел)
            for узел in ast.walk(дерево)
            if isinstance(узел, (ast.Attribute, ast.Call))
        }
        self.assertIn("metadata.partial_read_measured", источники,
                      "измеренность по-прежнему выводится, а не читается")
        self.assertNotIn("bool(metadata.worksharing)", источники,
                         "значение величины снова выдаётся за факт замера")


class СторожШапкиРазличаетНОЛЬиНЕЗНАЮ(unittest.TestCase):
    """🔴 THE GUARD COULD NOT TRIGGER EXACTLY WHERE THERE IS NO CENSUS.

    `UnloadedElements` goes red when `census_total > 0`. But a zero census, by
    the law of THIS SAME file, means "there WAS NO census", not "the document
    has zero elements". Measurement by the live reader across 40 readable
    snapshots: four have no census with a non-empty stream —
    sklnk_eom_r26_20260727 (1916 elements), sob62_r23_v3/v4/v6. On these,
    `len(md.elements) == 0` was passing silently.

    Three cases, and they are DIFFERENT:

        census taken, counted >0, elements empty      -> CONTRADICTION, refuse
        census taken, counted 0                        -> the document is
                                                          genuinely empty,
                                                          silence is legitimate
        there WAS NO census                             -> nothing to prove
                                                          with, refuse with a
                                                          DIFFERENT message

    The third case is canon shape 4: a zero from a corpus whose reachability
    has no proof is not a zero.
    """

    def test_перепись_не_снята_молчания_нет(self):
        from kir.decompile.schema import L0HeaderMisread, UnloadedElements
        неизвестно = UnloadedElements(0, census_taken=False)
        with self.assertRaises(L0HeaderMisread) as поймано:
            len(неизвестно)
        self.assertIn("перепись", str(поймано.exception).lower())

    def test_КОНТРОЛЬ_правда_пустой_документ_по_прежнему_молчит(self):
        """The refusal catches the IMPOSSIBLE, not the rare. A census was
        taken and gave zero — that is a measurement, and reading it silently
        is legitimate."""
        from kir.decompile.schema import UnloadedElements
        пусто = UnloadedElements(0, census_taken=True)
        self.assertEqual(len(пусто), 0)
        self.assertEqual(list(пусто), [])
        self.assertFalse(пусто)

    def test_КОНТРОЛЬ_противоречие_по_прежнему_ловится(self):
        from kir.decompile.schema import L0HeaderMisread, UnloadedElements
        with self.assertRaises(L0HeaderMisread):
            len(UnloadedElements(310_558, census_taken=True))

    def test_два_отказа_говорят_РАЗНОЕ(self):
        """One message for two different facts would bring back the same
        blindness one level down: the reader would not be able to tell "a
        header instead of a document" from "there was no census"."""
        from kir.decompile.schema import L0HeaderMisread, UnloadedElements
        тексты = []
        for всего, снята in ((310_558, True), (0, False)):
            try:
                len(UnloadedElements(всего, census_taken=снята))
            except L0HeaderMisread as e:
                тексты.append(str(e))
        self.assertEqual(len(тексты), 2)
        self.assertNotEqual(тексты[0], тексты[1])
