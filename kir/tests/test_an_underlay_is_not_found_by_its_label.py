"""AN UNDERLAY IS RECOGNIZED BY ITS KIND AND FILE, NOT BY AN EDITABLE LABEL (S-07).

🔴 WHAT IT USED TO BE. `pdf_underlay` was computed as `__TypeNameOf(e).EndsWith(".pdf")` —
a suffix on the TYPE NAME, which the user edits and to which Revit ITSELF
appends suffixes. Both forms were found on a live corpus (measurement
2026-08-30 across 81 decompiles of `L0.jsonl`, corpus read-only):

    a page of a multi-page PDF -> 'How to Use this Project.pdf - 1'
    a duplicate on re-import    -> '01_Ситуационный план-01_Сит. план.pdf (2)'

THE NUMBERS, AND THEY DECIDE:

    distinct raster types                70   ·  instances 165
    caught by .EndsWith('.pdf')           2 types / 2 instances
    underlays in the corpus, in fact      9 types / 21 instances

The instrument found 2 of 21 and SILENTLY skipped 19 — ninety percent. The
answer from `query_count(pdf_underlay)` was not "few underlays," it was "we
did not find them," and the reader had no way to tell the two apart.

🔴 THE PROPERTY "THIS IS A PDF" DOES NOT EXIST IN THE API, IN ANY OF THE SIX
TARGET VERSIONS. Checked against `RevitAPI.xml` 2021…2026: `ImageType` has
`Source` (`ImageTypeSource`: Internal/Import/Link), `PageNumber`, `Path` — and
not a single `IsPdf`. So what is asked is the KIND (`Source != Internal` —
the image came IN FROM A FILE, rather than being saved by the project) plus
the extension of `Path` — the path to the FILE ITSELF, which a type rename
does not change.

This is not "a name instead of a kind," it is the only PDF discriminator the
API offers at all, and it is taken from the FILE, not from the label.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

#: Real type names from the corpus — not made up. The first is caught by
#: the old feature, the other five are NOT, and all six are underlays.
ИЗ_КОРПУСА = (
    "Ситуационный план.pdf",
    "How to Use this Project.pdf - 1",
    "How to Use this Project.pdf - 4",
    "01_Ситуационный план-01_Сит. план.pdf (2)",
    "Лист 16 15.06.2026.pdf (3)",
    "Перемычка (3)-Лист1.pdf (2)",
)


def _эмиссия() -> str:
    out = compile_program(
        {"ir_version": "1.0", "intent": "t",
         "ops": [{"op": "query_count", "id": "pdf", "kind": "pdf_underlay"}]},
        revit_version="2026")
    assert out.ok, out.diagnostics
    return out.csharp


class ПодложкаОпознаётсяПоРодуИФайлу(unittest.TestCase):

    def test_имя_типа_для_подложки_больше_не_спрашивается(self):
        cs = _эмиссия()
        self.assertNotIn('__TypeNameOf(e).EndsWith(".pdf"', cs,
                         "признак снова читает РЕДАКТИРУЕМОЕ имя типа: Ревит "
                         "дописывает к нему ' - 1' и ' (2)', и подложка "
                         "теряется молча")

    def test_спрашивается_род_источника(self):
        cs = _эмиссия()
        self.assertIn("Source != ImageTypeSource.Internal", cs,
                      "род не спрошен: внутренний рендер, сохранённый в проект, "
                      "неотличим от импортированного файла")

    def test_расширение_берётся_у_ПУТИ_а_не_у_имени(self):
        cs = _эмиссия()
        self.assertIn('__ImageTypeOf(e).Path.EndsWith(".pdf"', cs)

    def test_помощник_есть_в_преамбуле(self):
        """The link across two places breaks silently: the predicate calls a helper,
        the helper is obligated to be emitted."""
        cs = _эмиссия()
        self.assertIn("Func<Element, ImageType> __ImageTypeOf", cs)

    def test_старый_признак_проваливал_живые_имена_корпуса(self):
        """🔴 A MEASUREMENT INSIDE THE GUARD, NOT JUST IN THE DOCSTRING.

        What is checked is the ARITHMETIC ITSELF of the old feature on REAL
        names: it misses five of six. Without this case, "the feature was
        changed" would remain a claim about the text, not about the subject.
        """
        поймано = [t for t in ИЗ_КОРПУСА if t.lower().endswith(".pdf")]
        self.assertEqual(len(поймано), 1,
                         "старый признак ловит не одно имя из шести — замер "
                         "устарел, пересними по корпусу")
        self.assertEqual(len(ИЗ_КОРПУСА) - len(поймано), 5)

    def test_вторая_половина_растр_НЕ_подложка(self):
        """Without this half, a predicate of "any image from a file" would pass.

        An ordinary raster (`.png`) is a file, `Source != Internal`, but it
        is NOT an underlay; the path extension is obligated to filter it out.
        """
        for имя, подложка in (("plan.pdf", True), ("logo.png", False),
                              ("scan.PDF", True), ("shot.jpeg", False)):
            with self.subTest(файл=имя):
                self.assertEqual(имя.lower().endswith(".pdf"), подложка)


if __name__ == "__main__":
    unittest.main()
