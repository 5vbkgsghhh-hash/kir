"""Раздел зонной раскладки берётся из таблицы экстрактора, а не из своего
словаря внутри fold.py.

Повод (28.07): в пакете лежало ТРИ источника правды об одном понятии
«раздел» — `registry_base.DISCIPLINES` (закрытый словарь значений), колонка
`CategorySpec.discipline` в `decompile/extract.py` (покрывает все категории
таблицы) и `_CATEGORY_DISCIPLINE` внутри `fold.py`. Третий знал 17 категорий
из 47 и говорил на своём лексиконе («architecture»/«structure»/
«coordination»), поэтому ВСЕ 25 категорий инженерных разделов — светильники,
фитинги труб, короба — в зонной раскладке падали в «unknown». Раздел ЭОМ
целиком выглядел как «не знаем, что это», хотя таблица экстрактора знает про
него всё.

Тесты ниже фиксируют закон, а не текущий вывод: раскладка обязана называть
раздел ровно так, как его называет таблица экстрактора, и молчать («unknown»)
только там, где таблица действительно молчит.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile import fold as fold_module
from kukai.ir.decompile.fold import TreeNode, fold_document
from kukai.ir.decompile.lift import lift_document
from kukai.ir.registry_base import DISCIPLINES
from kukai.ir.decompile.tests.test_fold import (  # noqa: E402
    _curve_element,
    _document,
    _kind,
    _point_element,
)

_LEVEL = ("1", "L1", 0.0)


def _discipline_labels(tree: TreeNode) -> set[str]:
    return {
        node["macro"]["discipline"]
        for node in _kind(tree, "group")
        if node["macro"] and node["macro"].get("type") == "discipline"
    }


def _zoned(rows: list[dict]) -> TreeNode:
    # rooms=[] — этаж без комнат, семантическая раскладка невозможна, и FOLD
    # уходит в зонную ветку, где и живёт разбивка по разделам.
    document = _document([_LEVEL], rows, rooms=[])
    return fold_document(document, lift_document(document))


class ZonedDisciplineFromExtractTableTests(unittest.TestCase):
    def test_engineering_category_is_not_unknown(self) -> None:
        # Опровергающий случай: светильник — ЭОМ. В таблице экстрактора
        # OST_LightingFixtures стоит с discipline="electrical"; раскладка
        # обязана прочитать ту же строку, а не гадать по своему списку.
        tree = _zoned([
            _point_element("OST_LightingFixtures", 15_000, _LEVEL,
                           (1_000.0, 1_000.0, 0.0)),
        ])

        labels = _discipline_labels(tree)

        self.assertEqual(labels, {"electrical"})
        self.assertNotIn(
            "unknown", labels,
            "категория есть в таблице экстрактора — «не знаем» здесь ложь")

    def test_every_engineering_section_is_named(self) -> None:
        # По одному представителю от каждого инженерного раздела: раскладка
        # обязана назвать все три, а не свалить их в одну кучу.
        tree = _zoned([
            _point_element("OST_LightingFixtures", 15_010, _LEVEL,
                           (1_000.0, 1_000.0, 0.0)),
            _point_element("OST_PipeFitting", 15_011, _LEVEL,
                           (1_200.0, 1_000.0, 0.0)),
            _point_element("OST_DuctFitting", 15_012, _LEVEL,
                           (1_400.0, 1_000.0, 0.0)),
            _point_element("OST_StructuralTruss", 15_013, _LEVEL,
                           (1_600.0, 1_000.0, 0.0)),
            _point_element("OST_Ceilings", 15_014, _LEVEL,
                           (1_800.0, 1_000.0, 0.0)),
        ])

        self.assertEqual(
            _discipline_labels(tree),
            {"electrical", "plumbing", "mechanical", "structural",
             "architectural"})

    def test_lexicon_is_the_package_wide_closed_set(self) -> None:
        # Лексикон один на пакет. Прежние «architecture»/«structure» из
        # собственного словаря fold.py в DISCIPLINES не входят и не должны
        # появляться ни на одном документе.
        tree = _zoned([
            _curve_element("OST_Walls", 15_020, _LEVEL,
                           (0.0, 0.0, 0.0), (4_000.0, 0.0, 0.0)),
            _point_element("OST_StructuralColumns", 15_021, _LEVEL,
                           (500.0, 500.0, 0.0)),
            _curve_element("OST_PipeCurves", 15_022, _LEVEL,
                           (0.0, 800.0, 0.0), (4_000.0, 800.0, 0.0)),
            _point_element("OST_LightingFixtures", 15_023, _LEVEL,
                           (900.0, 900.0, 0.0)),
        ])

        labels = _discipline_labels(tree)

        self.assertTrue(labels)
        self.assertLessEqual(labels, set(DISCIPLINES) | {"unknown"})
        self.assertNotIn("architecture", labels)
        self.assertNotIn("structure", labels)
        self.assertNotIn("coordination", labels)

    def test_grid_is_shared_not_a_private_coordination_label(self) -> None:
        # Оси/уровни в таблице экстрактора помечены «shared» — «принадлежит
        # всем», а не отдельным разделом «координация», которого в лексиконе
        # пакета нет.
        tree = _zoned([
            _curve_element("OST_Grids", 15_030, _LEVEL,
                           (0.0, 0.0, 0.0), (6_000.0, 0.0, 0.0)),
        ])

        self.assertEqual(_discipline_labels(tree), {"shared"})

    def test_category_outside_the_table_stays_unknown(self) -> None:
        # Честное «не знаем» остаётся ровно там, где таблица молчит: догадка
        # по имени категории была бы хуже пустоты.
        row = _point_element("OST_Furniture", 15_040, _LEVEL,
                             (1_000.0, 1_000.0, 0.0))
        row["category"] = "OST_SomethingTheTableDoesNotKnow"

        self.assertEqual(_discipline_labels(_zoned([row])), {"unknown"})

    def test_fold_holds_no_private_discipline_dictionary(self) -> None:
        # Закон «второго словаря об одном понятии быть не должно» — проверяем
        # структурно, иначе он держится только на памяти ревьюера.
        self.assertFalse(
            hasattr(fold_module, "_CATEGORY_DISCIPLINE"),
            "fold.py снова завёл собственную таблицу разделов")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
