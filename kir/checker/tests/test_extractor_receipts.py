"""ONE ELEMENT'S FAILURE IS NOT THE BUILDING'S FAILURE — the Python half of the seam.

MEASUREMENT 20.08.2026, live document `MNVNK_ATR_PD_B14_K6_AR_R2022` (Revit 2023,
read-only). `get_FromRoom(phase)` throws on **246 doors out of 1230** — "The
target instance does not exist in the given phase." The whole of `extractor.cs` was
ONE unprotected traversal, so one door extinguished the reading of the ENTIRE building:
1102 rooms, 2952 windows, levels and walls did not arrive, and what came out
was one sentence with no address.

Contract §18.2: every requested element yields a ROW or a TYPED
RECEIPT; silence is forbidden. A door without a room in this phase is a FACT ABOUT THE BUILDING,
and it must get a row, with the reason travelling as a field.

🔴 THIS FILE'S BOUNDARY, NAMED HONESTLY (shape 27). The producer is C#, and
it cannot be run from here: the input here is HANDWRITTEN, that is, the file guards
the SHAPE of the receipt, not the fact that Revit hands it over in that shape. That C# compiles on
six versions — checked separately and by the compiler (6/6, 0 errors), with a
FAIL control: removing one `catch` from a door pair -> `CS1524` on all six.
That it READS a live document is checked by nothing here and stands on the list of live
checks for the coordinator.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.checker.extractor import receipts


def _raw(**over):
    base = {
        "phase_name": "ПД",
        "failures_total": 246,
        "failures_cap": 200,
        "failures": [{"stage": "door_phase_link", "element_id": str(i),
                      "reason": "The target instance does not exist in the given phase."}
                     for i in range(200)],
        "counts": {"rooms": 473, "rooms_unplaced": 629},
        "doors": ([{"room_link": "refused"}] * 246
                  + [{"room_link": "ok"}] * 273
                  + [{"room_link": "no_room_in_phase"}] * 711),
        "windows": [{"room_link": "ok"}] * 2952,
    }
    base.update(over)
    return base


class КвитанцияНеТеряетНиОдногоОтказа(unittest.TestCase):

    def test_полное_число_и_показанное_РАЗНЫЕ_поля(self):
        """Truncating the list must be VISIBLE, otherwise it is a silent loss."""
        r = receipts(_raw())
        self.assertEqual(r["total"], 246)
        self.assertEqual(len(r["sample"]), 200)
        self.assertEqual(r["cap"], 200)
        self.assertNotEqual(r["total"], len(r["sample"]),
                            "контроль вырожден: на этом входе обрезания нет")

    def test_состояния_связи_считаются_поимённо(self):
        r = receipts(_raw())
        self.assertEqual(r["room_link"]["doors:refused"], 246)
        self.assertEqual(r["room_link"]["doors:ok"], 273)
        self.assertEqual(r["room_link"]["doors:no_room_in_phase"], 711)
        self.assertEqual(r["room_link"]["windows:ok"], 2952)

    def test_отказ_и_отсутствие_комнаты_НЕ_ОДНО_И_ТО_ЖЕ(self):
        """The distinction is load-bearing: the first is about us, the second is about the building.

        Merging them into one column, we would get 957 "doors without a room" and
        would not be able to say how many of them are a fact about the building.
        """
        r = receipts(_raw())
        self.assertIn("doors:refused", r["room_link"])
        self.assertIn("doors:no_room_in_phase", r["room_link"])

    def test_неразмещённые_комнаты_названы_числом(self):
        r = receipts(_raw())
        self.assertEqual(r["rooms_unplaced"], 629)
        self.assertEqual(r["rooms_placed"], 473)

    def test_молчащий_источник_даёт_НЕ_СООБЩЕНО_а_не_ноль(self):
        """🔴 FIXED FOR ITS OWN DEFECT, AND THIS IS THE MAIN POINT OF THE FILE.

        The first edition of both the code and this test asserted "a silent source
        gives zeros." The assertion is wrong: the old C# carries no fields, and a zero
        would be read as "there are no unplaced rooms" — a claim about the building
        that no one made. I had decompiled the very same shape CORRECTLY an hour earlier
        for `room_link` (there `unknown` arrived), but not for the two counters on
        neighbouring lines of the same file.
        """
        r = receipts({})
        self.assertIsNone(r["total"], "«отказов не было» и «не спрашивали» — разное")
        self.assertIsNone(r["rooms_unplaced"])
        self.assertIsNone(r["rooms_placed"])
        self.assertEqual(r["sample"], [])
        self.assertEqual(r["room_link"], {})
        self.assertIsNone(r["phase_name"])

    def test_явный_ноль_остаётся_нулём(self):
        """A control in the other direction: otherwise `None` would swallow a real zero."""
        r = receipts({"failures_total": 0, "counts": {"rooms_unplaced": 0, "rooms": 473}})
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["rooms_unplaced"], 0)
        self.assertEqual(r["rooms_placed"], 473)


class КонтрольЧитаетСостояниеАНеПересчитываетЕго(unittest.TestCase):

    def test_неизвестное_состояние_не_теряется_а_называется(self):
        """A row from the OLD C# has no `room_link` field — it must be visible.

        Otherwise a mixed response (some rows from the new code, some from the old)
        would be read as "all links are fine."
        """
        r = receipts(_raw(doors=[{"from_room_id": "1"}] * 5))
        self.assertEqual(r["room_link"]["doors:unknown"], 5)


if __name__ == "__main__":
    unittest.main()
