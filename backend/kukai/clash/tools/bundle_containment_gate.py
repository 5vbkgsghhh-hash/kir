"""ВОРОТА ЗАМКА sections: содержит ли ЗАЯВЛЕННАЯ оболочка настоящее тело.

    PYTHONPATH=. venv/bin/python -m kukai.clash.tools.bundle_containment_gate <прогон> [...]

ЧТО ЭТО МЕРИТ И ЧЕМ ОТЛИЧАЕТСЯ ОТ `wall_prism_gate`. Тот проверяет формулу,
собранную из СНЯТЫХ параметров разбора (L0), и оступился на неоднозначности
`WALL_BASE_OFFSET`. Здесь проверяется то, что реально поедет в поиск: L0 ->
lift -> materialize -> ПРОГРАММЫ KIR -> `clash_bundle.bundle_elements` ->
`hulls.build_hull`. Программа объявляет отметку, высоту и тип сама, поэтому
неоднозначности размаха по Z у неё нет вовсе.

ОТКУДА БЕРЁТСЯ СЕЧЕНИЕ ТИПА В ОФЛАЙНЕ. Живой путь читает его у типа на стадии
ground (`WallType.Width`, `CompoundStructure.GetWidth`,
`FamilySymbol.get_BoundingBox`). Все сохранённые разборы сняты ДО волны
sections, и переснять их без живого Revit нельзя. Поэтому здесь та же величина
восстанавливается из НАСТОЯЩИХ элементов того же документа и принимается
ТОЛЬКО постоянной по типу: тип, чьи экземпляры спорят, — не факт о типе.
Восстановление даёт ОЦЕНКУ числа тел; доказывает же здесь другое — проверка
содержания, и она от способа восстановления не зависит.

СВИДЕТЕЛЬ ВНЕШНИЙ. Оболочка сверяется с габаритом Revit того же элемента из
L0. Габарит приходит из живой геометрии модели, поэтому это проверка закона
консервативности против внешнего свидетеля, а не сверка формулы с собой.

ПРАВИЛО ЗАМКА (то же, что у `wall_prism_gate`): ноль нарушений на всей
выборке открывает источник; любое ненулевое число — отказ.

ЗАМЕР 09.08.2026, `snowdon_plumb_v5` (11 069 элементов, 22 программы):

    OST_Floors/profile   111 проверено, 0 нарушений
    OST_Columns/bbox      11 проверено, 0 нарушений
    OST_Walls/prism      787 проверено, 360 нарушений, до 5283 мм наружу
                         (вдоль оси 409/800 — примыкания; поперёк 93/800 —
                          тело шире собственной `WallType.Width`)

Поэтому `OST_Walls` стоит на габарите, а плита и колонна — нет.
"""
from __future__ import annotations

import collections
import dataclasses
import json
import pathlib
import sys
from typing import Any

#: Категория -> пул снапшота, куда кладётся сечение её типа.
_POOL = {
    "OST_Walls": "wall_types",
    "OST_Floors": "floor_types",
    "OST_Ceilings": "ceiling_types",
    "OST_Roofs": "roof_types",
    "OST_Columns": "column_symbols_architectural",
    "OST_StructuralColumns": "column_symbols_structural",
}

#: Шум округления мм-сетки: L0 и программа хранят одни и те же координаты
#: разными путями. 1 мм — шаг самой сетки, а не «мало».
_NOISE_MM = 1.0

#: Склад разборов. В рабочем дереве его нет (0.5 ГБ на здание), поэтому имя
#: прогона ищется сначала рядом, потом на проде, а абсолютный путь принимается
#: как есть. Молча вернуть «прогонов нет» нельзя: это читалось бы как «ноль
#: нарушений».
_ROOTS = (
    pathlib.Path(__file__).resolve().parents[3] / "backend" / "data" / "decompile",
    pathlib.Path("/opt/kukai-rebuild1/backend/backend/data/decompile"),
)


def _resolve(run: str) -> pathlib.Path:
    candidate = pathlib.Path(run)
    if candidate.is_dir():
        return candidate
    for root in _ROOTS:
        if (root / run / "L0.jsonl").is_file():
            return root / run
    raise SystemExit(
        f"разбор {run!r} не найден ни в одном из складов: "
        + ", ".join(str(root) for root in _ROOTS))


def _bbox(el: dict) -> tuple[list[float], list[float]] | None:
    lo, hi = el.get("bbox_min_mm"), el.get("bbox_max_mm")
    if not (isinstance(lo, list) and isinstance(hi, list)
            and len(lo) == 3 and len(hi) == 3):
        return None
    return [float(c) for c in lo], [float(c) for c in hi]


def read_l0(run_dir: pathlib.Path) -> tuple[dict[str, float], list[dict]]:
    levels: dict[str, float] = {}
    elements: list[dict] = []
    with (run_dir / "L0.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("record") == "header":
                for level in (row["document"].get("levels") or []):
                    levels[str(level["id"])] = float(level["elevation_mm"])
            elif row.get("record") == "element":
                elements.append(row["element"])
    return levels, elements


def derive_sections(levels: dict[str, float],
                    elements: list[dict]) -> tuple[dict, dict[str, int]]:
    """Сечения типов, восстановленные из экземпляров. См. шапку."""
    width: dict = collections.defaultdict(set)
    xsec: dict = collections.defaultdict(set)
    thick: dict = collections.defaultdict(set)
    plan: dict = collections.defaultdict(set)
    local_z: dict = collections.defaultdict(set)
    names: dict = {}
    for el in elements:
        category, type_id = el.get("category"), el.get("type_id")
        if category not in _POOL or not type_id:
            continue
        key = (category, str(type_id))
        names[key] = el.get("type_name") or ""
        params = el.get("params") or {}
        box = _bbox(el)
        if category == "OST_Walls":
            if "WALL_ATTR_WIDTH_PARAM" in params:
                width[key].add(round(float(params["WALL_ATTR_WIDTH_PARAM"]), 3))
            if "WALL_CROSS_SECTION" in params:
                xsec[key].add(int(float(params["WALL_CROSS_SECTION"])))
        elif category in ("OST_Floors", "OST_Ceilings", "OST_Roofs"):
            if box is not None:
                thick[key].add(round(box[1][2] - box[0][2], 1))
        elif box is not None:
            plan[key].add((round(box[1][0] - box[0][0], 1),
                           round(box[1][1] - box[0][1], 1)))
            base = levels.get(str(el.get("level_id")))
            offset = params.get("FAMILY_BASE_LEVEL_OFFSET_PARAM")
            top_level = params.get("FAMILY_TOP_LEVEL_PARAM")
            if base is None or offset is None:
                continue
            if top_level is not None and str(top_level) in levels:
                z0 = base + float(offset)
                local_z[key].add((round(box[0][2] - z0, 1),
                                  round(box[1][2] - z0, 1)))

    snapshot: dict[str, list] = collections.defaultdict(list)
    report: collections.Counter = collections.Counter()
    for key, name in sorted(names.items()):
        category, type_id = key
        row: dict[str, Any] = {"id": int(type_id), "name": name}
        if category == "OST_Walls":
            widths, sections = width[key], xsec[key]
            if len(widths) != 1:
                report[f"{category}:width_not_constant_per_type"] += 1
            elif len(sections) != 1:
                report[f"{category}:cross_section_not_constant"] += 1
            else:
                section = {"kind": "plate", "source": "WallType.Width",
                           "thickness_mm": sorted(widths)[0]}
                if sections == {1}:              # 1 == Vertical (замер 27.07)
                    section["uniform"] = True
                else:
                    section["blockers"] = [
                        f"wall_cross_section_{sorted(sections)[0]}"]
                row["section"] = section
                report[f"{category}:derived"] += 1
        elif category in ("OST_Floors", "OST_Ceilings", "OST_Roofs"):
            thicknesses = {t for t in thick[key] if t > 0}
            if len(thicknesses) != 1:
                report[f"{category}:thickness_not_constant_per_type"] += 1
            else:
                row["section"] = {
                    "kind": "plate",
                    "source":
                        "HostObjAttributes.GetCompoundStructure().GetWidth",
                    "thickness_mm": sorted(thicknesses)[0], "uniform": True}
                report[f"{category}:derived"] += 1
        else:
            plans = {p for p in plan[key] if p[0] > 0 and p[1] > 0}
            zs = local_z[key]
            if len(plans) != 1:
                report[f"{category}:plan_section_not_constant"] += 1
            elif len(zs) != 1:
                report[f"{category}:local_z_not_constant"] += 1
            else:
                w, h = sorted(plans)[0]
                z_lo, z_hi = sorted(zs)[0]
                row["section"] = {
                    "kind": "rect",
                    "source": "STRUCTURAL_SECTION_COMMON_WIDTH+HEIGHT",
                    "width_mm": w, "height_mm": h, "uniform": True,
                    "local_z_min_mm": z_lo, "local_z_max_mm": z_hi}
                report[f"{category}:derived"] += 1
        snapshot[_POOL[category]].append(row)
    snapshot["levels"] = [
        {"id": int(lid), "name": str(lid), "elevation_mm": elevation}
        for lid, elevation in sorted(levels.items())]
    return dict(snapshot), dict(sorted(report.items()))


def materialise(run_dir: pathlib.Path) -> list[dict]:
    """L0 -> lift -> materialize -> программы KIR (без Revit и без моста)."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
    from kukai.ir.decompile import lift, materialize
    from tools.compile_gate_offline import (
        _load_envelope, _load_side_index, load_document)

    document, elements = load_document(run_dir)
    result = lift.lift_document_detailed(
        dataclasses.replace(document, elements=elements),
        _load_side_index(run_dir, "sketch.index.json", "sketch_index"),
        _load_envelope(run_dir, "family_placement.index.json"),
        wall_curve_index=_load_side_index(
            run_dir, "curve.index.json", "curve_index"),
        curtain_index=_load_envelope(run_dir, "curtain.index.json"),
        annotation_index=_load_envelope(run_dir, "annotation.index.json"),
        tag_index=_load_envelope(run_dir, "tag.index.json"),
        mep_system_index=_load_envelope(run_dir, "mep_system.index.json"))
    leaves = [node for node in result.nodes if isinstance(node, dict)]
    return list(materialize.leaves_to_program(
        leaves, chunk_target=250).programs)


def gate(run: str) -> dict:
    from kukai.clash import snapshot as _snapshot
    from kukai.ir import clash_bundle as _bundle

    run_dir = _resolve(run)
    levels, elements = read_l0(run_dir)
    real = {str(el.get("element_id")): _bbox(el)
            for el in elements if _bbox(el) is not None}
    sections, derivation = derive_sections(levels, elements)
    programs = json.loads(json.dumps(materialise(run_dir), default=str))

    geometry = _bundle.bundle_elements(programs, snapshot=sections)
    snap = _snapshot.build_from_elements(
        geometry.elements,
        origin={"source": "bundle-containment-gate", "run_dir": run_dir.name},
        profiles=geometry.profiles)

    checked: collections.Counter = collections.Counter()
    violations: collections.Counter = collections.Counter()
    worst: dict[str, float] = collections.defaultdict(float)
    unjoined = 0
    for record in snap.records:
        tail = record.source_id.rsplit("/", 1)[-1]
        box = (real.get(tail[1:])
               if tail.startswith("e") and tail[1:].isdigit() else None)
        if box is None:
            unjoined += 1
            continue
        key = f"{record.category}/{record.hull_source}"
        checked[key] += 1
        hull_lo, hull_hi = record.hull.bounds()
        out = max([0.0] + [max(hull_lo[k] - box[0][k], box[1][k] - hull_hi[k])
                           for k in range(3)])
        if out > _NOISE_MM:
            violations[key] += 1
            worst[key] = max(worst[key], out)
    return {
        "run": run_dir.name,
        "programs": len(programs),
        "bodies": len(snap.records),
        "derivation": derivation,
        "checked": dict(sorted(checked.items())),
        "violations": dict(sorted(violations.items())),
        "worst_mm": {k: round(v, 1) for k, v in sorted(worst.items())},
        "unjoined": unjoined,
        "no_geometry": dict(sorted(geometry.no_geometry.items(),
                                   key=lambda kv: (-kv[1], kv[0]))),
        "gate": "PASS" if not violations else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    runs = list(argv or sys.argv[1:])
    if not runs:
        print(__doc__)
        return 2
    failed = False
    for run in runs:
        row = gate(run)
        failed |= row["gate"] == "FAIL"
        print(f"== {row['run']}: программ {row['programs']}, "
              f"ТЕЛ {row['bodies']}")
        print(f"   вывод сечений: {row['derivation']}")
        print(f"   проверено:     {row['checked']}")
        print(f"   нарушений:     {row['violations'] or '—'}")
        print(f"   макс выход:    {row['worst_mm'] or '—'} мм")
        print(f"   без тела:      {row['no_geometry']}")
        print(f"   ЗАМОК: {row['gate']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
