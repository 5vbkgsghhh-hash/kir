"""HAB000 TALKED ABOUT THE BUILDING, BUT WAS DESCRIBING THE INSTRUMENT'S BOUNDARY.

Measured 23.08.2026 on a real paired-run program: 714 operations, of which
204 `create_room`, 192 `create_wall`, 96 windows, 96 doors. The judge answered

    прочитано: doors 0, levels 0, rooms 0, stairs 0, walls 0, windows 0
    БЛОКИРУЮЩИЕ 1: HAB000 — model has no rooms; nothing was verified and the
    building must NOT read as valid.

The judge is right by contract: it takes elevations ONLY from this same
program's `create_level`, while all the references pointed at the open
model's levels by name. But the text said nothing about this, and the author
read a verdict on their building exactly where the self-check's boundary
stood. The "verdict" lesson describes this very boundary and names the cure —
yet the course was never invoked once across eight paired runs.

THREE claims are guarded here, and the third is the control:
  * the note appears when rooms are declared but levels are not;
  * it names the NUMBER and the NEXT MOVE, not just a reference to the
    lesson;
  * it is ABSENT when HAB000 is true without reservation (no rooms in the
    program) and when levels are declared. A note on every verdict would be
    noise.
"""
import io
import contextlib
import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import course


def _verdict_of(ops):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        course.design_check(ops)
    return buf.getvalue()


def _wall(a, b, level):
    return {"op": "create_wall", "p0_mm": a, "p1_mm": b, "height_mm": 3000,
            "level": {"by": "name", "value": level}, "type": "Типовой - 200мм"}


_SQUARE = [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]
_RING = [_wall(_SQUARE[i], _SQUARE[(i + 1) % 4], "ГЕЛИКОН 01") for i in range(4)]
_ROOM = {"op": "create_room", "xy": [2500, 2000],
         "level": {"by": "name", "value": "ГЕЛИКОН 01"}, "name": "Комната"}


class TheVerdictNamesTheBoundary(unittest.TestCase):
    def test_rooms_declared_but_no_level_gets_the_real_cause(self):
        text = _verdict_of(_RING + [_ROOM])
        self.assertIn("HAB000", text)
        self.assertIn("ПОЧЕМУ ПРОЧИТАНО НОЛЬ", text)
        self.assertIn("1 операций `create_room`", text,
                      "число объявленных помещений не названо")
        self.assertIn("create_level", text, "лекарство не названо")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)
        self.assertIn("не приговор зданию", text,
                      "не сказано, что это граница прибора, а не вердикт")

    def test_no_rooms_at_all_keeps_hab000_plain(self):
        """CONTROL: with no rooms, HAB000 is true, and the note would be noise."""
        text = _verdict_of(list(_RING))
        self.assertIn("HAB000", text)
        self.assertNotIn("ПОЧЕМУ ПРОЧИТАНО НОЛЬ", text)

    def test_a_declared_level_removes_the_note(self):
        """CONTROL FROM THE OTHER SIDE: as soon as a level is declared, the cause
        is different — and the note must disappear, not linger out of
        inertia."""
        ops = ([{"op": "create_level", "name": "ГЕЛИКОН 01", "elev_mm": 0}]
               + _RING + [_ROOM])
        text = _verdict_of(ops)
        self.assertNotIn("ПОЧЕМУ ПРОЧИТАНО НОЛЬ", text)


if __name__ == "__main__":
    unittest.main()
