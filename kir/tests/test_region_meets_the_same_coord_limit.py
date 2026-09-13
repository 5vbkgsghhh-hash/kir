"""THE `region` KIND HAD NO COORDINATE LIMIT — WHILE ALL ITS NEIGHBORS DID.

🔴 WHY (2026-08-25, an audit finding, reproduced by running the code).

`authoring_validation` for `kind == "region"` checks exactly
`isinstance(v, dict)` and passes it onward with the words "the full laws
will run at ground." In `contour._validate_shape`, the coordinate value was
checked NOWHERE: not for `origin` (only the SIDES are bounded there), not
for the `poly` points (only the COUNT is measured there).

Measured: a `rect` with `origin: [9e11, 9e11]` — nine hundred million
meters — was ACCEPTED, and the emission printed
`Line.CreateBound(P(900000000000.0, ...))`.

The same `create_ceiling`, written via `pts`, failed statically
(`_COORD_LIMIT_MM = 16 000 000`). Written via `contour`, it sailed through
to a late Revit failure. One quantity, two records, two verdicts.

**And the number itself lived in TWO copies** — `authoring_validation` and
`connect` — with the second one marked "same static sanity bound as
authoring": the author KNEW about the copy and left it. A copy someone
knows about is still a copy. There is now one home for it:
`registry_base.COORD_LIMIT_MM`.
"""
from __future__ import annotations

import unittest

from kir import connect, contour, registry_base
from kir import authoring_validation as av

ПРЕДЕЛ = registry_base.COORD_LIMIT_MM


def _проверить(форма):
    diags: list = []
    contour._validate_shape(форма, None, "O1", "contour", diags)
    return diags


class ОБЛАСТЬВСТРЕЧАЕТПРЕДЕЛ(unittest.TestCase):

    def test_origin_за_пределом_ОТКАЗАН(self):
        """🔴 RED before the fix: it was accepted."""
        diags = _проверить({"shape": "rect", "origin": [9e11, 9e11],
                            "size_mm": [1000.0, 1000.0]})
        self.assertEqual(len(diags), 1)
        self.assertIn("охвата модели", str(diags[0].message_ru))

    def test_точка_poly_за_пределом_ОТКАЗАНА(self):
        """🔴 THE EXPECTATION `len(diags) == 1` USED TO LIVE HERE, AND IT
        ENCODED A DEFECT.

        For this input, TWO points are beyond the limit — `[1]` and `[2]`
        — while one was expected: the ring-parsing loop returned `None` at
        the first bad one, and the rest were never asked about at all. The
        test copied this behavior from the code and thereby locked it in;
        the test's actual subject, as declared in the file's docstring, is
        different — "the region kind gained a coordinate limit," not at all
        "exactly one point is named."

        Since 08-26, ALL bad ones are named (up to `_BAD_POINTS_SHOWN`, the
        remainder as a count), because an author learning about them one at
        a time pays a round trip for each. The expectation has been
        brought in line with the subject, and it pins a new law along the
        way.
        """
        diags = _проверить({"shape": "poly",
                            "points_mm": [[0, 0], [9e11, 0],
                                          [9e11, 1000], [0, 1000]]})
        поля = [str(d.field_name) for d in diags]
        self.assertEqual(len(diags), 2, поля)
        self.assertIn("contour.points_mm[1]", поля)
        self.assertIn("contour.points_mm[2]", поля)
        for d in diags:
            self.assertIn("охвата модели", str(d.message_ru))

    def test_отказ_называет_вероятную_ПРИЧИНУ_и_ход(self):
        """A number like that is almost always a units mistake — and it
        says so."""
        diags = _проверить({"shape": "rect", "origin": [9e11, 0.0],
                            "size_mm": [1000.0, 1000.0]})
        текст = str(diags[0].message_ru)
        self.assertIn("ЕДИНИЦ", текст)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)

    def test_КОНТРОЛЬ_PASS_обычные_координаты_проходят(self):
        for форма in ({"shape": "rect", "origin": [0.0, 0.0],
                       "size_mm": [1000.0, 1000.0]},
                      {"shape": "poly",
                       "points_mm": [[0, 0], [1000, 0], [1000, 1000],
                                     [0, 1000]]}):
            with self.subTest(форма=форма["shape"]):
                self.assertEqual(_проверить(форма), [])

    def test_ровно_на_пределе_ПРИНИМАЕТСЯ(self):
        """The boundary is inclusive — otherwise a legal model at the edge
        would be rejected.

        🔴 THIS TEST'S EARLIER CLAIM WAS WRONG, AND IT LOCKED IN A DEFECT
        (rewritten 2026-09-04, audit finding FC-15).

        It used to have `origin=[LIMIT, 0]` with `size_mm=[1000, 1000]`
        and expected "accepted." The words "exactly at the limit" described
        only ONE vertex out of four in that setup: the other three were
        computed as `origin + size` and sat at 16 001 000 mm, i.e. BEYOND
        the limit. The test copied from the code exactly what the code was
        missing (`_rect_edges` built the vertices, and nobody re-checked
        them), thereby pinning the defect under the name of a law.

        The test's subject, as declared in the file's docstring, is
        different — "the region kind gained a coordinate limit." The real
        boundary is inclusive at the FARTHEST point of the contour, and it
        is checked from both sides: a vertex exactly at the limit is
        accepted, a vertex one millimeter farther is not. A one-sided
        check here would prove nothing: "accept everything" would pass it
        just as the earlier version did.
        """
        ровно = {"shape": "rect", "origin": [ПРЕДЕЛ - 1000.0, 0.0],
                 "size_mm": [1000.0, 1000.0]}
        дальше = {"shape": "rect", "origin": [ПРЕДЕЛ - 999.0, 0.0],
                  "size_mm": [1000.0, 1000.0]}
        рёбра = contour._validate_shape(ровно, None, "O1", "contour", [])
        self.assertEqual(_проверить(ровно), [], "вершина ровно на пределе")
        self.assertEqual(max(p[0] for p0, p1, _b in рёбра for p in (p0, p1)),
                         ПРЕДЕЛ, "дальняя вершина обязана лежать РОВНО на пределе")
        self.assertEqual(len(_проверить(дальше)), 1,
                         "вершина на 1 мм за пределом обязана отказывать")


class ПРОИЗВОДНАЯВЕРШИНАВСТРЕЧАЕТТОТЖЕПРЕДЕЛ(unittest.TestCase):
    """FC-15: the INPUT was checked, but a derived value nobody asked
    about was left unchecked.

    🔴 MEASURED BEFORE THE FIX (2026-09-04, reproduced by running the code):

        rect origin=[16 000 000, 0] size=[1000, 1000] -> ACCEPTED, diags 0,
             vertex x's = [16 000 000.0, 16 001 000.0]   (limit 16 000 000)
        l    origin=[16 000 000, 0] size=[4000, 4000]  -> ACCEPTED, diags 0,
             max vertex x = 16 004 000.0
        CONTROL origin=[0, 0] same size                 -> accepted, vertices within limits

    `resolve_anchor` guarded EVERY coordinate the author wrote and carried
    the argument that it was "the ONLY gate for any area coordinate." For
    `poly` that is true: the author writes every vertex there. For `rect`
    and `l`, most of the vertices are COMPUTED, and they never passed
    through that gate at all.
    """

    def test_rect_производная_вершина_за_пределом_ОТКАЗАНА(self):
        """🔴 RED before the fix: it was accepted, diags 0."""
        diags = _проверить({"shape": "rect", "origin": [ПРЕДЕЛ, 0.0],
                            "size_mm": [1000.0, 1000.0]})
        self.assertEqual(len(diags), 1, [d.field_name for d in diags])
        self.assertIn("охват модели", str(diags[0].message_ru))

    def test_Г_форма_тоже(self):
        """A second form with computed vertices — and the same verdict."""
        diags = _проверить({"shape": "l", "origin": [ПРЕДЕЛ, 0.0],
                            "size_mm": [4000.0, 4000.0],
                            "cut_mm": [1000.0, 1000.0]})
        self.assertEqual(len(diags), 1)
        self.assertIn("охват модели", str(diags[0].message_ru))

    def test_поворот_выносит_вершину_и_это_видно(self):
        """`rotation_deg` — a third way to compute a point the author never
        wrote."""
        внутри = {"shape": "rect", "origin": [ПРЕДЕЛ - 100_000.0, 0.0],
                  "size_mm": [100_000.0, 100_000.0], "rotation_deg": 0}
        снаружи = dict(внутри, rotation_deg=-45)
        self.assertEqual(_проверить(внутри), [], "КОНТРОЛЬ: без поворота внутри")
        self.assertEqual(len(_проверить(снаружи)), 1,
                         "поворот вынес вершину за предел — отказ обязан быть")

    def test_дуга_между_законными_вершинами_тоже_считается(self):
        """The `poly` vertices passed through `resolve_anchor`, but the ARC
        between them did not.

        The bounding extent here is EXACT (for a line and an arc), so the
        check is legitimate: for a spline it would be a lower bound, and
        that is stated in `_reject_out_of_reach`.
        """
        форма = {"shape": "poly",
                 "points_mm": [[ПРЕДЕЛ, -1_000_000.0], [ПРЕДЕЛ, 1_000_000.0],
                               [ПРЕДЕЛ - 2_000_000.0, 0.0]],
                 "arcs": [{"edge": 0, "bulge": 1.0}]}
        сырые = contour._shape_edges(форма, None, "O1", "contour", [])
        self.assertGreater(contour.edges_bbox(сырые)[2], ПРЕДЕЛ,
                           "проба обязана правда выходить за предел")
        self.assertEqual(len(_проверить(форма)), 1)

    def test_отказ_называет_ЧИСЛО_и_следующий_ход(self):
        текст = str(_проверить({"shape": "rect", "origin": [ПРЕДЕЛ, 0.0],
                                "size_mm": [1000.0, 1000.0]})[0].message_ru)
        self.assertIn("16001000", текст.replace(" ", ""),
                      "дальняя координата обязана быть названа числом")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)

    def test_КОНТРОЛЬ_FAIL_форма_у_края_но_внутри_ПРОХОДИТ(self):
        """A guard that rejects everything is a fix worse than the defect.

        The same thing, shifted 1000 mm inward: one changed condition, the
        opposite verdict.
        """
        for форма in ({"shape": "rect", "origin": [ПРЕДЕЛ - 1000.0, 0.0],
                       "size_mm": [1000.0, 1000.0]},
                      {"shape": "l", "origin": [ПРЕДЕЛ - 4000.0, 0.0],
                       "size_mm": [4000.0, 4000.0],
                       "cut_mm": [1000.0, 1000.0]},
                      {"shape": "rect", "origin": [0.0, 0.0],
                       "size_mm": [1000.0, 1000.0]}):
            with self.subTest(форма=форма["shape"], origin=форма["origin"]):
                self.assertEqual(_проверить(форма), [])

    def test_МУТАЦИЯ_производная_вершина_ЧИТАЕТ_предел_а_не_помнит(self):
        """The same control as for the author's coordinate one level up."""
        from unittest import mock
        форма = {"shape": "rect", "origin": [1.0e6, 0.0],
                 "size_mm": [1000.0, 1000.0]}
        self.assertEqual(_проверить(форма), [])
        with mock.patch.object(contour, "COORD_LIMIT_MM", 1.0005e6):
            # 1 000 000 is inside the new limit, 1 001 000 is not:
            # exactly the DERIVED vertex goes red, not the written one.
            diags = _проверить(форма)
            self.assertEqual(len(diags), 1)
            self.assertIn("охват модели", str(diags[0].message_ru))


class ЧИСЛОЖИВЁТВОДНОМДОМЕ(unittest.TestCase):

    def test_три_читателя_одно_число(self):
        self.assertEqual(av._COORD_LIMIT_MM, ПРЕДЕЛ)
        self.assertEqual(connect._COORD_LIMIT_MM, ПРЕДЕЛ)

    def test_МУТАЦИЯ_сдвиг_реестра_двигает_область(self):
        """This is exactly what the single home was built for: `contour`
        READS, it does not remember."""
        from unittest import mock
        форма = {"shape": "rect", "origin": [1.0e7, 0.0],
                 "size_mm": [1000.0, 1000.0]}
        self.assertEqual(_проверить(форма), [], "на реестровой границе принят")
        with mock.patch.object(contour, "COORD_LIMIT_MM", 1.0e3):
            self.assertEqual(len(_проверить(форма)), 1,
                             "правило обязано ЧИТАТЬ предел, а не помнить")


if __name__ == "__main__":
    unittest.main()
