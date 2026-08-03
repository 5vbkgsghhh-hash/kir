"""TemplateCanon must not quantize non-millimetre quantities on a mm grid.

Архитектурный разбор 2026-07-25, §3.2: fallback-ветка ``_canonical_value``
клала на сетку 1.0 ЛЮБОЕ число — включая компоненты единичных осей дуги,
радианы и безразмерные скаляры.  Следствие воспроизводилось запуском: две
визуально разные дуговые стены давали побайтово ОДИН канон (ось
``[0.7071, 0.7071, 0]`` округлялась в ``[1.0, 1.0, 0.0]`` и переставала быть
единичной, радианы ложились на сетку с шагом ≈57.3°).  Это «два разных здания →
один канон», а на TemplateCanon стоят merkle-store, dedup, diff, rebuild-план и
journal.

Дименсиональная граница, которую фиксируют эти тесты:
  * величины в миллиметрах (``*_mm``) — сетка CANON_MM, это НАМЕРЕННО (дедуп
    должен переживать float-шум ревитовской геометрии);
  * всё остальное (оси, радианы, безразмерные) — тонкая сетка, как в
    FidelityCanon.
"""

from __future__ import annotations

import unittest

from kukai.ir.decompile.fold import (
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
    """§3.2: разные дуги обязаны давать РАЗНЫЙ канон."""

    def test_different_arcs_are_not_collapsed(self) -> None:
        a = _arc_wall([0.7071, 0.7071, 0.0], 0.0, 1.0)
        b = _arc_wall([0.6, 0.8, 0.0], 0.3, 0.7)
        self.assertNotEqual(
            canon_op(a, _ORIGIN), canon_op(b, _ORIGIN),
            "две разные дуговые стены дали ОДИН TemplateCanon — "
            "склейка разных зданий под merkle/dedup/rebuild")

    def test_unit_axis_survives_canonicalization(self) -> None:
        """Единичная ось не должна округляться до неединичной."""

        canon = canon_op(_arc_wall([0.7071, 0.7071, 0.0], 0.0, 1.0), _ORIGIN)
        self.assertNotIn(
            '"x_axis":[1.0,1.0,0.0]', canon.replace(" ", ""),
            "ось [0.7071,0.7071,0] округлилась в [1,1,0] — перестала быть "
            "единичной")

    def test_radians_are_not_on_a_millimetre_grid(self) -> None:
        """Раствор дуги 0.3→0.7 рад не равен 0.0→1.0 рад."""

        near = _arc_wall([1.0, 0.0, 0.0], 0.3, 0.7)
        far = _arc_wall([1.0, 0.0, 0.0], 0.0, 1.0)
        self.assertNotEqual(canon_op(near, _ORIGIN), canon_op(far, _ORIGIN))

    def test_dimensionless_scalars_are_distinguished(self) -> None:
        """coverage 0.8 (массив заполнен на 80%) ≠ coverage 1.0 (полный)."""

        def grid(coverage: float) -> dict:
            return {
                "kind": "op",
                "op_name": "grid_array",
                "params": {"coverage": coverage},
            }

        self.assertNotEqual(
            canon_op(grid(0.8), _ORIGIN), canon_op(grid(1.0), _ORIGIN))


class TemplateCanonKeepsTheMillimetreGrid(unittest.TestCase):
    """Регрессия: дименсиональные мм-величины ОСТАЮТСЯ на сетке CANON_MM.

    Это не побочный эффект, а условие работы дедупа: канон обязан переживать
    суб-миллиметровый float-шум ревитовской геометрии (живое свидетельство
    2026-07-21: 10/40 стен «промахивались» мимо канона из-за дрейфа 0.5 мм).
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
    """§3.6: смысл канон-хешей уже менялся дважды, а версия в digest не входила."""

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
