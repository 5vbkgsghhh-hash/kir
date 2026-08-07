"""Цепочка ЧТЕНИЯ уровня — тот же закон, что у цепочки ЗАПИСИ.

ЗАМЕР, ИЗ КОТОРОГО РОДИЛСЯ ЭТОТ ФАЙЛ (03.08.2026, обход восьми настоящих
разборов на диске). У 2367 балок, 116 лестниц и 21 ограждения в L0 стоит
``level_id: null``, и это НЕ свойство моделей — это свойство читателя:

    OST_StructuralFraming  SKLNK 2240/2240 · K2 41 · SOB6.2_AR 86
                           (все 2367 несут STRUCTURAL_BEAM_END0_ELEVATION,
                            то есть это настоящие балки с кривой)
    OST_Stairs             K2 89/89 · SOB6.2_AR 12/12 · демо 15/15
    OST_StairsRailing      SOB6.2_AR 17/27 · K2 4/203

Дом УЖЕ ЗНАЛ правду — но только на стороне записи. Прямая проба 27.07
(``ir/tests/test_hangs_and_lies.BeamLevelWitnessMustReadTheParameterABeamActuallyHas``)
записала у построенной балки:

    INSTANCE_REFERENCE_LEVEL_PARAM = 172458 («L_01_+0.000»)
    FAMILY_LEVEL_PARAM   = -1
    SCHEDULE_LEVEL_PARAM = -1
    LEVEL_PARAM          = нет такого параметра
    fi.LevelId           = -1

Свидетель эмиссии эту правду впитал (``authoring._level_chain_check``),
читатель — нет. Один дом, два разных ответа на один вопрос «какой уровень у
этого элемента»; ``revit_read_helpers`` для того и заведён, чтобы судей было
не два, и его собственный докстринг это требует.

ДВА ДЕФЕКТА, А НЕ ОДИН:

1. в цепочке нет ЗВЕНЬЕВ, в которых уровень у этих категорий и лежит;
2. цепочка ОБРЫВАЕТСЯ на первом НЕ-NULL параметре, а не на первом
   параметре, ДЕРЖАЩЕМ НАСТОЯЩИЙ ElementId. У балки ``SCHEDULE_LEVEL_PARAM``
   существует и равен -1 — то есть даже дописанное в хвост звено было бы
   недостижимо. Ровно это различие ``authoring._level_chain_check`` называет
   словами «"параметр заполнен" и "параметр существует" — разные вещи».

ПОЧЕМУ НОВЫЕ ЗВЕНЬЯ СТРОГО В ХВОСТЕ. Цепочка короткозамкнутая: победитель —
первое звено, держащее настоящий id. Все прежние звенья остаются на прежних
местах, поэтому элемент, у которого уровень находился раньше, находит РОВНО
ТОТ ЖЕ уровень. Приписка в хвост не может изменить ответ — только дать ответ
там, где его не было. Этот порядок здесь и проверяется, чтобы правку нельзя
было «улучшить» перестановкой.
"""
from __future__ import annotations

import pathlib
import sqlite3
import unittest

from kukai.ir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS


#: Прежние звенья — в прежнем порядке. Список существует, чтобы тест на
#: хвост был структурным, а не списком строк.
LEGACY_LEVEL_BIPS = (
    "WALL_BASE_CONSTRAINT",
    "LEVEL_PARAM",
    "SCHEDULE_LEVEL_PARAM",
    "FAMILY_LEVEL_PARAM",
)

#: Новые звенья. У каждого — категория, которую оно спасает, и замер.
ADDED_LEVEL_BIPS = (
    "INSTANCE_REFERENCE_LEVEL_PARAM",       # балки/связи (замер 27.07)
    "STAIRS_BASE_LEVEL_PARAM",              # лестницы (116 шт. в 3 разборах)
    "STAIRS_RAILING_BASE_LEVEL_PARAM",      # ограждения (21 шт. в 2 разборах)
)

TRAP_INDEX = pathlib.Path(
    "/opt/kukai-rebuild1/backend/data/api_traps/revit_api_traps.sqlite")
SHIPPED_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


class ReadChainKnowsWhereTheseCategoriesKeepTheirLevel(unittest.TestCase):
    def test_beam_reference_level_parameter_is_a_link(self) -> None:
        """2367 балок на диске. Уровень балки лежит ТОЛЬКО здесь."""
        self.assertIn("INSTANCE_REFERENCE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)

    def test_stairs_base_level_parameter_is_a_link(self) -> None:
        """116 лестниц. Без уровня узел уходит в ``unassigned-level`` и
        ``_semantic_fold`` его не видит — из-за чего метка ``core`` не
        произведена ни разу за 52 дерева."""
        self.assertIn("STAIRS_BASE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)

    def test_railing_base_level_parameter_is_a_link(self) -> None:
        self.assertIn(
            "STAIRS_RAILING_BASE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)


class ALinkHoldingNoElementDoesNotEndTheChain(unittest.TestCase):
    """`HasValue` истинен и для InvalidElementId — замерено на балке.

    Звено принимается, ТОЛЬКО если держит настоящий ElementId; иначе цепочка
    обрывается на пустом параметре и хвост недостижим. Тот же закон, что в
    ``authoring._level_chain_check``.
    """

    def test_chain_advance_tests_for_a_real_element_id(self) -> None:
        self.assertIn("InvalidElementId", ELEMENT_LEVEL_HELPERS_CS)
        # Условие перехода обязано смотреть на ЗНАЧЕНИЕ, а не только на
        # существование параметра.
        self.assertIn("AsElementId()", ELEMENT_LEVEL_HELPERS_CS)
        self.assertNotIn(
            "if (__levelParam == null)\n", ELEMENT_LEVEL_HELPERS_CS,
            "переход по одному лишь null — тот самый обрыв на -1")


class NewLinksAreStrictlyAtTheTail(unittest.TestCase):
    def test_every_legacy_link_precedes_every_added_link(self) -> None:
        for legacy in LEGACY_LEVEL_BIPS:
            self.assertIn(legacy, ELEMENT_LEVEL_HELPERS_CS, legacy)
        for added in ADDED_LEVEL_BIPS:
            self.assertIn(added, ELEMENT_LEVEL_HELPERS_CS, added)
        last_legacy = max(
            ELEMENT_LEVEL_HELPERS_CS.index(bip) for bip in LEGACY_LEVEL_BIPS)
        first_added = min(
            ELEMENT_LEVEL_HELPERS_CS.index(bip) for bip in ADDED_LEVEL_BIPS)
        self.assertLess(
            last_legacy, first_added,
            "новое звено раньше прежнего = элемент, у которого уровень "
            "находился, может получить ДРУГОЙ уровень")

    def test_legacy_links_keep_their_relative_order(self) -> None:
        positions = [ELEMENT_LEVEL_HELPERS_CS.index(bip)
                     for bip in LEGACY_LEVEL_BIPS]
        self.assertEqual(positions, sorted(positions))


class EveryLinkExistsOnEveryShippedVersion(unittest.TestCase):
    """Имя члена Revit API проверяется индексом ловушек, а не памятью."""

    def test_all_chain_bips_ship_on_all_six(self) -> None:
        if not TRAP_INDEX.exists():
            self.skipTest(f"индекса ловушек нет: {TRAP_INDEX}")
        connection = sqlite3.connect(f"file:{TRAP_INDEX}?mode=ro", uri=True)
        try:
            for bip in LEGACY_LEVEL_BIPS + ADDED_LEVEL_BIPS:
                row = connection.execute(
                    "select versions from member where owner = ? "
                    "and simple = ?",
                    ("Autodesk.Revit.DB.BuiltInParameter", bip),
                ).fetchone()
                self.assertIsNotNone(row, f"{bip} нет в индексе ловушек")
                shipped = tuple(row[0].split(","))
                self.assertEqual(
                    shipped, SHIPPED_VERSIONS,
                    f"{bip} живёт не на всех шести: {row[0]}")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
