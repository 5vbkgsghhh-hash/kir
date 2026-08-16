"""ЧЕГО АВТОРУ НЕ ХВАТАЕТ БЕЗ БИБЛИОТЕК — ЗАМЕР, А НЕ ВКУС (15.08.2026).

ЗАЧЕМ ЭТОТ ФАЙЛ. Список `ALLOWED_IMPORTS` расширяют по ощущению «математики
мало». Ощущение проверено тремя настоящими задачами автора, и оно оказалось
НЕВЕРНЫМ в двух случаях из трёх:

    панелизация фасада по ломаной   30 строк на `math`   ВЕРНО
    колонны по неортогональной сетке 68 строк на `math`  ВЕРНО
    вальмовая кровля L-образного плана 78 строк на `math` 🔴 МОЛЧА НЕВЕРНО

Третья — это весь предмет файла. Скрипт отработал ЗЕЛЕНО, напечатал «скатов
построено: 6 из 6» и «вершин конька ВНЕ контура: 0», а объединение построенных
скатов накрыло 198 м² плана из 288 — **90 м², 31.25 % кровли, дыра, о которой
никто не сказал**. Наивный «скелет» смещением рёбер не сходится на вогнутом
угле, и на `math` этого НЕ ЧЕМ ЗАМЕТИТЬ: невязку считает булева операция над
полигонами, которой в белом списке нет.

ПОЭТОМУ НЕХВАТКА НЕ В АРИФМЕТИКЕ, А В ПРОВЕРКЕ СОБСТВЕННОЙ ГЕОМЕТРИИ. Автор
без библиотек не лишён возможности ПОСЧИТАТЬ — он лишён возможности УЗНАТЬ, что
посчитал неверно. Это ровно форма 18 канона: зелёное без акта различения.

СЛЕДСТВИЕ ДЛЯ СПИСКА: расширять его нечем. `shapely` и `numpy` уже названы в
`GEOMETRY_IMPORTS`, и они закрывают замеренную нехватку целиком (тест ниже).
Ни одна из трёх задач не потребовала ничего сверх; добавлять `networkx`,
который просто установлен, значило бы расширять по аппетиту, а не по замеру.

    venv/bin/python3.12 -m pytest \\
        kukai/ir/tests/test_author_libs_close_a_measured_gap.py -q

ЦЕНА, ЗАМЕРЕННАЯ ЗДЕСЬ ЖЕ: прогрев shapely+numpy стоит ~4.0 с и ~17 МБ сверх
базовых 0.4 с / 26 МБ, и платит его ТОЛЬКО скрипт, назвавший библиотеку.
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import sandbox

try:                                        # тест ВПРАВЕ считать полигоны:
    from shapely.geometry import Polygon    # ограничен АВТОР, а не проверяющий
    from shapely.ops import unary_union
    _SHAPELY = True
except Exception:                           # noqa: BLE001
    _SHAPELY = False

#: L-образный план: вогнутый угол — то самое место, где наивный скелет врёт.
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
PLAN_M2 = 288.0

#: Кровля на `math`: смещение рёбер внутрь и пересечение соседей. Ровно то, что
#: пишет автор, у которого нет булевых операций. Печатает успех.
_ROOF_MATH = '''
import math
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
INSET = 3000.0
def _u(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy)
    return dx / n, dy / n
a2 = 0.0
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    a2 += x0 * y1 - x1 * y0
lines = []
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    ux, uy = _u(x0, y0, x1, y1)
    nx, ny = (-uy, ux) if a2 > 0 else (uy, -ux)
    px, py = x0 + nx * INSET, y0 + ny * INSET
    lines.append((uy, -ux, uy * px - ux * py))
ridge = []
for i in range(len(lines)):
    a1, b1, c1 = lines[i]
    a3, b3, c3 = lines[(i + 1) % len(lines)]
    det = a1 * b3 - a3 * b1
    ridge.append(None if abs(det) < 1e-9
                 else ((c1 * b3 - c3 * b1) / det, (a1 * c3 - a3 * c1) / det))
lvl = create_level(elev_mm=0, name="Кровля")
made = 0
for i in range(len(OUTLINE)):
    r0, r1 = ridge[(i - 1) % len(ridge)], ridge[i]
    if r0 is None or r1 is None:
        continue
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    create_roof(outline={"shape": "poly",
                         "points_mm": [[x0, y0], [x1, y1],
                                       [round(r1[0], 1), round(r1[1], 1)],
                                       [round(r0[0], 1), round(r0[1], 1)]]},
                level=lvl, type="Кровля 200")
    made += 1
print("скатов построено:", made, "из", len(OUTLINE))
'''

#: Та же кровля, но автору доступны библиотеки. Скат — ячейка диаграммы по
#: рёбрам; невязка МЕРЯЕТСЯ и печатается — то, чего на `math` нет.
_ROOF_LIBS = '''
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import voronoi_diagram, unary_union
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
plan = Polygon(OUTLINE)
seeds, owner = [], []
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    n = max(2, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 250.0))
    for k in range(n):
        t = (k + 0.5) / n
        seeds.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        owner.append(i)
cells = voronoi_diagram(MultiPoint(seeds), envelope=plan.buffer(5000.0))
by_edge = {}
for cell in cells.geoms:
    hit = None
    for idx, s in enumerate(seeds):
        if cell.covers(MultiPoint([s]).geoms[0]):
            hit = owner[idx]
            break
    if hit is None:
        continue
    part = cell.intersection(plan)
    if part.is_empty or part.area < 1.0:
        continue
    by_edge[hit] = unary_union([by_edge[hit], part]) if hit in by_edge else part
slopes = []
for i in sorted(by_edge):
    g = by_edge[i]
    g = max(g.geoms, key=lambda p: p.area) if g.geom_type == "MultiPolygon" else g
    slopes.append(g.simplify(1.0))
u = unary_union(slopes)
print("не покрыто м2:", round(plan.difference(u).area / 1e6, 2))
lvl = create_level(elev_mm=0, name="Кровля")
for g in slopes:
    create_roof(outline={"shape": "poly",
                         "points_mm": [[round(float(x), 1), round(float(y), 1)]
                                       for x, y in list(g.exterior.coords)[:-1]]},
                level=lvl, type="Кровля 200")
'''


def _uncovered_m2(ops) -> float:
    """Сколько плана НЕ накрыто построенными скатами, в м². Считает проверяющий."""
    polys = [Polygon(o["outline"]["points_mm"])
             for o in ops if o.get("op") == "create_roof"]
    if not polys:
        return PLAN_M2
    return Polygon(OUTLINE).difference(unary_union(polys)).area / 1e6


class _Case(unittest.TestCase):
    """Тумблер снимается ВСЕГДА — набор может идти в любом порядке."""

    def setUp(self) -> None:
        self._saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = self._saved

    def policy(self):
        """Политика строится ПРОД-КОДОМ.

        `SandboxPolicy(replay_check=True)` — НЕ прод: белый список там заморожен
        умолчанием класса и тумблер оператора не читает. Совпадает с продом
        ровно при выключенном флаге, то есть в половине случаев этого файла.
        """
        from kukai.ir import serving
        return serving._sandbox_policy()


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ — это отказ "
                               "прибора, а не сведение о списке импортов")
class TheDefaultSetCannotCheckItsOwnGeometry(_Case):
    """🔴 НА `math` ЗАДАЧА ВЫХОДИТ ЗЕЛЁНОЙ И НЕВЕРНОЙ."""

    def test_the_math_roof_is_green(self) -> None:
        """Первая половина беды: отказа НЕТ. Скрипт доволен собой."""
        res = sandbox.execute_author_script(_ROOF_MATH, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        self.assertIn("скатов построено: 6 из 6", res.stdout)

    def test_and_it_leaves_a_hole_nobody_named(self) -> None:
        """Вторая половина: 90 м² из 288 не накрыты, и автор об этом не узнал.

        Число не «примерно»: допуск 1 м² на округление координат в опах.
        """
        res = sandbox.execute_author_script(_ROOF_MATH, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        hole = _uncovered_m2(res.ops)
        self.assertAlmostEqual(hole, 90.0, delta=1.0,
                               msg=f"дыра в кровле изменилась: {hole:.2f} м²")

    def test_the_author_cannot_import_the_thing_that_would_show_it(self) -> None:
        """КОНТРОЛЬ ПРИЧИНЫ: дыру видно булевой операцией, а её нет в списке."""
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertFalse(res.ok)
        self.assertEqual(res.refusal.code, "KIR-B004")


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ")
class TheLibrariesCloseExactlyThatGap(_Case):
    """При включённом флаге та же задача выходит ВЕРНОЙ и говорит невязку."""

    def setUp(self) -> None:
        super().setUp()
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def test_the_same_roof_covers_the_plan(self) -> None:
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        hole = _uncovered_m2(res.ops)
        self.assertLess(hole, 1.0, f"скаты не накрыли план: {hole:.2f} м²")

    def test_the_script_says_the_residual_itself(self) -> None:
        """Автор ЗНАЕТ свою невязку — это и есть закрытая нехватка."""
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        self.assertIn("не покрыто м2: 0.0", res.stdout)


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ")
class TheMeasuringSideIsNotVacuous(_Case):
    """КОНТРОЛЬ-FAIL прибора: он обязан УМЕТЬ сказать «дыра есть»."""

    def setUp(self) -> None:
        super().setUp()
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def test_a_missing_slope_is_seen(self) -> None:
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        roofs = [o for o in res.ops if o.get("op") == "create_roof"]
        self.assertGreaterEqual(len(roofs), 3, "нечего выбрасывать — контроль вырожден")
        cut = [o for o in res.ops
               if o.get("op") != "create_roof" or o is not roofs[0]]
        self.assertGreater(_uncovered_m2(cut), 1.0,
                           "прибор не заметил выброшенного ската — он вакуумен")


if __name__ == "__main__":
    unittest.main()
