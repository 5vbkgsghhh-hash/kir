"""Криволинейный этаж: shapely режет геометрию, KIR ставит плиту и стены.

Задача, на которой ручной KIR ломается: «этаж — это лента шириной 14 м вдоль
изогнутой оси». Контур такой ленты — это offset кривой, а offset полигона
руками не считают: считают его shapely (`buffer` + `simplify`), и ровно за этим
разъём и нужен. KIR получает готовый контур и делает то, чего shapely не умеет:
кладёт плиту, ставит стены по периметру и отвечает за единицы и версии API.

Упрощение здесь не косметика, а бюджет: программа держит 20 авторских опов
(`compiler.MAX_OPS_PER_PROGRAM`), а сырой buffer даёт сотни вершин. Допуск
упрощения печатается вместе с настоящим отклонением контура — приближение,
названное числом, честно; неназванное — нет.

    backend/venv/bin/python tools/design/examples/contour_shapely.py
"""
import pathlib
import sys

import numpy as np
from shapely.geometry import LineString, Polygon

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from kukai.ir import sdk                                        # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT             # noqa: E402

WIDTH_MM = 14000.0          # ширина ленты этажа
SIMPLIFY_MM = 220.0         # допуск упрощения контура
WALL_H_MM = 3600.0
OPS_PER_PROGRAM = 20        # compiler.MAX_OPS_PER_PROGRAM


def spine() -> LineString:
    """Ось этажа — синусоидальная дуга; обычный numpy, никакого KIR."""
    x = np.linspace(0.0, 90000.0, 60)
    y = 16000.0 * np.sin(np.pi * x / 90000.0) + 0.00018 * x ** 1.5
    return LineString(np.column_stack([x, y]))


def slab_outline() -> tuple[list[list[float]], Polygon, Polygon]:
    """Лента вдоль оси -> замкнутый контур плиты, упрощённый до бюджета опов."""
    raw = spine().buffer(WIDTH_MM / 2.0, cap_style="flat", join_style="round")
    simple = raw.simplify(SIMPLIFY_MM)
    pts = [[float(x), float(y)] for x, y in simple.exterior.coords[:-1]]
    return pts, raw, simple


def build(pts: list[list[float]]) -> list[sdk.Program]:
    """Плита по контуру + стены по каждому его ребру."""
    edges = list(zip(pts, pts[1:] + pts[:1]))
    programs: list[sdk.Program] = []

    def fresh(n: int) -> sdk.Program:
        p = sdk.program(intent=f"криволинейный этаж, часть {n}",
                        defaults={"level": "Этаж 1", "type": "Кирпич 250"})
        programs.append(p)
        return p

    p = fresh(1)
    p.add(sdk.create_floor_by_contour(
        contour={"outer": {"shape": "poly", "points_mm": pts}},
        level="Этаж 1", type="Монолит 200"))
    for a, b in edges:
        if len(p) >= OPS_PER_PROGRAM:
            p = fresh(len(programs) + 1)
        p.add(sdk.create_wall(a, b, "Этаж 1", height_mm=WALL_H_MM))
    return programs


def main() -> int:
    pts, raw, simple = slab_outline()
    programs = build(pts)
    st = [p.stats() for p in programs]
    tot = {k: sum(x[k] for x in st) for k in st[0]}
    lines = len(pathlib.Path(__file__).read_text("utf-8").splitlines())
    versions = sorted({v for p in programs
                       for v, out in p.compile_all(snapshot=GROUND_SNAPSHOT).items()
                       if out.ok})
    # Отклонение — не допуск: `simplify` обещает не больше допуска, а сколько
    # вышло на самом деле, знает только разность площадей к периметру.
    drift = raw.symmetric_difference(simple).area / raw.exterior.length

    print(f"{lines} строк питона → {tot['ops_written']} опов написано → "
          f"{tot['ops_expanded']} после экспансии → {tot['elements']} элементов "
          f"(программ KIR: {len(programs)})")
    print(f"контур: {len(raw.exterior.coords) - 1} вершин из buffer → "
          f"{len(pts)} после simplify (допуск {SIMPLIFY_MM:.0f} мм)")
    print(f"среднее отклонение контура: {drift:.0f} мм, "
          f"площадь этажа {simple.area / 1e6:.0f} м²")
    print(f"компиляция: {len(versions)}/6 версий {versions}")
    return 0 if len(versions) == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
