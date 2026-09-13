"""ZERO MATCHES IS NEVER AMBIGUOUS.

🔴 WHY (25.08.2026, an audit finding, reproduced by a run).

After `disambiguate_by`, a pool can end up with ZERO rows left. Both
branches — `by=name` and `by=default` — coded this as `KIR-G102 AMBIGUOUS`
with the text "ambiguous — 0 matches remained after disambiguate_by". The
phrase refutes itself.

**What cost more than the code were the CANDIDATES.** The list was taken
BEFORE the narrowing:

    candidates=_candidate_rows(exact if exact or disambiguate_by is None
                               else initial_matches)

that is, the refusal handed the author the id of exactly the row that its
own predicate had just disqualified. The author went to the named address,
asked again — and got the SAME refusal. A full loop with no progress.

Now: the code is `KIR-G101` (not found), the text names HOW MANY rows there
were and that not one passed, and each candidate carries the ACTUAL value of
the asked-about parameter — "asked for Diameter=100, this one has 200". The
list turns from a trap into an answer.
"""
from __future__ import annotations

import unittest

from kir.ground import _resolve_one

ПУЛ = [{"id": 41, "name": "Труба", "params": {"Diameter": 200}},
       {"id": 42, "name": "Труба", "params": {"Diameter": 300}}]
ПРЕДИКАТ = {"param": "Diameter", "value": 100}


def _отказ(sel):
    diags: list = []
    got = _resolve_one(sel, "pipe_types", [dict(r) for r in ПУЛ],
                       0, "P1", "type", "create_pipe", diags)
    assert got is None
    assert len(diags) == 1, [d.code for d in diags]
    return diags[0]


class НОЛЬЭТОНЕНАЙДЕНО(unittest.TestCase):

    def test_by_name_даёт_НЕ_НАЙДЕН_а_не_неоднозначно(self):
        """🔴 RED before the fix: the code used to be KIR-G102."""
        self.assertEqual(_отказ({"by": "name", "value": "Труба",
                                 "disambiguate_by": ПРЕДИКАТ}).code,
                         "KIR-G101")

    def test_by_default_тем_же_законом(self):
        self.assertEqual(_отказ({"by": "default",
                                 "disambiguate_by": ПРЕДИКАТ}).code,
                         "KIR-G101")

    def test_текст_НЕ_называет_ноль_неоднозначностью(self):
        текст = str(_отказ({"by": "name", "value": "Труба",
                            "disambiguate_by": ПРЕДИКАТ}).message_ru)
        self.assertNotIn("неоднозначен", текст)
        self.assertIn("НИ ОДНА", текст)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)


class КАНДИДАТЫНЕСУТПРИЧИНУДИСКВАЛИФИКАЦИИ(unittest.TestCase):

    def test_каждый_кандидат_показывает_ФАКТИЧЕСКОЕ_значение(self):
        """🔴 This is the whole point of it: the list used to be a trap."""
        for sel in ({"by": "name", "value": "Труба",
                     "disambiguate_by": ПРЕДИКАТ},
                    {"by": "default", "disambiguate_by": ПРЕДИКАТ}):
            with self.subTest(sel=sel["by"]):
                кандидаты = _отказ(sel).as_dict().get("candidates")
                self.assertEqual([c.get("Diameter") for c in кандидаты],
                                 [200, 300])

    def test_отсутствие_параметра_НАЗЫВАЕТСЯ_а_не_молчит(self):
        """A row without the asked-for parameter is also an answer, and a different one."""
        diags: list = []
        _resolve_one({"by": "name", "value": "Труба",
                      "disambiguate_by": ПРЕДИКАТ},
                     "pipe_types", [{"id": 7, "name": "Труба"}],
                     0, "P1", "type", "create_pipe", diags)
        кандидаты = diags[0].as_dict().get("candidates")
        self.assertEqual(кандидаты[0].get("Diameter"),
                         "нет такого параметра")


class КОНТРОЛЬ_НАСТОЯЩАЯНЕОДНОЗНАЧНОСТЬОСТАЛАСЬ(unittest.TestCase):
    """Without it, the fix would mean "KIR-G102 was removed altogether"."""

    def test_две_строки_прошли_сужение_это_ВСЁ_ЕЩЁ_неоднозначно(self):
        пул = [{"id": 41, "name": "Труба", "params": {"Diameter": 100}},
               {"id": 42, "name": "Труба", "params": {"Diameter": 100}}]
        diags: list = []
        _resolve_one({"by": "name", "value": "Труба",
                      "disambiguate_by": ПРЕДИКАТ},
                     "pipe_types", пул, 0, "P1", "type", "create_pipe", diags)
        self.assertEqual(diags[0].code, "KIR-G102")
        self.assertIn("неоднозначен", str(diags[0].message_ru))

    def test_ОДНА_строка_прошла_отказа_НЕТ(self):
        пул = [{"id": 41, "name": "Труба", "params": {"Diameter": 100}},
               {"id": 42, "name": "Труба", "params": {"Diameter": 200}}]
        diags: list = []
        got = _resolve_one({"by": "name", "value": "Труба",
                            "disambiguate_by": ПРЕДИКАТ},
                           "pipe_types", пул, 0, "P1", "type", "create_pipe",
                           diags)
        self.assertEqual(diags, [])
        self.assertEqual(got["id"], 41)


if __name__ == "__main__":
    unittest.main()
