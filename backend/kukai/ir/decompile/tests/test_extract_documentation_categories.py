"""Волна 29.07 — чтение РАБОЧЕЙ ДОКУМЕНТАЦИИ: размеры, марки, примечания.

Повод замерен на настоящей РД (13A-RD-AR-K2_v33, слепок ``k2_ar_rd_v6``):
покрытие ОТ ДОКУМЕНТА 9.61 %, в переписи 112 категорий и 310 558 элементов,
а таблица извлечения читала 54 категории = 55 293 элемента (17.80 %).
Бо́льшая часть непрочитанного вне таблицы ЗАКОННО (эскизы, автонанесение,
служебное), но вместе с ней невидимым лежало содержание самой документации:
размеры 13 905, марки помещений 11 585, линии 9 407, элементы узлов 3 046,
текстовые примечания 2 697.

Здесь проверяется ровно то, что нельзя нарушать:

  * индекс РАНЕЕ существовавших категорий не сдвинулся (формат возобновления);
  * новые строки есть и стоят В ХВОСТЕ;
  * коллектор каждой строки спрашивает ИМЕННО СВОЮ категорию (19 почти
    одинаковых строк подряд — идеальная почва для копипасты);
  * перепись после расширения считает их ПРОЧИТАННЫМИ, а не «вне таблицы»;
  * и — опровергающая половина — производное, которое мы сознательно НЕ
    брали, по-прежнему честно числится вне таблицы.

Имена всех 19 категорий проверены компиляцией 6/6 на 2021-2026 (членов
BuiltInCategory в RevitAPI.xml нет вовсе — единственный честный оракул это
компайл-сервис). Тем же прогоном взят контроль: OST_CurtainGridWall и
OST_CurtainGridsSlopedGlazing не компилируются ни на одной версии (CS0117),
что воспроизводит запись, сделанную в extract.py волной 28.07.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile import extract as ex
from kukai.ir.decompile.census import UnscannedReason, reconcile_census
from kukai.ir.decompile.schema import CensusEntry, L0Document
from kukai.ir.decompile.schema import GridInfo, LevelInfo, ProjectInfo
from kukai.security.validation import validate_code_safety


# Порядок 54 категорий, каким он был ДО этой волны (git HEAD, 29.07).
# Заморожен ЦЕЛИКОМ, а не первыми двадцатью двумя: индекс категории —
# часть формата возобновления (``EXTRACT_CATEGORIES[len(processed):]``),
# поэтому вставка в середину ЛЮБОГО из этих участков перепутала бы уже
# начатые извлечения и все существующие L0. Старый тест замораживал только
# префикс из 22 имён, и позиции 22..53 — весь ЭОМ/ОВ/ВК/КР-набор, витражи и
# изоляция — не были защищены ничем.
CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE = (
    "OST_Walls", "OST_Floors", "OST_Roofs", "OST_Columns",
    "OST_StructuralColumns", "OST_StructuralFraming",
    "OST_StructuralFoundation", "OST_Doors", "OST_Windows", "OST_Stairs",
    "OST_StairsRailing", "OST_Rooms", "OST_Grids", "OST_Levels",
    "OST_PipeCurves", "OST_DuctCurves", "OST_CableTray", "OST_Furniture",
    "OST_GenericModel", "DirectShape", "ImportInstance", "OST_RasterImages",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures",
    "OST_LightingFixtures", "OST_LightingDevices", "OST_CableTrayFitting",
    "OST_Conduit", "OST_ConduitFitting", "OST_MechanicalEquipment",
    "OST_DuctFitting", "OST_DuctTerminal", "OST_FlexDuctCurves",
    "OST_MEPSpaces", "OST_PlumbingFixtures", "OST_PipeFitting",
    "OST_PipeAccessory", "OST_FlexPipeCurves", "OST_Sprinklers",
    "OST_StructuralTruss", "OST_Ceilings", "OST_Ramps",
    "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_Casework",
    "OST_SpecialityEquipment", "OST_Areas", "OST_CurtaSystem",
    "OST_CurtainGridsWall", "OST_CurtainGridsRoof",
    "OST_CurtainGridsCurtaSystem", "OST_PipeInsulations",
    "OST_DuctInsulations", "OST_DuctLinings",
)

# Замер переписи k2_ar_rd_v6: категория -> сколько элементов в ДОКУМЕНТЕ.
# Это содержание рабочей документации, ради которого волна и сделана.
MEASURED_DOCUMENTATION_CATEGORIES = {
    "OST_Dimensions": 13_905,
    "OST_RoomTags": 11_585,
    "OST_Lines": 9_407,
    "OST_TelephoneDevices": 4_479,
    "OST_MultiCategoryTags": 3_669,
    "OST_MechanicalEquipmentTags": 3_048,
    "OST_DetailComponents": 3_046,
    "OST_TextNotes": 2_697,
    "OST_RoomSeparationLines": 2_313,
    "OST_SpotElevations": 2_292,
    "OST_GenericAnnotation": 1_954,
    "OST_DoorTags": 1_337,
    "OST_MaterialTags": 339,
    "OST_StructuralFramingTags": 161,
    "OST_FloorTags": 147,
    "OST_WallTags": 92,
    "OST_StairsRailingTags": 57,
    "OST_SpotSlopes": 46,
    "OST_AreaTags": 13,
}

# Тот же замер, ПРОИЗВОДНОЕ И ВНУТРЕННЕЕ: сюда мы сознательно не пошли.
# Оно обязано остаться «вне таблицы» — иначе волна съела бы правило допуска.
MEASURED_DERIVED_CATEGORIES = {
    "OST_AreaSchemeLines": 61_520,
    "OST_SketchLines": 38_093,
    "OST_WeakDims": 19_547,
    "OST_AnalyticalNodes": 2_744,
    "OST_StairsPaths": 689,
    "OST_Constraints": 867,
}


def _document(census: dict[str, int]) -> L0Document:
    """Документ БЕЗ извлечённых элементов — только перепись.

    Ноль извлечённого выбран намеренно: он показывает ПРИЧИНУ в чистом
    виде. Категория вне таблицы и категория в таблице, которую не успели
    прочитать, дают одинаковый недобор и обязаны получить РАЗНЫЕ причины.
    """
    return L0Document(
        doc_name="k2-census-shape",
        revit_version="2023",
        units="mm",
        change_stamp="doc-wave-v1",
        levels=(LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0),),
        grids=(GridInfo(id="7001", name="1", p0_mm=[0.0, 0.0, 0.0],
                        p1_mm=[0.0, 9_000.0, 0.0]),),
        rooms=(),
        project_info=ProjectInfo(name="К2", address="а",
                                 building_type_hint=None),
        elements=(),
        category_status=(),
        census=tuple(
            CensusEntry(key=key, name="", count=count)
            for key, count in sorted(census.items())),
    )


class TheResumeFormatIsNotDisturbed(unittest.TestCase):
    """Дописка в конец обязана оставить чужие индексы на месте."""

    def test_every_earlier_category_keeps_its_index(self) -> None:
        before = CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE
        self.assertEqual(
            ex.EXTRACT_CATEGORIES[:len(before)], before,
            "порядок ранее существовавших категорий сдвинулся — это ломает "
            "возобновление уже начатых извлечений и все существующие L0")

    def test_the_table_only_grew(self) -> None:
        self.assertGreater(len(ex.EXTRACT_CATEGORIES),
                           len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        self.assertEqual(len(set(ex.EXTRACT_CATEGORIES)),
                         len(ex.EXTRACT_CATEGORIES),
                         "категория продублирована")

    def test_documentation_categories_live_in_the_tail(self) -> None:
        tail = ex.EXTRACT_CATEGORIES[
            len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE):]
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertIn(name, ex.EXTRACT_CATEGORIES)
                self.assertIn(
                    name, tail,
                    "новая категория обязана быть ДОПИСАНА в конец, а не "
                    "вставлена в середину")


class EachRowAsksForItsOwnCategory(unittest.TestCase):
    """19 почти одинаковых строк подряд — идеальная почва для копипасты."""

    def test_collector_names_the_same_category_as_the_spec(self) -> None:
        """Проверяется ТОЧНОЕ правило, а не похожее на него.

        Не «имя начинается с OST_ ⇒ коллектор по категории»: OST_Grids и
        OST_Levels собираются классом (``.OfClass(typeof(Grid))``) намеренно
        — оси и уровни надёжнее берутся типом, чем категорией. Правило,
        которое здесь нельзя нарушать, другое: ЕСЛИ коллектор ходит по
        ``OfCategory``, он обязан назвать СВОЮ категорию. Ровно это и ловит
        копипасту в девятнадцати почти одинаковых строках подряд.
        """
        checked = 0
        for spec in ex._CATEGORY_SPECS:
            if ".OfCategory(" not in spec.collector_cs:
                continue
            with self.subTest(category=spec.name):
                self.assertEqual(
                    spec.collector_cs,
                    f".OfCategory(BuiltInCategory.{spec.name})",
                    "коллектор спрашивает ЧУЖУЮ категорию")
                checked += 1
        self.assertGreaterEqual(checked, len(MEASURED_DOCUMENTATION_CATEGORIES))

    def test_emitted_bodies_stay_safe_and_name_the_category(self) -> None:
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                probe = ex.build_category_probe_cs(name)
                page = ex.build_category_batch_cs(name)
                for body in (probe, page):
                    self.assertIn(f"BuiltInCategory.{name})", body)
                    self.assertIn("WhereElementIsNotElementType()", body)
                    self.assertIsNone(validate_code_safety(body))
                    # Чтение остаётся чтением.
                    self.assertNotIn("Transaction", body)


class AnnotationShapedRowsSurviveTheSchema(unittest.TestCase):
    """Главный риск волны, проверяемый ОФЛАЙН.

    Аннотация — не стена: у размера нет ни уровня, ни Location, а
    ``GetTypeId()`` у линии вполне может вернуть InvalidElementId. Если бы
    схема L0 требовала непустой ``type_id`` или уровень, то ПЕРВАЯ ЖЕ
    страница новой категории упала бы разбором, категория получила бы
    PARTIAL, и волна выглядела бы как поломка компилятора вместо честного
    чтения. Живого Revit здесь нет, поэтому проверяется ровно то, что
    проверяемо офлайн: строка той формы, которую даст мост, проходит схему.
    """

    def _row(self, category: str, **overrides: object) -> dict:
        row: dict = {
            "element_id": "123456",
            "category": category,
            "category_ru": "",
            "type_id": "",       # линия без типа — законный случай
            "type_name": "",
            "level_id": None,    # у аннотации уровня нет
            "level_name": None,
            "geom_kind": "bbox_only",
            "curve_kind": None,
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": [0.0, 0.0, 0.0],
            "bbox_max_mm": [100.0, 10.0, 0.0],
            "host_id": None,
            "params": {},
            "design_option": None,
            "phase_created": None,
            "workset": None,
        }
        row.update(overrides)
        return row

    def test_no_type_and_no_level_is_accepted(self) -> None:
        from kukai.ir.decompile.geometry_store import parse_geometry
        from kukai.ir.decompile.schema import L0Element

        for category in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=category):
                row = self._row(category)
                row.update(parse_geometry(row).to_element_fields())
                element = L0Element.from_dict(row)
                self.assertEqual(element.category, category)
                self.assertEqual(element.type_id, "")
                self.assertIsNone(element.level_id)

    def test_an_element_revit_gives_no_bbox_for_is_still_an_element(
            self) -> None:
        """Габарита может не быть вовсе — это не повод терять элемент."""
        from kukai.ir.decompile.geometry_store import parse_geometry
        from kukai.ir.decompile.schema import L0Element

        row = self._row("OST_Dimensions", bbox_min_mm=None, bbox_max_mm=None)
        row.update(parse_geometry(row).to_element_fields())
        element = L0Element.from_dict(row)
        self.assertEqual(element.element_id, "123456")


class TheCensusNowCountsThemAsRead(unittest.TestCase):
    """Опровергающая пара: было «вне таблицы» — стало прочитанным."""

    def test_before_the_wave_every_row_was_invisible_to_reading(self) -> None:
        """Состояние ДО — воспроизведено старой таблицей, а не памятью."""
        document = _document(MEASURED_DOCUMENTATION_CATEGORIES)
        balance = reconcile_census(
            document,
            table=frozenset(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        self.assertEqual(balance.categories_scanned, 0)
        by_category = {row.category: row for row in balance.rows}
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_OUTSIDE_TABLE)

    def test_after_the_wave_none_of_them_is_outside_the_table(self) -> None:
        document = _document(MEASURED_DOCUMENTATION_CATEGORIES)
        balance = reconcile_census(document)
        self.assertEqual(balance.categories_scanned,
                         len(MEASURED_DOCUMENTATION_CATEGORIES))
        by_category = {row.category: row for row in balance.rows}
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertNotEqual(
                    by_category[name].reason,
                    UnscannedReason.CATEGORY_OUTSIDE_TABLE,
                    "категория в таблице не может числиться вне таблицы")
                # Прочитать не успели — но это ДРУГАЯ, честная причина.
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_SHORT_READ)

    def test_derived_content_is_still_honestly_outside_the_table(self) -> None:
        """Волна не имела права съесть правило допуска.

        Эскизы, автонанесение размеров, аналитика и зависимости — производное
        от другого элемента. Их отсутствие в таблице не дефект, а решение, и
        перепись обязана продолжать называть их вслух.
        """
        document = _document(MEASURED_DERIVED_CATEGORIES)
        balance = reconcile_census(document)
        self.assertEqual(balance.categories_scanned, 0)
        by_category = {row.category: row for row in balance.rows}
        for name in MEASURED_DERIVED_CATEGORIES:
            with self.subTest(category=name):
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_OUTSIDE_TABLE)

    def test_the_document_denominator_never_moves(self) -> None:
        """Расширение таблицы меняет ПРОЧИТАННОЕ, а не размер документа.

        Знаменатель §18.1 — перепись, и она про документ, а не про нашу
        выборку. Если бы расширение таблицы двигало census_total, любой
        процент покрытия можно было бы улучшить, дописав строку.
        """
        census = dict(MEASURED_DOCUMENTATION_CATEGORIES)
        census.update(MEASURED_DERIVED_CATEGORIES)
        document = _document(census)
        before = reconcile_census(
            document,
            table=frozenset(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        after = reconcile_census(document)
        self.assertEqual(before.census_total, after.census_total)
        self.assertEqual(before.census_total, sum(census.values()))
        # А вот СКОЛЬКО категорий читается — обязано вырасти ровно на волну.
        self.assertEqual(after.categories_scanned - before.categories_scanned,
                         len(MEASURED_DOCUMENTATION_CATEGORIES))


class AnOlderSnapshotIsNamedNotReinterpreted(unittest.TestCase):
    """Цена расширения таблицы, названная вслух и закреплённая тестом.

    ЭТОТ КЛАСС СМЕНИЛ ДИСПОЗИЦИЮ 29.07, И ВОТ ПОЧЕМУ. В первой редакции он
    требовал, чтобы старый слепок ОТКАЗЫВАЛ («footer precedes one or more
    fixed categories»), и был прав в главном: молча дочитать старый поток
    как полный — значит завести второй диалект, где слово «complete» у двух
    слепков значит разное. Ошибка была не в запрете, а в том, что кроме
    отказа не предлагалось НИЧЕГО: у диалекта не было версии, поэтому
    единственным способом не соврать оставалось не читать.

    Тот же день показал цену: ``L0_SCHEMA_VERSION`` не менялся НИ РАЗУ, а
    таблица росла ШЕСТЬ раз (22 -> 47 -> 48 -> 51 -> 54 -> 73), то есть
    каждый прошлый рост так же обесценивал накопленное — 53 целых слепка на
    диске, снятых с живых моделей за одиннадцать дней, переставали
    открываться. Закон дома отвечает на это не отказом, а именем: диалект
    изменился — версия обязана это назвать (так же поступили с индексом
    витражей, 6b486c08).

    Поэтому теперь: слепок ЧИТАЕТСЯ, его поколение НАЗЫВАЕТСЯ, а категории,
    которых в таблице тогда не было, перечисляются поимённо. Запрет остался
    ровно там, где он и был по существу, — на тихой переинтерпретации: ни
    одна из недостающих категорий не смеет выглядеть как «прочитано ноль».
    Лестница поколений и её сторож — в ``schema.py``, проверка на настоящих
    байтах корпуса — в ``test_l0_dialect.py``.
    """

    def _stream(self, path, categories) -> None:
        from kukai.ir.decompile.schema import (
            CategoryState, CategoryStatus, L0_SCHEMA_VERSION)
        from kukai.ir.decompile.tests.fixtures_decompile import (
            project1_metadata)

        with open(path, "wb") as handle:
            ex._write_record(handle, {
                "record": "header",
                "schema_version": L0_SCHEMA_VERSION,
                "document": ex._parse_metadata(
                    project1_metadata(), "snapshot-v1").metadata_dict(),
            })
            for name in categories:
                ex._write_record(handle, {
                    "record": "category_status",
                    "status": CategoryStatus(
                        category=name, state=CategoryState.COMPLETE,
                        extracted_count=0, expected_count=0).to_dict(),
                })
            ex._write_record(handle, {
                "record": "footer", "stream_complete": True,
                "element_count": 0, "link_count": 0,
                "category_count": len(categories),
            })

    def test_a_stream_written_under_the_old_table_reads_and_is_named(self) -> None:
        """Старый слепок читается — и сам называет своё поколение."""
        import tempfile
        from pathlib import Path

        from kukai.ir.decompile.schema import (
            categories_outside_dialect, resolve_dialect)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE)
            reader = ex.L0JSONLReader(path)
            reader.validate()
            expected = resolve_dialect(
                len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE),
                ex.EXTRACT_CATEGORIES)
            self.assertEqual(reader.dialect().version, expected.version)
            # Недостающее НАЗВАНО поимённо, а не досчитано нулями.
            #
            # Проверяется РАВЕНСТВО множеству «всё, что дописано в таблицу
            # ПОСЛЕ этого поколения», а не одной волне: после волны рабочей
            # документации таблица росла снова (03.08 — проёмы отдельными
            # элементами), и прибитая к одной волне константа превращала
            # ЗАКОННЫЙ рост в падение. Смысл теста при этом не ослаб: хвост
            # по-прежнему сверяется ПОИМЁННО и целиком — он просто берётся у
            # самой таблицы, а не переписывается от руки на каждую волну.
            absent = categories_outside_dialect(
                reader.dialect(), ex.EXTRACT_CATEGORIES)
            added_since = set(
                ex.EXTRACT_CATEGORIES[
                    len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE):])
            self.assertEqual(set(absent), added_since)
            # ...и внутри него ОБЯЗАНЫ лежать обе волны поимённо: замеренная
            # рабочая документация и проёмы.
            self.assertLessEqual(
                set(MEASURED_DOCUMENTATION_CATEGORIES), set(absent))
            self.assertLessEqual(
                {"OST_SWallRectOpening", "OST_FloorOpening",
                 "OST_RoofOpening", "OST_ShaftOpening"}, set(absent))

    def test_a_stream_of_an_invented_table_size_is_still_refused(self) -> None:
        """ОПРОВЕРГАЮЩИЙ: послабление касается ПОКОЛЕНИЙ, а не любого хвоста.

        Длина, которой не было ни в одной сборке, — не поколение: неизвестно,
        что та сборка считала полнотой. Догадка «наверное, префикс» здесь и
        была бы той самой тихой переинтерпретацией.
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, ex.EXTRACT_CATEGORIES[:30])
            with self.assertRaises(ex.ExtractionProtocolError) as caught:
                ex.L0JSONLReader(path).validate()
            self.assertIn("30", str(caught.exception))

    def test_a_stream_written_under_the_current_table_is_accepted(self) -> None:
        """Опровергающая половина: отказ выше — про СОСТАВ, а не про всё подряд."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, ex.EXTRACT_CATEGORIES)
            ex.L0JSONLReader(path).validate()  # не бросает


if __name__ == "__main__":
    unittest.main()
