"""Башня с талией: numpy считает форму, KIR её строит.

Профиль плана и закрутка СИНУСОИДАЛЬНЫЕ, а `stack.transform` умеет только
линейную интерполяцию — и это ровно тот случай, ради которого разъём и нужен:
numpy считает точную кривую и выдаёт каждому участку его концевые значения, а
язык повторяет этаж. Ошибка приближения печатается числом: сказать «синус» и
построить ломаную, не назвав расхождение, — молчаливо неверный ответ.

    backend/venv/bin/python tools/design/examples/tower_numpy.py
"""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from kukai.ir import sdk                                        # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT             # noqa: E402

STOREYS, SEGMENTS = 60, 6           # 10 этажей в сегменте
H_MM, R_MM, COLUMNS = 4000.0, 22000.0, 12   # этаж, радиус базы, колонн в кольце
WAIST, TWIST_DEG = 0.30, 120.0              # ужатие в талии, суммарная закрутка

#: `stack` из 10 этажей по (1 плита + 12 колонн) — это 140 опов после
#: экспансии, а компилятор держит 320 (`compiler.MAX_VALIDATED_OPS`). Здание —
#: ПАЧКА программ, и здесь это видно, а не спрятано.
SEGMENTS_PER_PROGRAM = 2


def plan_scale(t: np.ndarray | float) -> np.ndarray | float:
    """Талия: 1.0 у земли и на макушке, минимум посередине."""
    return 1.0 - WAIST * np.sin(np.pi * np.asarray(t, dtype=float))


def twist_deg(t: np.ndarray | float) -> np.ndarray | float:
    """Закрутка: быстрая внизу, затухающая к верху."""
    return TWIST_DEG * np.sin(np.pi * np.asarray(t, dtype=float) / 2.0)


def ring(radius: float, angle_deg: float) -> np.ndarray:
    """Кольцо точек плана — обычный numpy, никакого KIR."""
    a = np.linspace(0.0, 2 * np.pi, COLUMNS, endpoint=False) + np.radians(angle_deg)
    return np.stack([radius * np.cos(a), radius * np.sin(a)], axis=1)


def approximation_error_mm() -> float:
    """Насколько ломаная по сегментам расходится с настоящим синусом."""
    t = np.linspace(0.0, 1.0, 601)
    knots = np.linspace(0.0, 1.0, SEGMENTS + 1)
    piecewise = np.interp(t, knots, plan_scale(knots))
    return float(np.max(np.abs(piecewise - plan_scale(t))) * R_MM)


def build() -> list[sdk.Program]:
    programs: list[sdk.Program] = []
    knots = np.linspace(0.0, 1.0, SEGMENTS + 1)
    for k in range(SEGMENTS):
        if k % SEGMENTS_PER_PROGRAM == 0:
            programs.append(sdk.program(
                intent=f"башня с талией, сегменты {k + 1}..{k + SEGMENTS_PER_PROGRAM}",
                defaults={"type": "Монолит 200", "symbol": "К 300x300"}))
        t0, t1 = float(knots[k]), float(knots[k + 1])
        s0, s1 = float(plan_scale(t0)), float(plan_scale(t1))
        base = ring(R_MM * s0, float(twist_deg(t0)))
        with programs[-1].stack(
            levels=STOREYS // SEGMENTS, h_mm=H_MM,
            base_elev_mm=t0 * STOREYS * H_MM,
            name_prefix=f"Э{k + 1}",
            transform=sdk.transform(
                scale_xy_top=[s1 / s0, s1 / s0],
                twist_deg_total=float(twist_deg(t1) - twist_deg(t0)))
        ) as floor:
            floor.add(sdk.create_floor_by_contour(
                contour={"outer": {"shape": "poly", "points_mm": base}},
                level=sdk.BY_MACRO))
            for xy in base:
                floor.add(sdk.create_column(xy=xy, level=sdk.BY_MACRO))
    return programs


def main() -> int:
    programs = build()
    st = [p.stats() for p in programs]
    tot = {k: sum(x[k] for x in st) for k in st[0]}
    lines = len(pathlib.Path(__file__).read_text("utf-8").splitlines())
    versions = sorted({v for p in programs
                       for v, out in p.compile_all(snapshot=GROUND_SNAPSHOT).items()
                       if out.ok})
    print(f"{lines} строк питона → {tot['ops_written']} опов написано → "
          f"{tot['ops_expanded']} после экспансии → {tot['elements']} элементов "
          f"(программ KIR: {len(programs)})")
    print(f"этажей {STOREYS}, талия {WAIST:.0%}, закрутка {TWIST_DEG:g}°")
    print(f"ломаная против синуса: {approximation_error_mm():.0f} мм по радиусу")
    print(f"компиляция: {len(versions)}/6 версий {versions}")
    return 0 if len(versions) == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
