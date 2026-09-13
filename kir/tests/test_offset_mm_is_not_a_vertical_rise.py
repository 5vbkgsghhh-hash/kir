"""ONE WORD, TWO MEANINGS: AN OPENING'S `offset_mm` RUNS ALONG THE HOST, NOT
UPWARD.

Audit finding `F-156` (P0), `kir/viewer/live_scene._z_of`.

The vertical base was taken from a CLOSED list of names, and the common name
`offset_mm` was in it. For `create_door`/`create_window` it means SOMETHING
ENTIRELY DIFFERENT — the distance ALONG the host from its start. Measured
before the fix:

    create_door    offset_mm=3000.0 -> z0=3000.0  z1=3100.0
    create_window  offset_mm=1200.0 -> z0=1200.0  z1=1300.0
    create_wall    base_offset_mm=500.0 -> z0=500.0 z1=3500.0

A door standing three meters from a corner was drawn three meters ABOVE the
floor — above the very opening it stands in. A human sees a building that
will not exist. A homonym under one word: the same kind as
`Observation.unit` against `of_unit` (`assembly_view.py:298`).

🔴 TWO CORRECTIONS TO THE PACKAGE, BOTH LIFTED BY EXECUTION.

1. The package writes: "`sill_mm` is NOT in the registry," and so proposes
   leaving the opening with no vertical base at all. `sill_mm` IS IN THE
   REGISTRY — for both ops (`create_door.sill_mm`, `create_window.sill_mm`).
   This is exactly the opening's REAL vertical: the rise above the host's
   bottom. A window with `sill_mm=900` now draws at 900 mm, not at zero and
   not at 1200.

2. The package proposes a handwritten list `_OFFSET_IS_ALONG_HOST =
   ("create_door", "create_window")`. Such a list chases the registry
   forever and will fall behind on the very first new host-based op. The
   registry knows the trait BY ITSELF: `offset_mm` exists across the whole
   registry in exactly TWO ops, and BOTH have a `host`. So the rule is
   derived — "has a host" means "`offset_mm` runs along it."

An op that is not in the registry is read by the rule as having NO
`offset_mm`: an unknown kind has no right to silently ride upward.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.viewer import live_scene as L


class ПроёмНеУезжаетВверх(unittest.TestCase):

    def test_a_door_offset_along_the_host_is_not_a_rise(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING."""
        z0, z1, known = L._z_of(
            {"op": "create_door", "id": "d1", "offset_mm": 3000.0,
             "host": "w0"}, 0.0)
        self.assertEqual(z0, 0.0, "дверь уехала вверх на расстояние вдоль стены")
        self.assertEqual(z1, L.FALLBACK_HEIGHT_MM)
        self.assertFalse(known)

    def test_a_window_sill_is_the_real_rise(self) -> None:
        """🔴 A CORRECTION TO THE PACKAGE: `sill_mm` IS in the registry, and
        this is the opening's real vertical. Leaving the opening without a
        base would mean trading one wrong for a loss."""
        z0, _z1, _known = L._z_of(
            {"op": "create_window", "id": "wd", "offset_mm": 1200.0,
             "sill_mm": 900.0, "host": "w0"}, 0.0)
        self.assertEqual(z0, 900.0)

    def test_a_wall_base_offset_still_works(self) -> None:
        """🔴 A GREEN OUTCOME, AND IT IS NOT DECORATION. A wall uses
        `base_offset_mm` LAWFULLY; without this case, the check would turn
        green even for someone who threw out `_BASE_FIELDS` entirely."""
        z0, z1, known = L._z_of(
            {"op": "create_wall", "id": "w1", "base_offset_mm": 500.0,
             "height_mm": 3000.0}, 0.0)
        self.assertEqual((z0, z1, known), (500.0, 3500.0, True))

    def test_a_level_elevation_still_works(self) -> None:
        z0, _z1, _k = L._z_of(
            {"op": "create_level", "id": "lv", "elev_mm": 3300.0}, 0.0)
        self.assertEqual(z0, 3300.0)

    def test_an_op_outside_the_registry_does_not_fly_up(self) -> None:
        """The default for an unknown kind — do NOT treat `offset_mm` as a
        vertical. It has no right to silently ride upward."""
        z0, _z1, _k = L._z_of(
            {"op": "такого-опа-нет", "id": "x", "offset_mm": 5000.0}, 0.0)
        self.assertEqual(z0, 0.0)


class ПравилоВыведеноИзРеестраАНеНабрано(unittest.TestCase):

    def test_offset_mm_belongs_only_to_hosted_ops(self) -> None:
        """🔴 THE RULE'S FOUNDATION, CHECKED BY A NUMBER. If tomorrow an op
        appears with `offset_mm` and WITHOUT a `host`, the premise falls
        apart — and this test must turn red and demand a decision, rather
        than silently get it wrong."""
        offenders = []
        with_offset = []
        for name, op in spec.OPS.items():
            names = {p.name for p in op.params}
            if "offset_mm" in names:
                with_offset.append(name)
                if "host" not in names:
                    offenders.append(name)
        self.assertEqual(offenders, [],
                         f"`offset_mm` без хозяина: {offenders} — посылка "
                         f"правила `_base_fields_for` больше не верна")
        self.assertGreaterEqual(len(with_offset), 2)   # denominator control

    def test_the_rule_asks_the_registry_not_a_name_list(self) -> None:
        """What is checked is the rule's BEHAVIOR on both kinds, not the text."""
        self.assertNotIn("offset_mm",
                         L._base_fields_for({"op": "create_door"}))
        self.assertIn("sill_mm", L._base_fields_for({"op": "create_door"}))
        self.assertNotIn("sill_mm",
                         L._base_fields_for({"op": "create_wall"}))
        self.assertIn("base_offset_mm",
                      L._base_fields_for({"op": "create_wall"}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
