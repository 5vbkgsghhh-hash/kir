"""ACCEPTANCE REJECTED A CORRECT RECORD BECAUSE IT DID NOT KNOW ABOUT OFFSETS.

Bought by a live record on 2026-08-23 next to a real `MNVNK_..._K3_AR_R2022`.
Program: seven walls of one floor as a unit, and eleven placements shifted
vertically by the floor height (3300 mm, derived from K3's own level marks).

Revit executed correctly — seven walls went up on each of the twelve floors,
the witness is green on all three axes, `execution: committed`. But acceptance said:

    OST_Walls на уровне «L02_K3_+9,850»: программа даёт 84, прибавилось 7
    OST_Walls на уровне «L03_K3_+13,150»: могло попасть не более 0, прибавилось 7
    … и так по всем двенадцати  →  KIR-A006, acceptance: rejected

The INSTRUMENT was wrong: it attributed every copy to the level named on the
member, because the multiplier `1 + len(placements)` did not distinguish
flat placements from lifted ones.

The level of a lifted copy is NOT COMPUTED here — it is FORGOTTEN: assigning
an element to a level is Revit's own call, made from its own table of marks,
and our own count would be a second opinion on someone else's decision — the
very same shape of defect that this fix corrects.
A row with no level still counts toward the TOTAL.
"""
import unittest

from kir import acceptance as A


def _rows(placements):
    ops = [{"op": "create_level", "id": "L", "name": "Э2", "elev_mm": 3300},
           {"op": "create_group", "id": "g", "name": "секция",
            "placements": placements,
            "members": [
                {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0], "height_mm": 3300,
                 "level": {"by": "name", "value": "Э2"}},
                {"op": "create_wall", "id": "w2", "p0_mm": [6000, 0],
                 "p1_mm": [6000, 4000], "height_mm": 3300,
                 "level": {"by": "name", "value": "Э2"}},
            ]}]
    exp = A.derive_expectation({"ops": ops})
    return [r for r in exp.rows if "OST_Walls" in (r.categories or ())]


def _total(rows):
    return sum(r.count for r in rows)


class LiftedCopiesLoseTheirLevel(unittest.TestCase):
    def test_flat_placements_keep_the_level(self):
        """CONTROL: an offset with no vertical component does not change the level, and
        forgetting that is not allowed — otherwise the fix would blur a check that used to work."""
        rows = _rows([[8000, 0], [16000, 0]])
        self.assertEqual(_total(rows), 6, "две копии плюс сами члены = 3×2 стены")
        self.assertTrue(all(r.level == "Э2" for r in rows),
                        "плоская копия стоит на том же уровне")

    def test_lifted_placements_are_level_agnostic(self):
        rows = _rows([[0, 0, 3300], [0, 0, 6600]])
        self.assertEqual(_total(rows), 6, "общее число не изменилось")
        с_уровнем = [r for r in rows if r.level == "Э2"]
        без = [r for r in rows if r.level is None]
        self.assertEqual(_total(с_уровнем), 2, "на своём уровне — только сами члены")
        self.assertEqual(_total(без), 4, "поднятые вхождения уровня не обещают")

    def test_the_live_shape_no_longer_promises_84_on_one_level(self):
        """The very shape that produced the false KIR-A006: 11 lifted placements."""
        rows = _rows([[0, 0, 3300 * k] for k in range(1, 12)])
        self.assertEqual(_total(rows), 24, "2 стены × 12 занятий")
        на_уровне = sum(r.count for r in rows if r.level == "Э2")
        self.assertEqual(на_уровне, 2,
                         "приёмка снова обещает всё на одном уровне — "
                         "именно это отклоняло верную запись живьём")


if __name__ == "__main__":
    unittest.main()
