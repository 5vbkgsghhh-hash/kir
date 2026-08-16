"""Потолок веса формы при съёме — защита живого Revit от зависания.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ И ПОЧЕМУ ИМЕННО ЭТО. `Face.Triangulate` прервать
нельзя, а временные бюджеты проверяются ДО и ПОСЛЕ стадии — значит одна
тяжёлая форма уводит съём за любой бюджет и утаскивает UI-поток Revit.
Замер 14.08.2026: пилястра на 236 тыс. треугольников подвесила Revit 2023
насмерть на полчаса с лишним. Поэтому потолок обязан быть НАКОПИТЕЛЬНЫМ и
проверяться ВНУТРИ обхода граней, а не до него: предсказать вес заранее
дёшево нельзя (замер по 351 форме: у тяжёлых 120..262 грани, у лёгких до 418
— порог по граням не разделяет).

Тесты бьют по трём разным утверждениям, а не по одному:
  1. потолок ЕСТЬ в эмитируемом C# и стоит в обеих заставах обхода;
  2. отказ ТИПИЗИРОВАН и отличим от «не смогли прочитать» и от бюджетов;
  3. счётчик обнуляется НА ЭЛЕМЕНТ, иначе второй элемент падал бы за грехи
     первого.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.geom_extract import (
    GEOMETRY_EXTRACT_SCHEMA_VERSION,
    GeometryFailureReason,
    build_geometry_extract_cs,
    extract_geometry,
)
from kukai.ir.decompile.schema import GEOM_WEIGHT_CEILING


def _payload(elements: list[dict]) -> dict:
    return {
        "schema_version": GEOMETRY_EXTRACT_SCHEMA_VERSION,
        "elements": elements,
    }


def _refused(element_id: str, reason: str, elapsed_ms: int = 7) -> dict:
    """Строка отказа ровно той формы, какую эмитирует прод-C#."""
    return {
        "element_id": element_id,
        "category": "OST_GenericModel",
        "status": "failed",
        "parts": [],
        "errors": [reason],
        "reason": reason,
        "elapsed_ms": elapsed_ms,
    }


class WeightCeilingConstant(unittest.TestCase):
    def test_ceiling_sits_between_storage_limit_and_measured_hang(self) -> None:
        """Число не круглое «на глаз», а зажато двумя замерами.

        Снизу — предел формата авторского опа (`ir/mesh.py`, 4096): ниже него
        потолок резал бы формы, которые ещё можно построить. Сверху —
        замеренное зависание на 236 тыс. треугольников: потолок обязан быть
        заметно ниже, чтобы работа до отказа оставалась ограниченной.
        """
        from kukai.ir.mesh import MAX_TRIANGLES

        self.assertGreaterEqual(GEOM_WEIGHT_CEILING, MAX_TRIANGLES)
        self.assertLess(GEOM_WEIGHT_CEILING, 236_000 // 4)


class WeightCeilingIsEmitted(unittest.TestCase):
    """Потолок обязан ДОЕХАТЬ до Revit, а не остаться числом в питоне."""

    def setUp(self) -> None:
        self.cs = build_geometry_extract_cs(["12345"])

    def test_ceiling_value_reaches_the_emitted_csharp(self) -> None:
        self.assertIn(
            "int __gxWeightCeiling = %d;" % GEOM_WEIGHT_CEILING, self.cs)

    def test_no_placeholder_survives_into_live_revit(self) -> None:
        """Guard на неразрешённый placeholder смотрит и в помощники.

        До правки он проверял только тело, а потолок живёт в помощниках —
        неподставленный `__GX_WEIGHT_CEILING__` уехал бы на машину
        пользователя и не собрался бы там.
        """
        self.assertNotIn("__GX_", self.cs)

    def test_ceiling_is_checked_inside_the_face_loop_not_only_after(self) -> None:
        """Две заставы: одна оплачивает грань, другая не даёт оплатить следующую.

        Одной проверки в `__gxAppendMesh` мало — она срабатывает уже ПОСЛЕ
        тесселяции очередной грани. Вторая стоит перед `Triangulate`, и только
        вместе они делают работу до отказа ограниченной.
        """
        self.assertEqual(
            self.cs.count('__gxWeightSentinel + ": triangles="'), 2)
        loop_head = self.cs.index("foreach (Face __face in __solid.Faces)")
        triangulate = self.cs.index("__face.Triangulate(1.0)", loop_head)
        guard = self.cs.index("__gxWeightCeiling", loop_head)
        self.assertLess(
            guard, triangulate,
            "застава обязана стоять ДО тесселяции следующей грани")

    def test_counter_is_reset_per_element(self) -> None:
        """Иначе второй элемент отказал бы за вес первого."""
        self.assertIn("__gxWeight[0] = 0;", self.cs)
        self.assertIn("__gxWeight[1] = 0;", self.cs)

    def test_refusal_is_emitted_as_a_typed_row_reason(self) -> None:
        self.assertIn('__row["reason"] = __gxWeightSentinel;', self.cs)
        self.assertIn('__row["status"] = "failed";', self.cs)


class WeightCeilingRefusalIsTyped(unittest.TestCase):
    """Отказ обязан быть ОТЛИЧИМ, а не слиться с прочими неудачами."""

    def test_reason_exists_as_a_typed_enum_member(self) -> None:
        self.assertEqual(
            GeometryFailureReason("weight_ceiling_exceeded"),
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED)

    def test_payload_parses_into_a_failure_carrying_that_reason(self) -> None:
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded")]))

        self.assertEqual(len(result.failures), 1)
        failure = result.failures[0]
        self.assertEqual(
            failure.reason, GeometryFailureReason.WEIGHT_CEILING_EXCEEDED)
        self.assertEqual(failure.element_id, "101")

    def test_heavy_shape_is_not_reported_as_empty_geometry(self) -> None:
        """Тяжёлая форма — НЕ «геометрии нет».

        Tier A означает «у элемента нечего снимать». Отказ по весу означает
        «снимать есть что, но это стоит нам живого Revit» — если бы он попал в
        Tier A, элемент молча потерял бы форму и выглядел бы пустым.
        """
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded")]))

        self.assertEqual(result.index, ())
        self.assertEqual(len(result.failures), 1)

    def test_weight_refusal_is_distinct_from_the_time_budgets(self) -> None:
        """Постоянный отказ не должен выглядеть как временный.

        Бюджет говорит «здесь кончилось время» — это приглашение повторить.
        Вес говорит «эта форма неподъёмна» — свойство формы, верное и на
        следующем прогоне. Один код на двоих звал бы к бессмысленному ретраю.
        """
        reasons = {member.value for member in GeometryFailureReason}
        self.assertIn("weight_ceiling_exceeded", reasons)
        self.assertNotEqual(
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED,
            GeometryFailureReason.TIME_BUDGET_EXCEEDED)
        self.assertNotEqual(
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED,
            GeometryFailureReason.CALL_BUDGET_EXHAUSTED)

    def test_one_heavy_shape_does_not_condemn_its_neighbours(self) -> None:
        """Соседи по батчу обязаны сниматься как ни в чём не бывало."""
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded"),
            {
                "element_id": "102",
                "category": "OST_GenericModel",
                "status": "empty",
                "parts": [],
                "errors": [],
            },
        ]))

        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].element_id, "101")
        self.assertEqual(len(result.index), 1)
        self.assertEqual(result.index[0].element_id, "102")


if __name__ == "__main__":
    unittest.main()
