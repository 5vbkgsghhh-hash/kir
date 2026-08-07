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


def build(directory: pathlib.Path, ops: int | None = None,
          generator_children: int | None = None) -> dict[str, Any]:
    header = _header(directory)
    census = _census(header, directory)
    extracted = _extracted_by_collector(directory)

    if ops is None:
        from relift_offline import relift
        report = relift(directory)
        ops = int(report.get("op_total", 0))
        elements = int(report.get("elements", 0))
        if generator_children is None:
            generator_children = int(report.get("generator_children", 0))
    else:
        elements = sum(extracted.values())
        generator_children = generator_children or 0

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

    # Коллекторы-псевдонимы читают элементы, уже посчитанные переписью под их
    # настоящими категориями. Их след виден только в «прочитано», и если он
    # ненулевой — сумма прочитанного по классам будет меньше общего числа
    # элементов. Это не ошибка, но и не молчание: печатаем.
    alias_read = {k: v for k, v in extracted.items() if k in COLLECTOR_ALIASES}

    return {
        "directory": str(directory),
        "doc_name": header.get("document", {}).get("doc_name", ""),
        "ops": ops,
        "elements_read": elements,
        "generator_children": generator_children,
        "census_total": census_total,
        "categories_total": len(census),
        "denominators": {
            "model": model,
            "model_authored": authored_model,
            "documentation": documentation,
            "content": content,
            "content_authored": authored_content,
            "document": census_total,
            "unknown": unknown,
        },
        "model_pct": pct(ops, model),
        "model_pct_authored": pct(ops, authored_model),
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
            "model_read_unlifted": max(authored_model_read - ops, 0),
            "expressed_of_read_pct": pct(ops, authored_model_read),
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
        f"({report['ops']} опов из {gap['model_read_authored']} авторских)",
        f"  не ЧИТАЕМ элементов здания:      {gap['model_unread']}"
        f"   ← строка в таблице категорий",
        f"  читаем, но не поднимаем:         {gap['model_read_unlifted']}"
        f"   ← лифтер и оп",
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
        for row in report["unknown_rows"][:20]:
            lines.append(f"  {row['census']:>7}  {row['category']}"
                         f"  {row['category_ru']}")
        lower = report["content_pct_lower_bound"]
        lines.append(f"  ⇒ содержательное покрытие лежит между {lower}% "
                     f"и {report['content_pct_authored']}%")
    if report["alias_collectors_read"]:
        lines.append("")
        lines.append(f"коллекторы-псевдонимы (уже в переписи под своими "
                     f"категориями): {report['alias_collectors_read']}")
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
