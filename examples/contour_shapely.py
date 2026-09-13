"""Curved floor: shapely cuts the geometry, KIR places the slab and walls.

The problem where hand-written KIR breaks down: "the floor is a 14 m wide
ribbon along a curved axis." Its outline is a curve offset, which nobody
computes by hand: shapely does (`buffer` + `simplify`). KIR takes the finished
outline and does what shapely cannot: lays the slab, places walls along the
perimeter, and answers for units and API versions.

Simplification here is not cosmetic, it is a budget: a program holds 20
authored ops (`compiler.MAX_OPS_PER_PROGRAM`), while a raw buffer produces
hundreds of vertices. The simplification tolerance is printed together with
the actual outline deviation — an approximation named by a number is honest;
an unnamed one is not.

    PYTHONPATH=/opt/kir python3.12 examples/contour_shapely.py
"""
import pathlib
import sys

import numpy as np
from shapely.geometry import LineString, Polygon

# 🔴 IT USED TO BE `parents[3]` — three steps up from `examples/` reach the ROOT OF THE FILESYSTEM,
# and the example was dead TWICE: the anchor missed, and the import called `kukai.ir`, renamed to
# `kir` at the 27.08 split. Counting steps upward is only correct for one specific layout. This
# example sits next to the package by construction: one step.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from kir import sdk                                            # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT                 # noqa: E402

WIDTH_MM = 14000.0          # width of the floor ribbon
SIMPLIFY_MM = 220.0         # outline simplification tolerance
WALL_H_MM = 3600.0
OPS_PER_PROGRAM = 20        # compiler.MAX_OPS_PER_PROGRAM


def spine() -> LineString:
    """Floor axis — a sinusoidal arc; plain numpy, no KIR involved."""
    x = np.linspace(0.0, 90000.0, 60)
    y = 16000.0 * np.sin(np.pi * x / 90000.0) + 0.00018 * x ** 1.5
    return LineString(np.column_stack([x, y]))


def slab_outline() -> tuple[list[list[float]], Polygon, Polygon]:
    """Ribbon along the axis -> closed slab outline, simplified to the op budget."""
    raw = spine().buffer(WIDTH_MM / 2.0, cap_style="flat", join_style="round")
    simple = raw.simplify(SIMPLIFY_MM)
    pts = [[float(x), float(y)] for x, y in simple.exterior.coords[:-1]]
    return pts, raw, simple


def build(pts: list[list[float]]) -> list[sdk.Program]:
    """Slab from the outline + walls along each of its edges."""
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
    # Deviation is not tolerance: `simplify` promises no more than the tolerance, and what actually
    # resulted is known only by the area difference relative to the perimeter.
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
