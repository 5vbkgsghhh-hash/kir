"""Synthetic Wave A fixtures grounded in the persisted spike's data shapes.

These are not LOT31 measurements.  The persisted artifact establishes that a
real document contains, among others, high-population walls, generic models,
furniture and doors alongside bbox-only/non-geometric records.  The fixtures
reuse those category/geometry shapes and the spec's 13-level ``Проект1``
known-answer size, while all coordinates and identities below are synthetic.
"""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from typing import Any

from kukai.ir.decompile.extract import (
    EXTRACT_CATEGORIES,
    SECTION_PARAM_NAMES,
    build_category_probe_cs,
)
from kukai.ir.decompile.schema import SECTION_RECEIPT_OUTCOMES


CATEGORY_RU = {
    "OST_Walls": "Стены",
    "OST_Floors": "Перекрытия",
    "OST_Roofs": "Крыши",
    "OST_Columns": "Колонны",
    "OST_StructuralColumns": "Несущие колонны",
    "OST_StructuralFraming": "Несущий каркас",
    "OST_StructuralFoundation": "Фундаменты несущих конструкций",
    "OST_Doors": "Двери",
    "OST_Windows": "Окна",
    "OST_Stairs": "Лестницы",
    "OST_StairsRailing": "Ограждения",
    "OST_Rooms": "Помещения",
    "OST_Grids": "Оси",
    "OST_Levels": "Уровни",
    "OST_PipeCurves": "Трубы",
    "OST_DuctCurves": "Воздуховоды",
    "OST_CableTray": "Кабельные лотки",
    "OST_Furniture": "Мебель",
    "OST_GenericModel": "Обобщенные модели",
    "DirectShape": "Обобщенные модели",
    "ImportInstance": "Импортированные категории",
    "OST_RasterImages": "Растровые изображения",
    # Разделы кроме АР — добавлены вместе с категориями экстрактора 27.07.
    "OST_ElectricalEquipment": "Электрооборудование",
    "OST_ElectricalFixtures": "Электроприборы",
    "OST_LightingFixtures": "Осветительные приборы",
    "OST_LightingDevices": "Осветительная арматура",
    "OST_CableTrayFitting": "Соединительные детали кабельных лотков",
    "OST_Conduit": "Короба",
    "OST_ConduitFitting": "Соединительные детали коробов",
    "OST_MechanicalEquipment": "Оборудование",
    "OST_DuctFitting": "Соединительные детали воздуховодов",
    "OST_DuctTerminal": "Воздухораспределители",
    "OST_FlexDuctCurves": "Гибкие воздуховоды",
    "OST_MEPSpaces": "Пространства",
    "OST_PlumbingFixtures": "Сантехнические приборы",
    "OST_PipeFitting": "Соединительные детали трубопроводов",
    "OST_PipeAccessory": "Арматура трубопроводов",
    "OST_FlexPipeCurves": "Гибкие трубы",
    "OST_Sprinklers": "Спринклеры",
    "OST_StructuralTruss": "Фермы",
    "OST_Ceilings": "Потолки",
    "OST_Ramps": "Пандусы",
    "OST_CurtainWallPanels": "Панели витража",
    "OST_CurtainWallMullions": "Импосты",
    "OST_Casework": "Встроенная мебель",
    "OST_SpecialityEquipment": "Специальное оборудование",
    "OST_Areas": "Зоны",
    # OST_CurtaSystem дописан в extract.py в конец кортежа (хвост волны
    # aaa44b45, 28.07) — третий род носителя витражной сетки.
    "OST_CurtaSystem": "Витражные системы",
    # Линии разрезки витража (волна 29.07): имя категории взято из ПЕРЕПИСИ
    # живой модели v14 — «Схемы разрезки витражей», 122 элемента, ровно
    # столько же, сколько линий в curtain-индексе того же прогона.
    "OST_CurtainGridsWall": "Схемы разрезки витражей",
    "OST_CurtainGridsRoof": "Схемы разрезки витражей кровли",
    "OST_CurtainGridsCurtaSystem": "Схемы разрезки витражных систем",
    # R4 красных: изоляция и футеровка — отдельные тела со своим габаритом.
    "OST_PipeInsulations": "Изоляция труб",
    "OST_DuctInsulations": "Изоляция воздуховодов",
    "OST_DuctLinings": "Внутренняя обшивка воздуховодов",
    # Рабочая документация — размеры, марки, примечания (волна 29.07).
    # Имена НЕ придуманы: это локализованные подписи из переписи слепка
    # k2_ar_rd_v6 (13A-RD-AR-K2_v33), то есть ровно то, чем их называет сам
    # Revit в этом документе. Фикстура обязана врать не больше, чем модель.
    "OST_Dimensions": "Размеры",
    "OST_TextNotes": "Текстовые примечания",
    "OST_SpotElevations": "Высотные отметки",
    "OST_SpotSlopes": "Уклоны в точках",
    "OST_GenericAnnotation": "Типовые аннотации",
    "OST_Lines": "Линии",
    "OST_RoomSeparationLines": "<Разделитель помещений>",
    "OST_DetailComponents": "Элементы узлов",
    "OST_RoomTags": "Марки помещений",
    "OST_DoorTags": "Марки дверей",
    "OST_WallTags": "Марки стен",
    "OST_FloorTags": "Марки перекрытий",
    "OST_AreaTags": "Марки зон",
    "OST_StairsRailingTags": "Марки ограждения",
    "OST_StructuralFramingTags": "Марки несущего каркаса",
    "OST_MechanicalEquipmentTags": "Марки оборудования",
    "OST_MaterialTags": "Марки материалов",
    "OST_MultiCategoryTags": "Марки по нескольким категориям",
    "OST_TelephoneDevices": "Телефонные устройства",
    # wave/opening (03.08.2026): проёмы отдельными элементами. Локализованные
    # имена — те, что Revit печатает в диспетчере (§18.5: локализованное имя
    # только справочная колонка, ключует всё равно BuiltInCategory).
    "OST_SWallRectOpening": "Проёмы в стенах",
    "OST_FloorOpening": "Проёмы в перекрытиях",
    "OST_RoofOpening": "Проёмы в крышах",
    "OST_ShaftOpening": "Шахты",
}

# Страховка от следующего добавления: таблица имён обязана покрывать таблицу
# категорий целиком. Без этой проверки новая категория падала бы KeyError'ом
# в глубине фикстуры, и причина читалась бы как поломка теста, а не как
# незаполненная строка (так и случилось 27.07 при добавлении разделов).
_MISSING_RU = [c for c in EXTRACT_CATEGORIES if c not in CATEGORY_RU]
if _MISSING_RU:
    raise RuntimeError(
        "CATEGORY_RU не покрывает категории экстрактора: "
        + ", ".join(_MISSING_RU))

CURVE_CATEGORIES = {
    "OST_Walls",
    "OST_StructuralFraming",
    "OST_StairsRailing",
    "OST_Grids",
    "OST_PipeCurves",
    "OST_DuctCurves",
    "OST_CableTray",
    # Волна ЭОМ 09.08: короб — такой же линейный MEPCurve, как лоток, и до
    # появления опа его форма в фикстуре роли не играла (атом он и есть
    # атом). Теперь играет: оставить короб на bbox_only значило бы заложить в
    # фикстуру геометрию, которой у него не бывает, и новый лифтер
    # проверялся бы на неправде — ровно довод строки про линии ниже.
    "OST_Conduit",
    # Волна 29.07: линии — это ЛИНИИ. Оставить их на bbox_only значило бы
    # заложить в фикстуру геометрию, которой у них не бывает, и любой
    # разбор кривой ниже по течению проверялся бы на неправде.
    "OST_Lines",
    "OST_RoomSeparationLines",
}
POINT_CATEGORIES = {
    "OST_Columns",
    "OST_StructuralColumns",
    "OST_StructuralFoundation",
    "OST_Doors",
    "OST_Windows",
    "OST_Furniture",
    "OST_GenericModel",
    # Волна 29.07: и элемент узла, и телефонное устройство — FamilyInstance,
    # то есть LocationPoint. Марки, размеры и примечания сюда НЕ входят
    # намеренно: у них Location нет вовсе, живьём они дадут bbox_only, и
    # фикстура обязана показывать именно это.
    "OST_DetailComponents",
    "OST_TelephoneDevices",
}


def project1_metadata() -> dict[str, Any]:
    levels = [
        {"id": str(100 + index), "name": f"Этаж {index + 1}",
         "elevation_mm": float(index * 3_000)}
        for index in range(13)
    ]
    return {
        "doc_name": "Проект1_synthetic",
        "revit_version": "2026",
        "units": "mm",
        "levels": levels,
        "grids": [
            {"id": "7001", "name": "1",
             "p0_mm": [0.0, -1_000.0, 0.0],
             "p1_mm": [0.0, 12_000.0, 0.0]},
            {"id": "7002", "name": "А",
             "p0_mm": [-1_000.0, 0.0, 0.0],
             "p1_mm": [18_000.0, 0.0, 0.0]},
        ],
        "rooms": [{
            "id": "8001",
            "name": "Комната 101",
            "level_id": "100",
            "level_name": "Этаж 1",
            "area_m2": 24.0,
            "boundary_mm": [
                [0.0, 0.0], [6_000.0, 0.0],
                [6_000.0, 4_000.0], [0.0, 4_000.0],
            ],
            "boundary_loops_mm": [[
                [0.0, 0.0], [6_000.0, 0.0],
                [6_000.0, 4_000.0], [0.0, 4_000.0],
            ]],
            "bounding_element_ids": ["9001", "9002", "9003", "9004"],
        }],
        "project_info": {
            "name": "Проект1",
            "address": "Синтетический адрес",
            "building_type_hint": None,
        },
        "links": [{
            "element_id": "99001",
            "name": "КР_synthetic.rvt",
            "loaded": True,
            "element_count": 1_200,
            "bbox_min_mm": [-5_000.0, -5_000.0, -1_000.0],
            "bbox_max_mm": [25_000.0, 20_000.0, 40_000.0],
            "discipline": "structural",
        }],
    }


def make_element(
    category: str,
    element_id: int,
    *,
    ordinal: int = 0,
) -> dict[str, Any]:
    level_index = ordinal % 13
    level_id = str(100 + level_index)
    level_name = f"Этаж {level_index + 1}"
    x = float((ordinal % 10) * 1_200)
    y = float(((ordinal // 10) % 10) * 1_000)
    z = float(level_index * 3_000)
    bbox_min = [x, y, z]
    bbox_max = [x + 900.0, y + 600.0, z + 2_800.0]
    row: dict[str, Any] = {
        "element_id": str(element_id),
        "category": category,
        "category_ru": CATEGORY_RU[category],
        "type_id": str(50_000 + EXTRACT_CATEGORIES.index(category)),
        "type_name": f"{CATEGORY_RU[category]} — synthetic type",
        "level_id": level_id,
        "level_name": level_name,
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": bbox_min,
        "bbox_max_mm": bbox_max,
        "host_id": None,
        "params": {},
        "design_option": (
            {"id": "61001", "name": "Основной вариант"}
            if ordinal % 7 == 0 else None),
        "phase_created": {"id": "62001", "name": "Новое строительство"},
        "workset": {"id": "1", "name": "Рабочий набор 1"},
    }
    if category in CURVE_CATEGORIES:
        row.update({
            "geom_kind": "curve",
            "p0_mm": [x, y, z],
            "p1_mm": [x + 6_000.0, y, z],
        })
    elif category in POINT_CATEGORIES:
        row.update({
            "geom_kind": "point",
            "p0_mm": [x + 450.0, y + 300.0, z],
            "rotation_deg": float((ordinal * 15) % 360),
        })
    if category == "OST_Walls":
        row["params"] = {"WALL_USER_HEIGHT_PARAM": 2_800.0}
    elif category == "OST_PipeCurves":
        row["params"] = {"RBS_PIPE_DIAMETER_PARAM": 100.0}
    elif category == "OST_DuctCurves":
        row["params"] = {
            "RBS_CURVE_WIDTH_PARAM": 500.0,
            "RBS_CURVE_HEIGHT_PARAM": 300.0,
        }
    elif category in ("OST_Doors", "OST_Windows"):
        row["host_id"] = "9001"
        row["params"] = {
            "FAMILY_WIDTH_PARAM": 900.0,
            "FAMILY_HEIGHT_PARAM": 2_100.0,
        }
    elif category == "OST_Stairs":
        row["params"] = {
            "STAIRS_BASE_LEVEL_PARAM": level_id,
            "STAIRS_TOP_LEVEL_PARAM": str(100 + min(level_index + 1, 12)),
        }
    return row


def project1_elements(total: int = 350) -> dict[str, list[dict[str, Any]]]:
    """``total`` synthetic elements spread over EVERY extraction family.

    Число семейств НЕ зашито: таблица категорий растёт (27.07: 20 -> 45,
    когда в неё добавили ЭОМ/ОВ/ВК/КР), и зашитое число превратило бы
    законный рост в падение фикстуры.
    """

    by_category: dict[str, list[dict[str, Any]]] = {
        category: [] for category in EXTRACT_CATEGORIES}
    for ordinal in range(total):
        category = EXTRACT_CATEGORIES[ordinal % len(EXTRACT_CATEGORIES)]
        by_category[category].append(
            make_element(category, 10_000 + ordinal, ordinal=ordinal))
    return by_category


class SyntheticBridgeCrash(BaseException):
    """Models process/transport death, not a retryable bridge exception."""


class FakeExtractBridge:
    """Interpreter for the fixed generated snippets used by unit tests."""

    _CATEGORY_RE = re.compile(
        r'string __Category = ("(?:[^"\\\\]|\\\\.)*");')
    _SCOPE_RE = re.compile(
        r'string __Scope = ("(?:[^"\\\\]|\\\\.)*");')
    _AFTER_RE = re.compile(r"long __After = (-?\d+)L;")
    _ROOM_AFTER_RE = re.compile(r"long __RoomAfter = (-?\d+)L;")

    def __init__(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        elements: dict[str, list[dict[str, Any]]] | None = None,
        timeout_probe_for: str | None = None,
        crash_batch_for: str | None = None,
        crash_after_pages: int = 0,
        outage_for: str | None = None,
        outage_after_pages: int = 0,
        outage_calls: int = 0,
        link_title: str | None = None,
    ) -> None:
        # Чей документ ЖДЁТ увидеть подделка. Проба узнаётся по точному
        # тексту, а текст зависит от источника: подделка, не знающая про
        # связь, не узнала бы пробу связи и объявила бы окно мёртвым — то
        # есть проводка источника осталась бы непроверяемой ровно там, где
        # она и сломалась живьём.
        self.link_title = link_title
        self.metadata_payload = metadata or project1_metadata()
        self.elements = elements or project1_elements()
        self.timeout_probe_for = timeout_probe_for
        self.crash_batch_for = crash_batch_for
        self.crash_after_pages = crash_after_pages
        self.crashed = False
        # ОБРЫВ ОКНА — не смерть процесса, а РЕТРАИБЕЛЬНЫЙ транспорт: сеть
        # оператора рвётся, мост умирает 1006, окно возвращается с новым
        # ws_id через секунды-минуты. Ровно ту ошибку и поднимает
        # admin_kir.bridge_callback, когда окна ещё нет в списке.
        self.outage_for = outage_for
        self.outage_after_pages = outage_after_pages
        self.outage_calls = outage_calls
        self.outage_raised = 0
        self.calls: list[tuple[str, int]] = []
        self.probe_attempts: defaultdict[str, int] = defaultdict(int)
        self.page_attempts: defaultdict[str, int] = defaultdict(int)
        self.max_page_size = 0
        self.max_room_page_size = 0
        self.link_recursion_attempted = False

    async def __call__(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        self.calls.append((code, timeout_ms))
        room_after_match = self._ROOM_AFTER_RE.search(code)
        if room_after_match:
            # The only linked-document collector is the requested count; no
            # category or geometry body is composed against the link document.
            if "get_Geometry" in code or "__PutGeometry" in code:
                self.link_recursion_attempted = True
            after = int(room_after_match.group(1))
            payload = copy.deepcopy(self.metadata_payload)
            rooms = [
                room for room in payload.get("rooms", [])
                if int(room["id"]) > after
            ]
            rooms.sort(key=lambda room: int(room["id"]))
            page = rooms[:2_000]
            has_more = len(rooms) > 2_000
            payload["rooms"] = page
            payload["rooms_has_more"] = has_more
            payload["rooms_next_cursor"] = (
                page[-1]["id"] if has_more else None)
            self.max_room_page_size = max(
                self.max_room_page_size, len(page))
            return {"ok": True, "result": payload}

        for category in EXTRACT_CATEGORIES:
            # Pipeline may wrap the body in its document-revision envelope;
            # the original generated probe remains byte-for-byte inside it.
            if build_category_probe_cs(
                    category, link_title=self.link_title) in code:
                self.probe_attempts[category] += 1
                if category == self.timeout_probe_for:
                    raise TimeoutError(f"synthetic timeout for {category}")
                counts: defaultdict[str, int] = defaultdict(int)
                rows = self.elements.get(category, [])
                for row in rows:
                    counts[row.get("level_id") or "__none__"] += 1
                result = {
                    "count": len(rows),
                    "levels": [
                        {"key": key, "count": count}
                        for key, count in sorted(counts.items())
                    ],
                }
                return {"ok": True, "result": result}

        category_match = self._CATEGORY_RE.search(code)
        scope_match = self._SCOPE_RE.search(code)
        after_match = self._AFTER_RE.search(code)
        if not category_match or not scope_match or not after_match:
            raise AssertionError("unknown generated extraction body")
        category = json.loads(category_match.group(1))
        scope = json.loads(scope_match.group(1))
        after = int(after_match.group(1))
        self.page_attempts[category] += 1
        if (category == self.crash_batch_for and not self.crashed
                and self.page_attempts[category] > self.crash_after_pages):
            self.crashed = True
            raise SyntheticBridgeCrash(f"synthetic crash for {category}")
        if (category == self.outage_for
                and self.page_attempts[category] > self.outage_after_pages
                and self.outage_raised < self.outage_calls):
            self.outage_raised += 1
            raise RuntimeError(
                f"bridge window for {category!r} is not connected "
                f"(matches: 0)")
        rows = [
            row for row in self.elements.get(category, [])
            if int(row["element_id"]) > after
            and (scope == "__all__"
                 or (row.get("level_id") or "__none__") == scope)
        ]
        rows.sort(key=lambda row: int(row["element_id"]))
        page = copy.deepcopy(rows[:2_000])
        has_more = len(rows) > 2_000
        self.max_page_size = max(self.max_page_size, len(page))
        result = {
            "elements": page,
            "has_more": has_more,
            "next_cursor": page[-1]["element_id"] if has_more else None,
            # Квитанции сечений (ревью кодекса №12). Подделка обязана
            # моделировать КОНТРАКТ, а не удобство: каждый элемент страницы
            # опрошен каждым параметром ровно один раз, поэтому сумма шести
            # исходов равна размеру страницы. Исход выбран по факту наличия
            # числа в `params` — так подделка не может «случайно» сойтись.
            "section_receipts": self._section_receipts(page),
        }
        return {"ok": True, "result": result}

    @staticmethod
    def _section_receipts(page: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for name in SECTION_PARAM_NAMES:
            hits = sum(1 for row in page if name in (row.get("params") or {}))
            counters = {outcome: 0 for outcome in SECTION_RECEIPT_OUTCOMES}
            counters["instance_hit"] = hits
            counters["not_applicable"] = len(page) - hits
            rows.append({"parameter": name, **counters})
        return rows if page else []
