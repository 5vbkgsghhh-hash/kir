"""THE "NOT FOUND" REFUSAL PRESENTED FIVE NAMES AND NOT A SINGLE REASON.

🔴 WHY (24.08.2026, found by LIVE REVIT, «Проект1», Revit 2026).

`8b3e5f64` (the same day) taught eight `FamilySymbol` pools to bring back
`placement_type` — a trait by which a candidate can be unfit BY
CONSTRUCTION, not by taste. It was built EXACTLY for the refusal that
presents candidates.

Before this file, it never REACHED that refusal. Live measurement:

    create_adaptive_component symbol={"by":"name","value":"КИР-нет-такого"}
    -> KIR-G101, candidates:
       "Выноска элемента" · "Коническое врезание" ·
       "Импост круглого сечения 1" · "Опора - Металлическая - Круглого сечения"

Bare strings. Not a single `element_id` the author could use to reassemble
the selector deterministically (the neighboring `KIR-G102` path has provided
it since 17.07), and not a single reason for unfitness: out of the five,
probably not one is adaptive — and there is no way to find that out.

The author gets five names and goes off to try them one by one. This is
exactly the "typed refusal naming the wrong cause" that is WORSE than a
crash: a crash stops you, this one teaches you the wrong thing.
"""
from __future__ import annotations

import unittest

from kir import ground
from kir.ground import _nearest

ПУЛ = [
    {"id": 101, "name": "Балка двутавровая",
     "placement_type": "CurveDrivenStructural", "family_name": "Балки"},
    {"id": 102, "name": "Импост круглого сечения",
     "placement_type": "OneLevelBased", "family_name": "Импосты"},
    {"id": 103, "name": "Балка коробчатая",
     "placement_type": "CurveBased", "family_name": "Балки"},
    {"id": 104, "name": "Выноска элемента",
     "placement_type": "ViewBased"},
]


class КандидатНесётАДРЕСИПРИЧИНУ(unittest.TestCase):

    def test_кандидат_это_строка_а_не_имя(self):
        """🔴 RED before the fix: `list[str]` was being returned."""
        got = _nearest("Балка", ПУЛ)
        self.assertTrue(all(isinstance(row, dict) for row in got), got)

    def test_каждый_кандидат_несёт_element_id(self):
        """This is what the refusal presents the list for: to reassemble the selector."""
        for row in _nearest("Балка", ПУЛ):
            self.assertIn("id", row)
            self.assertIsInstance(row["id"], int)

    def test_каждый_кандидат_несёт_тип_размещения(self):
        """The trait of unfitness BY CONSTRUCTION — what it was built for."""
        типы = {row["name"]: row.get("placement_type")
                for row in _nearest("Балка", ПУЛ)}
        self.assertEqual(типы.get("Импост круглого сечения"), "OneLevelBased")
        self.assertEqual(типы.get("Балка двутавровая"),
                         "CurveDrivenStructural")

    def test_порядок_остался_РЕЛЕВАНТНОСТНЫМ(self):
        """A name exists — closeness by name is the best that can be offered.

        Pool order would be a regression: it puts first whatever the
        collector returned first, and that means nothing to the author.
        """
        имена = [row["name"] for row in _nearest("Балка коробчатая", ПУЛ)]
        self.assertEqual(имена[0], "Балка коробчатая")

    def test_КОНТРОЛЬ_отсутствующий_ключ_НЕ_ВЫДУМЫВАЕТСЯ(self):
        """"Did not read" and "read, and here is what's there" must be distinguished."""
        got = _nearest("Выноска", [{"id": 9, "name": "Выноска элемента"}])
        self.assertEqual(got, [{"id": 9, "name": "Выноска элемента"}])

    def test_КОНТРОЛЬ_потолок_показа_ОДИН_на_всех(self):
        """The display ceiling on `_nearest` is NOT its own, but shared with
        the rest.

        🔴 RENAMED AND REWRITTEN ON 26.08.2026. The test used to be called
        «потолок_показа_остался_пять» and pinned the LITERAL 5. The argument
        behind it was correct ("a refusal is paid for in tokens on every
        turn"), but the literal outlived the raise of the shared threshold
        to twelve (ceb4ea24) and turned the neighboring caption into a lie:
        the author got FIVE lines under «ПОКАЗАНЫ 12 ИЗ N». The test did not
        turn red — it was guarding a number, not the LAW.

        The law: one display ceiling for all trimmers. The number lives on
        `_CANDIDATES_SHOWN` and is derived by measurement (83 profiles, 1344
        pool observations), rather than being repeated here a second time.
        """
        большой = [{"id": i, "name": f"Балка {i}"} for i in range(40)]
        self.assertEqual(len(_nearest("Балка", большой)),
                         ground._CANDIDATES_SHOWN)


if __name__ == "__main__":
    unittest.main()
