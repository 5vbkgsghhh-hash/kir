"""Почему у экземпляра НЕТ точки вставки — и почему трансформ ею не станет.

ЗАМЕР 2026-07-29 (четыре документа, 55 сохранённых разборов,
``coverage_matrix_2026-07-29.json``). Причина «FamilyInstance has no captured
LocationPoint and rotation» стояла на 7 083 элементах, и версия «это семейства
на грани / на рабочей плоскости, их положение лежит в GetTransform()» НЕ
подтвердилась. Поимённый разбор всех четырёх документов (лифт прогнан
живьём по замороженным L0):

    446 + 600 + 5880 + 157 = 7083 — и ВСЕ ДО ОДНОГО OST_CurtainWallPanels.

Ни одного face-hosted, ни одного work-plane-based. Больше того: в K2 все
5 060 экземпляров ``WorkPlaneBased`` точку ИМЕЮТ — то есть класс, который
версия называла дырой, на деле читается полностью.

Отсюда два обязательства, которые этот файл и охраняет:

1. У витражной панели точки вставки нет ПО ПОСТРОЕНИЮ: её положение
   порождает сетка разрезки носителя, а ставится она не
   ``NewFamilyInstance``, а назначением типа ячейке. Подставить ей
   свободную точку из ``GetTransform()`` значило бы выдать тихую потерю
   привязки за успех (§18.1).
2. Отсутствие точки обязано НАЗЫВАТЬ СЕБЯ. «Не прочиталось» и «его тут не
   бывает» — разные утверждения, и только второе что-то говорит о модели.

Поэтому трансформ читается ТРЕТЬИМ ИСТОЧНИКОМ, но кладётся в поля, которые
точкой вставки не притворяются, и инвариант записи запрещает строке нести
точку и трансформ одновременно — подменить одно другим structurally нельзя.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementPayloadError,
    FamilyPlacementRecord,
    FamilyPlacementType,
    LocationAbsence,
    build_family_placement_extract_cs,
    parse_family_placement_index,
)
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


def _raw(element_id: str = "10", **overrides) -> dict:
    """Сырая строка БЕЗ точки — ровно тот случай, о котором этот файл."""
    row = {
        "element_id": element_id,
        "symbol_id": "800",
        "type_name": "С остеклением",
        "family_name": "Системная панель",
        "placement_type": "OneLevelBased",
        "in_place": False,
        "mirrored": False,
        "hand_flipped": False,
        "facing_flipped": False,
        "super_component_id": None,
        "group_id": None,
        "host_id": "900",
        "host_class": "Wall",
        "hand_orientation": [1.0, 0.0, 0.0],
        "facing_orientation": [0.0, 1.0, 0.0],
        "status": "ok",
    }
    row.update(overrides)
    return row


class TheAbsenceOfAPointNamesItself(unittest.TestCase):
    """Пустая точка — типизированная причина, а не молчание."""

    def test_curtain_panel_absence_is_typed(self) -> None:
        record = FamilyPlacementRecord.from_raw(
            _raw(location_absence="curtain_grid_generated"))
        self.assertIs(
            record.location_absence, LocationAbsence.CURTAIN_GRID_GENERATED)
        self.assertFalse(record.placement_available)
        self.assertIsNone(record.point_mm)
        self.assertIsNone(record.rotation_deg)

    def test_every_absence_spelling_is_accepted(self) -> None:
        for spelling in ("curtain_grid_generated", "face_hosted",
                         "work_plane_based", "unreadable"):
            with self.subTest(spelling=spelling):
                record = FamilyPlacementRecord.from_raw(
                    _raw(location_absence=spelling))
                self.assertEqual(record.location_absence.value, spelling)

    def test_an_unknown_absence_is_refused(self) -> None:
        # Незнакомое слово — это НЕ «наверное, unreadable»: причина, которую
        # мы не умеем читать, обязана падать, а не тихо огрубляться.
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(
                _raw(location_absence="probably_fine"))

    def test_an_available_placement_explains_nothing(self) -> None:
        # Точка есть — объяснять нечего. Строка, несущая и то и другое,
        # означает, что эмиттер сам себе противоречит.
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(_raw(
                point_ft=[1.0, 2.0, 3.0], rotation_rad=0.0,
                location_absence="face_hosted"))

    def test_a_legacy_row_without_the_cause_still_loads(self) -> None:
        # Замороженный корпус снят схемой, которая причины не читала. Такая
        # строка обязана грузиться, а None здесь значит РОВНО «не смотрели»,
        # а не «причины нет» — различие, на котором лифт строит формулировку.
        record = FamilyPlacementRecord.from_raw(_raw())
        self.assertIsNone(record.location_absence)
        self.assertFalse(record.placement_available)


class ATransformIsNeverAnInsertionPoint(unittest.TestCase):
    """Главный страж файла: трансформ не может стать точкой."""

    def test_transform_is_read_but_kept_out_of_the_point(self) -> None:
        record = FamilyPlacementRecord.from_raw(_raw(
            location_absence="face_hosted",
            transform_origin_ft=[1.0, -2.0, 3.5],
            transform_basis_x=[1.0, 0.0, 0.0],
            transform_basis_y=[0.0, 1.0, 0.0],
            transform_basis_z=[0.0, 0.0, 1.0],
        ))
        self.assertIsNotNone(record.transform_origin_mm)
        # RAW-футы пересчитаны в мм тем же множителем, что и точка.
        self.assertAlmostEqual(record.transform_origin_mm[0], 304.8, places=6)
        # ...и точкой вставки при этом НЕ стали.
        self.assertIsNone(record.point_mm)
        self.assertIsNone(record.rotation_deg)
        self.assertFalse(record.placement_available)

    def test_a_row_cannot_carry_both_a_point_and_a_transform(self) -> None:
        # Структурный запрет подмены: пока эти два поля не могут стоять
        # рядом, ни одна ветка кода не сможет молча повысить трансформ до
        # точки — для этого ей пришлось бы сначала нарушить инвариант.
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord(
                element_id="10", symbol_id="800", type_name="t",
                family_name="f",
                placement_type=FamilyPlacementType.ONE_LEVEL_BASED,
                in_place=False, mirrored=False, hand_flipped=False,
                facing_flipped=False, super_component_id=None, group_id=None,
                host_id=None, host_class=None,
                hand_orientation=(1.0, 0.0, 0.0),
                facing_orientation=(0.0, 1.0, 0.0),
                placement_available=True,
                point_mm=(1.0, 2.0, 3.0), rotation_deg=0.0,
                transform_origin_mm=(1.0, 2.0, 3.0),
                transform_basis_x=(1.0, 0.0, 0.0),
                transform_basis_y=(0.0, 1.0, 0.0),
                transform_basis_z=(0.0, 0.0, 1.0),
            )

    def test_an_origin_without_a_basis_is_refused(self) -> None:
        # Половина трансформа — не трансформ: без базиса ориентацию нечем
        # восстановить, а «начало есть, поворота нет» выглядит как точка.
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(_raw(
                location_absence="face_hosted",
                transform_origin_ft=[1.0, -2.0, 3.5]))

    def test_a_degenerate_basis_is_refused(self) -> None:
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(_raw(
                location_absence="face_hosted",
                transform_origin_ft=[1.0, -2.0, 3.5],
                transform_basis_x=[1.0, 0.0, 0.0],
                transform_basis_y=[1.0, 0.0, 0.0],
                transform_basis_z=[0.0, 0.0, 1.0]))


class TheProbeReadsTheThirdSourceUnderItsOwnGuard(unittest.TestCase):
    """Каждое необязательное чтение — под СВОИМ стражем."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_family_placement_extract_cs(["1", "2"])

    def test_the_transform_member_is_the_one_that_exists(self) -> None:
        # ЗАМЕР по индексу ловушек (35 516 членов, шесть версий):
        # ``FamilyInstance.GetTransform`` НЕ СУЩЕСТВУЕТ. Член объявлен на
        # Autodesk.Revit.DB.Instance (все шесть версий, since 2012). Тест
        # держит именно вызов, а не имя из головы.
        self.assertIn("GetTransform()", self.body)

    def test_the_third_source_never_writes_the_point(self) -> None:
        # Ни одна строка не кладёт трансформ в point_ft/rotation_rad.
        for forbidden in ('__row["point_ft"] = __fpRawPoint(__xf',
                          '__row["point_ft"] = __fpRawPoint(__transform',
                          '__row["rotation_rad"] = __xf'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.body)
        self.assertIn('__row["transform_origin_ft"]', self.body)

    def test_each_optional_read_has_its_own_catch(self) -> None:
        # Общий try на весь элемент — это и есть форма бага (см. 12 369
        # помещений, cb9c3b65). Новые чтения обязаны падать поодиночке.
        for guarded in ("__fpTryHostFace", "__fpTryTransform",
                        "__fpTryLocation"):
            with self.subTest(guarded=guarded):
                self.assertIn(guarded, self.body)

    def test_the_curtain_panel_test_is_structural(self) -> None:
        # Витражная панель опознаётся КЛАССОМ Autodesk.Revit.DB.Panel, а не
        # именем семейства и не именем категории: имя врёт легко.
        self.assertIn("Autodesk.Revit.DB.Panel", self.body)
        self.assertNotIn("Системная панель", self.body)
        self.assertNotIn("System Panel", self.body)

    def test_the_probe_is_still_shippable(self) -> None:
        validate_code_safety(self.body)
        # Обёртка ОТСТУПАЕТ каждую строку тела, поэтому сверяется первая
        # строка, а не первые сорок символов: сорок символов теперь
        # перешагивают перевод строки (тело начинается с привязки источника
        # ``Document __src = ...``), и тест мерил бы отступ, а не доставку.
        self.assertIn(self.body.strip().splitlines()[0],
                      wrap_user_code(self.body))


_CORPUS = pathlib.Path(__file__).resolve().parents[4] / "backend" / "data" / "decompile"
#: По одному разбору на каждый из четырёх документов, давших 7 083.
_MEASURED = ("k2_ar_rd_v6", "sklnk_eom_r26_v7", "sklnk_eom_r26_v8",
             "sob62_fas_r23_v2")


class TheMeasuredGapIsNotFaceHosted(unittest.TestCase):
    """Опровержение версии, зафиксированное на данных.

    Если однажды этот тест упадёт, значит появился документ, где точки нет
    у НЕ витражного экземпляра, — и вот тогда третий источник впервые
    получит адресата. До тех пор он читается ради диагноза, а не ради точки.
    """

    def test_no_point_less_instance_is_work_plane_based(self) -> None:
        seen_any = False
        for name in _MEASURED:
            path = _CORPUS / name / "family_placement.index.json"
            if not path.exists():
                continue
            seen_any = True
            index = json.loads(path.read_text())["family_placement_index"]
            offenders = {
                key: row for key, row in index.items()
                if row.get("point_mm") is None
                and row.get("placement_type") == "WorkPlaneBased"
            }
            with self.subTest(snapshot=name):
                self.assertEqual(
                    offenders, {},
                    f"{name}: появился work-plane-based экземпляр без точки — "
                    "версию о face-hosted пора перемерить")
        if not seen_any:
            self.skipTest("замороженные разборы недоступны")

    def test_the_point_less_rows_are_curtain_panels(self) -> None:
        # Не имя семейства, а СТРУКТУРА: у витражной панели всегда есть
        # носитель (Wall/CurtainSystem), и точки нет ни у одной.
        for name in _MEASURED:
            path = _CORPUS / name / "family_placement.index.json"
            if not path.exists():
                continue
            index = json.loads(path.read_text())["family_placement_index"]
            hostless = [
                key for key, row in index.items()
                if row.get("point_mm") is None
                and row.get("placement_type") in (
                    "OneLevelBased", "OneLevelBasedHosted")
                and row.get("host_id") is None
            ]
            with self.subTest(snapshot=name):
                self.assertEqual(
                    hostless, [],
                    f"{name}: точечный экземпляр без точки И без носителя — "
                    "это уже не витражная панель")


if __name__ == "__main__":
    unittest.main()
