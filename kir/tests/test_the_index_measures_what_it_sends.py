"""THE BUILDING INDEX MEASURES WHAT IT ACTUALLY SENDS OUT.

WHY THIS FILE APPEARED ON 30.08.2026 (audit finding F-294).

`build_index` serialized the payload, MEASURED it, compared it against the
ceiling — and only AFTER that appended the `bytes` field, without
re-measuring. There are two consequences, and the second is heavier than
the first:

  1. the declared `bytes` is smaller than the actual frame by exactly the
     length of `,"bytes":NNN` — 12 bytes for a three-digit number, up to 16
     for an eight-digit one;
  2. AT THE BOUNDARY the instrument declared `tier=full` and sent out a
     frame EXCEEDING the very ceiling it exists to hold.

The refusal branch suffered the same defect: `census_only["bytes"]` was
computed before the assignment.

An instrument that measures something other than what it sends out guards
nothing.
"""
from __future__ import annotations

import json
import types
import unittest

from kir.building_index import (
    CEILING_BYTES,
    TIER_CENSUS,
    TIER_FULL,
    _frame_bytes,
    _stamp_frame_bytes,
    build_index,
)


def _элемент(i: int):
    return types.SimpleNamespace(
        element_id=i, category="OST_Walls", level_name="L1",
        type_name="Типовой - 200мм", p0_mm=None, p1_mm=None,
        bbox_min_mm=None, bbox_max_mm=None, host_id=None, params=None)


def _кадр(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":"), default=str).encode("utf-8"))


class ЗаявленныйРазмерРавенНастоящему(unittest.TestCase):

    def test_the_full_tier_declares_its_own_frame(self):
        payload = build_index([_элемент(1)])
        self.assertEqual(payload["tier"], TIER_FULL)
        self.assertEqual(payload["bytes"], _кадр(payload),
                         "индекс заявил размер, которого у кадра нет")

    def test_the_census_tier_declares_its_own_frame(self):
        """The refusal branch computed the number BEFORE the assignment —
        the same defect."""
        payload = build_index([_элемент(i) for i in range(40)],
                              ceiling_bytes=300)
        self.assertEqual(payload["tier"], TIER_CENSUS)
        self.assertEqual(payload["bytes"], _кадр(payload))

    def test_it_holds_across_many_sizes(self):
        """The difference is constant in the field's length, but the
        NUMBER OF DIGITS floats — so a range is checked, not a single
        case."""
        for n in list(range(1, 40)) + [120, 400]:
            with self.subTest(элементов=n):
                payload = build_index([_элемент(i) for i in range(n)])
                self.assertEqual(payload["bytes"], _кадр(payload))


class ПотолокДержитТО_ЧТО_УЕЗЖАЕТ(unittest.TestCase):

    def test_a_frame_at_the_ceiling_does_not_exceed_it(self):
        """🔴 THE MAIN POINT. The ceiling is set EXACTLY at the frame size:
        the instrument must deliver the full layer and not exceed the
        ceiling by even one byte."""
        эталон = build_index([_элемент(1)])
        payload = build_index([_элемент(1)],
                              ceiling_bytes=эталон["bytes"])
        self.assertEqual(payload["tier"], TIER_FULL)
        self.assertLessEqual(_кадр(payload), эталон["bytes"],
                             "кадр превысил потолок, который прибор держит")

    def test_one_byte_below_the_frame_falls_back_to_census(self):
        """A NARROWNESS CONTROL: the instrument did not simply become
        "always let it through." A ceiling one byte below the frame must
        give a census."""
        эталон = build_index([_элемент(1)])
        payload = build_index([_элемент(1)],
                              ceiling_bytes=эталон["bytes"] - 1)
        self.assertEqual(payload["tier"], TIER_CENSUS)

    def test_the_default_ceiling_is_not_moved_by_this_fix(self):
        """The fix changes the MEASUREMENT, not the ceiling."""
        self.assertEqual(CEILING_BYTES, 8388608)


class НеподвижнаяТочкаДостигаетсяЦИКЛОМ_АНеДВУМЯПРОХОДАМИ(unittest.TestCase):
    """🔴 WHY THERE IS A LOOP HERE, RATHER THAN "TWO PASSES CONVERGE."

    Appending the number lengthens its own written form, and at a
    digit-count boundary two passes are NOT ENOUGH. The finding's patch
    proposed exactly two passes; a measurement showed a case where, after
    them, 100 was declared for a frame of 101. The test holds exactly this
    case, not "usually converges."
    """

    @staticmethod
    def _два_прохода(payload: dict) -> dict:
        payload["bytes"] = 0
        payload["bytes"] = _frame_bytes(payload)
        payload["bytes"] = _frame_bytes(payload)
        return payload

    def test_two_passes_are_provably_not_enough(self):
        набивка = None
        for pad in range(60, 200):
            проба = self._два_прохода({"x": "a" * pad, "bytes": 0})
            if проба["bytes"] != _frame_bytes(проба):
                набивка = pad
                break
        self.assertIsNotNone(
            набивка,
            "границы разрядности не нашлось — предмет теста исчез, и его надо "
            "переписать, а не оставить зелёным")

    def test_the_loop_reaches_the_fixed_point_where_two_passes_do_not(self):
        набивка = None
        for pad in range(60, 200):
            проба = self._два_прохода({"x": "a" * pad, "bytes": 0})
            if проба["bytes"] != _frame_bytes(проба):
                набивка = pad
                break
        payload = {"x": "a" * набивка, "bytes": 0}
        size = _stamp_frame_bytes(payload)
        self.assertEqual(size, _frame_bytes(payload))
        self.assertEqual(payload["bytes"], _frame_bytes(payload))

    def test_the_stamp_never_understates(self):
        """Understating the size brings back the original defect. Error
        must lean toward caution, so what is checked is NON-understatement,
        not mere equality."""
        for pad in range(60, 140):
            with self.subTest(набивка=pad):
                payload = {"x": "a" * pad, "bytes": 0}
                _stamp_frame_bytes(payload)
                self.assertGreaterEqual(payload["bytes"], _frame_bytes(payload))


if __name__ == "__main__":
    unittest.main()
