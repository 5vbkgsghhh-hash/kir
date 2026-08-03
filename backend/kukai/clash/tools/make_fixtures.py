"""Генератор эталонов CLASH — ОТДЕЛЬНЫЙ от тестов (ревью №17).

Тест, который при отсутствии эталона записывает его и проходит, не может
упасть никогда: он благословляет любое поведение, включая сломанное. Поэтому
запись эталонов живёт здесь, а тест умеет ровно одно — сравнивать и падать.

    PYTHONPATH=. venv/bin/python -m kukai.clash.tools.make_fixtures

Перегенерация — осознанный ход руками, и её результат обязан быть прочитан
глазами в диффе: сдвинувшийся голден означает, что сдвинулась формула.
"""
from __future__ import annotations

import json
import pathlib

from kukai.clash import detect as D
from kukai.clash import hulls as H
from kukai.clash import snapshot as S

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def golden_scene() -> S.ClashGeometrySnapshot:
    """Сцена голдена покрывает ВСЕ виды пар и отношений (ревью №17).

    Прежний голден нёс одну грубую AABB-пару: большая часть `geom.py` могла
    сломаться, не сдвинув ни байта. Здесь есть перекрытие, касание, зазор,
    капсула против призмы, капсула против капсулы, отказ по геометрии и
    непригодная категория.
    """
    els = [
        # стена-приёмник (bbox/coarse — стене ось запрещена, ревью №2)
        {"element_id": "100", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [6000, 200, 3000],
         "level_id": "L1", "type_name": "Кирпич 250"},
        # труба НАСКВОЗЬ стены — overlap, капсула против бокса
        {"element_id": "200", "category": "OST_PipeCurves",
         "p0_mm": [3000, -500, 1500], "p1_mm": [3000, 700, 1500],
         "section_radius_mm": 50.0, "section_round": True,
         "bbox_min_mm": [2950, -550, 1450], "bbox_max_mm": [3050, 750, 1550],
         "level_id": "L1", "type_name": "Сталь 100"},
        # воздуховод, КАСАЮЩИЙСЯ грани стены ровно в 0 — contact
        {"element_id": "300", "category": "OST_DuctCurves",
         "p0_mm": [1000, 400, 2000], "p1_mm": [2000, 400, 2000],
         "section_radius_mm": 200.0,
         "bbox_min_mm": [800, 200, 1800], "bbox_max_mm": [2200, 600, 2200],
         "level_id": "L1", "type_name": "Круглый 400"},
        # лоток далеко — не находка, но в переписи и в парах области
        {"element_id": "400", "category": "OST_CableTray",
         "p0_mm": [0, 20000, 0], "p1_mm": [1000, 20000, 0],
         "section_radius_mm": 100.0,
         "bbox_min_mm": [-100, 19900, -100], "bbox_max_mm": [1100, 20100, 100],
         "level_id": "L1", "type_name": "Лоток 200"},
        # перекрытие с ДУГОЙ в контуре -> откат в bbox (ревью №1)
        {"element_id": "500", "category": "OST_Floors",
         "bbox_min_mm": [0, 0, 2950], "bbox_max_mm": [6000, 4000, 3150],
         "level_id": "L1", "type_name": "Монолит 200"},
        # перекрытие с ЧИСТЫМ контуром -> призма/conservative; труба 200 его
        # прошивает, давая пару conservative×conservative (иначе голден знает
        # только грубые пары — ровно упрёк ревью №17)
        {"element_id": "900", "category": "OST_Floors",
         "bbox_min_mm": [2000, -1000, 1400], "bbox_max_mm": [4000, 1000, 1600],
         "level_id": "L1", "type_name": "Монолит 200 чистый"},
        # элемент без всякой геометрии -> missing_geometry
        {"element_id": "600", "category": "OST_PipeCurves",
         "level_id": "L1", "type_name": "битый"},
        # категория вне таблицы -> unsupported/kind_outside_table
        {"element_id": "700", "category": "OST_Parking", "level_id": "L1"},
        # датум -> not_eligible
        {"element_id": "800", "category": "OST_Grids"},
    ]
    profiles = {
        "500": {"profile_available": True,
                "exterior_loop": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                "curve_kinds": [["line", "line", "arc", "line"]],
                "arc_midpoints": [[None, None, [3000, 4300], None]],
                "holes": []},
        "900": {"profile_available": True,
                "exterior_loop": [[2000, -1000], [4000, -1000], [4000, 1000],
                                  [2000, 1000]],
                "curve_kinds": [["line", "line", "line", "line"]],
                "arc_midpoints": [[None, None, None, None]],
                "holes": []},
    }
    return S.build_from_elements(
        els, origin={"run_dir": "golden", "l0_sha": "0"}, profiles=profiles)


def category_manifest() -> dict:
    """Замороженное ожидание по категориям (ревью №12).

    Сравнивать `coverage_matrix()` с той же `KIND_TABLE` бессмысленно: одна и
    та же ошибочная правка обеих сторон зелёная. Манифест — независимая
    сторона равенства, и меняется он только руками.
    """
    rows = {}
    for row in H.coverage_matrix():
        rows[row["category"]] = {
            "eligible": row["eligible"],
            "mvp_side": row["mvp_side"],
            "label": row["label"],
            "hull_sources": row["hull_sources"],
            "refusal": row["refusal"],
        }
    return {"row_count": len(H.KIND_TABLE),
            "note": "Заморожено руками. Новая категория обязана уронить тест.",
            "rows": rows}


def _write(name: str, payload) -> None:
    p = FIXTURES / name
    p.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=1)
    p.write_text(text + "\n", encoding="utf-8")
    print(f"написан {p.relative_to(FIXTURES.parents[2])}")


def main() -> int:
    snap = golden_scene()
    rep = D.detect(snap, clearance_mm=0.0)
    _write("golden_report_v2.json", D.dumps(rep))
    _write("category_manifest.json", category_manifest())
    print("грейды:", snap.by_grade())
    print("находок:", len(rep["findings"]),
          "отношения:", rep["relation_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
