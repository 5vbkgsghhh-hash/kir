"""TemplateCanon must not quantize non-millimetre quantities on a mm grid.

Architectural review 2026-07-25, §3.2: the fallback branch of
``_canonical_value`` snapped ANY number onto a 1.0 grid — including
components of an arc's unit axis, radians, and dimensionless scalars. The
consequence was reproduced by running it: two visually different arc
walls produced byte-for-byte the SAME canon (the axis
``[0.7071, 0.7071, 0]`` rounded to ``[1.0, 1.0, 0.0]`` and stopped being a
unit vector, radians landed on a grid with a step of ≈57.3°). This is
"two different buildings → one canon," and TemplateCanon carries the
merkle-store, dedup, diff, the rebuild plan, and the journal on top of it.

The dimensional boundary these tests pin down:
  * quantities in millimetres (``*_mm``) — the CANON_MM grid, and this is
    DELIBERATE (dedup must survive the float noise of Revit's geometry);
  * everything else (axes, radians, dimensionless values) — a fine grid,
    as in FidelityCanon.
"""

from __future__ import annotations

import unittest

from kir.decompile.fold import (
    TEMPLATE_CANON_VERSION,
    canon_hash,
    canon_op,
)


_ORIGIN = (0.0, 0.0, 0.0)


def _arc_wall(x_axis: list[float], start_rad: float, end_rad: float) -> dict:
    return {
        "kind": "op",
        "op_name": "create_wall",
        "params": {
            "p0_mm": [0.0, 0.0],
            "p1_mm": [1000.0, 0.0],
            "height_mm": 3000.0,
            "arc": {
                "center_mm": [2500.0, 0.0, 0.0],
                "radius_mm": 3000.0,
                "x_axis": list(x_axis),
                "y_axis": [0.0, 0.0, 1.0],
                "start_angle_rad": start_rad,
                "end_angle_rad": end_rad,
            },
        },
    }


class TemplateCanonKeepsNonMillimetreQuantities(unittest.TestCase):
    """§3.2: different arcs must produce a DIFFERENT canon."""

    def test_different_arcs_are_not_collapsed(self) -> None:
        a = _arc_wall([0.7071, 0.7071, 0.0], 0.0, 1.0)
        b = _arc_wall([0.6, 0.8, 0.0], 0.3, 0.7)
        self.assertNotEqual(
            canon_op(a, _ORIGIN), canon_op(b, _ORIGIN),
            "две разные дуговые стены дали ОДИН TemplateCanon — "
            "склейка разных зданий под merkle/dedup/rebuild")

    def test_unit_axis_survives_canonicalization(self) -> None:
        """A unit axis must not be rounded into a non-unit one."""

        canon = canon_op(_arc_wall([0.7071, 0.7071, 0.0], 0.0, 1.0), _ORIGIN)
        self.assertNotIn(
            '"x_axis":[1.0,1.0,0.0]', canon.replace(" ", ""),
            "ось [0.7071,0.7071,0] округлилась в [1,1,0] — перестала быть "
            "единичной")

    def test_radians_are_not_on_a_millimetre_grid(self) -> None:
        """An arc span of 0.3→0.7 rad is not equal to 0.0→1.0 rad."""

        near = _arc_wall([1.0, 0.0, 0.0], 0.3, 0.7)
        far = _arc_wall([1.0, 0.0, 0.0], 0.0, 1.0)
        self.assertNotEqual(canon_op(near, _ORIGIN), canon_op(far, _ORIGIN))

    def test_dimensionless_scalars_are_distinguished(self) -> None:
        """coverage 0.8 (the array is 80% filled) ≠ coverage 1.0 (full)."""

        def grid(coverage: float) -> dict:
            return {
                "kind": "op",
                "op_name": "grid_array",
                "params": {"coverage": coverage},
            }

        self.assertNotEqual(
            canon_op(grid(0.8), _ORIGIN), canon_op(grid(1.0), _ORIGIN))


class TemplateCanonKeepsTheMillimetreGrid(unittest.TestCase):
    """Regression: dimensional mm-quantities STAY on the CANON_MM grid.

    This is not a side effect but a condition for dedup to work: the
    canon must survive sub-millimeter float noise in Revit's geometry
    (live evidence from 2026-07-21: 10/40 walls "missed" their canon
    because of a 0.5 mm drift).
    """

    def test_sub_millimetre_noise_still_collapses(self) -> None:
        def wall(height: float) -> dict:
            return {
                "kind": "op",
                "op_name": "create_wall",
                "params": {
                    "p0_mm": [0.0, 0.0],
                    "p1_mm": [1000.0, 0.0],
                    "height_mm": height,
                },
            }

        self.assertEqual(
            canon_op(wall(3000.0), _ORIGIN), canon_op(wall(3000.2), _ORIGIN),
            "мм-величины должны склеиваться на сетке CANON_MM — иначе дедуп "
            "рассыпается о float-шум")


class CanonHashCarriesItsVersion(unittest.TestCase):
    """§3.6: the meaning of canon hashes has already changed twice, and
    the version was not part of the digest."""

    def test_version_is_mixed_into_the_digest(self) -> None:
        node = _arc_wall([1.0, 0.0, 0.0], 0.0, 1.0)
        digest = canon_hash(node, _ORIGIN)

        import hashlib

        naked = hashlib.sha1(
            canon_op(node, _ORIGIN).encode("utf-8")).hexdigest()
        self.assertNotEqual(
            digest, naked,
            "canon_hash считается от голого канона без TEMPLATE_CANON_VERSION "
            "— персистированные хеши молча меняют смысл при смене канона")
        self.assertTrue(TEMPLATE_CANON_VERSION)


if __name__ == "__main__":
    unittest.main()
