"""Точка не обязана нести поворот — иначе теряется и точка.

Находка индекса ловушек 29.07 и её цена, замеренная до починки.

``LocationPoint.Rotation`` документирован Autodesk как НЕПОДДЕРЖИВАЕМЫЙ у части
элементов и бросает ``InvalidOperationException`` (RevitAPI.xml, все шесть
версий 2021–2026, ``P:Autodesk.Revit.DB.LocationPoint.Rotation``): *"This
property is not supported for some elements supporting LocationPoints, such as
AssemblyInstances, Groups, ModelText, Room, and SpotDimensions."*

В ``geometry_store`` это чтение стояло ПЕРЕД тремя присваиваниями и внутри
общего ``catch`` на весь блок локации. Значит у помещения, зоны, текста модели
молча терялся не только поворот, но и САМА ТОЧКА, а элемент уходил в L0 как
``bbox_only``. Замер по 55 сохранённым прогонам четырёх зданий: **12 369
помещений и 566 зон, у всех до единого ``geom_kind: bbox_only``, ``p0_mm:
null``** — ни одно помещение ни в одной модели никогда не получило свою точку.

Тот же почерк ровно тем же членом API уже стоил нам 96.77% групп (коммит
3f54267f); здесь он найден вторым сайтом того же класса.

Второй инвариант, снятый вместе с первым: строгий разбор ТРЕБОВАЛ поворот у
точечной геометрии. Требование было написано в уверенности, что поворот
доступен всегда, и оно же вынуждало эмиссию выбирать между «точка без
поворота» и «ничего»; выбиралось «ничего». Отсутствие поворота у помещения —
факт о модели, а лифт уже отказывает типизированно там, где поворот ему нужен.

Дисциплина §18.7: опровергающий тест ДО починки.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    parse_geometry,
)
from kukai.ir.decompile.schema import L0Element, L0SchemaError
from kukai.ir.decompile.tests.fixtures_decompile import make_element


def _point_row(**overrides):
    row = {
        "geom_kind": "point",
        "curve_kind": None,
        "p0_mm": [1000.0, 2000.0, 0.0],
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": None,
        "bbox_max_mm": None,
    }
    row.update(overrides)
    return row


class PointWithoutRotationParses(unittest.TestCase):
    """Помещение приезжает с точкой и без поворота — это законная строка."""

    def test_geometry_store_accepts_point_without_rotation(self):
        geometry = parse_geometry(_point_row())
        self.assertEqual(list(geometry.p0_mm), [1000.0, 2000.0, 0.0])
        self.assertIsNone(geometry.rotation_deg)

    def test_l0_element_accepts_point_without_rotation(self):
        row = make_element("OST_Rooms", 77001)
        row.update(_point_row())
        element = L0Element.from_dict(row)
        self.assertIsNone(element.rotation_deg)
        self.assertEqual(list(element.p0_mm), [1000.0, 2000.0, 0.0])

    def test_point_still_requires_its_point(self):
        """Послабление касается ТОЛЬКО поворота: точка без точки — по-прежнему
        ошибка схемы, иначе `geom_kind: point` перестал бы что-либо значить."""
        with self.assertRaises(L0SchemaError):
            parse_geometry(_point_row(p0_mm=None))

    def test_curve_still_refuses_rotation(self):
        """Встречный инвариант не тронут: у кривой поворота быть не может."""
        with self.assertRaises(L0SchemaError):
            parse_geometry({
                **_point_row(),
                "geom_kind": "curve",
                "curve_kind": "line",
                "p1_mm": [2000.0, 2000.0, 0.0],
                "rotation_deg": 30.0,
            })


class EmissionOrderIsTheFix(unittest.TestCase):
    """Порядок в эмитируемом C# — и есть починка, поэтому он под тестом."""

    def test_point_is_written_before_rotation_is_read(self):
        body = GEOMETRY_HELPER_CS
        point_write = body.index('__row["p0_mm"] = __point;')
        rotation_read = body.index("__lp.Rotation")
        self.assertLess(
            point_write, rotation_read,
            "чтение поворота обязано идти ПОСЛЕ записи точки: у помещений и "
            "зон оно бросает, и всё, что стоит за ним, теряется")

    def test_rotation_read_has_its_own_guard(self):
        """Между чтением поворота и записью точки обязан стоять свой try —
        общего стража на весь блок локации недостаточно, он и был причиной."""
        body = GEOMETRY_HELPER_CS
        point_write = body.index('__row["p0_mm"] = __point;')
        rotation_read = body.index("__lp.Rotation")
        between = body[point_write:rotation_read]
        self.assertIn(
            "try", between,
            "поворот обязан читаться под СВОИМ стражем, иначе исключение "
            "уносит запись, стоящую рядом")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
