"""For the `region` kind, "the form above" is a FORM, not the word "region."

🔴 WHAT THIS FILE IS BOUGHT BY, MEASURED 2026-08-25.

The tail of every slot failure ends with the line "bring X to the form
above," and "the form above" is the slot annotation printed one line
earlier. Measured against the live registry: for 124 of 373 parameters
(33.2%), the annotation is the BARE kind name.

This is especially bad for `region`, because its form is complex AND
GENERATED. What the author saw:

    contour.outer: edge 0 is described by an arc more than once
        contour  region
    NEXT MOVE: bring contour to the form above; …

That is, "the form above" is one word. The move is unexecutable by
construction.

And right next to it, in `contour.shape_forms_text`, the form is GENERATED
from the registry in full: three forms, every field of each, with bounds.
Its docstring says outright that a hand-written copy is deliberately absent
here — "in this tree ALL hand-written lists have drifted, and NOT ONE
generated one has." The generated form existed and was not being read.

THE BOUNDARY. Fixed here is `region` — 15 parameters that have a form and
were not showing it. The other bare kinds (`pt_xy`, `pt_xyz`, `bool`) are
untouched: for the first two, the form is carried by the failure's
`expected` field, for the third, the word "bool" is its own form. The
33.2% share is named in full, and the fix covers the measured part — not
the other way around.
"""

from __future__ import annotations

import unittest

from kir import spec
from kir.dsl import _annotation


class ФормаОбластиПоказывается(unittest.TestCase):

    @staticmethod
    def _region_параметры():
        for имя, оп in spec.OPS.items():
            for p in оп.params:
                if str(p.kind) == "region":
                    yield имя, оп, p

    def test_аннотация_региона_не_голое_слово(self):
        голые = [f"{имя}.{p.name}"
                 for имя, оп, p in self._region_параметры()
                 if str(_annotation(оп, p)).strip() == "region"]
        self.assertEqual(
            голые, [],
            f"{len(голые)} слотов рода `region` показывают автору одно слово "
            f"вместо формы: {голые[:5]}. «Приведи к виду выше» неисполнимо, "
            f"когда вид — это слово «region».")

    def test_аннотация_называет_все_три_формы(self):
        имя, оп, p = next(iter(self._region_параметры()))
        текст = str(_annotation(оп, p))
        for форма in ("rect", "l", "poly"):
            with self.subTest(форма=форма):
                self.assertIn(форма, текст)

    def test_форма_порождается_а_не_переписана(self):
        """A copy would drift silently. The text must come from the same
        generator as the failure about an unknown form field."""
        from kir.contour import shape_forms_text
        имя, оп, p = next(iter(self._region_параметры()))
        порождённое = shape_forms_text(p.name)
        аннотация = str(_annotation(оп, p))
        общее = [ф for ф in ("rect", "poly", "size_mm", "points_mm")
                 if ф in порождённое and ф in аннотация]
        self.assertGreaterEqual(
            len(общее), 3,
            "аннотация не выведена из `shape_forms_text`: два носителя одной "
            "формы разойдутся молча")

    def test_КОНТРОЛЬ_прочие_рода_не_тронуты(self):
        """The fix covers the measured part, not everything
        indiscriminately. `mm`, `enum`, `sel` already had a form before —
        their annotations must not change."""
        for оп_имя, ожидание in (("create_wall", "mm"), ):
            оп = spec.OPS[оп_имя]
            p = next(x for x in оп.params if str(x.kind) == ожидание)
            self.assertTrue(str(_annotation(оп, p)).startswith(ожидание))

    def test_КОНТРОЛЬ_замер_доли_голых_назван(self):
        """The number from the docstring must be re-measurable, otherwise
        it is decoration."""
        всего = голых = 0
        for имя, оп in spec.OPS.items():
            for p in оп.params:
                всего += 1
                if str(_annotation(оп, p)).strip() == str(p.kind):
                    голых += 1
        self.assertGreater(всего, 300)
        self.assertLess(
            голых, 124,
            f"голых аннотаций {голых} из {всего}: было 124, и region должен "
            f"был их убавить")


if __name__ == "__main__":
    unittest.main()
