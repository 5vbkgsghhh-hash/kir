"""Wave A read-only, streamed Revit-to-L0 extraction.

The bridge is injected as an async callable so this module owns no device or
transport policy.  One bridge response contains at most ``EXTRACT_BATCH``
elements; JSONL persistence commits one category at a time and can resume by
truncating any uncommitted category tail.
"""
from __future__ import annotations

import asyncio
import logging
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Mapping

from kukai.ir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS

from .census_contract import NO_CATEGORY_KEY
from .geometry_store import GEOMETRY_HELPER_CS, parse_geometry
from .schema import (
    EXTRACT_BATCH,
    EXTRACT_RETRIES,
    EXTRACT_TIMEOUT_MS,
    EXTRACT_WINDOW_POLL_S,
    EXTRACT_WINDOW_WAIT_S,
    L0_DIALECT_VERSION,
    L0_SCHEMA_VERSION,
    SECTION_RECEIPT_OUTCOMES,
    CategoryState,
    CategoryStatus,
    L0Dialect,
    L0Document,
    L0Element,
    L0SchemaError,
    LinkSummary,
    RoomInfo,
    SectionReceipt,
    dialect_by_version,
    resolve_dialect,
)
from .side_contract import source_binding_cs


BridgeExecutor = Callable[..., Awaitable[Any]]
DECOMPILE_OUT_ENV = "KUKAI_DECOMPILE_OUT"


def default_output_root() -> Path:
    """Корень для артефактов декомпайла, когда вызывающий не назвал путь.

    §18.5: абсолютный путь установки («/root/kukai-ir/decompile_out») в
    исполняемом коде запрещён — на чужой машине это либо чужая ФС, либо отказ
    прав. Главный источник остаётся прежним — env ``KUKAI_DECOMPILE_OUT``;
    дефолт нейтрален и задокументирован: подкаталог системного temp
    (``$TMPDIR/kukai-ir/decompile_out``), то есть место, писать в которое
    процесс вправе на любой ОС. Прод и все живые прогоны путь задают явно
    (pipeline получает ``out_dir`` от serving), поэтому дефолт — только для
    ручного вызова extract_document без аргумента.
    """
    configured = os.environ.get(DECOMPILE_OUT_ENV)
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "kukai-ir" / "decompile_out"


# Историческое имя (импортируется инструментами) — вычисляется на импорте.
DEFAULT_OUTPUT_ROOT = default_output_root()


class ExtractionError(RuntimeError):
    """The extraction contract could not be completed safely."""


class ExtractionProtocolError(ExtractionError):
    """A bridge/checkpoint/JSONL payload violates the extraction protocol."""


logger = logging.getLogger(__name__)


class BridgeCallError(ExtractionError):
    """A bridge round-trip failed after its bounded retry budget."""


class DocumentRevisionError(ExtractionError):
    """Two read-only calls did not observe one immutable document revision."""


class TemplateCompileError(ExtractionError):
    """НАШ шаблон не стал сборкой — до Revit не доехало ничего.

    Отдельный род отказа, а не разновидность транспортной неудачи, и разница
    не косметическая: нескомпилировавшийся текст не соберётся оттого, что мы
    подождали. Ретрай и ожидание окна для него — чистая трата часов.

    ЖИВОЙ СЛУЧАЙ 30.07, ради которого класс заведён. Разбор 59-этажной башни
    на R2023 полтора часа печатал «окно не отвечает на боковая стадия
    annotation пачка 1/14 — ждём возвращения», пока служба по кругу писала
    ``TEMPLATE COMPILE FAILED ... CS1503 ... bridge_roundtrips=0``. Окно было
    живым. Слой ожидания отправлял искать причину в Revit — то есть ровно
    туда, где её не было; а наружу при этом уходило ``ExtractionProtocolError:
    True``, потому что причина бралась из БУЛЕВА флага ``error``.
    """


@dataclass(frozen=True, slots=True)
class CategorySpec:
    name: str
    collector_cs: str
    exclude_direct_shape: bool = True
    # Раздел проекта, к которому категория относится. Тот же закрытый словарь,
    # что у KindSpec (registry_base.DISCIPLINES) — второго словаря о том же
    # понятии в пакете быть не должно.
    #
    # Зачем в ЭКСТРАКТОРЕ: по составу категорий видно, какой раздел лежит в
    # документе, и это честнее, чем разбирать имя файла — имя врёт легко,
    # состав не врёт. Карта покрытия обязана называть, какие разделы вошли в
    # выборку: 27.07 она замерила два документа, оба архитектурные, и на
    # этом основании было заявлено «покрытие стабильно между зданиями» —
    # утверждение про компилятор, сделанное по свойству выборки. На первой
    # же не-АР модели оно рухнуло с ~93% до 67.7%.
    discipline: str = "shared"

    def __post_init__(self) -> None:
        from kukai.ir.registry_base import DISCIPLINES
        if self.discipline not in DISCIPLINES:
            raise ValueError(
                f"CategorySpec {self.name!r}: unknown discipline "
                f"{self.discipline!r}")


# The order is part of the resume format.  These are the exact 22 families in
# DECOMPILE §4.4; class-only families use stable pseudo-category names because
# no single BuiltInCategory identifies every DirectShape or ImportInstance.
_CATEGORY_SPECS = (
    CategorySpec("OST_Walls",
                 ".OfCategory(BuiltInCategory.OST_Walls)",
                 discipline="architectural"),
    CategorySpec("OST_Floors",
                 ".OfCategory(BuiltInCategory.OST_Floors)",
                 discipline="architectural"),
    CategorySpec("OST_Roofs",
                 ".OfCategory(BuiltInCategory.OST_Roofs)",
                 discipline="architectural"),
    CategorySpec("OST_Columns",
                 ".OfCategory(BuiltInCategory.OST_Columns)",
                 discipline="architectural"),
    CategorySpec("OST_StructuralColumns",
                 ".OfCategory(BuiltInCategory.OST_StructuralColumns)",
                 discipline="structural"),
    CategorySpec("OST_StructuralFraming",
                 ".OfCategory(BuiltInCategory.OST_StructuralFraming)",
                 discipline="structural"),
    CategorySpec("OST_StructuralFoundation",
                 ".OfCategory(BuiltInCategory.OST_StructuralFoundation)",
                 discipline="structural"),
    CategorySpec("OST_Doors",
                 ".OfCategory(BuiltInCategory.OST_Doors)",
                 discipline="architectural"),
    CategorySpec("OST_Windows",
                 ".OfCategory(BuiltInCategory.OST_Windows)",
                 discipline="architectural"),
    CategorySpec("OST_Stairs",
                 ".OfCategory(BuiltInCategory.OST_Stairs)",
                 discipline="architectural"),
    CategorySpec("OST_StairsRailing",
                 ".OfCategory(BuiltInCategory.OST_StairsRailing)",
                 discipline="architectural"),
    CategorySpec("OST_Rooms",
                 ".OfCategory(BuiltInCategory.OST_Rooms)",
                 discipline="architectural"),
    CategorySpec("OST_Grids", ".OfClass(typeof(Grid))"),
    CategorySpec("OST_Levels", ".OfClass(typeof(Level))"),
    CategorySpec("OST_PipeCurves",
                 ".OfCategory(BuiltInCategory.OST_PipeCurves)",
                 discipline="plumbing"),
    CategorySpec("OST_DuctCurves",
                 ".OfCategory(BuiltInCategory.OST_DuctCurves)",
                 discipline="mechanical"),
    CategorySpec("OST_CableTray",
                 ".OfCategory(BuiltInCategory.OST_CableTray)",
                 discipline="electrical"),
    CategorySpec("OST_Furniture",
                 ".OfCategory(BuiltInCategory.OST_Furniture)",
                 discipline="architectural"),
    CategorySpec("OST_GenericModel",
                 ".OfCategory(BuiltInCategory.OST_GenericModel)"),
    CategorySpec(
        "DirectShape", ".OfClass(typeof(DirectShape))",
        exclude_direct_shape=False),
    CategorySpec(
        "ImportInstance", ".OfClass(typeof(ImportInstance))",
        exclude_direct_shape=False),
    CategorySpec("OST_RasterImages",
                 ".OfCategory(BuiltInCategory.OST_RasterImages)"),

    # ── Разделы кроме АР (добавлено 27.07) ─────────────────────────────────
    # ДОПИСАНО В КОНЕЦ НАМЕРЕННО: порядок этого кортежа — часть формата
    # возобновления, вставка в середину сдвинула бы индексы уже начатых
    # извлечений.
    #
    # Повод замерен: в тренировочной модели ЭОМ (SKLNK, R2026) содержимое —
    # электрооборудование, светильники, короба и фитинги лотков, и НИ ОДНОЙ
    # из этих категорий в таблице не было. То есть раздел целиком был
    # невидим, а отказ выглядел бы как отказ компилятора, хотя это отсутствие
    # строки. Таблица знала 20 категорий, из них 12 архитектурных.
    #
    # Каждая строка — коллектор и ничего больше; проверка та же, что у видов:
    # категория, которой нет в какой-то из шести версий Revit, роняет ворота.

    # ЭОМ
    CategorySpec("OST_ElectricalEquipment",
                 ".OfCategory(BuiltInCategory.OST_ElectricalEquipment)",
                 discipline="electrical"),
    CategorySpec("OST_ElectricalFixtures",
                 ".OfCategory(BuiltInCategory.OST_ElectricalFixtures)",
                 discipline="electrical"),
    CategorySpec("OST_LightingFixtures",
                 ".OfCategory(BuiltInCategory.OST_LightingFixtures)",
                 discipline="electrical"),
    CategorySpec("OST_LightingDevices",
                 ".OfCategory(BuiltInCategory.OST_LightingDevices)",
                 discipline="electrical"),
    CategorySpec("OST_CableTrayFitting",
                 ".OfCategory(BuiltInCategory.OST_CableTrayFitting)",
                 discipline="electrical"),
    CategorySpec("OST_Conduit",
                 ".OfCategory(BuiltInCategory.OST_Conduit)",
                 discipline="electrical"),
    CategorySpec("OST_ConduitFitting",
                 ".OfCategory(BuiltInCategory.OST_ConduitFitting)",
                 discipline="electrical"),

    # ОВ
    CategorySpec("OST_MechanicalEquipment",
                 ".OfCategory(BuiltInCategory.OST_MechanicalEquipment)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctFitting",
                 ".OfCategory(BuiltInCategory.OST_DuctFitting)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctTerminal",
                 ".OfCategory(BuiltInCategory.OST_DuctTerminal)",
                 discipline="mechanical"),
    CategorySpec("OST_FlexDuctCurves",
                 ".OfCategory(BuiltInCategory.OST_FlexDuctCurves)",
                 discipline="mechanical"),
    CategorySpec("OST_MEPSpaces",
                 ".OfCategory(BuiltInCategory.OST_MEPSpaces)",
                 discipline="mechanical"),

    # ВК
    CategorySpec("OST_PlumbingFixtures",
                 ".OfCategory(BuiltInCategory.OST_PlumbingFixtures)",
                 discipline="plumbing"),
    CategorySpec("OST_PipeFitting",
                 ".OfCategory(BuiltInCategory.OST_PipeFitting)",
                 discipline="plumbing"),
    CategorySpec("OST_PipeAccessory",
                 ".OfCategory(BuiltInCategory.OST_PipeAccessory)",
                 discipline="plumbing"),
    CategorySpec("OST_FlexPipeCurves",
                 ".OfCategory(BuiltInCategory.OST_FlexPipeCurves)",
                 discipline="plumbing"),
    CategorySpec("OST_Sprinklers",
                 ".OfCategory(BuiltInCategory.OST_Sprinklers)",
                 discipline="plumbing"),

    # КР
    CategorySpec("OST_StructuralTruss",
                 ".OfCategory(BuiltInCategory.OST_StructuralTruss)",
                 discipline="structural"),

    # АР — то, чего не хватало в собственном разделе
    CategorySpec("OST_Ceilings",
                 ".OfCategory(BuiltInCategory.OST_Ceilings)",
                 discipline="architectural"),
    CategorySpec("OST_Ramps",
                 ".OfCategory(BuiltInCategory.OST_Ramps)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainWallPanels",
                 ".OfCategory(BuiltInCategory.OST_CurtainWallPanels)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainWallMullions",
                 ".OfCategory(BuiltInCategory.OST_CurtainWallMullions)",
                 discipline="architectural"),
    CategorySpec("OST_Casework",
                 ".OfCategory(BuiltInCategory.OST_Casework)",
                 discipline="architectural"),
    CategorySpec("OST_SpecialityEquipment",
                 ".OfCategory(BuiltInCategory.OST_SpecialityEquipment)",
                 discipline="architectural"),
    CategorySpec("OST_Areas",
                 ".OfCategory(BuiltInCategory.OST_Areas)",
                 discipline="architectural"),

    # ДОПИСАНО В КОНЕЦ НАМЕРЕННО, тем же поводом, что и раздел выше (порядок
    # этого кортежа — часть формата возобновления, вставка в середину
    # сдвинула бы индексы уже начатых извлечений): витражная СИСТЕМА
    # (BuiltInCategory.OST_CurtaSystem, имя проверено по строкам RevitAPI.dll
    # всех шести версий 2021-2026) — третий род носителя витражной сетки
    # наравне со стеной и кровлей. Без строки здесь такой носитель в таблице
    # категорий невидим ЧТЕНИЮ: create_curtain-захват (curtain_extract.py) уже
    # умеет ходить по CurtainSystem.CurtainGrids, но кормить его id было
    # неоткуда — панели витражной системы не получали носителя (хвост волны
    # aaa44b45, 28.07).
    CategorySpec("OST_CurtaSystem",
                 ".OfCategory(BuiltInCategory.OST_CurtaSystem)",
                 discipline="architectural"),

    # ЛИНИИ РАЗРЕЗКИ ВИТРАЖА. Дописано в конец по той же причине, что и
    # строка выше: порядок кортежа — часть формата возобновления.
    #
    # ЗАЧЕМ. Линия разрезки — настоящий элемент со своим id, и раскладка
    # сетки задаётся именно ими: тип носителя её не несёт (живой замер v14:
    # у ВСЕХ 393 витражных носителей все шесть слотов SPACING_LAYOUT_* равны
    # нулю, а линий при этом 122 на 70 носителях). Пока категории не было в
    # этой таблице, линии не существовало для ЧТЕНИЯ, и обратный ход не мог
    # поставить её операцией, не ИЗОБРЕТЯ источник — на чём живой прогон
    # v14 и остановился: FoldError('L0/L1 source mismatch: missing=0,
    # invented=122'). Закон переписи фолда прав: лифт не вправе изобретать
    # источники, поэтому чинится сторона L0.
    #
    # ИМЯ КАТЕГОРИИ ЗАМЕРЕНО, А НЕ УГАДАНО. Перепись живой модели v14
    # назвала её сама: OST_CurtainGridsWall, 122 элемента — ровно столько,
    # сколько линий в curtain-индексе того же прогона. Существование всех
    # трёх имён проверено компиляцией на 2021-2026 (OST_CurtainGridWall и
    # OST_CurtainGridsSlopedGlazing, для сравнения, не компилируются ни на
    # одной версии).
    #
    # РОДОВ ТРИ, ПОТОМУ ЧТО ТРИ РОДА НОСИТЕЛЯ: стена, кровля, витражная
    # система — ровно те, по которым уже ходит curtain_extract.py. Имена
    # OST_CurtainGrids и OST_CurtainGridsSystem в таблицу НЕ включены
    # сознательно: они компилируются, но ни один замер не говорит, что за
    # ними стоит, а закрытый список не место для догадок.
    CategorySpec("OST_CurtainGridsWall",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsWall)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainGridsRoof",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsRoof)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainGridsCurtaSystem",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsCurtaSystem)",
                 discipline="architectural"),
    # ── R4 красных: ИЗОЛЯЦИЯ И ФУТЕРОВКА. Тело препятствия есть в модели
    # ОТДЕЛЬНЫМ элементом со своим габаритом — и мы его не спрашивали.
    # Замер красных: ДУ20 (наружный 26.9 мм) + 50 мм изоляции — оболочка трубы
    # покрывала 4.5 % площади сечения препятствия. Для мелких диаметров
    # изоляция ТОЛЩЕ трубы. Изолированные трубопроводы — норма для ОВ и ВК,
    # то есть для двух из трёх разделов MVP.
    #
    # ИМЕНА ПРОВЕРЕНЫ КОМПИЛЯЦИЕЙ 6/6 (2021-2026), а не по памяти: в
    # RevitAPI.xml членов BuiltInCategory нет вовсе, поэтому единственный
    # честный способ проверки — компайл-сервис.
    #
    # Дописано В КОНЕЦ: порядок категорий — часть замороженной схемы потока
    # (`category_status` идёт строго по нему), и вставка в середину сдвинула
    # бы все существующие L0.
    CategorySpec("OST_PipeInsulations",
                 ".OfCategory(BuiltInCategory.OST_PipeInsulations)",
                 discipline="plumbing"),
    CategorySpec("OST_DuctInsulations",
                 ".OfCategory(BuiltInCategory.OST_DuctInsulations)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctLinings",
                 ".OfCategory(BuiltInCategory.OST_DuctLinings)",
                 discipline="mechanical"),

    # ── РАБОЧАЯ ДОКУМЕНТАЦИЯ: РАЗМЕРЫ, МАРКИ, ПРИМЕЧАНИЯ (29.07) ──────────
    #
    # ЗАЧЕМ. Замер на настоящей РД (13A-RD-AR-K2_v33, слепок k2_ar_rd_v6)
    # вскрыл главную дыру ЧТЕНИЯ: покрытие ОТ ДОКУМЕНТА 9.61 %. В переписи
    # 112 категорий и 310 558 элементов, а таблица читала 54 категории =
    # 55 293 элемента, то есть 17.80 % документа. Бо́льшая часть остального
    # вне таблицы ЗАКОННО — это производное и внутреннее: OST_AreaSchemeLines
    # 61 520, no_category 53 885, OST_SketchLines 38 093, OST_WeakDims 19 547.
    # Но ВМЕСТЕ с ними невидимым лежало СОДЕРЖАНИЕ рабочей документации:
    # размеры 13 905, марки помещений 11 585, линии 9 407, элементы узлов
    # 3 046, текстовые примечания 2 697. Мы делаем инструмент для РД, а
    # размеры, марки и примечания и ЕСТЬ рабочая документация. Без строки
    # здесь их не существует для чтения вовсе: ни элемента, ни статуса
    # категории, ни отказа — ровно та немота, ради запрета которой заведён
    # закон переписи (§18.1).
    #
    # ЧЕМ ЗАМЕРЕНО. Все числа выше и ниже — перепись ТОГО САМОГО прогона
    # (заголовок L0.jsonl, поле census, 112 строк), а не оценка. Каждая
    # строка ниже входит с ЗАМЕРЕННЫМ ненулевым числом элементов; ни одного
    # имени «на будущее» здесь нет. Это тот же порог, по которому 28.07 в
    # таблицу не пустили OST_CurtainGrids и OST_CurtainGridsSystem: они
    # компилируются, но ни один замер не говорит, что за ними стоит, а
    # закрытый список не место для догадок. По этой же причине отсюда
    # выброшены марки, которых в замеренном документе нет (OST_WindowTags,
    # OST_CeilingTags и прочие сиблинги): включать их — гадать, а исключать
    # OST_WallTags при включённом OST_DoorTags — подгонять таблицу под одну
    # модель. Разрешение обоих запретов одно: входит ЗАМЕРЕННОЕ, целиком.
    #
    # ПРАВИЛО ДОПУСКА (решение лида 29.07, исполнено буквально): категория
    # входит, если (а) её элементы — проектное СОДЕРЖАНИЕ, а не производное
    # от другого элемента, И (б) есть оп, способный её выразить, ЛИБО её
    # чтение нужно как КОНТЕКСТ. Поэтому здесь НЕТ эскизов и автонанесения
    # (OST_SketchLines, OST_WeakDims, OST_StairsSketch* — производное от
    # своего носителя), нет аналитической модели (OST_AnalyticalNodes 2 744,
    # OST_AnalyticalMember 686 — выводится из физической), нет частей
    # лестниц и ограждений (OST_StairsRuns, OST_StairsLandings,
    # OST_RailingTopRail — части, а не элементы), и нет слоя ЛИСТА
    # (OST_Views 773, OST_Schedules 761, OST_Sheets 159, OST_Viewports 568):
    # лист — настоящая РД, но под него нет ни одного опа и он заслуживает
    # собственной волны, а не хвоста этой.
    #
    # ЧЕТЫРЕ СТРОКИ ВХОДЯТ БЕЗ ОПА, И ЭТО НАЗВАНО ВСЛУХ: OST_Lines,
    # OST_SpotElevations, OST_SpotSlopes, OST_GenericAnnotation. Лифта под
    # них нет, и каждый их элемент станет атомом с типизированной причиной
    # `no_lifter`. Это ХУЖЕ поднятой операции и ЛУЧШЕ невидимости: атом
    # виден в переписи фолда и называет свою причину, а непрочитанная
    # категория молчит. OST_RoomSeparationLines входит по ВТОРОЙ половине
    # правила — как контекст: помещения мы читаем давно, а границы им
    # задают именно эти линии.
    #
    # ИМЕНА ПРОВЕРЕНЫ КОМПИЛЯЦИЕЙ 6/6 (2021-2026), А НЕ ПО ПАМЯТИ: членов
    # BuiltInCategory в RevitAPI.xml нет вовсе, поэтому единственный честный
    # оракул — компайл-сервис. Все 19 имён ниже прошли 6/6. Тем же прогоном
    # взят контроль, и он воспроизвёл записанное выше по файлу:
    # OST_CurtainGridWall и OST_CurtainGridsSlopedGlazing не компилируются
    # ни на одной из шести версий (CS0117).
    #
    # ЦЕНА ЗАМЕРЕНА, А НЕ ПРИКИНУТА. По пяти прогонам одной и той же модели
    # (k2_ar_rd_v1/v2/v3/v5/v6; раунды считаны как пробы + страницы по
    # scope'ам, время — по границам стадии) решается
    # T = 0.326 с/раунд + 12.2 мс/элемент. Остаток полного прогона (~41 мин)
    # — это перепись 310 558 элементов, и она от ЭТОЙ правки не меняется.
    # +60 587 элементов и +19 проб дают +12.7...13.6 мин к стадии извлечения
    # (56.2 -> ~69 мин). Дробление страниц по уровням цену почти не двигает:
    # у аннотаций уровня нет, они попадают в единственный scope "__none__".
    #
    # ПОЧЕМУ ИМЕННО ЗДЕСЬ, В КОНЦЕ. Порядок этого кортежа — часть
    # замороженного формата возобновления: цикл идёт по
    # ``EXTRACT_CATEGORIES[len(processed):]``, то есть категория адресуется
    # ИНДЕКСОМ, и вставка в середину сдвинула бы все начатые извлечения и
    # все существующие L0. Дописка в хвост, наоборот, безопасна — уже
    # снятый чекпойнт просто продолжится с новых строк.
    #
    # Дисциплина у марки — дисциплина её ХОЗЯИНА (та же, что у хозяйской
    # строки этой таблицы); у размеров, линий и примечаний хозяина нет, они
    # общие для всех разделов, поэтому "shared".

    # Размеры, примечания, отметки — то, из чего состоит лист РД.
    CategorySpec("OST_Dimensions",
                 ".OfCategory(BuiltInCategory.OST_Dimensions)"),
    CategorySpec("OST_TextNotes",
                 ".OfCategory(BuiltInCategory.OST_TextNotes)"),
    CategorySpec("OST_SpotElevations",
                 ".OfCategory(BuiltInCategory.OST_SpotElevations)"),
    CategorySpec("OST_SpotSlopes",
                 ".OfCategory(BuiltInCategory.OST_SpotSlopes)"),
    CategorySpec("OST_GenericAnnotation",
                 ".OfCategory(BuiltInCategory.OST_GenericAnnotation)"),

    # Линии: чертёжные и модельные. OST_RoomSeparationLines — контекст
    # помещений (границу помещения задаёт линия, а не стена).
    CategorySpec("OST_Lines",
                 ".OfCategory(BuiltInCategory.OST_Lines)"),
    CategorySpec("OST_RoomSeparationLines",
                 ".OfCategory(BuiltInCategory.OST_RoomSeparationLines)",
                 discipline="architectural"),

    # Элементы узлов — FamilyInstance, то есть place_family.
    CategorySpec("OST_DetailComponents",
                 ".OfCategory(BuiltInCategory.OST_DetailComponents)"),

    # МАРКИ (create_tag). Входят ВСЕ, что замерены в документе, а не те,
    # что первыми попались на глаза, — иначе таблица подгоняется под модель.
    CategorySpec("OST_RoomTags",
                 ".OfCategory(BuiltInCategory.OST_RoomTags)",
                 discipline="architectural"),
    CategorySpec("OST_DoorTags",
                 ".OfCategory(BuiltInCategory.OST_DoorTags)",
                 discipline="architectural"),
    CategorySpec("OST_WallTags",
                 ".OfCategory(BuiltInCategory.OST_WallTags)",
                 discipline="architectural"),
    CategorySpec("OST_FloorTags",
                 ".OfCategory(BuiltInCategory.OST_FloorTags)",
                 discipline="architectural"),
    CategorySpec("OST_AreaTags",
                 ".OfCategory(BuiltInCategory.OST_AreaTags)",
                 discipline="architectural"),
    CategorySpec("OST_StairsRailingTags",
                 ".OfCategory(BuiltInCategory.OST_StairsRailingTags)",
                 discipline="architectural"),
    CategorySpec("OST_StructuralFramingTags",
                 ".OfCategory(BuiltInCategory.OST_StructuralFramingTags)",
                 discipline="structural"),
    CategorySpec("OST_MechanicalEquipmentTags",
                 ".OfCategory(BuiltInCategory.OST_MechanicalEquipmentTags)",
                 discipline="mechanical"),
    CategorySpec("OST_MaterialTags",
                 ".OfCategory(BuiltInCategory.OST_MaterialTags)"),
    CategorySpec("OST_MultiCategoryTags",
                 ".OfCategory(BuiltInCategory.OST_MultiCategoryTags)"),

    # МОДЕЛЬНОЕ СОДЕРЖАНИЕ, а не аннотация: 4 479 элементов замерены в
    # документе, это FamilyInstance под place_family, и категория —
    # прямой сиблинг уже читаемой OST_LightingDevices. Строки не было по
    # той же причине, что и у ЭОМ-волны 27.07: не потому, что решили не
    # читать, а потому, что никто не смотрел.
    CategorySpec("OST_TelephoneDevices",
                 ".OfCategory(BuiltInCategory.OST_TelephoneDevices)",
                 discipline="electrical"),

    # ── ПРОЁМЫ КАК ОТДЕЛЬНЫЕ ЭЛЕМЕНТЫ (wave/opening, 03.08.2026) ──────────
    #
    # ЕДИНСТВЕННАЯ МОЛЧАЛИВАЯ ПОТЕРЯ, найденная обходом восьми зданий. Проём
    # делается ДВУМЯ механизмами: внутренней петлёй эскиза носителя (это мы
    # умеем — 60 create_floor с непустым holes в трёх зданиях) и ОТДЕЛЬНЫМ
    # элементом Opening. Второго не существовало для чтения вовсе, и это
    # хуже, чем «не поднимается»: элемент не извлекается ⇒ атома не даёт ⇒
    # его нет ни в одном ранжире причин, а НОСИТЕЛЬ при этом поднимается
    # обычным create_floor/create_wall и пересобирается СПЛОШНЫМ. Приёмка L2
    # такое не ловит по построению (acceptance.py прямым текстом: геометрию
    # не смотрит вообще), то есть тихо неверный результат снаружи неотличим
    # от успеха.
    #
    # ЧТО ЗАМЕРЕНО (перепись восьми зданий): OST_FloorOpening 10,
    # OST_ShaftOpening 9, OST_SWallRectOpening 9, OST_RoofOpening 7 —
    # 35 элементов в 3 зданиях из 6. Входят ровно эти четыре и ни одной
    # строкой больше: OST_CeilingOpening, OST_ArcWallRectOpening,
    # OST_ColumnOpening и OST_StructuralFramingOpening КОМПИЛИРУЮТСЯ (см.
    # ниже), но ни один замер не говорит, что за ними стоит, — тот же порог,
    # по которому 28.07 в таблицу не пустили OST_CurtainGrids.
    #
    # ИМЕНА ПРОВЕРЕНЫ КОМПИЛЯЦИЕЙ 6/6 (:52412, 2021-2026), а не по памяти:
    # членов BuiltInCategory в RevitAPI.xml нет вовсе. Тем же прогоном взят
    # ОТРИЦАТЕЛЬНЫЙ контроль — выдуманное OST_TotallyMadeUpOpening не
    # компилируется ни на одной версии, то есть оракул различает.
    #
    # ТРИ ИЗ ЧЕТЫРЁХ ИМЕЮТ ОП (`create_opening`, ops_opening.py) и дают
    # `source_contract_gap`: операция есть, а L0 1.0 не несёт ни
    # Opening.Host, ни границы проёма. ЧЕТВЁРТАЯ — OST_ShaftOpening —
    # входит БЕЗ опа и даёт `no_lifter`, и это правда: шахту не строит
    # никакая операция реестра (причина в ops_opening.VARIETIES_NOT_TAKEN —
    # её связь с парой уровней нечем подтвердить с построенного элемента).
    # Прецедент ровно этой формы уже записан выше по файлу: «ЧЕТЫРЕ СТРОКИ
    # ВХОДЯТ БЕЗ ОПА, И ЭТО НАЗВАНО ВСЛУХ ... Это ХУЖЕ поднятой операции и
    # ЛУЧШЕ невидимости».
    #
    # ДОПИСАНО В КОНЕЦ, как и всё выше: порядок кортежа — часть замороженного
    # формата возобновления (цикл идёт по EXTRACT_CATEGORIES[len(processed):],
    # то есть категория адресуется ИНДЕКСОМ). Рост таблицы 73 -> 77 обязан
    # получить свою ступень диалекта — она заведена в schema.py
    # (kir-decompile-l0-dialect/7), иначе свежий слепок не откроется своим же
    # читателем.
    CategorySpec("OST_SWallRectOpening",
                 ".OfCategory(BuiltInCategory.OST_SWallRectOpening)",
                 discipline="architectural"),
    CategorySpec("OST_FloorOpening",
                 ".OfCategory(BuiltInCategory.OST_FloorOpening)",
                 discipline="architectural"),
    CategorySpec("OST_RoofOpening",
                 ".OfCategory(BuiltInCategory.OST_RoofOpening)",
                 discipline="architectural"),
    CategorySpec("OST_ShaftOpening",
                 ".OfCategory(BuiltInCategory.OST_ShaftOpening)",
                 discipline="architectural"),
)
EXTRACT_CATEGORIES = tuple(spec.name for spec in _CATEGORY_SPECS)
_SPEC_BY_NAME = {spec.name: spec for spec in _CATEGORY_SPECS}


_COMMON_HELPERS_CS = r"""
Func<double, double> __MM = (__value) =>
    UnitUtils.ConvertFromInternalUnits(__value, UnitTypeId.Millimeters);
Func<Element, long> __Id = (__e) =>
{
    try { return long.Parse(__e.Id.ToString()); }
    catch { return long.MinValue; }
};
""".strip() + "\n" + ELEMENT_LEVEL_HELPERS_CS


_ELEMENT_HELPERS_CS = r"""
Func<Element, BuiltInParameter, Parameter> __Parameter = (__e, __bip) =>
{
    Parameter __p = null;
    try { __p = __e.get_Parameter(__bip); } catch { }
    if (__p != null && __p.HasValue) return __p;
    try
    {
        var __type = doc.GetElement(__e.GetTypeId());
        if (__type != null) __p = __type.get_Parameter(__bip);
    }
    catch { }
    return (__p != null && __p.HasValue) ? __p : null;
};
Action<Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutLengthParam = (__e, __bip, __name, __params) =>
{
    try
    {
        var __p = __Parameter(__e, __bip);
        if (__p != null && __p.StorageType == StorageType.Double)
            __params[__name] = __MM(__p.AsDouble());
    }
    catch { }
};
// КВИТАНЦИИ fail-open сечений (ревью кодекса №12). Прежде null, HasValue=false,
// чужой StorageType и исключение схлопывались в ОДИН отсутствующий ключ:
// «у этого класса параметра нет» было неотличимо от «параметр есть, а
// прочитать не вышло». Замер v13: ширина у 992 стен из 1189, все 197 пропусков
// совпадают с витражными носителями — совпадение идеальное, а доказательства
// не было. Счётчики агрегатные (шесть int на ПАРАМЕТР, не на элемент),
// поэтому цена не зависит от размера модели.
var __sectionReceipts = new Dictionary<string, int[]>();
Action<string, int> __BumpSection = (__name, __slot) =>
{
    int[] __row;
    if (!__sectionReceipts.TryGetValue(__name, out __row))
    {
        __row = new int[6];
        __sectionReceipts[__name] = __row;
    }
    __row[__slot] = __row[__slot] + 1;
};
Action<Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutSectionParam = (__e, __bip, __name, __params) =>
{
    // Ровно ОДИН инкремент на вызов: иначе сумма перестанет быть переписью.
    bool __counted = false;
    try
    {
        Parameter __p = null;
        bool __exists = false;
        bool __fromType = false;
        try { __p = __e.get_Parameter(__bip); } catch { }
        if (__p != null) __exists = true;
        if (__p == null || !__p.HasValue)
        {
            Parameter __tp = null;
            try
            {
                var __type = doc.GetElement(__e.GetTypeId());
                if (__type != null) __tp = __type.get_Parameter(__bip);
            }
            catch { }
            if (__tp != null)
            {
                __exists = true;
                if (__tp.HasValue) { __p = __tp; __fromType = true; }
            }
        }
        if (__p == null || !__p.HasValue)
        {
            // 2 = not_applicable: параметра нет НИ на экземпляре, НИ на типе —
            // класс элемента его не имеет вовсе. 3 = no_value: параметр есть,
            // значение не задано. Это разные диагнозы одной пустой ячейки.
            __counted = true;
            __BumpSection(__name, __exists ? 3 : 2);
            return;
        }
        if (__p.StorageType != StorageType.Double)
        {
            __counted = true;
            __BumpSection(__name, 4);
            return;
        }
        __params[__name] = __MM(__p.AsDouble());
        __counted = true;
        __BumpSection(__name, __fromType ? 1 : 0);
    }
    catch { if (!__counted) __BumpSection(__name, 5); }
};
// Сечение, которое НЕ длина: WALL_CROSS_SECTION ("Cross-Section") —
// перечисление (Integer), отличающее vertical от slanted/tapered. Читать его
// через __PutSectionParam нельзя: тот требует StorageType.Double и записал бы
// каждой стене `wrong_storage` — ответ честный, но бесполезный. Квитанция
// ОБЩАЯ с длинами: закон переписи (сумма шести исходов = число опрошенных)
// не различает тип хранения.
Action<Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutSectionIntParam = (__e, __bip, __name, __params) =>
{
    bool __counted = false;
    try
    {
        Parameter __p = null;
        bool __exists = false;
        bool __fromType = false;
        try { __p = __e.get_Parameter(__bip); } catch { }
        if (__p != null) __exists = true;
        if (__p == null || !__p.HasValue)
        {
            Parameter __tp = null;
            try
            {
                var __type = doc.GetElement(__e.GetTypeId());
                if (__type != null) __tp = __type.get_Parameter(__bip);
            }
            catch { }
            if (__tp != null)
            {
                __exists = true;
                if (__tp.HasValue) { __p = __tp; __fromType = true; }
            }
        }
        if (__p == null || !__p.HasValue)
        {
            __counted = true;
            __BumpSection(__name, __exists ? 3 : 2);
            return;
        }
        if (__p.StorageType != StorageType.Integer)
        {
            __counted = true;
            __BumpSection(__name, 4);
            return;
        }
        __params[__name] = __p.AsInteger();
        __counted = true;
        __BumpSection(__name, __fromType ? 1 : 0);
    }
    catch { if (!__counted) __BumpSection(__name, 5); }
};
Action<Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutIdParam = (__e, __bip, __name, __params) =>
{
    try
    {
        var __p = __Parameter(__e, __bip);
        if (__p != null && __p.StorageType == StorageType.ElementId)
        {
            var __id = __p.AsElementId();
            if (__id != null && __id != ElementId.InvalidElementId)
                __params[__name] = __id.ToString();
        }
    }
    catch { }
};
Action<Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutIntParam = (__e, __bip, __name, __params) =>
{
    try
    {
        var __p = __Parameter(__e, __bip);
        if (__p != null && __p.StorageType == StorageType.Integer)
            __params[__name] = __p.AsInteger();
    }
    catch { }
};
Action<Element, Dictionary<string, object>> __PutParams = (__e, __row) =>
{
    var __params = new Dictionary<string, object>();
    __PutLengthParam(__e, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
                     "WALL_USER_HEIGHT_PARAM", __params);
    // audit F6: vertical wall attributes.  WALL_BASE_OFFSET (length, mm) and
    // WALL_HEIGHT_TYPE (the attached top-constraint level's id; __PutIdParam
    // skips InvalidElementId, so an unconnected wall carries neither key).
    // Additive: params is the open per-element dictionary, frozen L0 1.0
    // schema untouched.
    __PutLengthParam(__e, BuiltInParameter.WALL_BASE_OFFSET,
                     "WALL_BASE_OFFSET", __params);
    __PutIdParam(__e, BuiltInParameter.WALL_HEIGHT_TYPE,
                 "WALL_HEIGHT_TYPE", __params);
    // Wall-fidelity (live A5 evidence 2026-07-21): WALL_TOP_OFFSET is a
    // DEFINING degree of freedom of an attached wall.  Unread, the rebuild
    // derives height as the full base->top span (emitter forced offset 0) and
    // every attached wall missed canon by exactly |top offset| (observed
    // -300/-400/-2100mm on «демо»).  Additive length param, same discipline
    // as WALL_BASE_OFFSET.
    __PutLengthParam(__e, BuiltInParameter.WALL_TOP_OFFSET,
                     "WALL_TOP_OFFSET", __params);
    // P1 DOF-completeness (fidelity audit 2026-07-21, Находка B): vertical
    // defining DOF of columns / floors / beams — the same class the wall's
    // top_offset belonged to.  Pull-only (lift ignores unread keys): this is
    // the EVIDENCE step — offline stats over a fresh L0 decide which lift/emit
    // chains are material.  All Put* helpers skip absent params, so every
    // category stays byte-compatible.
    __PutIdParam(__e, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
                 "FAMILY_BASE_LEVEL_PARAM", __params);
    __PutIdParam(__e, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM,
                 "FAMILY_TOP_LEVEL_PARAM", __params);
    __PutLengthParam(__e, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
                     "FAMILY_BASE_LEVEL_OFFSET_PARAM", __params);
    __PutLengthParam(__e, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM,
                     "FAMILY_TOP_LEVEL_OFFSET_PARAM", __params);
    __PutIntParam(__e, BuiltInParameter.SLANTED_COLUMN_TYPE_PARAM,
                  "SLANTED_COLUMN_TYPE_PARAM", __params);
    // A wall is a location CURVE plus the rule saying which plane of the wall
    // that curve is (centreline, core centreline, or one of four faces).  Two
    // walls with identical endpoints and identical types occupy DIFFERENT
    // space when the rule differs -- by half the thickness, 100mm for the
    // 200mm types LOT31 is full of.  Unread, the round trip compares curves,
    // the curves match, and a wall standing 100mm away is recorded `exact`:
    // twenty times the 5mm endpoint tolerance, and a metric lying in its own
    // favour.  An enum ordinal, so Int and never Length -- reading it as a
    // length would unit-convert it into a plausible wrong number.
    __PutIntParam(__e, BuiltInParameter.WALL_KEY_REF_PARAM,
                  "WALL_KEY_REF_PARAM", __params);
    __PutLengthParam(__e, BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM,
                     "FLOOR_HEIGHTABOVELEVEL_PARAM", __params);
    // Потолочное смещение — СВОЁ имя, а не floor-овское: имя параметра здесь
    // часть тождества категории. `_lift_ceiling` (lift.py:1787) читало
    // CEILING_HEIGHTABOVELEVEL_PARAM, которого захват не клал НИКОГДА, и
    // каждый потолок поднимался на отметке уровня. Не отказом — молчаливым
    // нулём, худшим из двух исходов, названных ведомостью захвата. Тот же
    // род расхождения, что стоил 2153 помещений: производитель поля и его
    // потребитель договорились комментарием, а не контрактом.
    __PutLengthParam(__e, BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM,
                     "CEILING_HEIGHTABOVELEVEL_PARAM", __params);
    __PutIntParam(__e, BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL,
                  "FLOOR_PARAM_IS_STRUCTURAL", __params);
    __PutLengthParam(__e, BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION,
                     "STRUCTURAL_BEAM_END0_ELEVATION", __params);
    __PutLengthParam(__e, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION,
                     "STRUCTURAL_BEAM_END1_ELEVATION", __params);
    __PutIntParam(__e, BuiltInParameter.Z_JUSTIFICATION,
                  "Z_JUSTIFICATION", __params);
    __PutLengthParam(__e, BuiltInParameter.Z_OFFSET_VALUE,
                     "Z_OFFSET_VALUE", __params);
    // СЕЧЕНИЯ — все одиннадцать через __PutSectionParam, который сам падает
    // на ТИП элемента (толщина стены живёт на WallType, а не на стене) и
    // ОСТАВЛЯЕТ КВИТАНЦИЮ о причине пропуска (ревью кодекса №12). Имена
    // сверены по RevitAPI.xml (ref/net8.0) — в частности WALL_ATTR_WIDTH_PARAM,
    // а НЕ WALL_ATTR_WIDTH: члена с таким именем в перечислении нет вовсе.
    // Без этих чисел клеш-детектор строит только габаритные боксы (замер D1
    // на фасаде SOB6.2: exact=0 из 2754 оболочек).
    // R3 красных: RBS_PIPE_DIAMETER_PARAM — это "Diameter", то есть НОМИНАЛ.
    // У ДУ100 он 100 мм при наружном 114.3: капсула радиуса 50 не содержит
    // тела радиуса 57.15, и клеш пропускается в паре MVP. Наружный —
    // отдельный параметр, и снимать надо ОБА: номинал остаётся квитанцией
    // «наружного не нашлось», а не молчаливой заменой ему.
    __PutSectionParam(__e, BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                     "RBS_PIPE_DIAMETER_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
                     "RBS_PIPE_OUTER_DIAMETER", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
                     "RBS_CURVE_DIAMETER_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
                     "RBS_CURVE_WIDTH_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
                     "RBS_CURVE_HEIGHT_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,
                     "WALL_ATTR_WIDTH_PARAM", __params);
    // Замер v18: WALL_CROSS_SECTION не снят НИ У ОДНОЙ из 2360 стен, и
    // именно поэтому призма по одной толщине остаётся запрещённой (ревью
    // №10): отличить vertical от slanted/tapered нечем.
    __PutSectionIntParam(__e, BuiltInParameter.WALL_CROSS_SECTION,
                     "WALL_CROSS_SECTION", __params);
    // ПРИСОЕДИНЕНИЕ верха/низа стены. Замер v19: у присоединённой стены
    // реальная высота НЕ равна WALL_USER_HEIGHT_PARAM (8234565: параметр
    // 7970 мм при настоящих 9755 мм), а присоединение к КРЫШЕ не описывается
    // даже отметкой верхнего уровня. Признак структурный и универсальный —
    // никаких имён типов и семейств. Квитанция ОБЩАЯ с сечениями.
    __PutSectionIntParam(__e, BuiltInParameter.WALL_TOP_IS_ATTACHED,
                     "WALL_TOP_IS_ATTACHED", __params);
    __PutSectionIntParam(__e, BuiltInParameter.WALL_BOTTOM_IS_ATTACHED,
                     "WALL_BOTTOM_IS_ATTACHED", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
                     "RBS_CABLETRAY_WIDTH_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
                     "RBS_CABLETRAY_HEIGHT_PARAM", __params);
    // "Diameter(Trade Size)" — номинал прямым текстом в API.
    __PutSectionParam(__e, BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
                     "RBS_CONDUIT_DIAMETER_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
                     "RBS_CONDUIT_OUTER_DIAM_PARAM", __params);
    __PutSectionParam(__e, BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH,
                     "STRUCTURAL_SECTION_COMMON_WIDTH", __params);
    __PutSectionParam(__e, BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT,
                     "STRUCTURAL_SECTION_COMMON_HEIGHT", __params);
    __PutSectionParam(__e, BuiltInParameter.STRUCTURAL_SECTION_COMMON_DIAMETER,
                     "STRUCTURAL_SECTION_COMMON_DIAMETER", __params);
    __PutLengthParam(__e, BuiltInParameter.FAMILY_WIDTH_PARAM,
                     "FAMILY_WIDTH_PARAM", __params);
    __PutLengthParam(__e, BuiltInParameter.FAMILY_HEIGHT_PARAM,
                     "FAMILY_HEIGHT_PARAM", __params);
    __PutLengthParam(__e, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM,
                     "INSTANCE_SILL_HEIGHT_PARAM", __params);
    __PutIdParam(__e, BuiltInParameter.STAIRS_BASE_LEVEL_PARAM,
                 "STAIRS_BASE_LEVEL_PARAM", __params);
    __PutIdParam(__e, BuiltInParameter.STAIRS_TOP_LEVEL_PARAM,
                 "STAIRS_TOP_LEVEL_PARAM", __params);
    __row["params"] = __params;
};
Action<Element, Dictionary<string, object>> __PutGroupingState = (__e, __row) =>
{
    __row["design_option"] = null;
    __row["phase_created"] = null;
    __row["workset"] = null;
    try
    {
        var __option = __e.DesignOption;
        if (__option != null)
            __row["design_option"] = new Dictionary<string, object> {
                {"id", __option.Id.ToString()}, {"name", __option.Name ?? ""}
            };
    }
    catch { }
    try
    {
        var __phaseId = __e.CreatedPhaseId;
        if (__phaseId != null && __phaseId != ElementId.InvalidElementId)
        {
            var __phase = doc.GetElement(__phaseId) as Phase;
            if (__phase != null)
                __row["phase_created"] = new Dictionary<string, object> {
                    {"id", __phase.Id.ToString()}, {"name", __phase.Name ?? ""}
                };
        }
    }
    catch { }
    try
    {
        if (doc.IsWorkshared)
        {
            var __workset = doc.GetWorksetTable().GetWorkset(__e.WorksetId);
            if (__workset != null)
                __row["workset"] = new Dictionary<string, object> {
                    {"id", __workset.Id.ToString()}, {"name", __workset.Name ?? ""}
                };
        }
    }
    catch { }
};
""".strip()


_METADATA_CS = r"""
Func<double, double> __MM = (__value) =>
    UnitUtils.ConvertFromInternalUnits(__value, UnitTypeId.Millimeters);
long __RoomAfter = __ROOM_AFTER__;
Func<XYZ, double[]> __VecMM = (__p) => new double[] {
    __MM(__p.X), __MM(__p.Y), __MM(__p.Z)
};
Func<string, object> __Text = (__value) =>
    String.IsNullOrWhiteSpace(__value) ? null : (object)__value;
var __result = new Dictionary<string, object>();
__result["doc_name"] = String.IsNullOrWhiteSpace(__src.Title) ? "(untitled)" : __src.Title;
__result["revit_version"] = __src.Application.VersionNumber;
__result["units"] = "mm";

var __levels = new List<object>();
foreach (Level __level in new FilteredElementCollector(__src)
         .OfClass(typeof(Level)).WhereElementIsNotElementType()
         .Cast<Level>().OrderBy(__x => __x.Elevation)
         .ThenBy(__x => __x.Id.ToString()))
{
    __levels.Add(new Dictionary<string, object> {
        {"id", __level.Id.ToString()},
        {"name", __level.Name ?? ""},
        {"elevation_mm", __MM(__level.ProjectElevation)}
    });
}
__result["levels"] = __levels;

var __grids = new List<object>();
foreach (Grid __grid in new FilteredElementCollector(__src)
         .OfClass(typeof(Grid)).WhereElementIsNotElementType()
         .Cast<Grid>().OrderBy(__x => __x.Id.ToString()))
{
    var __curve = __grid.Curve;
    if (__curve == null)
        throw new InvalidOperationException(
            "Grid " + __grid.Id.ToString() + " has no curve");
    __grids.Add(new Dictionary<string, object> {
        {"id", __grid.Id.ToString()},
        {"name", __grid.Name ?? ""},
        {"p0_mm", __VecMM(__curve.GetEndPoint(0))},
        {"p1_mm", __VecMM(__curve.GetEndPoint(1))}
    });
}
__result["grids"] = __grids;

var __rooms = new List<object>();
var __boundaryOptions = new SpatialElementBoundaryOptions();
var __roomPage = new FilteredElementCollector(__src)
    .OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType()
    .Cast<Autodesk.Revit.DB.Architecture.Room>()
    .Where(__x => long.Parse(__x.Id.ToString()) > __RoomAfter)
    .OrderBy(__x => long.Parse(__x.Id.ToString()))
    .Take(__ROOM_TAKE__)
    .ToList();
bool __roomsHaveMore = __roomPage.Count > __ROOM_BATCH__;
if (__roomsHaveMore)
    __roomPage.RemoveRange(
        __ROOM_BATCH__, __roomPage.Count - __ROOM_BATCH__);
foreach (Autodesk.Revit.DB.Architecture.Room __room in __roomPage)
{
    var __roomRow = new Dictionary<string, object>();
    __roomRow["id"] = __room.Id.ToString();
    __roomRow["name"] = __room.Name ?? "";
    __roomRow["level_id"] = null;
    __roomRow["level_name"] = null;
    try
    {
        var __level = __room.Level;
        if (__level != null)
        {
            __roomRow["level_id"] = __level.Id.ToString();
            __roomRow["level_name"] = __level.Name ?? "";
        }
    }
    catch { }
    double __roomArea = UnitUtils.ConvertFromInternalUnits(
        __room.Area, UnitTypeId.SquareMeters);
    __roomRow["area_m2"] = __roomArea;

    var __loopsOut = new List<object>();
    var __boundaryIds = new List<object>();
    var __seenBoundaryIds = new HashSet<string>();
    // Area==0 is Revit's ordinary unplaced/unbounded-room state.  A placed
    // room, by contrast, must not become a plausible empty boundary merely
    // because an API read failed.
    if (__roomArea > 0.0)
    {
        var __loops = __room.GetBoundarySegments(__boundaryOptions);
        if (__loops == null || __loops.Count == 0)
            throw new InvalidOperationException(
                "Placed room " + __room.Id.ToString() +
                " has no readable boundary");
        foreach (var __loop in __loops)
        {
            var __points = new List<object>();
            foreach (var __segment in __loop)
            {
                var __point = __segment.GetCurve().GetEndPoint(0);
                __points.Add(new double[] {
                    __MM(__point.X), __MM(__point.Y)
                });
                var __boundaryId = __segment.ElementId;
                if (__boundaryId != null &&
                    __boundaryId != ElementId.InvalidElementId)
                {
                    string __id = __boundaryId.ToString();
                    if (__seenBoundaryIds.Add(__id))
                        __boundaryIds.Add(__id);
                }
            }
            __loopsOut.Add(__points);
        }
    }
    __roomRow["boundary_loops_mm"] = __loopsOut;
    __roomRow["boundary_mm"] =
        __loopsOut.Count > 0 ? __loopsOut[0] : new List<object>();
    __roomRow["bounding_element_ids"] = __boundaryIds;
    __rooms.Add(__roomRow);
}
__result["rooms"] = __rooms;
__result["rooms_has_more"] = __roomsHaveMore;
__result["rooms_next_cursor"] = (
    __roomsHaveMore && __roomPage.Count > 0
    ? (object)__roomPage[__roomPage.Count - 1].Id.ToString()
    : null);

var __project = new Dictionary<string, object>();
__project["name"] = null;
__project["address"] = null;
__project["building_type_hint"] = null;
try
{
    var __info = __src.ProjectInformation;
    if (__info != null)
    {
        __project["name"] = __Text(__info.Name);
        __project["address"] = __Text(__info.Address);
    }
}
catch { }
__result["project_info"] = __project;

Func<string, string> __Discipline = (__name) =>
{
    string __upper = (__name ?? "").ToUpperInvariant();
    // БЕЗ Regex, и это не вкусовщина. Замер 04.08 на живом устройстве:
    // голое `Regex` -> CS0103, полное имя -> CS1069 «type has been forwarded
    // to assembly 'System'».
    //
    // ПРИЧИНА ОДНА, А НЕ ДВЕ (первая редакция этого комментария была неверна
    // и списывала CS0103 на usings): обёртку излучаемого кода строит СЕРВЕР
    // (`bridge_protocol._WRAPPER_HEADER`), клиент своего списка не имеет
    // вовсе — `CodeCompiler` сам себя описывает как «receives pre-wrapped
    // code from server», и все шесть копий обёртки одинаковы и все включают
    // `System.Text.RegularExpressions`. Значит оба отказа — про ОТСУТСТВУЮЩУЮ
    // ССЫЛКУ: на .NET Framework 4.8 `Regex` живёт в `System.dll`, которой нет
    // в замыкании РАЗВЁРНУТОГО у пользователя плагина (в HEAD она есть —
    // расхождение между деревом и установленным бинарником, а не внутри
    // дерева). Там же `Stopwatch` и `Stack<T>` — итого 24 места, все найдены
    // одним проходом переписи после того, как три из них нашлись живьём.
    //
    // Разбор по индексам требует только String/Char: `Char.IsLetterOrDigit`
    // покрывает те же категории Unicode, что `[^\p{L}\p{Nd}]+` в обратную.
    // Сторож класса — `tests/bridge_reference_closure.py`, профиль `deployed`.
    var __tokens = new HashSet<string>();
    int __tokStart = -1;
    for (int __tokI = 0; __tokI <= __upper.Length; __tokI++)
    {
        bool __tokIn = __tokI < __upper.Length
            && Char.IsLetterOrDigit(__upper[__tokI]);
        if (__tokIn) { if (__tokStart < 0) __tokStart = __tokI; }
        else if (__tokStart >= 0)
        {
            __tokens.Add(__upper.Substring(__tokStart, __tokI - __tokStart));
            __tokStart = -1;
        }
    }
    if (__tokens.Contains("ОВ") || __tokens.Contains("HVAC") ||
        __tokens.Contains("MECH")) return "mechanical";
    if (__tokens.Contains("ВК") || __tokens.Contains("PLUMB"))
        return "plumbing";
    if (__tokens.Contains("ЭОМ") || __tokens.Contains("ЭЛ") ||
        __tokens.Contains("ELECT")) return "electrical";
    if (__tokens.Contains("КР") || __tokens.Contains("КЖ") ||
        __tokens.Contains("STRUCT")) return "structural";
    if (__tokens.Contains("АР") || __tokens.Contains("ARCH"))
        return "architectural";
    return "unknown";
};
// ── Рабочие наборы ──────────────────────────────────────────────────────
// ЗАМЕР 27.07 (тренировочная модель ЭОМ, SKLNK R2026): модель открыли с 17
// закрытыми наборами из 18, и `FilteredElementCollector` честно вернул то,
// что видел, — 11 элементов в 3D-видах вместо 2016. Извлечение при этом
// прошло бы БЕЗ ЕДИНОГО ПРИЗНАКА неполноты, и покрытие, посчитанное по
// такому L0, описывало бы диалог открытия файла, а не компилятор.
//
// Молчаливо-неполное чтение неотличимо от полного — ровно тот исход,
// который этот компилятор объявляет невыразимым на записи. Значит и на
// чтении состояние наборов обязано ехать в паспорт, а не подразумеваться.
var __worksets = new List<object>();
bool __worksharing = false;
int __worksetsClosed = 0;
try
{
    __worksharing = __src.IsWorkshared;
    if (__worksharing)
    {
        foreach (Workset __ws in new FilteredWorksetCollector(__src)
                 .OfKind(WorksetKind.UserWorkset))
        {
            var __wsRow = new Dictionary<string, object>();
            // Идентификатор берётся строкой: числовой аксессор ElementId
            // нестабилен между версиями Revit, и правило одно для ВСЕХ
            // идентификаторов — иначе пришлось бы помнить исключения.
            // Инвариант проверяет подстроку во всей эмиссии, поэтому её
            // нельзя даже упоминать в комментарии (проверено падением).
            __wsRow["id"] = __ws.Id.ToString();
            __wsRow["name"] = __ws.Name ?? "";
            __wsRow["open"] = __ws.IsOpen;
            if (!__ws.IsOpen) __worksetsClosed++;
            __worksets.Add(__wsRow);
        }
    }
}
catch { }
__result["worksharing"] = __worksharing;
__result["worksets"] = __worksets;
__result["worksets_closed"] = __worksetsClosed;

var __links = new List<object>();
foreach (RevitLinkInstance __link in new FilteredElementCollector(__src)
         .OfClass(typeof(RevitLinkInstance))
         .WhereElementIsNotElementType()
         .Cast<RevitLinkInstance>().OrderBy(__x => __x.Id.ToString()))
{
    var __linkRow = new Dictionary<string, object>();
    string __name = __link.Name ?? "";
    __linkRow["element_id"] = __link.Id.ToString();
    __linkRow["name"] = __name;
    __linkRow["loaded"] = false;
    __linkRow["element_count"] = null;
    __linkRow["bbox_min_mm"] = null;
    __linkRow["bbox_max_mm"] = null;
    __linkRow["discipline"] = __Discipline(__name);
    var __linkedDocument = __link.GetLinkDocument();
    if (__linkedDocument != null)
    {
        __linkRow["loaded"] = true;
        try
        {
            __linkRow["element_count"] =
                new FilteredElementCollector(__linkedDocument)
                .WhereElementIsNotElementType().GetElementCount();
        }
        catch { }
    }
    try
    {
        var __bbox = __link.get_BoundingBox(null);
        if (__bbox != null)
        {
            __linkRow["bbox_min_mm"] = __VecMM(__bbox.Min);
            __linkRow["bbox_max_mm"] = __VecMM(__bbox.Max);
        }
    }
    catch { }
    __links.Add(__linkRow);
}
__result["links"] = __links;

// ── Перепись документа (§18.1) ──────────────────────────────────────────
// Таблица категорий закрыта (47 штук), и всё, чего в ней нет — топография,
// площадка, паркинг, озеленение, массы, арматура, изоляция, — не давало НИ
// ЭЛЕМЕНТА, НИ СТРОКИ СТАТУСА, НИ ОТКАЗА. Знаменатель покрытия был выборкой
// таблицы, а не документом.
//
// Перепись — ОДИН проход, без геометрии и без параметров: только счётчик на
// категорию, поэтому дёшева даже на полумиллионе элементов и исполняется
// ВСЕГДА. Ключ — BuiltInCategory (§18.5: локализованное имя категории
// допустимо лишь как справочная колонка, ключом правила ему быть нельзя).
// Enum.GetName зовётся один раз на КАТЕГОРИЮ, а не на элемент.
//
// DirectShape/ImportInstance отражены здесь ровно так же, как их берут
// коллекторы таблицы (по классу, а не по категории) — иначе тождество
// «перепись = прочитано + не читалось» не сходилось бы по построению и
// показывало бы непрочитанным то, что прочитано.
var __censusCounts = new Dictionary<string, int>();
var __censusNames = new Dictionary<string, string>();
var __censusKeyByCatId = new Dictionary<string, string>();
long __censusTotal = 0;
bool __censusWanted = (__RoomAfter == -9223372036854775808L);
if (__censusWanted)
{
    foreach (Element __any in new FilteredElementCollector(__src)
             .WhereElementIsNotElementType())
    {
        __censusTotal++;
        string __key = "__CENSUS_NO_CATEGORY__";
        if (__any is DirectShape)
        {
            __key = "DirectShape";
        }
        else if (__any is ImportInstance)
        {
            __key = "ImportInstance";
        }
        else
        {
            Category __anyCat = null;
            try { __anyCat = __any.Category; } catch { }
            if (__anyCat != null)
            {
                string __catId = __anyCat.Id.ToString();
                if (!__censusKeyByCatId.TryGetValue(__catId, out __key))
                {
                    string __enumName = null;
                    long __catNumeric = 0;
                    if (Int64.TryParse(__catId, out __catNumeric))
                    {
                        try
                        {
                            __enumName = Enum.GetName(
                                typeof(BuiltInCategory),
                                (BuiltInCategory)__catNumeric);
                        }
                        catch { }
                    }
                    __key = String.IsNullOrEmpty(__enumName)
                        ? ("category_id:" + __catId) : __enumName;
                    __censusKeyByCatId[__catId] = __key;
                    string __localized = "";
                    try { __localized = __anyCat.Name ?? ""; } catch { }
                    if (!__censusNames.ContainsKey(__key))
                        __censusNames[__key] = __localized;
                }
            }
        }
        __censusCounts[__key] = __censusCounts.ContainsKey(__key)
            ? __censusCounts[__key] + 1 : 1;
    }
}
if (__censusWanted)
{
    var __census = new List<object>();
    foreach (var __censusPair in __censusCounts.OrderBy(__x => __x.Key))
        __census.Add(new Dictionary<string, object> {
            {"key", __censusPair.Key},
            {"name", __censusNames.ContainsKey(__censusPair.Key)
                ? __censusNames[__censusPair.Key] : ""},
            {"count", __censusPair.Value}
        });
    __result["census"] = __census;
    __result["census_total"] = __censusTotal;
}
else
{
    // Страница комнат №2+ переписи НЕ ПОВТОРЯЕТ: документ между страницами
    // неизменен (ревизия сторожится), и платить полным проходом за каждую
    // страницу значило бы делать закон дорогим ровно там, где модель велика.
    __result["census"] = null;
    __result["census_total"] = null;
}
return __result;
""".strip()


def _source_binding_cs(link_title: str | None) -> str:
    """Чей документ мы читаем: хозяин или его СВЯЗЬ.

    Связанные документы уже открыты в сессии (замер 30.07 на Snowdon:
    ``Application.Documents.Size == 5``), и ``GetLinkDocument()`` отдаёт готовый
    ``Document``. Поэтому чтение связи не требует ОТКРЫВАТЬ ничего: достаточно
    строить коллекторы против неё, а не против хозяина. Окном связь открыть мы
    всё равно не можем — ``UIApplication.OpenAndActivateDocument`` запрещён
    изнутри обработчика события (документировано Autodesk, проверено живьём:
    вызов вернул null, не бросив исключения).

    Каждая связь снимается СВОИМ слепком со своим штампом, поэтому ни
    составные ключи, ни федеративная перепись не нужны: для всего, что ниже,
    это просто ещё один документ.

    ОГОВОРКА, КОТОРУЮ НЕЛЬЗЯ ПРЯТАТЬ: ревизионный страж отпечатывает документ
    ХОЗЯИНА. Правка внутри связи хозяйскую ревизию не меняет, значит на чтении
    связи страж concurrent-правку НЕ ПОЙМАЕТ. Пока это так, слепок связи —
    честное чтение без охраны от одновременного редактирования, и говорить о
    нём надо именно так.

    ТЕКСТ ЖИВЁТ В ОДНОМ МЕСТЕ (``side_contract.source_binding_cs``), потому
    что с 30.07 его эмитируют не только страницы категорий, но и КАЖДАЯ
    боковая стадия. Вторая копия означала бы вторую правду о том, какой
    документ читается, а закон «одно тело — один документ» проверяется по
    ТЕКСТУ эмиссии: копии разошлись бы молча и оставили проверку зелёной.
    """
    return source_binding_cs(link_title)


def _collector_cs(spec: CategorySpec, variable: str = "__query") -> str:
    code = (
        f"System.Collections.Generic.IEnumerable<Element> {variable} = "
        f"new FilteredElementCollector(__src){spec.collector_cs}"
        ".WhereElementIsNotElementType().Cast<Element>();"
    )
    if spec.exclude_direct_shape:
        code += (
            f"\n{variable} = {variable}.Where("
            "__e => !(__e is DirectShape));"
        )
    return code


def build_metadata_cs(*, after_room_id: int | None = None,
                      link_title: str | None = None) -> str:
    """Return one version-safe document-metadata/room-boundary page.

    §18.1: перепись документа едет в ЭТОМ же теле — отдельным round-trip'ом
    она стоила бы лишнего хода на каждую модель (латентность здесь измеряется
    числом раундов, не байтами), а её результат нужен ровно там же, где
    остальной заголовок. Считается она только на ПЕРВОЙ странице комнат.
    """

    after = (
        "-9223372036854775808L"
        if after_room_id is None else f"{after_room_id}L")
    return (
        # Метаданные и ПЕРЕПИСЬ обязаны считаться по тому же документу,
        # что и элементы: иначе перепись мерила бы хозяина, а элементы
        # приходили бы из связи — и закон переписи поймал бы это как
        # расхождение, не назвав причины.
        _source_binding_cs(link_title) + "\n" + _METADATA_CS
        .replace("__ROOM_AFTER__", after, 1)
        .replace("__ROOM_TAKE__", str(EXTRACT_BATCH + 1))
        .replace("__ROOM_BATCH__", str(EXTRACT_BATCH))
        .replace("__CENSUS_NO_CATEGORY__", NO_CATEGORY_KEY)
    )


def build_category_probe_cs(category: str, *,
                            link_title: str | None = None) -> str:
    """Build the count/level-scope probe for one fixed category."""

    spec = _SPEC_BY_NAME.get(category)
    if spec is None:
        raise ValueError(f"unknown extraction category: {category!r}")
    return "\n".join((
        _COMMON_HELPERS_CS,
        _source_binding_cs(link_title),
        _collector_cs(spec),
        r"""
var __counts = new Dictionary<string, int>();
int __total = 0;
foreach (var __element in __query)
{
    __total++;
    string __key = __LevelKey(__element);
    __counts[__key] = __counts.ContainsKey(__key)
        ? __counts[__key] + 1 : 1;
}
var __scopes = new List<object>();
foreach (var __pair in __counts.OrderBy(__x => __x.Key))
    __scopes.Add(new Dictionary<string, object> {
        {"key", __pair.Key}, {"count", __pair.Value}
    });
return new Dictionary<string, object> {
    {"count", __total}, {"levels", __scopes}
};
""".strip(),
    ))


def _csharp_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def build_category_batch_cs(
    category: str,
    *,
    level_scope: str = "__all__",
    after_element_id: int | None = None,
    link_title: str | None = None,
) -> str:
    """Build one deterministic page (at most ``EXTRACT_BATCH`` rows)."""

    spec = _SPEC_BY_NAME.get(category)
    if spec is None:
        raise ValueError(f"unknown extraction category: {category!r}")
    after = (
        "-9223372036854775808L"
        if after_element_id is None else f"{after_element_id}L")
    category_literal = _csharp_string(category)
    scope_literal = _csharp_string(level_scope)
    body = f"""
string __Category = {category_literal};
string __Scope = {scope_literal};
long __After = {after};
var __page = __query
    .Where(__e => __Id(__e) > __After &&
        (__Scope == "__all__" || __LevelKey(__e) == __Scope))
    .OrderBy(__e => __Id(__e))
    .Take({EXTRACT_BATCH + 1})
    .ToList();
bool __hasMore = __page.Count > {EXTRACT_BATCH};
if (__hasMore) __page.RemoveRange({EXTRACT_BATCH},
                                  __page.Count - {EXTRACT_BATCH});
var __rows = new List<object>();
foreach (var __element in __page)
{{
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __element.Id.ToString();
    __row["category"] = __Category;
    __row["category_ru"] = "";
    try
    {{
        if (__element.Category != null && __element.Category.Name != null)
            __row["category_ru"] = __element.Category.Name;
    }}
    catch {{ }}
    __row["type_id"] = "";
    __row["type_name"] = "";
    try
    {{
        var __typeId = __element.GetTypeId();
        if (__typeId != null && __typeId != ElementId.InvalidElementId)
        {{
            __row["type_id"] = __typeId.ToString();
            var __type = doc.GetElement(__typeId);
            if (__type != null && __type.Name != null)
                __row["type_name"] = __type.Name;
        }}
    }}
    catch {{ }}
    __row["level_id"] = null;
    __row["level_name"] = null;
    var __level = __ElementLevel(__element);
    if (__level != null)
    {{
        __row["level_id"] = __level.Id.ToString();
        __row["level_name"] = __level.Name ?? "";
    }}
    __row["host_id"] = null;
    try
    {{
        var __familyInstance = __element as FamilyInstance;
        if (__familyInstance != null && __familyInstance.Host != null)
            __row["host_id"] = __familyInstance.Host.Id.ToString();
    }}
    catch {{ }}
    __PutParams(__element, __row);
    __PutGroupingState(__element, __row);
    __PutGeometry(__element, __row);
    __rows.Add(__row);
}}
object __next = null;
if (__hasMore && __page.Count > 0)
    __next = __page[__page.Count - 1].Id.ToString();
// Квитанции сечений (ревью кодекса №12). Порядок ЗАДАН сортировкой, а не
// порядком словаря: два прогона обязаны давать один отчёт.
var __receipts = new List<object>();
foreach (var __kv in __sectionReceipts.OrderBy(__x => __x.Key))
    __receipts.Add(new Dictionary<string, object> {{
        {{"parameter", __kv.Key}},
        {{"instance_hit", __kv.Value[0]}},
        {{"type_hit", __kv.Value[1]}},
        {{"not_applicable", __kv.Value[2]}},
        {{"no_value", __kv.Value[3]}},
        {{"wrong_storage", __kv.Value[4]}},
        {{"exception", __kv.Value[5]}}
    }});
return new Dictionary<string, object> {{
    {{"elements", __rows}},
    {{"has_more", __hasMore}},
    {{"next_cursor", __next}},
    {{"section_receipts", __receipts}}
}};
""".strip()
    return "\n".join((
        _COMMON_HELPERS_CS,
        _source_binding_cs(link_title),
        _ELEMENT_HELPERS_CS,
        GEOMETRY_HELPER_CS,
        _collector_cs(spec),
        body,
    ))


@dataclass(frozen=True, slots=True)
class _Scope:
    key: str
    count: int


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    output_path: Path
    checkpoint_path: Path
    element_count: int
    completed_categories: tuple[str, ...]
    partial_categories: tuple[str, ...]
    resumed: bool
    #: Разбивка ВРЕМЕНИ по категориям, ключ — имя категории (см.
    #: :func:`_timing_totals` о том, что здесь разделяется, а что нет).
    #: Пустой словарь у резюма завершённого потока: там ничего не читали.
    timing: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


#: ГРАНИЦА ЗАМЕРА, ОБЪЯВЛЕННАЯ СЛОВАМИ.
#:
#: ``bridge_ms`` — один неделимый отсюда отрезок. Внутри него лежат, по
#: порядку: отправка в вебсокет, ожидание UI-потока Revit, компиляция тела C#
#: Roslyn'ом, работа коллектора Revit API, сериализация ответа в JSON на
#: стороне плагина, обратный транспорт и ``json.loads`` в нашем процессе.
#: РАЗДЕЛИТЬ ИХ ИЗ ПИТОНА НЕЛЬЗЯ: плагин не возвращает собственного времени
#: (Stopwatch есть только в ContextCollector и IFCExporter — это другие пути,
#: не путь декомпайла). Кто захочет разделить — обязан добавить отсчёт В
#: ПЛАГИН, и это отдельная волна.
#:
#: Что ЗАМЕРЯЕТСЯ раздельно и честно:
#:   ``probe_ms``  — дешёвый вызов пробы (count + max id) той же категории.
#:                   У него та же постоянная цена вызова (транспорт + Roslyn +
#:                   попадание в UI-поток), но почти нет сбора и сериализации.
#:                   Поэтому ``probe_ms/вызов`` — ВЕРХНЯЯ ОЦЕНКА постоянной
#:                   цены одного обращения к мосту, а ``bridge_ms/pages``
#:                   минус она — нижняя оценка полезной работы Revit.
#:                   Верхняя, а не точная: проба тоже гоняет коллектор.
#:   ``parse_ms``  — НАШ разбор страницы в типы (``_parse_page``).
#:   ``write_ms``  — НАША запись строк в L0.jsonl вместе с ``fsync``.
#:   ``bytes``     — сколько L0 прибавил на этой категории (прокси размера
#:                   ответа: ответ мы уже разобрали, повторно сериализовать
#:                   его ради размера дороже, чем сам замер).
_TIMING_KEYS = ("probe_ms", "bridge_ms", "parse_ms", "write_ms")


def _new_timing_slot() -> dict[str, float]:
    return {"probe_ms": 0.0, "bridge_ms": 0.0, "parse_ms": 0.0,
            "write_ms": 0.0, "pages": 0.0, "bytes": 0.0, "elements": 0.0}


def _timing_totals(
    timing: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """Свернуть покатегорийную разбивку в итог прогона.

    ``bridge_ms`` НЕ делится дальше — см. ``_TIMING_KEYS`` выше.  ``our_ms``
    (parse+write) и ``bridge_ms`` — это ровно та граница, которая решает
    вопрос «наши оптимизации вообще имеют смысл»: если ``bridge_ms``
    подавляет, лечится только чтением МЕНЬШЕГО, а не более быстрым питоном.
    """

    out: dict[str, float] = {key: 0.0 for key in _TIMING_KEYS}
    out.update({"pages": 0.0, "bytes": 0.0, "elements": 0.0})
    for slot in timing.values():
        for key in out:
            out[key] += float(slot.get(key) or 0.0)
    out["our_ms"] = out["parse_ms"] + out["write_ms"]
    out["bridge_ms_share"] = (
        round(out["bridge_ms"] / (out["bridge_ms"] + out["our_ms"]), 4)
        if (out["bridge_ms"] + out["our_ms"]) > 0 else 0.0)
    return {key: round(value, 3) for key, value in out.items()}


@dataclass(frozen=True, slots=True)
class ExtractProgress:
    """Один доклад о пройденной категории — ровно то, что уже легло на диск.

    Замер 30.07 на живой башне: извлечение шло 41 минуту, L0 дорос до 88 МБ и
    закрылся футером, а спрашивающий «как там прогон» всё это время получал
    ``stage=open_model_profile, done 0/0``. Отличить «идёт нормально» от
    «повисло на первой странице» было нельзя ничем, кроме размера файла.

    Доклад ставится ПОСЛЕ записи чекпойнта, а не до: он обязан описывать
    состояние, которое уже переживёт падение процесса. Доклад о том, что
    только собираются сделать, — это обещание, а не прогресс.
    """

    category: str
    #: Значение :class:`~kukai.ir.decompile.schema.CategoryState` строкой.
    #: Вердикт категории — часть прогресса: PARTIAL, о котором узнают только
    #: в конце, обесценивает весь доклад.
    category_state: str
    categories_done: int
    categories_total: int
    #: Элементов, уже закоммиченных в поток (не «ожидается», а «лежит»).
    elements: int


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtractionProtocolError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ExtractionProtocolError(f"{field_name} keys must be strings")
    return dict(value)


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExtractionProtocolError(f"{field_name} must be an array")
    return value


def _require_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExtractionProtocolError(
            f"{field_name} must be an integer >= {minimum}")
    return value


#: Группа кодов конверта (``kukai.llm.envelope.ErrCode``), означающая, что
#: НАШ текст не стал сборкой. Сверяется ПРЕФИКСОМ: группа закрытая и растёт
#: (``compile.cs_error``, ``compile.failed_after_repairs``), а перечислять её
#: членов здесь значило бы завести второй словарь о том же понятии.
_TEMPLATE_COMPILE_ERR_PREFIX = "compile."


def _envelope_failure_detail(row: Mapping[str, Any]) -> str:
    """Человеческая причина отказа из конверта — НИКОГДА не голое ``True``.

    Порядок неслучаен. ``error`` в конверте бывает и строкой, и БУЛЕВЫМ
    флагом; ``str(True)`` — это не причина, а потеря причины, и именно её
    видел оператор вместо ``CS1503 ... (line 103)``. Строка берётся оттуда,
    где она есть, а флаг не выдаётся за текст.
    """
    for key in ("message", "error"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    err = row.get("err")
    if isinstance(err, Mapping):
        code = err.get("code")
        if isinstance(code, str) and code:
            return code
    return "bridge refused"


def _raise_envelope_failure(row: Mapping[str, Any]) -> None:
    """Отказ конверта — типизированный по ЕГО ЖЕ коду, а не по догадке."""
    detail = _envelope_failure_detail(row)[:240]
    err = row.get("err")
    code = err.get("code") if isinstance(err, Mapping) else None
    if isinstance(code, str) and code.startswith(_TEMPLATE_COMPILE_ERR_PREFIX):
        raise TemplateCompileError(detail)
    raise ExtractionProtocolError(detail)


def _unwrap_bridge_payload(value: Any) -> Any:
    """Unwrap the serving pipeline envelope without guessing at plain rows."""

    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            _raise_envelope_failure(current)
        if "result" not in current:
            break
        current = current["result"]
    if (isinstance(current, Mapping)
            and current.get("error") not in (None, False)):
        _raise_envelope_failure(current)
    return current


#: Паузы между попытками страницы. Мгновенный ретрай (sleep(0)) бил в ещё
#: МЁРТВЫЙ сокет: обрыв сети рвёт мост кодом 1006, окно возвращается с новым
#: ws_id через секунды — ретраю надо ДОЖДАТЬСЯ переподключения, а не
#: израсходовать бюджет за миллисекунды (замер 29.07, К2 РД: три прогона).
#: Чтения идемпотентны, каждая страница под ревизионным стражем — ждать
#: безопасно по построению.
EXTRACT_RETRY_BACKOFF_S: tuple[float, ...] = (5.0, 20.0)


async def _execute_with_retries(
    executor: BridgeExecutor,
    code: str,
    *,
    timeout_ms: int,
    retries: int,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            call = executor(code, timeout_ms=timeout_ms)
            raw = await asyncio.wait_for(
                call, timeout=max(timeout_ms / 1000.0, 0.001))
            return _unwrap_bridge_payload(raw)
        except asyncio.CancelledError:
            raise
        except DocumentRevisionError:
            # A retry would merely choose another revision and make a mixed
            # snapshot look successful.  Revision drift is a run-level typed
            # refusal, never a transport failure within the retry budget.
            raise
        except TemplateCompileError:
            # НАШ шаблон не собрался. Второй такой же вызов пошлёт тот же
            # текст тому же Roslyn и получит тот же CS-код: ретрай здесь не
            # «лишняя попытка», а гарантированно бесполезная. Летит мимо
            # бюджета ретраев И мимо ожидания окна (см. класс) — ровно так
            # же, как ревизия документа.
            raise
        except Exception as exc:  # bridge/protocol failures share retry budget
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(EXTRACT_RETRY_BACKOFF_S[
                    min(attempt, len(EXTRACT_RETRY_BACKOFF_S) - 1)])
    assert last_error is not None
    detail = f"{type(last_error).__name__}: {last_error}"[:240]
    raise BridgeCallError(
        f"bridge round-trip failed after {retries + 1} attempts: {detail}"
    ) from last_error


class _WindowWaitBudget:
    """Общий на ПРОГОН запас ожидания вернувшегося окна (задача #26).

    Бюджет ретраев страницы терпит ~25 с. Реальный обрыв длится дольше:
    сеть рвётся, мост умирает 1006, окно возвращается с НОВЫМ ws_id через
    секунды-минуты (замер 29.07, К2 РД). Хоронить категорию через 25 секунд
    значит выбросить извлечение целой модели из-за перезагрузки роутера.

    Запас ОБЩИЙ, а не попостраничный: попостраничный множился бы на число
    страниц, и закрытое навсегда окно стоило бы часы мнимой работы. Здесь
    мёртвое окно стоит `EXTRACT_WINDOW_WAIT_S` ровно один раз на прогон.

    Безопасность по построению: чтения идемпотентны, каждая страница идёт
    под ревизионным стражем. Если за время обрыва документ изменился,
    страж поднимет DocumentRevisionError — типизированный отказ ПРОГОНА, и
    это правильный исход, а не повод для ещё одной попытки.
    """

    __slots__ = ("_remaining", "spent", "waits")

    def __init__(self, total_s: float | None = None) -> None:
        # Константы читаются В РАНТАЙМЕ, а не защёлкиваются в значении по
        # умолчанию: иначе переопределение через окружение не подействовало бы
        # ни на импортированный модуль, ни на тест, а «настройка, которая не
        # настраивает» — худший вид настройки.
        total = EXTRACT_WINDOW_WAIT_S if total_s is None else total_s
        self._remaining = max(0.0, float(total))
        self.spent = 0.0
        self.waits = 0

    @property
    def remaining(self) -> float:
        return self._remaining

    async def pause(self, poll_s: float | None = None) -> bool:
        """Подождать перед следующей попыткой; False — запас исчерпан."""

        if self._remaining <= 0.0:
            return False
        poll = EXTRACT_WINDOW_POLL_S if poll_s is None else poll_s
        slice_s = min(float(poll), self._remaining)
        await asyncio.sleep(slice_s)
        self._remaining -= slice_s
        self.spent += slice_s
        self.waits += 1
        return True


async def _execute_awaiting_window(
    executor: BridgeExecutor,
    code: str,
    *,
    timeout_ms: int,
    retries: int,
    budget: _WindowWaitBudget,
    what: str,
) -> Any:
    """Вызов страницы, переживающий уход окна на минуты.

    Ретраи внутри ``_execute_with_retries`` остаются транспортными; когда их
    бюджет сгорел, здесь начинается ОЖИДАНИЕ: пауза — повтор — пауза, пока
    не вернётся окно или не кончится общий запас прогона.

    Ни одного нового пути «тихого успеха»: наружу отдаётся только то, что
    вернул мост. Исчерпанный запас — по-прежнему ``BridgeCallError``, просто
    с честным упоминанием, сколько ждали (текст уходит в причину partial).
    ``DocumentRevisionError`` сюда не попадает — ``_execute_with_retries``
    поднимает его мимо retry-бюджета, и мимо ожидания он летит так же.

    ЖДЁТСЯ ТОЛЬКО МОЛЧАНИЕ ОКНА. ``TemplateCompileError`` — второй отказ,
    летящий мимо: «мост молчит» и «мы не смогли собрать то, что собирались
    послать» — разные состояния, и второе не лечится временем. Пока они были
    одним, разбор башни на R2023 полтора часа писал «окно не отвечает» про
    живое окно и наш собственный CS1503.
    """

    while True:
        try:
            return await _execute_with_retries(
                executor, code, timeout_ms=timeout_ms, retries=retries)
        except BridgeCallError as exc:
            if not await budget.pause():
                raise BridgeCallError(
                    f"{exc} | окно не вернулось за "
                    f"{budget.spent:.0f} с ожидания ({what})") from exc
            logger.warning(
                "[extract] окно не отвечает на %s — ждём возвращения "
                "(потрачено %.0f с, осталось %.0f, ожидание №%d)",
                what, budget.spent, budget.remaining, budget.waits)


def _parse_census(row: dict[str, Any]) -> list[Any]:
    """Проверить контракт переписи и вернуть её строки (§18.1/§18.2).

    Мост присылает и строки, и собственный итог. Их расхождение — не повод
    «взять то, что похоже на правду»: перепись существует, чтобы быть
    знаменателем, и знаменатель, посчитанный из усечённого ответа, врал бы
    тише и опаснее, чем отсутствие ответа.
    """
    census = row.pop("census", None)
    total = row.pop("census_total", None)
    if census is None:
        if total is not None:
            raise ExtractionProtocolError(
                "metadata.census_total is present without metadata.census")
        return []
    rows = _require_list(census, "metadata.census")
    declared = _require_int(total, "metadata.census_total")
    counted = 0
    for index, entry in enumerate(rows):
        item = _require_mapping(entry, f"metadata.census[{index}]")
        counted += _require_int(
            item.get("count"), f"metadata.census[{index}].count")
    if counted != declared:
        raise ExtractionProtocolError(
            f"metadata.census rows sum to {counted}, "
            f"but census_total says {declared}")
    return rows


def _parse_metadata(value: Any, change_stamp: str) -> L0Document:
    row = _require_mapping(value, "metadata")
    row.pop("rooms_has_more", None)
    row.pop("rooms_next_cursor", None)
    if "links" not in row:
        raise ExtractionProtocolError(
            "metadata is missing required links array")
    links = _require_list(row.pop("links"), "metadata.links")
    census = _parse_census(row)
    document = {
        **row,
        "change_stamp": change_stamp,
        "elements": [],
        "category_status": [],
        "links": links,
        "census": census,
    }
    try:
        return L0Document.from_dict(document)
    except L0SchemaError as exc:
        raise ExtractionProtocolError(f"invalid metadata: {exc}") from exc


def _parse_metadata_page(
    value: Any,
    change_stamp: str,
    *,
    after_room_id: int | None,
) -> tuple[L0Document, bool, int | None]:
    row = _require_mapping(value, "metadata")
    has_more = row.get("rooms_has_more")
    if not isinstance(has_more, bool):
        raise ExtractionProtocolError(
            "metadata.rooms_has_more must be boolean")
    raw_cursor = row.get("rooms_next_cursor")
    if has_more:
        if not isinstance(raw_cursor, str) or not raw_cursor:
            raise ExtractionProtocolError(
                "paged room metadata requires rooms_next_cursor")
        try:
            cursor = int(raw_cursor)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "metadata room cursor must be a numeric element id") from exc
        if after_room_id is not None and cursor <= after_room_id:
            raise ExtractionProtocolError(
                "metadata room cursor did not advance")
    else:
        if raw_cursor is not None:
            raise ExtractionProtocolError(
                "final room metadata page must have null cursor")
        cursor = None
    document = _parse_metadata(row, change_stamp)
    if len(document.rooms) > EXTRACT_BATCH:
        raise ExtractionProtocolError(
            f"metadata room page exceeds EXTRACT_BATCH={EXTRACT_BATCH}")
    room_ids: list[int] = []
    for room in document.rooms:
        try:
            room_ids.append(int(room.id))
        except ValueError as exc:
            raise ExtractionProtocolError(
                "Revit room id must be numeric") from exc
    if room_ids != sorted(room_ids) or len(room_ids) != len(set(room_ids)):
        raise ExtractionProtocolError(
            "metadata room ids must be unique and sorted")
    if has_more and not room_ids:
        raise ExtractionProtocolError(
            "empty room metadata page cannot claim has_more")
    if has_more and room_ids[-1] != cursor:
        raise ExtractionProtocolError(
            "room metadata cursor must equal its last room id")
    if after_room_id is not None and room_ids and room_ids[0] <= after_room_id:
        raise ExtractionProtocolError(
            "room metadata page repeated an emitted room")
    return document, has_more, cursor


def _parse_probe(value: Any) -> tuple[int, tuple[_Scope, ...]]:
    row = _require_mapping(value, "category probe")
    total = _require_int(row.get("count"), "category probe.count")
    levels = _require_list(row.get("levels"), "category probe.levels")
    parsed: list[_Scope] = []
    seen: set[str] = set()
    for index, raw_scope in enumerate(levels):
        scope = _require_mapping(raw_scope, f"category probe.levels[{index}]")
        key = scope.get("key")
        if not isinstance(key, str) or not key:
            raise ExtractionProtocolError(
                f"category probe.levels[{index}].key must be non-empty")
        if key in seen:
            raise ExtractionProtocolError(
                f"duplicate category probe level scope {key!r}")
        seen.add(key)
        count = _require_int(
            scope.get("count"), f"category probe.levels[{index}].count")
        if count:
            parsed.append(_Scope(key, count))
    if sum(scope.count for scope in parsed) != total:
        raise ExtractionProtocolError(
            "category probe level counts do not equal total count")
    if total <= EXTRACT_BATCH:
        return total, ((_Scope("__all__", total),) if total else ())
    return total, tuple(parsed)


#: Одиннадцать параметров сечения, читаемых с квитанцией. Список ЗАКРЫТ:
#: страница, не приславшая строку по каждому из них, отвергается — иначе
#: «сечения нет» снова станет неотличимо от «перестали спрашивать».
SECTION_PARAM_NAMES: tuple[str, ...] = (
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_PIPE_OUTER_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "WALL_ATTR_WIDTH_PARAM",
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_CROSS_SECTION",
    "WALL_TOP_IS_ATTACHED",
)


def _parse_section_receipts(
    value: Any,
    *,
    interrogated: int,
) -> tuple[SectionReceipt, ...]:
    """Квитанции одной страницы -> кортеж, отсортированный по параметру.

    Ревью кодекса №12. Проверяется ровно то, отсутствие чего делает пропуск
    сечения неотличимым от отказа чтения: (а) квитанции ЕСТЬ, (б) параметров
    ровно столько, сколько мы спрашивали, (в) сумма шести исходов каждого
    параметра равна числу опрошенных элементов страницы.
    """
    if value is None:
        raise ExtractionProtocolError(
            "category page has no section_receipts: fail-open чтения сечений "
            "снова стал молчаливым (ревью №12)")
    rows = _require_list(value, "category page.section_receipts")
    receipts: list[SectionReceipt] = []
    for index, raw in enumerate(rows):
        try:
            receipts.append(SectionReceipt.from_dict(raw))
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid section receipt at index {index}: {exc}") from exc
    names = tuple(sorted(r.parameter for r in receipts))
    if len(set(names)) != len(names):
        raise ExtractionProtocolError(
            "section receipts repeat a parameter")
    if interrogated and names != SECTION_PARAM_NAMES:
        missing = sorted(set(SECTION_PARAM_NAMES) - set(names))
        extra = sorted(set(names) - set(SECTION_PARAM_NAMES))
        raise ExtractionProtocolError(
            f"квитанции сечений не покрывают закрытый список параметров: "
            f"не хватает {missing}, лишние {extra}")
    if not interrogated and receipts:
        raise ExtractionProtocolError(
            "пустая страница никого не опрашивала, а квитанции прислала")
    for receipt in receipts:
        if receipt.total() != interrogated:
            raise ExtractionProtocolError(
                f"перепись сечений не сходится: {receipt.parameter} опросил "
                f"{receipt.total()} элементов, на странице {interrogated}")
    return tuple(sorted(receipts, key=lambda r: r.parameter))


def _parse_page(
    value: Any,
    *,
    category: str,
    scope: _Scope,
    after_element_id: int | None,
) -> tuple[tuple[L0Element, ...], bool, int | None, tuple[SectionReceipt, ...]]:
    row = _require_mapping(value, "category page")
    raw_elements = _require_list(row.get("elements"), "category page.elements")
    if len(raw_elements) > EXTRACT_BATCH:
        raise ExtractionProtocolError(
            f"category page exceeds EXTRACT_BATCH={EXTRACT_BATCH}")
    has_more = row.get("has_more")
    if not isinstance(has_more, bool):
        raise ExtractionProtocolError(
            "category page.has_more must be boolean")
    raw_cursor = row.get("next_cursor")
    if has_more:
        if not isinstance(raw_cursor, str) or not raw_cursor:
            raise ExtractionProtocolError(
                "paged category response requires next_cursor")
        try:
            next_cursor = int(raw_cursor)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "category page.next_cursor must be a numeric element id") from exc
        if after_element_id is not None and next_cursor <= after_element_id:
            raise ExtractionProtocolError(
                "category page cursor did not advance")
    else:
        if raw_cursor is not None:
            raise ExtractionProtocolError(
                "final category page must have null next_cursor")
        next_cursor = None

    elements: list[L0Element] = []
    ids: list[int] = []
    for index, raw_element in enumerate(raw_elements):
        element_row = _require_mapping(
            raw_element, f"category page.elements[{index}]")
        try:
            geometry = parse_geometry(element_row)
            element_row.update(geometry.to_element_fields())
            element = L0Element.from_dict(element_row)
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid {category} element at page index {index}: {exc}"
            ) from exc
        if element.category != category:
            raise ExtractionProtocolError(
                f"element category {element.category!r} does not match "
                f"collector {category!r}")
        if scope.key == "__none__" and element.level_id is not None:
            raise ExtractionProtocolError(
                f"{category} element escaped no-level scope")
        if scope.key not in ("__all__", "__none__") \
                and element.level_id != scope.key:
            raise ExtractionProtocolError(
                f"{category} element escaped level scope {scope.key!r}")
        try:
            numeric_id = int(element.element_id)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "Revit element_id must be numeric") from exc
        ids.append(numeric_id)
        elements.append(element)
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ExtractionProtocolError(
            "category page element ids must be unique and sorted")
    if has_more and not elements:
        raise ExtractionProtocolError(
            "empty category page cannot claim has_more")
    if has_more and ids[-1] != next_cursor:
        raise ExtractionProtocolError(
            "category page cursor must equal its last element id")
    if after_element_id is not None and ids and ids[0] <= after_element_id:
        raise ExtractionProtocolError(
            "category page repeated an already-emitted element")
    receipts = _parse_section_receipts(
        row.get("section_receipts"), interrogated=len(elements))
    return tuple(elements), has_more, next_cursor, receipts


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ExtractionProtocolError(
            f"record is not valid JSON data: {exc}") from exc
    return text.encode("utf-8") + b"\n"


def _write_record(handle: Any, value: Mapping[str, Any]) -> None:
    handle.write(_json_bytes(value))


def _sync_file(handle: Any) -> int:
    handle.flush()
    os.fsync(handle.fileno())
    return handle.tell()


@dataclass(frozen=True, slots=True)
class _StreamMark:
    """Где кончается категория в потоке и сколько элементов она дала."""

    category: str
    state: str
    extracted_count: int
    offset_after: int


def _scan_stream_ledger(output: Path) -> tuple[int, tuple[_StreamMark, ...]]:
    """``(смещение после шапки, отметки по категориям)`` — читая сам поток.

    Смещения НЕ хранятся в чекпойнте намеренно: поток и так их содержит, а
    дублирование завело бы второй источник правды о том, где кончается
    категория, — расходись он с файлом, отмотка резала бы по мнимой границе.
    Здесь граница читается оттуда же, где записана.

    Файл построчный, поэтому смещение — сумма длин строк; ``_write_record``
    другого разделителя не знает.
    """

    header_offset = 0
    marks: list[_StreamMark] = []
    seen_header = False
    with output.open("rb") as handle:
        offset = 0
        for line in handle:
            offset += len(line)
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ExtractionProtocolError(
                    f"L0 stream has an unreadable record at {offset}") from exc
            kind = row.get("record")
            if kind == "header":
                seen_header = True
                header_offset = offset
            elif kind == "link":
                if not seen_header:
                    raise ExtractionProtocolError("L0 link precedes the header")
                header_offset = offset
            elif kind == "category_status":
                status = row.get("status") or {}
                marks.append(_StreamMark(
                    category=str(status.get("category")),
                    state=str(status.get("state")),
                    extracted_count=int(status.get("extracted_count") or 0),
                    offset_after=offset,
                ))
    if not seen_header:
        raise ExtractionProtocolError("L0 stream has no header record")
    return header_offset, tuple(marks)


def _rewind_to_first_partial(
    output: Path,
    state: dict[str, Any],
    checkpoint: Path,
) -> bool:
    """Отмотать поток к ПЕРВОЙ незавершённой категории (задача #27).

    Сегодня резюм с уже написанным футером возвращает результат как есть, и
    partial-категории уходят вниз по течению как «снимок неавторитетен» —
    оператору остаётся полный прогон под новым штампом (замер: попытки 2-3
    k2_ar_rd_v1 умирали мгновенно). Partial при резюме — это РАБОТА.

    ПОЧЕМУ ОТМОТКА, А НЕ ВТОРОЙ ФУТЕР И НЕ ЛАТАНИЕ ХВОСТА. Дописать заново
    извлечённую категорию в конец нельзя: её прежние (неполные) элементы уже
    лежат в потоке, и рядом с новыми они дали бы ДУБЛИ, которых читатель не
    отличит. Второй футер с приоритетом лечил бы только счётчик и оставил бы
    дубли на месте, а заодно сделал бы «последний футер побеждает» вторым
    законом рядом с ``stream_complete``. Отмотка сохраняет формат ровно
    таким, каким он объявлен: ОДИН header, категории в фиксированном
    порядке, ОДИН футер последним и с настоящим счётчиком. Цена — категории
    после первой незавершённой извлекаются заново; это минуты против часов
    полного прогона, и это честные минуты.

    Возвращает True, если отмотка была (есть что доизвлекать).
    """

    states = dict(state["category_states"])
    first_partial = next(
        (category for category in EXTRACT_CATEGORIES
         if states.get(category) == CategoryState.PARTIAL.value), None)
    if first_partial is None:
        return False

    header_offset, marks = _scan_stream_ledger(output)
    by_category = {mark.category: mark for mark in marks}
    # Поток и чекпойнт обязаны говорить одно и то же о том, что закончено.
    # Расхождение — не повод «выбрать более полный»: обе стороны описывают
    # ОДИН прогон, и если они спорят, неизвестно, какая граница настоящая.
    for category, value in states.items():
        mark = by_category.get(category)
        if mark is not None and mark.state != value:
            raise ExtractionProtocolError(
                f"checkpoint says {category} is {value}, stream says "
                f"{mark.state}")

    index = EXTRACT_CATEGORIES.index(first_partial)
    kept = list(EXTRACT_CATEGORIES[:index])
    if kept:
        previous = by_category.get(kept[-1])
        if previous is None:
            raise ExtractionProtocolError(
                f"L0 stream has no category_status for {kept[-1]}")
        rewind_offset = previous.offset_after
    else:
        rewind_offset = header_offset
    element_count = sum(
        by_category[category].extracted_count
        for category in kept if category in by_category)

    with output.open("r+b") as handle:
        handle.truncate(rewind_offset)
    state.update({
        "committed_offset": rewind_offset,
        "processed_categories": kept,
        "category_states": {
            category: value for category, value in states.items()
            if category in kept},
        "element_count": element_count,
        # Футер СНЯТ вместе с хвостом: заново он будет написан в конце
        # доизвлечения, с настоящим счётчиком. `stream_complete` остаётся
        # законом — просто сейчас поток честно НЕ полон.
        "footer_written": False,
    })
    _atomic_write_json(checkpoint, state)
    logger.info(
        "[extract] резюм: отмотка к %s (оставлено %d категорий, %d элементов, "
        "смещение %d) — доизвлекаем",
        first_partial, len(kept), element_count, rewind_offset)
    return True


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(_json_bytes(value))
        _sync_file(handle)
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _checkpoint_template(change_stamp: str, output_path: Path) -> dict[str, Any]:
    return {
        "schema_version": L0_SCHEMA_VERSION,
        # Поколение таблицы, которой ведётся ЭТОТ прогон. Чекпойнты, снятые
        # до версионирования (все 55 на диске 29.07), этого ключа не несут —
        # и его отсутствие значит «поколение не названо», а не «поколение
        # сегодняшнее»; разбор — в ``_load_checkpoint``.
        "dialect": L0_DIALECT_VERSION,
        #: Поколения, под которыми писались куски этого потока, по порядку.
        #: Один элемент — поток однороден; больше одного — резюм пересёк бамп
        #: таблицы, и это обязано быть НАПИСАНО, а не выведено задним числом.
        "dialect_history": [L0_DIALECT_VERSION],
        "change_stamp": change_stamp,
        "output_path": str(output_path.resolve()),
        "committed_offset": 0,
        "header_written": False,
        "footer_written": False,
        "processed_categories": [],
        "category_states": {},
        "element_count": 0,
        "link_count": 0,
    }


def _load_checkpoint(
    path: Path,
    *,
    change_stamp: str,
    output_path: Path,
) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionProtocolError(
            f"cannot read checkpoint {path}: {exc}") from exc
    row = _require_mapping(raw, "checkpoint")
    if row.get("schema_version") != L0_SCHEMA_VERSION:
        raise ExtractionProtocolError("checkpoint schema version mismatch")
    if row.get("change_stamp") != change_stamp:
        raise ExtractionProtocolError(
            "checkpoint change_stamp differs; refusing stale resume")
    if row.get("output_path") != str(output_path.resolve()):
        raise ExtractionProtocolError("checkpoint output_path mismatch")
    offset = _require_int(
        row.get("committed_offset"), "checkpoint.committed_offset")
    header_written = row.get("header_written")
    footer_written = row.get("footer_written")
    if not isinstance(header_written, bool) or not isinstance(
            footer_written, bool):
        raise ExtractionProtocolError(
            "checkpoint header/footer flags must be boolean")
    processed = _require_list(
        row.get("processed_categories"), "checkpoint.processed_categories")
    if not all(isinstance(item, str) for item in processed):
        raise ExtractionProtocolError(
            "checkpoint.processed_categories must contain strings")
    if processed != list(EXTRACT_CATEGORIES[:len(processed)]):
        raise ExtractionProtocolError(
            "checkpoint categories are not a valid extraction prefix")
    states = _require_mapping(
        row.get("category_states"), "checkpoint.category_states")
    if set(states) != set(processed) or any(
            state not in (CategoryState.COMPLETE.value,
                          CategoryState.PARTIAL.value)
            for state in states.values()):
        raise ExtractionProtocolError(
            "checkpoint category states do not match processed categories")
    _require_int(row.get("element_count"), "checkpoint.element_count")
    _require_int(row.get("link_count"), "checkpoint.link_count")
    # ── ВОЗОБНОВЛЕНИЕ ЧЕРЕЗ БАМП ДИАЛЕКТА ───────────────────────────────
    #
    # ЧИТАТЬ И ДОПИСЫВАТЬ — РАЗНЫЕ ГЛАГОЛЫ, И ОТВЕТЫ У НИХ РАЗНЫЕ. Старый
    # целый слепок обязан ЧИТАТЬСЯ (ради этого и заведена лестница
    # поколений). Дописываться он не обязан, и вот граница:
    #
    # * ОБОРВАННЫЙ прогон (футера нет) — ПРОДОЛЖАЕМ. Дописка в хвост
    #   доказана тремя источниками, значит уже обработанные категории — те же
    #   строки с теми же индексами; цикл адресует категорию ИНДЕКСОМ
    #   (``EXTRACT_CATEGORIES[len(processed):]``), и при дописи в хвост ни
    #   один индекс не сдвинулся. Новые строки просто допишутся следом, и
    #   футер в конце скажет правду: все категории сегодняшней таблицы для
    #   этого ``change_stamp`` обойдены. Цена отказа была бы несоразмерной:
    #   прогон К2 РД — ~69 минут, и выбрасывать его из-за того, что таблица
    #   выросла между обрывом и повтором, значит наказывать за собственный
    #   рост.
    #
    # * ЗАКОНЧЕННЫЙ прогон (футер написан) старого поколения — ОТКАЗ. Не
    #   потому, что дописать технически нельзя, а потому, что ``stream_complete``
    #   — единственный закон этого контейнера. Поток, однажды сказавший «я
    #   полон», не вправе потом сказать «не полон, дописываюсь»: это не
    #   доизвлечение, а ретроактивная правка опубликованного факта, и любой
    #   потребитель, уже сославшийся на тот футер, оказался бы обманут
    #   задним числом. Отказ здесь ничего не стоит читателю: слепок
    #   по-прежнему открывается как своё поколение.
    #
    # ЧЕСТНО ЛИ СМЕШАННЫЙ СЛЕПОК. Да — при условии, что смешение НАЗВАНО.
    # Категории смешать нельзя (префикс), а вот ПОЛЯ можно: куски, снятые
    # разными сборками, отличаются наличием полей, дописанных между ними
    # (``curve_kind``, квитанции сечений). Но у дома на это уже есть закон:
    # отсутствие поля значит «не мерили», а не «ноль», — и он действует
    # ПОЗАПИСНО, поэтому смешанный поток остаётся разбираемым, а каждая
    # запись — правдивой о себе. Остаётся назвать смешение целиком: это
    # ``dialect_history`` в чекпойнте и в футере.
    #
    # ЧЕКПОЙНТ БЕЗ ПОЛЯ ``dialect`` — отдельный, ЧЕТВЁРТЫЙ случай, и он
    # массовый: на 29.07 таких 55 из 55. Поколение такого чекпойнта
    # невыводимо (7 обработанных категорий одинаково выглядят и как обрыв
    # поколения /1, и как обрыв поколения /6), поэтому оно так и называется —
    # ``unknown``. Продолжаем: отказать значило бы выбросить всю накопленную
    # незаконченную работу ради поля, которого в момент её записи не
    # существовало. Но в родословную попадает именно ``unknown``, а не
    # сегодняшняя версия: подставить её здесь было бы ровно тем молчаливым
    # додумыванием, ради запрета которого лестница и заведена.
    raw_dialect = row.get("dialect")
    if raw_dialect is not None:
        if not isinstance(raw_dialect, str):
            raise ExtractionProtocolError("checkpoint.dialect must be a string")
        try:
            dialect_by_version(raw_dialect)
        except L0SchemaError as exc:
            raise ExtractionProtocolError(f"checkpoint: {exc}") from exc
    if footer_written and processed != list(EXTRACT_CATEGORIES):
        raise ExtractionProtocolError(
            f"checkpoint is a FINISHED stream of dialect "
            f"{raw_dialect or 'unknown'} ({len(processed)} categories); "
            f"today's dialect is {L0_DIALECT_VERSION} "
            f"({len(EXTRACT_CATEGORIES)} categories). A committed footer is "
            f"never re-opened — the snapshot still reads as its own "
            f"generation; extract afresh to get the added categories")
    history = row.get("dialect_history")
    if history is None:
        history = [raw_dialect or "unknown"]
    elif (not isinstance(history, list)
            or not all(isinstance(item, str) for item in history)):
        raise ExtractionProtocolError(
            "checkpoint.dialect_history must contain strings")
    if history[-1] != L0_DIALECT_VERSION:
        logger.warning(
            "[extract] резюм ПЕРЕСЁК бамп диалекта: поток начат под %s, "
            "продолжается под %s. Категории не смешиваются (дописка в "
            "хвост), поля — могут: в первых %d категориях полей, заведённых "
            "позже, НЕТ, и это значит «не мерили», а не «ноль». Родословная "
            "записана в футер.",
            history[-1], L0_DIALECT_VERSION, len(processed))
        history = [*history, L0_DIALECT_VERSION]
    row["dialect_history"] = history
    row["dialect"] = L0_DIALECT_VERSION
    if not header_written and (offset or processed):
        raise ExtractionProtocolError(
            "checkpoint has progress before its header commit")
    return row


def _safe_document_filename(doc_name: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", doc_name, flags=re.UNICODE).strip("._")
    return value or "untitled"


def _checkpoint_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".checkpoint.json")


async def _new_metadata(
    executor: BridgeExecutor,
    change_stamp: str,
    *,
    timeout_ms: int,
    retries: int,
    link_title: str | None = None,
) -> L0Document:
    room_cursor: int | None = None
    metadata: L0Document | None = None
    rooms: list[RoomInfo] = []
    while True:
        payload = await _execute_with_retries(
            executor, build_metadata_cs(after_room_id=room_cursor,
                                        link_title=link_title),
            timeout_ms=timeout_ms, retries=retries)
        page, has_more, next_cursor = _parse_metadata_page(
            payload, change_stamp, after_room_id=room_cursor)
        if metadata is None:
            metadata = page
        else:
            stable_first = (
                metadata.doc_name, metadata.revit_version, metadata.units,
                metadata.change_stamp, metadata.levels, metadata.grids,
                metadata.project_info, metadata.links,
            )
            stable_page = (
                page.doc_name, page.revit_version, page.units,
                page.change_stamp, page.levels, page.grids,
                page.project_info, page.links,
            )
            if stable_page != stable_first:
                raise ExtractionProtocolError(
                    "document metadata changed between room pages")
        rooms.extend(page.rooms)
        if not has_more:
            break
        room_cursor = next_cursor
    assert metadata is not None
    return L0Document(
        doc_name=metadata.doc_name,
        revit_version=metadata.revit_version,
        units=metadata.units,
        change_stamp=metadata.change_stamp,
        levels=metadata.levels,
        grids=metadata.grids,
        rooms=tuple(rooms),
        project_info=metadata.project_info,
        links=metadata.links,
        # §18.4: пересборка документа из страниц комнат обязана переносить
        # состояние рабочих наборов — иначе неполнота чтения умирает здесь,
        # между разбором ответа C# и записью заголовка.
        worksharing=metadata.worksharing,
        worksets=metadata.worksets,
        worksets_closed=metadata.worksets_closed,
        # §18.1: перепись считается на ПЕРВОЙ странице комнат и живёт в
        # ``metadata``; страницы 2+ возвращают null и не должны её стирать.
        census=metadata.census,
    )


def _read_header(path: Path) -> L0Document:
    try:
        with path.open("rb") as handle:
            raw_line = handle.readline()
    except OSError as exc:
        raise ExtractionProtocolError(
            f"cannot read L0 header from {path}: {exc}") from exc
    if not raw_line:
        raise ExtractionProtocolError("L0 stream has no header")
    try:
        row = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtractionProtocolError(f"invalid L0 header JSON: {exc}") from exc
    record = _require_mapping(row, "L0 header")
    if (record.get("record") != "header"
            or record.get("schema_version") != L0_SCHEMA_VERSION):
        raise ExtractionProtocolError("invalid L0 stream header")
    document = _require_mapping(record.get("document"), "L0 header.document")
    try:
        return L0Document.from_dict({
            **document, "elements": [], "category_status": [], "links": []})
    except L0SchemaError as exc:
        raise ExtractionProtocolError(f"invalid L0 header: {exc}") from exc


async def extract_document(
    executor: BridgeExecutor,
    *,
    change_stamp: str,
    output_path: str | os.PathLike[str] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    resume: bool = True,
    timeout_ms: int = EXTRACT_TIMEOUT_MS,
    retries: int = EXTRACT_RETRIES,
    window_budget: "_WindowWaitBudget | None" = None,
    on_progress: Callable[[ExtractProgress], None] | None = None,
    #: Читать не хозяина, а его СВЯЗЬ с таким Document.Title. Связанные
    #: документы уже открыты в сессии — открывать ничего не нужно. Слепок
    #: связи отдельный, со своим штампом: ниже по течению это просто ещё
    #: один документ, поэтому ни составных ключей, ни федеративной переписи
    #: не требуется.
    link_title: str | None = None,
) -> ExtractionResult:
    """Extract one document without retaining its element population in RAM.

    ``executor`` must execute a read-only C# body and accept ``timeout_ms`` as
    a keyword argument.  The caller/world-state owner supplies the document
    change stamp; resume refuses a different stamp rather than inventing one.
    """

    if not isinstance(change_stamp, str) or not change_stamp:
        raise ValueError("change_stamp must be a non-empty string")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) \
            or timeout_ms <= 0 or timeout_ms > EXTRACT_TIMEOUT_MS:
        raise ValueError(
            f"timeout_ms must be in 1..{EXTRACT_TIMEOUT_MS}")
    if isinstance(retries, bool) or not isinstance(retries, int) \
            or retries < 0 or retries > EXTRACT_RETRIES:
        raise ValueError(f"retries must be in 0..{EXTRACT_RETRIES}")

    metadata: L0Document | None = None
    if output_path is None:
        metadata = await _new_metadata(
            executor, change_stamp, timeout_ms=timeout_ms, retries=retries,
            link_title=link_title)
        # Читаем env КАЖДЫЙ раз: модуль импортируется один раз на процесс,
        # и запомненный на импорте корень нельзя переназначить конфигом.
        output = default_output_root() / (
            _safe_document_filename(metadata.doc_name) + "_L0.jsonl")
    else:
        output = Path(output_path)
    checkpoint = (
        Path(checkpoint_path) if checkpoint_path is not None
        else _checkpoint_path(output))
    if output.resolve() == checkpoint.resolve():
        raise ValueError("output_path and checkpoint_path must be different")
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    resumed = checkpoint.exists()
    if resumed:
        if not resume:
            raise ExtractionProtocolError(
                f"checkpoint already exists: {checkpoint}")
        state = _load_checkpoint(
            checkpoint, change_stamp=change_stamp, output_path=output)
    else:
        if output.exists():
            raise ExtractionProtocolError(
                f"output exists without a checkpoint; refusing overwrite: {output}")
        state = _checkpoint_template(change_stamp, output)
        _atomic_write_json(checkpoint, state)

    committed_offset = int(state["committed_offset"])
    if committed_offset:
        if not output.exists() or output.stat().st_size < committed_offset:
            raise ExtractionProtocolError(
                "checkpoint offset exceeds the existing output")
    elif state["header_written"]:
        raise ExtractionProtocolError(
            "header-written checkpoint cannot have zero offset")

    if state["footer_written"]:
        reader = L0JSONLReader(output)
        reader.validate()
        # PARTIAL ПРИ РЕЗЮМЕ — ЭТО РАБОТА, А НЕ ИТОГ (задача #27). Раньше
        # футер закрывал разговор: резюм отдавал снимок как есть, ниже по
        # течению он падал `snapshot_non_authoritative`, и оператору
        # оставался полный прогон под новым штампом. Теперь поток
        # отматывается к первой незавершённой категории, и обычный цикл
        # доизвлекает хвост.
        if _rewind_to_first_partial(output, state, checkpoint):
            resumed = True
            # Отмотка ПЕРЕПИСАЛА границу — локальная копия смещения устарела,
            # а ниже по ней усекается файл. Читаем заново из состояния,
            # которое только что стало правдой.
            committed_offset = int(state["committed_offset"])
        else:
            complete = tuple(
                category for category in EXTRACT_CATEGORIES
                if state["category_states"][category] ==
                CategoryState.COMPLETE.value)
            # Готовый поток заново не читают — отдаём разбивку ТОГО чтения,
            # которое его наполнило, а не пустую (иначе резюм завершённого
            # слепка выглядел бы как бесплатный).
            _done_timing = state.get("timing")
            return ExtractionResult(
                output, checkpoint, int(state["element_count"]),
                complete, (), resumed=True,
                timing=(dict(_done_timing)
                        if isinstance(_done_timing, Mapping) else {}))

    if state["header_written"]:
        metadata = _read_header(output)
        if metadata.change_stamp != change_stamp:
            raise ExtractionProtocolError(
                "L0 header change_stamp differs from checkpoint")
        with output.open("r+b") as handle:
            handle.truncate(committed_offset)
    else:
        if metadata is None:
            metadata = await _new_metadata(
                executor, change_stamp,
                timeout_ms=timeout_ms, retries=retries,
                link_title=link_title)
        with output.open("wb") as handle:
            _write_record(handle, {
                "record": "header",
                "schema_version": L0_SCHEMA_VERSION,
                "document": metadata.metadata_dict(),
            })
            for link in metadata.links:
                _write_record(handle, {
                    "record": "link", "link": link.to_dict()})
            committed_offset = _sync_file(handle)
        state["committed_offset"] = committed_offset
        state["header_written"] = True
        state["link_count"] = len(metadata.links)
        _atomic_write_json(checkpoint, state)

    processed = list(state["processed_categories"])
    category_states = dict(state["category_states"])
    element_count = int(state["element_count"])
    # Разбивка ПЕРЕЖИВАЕТ резюм: чекпойнты, снятые до этой волны, ключа не
    # несут, и его отсутствие значит «не мерили», а не «ноль миллисекунд».
    # Категории, дочитанные вторым заходом, дописываются к первым — сумма
    # тогда описывает РАБОТУ, а не один календарный отрезок.
    _prior_timing = state.get("timing")
    timing: dict[str, dict[str, float]] = (
        {str(key): {str(k): float(v) for k, v in dict(value).items()}
         for key, value in _prior_timing.items()}
        if isinstance(_prior_timing, Mapping) else {})
    # Запас ожидания окна ОДИН на прогон (см. _WindowWaitBudget): мёртвое
    # окно обязано стоить пять минут ровно один раз, а не пять минут на
    # каждую из полусотни категорий. Конвейер передаёт СВОЙ запас, чтобы
    # извлечение и боковые стадии тратили общий, а не по пять минут каждая.
    if window_budget is None:
        window_budget = _WindowWaitBudget()

    with output.open("r+b") as handle:
        handle.truncate(int(state["committed_offset"]))
        handle.seek(int(state["committed_offset"]))
        for category in EXTRACT_CATEGORIES[len(processed):]:
            expected_count: int | None = None
            extracted_count = 0
            error: str | None = None
            category_state = CategoryState.COMPLETE
            # Квитанции сечений копятся по КАТЕГОРИИ (ревью кодекса №12):
            # `parameter -> [шесть исходов]`. Агрегат страниц, а не элементов,
            # поэтому его размер не зависит от размера модели.
            receipt_slots: dict[str, list[int]] = {}
            # ПРИБОР. Часы заводятся ДО пробы и живут ровно одну категорию:
            # разбивка обязана пережить падение, поэтому она уезжает в
            # чекпойнт вместе со смещением, а не копится в памяти до конца
            # сорокаминутного чтения.
            slot_t = _new_timing_slot()
            _bytes_at_start = handle.tell()
            try:
                _t0 = time.monotonic()
                probe_payload = await _execute_awaiting_window(
                    executor,
                    build_category_probe_cs(category, link_title=link_title),
                    timeout_ms=timeout_ms, retries=retries,
                    budget=window_budget, what=f"проба {category}")
                slot_t["probe_ms"] += (time.monotonic() - _t0) * 1000.0
                expected_count, scopes = _parse_probe(probe_payload)
                for scope in scopes:
                    scope_count = 0
                    cursor: int | None = None
                    while True:
                        _t0 = time.monotonic()
                        page_payload = await _execute_awaiting_window(
                            executor,
                            build_category_batch_cs(
                                category, level_scope=scope.key,
                                after_element_id=cursor,
                                link_title=link_title),
                            timeout_ms=timeout_ms, retries=retries,
                            budget=window_budget,
                            what=(f"страница {category}"
                                  f" scope={scope.key!r} after={cursor}"))
                        _t1 = time.monotonic()
                        slot_t["bridge_ms"] += (_t1 - _t0) * 1000.0
                        slot_t["pages"] += 1.0
                        elements, has_more, next_cursor, receipts = _parse_page(
                            page_payload, category=category, scope=scope,
                            after_element_id=cursor)
                        _t2 = time.monotonic()
                        slot_t["parse_ms"] += (_t2 - _t1) * 1000.0
                        for receipt in receipts:
                            slots = receipt_slots.setdefault(
                                receipt.parameter, [0] * len(SECTION_RECEIPT_OUTCOMES))
                            for slot, name in enumerate(SECTION_RECEIPT_OUTCOMES):
                                slots[slot] += getattr(receipt, name)
                        for element in elements:
                            _write_record(handle, {
                                "record": "element",
                                "collector": category,
                                "element": element.to_dict(),
                            })
                            scope_count += 1
                            extracted_count += 1
                        slot_t["write_ms"] += (
                            time.monotonic() - _t2) * 1000.0
                        if not has_more:
                            break
                        cursor = next_cursor
                    if scope_count != scope.count:
                        raise ExtractionProtocolError(
                            f"{category} scope {scope.key!r} yielded "
                            f"{scope_count}, expected {scope.count}")
                if extracted_count != expected_count:
                    raise ExtractionProtocolError(
                        f"{category} yielded {extracted_count}, "
                        f"expected {expected_count}")
            except (BridgeCallError, ExtractionProtocolError) as exc:
                category_state = CategoryState.PARTIAL
                error = str(exc)[:240]

            section_receipts = tuple(
                SectionReceipt(parameter=name,
                               **dict(zip(SECTION_RECEIPT_OUTCOMES, slots)))
                for name, slots in sorted(receipt_slots.items()))
            try:
                status = CategoryStatus(
                    category=category,
                    state=category_state,
                    extracted_count=extracted_count,
                    expected_count=expected_count,
                    error=error,
                    # Закон переписи проверяется САМИМ типом: сумма шести
                    # исходов каждого параметра обязана равняться числу
                    # извлечённых элементов категории (ревью кодекса №12).
                    section_receipts=section_receipts,
                )
            except L0SchemaError as exc:
                raise ExtractionProtocolError(
                    f"{category}: {exc}") from exc
            _t3 = time.monotonic()
            _write_record(handle, {
                "record": "category_status", "status": status.to_dict()})
            committed_offset = _sync_file(handle)
            slot_t["write_ms"] += (time.monotonic() - _t3) * 1000.0
            slot_t["bytes"] = float(committed_offset - _bytes_at_start)
            slot_t["elements"] = float(extracted_count)
            timing[category] = {
                key: round(value, 3) for key, value in slot_t.items()}
            processed.append(category)
            category_states[category] = category_state.value
            element_count += extracted_count
            state.update({
                "committed_offset": committed_offset,
                "processed_categories": list(processed),
                "category_states": dict(category_states),
                "element_count": element_count,
                # Разбивка едет в чекпойнт, а не в L0: L0 — детерминированный
                # артефакт (I4), и настенное время в нём сделало бы два
                # одинаковых чтения побайтово разными.
                "timing": dict(timing),
            })
            _atomic_write_json(checkpoint, state)
            if on_progress is not None:
                # Сток прогресса — НАБЛЮДАТЕЛЬ, а не участник: сломанный
                # наблюдатель не имеет права уронить сорокаминутное чтение.
                # Тот же приём, что у status_cb в конвейере.
                try:
                    on_progress(ExtractProgress(
                        category=category,
                        category_state=category_state.value,
                        categories_done=len(processed),
                        categories_total=len(EXTRACT_CATEGORIES),
                        elements=element_count,
                    ))
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "extract: сток прогресса отказал на %s", category,
                        exc_info=True)

        _write_record(handle, {
            "record": "footer",
            "stream_complete": True,
            "element_count": element_count,
            "link_count": int(state["link_count"]),
            "category_count": len(processed),
            # Поколение называется ЯВНО, хотя читатель умеет вывести его из
            # ``category_count``: вывод держится на законе дописи в хвост, а
            # запись — ни на чём. Пусть будущий слепок отвечает сам за себя,
            # даже если закон когда-нибудь нарушат.
            "dialect": L0_DIALECT_VERSION,
            # Смешанная родословная резюма (см. ``_load_checkpoint``): под
            # какими поколениями писались более ранние куски этого потока.
            # Ключа нет, если поток писан одним поколением.
            **({"dialect_history": list(state["dialect_history"])}
               if len(state.get("dialect_history") or ()) > 1 else {}),
        })
        committed_offset = _sync_file(handle)

    state["committed_offset"] = committed_offset
    state["footer_written"] = True
    _atomic_write_json(checkpoint, state)
    complete = tuple(
        category for category in EXTRACT_CATEGORIES
        if category_states[category] == CategoryState.COMPLETE.value)
    partial = tuple(
        category for category in EXTRACT_CATEGORIES
        if category_states[category] == CategoryState.PARTIAL.value)
    return ExtractionResult(
        output, checkpoint, element_count, complete, partial, resumed,
        timing=timing)


@dataclass(frozen=True, slots=True)
class _TypedRecord:
    kind: str
    value: Any


class L0JSONLReader:
    """Streaming validator/parser for the Wave A JSONL container.

    Iterating elements keeps only one JSONL record in memory.  ``materialize``
    is intentionally explicit and reserved for tests or known-small models.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._dialect: L0Dialect | None = None

    def dialect(self) -> L0Dialect:
        """Поколение таблицы, которым снят ЭТОТ поток.

        Читателю этого мало для вопроса «полон ли слепок по сегодняшним
        меркам» — и правильно: ответ на него зависит от того, кто спрашивает.
        Здесь называется факт («снято таблицей из N категорий»), а вывод
        («значит, вот этих категорий у него нет») делает
        :func:`~kukai.ir.decompile.schema.categories_outside_dialect` у того,
        кому он нужен.
        """
        if self._dialect is None:
            self.validate()
        assert self._dialect is not None
        return self._dialect

    def _records(self) -> Iterator[_TypedRecord]:
        header_seen = False
        footer_seen = False
        element_count = 0
        link_count = 0
        status_count = 0
        current_category_count = 0
        category_started = False
        try:
            from kukai.ir.decompile.snapshot_io import open_snapshot
            handle = open_snapshot(self.path, "rb")
        except OSError as exc:
            raise ExtractionProtocolError(
                f"cannot open L0 stream {self.path}: {exc}") from exc
        with handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if footer_seen:
                    raise ExtractionProtocolError(
                        f"record after footer at line {line_number}")
                try:
                    raw = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ExtractionProtocolError(
                        f"invalid JSONL at line {line_number}: {exc}") from exc
                row = _require_mapping(raw, f"JSONL line {line_number}")
                kind = row.get("record")
                if not isinstance(kind, str):
                    raise ExtractionProtocolError(
                        f"missing record kind at line {line_number}")
                if not header_seen:
                    if kind != "header":
                        raise ExtractionProtocolError(
                            "first JSONL record must be header")
                    if row.get("schema_version") != L0_SCHEMA_VERSION:
                        raise ExtractionProtocolError(
                            "L0 schema version mismatch")
                    document = _require_mapping(
                        row.get("document"), "header.document")
                    try:
                        parsed = L0Document.from_dict({
                            **document, "elements": [],
                            "category_status": [], "links": []})
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid header document: {exc}") from exc
                    header_seen = True
                    yield _TypedRecord(kind, parsed)
                elif kind == "header":
                    raise ExtractionProtocolError("duplicate JSONL header")
                elif kind == "element":
                    collector = row.get("collector")
                    if collector not in _SPEC_BY_NAME:
                        raise ExtractionProtocolError(
                            f"unknown element collector {collector!r}")
                    if (status_count >= len(EXTRACT_CATEGORIES)
                            or collector != EXTRACT_CATEGORIES[status_count]):
                        raise ExtractionProtocolError(
                            "element collector is out of category order")
                    category_started = True
                    element_row = _require_mapping(
                        row.get("element"), "element record")
                    try:
                        geometry = parse_geometry(element_row)
                        element_row.update(geometry.to_element_fields())
                        parsed = L0Element.from_dict(element_row)
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid element record: {exc}") from exc
                    if parsed.category != collector:
                        raise ExtractionProtocolError(
                            "element category/collector mismatch")
                    element_count += 1
                    current_category_count += 1
                    yield _TypedRecord(kind, parsed)
                elif kind == "link":
                    if category_started or status_count:
                        raise ExtractionProtocolError(
                            "link record appears after category extraction began")
                    try:
                        parsed = LinkSummary.from_dict(row.get("link"))
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid link record: {exc}") from exc
                    link_count += 1
                    yield _TypedRecord(kind, parsed)
                elif kind == "category_status":
                    try:
                        parsed = CategoryStatus.from_dict(row.get("status"))
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid category status: {exc}") from exc
                    if (status_count >= len(EXTRACT_CATEGORIES)
                            or parsed.category !=
                            EXTRACT_CATEGORIES[status_count]):
                        raise ExtractionProtocolError(
                            "category status is missing, duplicate, or out of order")
                    if parsed.extracted_count != current_category_count:
                        raise ExtractionProtocolError(
                            "category status extracted_count does not match "
                            "streamed records")
                    category_started = True
                    status_count += 1
                    current_category_count = 0
                    yield _TypedRecord(kind, parsed)
                elif kind == "footer":
                    if row.get("stream_complete") is not True:
                        raise ExtractionProtocolError(
                            "footer does not mark stream_complete")
                    if _require_int(
                            row.get("element_count"),
                            "footer.element_count") != element_count:
                        raise ExtractionProtocolError(
                            "footer element count mismatch")
                    if _require_int(
                            row.get("link_count"),
                            "footer.link_count") != link_count:
                        raise ExtractionProtocolError(
                            "footer link count mismatch")
                    if _require_int(
                            row.get("category_count"),
                            "footer.category_count") != status_count:
                        raise ExtractionProtocolError(
                            "footer category count mismatch")
                    # ПОКОЛЕНИЕ, А НЕ «СТОЛЬКО ЖЕ, СКОЛЬКО СЕГОДНЯ». Раньше
                    # здесь стояло ``status_count != len(EXTRACT_CATEGORIES)``,
                    # и каждый рост таблицы обесценивал ВСЁ накопленное: 29.07
                    # (54 -> 73) разом перестали открываться 55 слепков, но
                    # так же молча обесценивали их и пять прошлых ростов —
                    # просто никто не пробовал открыть старое новым кодом.
                    #
                    # Проверка не ослабла, она стала точной. Строгий префикс
                    # по-прежнему требуется построчно выше (element/
                    # category_status сверяются с ``EXTRACT_CATEGORIES``
                    # позиционно), а здесь поток обязан закончиться на длине
                    # РЕАЛЬНО СУЩЕСТВОВАВШЕГО поколения. Свежая сборка иначе
                    # и не умеет: футер пишется после обхода всей таблицы, а
                    # отказавшая категория получает статус PARTIAL и всё
                    # равно считается, — поэтому для сегодняшних потоков это
                    # ровно прежнее требование «все 73».
                    try:
                        self._dialect = resolve_dialect(
                            status_count, EXTRACT_CATEGORIES)
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(str(exc)) from exc
                    footer_seen = True
                    yield _TypedRecord(kind, dict(row))
                else:
                    raise ExtractionProtocolError(
                        f"unknown JSONL record kind {kind!r}")
        if not header_seen:
            raise ExtractionProtocolError("L0 stream is empty")
        if not footer_seen:
            raise ExtractionProtocolError("L0 stream has no committed footer")

    def metadata(self) -> L0Document:
        return _read_header(self.path)

    def iter_elements(self) -> Iterator[L0Element]:
        for record in self._records():
            if record.kind == "element":
                yield record.value

    def iter_links(self) -> Iterator[LinkSummary]:
        for record in self._records():
            if record.kind == "link":
                yield record.value

    def iter_category_status(self) -> Iterator[CategoryStatus]:
        for record in self._records():
            if record.kind == "category_status":
                yield record.value

    def validate(self) -> None:
        for _record in self._records():
            pass

    def materialize(self) -> L0Document:
        metadata: L0Document | None = None
        elements: list[L0Element] = []
        links: list[LinkSummary] = []
        statuses: list[CategoryStatus] = []
        for record in self._records():
            if record.kind == "header":
                metadata = record.value
            elif record.kind == "element":
                elements.append(record.value)
            elif record.kind == "link":
                links.append(record.value)
            elif record.kind == "category_status":
                statuses.append(record.value)
        assert metadata is not None
        return L0Document(
            doc_name=metadata.doc_name,
            revit_version=metadata.revit_version,
            units=metadata.units,
            change_stamp=metadata.change_stamp,
            levels=metadata.levels,
            grids=metadata.grids,
            rooms=metadata.rooms,
            project_info=metadata.project_info,
            elements=tuple(elements),
            category_status=tuple(statuses),
            links=tuple(links),
            # §18.4: то же и на чтении — материализованный документ несёт
            # пометку заголовка, иначе весь офлайн-хвост (lift/fold/verify/
            # паспорт) считает частичное чтение полным.
            worksharing=metadata.worksharing,
            worksets=metadata.worksets,
            worksets_closed=metadata.worksets_closed,
            # §18.1: то же и на чтении — без переписи в материализованном
            # документе весь офлайн-хвост считает знаменателем выборку.
            census=metadata.census,
        )
