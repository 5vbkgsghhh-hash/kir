"""THE ONLY ONE VISIBLE IN A TRUNCATED POOL WAS PASSED OFF AS THE ONLY ONE.

🔴 WHY (04.09.2026, audit findings FC-16 and FC-25, both reproduced by a run).

The collector cuts the pool at a ceiling and HONESTLY marks the slice
(`<pool>__truncated`, audit F7). The argument for what to do with that
mark was written in the tree exactly ONCE — in the branch
`ground._resolve_one`, `by == "default"`, verbatim:

    A truncated pool cannot prove sole-entry-ness (audit F7): the sole
    VISIBLE row may have invisible siblings beyond the cap.

And it worked exactly there. The neighboring branches asked the SAME
question — "there is exactly one visible match" — and never once asked
about `truncated`:

    ground._resolve_one  by=name         the word `truncated` in the success branch: 0 times
    ground._resolve_one  by=family_type  same
    relate._find_grid    len(rows) == 1  a caveat about truncation exists TWICE in the file,
                                         and BOTH times in the "no such axis" branch

MEASUREMENT BEFORE THE FIX:

    pool [{11,"Тип A"},{12,"Другое"}], truncated=True
        by=name «Тип A»                      -> id 11, diags 0
    pool [{21,"T1",OST_Doors/F/T}], truncated=True
        by=family_type                       -> id 21, diags 0
    grid pool [{1,"А"},{2,"1"}], truncated=True
        _find_grid «А»                       -> id 1,  diags 0
    CONTROL: the same three at truncated=False   -> the same ids, and this is LEGAL

THE COST. Each of the three rejects two visible namesakes (G102/G109) —
that is, an invisible namesake turns a HARD REFUSAL into a silently
chosen foreign entry. The most expensive kind of outcome in this tree: the
program drifts onto a foreign type or a foreign grid spacing and shows
nothing of it.

THE LEGAL NAME CASE IS PRESERVED, AND THAT IS THE MAIN HALF OF THE FIX: on
a FULL pool, a single exact match is itself the proof of uniqueness. The
refusal is hung EXACTLY on `truncated`, so every law here is checked as a
PAIR — truncated and not truncated — and a one-sided fix ("always
refuse") would not have passed a single one of these tests.
"""
from __future__ import annotations

import unittest

from kir import ground, relate

_ПУЛ = [{"id": 11, "name": "Тип A"}, {"id": 12, "name": "Другое"}]
_СИМВОЛЫ = [{"id": 21, "name": "T1", "category": "OST_Doors",
             "family_name": "F", "type_name": "T"}]
_ОСИ = [{"id": 1, "name": "А", "p0_mm": [0, 0], "p1_mm": [0, 10000]},
        {"id": 2, "name": "1", "p0_mm": [0, 0], "p1_mm": [10000, 0]}]


def _разрешить(sel, *, пул=None, имя_пула="wall_types", обрезан: bool):
    diags: list = []
    res = ground._resolve_one(sel, имя_пула, пул if пул is not None else _ПУЛ,
                              0, "O1", "type", "create_door", diags,
                              truncated=обрезан)
    return res, diags


class ОБРЕЗАННЫЙПУЛНЕДОКАЗЫВАЕТЕДИНСТВЕННОСТИ(unittest.TestCase):

    def test_имя_на_обрезанном_пуле_ОТКАЗАНО(self):
        """🔴 RED before the fix: it used to return id 11 at diags 0."""
        res, diags = _разрешить({"by": "name", "value": "Тип A"}, обрезан=True)
        self.assertIsNone(res)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, ground.GROUND_AMBIGUOUS)
        self.assertIn("обрезан коллектором", str(diags[0].message_ru))

    def test_КОНТРОЛЬ_FAIL_имя_на_ПОЛНОМ_пуле_разрешается(self):
        """One changed condition — the opposite verdict.

        Without this half, "refuse any name" would have passed the
        previous test too, and the fix would be worse than the defect: a
        name is the primary means of addressing.
        """
        res, diags = _разрешить({"by": "name", "value": "Тип A"}, обрезан=False)
        self.assertEqual(diags, [])
        self.assertEqual(res["id"], 11)
        self.assertEqual(res["via"], "name")

    def test_family_type_на_обрезанном_пуле_ОТКАЗАН(self):
        """🔴 RED before the fix: it used to return id 21 at diags 0.

        The branch is not named in the finding, but the law is one: the
        triple category/family/type is NOT unique by construction. And
        this pool really is cut in production —
        `acceptance.symbol_rows_from_snapshot` abstains exactly on
        `family_symbols__truncated`.
        """
        sel = {"by": "family_type", "category": "OST_Doors",
               "family_name": "F", "type_name": "T"}
        res, diags = _разрешить(sel, пул=_СИМВОЛЫ, имя_пула="family_symbols",
                                обрезан=True)
        self.assertIsNone(res)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, ground.GROUND_AMBIGUOUS)

    def test_КОНТРОЛЬ_FAIL_family_type_на_ПОЛНОМ_пуле_разрешается(self):
        sel = {"by": "family_type", "category": "OST_Doors",
               "family_name": "F", "type_name": "T"}
        res, diags = _разрешить(sel, пул=_СИМВОЛЫ, имя_пула="family_symbols",
                                обрезан=False)
        self.assertEqual(diags, [])
        self.assertEqual(res["id"], 21)

    def test_element_id_среза_НЕ_КАСАЕТСЯ(self):
        """The next move a refusal names must actually work.

        A refusal that sends the author to a place where the same
        refusal is waiting is a full circle with no movement (this same
        defect was already fixed here on 25.08).
        """
        for обрезан in (False, True):
            with self.subTest(обрезан=обрезан):
                res, diags = _разрешить({"by": "element_id", "value": 11},
                                        обрезан=обрезан)
                self.assertEqual(diags, [])
                self.assertEqual(res["id"], 11)

    def test_отказ_называет_следующий_ход(self):
        _res, diags = _разрешить({"by": "name", "value": "Тип A"}, обрезан=True)
        self.assertIn("element_id", str(diags[0].message_ru))

    def test_default_остался_на_прежнем_законе(self):
        """The branch where the argument was first written did not change its verdict."""
        res, diags = _разрешить({"by": "default"}, пул=[_ПУЛ[0]], обрезан=True)
        self.assertIsNone(res)
        self.assertEqual(len(diags), 1)
        self.assertIn("default/sole-entry невозможен", str(diags[0].message_ru))
        res, diags = _разрешить({"by": "default"}, пул=[_ПУЛ[0]], обрезан=False)
        self.assertEqual(diags, [])
        self.assertEqual(res["id"], 11)


class ОБРАЗЕЦОДИНИОНПРИМЕНЁНКОСЯМ(unittest.TestCase):
    """FC-25. `relate` says, verbatim, «по ОБРАЗЦУ `ground._resolve_one`» —
    meaning the sample must be singular AND applied here too."""

    def _ось(self, *, обрезан: bool):
        diags: list = []
        row = relate._find_grid("А", _ОСИ, "O1", "f", diags,
                                truncated=обрезан)
        return row, diags

    def test_ось_на_обрезанном_пуле_ОТКАЗАНА(self):
        """🔴 RED before the fix: it used to return grid id 1 at diags 0."""
        row, diags = self._ось(обрезан=True)
        self.assertIsNone(row)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, relate.GRID_AMBIGUOUS)
        self.assertIn("обрезан коллектором", str(diags[0].message_ru))

    def test_КОНТРОЛЬ_FAIL_ось_на_ПОЛНОМ_пуле_находится(self):
        row, diags = self._ось(обрезан=False)
        self.assertEqual(diags, [])
        self.assertEqual(row["id"], 1)

    def test_целый_адрес_отказывает_вместе_с_осью(self):
        """The refusal must actually reach `resolve_address`, not stay inside."""
        diags: list = []
        точка = relate.resolve_address({"at_grid": ["А", "1"]}, _ОСИ, "O1", "f",
                                       diags, dims=2, truncated=True)
        self.assertIsNone(точка)
        self.assertEqual(len(diags), 1)
        diags = []
        точка = relate.resolve_address({"at_grid": ["А", "1"]}, _ОСИ, "O1", "f",
                                       diags, dims=2, truncated=False)
        self.assertEqual(diags, [])
        self.assertEqual(точка, [0, 0])

    def test_отказ_называет_ход_КОТОРЫЙ_У_ОСЕЙ_ДРУГОЙ(self):
        """A type has a fallback — `element_id`; a grid has NONE, and lying about it is forbidden.

        Spec §5.4: the language does not address grids by element_id (a
        grid's name IS its identity). A refusal that offered element_id
        here would send the author into a grammar that does not exist.
        """
        _row, diags = self._ось(обрезан=True)
        текст = str(diags[0].message_ru)
        self.assertIn("литералом [x, y]", текст)
        self.assertIn("element_id язык не адресует", текст)


if __name__ == "__main__":
    unittest.main()
