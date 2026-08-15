"""Содержательное покрытие: знаменатель, который не врёт в обе стороны.

Покрытие документа (§18.1) считает опы от ВСЕХ элементов файла: на РД-башне
29 848 из 310 558 = 9.61%. Число честное, но отвечает на вопрос, который никто
не задавал. В тех 310 тысячах сидит 61 520 границ зон, 38 093 эскизных линии и
19 547 авторазмеров — следы построения, которые Revit заводит САМ и которые
никто никогда не «создаёт». Считать их в знаменателе — то же самое, что мерить
компилятор по числу временных переменных, порождённых его собственным выводом.

Ошибиться тут можно в обе стороны, и обе дорогие:

* оставить знаменателем весь документ — и мы вчетверо занижаем себя, а хуже
  того, получаем стимул «поднимать покрытие», начав читать мусор: прочитал
  61 520 границ зон, выдал их за опы — число выросло, компилятор не сдвинулся;
* выкинуть из знаменателя всё неудобное — и получить любой процент, какой
  захочется. Ровно так рождается «покрытие 98%», которое потом приходится
  снимать публично.

Поэтому классификация здесь — ЗАКРЫТАЯ ТАБЛИЦА В КОДЕ, строка на категорию, и
всё, чего в ней нет, попадает в ``UNKNOWN`` ГРОМКО (в отчёте отдельным списком
с числами), а не растворяется в удобном классе. Не согласен с конкретной
строкой — правь её и пересчитывай; спорить с классификацией можно, а не
заметить её нельзя.

    python tools/content_coverage.py backend/data/decompile/k2_ar_rd_v6
    python tools/content_coverage.py <dir> --json out.json

Три числа на выходе, и каждое отвечает на СВОЙ вопрос:

* ``model_pct``    — из того, что является ЗДАНИЕМ, сколько мы выражаем;
* ``content_pct``  — из здания и его оформления (то и другое авторское);
* ``document_pct`` — из всего файла (существующая §18.1-метрика, для сверки).

И отдельно — разложение разрыва на две ПРИНЦИПИАЛЬНО разные причины: чего мы
не ЧИТАЕМ (категории вне таблицы) и что читаем, но не УМЕЕМ выразить. Первое
чинится строкой в таблице категорий, второе — лифтером и опом. Смешивать их в
одном проценте значит не знать, что делать завтра.
"""
from __future__ import annotations

import argparse
import collections
import enum
import json
import pathlib
import sys
from typing import Any

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS.parent) not in sys.path:
    sys.path.insert(0, str(_TOOLS.parent))


class ContentClass(str, enum.Enum):
    """Закрытый словарь классов категории."""

    # Здание. То, что KIR обязан уметь строить: несущее, ограждающее,
    # инженерия, оборудование, пространства, датумы.
    MODEL = "model"
    # Оформление. Авторская документация поверх модели: размеры, марки,
    # тексты, узлы, облака изменений. Выразимо в принципе, опы частично есть.
    DOCUMENTATION = "documentation"
    # Организация документа: виды, листы, спецификации, видовые экраны.
    # Авторское, но это не здание и не его чертёж — это оглавление.
    VIEW = "view"
    # Производное. Порождается другим элементом и отдельно не существует:
    # эскизы, схемы разрезки, марши и площадки лестницы, аналитическая модель.
    # Знаменателем быть не может по построению — как generator_child в атомах.
    DERIVED = "derived"
    # Служебное: настройки, синглтоны проекта, определения нагрузок, материалы
    # как элементы, базовые точки. Не строится и не чертится.
    SYSTEM = "system"
    # Не классифицировано. Печатается отдельно и полным списком.
    UNKNOWN = "unknown"


_M = ContentClass.MODEL
_D = ContentClass.DOCUMENTATION
_V = ContentClass.VIEW
_G = ContentClass.DERIVED
_S = ContentClass.SYSTEM

# Строка на категорию. Порядок — по классам, внутри класса по алфавиту, чтобы
# правка была видна в дифе как одна строка, а не как перетасовка таблицы.
#: Сколько строк «не классифицировано» печатать. Не порог качества, а предел
#: читаемости: остальное обязано быть НАЗВАНО числом, а не пропасть молча.
_UNKNOWN_ROWS_SHOWN = 20

CATEGORY_CLASS: dict[str, ContentClass] = {
    # --- ЗДАНИЕ -----------------------------------------------------------
    "OST_Areas": _M,
    "OST_Casework": _M,
    "OST_Ceilings": _M,
    "OST_Columns": _M,
    "OST_Conduit": _M,
    "OST_ConduitFitting": _M,
    "OST_CableTray": _M,
    "OST_CableTrayFitting": _M,
    "OST_CurtaSystem": _M,
    "OST_CurtainWallMullions": _M,
    "OST_CurtainWallPanels": _M,
    "OST_Doors": _M,
    "OST_DuctCurves": _M,
    "OST_DuctFitting": _M,
    "OST_DuctInsulations": _M,
    "OST_DuctLinings": _M,
    "OST_DuctTerminal": _M,
    "OST_ElectricalEquipment": _M,
    "OST_ElectricalFixtures": _M,
    "OST_FlexDuctCurves": _M,
    "OST_FlexPipeCurves": _M,
    "OST_FloorOpening": _M,
    "OST_Floors": _M,
    "OST_Furniture": _M,
    "OST_GenericModel": _M,
    "OST_Grids": _M,
    "OST_IOSModelGroups": _M,
    "OST_LightingDevices": _M,
    "OST_LightingFixtures": _M,
    "OST_Levels": _M,
    "OST_Mass": _M,
    "OST_MEPSpaces": _M,
    "OST_MechanicalEquipment": _M,
    "OST_PipeAccessory": _M,
    "OST_PipeCurves": _M,
    # Логическая система — авторский объект, а не графика: у неё есть своя
    # операция (create_pipe_system / route_duct_system), значит она модельная.
    "OST_PipingSystem": _M,
    "OST_DuctSystem": _M,
    "OST_PlumbingEquipment": _M,
    "OST_PipeFitting": _M,
    "OST_PipeInsulations": _M,
    "OST_PlumbingFixtures": _M,
    "OST_Ramps": _M,
    "OST_Roofs": _M,
    "OST_Rooms": _M,
    # Разделитель помещений рисуется руками и без него помещение не
    # воспроизвести — это авторская геометрия, а не след построения.
    "OST_RoomSeparationLines": _M,
    "OST_SpecialityEquipment": _M,
    "OST_Sprinklers": _M,
    "OST_Stairs": _M,
    "OST_StairsRailing": _M,
    "OST_StructConnections": _M,
    "OST_StructuralColumns": _M,
    "OST_StructuralFoundation": _M,
    "OST_StructuralFraming": _M,
    "OST_StructuralTruss": _M,
    "OST_TelephoneDevices": _M,
    "OST_Topography": _M,
    "OST_Walls": _M,
    "OST_Windows": _M,
    # --- ОФОРМЛЕНИЕ -------------------------------------------------------
    "OST_AreaTags": _D,
    "OST_CeilingTags": _D,
    "OST_DetailComponents": _D,
    "OST_Dimensions": _D,
    "OST_DoorTags": _D,
    "OST_EditCutProfile": _D,
    "OST_FloorTags": _D,
    "OST_GenericAnnotation": _D,
    "OST_IOSDetailGroups": _D,
    "OST_LegendComponents": _D,
    # Линии детализации и модельные линии в одной категории. Отнесено к
    # оформлению по большинству в реальных РД; если модель линиями МОДЕЛИРУЕТ,
    # строку надо править — потому она и строка.
    "OST_Lines": _D,
    "OST_MaterialTags": _D,
    "OST_MEPSpaceTags": _D,
    "OST_PipeTags": _D,
    "OST_PlumbingEquipmentTags": _D,
    "OST_MechanicalEquipmentTags": _D,
    "OST_MultiCategoryTags": _D,
    "OST_RasterImages": _D,
    "OST_RevisionClouds": _D,
    "OST_RevisionCloudTags": _D,
    "OST_RoomTags": _D,
    "OST_SpotElevations": _D,
    "OST_SpotSlopes": _D,
    "OST_StairsRailingTags": _D,
    "OST_StructuralFramingTags": _D,
    "OST_TextNotes": _D,
    "OST_TitleBlocks": _D,
    "OST_WallTags": _D,
    "OST_WindowTags": _D,
    # --- ОРГАНИЗАЦИЯ ДОКУМЕНТА -------------------------------------------
    "OST_BranchPanelScheduleTemplates": _V,
    "OST_Cameras": _V,
    "OST_ColorFillSchema": _V,
    "OST_DataPanelScheduleTemplates": _V,
    "OST_Elev": _V,
    "OST_GuideGrid": _V,
    "OST_HVAC_Load_Schedules": _V,
    "OST_PlanRegion": _V,
    "OST_Revisions": _V,
    "OST_RevisionNumberingSequences": _V,
    "OST_Schedules": _V,
    "OST_SectionBox": _V,
    "OST_Sheets": _V,
    "OST_SwitchboardScheduleTemplates": _V,
    "OST_Viewports": _V,
    "OST_Views": _V,
    "OST_VolumeOfInterest": _V,
    # --- ПРОИЗВОДНОЕ ------------------------------------------------------
    "OST_AnalyticalMember": _G,
    "OST_AnalyticalNodes": _G,
    "OST_AreaSchemeLines": _G,
    "OST_Constraints": _G,
    # ОСЕВЫЕ ЛИНИИ — чистые зеркала: на образце Snowdon их РОВНО столько же,
    # сколько носителей (3051 труба / 3051 осевая, 2651 фитинг / 2651 осевая).
    # Такая категория не может быть ничем, кроме производного, по построению:
    # её рисует Revit из носителя, и отдельной операции у неё нет.
    "OST_PipeCurvesCenterLine": _G,
    "OST_PipeFittingCenterLine": _G,
    "OST_DuctCurvesCenterLine": _G,
    "OST_DuctFittingCenterLine": _G,
    "OST_FlexPipeCurvesCenterLine": _G,
    "OST_FlexDuctCurvesCenterLine": _G,
    "OST_ConduitCenterLine": _G,
    "OST_CableTrayCenterLine": _G,
    "OST_CurtainGrids": _G,
    "OST_CurtainGridsCurtaSystem": _G,
    "OST_CurtainGridsRoof": _G,
    "OST_CurtainGridsWall": _G,
    "OST_IOSSketchGrid": _G,
    "OST_PreviewLegendComponents": _G,
    "OST_RailingRailPathExtensionLines": _G,
    "OST_RailingTopRail": _G,
    "OST_ScheduleGraphics": _G,
    "OST_SketchLines": _G,
    "OST_StairsLandings": _G,
    "OST_StairsPaths": _G,
    "OST_StairsRailingBaluster": _G,
    "OST_StairsRuns": _G,
    "OST_StairsSketchBoundaryLines": _G,
    "OST_StairsSketchPathLines": _G,
    "OST_StairsSketchRiserLines": _G,
    "OST_TopographyContours": _G,
    "OST_Viewers": _G,
    "OST_WeakDims": _G,
    # --- СЛУЖЕБНОЕ --------------------------------------------------------
    "OST_AreaSchemes": _S,
    "OST_CLines": _S,
    "OST_CoordinateSystem": _S,
    "OST_ElectricalDemandFactorDefinitions": _S,
    "OST_ElectricalLoadClassifications": _S,
    "OST_ElectricalLoadZoneType": _S,
    "OST_HVAC_Load_Building_Types": _S,
    "OST_HVAC_Load_Space_Types": _S,
    "OST_HVAC_Zones": _S,
    "OST_IOSArrays": _S,
    "OST_IOS_GeoLocations": _S,
    "OST_LoadCases": _S,
    "OST_Materials": _S,
    "OST_ParamElemElectricalLoadClassification": _S,
    "OST_Phases": _S,
    "OST_PipeSegments": _S,
    "OST_ProjectBasePoint": _S,
    "OST_ProjectInformation": _S,
    "OST_PropertySet": _S,
    "OST_RvtLinks": _S,
    "OST_SharedBasePoint": _S,
    "OST_SunStudy": _S,
    # Элемент без категории. 53 885 штук на РД-башне — виды изнутри, эскизные
    # плоскости, служебное. Класс назван прямо, а не подставлен догадкой: это
    # верхняя граница неопределённости, и она печатается отдельной строкой.
    "no_category": ContentClass.UNKNOWN,

    # --- ДОБАВЛЕНО 13.08.2026 -------------------------------------------
    # 68 имён, встреченных в корпусе и не имевших строки. Классифицированы
    # ГЛАЗАМИ, а не по суффиксу, и суффикс дал бы другой ответ минимум
    # трижды: `OST_AnalyticSurfaces` (3041) выглядит поверхностями здания, а
    # есть АНАЛИТИЧЕСКАЯ модель, порождаемая физической; `OST_RailingSupport`
    # (2608) — не самостоятельное здание, а часть ограждения;
    # `OST_MEPLoadAreaSeparationLines` просится в оформление по `Lines`, но
    # прецедент уже стоит в этой же таблице — `OST_RoomSeparationLines`
    # отнесён к ЗДАНИЮ, потому что рисуется руками и без него пространство не
    # воспроизвести. Спорные строки правятся поштучно; на то они и строки.
    # ЗДАНИЕ
    "OST_Cornices": _M,
    "OST_DataDevices": _M,
    "OST_ElectricalCircuit": _M,
    "OST_ElectricalLoadZoneInstance": _M,
    "OST_Entourage": _M,
    "OST_FoodServiceEquipment": _M,
    "OST_Hardscape": _M,
    "OST_MEPLoadAreaSeparationLines": _M,
    "OST_MEPLoadAreas": _M,
    "OST_MEPSpaceSeparationLines": _M,
    "OST_MultistoryStairs": _M,
    "OST_Parking": _M,
    "OST_Planting": _M,
    "OST_RoofOpening": _M,
    "OST_SWallRectOpening": _M,
    "OST_ShaftOpening": _M,
    "OST_Site": _M,
    "OST_SiteProperty": _M,
    "OST_SitePropertyLineSegment": _M,
    "OST_VerticalCirculation": _M,
    "OST_Wire": _M,
    # ОФОРМЛЕНИЕ
    "OST_ConduitTags": _D,
    "OST_ELECTRICAL_AreaBasedLoads_Tags": _D,
    "OST_ElectricalEquipmentTags": _D,
    "OST_ElectricalFixtureTags": _D,
    "OST_GenericModelTags": _D,
    "OST_InsulationLines": _D,
    "OST_KeynoteTags": _D,
    "OST_LightingFixtureTags": _D,
    "OST_ParkingTags": _D,
    "OST_PathOfTravelLines": _D,
    "OST_PathOfTravelTags": _D,
    "OST_PlantingTags": _D,
    "OST_RoofTags": _D,
    "OST_SitePropertyLineSegmentTags": _D,
    "OST_SpecialityEquipmentTags": _D,
    "OST_SpotElevSymbols": _D,
    "OST_WireTags": _D,
    # ОРГАНИЗАЦИЯ ДОКУМЕНТА
    "OST_CalloutHeads": _V,
    "OST_ColorFillLegends": _V,
    "OST_ElevationMarks": _V,
    "OST_GridHeads": _V,
    "OST_LevelHeads": _V,
    "OST_PanelScheduleGraphics": _V,
    "OST_PanelSchedules": _V,
    "OST_ReferenceViewerSymbol": _V,
    "OST_SectionHeads": _V,
    "OST_ViewportLabel": _V,
    # ПРОИЗВОДНОЕ
    "OST_AdaptivePoints": _G,
    "OST_AnalyticSpaces": _G,
    "OST_AnalyticSurfaces": _G,
    "OST_CableTrayRun": _G,
    "OST_ConduitFittingCenterLine": _G,
    "OST_ConduitRun": _G,
    "OST_EdgeSlab": _G,
    "OST_ElectricalAnalyticalTransformer": _G,
    "OST_MEPAnalyticalBus": _G,
    "OST_Parts": _G,
    "OST_RailingHandRail": _G,
    "OST_RailingSupport": _G,
    "OST_StairsSketchLandingCenterLines": _G,
    "OST_StairsSketchRunLines": _G,
    "OST_StairsStringerCarriage": _G,
    # СЛУЖЕБНОЕ
    "OST_DesignOptionSets": _S,
    "OST_DesignOptions": _S,
    "OST_Divisions": _S,
    "OST_ElectricalCircuitNaming": _S,
    "OST_ElectricalPowerSource": _S,
}

# Ключи таблицы ИЗВЛЕЧЕНИЯ, которых нет в переписи как отдельных категорий:
# перепись ключует BuiltInCategory, а эти два коллектора — по классу элемента.
# Их элементы уже посчитаны переписью внутри своих категорий, поэтому в
# знаменатель они не добавляются, но и потеряться не должны.
COLLECTOR_ALIASES = {"DirectShape", "ImportInstance"}


def classify(key: str) -> ContentClass:
    return CATEGORY_CLASS.get(key, ContentClass.UNKNOWN)


def _header(directory: pathlib.Path) -> dict[str, Any]:
    with (directory / "L0.jsonl").open(encoding="utf-8") as handle:
        return json.loads(handle.readline())


def _census(header: dict[str, Any], directory: pathlib.Path) -> list[dict[str, Any]]:
    census = header.get("document", {}).get("census")
    if not census:
        raise SystemExit(
            f"{directory.name}: переписи нет — слепок снят до §18.1, "
            "содержательное покрытие для него не определено")
    return census


def _extracted_by_collector(directory: pathlib.Path) -> dict[str, int]:
    """Сколько элементов реально прочитано, по коллекторам."""
    counts: collections.Counter[str] = collections.Counter()
    with (directory / "L0.jsonl").open(encoding="utf-8") as handle:
        handle.readline()
        for line in handle:
            # Дешёвая проверка до разбора: строк тут десятки тысяч.
            if '"record": "element"' not in line and '"record":"element"' not in line:
                continue
            record = json.loads(line)
            if record.get("record") != "element":
                continue
            counts[record.get("collector") or "no_category"] += 1
    return dict(counts)


def _side_index_names() -> tuple[tuple[str, str], ...]:
    """Список боковых индексов — У ТОГО, КТО ИХ ГРУЗИТ, а не свой второй.

    `relift_offline._SIDE_INDEX_FILES` — единственное место, где этот список
    ведут, и лифт входит именно через него. Свой список здесь разошёлся бы с
    ним при первой же новой стадии, и разошёлся бы МОЛЧА: недостающее имя
    выглядело бы как «у прогона нет этого индекса».
    """
    from relift_offline import _SIDE_INDEX_FILES
    return tuple(_SIDE_INDEX_FILES)


#: Читается лениво, чтобы `content_coverage` оставался импортируемым без
#: инструментов рядом; ошибка импорта — не пустой список, а исключение.
_SIDE_INDEX_NAMES = _side_index_names()


def _conditions(directory: pathlib.Path, census: list[dict[str, Any]],
                extracted: dict[str, int]) -> dict[str, Any]:
    """Условия, при которых процент этого прогона вообще сопоставим с другим.

    Спрашиваем АВТОРИТЕТЫ, а не заводим поле: таблица извлечения знает, что мы
    умеем читать; перепись §18.1 знает, что в документе есть; `L0` знает, что
    прочитано на самом деле. Пересечение первых двух минус третье и есть
    «умели прочесть, документ это имел, не прочли».

    `category_outside_table` сюда НЕ попадает намеренно: это известный и
    названный пробел, ради описания которого метрика и заведена. Опасен
    другой случай — категория В ТАБЛИЦЕ, и он до 12.08 не был виден нигде.
    """
    try:
        from kukai.ir.decompile.extract import _CATEGORY_SPECS
        table = {spec.name for spec in _CATEGORY_SPECS}
    except Exception:                                          # noqa: BLE001
        # Таблицы нет — условия НЕИЗВЕСТНЫ, и это другой факт, чем «условий
        # нет». Пустой словарь тут читался бы как «всё прочитано».
        return {"table_available": False}
    unread = {row["key"]: int(row.get("count", 0)) for row in census
              if row.get("key") in table and int(row.get("count", 0)) > 0
              and extracted.get(row.get("key"), 0) == 0}
    status_path = directory / "status.json"
    scanned = None
    if status_path.is_file():
        try:
            scanned = int(json.loads(status_path.read_text(encoding="utf-8"))
                          .get("categories_scanned"))
        except Exception:                                      # noqa: BLE001
            scanned = None
    return {
        "table_available": True,
        "categories_scanned": scanned,
        "in_table_unread": dict(sorted(unread.items())),
        "in_table_unread_elements": sum(unread.values()),
        # ═══ БОКОВЫЕ ИНДЕКСЫ — УСЛОВИЕ ТОГО ЖЕ РАНГА, ЧТО НЕПРОЧИТАННЫЕ
        # КАТЕГОРИИ, и до 12.08 `comparable()` их не смотрел.
        #
        # Они решают, что лифтер ВООБЩЕ МОЖЕТ поднять: без
        # `family_placement.index.json` каждый экземпляр семейства — атом, без
        # `dimension.index.json` размеры не поднимутся никогда. Прогон,
        # оборвавшийся на побочных стадиях, честно проходит проверку по
        # непрочитанным категориям (перепись у него полна!) и при этом
        # выражает МЕНЬШЕ — просто потому, что лифтеру нечем.
        #
        # ПОВОД НАЗВАН ЗАРАНЕЕ, А НЕ ПОСЛЕ УКУСА: `k2_ar_rd_v15`, с которого
        # сняты все наши числа покрытия, завершился с `stage="error"` и БЕЗ
        # `mep_system`, `tag`, `dimension`. Живой разбор идёт до конца, со
        # всеми стадиями. Сравнение живого с `v15` прошло бы старый
        # `comparable()` и показало разницу, которую прочли бы как выигрыш
        # компилятора, — а это разница ПОЛНОТЫ ПРОГОНОВ. Ровно 27 пунктов
        # фасада, второй раз, и в самом важном сравнении.
        "side_indexes": sorted(
            name for name, filename in _SIDE_INDEX_NAMES
            if (directory / filename).is_file()),
        # ЧЕГО СТОИТ ОТСУТСТВУЮЩИЙ ИНДЕКС — В ЭЛЕМЕНТАХ, А НЕ В ФАКТЕ
        # (13.08.2026). `comparable()` сравнивал НАЛИЧИЕ файла и отвергал
        # прогон за ненятую стадию, которой НЕЧЕГО было снимать: у
        # `snowdon_plumb_v4` нет `dimension`, а в `OST_Dimensions` ноль
        # элементов — «стадия не снята» и «стадии нечего было снимать» суть
        # ОДИН факт, и различать их значит отказывать по признаку, не
        # влияющему на предмет.
        #
        # `None` вместо нуля там, где стадии нет строки в `_STAGE_CATEGORIES`
        # (`geometry` — она пишет bundle, а не индекс): пустое множество
        # категорий даёт ноль, НЕОТЛИЧИМЫЙ от «нечего читать», и этот ноль
        # означал бы «сравнивать можно» на голом незнании.
        "side_index_pending": _pending_by_stage(directory, census),
    }


def _pending_by_stage(directory: pathlib.Path,
                      census: list[dict[str, Any]]) -> dict[str, int | None]:
    """{стадия без индекса: сколько элементов её категорий В ПЕРЕПИСИ}.

    `None` = у стадии нет строки в `_STAGE_CATEGORIES`, то есть чего она
    читает — неизвестно, и ноль тут был бы утверждением, а не замером.
    """
    from kukai.ir.decompile.pipeline import _STAGE_CATEGORIES

    counts = {row["key"]: row["count"] for row in census
              if isinstance(row.get("count"), int)}
    pending: dict[str, int | None] = {}
    for name, filename in _SIDE_INDEX_NAMES:
        if (directory / filename).is_file():
            continue
        cats = _STAGE_CATEGORIES.get(name)
        pending[name] = (None if not cats
                         else sum(counts.get(c, 0) for c in cats))
    return pending


def comparable(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, str]:
    """Сопоставимы ли два отчёта. ОТКАЗ НАЗЫВАЕТ ОБЕ ВЕЛИЧИНЫ.

    Разброс по зданиям — то, что говорит о компиляторе; но он говорит о нём
    ТОЛЬКО если прогоны прочитали одно и то же множество категорий. Иначе
    сравниваются полноты чтения под именем компилятора, и это ровно тот
    случай, что стоил 27 пунктов на двух ревизиях одного фасада.
    """
    a = (left.get("conditions") or {}).get("in_table_unread")
    b = (right.get("conditions") or {}).get("in_table_unread")
    if a is None or b is None:
        return False, ("условия одного из отчётов неизвестны (нет таблицы "
                       "извлечения) — сравнивать нечего с чем")
    if set(a) != set(b):
        only_left = sorted(set(a) - set(b))
        only_right = sorted(set(b) - set(a))
        return False, (
            "прогоны прочитали РАЗНЫЕ множества категорий, поэтому их "
            "проценты несопоставимы: "
            f"не прочитано только у первого {only_left or '—'}, "
            f"только у второго {only_right or '—'}. "
            "Одна такая категория стоила 27 пунктов на двух ревизиях одного "
            "здания (12.08.2026): её элементы позволяют лифтеру опознать "
            "порождённых детей, которых честная цифра ИСКЛЮЧАЕТ, и падает "
            "ЗНАМЕНАТЕЛЬ, а не растёт числитель")
    # ВТОРОЕ УСЛОВИЕ, ТОГО ЖЕ РАНГА. Перепись может быть полна у обоих, а
    # лифтеру у одного нечем поднимать: боковой индекс решает, ВОЗМОЖЕН ли
    # подъём вообще. Прогон, оборвавшийся на побочных стадиях, честно проходит
    # первую проверку и выражает меньше — не потому, что компилятор хуже.
    sa = (left.get("conditions") or {}).get("side_indexes")
    sb = (right.get("conditions") or {}).get("side_indexes")
    if sa is None or sb is None:
        return False, ("набор боковых индексов у одного из отчётов неизвестен "
                       "(снят прибором до 12.08) — сравнивать нечего с чем")
    # ОТСУТСТВИЕ ИНДЕКСА ЗНАЧИМО ТОЛЬКО ЕСЛИ БЫЛО ЧТО ЧИТАТЬ (13.08.2026).
    # Стадия без индекса, в чьих категориях перепись даёт НОЛЬ, эквивалентна
    # присутствующей-и-пустой — такой индекс у корпуса есть (`mep_system` с
    # нулём строк) и сравнение его проходит. Отвергать за неё значит отказывать
    # по признаку, не влияющему на предмет.
    #
    # ГРАНИЦА: `None` (стадии нет строки в `_STAGE_CATEGORIES`) НЕ считается
    # пустой. Незнание того, что стадия читает, — не доказательство, что читать
    # было нечего.
    pa = (left.get("conditions") or {}).get("side_index_pending") or {}
    pb = (right.get("conditions") or {}).get("side_index_pending") or {}
    effective_a = set(sa) | {k for k, v in pa.items() if v == 0}
    effective_b = set(sb) | {k for k, v in pb.items() if v == 0}
    if effective_a != effective_b:
        # Отказ обязан назвать ЦЕНУ, а не только имя: «нет dimension» не
        # говорит, велика ли потеря — 13 905 элементов или ноль.
        def _cost(names, pending):
            return ", ".join(
                f"{n} ({pending.get(n)} эл. в переписи)"
                if pending.get(n) is not None
                else f"{n} (сколько читает — НЕИЗВЕСТНО, строки в "
                     f"_STAGE_CATEGORIES нет)"
                for n in sorted(names)) or "—"

        return False, (
            "у прогонов РАЗНЫЙ набор боковых индексов, и у отсутствующих было "
            "ЧТО читать, поэтому лифтер мог поднять разное: "
            f"только у первого {_cost(effective_a - effective_b, pb)}, "
            f"только у второго {_cost(effective_b - effective_a, pa)}. "
            "Индекс решает ВОЗМОЖНОСТЬ подъёма: без `family_placement` каждый "
            "экземпляр семейства — атом, без `dimension` размеры не "
            "поднимутся никогда. Прогон с оборванными побочными стадиями "
            "выражает меньше НЕ потому, что компилятор хуже")
    return True, ""


def build(directory: pathlib.Path, ops: int | None = None,
          generator_children: int | None = None,
          ops_by_category: dict[str, int] | None = None) -> dict[str, Any]:
    header = _header(directory)
    census = _census(header, directory)
    extracted = _extracted_by_collector(directory)

    if ops is None and ops_by_category is None:
        from relift_offline import relift
        report = relift(directory)
        ops = int(report.get("op_total", 0))
        elements = int(report.get("elements", 0))
        ops_by_category = dict(report.get("ops_by_category") or {})
        if generator_children is None:
            generator_children = int(report.get("generator_children", 0))
    else:
        if ops_by_category is not None:
            ops = sum(ops_by_category.values()) if ops is None else ops
        elements = sum(extracted.values())
        generator_children = generator_children or 0

    # Числитель раскладывается по ТОМУ ЖЕ классу, что и знаменатель, и по той
    # же закрытой таблице — по КАТЕГОРИИ элемента-источника, а не по имени
    # опа. Список опов двигается каждую неделю, категория элемента — факт о
    # модели. Пока разложения не было, `create_text`/`create_tag` попадали в
    # числитель «здания», знаменатель которого оформление исключает: замер
    # 10.08 на `snowdon_plumb_v4` дал 100.07%, а на РД-башне смесь стоила
    # +9.38 п.п. (v7 85.23% без стадии оформления против v8 94.61% с ней, на
    # одних и тех же 115 880 прочитанных элементах).
    ops_by_class: dict[str, int] = {cls.value: 0 for cls in ContentClass}
    if ops_by_category:
        for key, count in ops_by_category.items():
            ops_by_class[classify(key).value] += int(count)
        ops_class_source = "по категории элемента-источника"
    else:
        # Молчание тут запрещено: «нет разбивки» и «оформительских опов нет» —
        # разные факты, и второй нельзя подставлять вместо первого.
        ops_by_class[ContentClass.MODEL.value] = ops or 0
        ops_class_source = "разбивки нет: числитель отнесён к зданию"
    ops_model = ops_by_class[ContentClass.MODEL.value]

    per_class: dict[str, dict[str, Any]] = {
        cls.value: {"census": 0, "read": 0, "categories": 0, "rows": []}
        for cls in ContentClass
    }
    unknown_rows: list[dict[str, Any]] = []

    for row in census:
        key = row["key"]
        count = int(row["count"])
        cls = classify(key)
        read = extracted.get(key, 0)
        bucket = per_class[cls.value]
        bucket["census"] += count
        bucket["read"] += read
        bucket["categories"] += 1
        bucket["rows"].append({
            "category": key,
            "category_ru": row.get("name", ""),
            "census": count,
            "read": read,
        })
        if cls is ContentClass.UNKNOWN:
            unknown_rows.append(bucket["rows"][-1])

    for bucket in per_class.values():
        bucket["rows"].sort(key=lambda r: -r["census"])

    census_total = sum(int(r["count"]) for r in census)
    model = per_class[ContentClass.MODEL.value]["census"]
    model_read = per_class[ContentClass.MODEL.value]["read"]
    documentation = per_class[ContentClass.DOCUMENTATION.value]["census"]
    unknown = per_class[ContentClass.UNKNOWN.value]["census"]
    content = model + documentation

    def pct(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round(100.0 * numerator / denominator, 2)

    # Порождаемые (ячейки витража, импосты, вложенные общие семейства) лежат
    # ВНУТРИ класса «здание»: это элементы модели, у которых своей операции нет
    # по построению — их создаёт другая операция. Пока они в знаменателе,
    # «покрытие здания» меряет не компилятор, а долю порождаемого в проекте.
    #
    # Допущение названо и проверяемо: все порождаемые обязаны быть модельными.
    # Нарушится (например, порождаемые аннотации) — прогон СКАЖЕТ, а не
    # подгонит вычитание молча.
    assumption_broken = generator_children > model_read
    authored_model = max(model - generator_children, 0)
    authored_model_read = max(model_read - generator_children, 0)
    authored_content = authored_model + documentation
    # Второе допущение, названное рядом с первым по его же образцу: числитель
    # не может превышать знаменатель. Пока оно держится, «сколько не выражено»
    # исчислимо; нарушится — прибор ОТКАЗЫВАЕТСЯ считать, а не подгоняет.
    numerator_exceeds_read = ops_model > authored_model_read

    # Коллекторы-псевдонимы читают элементы, уже посчитанные переписью под их
    # настоящими категориями. Их след виден только в «прочитано», и если он
    # ненулевой — сумма прочитанного по классам будет меньше общего числа
    # элементов. Это не ошибка, но и не молчание: печатаем.
    alias_read = {k: v for k, v in extracted.items() if k in COLLECTOR_ALIASES}

    return {
        "directory": str(directory),
        "doc_name": header.get("document", {}).get("doc_name", ""),
        "ops": ops,
        "ops_by_class": ops_by_class,
        "ops_class_source": ops_class_source,
        "elements_read": elements,
        "generator_children": generator_children,
        "census_total": census_total,
        "categories_total": len(census),
        # ═══ ЧЕМ ЭТОТ ПРОЦЕНТ ОБУСЛОВЛЕН, РЯДОМ С НИМ САМИМ ═══
        #
        # ЗАМЕР 12.08.2026, ДВЕ РЕВИЗИИ ОДНОГО ФАСАДА, КОМПИЛЯТОР МЕЖДУ НИМИ
        # НЕ МЕНЯЛСЯ НИ НА СТРОКУ: `sob62_fas_r23_v12` даёт 63.80%,
        # `sob62_fas_r23_v19` — 91.23%. Разница 27 пунктов, и делает её НЕ
        # выразительность и даже не объём чтения в наивном смысле: прочитано
        # 5 095 против 5 218, то есть +2.4%.
        #
        # МЕХАНИЗМ ОСТРЕЕ. Одна лишняя прочитанная категория — 122 сетки
        # витража — позволила лифтеру ОПОЗНАТЬ 1 264 панели и импоста как
        # порождённых детей витражной стены. `generator_child` из честной
        # цифры исключается, поэтому знаменатель упал ровно на них
        # (4 205 -> 2 942), а числитель почти не двинулся (2 683 -> 2 806).
        # То есть **123 прочитанных элемента переклассифицировали 1 264
        # других**, и процент вырос от ЧТЕНИЯ, а не от компилятора.
        #
        # НИ ОДИН ФЛАГ ЭТОГО НЕ ЛОВИЛ: у обоих прогонов `census_balanced:
        # true`, `errors: []`, `done: 1`, `is_partial_read: false`, и даже
        # `generator_children_assumption_broken: false`. Различал их только
        # `categories_scanned` (14 против 15), который ни с чем не сравнивался.
        #
        # ПОЭТОМУ ПРОЦЕНТ ЕДЕТ СО СВОИМИ УСЛОВИЯМИ. Сигнал НЕ ЗАВОДИТСЯ
        # заново — он ВЫЧИСЛЯЕТСЯ у существующих авторитетов: таблица
        # извлечения (что мы вообще умеем читать) против переписи §18.1 (что
        # в документе есть) против фактически прочитанного. Категория, которая
        # В ТАБЛИЦЕ ЕСТЬ и в переписи ненулевая, а прочитана в ноль, — это не
        # «вне таблицы» (известный и названный пробел метрики), а другая,
        # опасная причина, и она обязана стоять рядом с числом.
        "conditions": _conditions(directory, census, extracted),
        "denominators": {
            "model": model,
            "model_authored": authored_model,
            "documentation": documentation,
            "content": content,
            "content_authored": authored_content,
            "document": census_total,
            "unknown": unknown,
        },
        # ЗДАНИЕ меряется зданием: числитель — только модельные опы.
        "model_pct": pct(ops_model, model),
        "model_pct_authored": pct(ops_model, authored_model),
        # СОДЕРЖАНИЕ = здание + оформление, поэтому здесь числитель полный.
        "content_pct": pct(ops, content),
        "content_pct_authored": pct(ops, authored_content),
        # Нижняя граница: если ВСЁ неклассифицированное окажется
        # содержательным. Настоящее число лежит между этим и
        # content_pct_authored — интервал, а не одно удобное число.
        "content_pct_lower_bound": pct(ops, authored_content + unknown),
        "document_pct": pct(ops, census_total),
        # Разрыв разложен на две причины, которые чинятся РАЗНЫМ трудом.
        "gap": {
            # Строка в таблице категорий: элементы здания, которых мы не видим.
            "model_unread": model - model_read,
            # Лифтер и оп: прочитано, авторское, но в опы не поднято.
            "model_read_authored": authored_model_read,
            # ИНВЕРСИЯ ОТКАЗЫВАЕТ, А НЕ ГАСИТСЯ (13.08.2026).
            #
            # Здесь стоял `max(authored_model_read - ops_model, 0)`. Числитель
            # (узлы-опы из `relift_offline`) и знаменатель (перепись §18.1)
            # приходят от РАЗНЫХ производителей, и сверки между ними нет:
            # ничто не мешает числителю превысить знаменатель. Зажим превращал
            # это в аккуратный ноль — в колонке «сколько мы НЕ выразили», то
            # есть печатал самый лестный из возможных ответов. **Гашение
            # скрывало ошибку В ПОЛЬЗУ НАШЕГО ЖЕ ЧИСЛА.**
            #
            # И это не гипотеза: на `sob62_fas_r23_v19` настоящий `build` с
            # удвоенным числителем (имитация лифтера, дающего два опа на
            # элемент) печатал **182.46% и «невыраженных 0»** — молча. А
            # `relift_offline.py:235` помнит замер 10.08, когда колонка уже
            # печатала 100.07% на `snowdon_plumb_v4`; тогда починили
            # КЛАССИФИКАЦИЮ, сверку не добавили.
            #
            # `None`, а не 0: «не знаем, сколько не выражено» и «не выражено
            # ноль» — разные факты, и второй сегодня печатался вместо первого.
            "model_read_unlifted": (
                None if numerator_exceeds_read
                else authored_model_read - ops_model),
            "expressed_of_read_pct": (
                None if numerator_exceeds_read
                else pct(ops_model, authored_model_read)),
            # СВОЙСТВО, НА КОТОРОМ ВСЁ ДЕРЖИТСЯ, — И ОНО НЕ ГАРАНТИРОВАНО.
            # Колонка верна, пока лифтер даёт ОДИН оп на элемент. Замерено
            # 13.08 по всему корпусу: 52 прогона с деревом, 247 347 узлов-опов,
            # столько же различных `source_element_id`, дельта 0, немых
            # прогонов 0. Но ничто в коде этого не требует, а библиотека
            # компонентов уже однажды это свойство сломала — покрытие,
            # посчитанное по РАЗВЁРНУТОМУ выводу, было завышено ровно на
            # избыток 2 351.
            "expressed_numerator_exceeds_read": numerator_exceeds_read,
            # Целый класс, которого мы не касались: оформление.
            "documentation_unread": documentation
            - per_class[ContentClass.DOCUMENTATION.value]["read"],
        },
        "generator_children_assumption_broken": assumption_broken,
        "per_class": {
            name: {k: v for k, v in bucket.items() if k != "rows"}
            for name, bucket in per_class.items()
        },
        "per_class_rows": {name: bucket["rows"]
                           for name, bucket in per_class.items()},
        "unknown_rows": sorted(unknown_rows, key=lambda r: -r["census"]),
        "alias_collectors_read": alias_read,
    }


def _conditions_line(cond: dict[str, Any]) -> str:
    if not cond.get("table_available"):
        return ("УСЛОВИЯ НЕИЗВЕСТНЫ: таблицы извлечения нет — с чем этот "
                "процент сопоставим, сказать нечем")
    unread = cond.get("in_table_unread") or {}
    scanned = cond.get("categories_scanned")
    head = (f"условия: категорий отсканировано {scanned}; "
            f"умели прочесть, но не прочли — {len(unread)} категорий "
            f"({cond.get('in_table_unread_elements', 0)} элементов)")
    if not unread:
        return head + ". Сопоставим только с прогоном такого же множества."
    names = ", ".join(f"{k}:{v}" for k, v in list(unread.items())[:6])
    tail = "" if len(unread) <= 6 else f" и ещё {len(unread) - 6}"
    return (head + f"\n  НЕ ПРОЧИТАНО ИЗ ТОГО, ЧТО УМЕЕМ: {names}{tail}"
            "\n  Сравнивать этот процент можно ТОЛЬКО с прогоном, у которого "
            "это множество ТО ЖЕ.")


def render(report: dict[str, Any]) -> str:
    den = report["denominators"]
    gap = report["gap"]
    model_bucket = report["per_class"][ContentClass.MODEL.value]
    doc_bucket = report["per_class"][ContentClass.DOCUMENTATION.value]

    def col(value: float | None) -> str:
        """Пустой знаменатель печатается прочерком, а не нулём: ноль — это
        замер «ничего не выражаем», прочерк — «мерить нечего»."""
        return f"{'—':>9} " if value is None else f"{value:>9}%"
    lines = [
        f"{report['doc_name']}  ({report['directory']})",
        f"опов поднято: {report['ops']}   элементов прочитано: "
        f"{report['elements_read']}   категорий в переписи: "
        f"{report['categories_total']}",
        # Числитель обязан называть свой состав рядом с процентами: пока он
        # был одним числом, оформительские опы молча считались зданием.
        f"опы по классам: {report['ops_by_class']}   ({report['ops_class_source']})",
        # УСЛОВИЯ СТОЯТ НАД ЧИСЛОМ, А НЕ ПОД НИМ: читатель, дошедший до
        # процента, уже должен знать, с чем этот процент сопоставим.
        _conditions_line(report.get("conditions") or {}),
        "",
        f"{'знаменатель':<30}{'элементов':>10}{'читаем':>9}{'покрытие':>10}",
        f"{'ЗДАНИЕ':<30}{den['model']:>10}{model_bucket['read']:>9}"
        f"{col(report['model_pct'])}",
        f"{'ЗДАНИЕ без порождаемых':<30}{den['model_authored']:>10}"
        f"{gap['model_read_authored']:>9}{col(report['model_pct_authored'])}",
        f"{'+ оформление = СОДЕРЖАНИЕ':<30}{den['content_authored']:>10}"
        f"{gap['model_read_authored'] + doc_bucket['read']:>9}"
        f"{col(report['content_pct_authored'])}",
        f"{'ВЕСЬ ДОКУМЕНТ':<30}{den['document']:>10}"
        f"{report['elements_read']:>9}{col(report['document_pct'])}",
        "",
        "разрыв разложен (чинится РАЗНЫМ трудом):",
        f"  выражаем из прочитанного здания: {gap['expressed_of_read_pct']}% "
        f"({report['ops_by_class']['model']} модельных опов из "
        f"{gap['model_read_authored']} авторских)",
        f"  не ЧИТАЕМ элементов здания:      {gap['model_unread']}"
        f"   ← строка в таблице категорий",
        (f"  читаем, но не поднимаем:         {gap['model_read_unlifted']}"
         f"   ← лифтер и оп"
         if gap["model_read_unlifted"] is not None else
         "  читаем, но не поднимаем:         НЕИСЧИСЛИМО"
         "   ← числитель больше знаменателя, см. ВНИМАНИЕ ниже"),
        f"  оформление не читается вовсе:    {gap['documentation_unread']}"
        f"   ← целый класс",
        "",
        "по классам:",
    ]
    for name, bucket in report["per_class"].items():
        if not bucket["census"]:
            continue
        share = 100.0 * bucket["census"] / report["census_total"]
        lines.append(f"  {name:<14} {bucket['census']:>7} эл. "
                     f"({share:5.2f}% документа), категорий "
                     f"{bucket['categories']:>3}, читаем {bucket['read']}")
    if report["unknown_rows"]:
        lines.append("")
        lines.append("НЕ КЛАССИФИЦИРОВАНО (правь таблицу или объясни):")
        # ОТСЕЧКА НАЗЫВАЕТ, СКОЛЬКО СКРЫЛА (13.08.2026). Список резался на
        # двадцати молча: на `snowdon_plumb_v5` незнакомых 44, читатель видел
        # 20 и не знал об остальных 24; на `snowdon_elec_v1` — 22 и 2. Это наше
        # же правило «никаких молчаливых отсечек», нарушенное в приборе, по
        # которому считаются доли. Показ по-прежнему ограничен — длинный хвост
        # нечитаем, — но ограничение теперь ЗАЯВЛЕНО числом.
        shown = report["unknown_rows"][:_UNKNOWN_ROWS_SHOWN]
        for row in shown:
            lines.append(f"  {row['census']:>7}  {row['category']}"
                         f"  {row['category_ru']}")
        hidden = report["unknown_rows"][len(shown):]
        if hidden:
            lines.append(
                f"  … и ещё {len(hidden)} категорий на "
                f"{sum(r['census'] for r in hidden)} элементов — НЕ ПОКАЗАНЫ "
                f"(показ ограничен {_UNKNOWN_ROWS_SHOWN} строками; полный "
                f"список в `--json`)")
        lower = report["content_pct_lower_bound"]
        lines.append(f"  ⇒ содержательное покрытие лежит между {lower}% "
                     f"и {report['content_pct_authored']}%")
    if report["alias_collectors_read"]:
        lines.append("")
        lines.append(f"коллекторы-псевдонимы (уже в переписи под своими "
                     f"категориями): {report['alias_collectors_read']}")
    if report["gap"]["expressed_numerator_exceeds_read"]:
        lines.append("")
        lines.append(
            "ВНИМАНИЕ: ВЫРАЖЕНО БОЛЬШЕ, ЧЕМ ПРОЧИТАНО "
            f"({report['ops_by_class']['model']} опов из "
            f"{report['gap']['model_read_authored']} авторских) — числитель и "
            "знаменатель приходят от РАЗНЫХ производителей, и это значит, что "
            "лифтер дал больше одного опа на элемент либо числитель посчитан "
            "по развёрнутому выводу. Проценты выше НЕ ПЕЧАТАЮТСЯ: доля больше "
            "ста — не результат, а отказ прибора. Следующий ход: сверить число "
            "узлов-опов с числом различных source_element_id "
            "(13.08: 52 прогона, 247 347 опов, дельта 0).")
    if report["generator_children_assumption_broken"]:
        lines.append("")
        lines.append(
            "ВНИМАНИЕ: порождаемых больше, чем прочитано модельных элементов "
            f"({report['generator_children']} > {model_bucket['read']}) — "
            "допущение «порождаемое всегда модельное» нарушено, вычитание "
            "ниже не обосновано")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=pathlib.Path)
    parser.add_argument("--ops", type=int, default=None,
                        help="число опов, если пересчёт лифтом не нужен")
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    report = build(args.directory, ops=args.ops)
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"\n→ {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
