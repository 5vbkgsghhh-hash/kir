"""KIR MESH — треугольная поверхность как значение языка (волна 29.07).

ЗАЧЕМ. В реестре 32 операции, и все они зданиецентричные: уровни, стены,
помещения, контуры. Произвольную форму — оболочку, решётку, скульптурный
объём — модель выразить не может НИЧЕМ. Это стена ровно там, где сила модели
наибольшая: придумать геометрию она умеет, а сказать её было нечем.

ЧТО ЭТО НА САМОМ ДЕЛЕ, И ЧЕГО ЗДЕСЬ НЕТ. Меш — это ГЕОМЕТРИЯ БЕЗ BIM-СМЫСЛА.
У полученного элемента нет типа, нет параметров толщины/материала слоёв, он не
попадёт в спецификации как стена или перекрытие, и человек не отредактирует
его ручками так, как редактируют стену. Это цена, а не недостаток реализации:
DirectShape в Revit устроен именно так. Поэтому единственное честное поведение
операции — говорить это самой, во всех местах, где её видно (докстринг спеки,
паспорт разбора, квитанция пользователю), а не молчать и дать назвать
результат «зданием». «Сгенерили здание», когда сгенерили меш, — ровно то
враньё, против которого написан весь этот компилятор.

ЗАКОНЫ ФОРМЫ (все статические, все — типизированный отказ, ни одного тихого
исправления входа). Тихая правка входа в этом доме уже стоила 96.77% групп
(«0 вместо отсутствующего значения»), поэтому здесь НЕТ ни выбрасывания
вырожденных треугольников, ни склейки вершин, ни обрезания списка по пределу:

  1. форма значения: ровно {vertices_mm, triangles}, лишние поля — отказ;
  2. вершины: 3..MAX_VERTICES точек [x,y,z] мм, каждая координата конечна;
  3. треугольники: 1..MAX_TRIANGLES троек ЦЕЛЫХ индексов;
  4. индекс вне диапазона вершин — отказ (а не «возьмём по модулю»);
  5. повторённый индекс внутри треугольника — вырожденный, отказ;
  6. ребро короче _MIN_EDGE_MM или площадь меньше _MIN_AREA_MM2 — отказ
     (два разных вырождения: тонкая игла ловится ребром, три точки на одной
     прямой — площадью);
  7. одинаковая тройка вершин дважды — сдвоенная грань, отказ;
  8. вершина, на которую не ссылается ни один треугольник, — отказ: мы бы
     построили не тот меш, который прислали, и снаружи это неотличимо от
     успеха;
  9. координата вне ±_COORD_MAX_MM — отказ;
 10. меш обязан быть СВЯЗНЫМ (см. ниже).

ПРО СВЯЗНОСТЬ — ЭТО ФАКТ API, А НЕ ВКУС. У TessellatedShapeBuilder единица
построения называется connected face set: OpenConnectedFaceSet/
CloseConnectedFaceSet ограничивают ОДНУ связную компоненту. Сложить в один
такой набор две несвязные компоненты — нарушение контракта API, и поведение
Revit там не определено. Поэтому несвязный меш здесь — НАЗВАННЫЙ отказ,
который сообщает число найденных компонент и говорит, что делать (по операции
на компоненту), а не молчаливая попытка построить неизвестно что.

Связность считается ГЕОМЕТРИЧЕСКИ, а не по индексам, и это принципиально.
Огромная доля реальных мешей приходит «супом треугольников»: у каждой грани
свои три вершины, и по индексам такой меш распадается на N компонент, хотя
физически он цельный. Отказать ему значило бы отказать самому обычному входу.
Поэтому для ПРОВЕРКИ СВЯЗНОСТИ вершины, совпадающие с точностью _WELD_TOL_MM,
считаются одной точкой — при этом сам вход не меняется ни на йоту: склейка
живёт только внутри проверки и наружу не протекает.

ПРЕДЕЛЫ ЧИСЛА (замер 29.07, живой компайл-сервис :52412, 2021 и 2026).
Эмитируется вершинный массив ОДИН раз плюс массив индексов, поэтому размер
исходника растёт линейно и обрыва не имеет:

    вершин  треуг.   символов C#     2021     2026
        30      48         2 729     22ms      7ms
       840   1 600        49 453     26ms     28ms
     1 624   3 136        99 469     50ms     49ms
     3 280   6 400       208 153    111ms     92ms
     6 384  12 544       411 877    187ms    182ms

То есть Roslyn НЕ является узким местом: ~33 символа и ~15 мкс на треугольник,
линейно, без обрыва. Предел MAX_TRIANGLES=4096 выбран по этому замеру с
запасом (≈135 КБ исходника, ≈65 мс компиляции — треть самого тяжёлого из
замеренных) и ЧЕСТНО НЕ ЯВЛЯЕТСЯ пределом времени построения в живом Revit:
сколько Revit собирает 4096 граней внутри транзакции, офлайн не измеряется
никак, а мост режет execute на 200 с. Этот предел разрешено ОПУСКАТЬ по
результату живого прогона и запрещено поднимать молча.

_COORD_MAX_MM, в отличие от предела числа граней, ЗАМЕРОМ НЕ ПОДКРЕПЛЁН и
честно помечен здесь как выведенный: Revit заявляет работу в пределах 20 миль
(32 186 880 мм) от внутреннего начала координат, и 10 км взяты с запасом
внутрь этого предела, а не подогнаны под него.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kukai.ir.diag import (
    Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION,
)
from kukai.ir.emit_utils import is_finite_number

#: Меш распался на несколько кусков — см. «ПРО СВЯЗНОСТЬ» выше.
MESH_DISCONNECTED = "KIR-M001"
#: Треугольник ссылается на несуществующую вершину.
MESH_INDEX_RANGE = "KIR-M002"
#: Вырожденный треугольник: повтор индекса, короткое ребро или нулевая площадь.
MESH_DEGENERATE = "KIR-M003"
#: Вершина, на которую не ссылается ни один треугольник.
MESH_UNUSED_VERTEX = "KIR-M004"
#: Одна и та же тройка вершин встречается дважды.
MESH_DUPLICATE_FACE = "KIR-M005"

MAX_VERTICES = 4096
MAX_TRIANGLES = 4096

#: Ребро короче считается вырожденным. Ровно та же величина и та же причина,
#: что у _EDGE_TOL в contour.py: ShortCurveTolerance Revit статически.
_MIN_EDGE_MM = 1.0
#: Площадь меньше — три точки на одной прямой при длинных рёбрах.
_MIN_AREA_MM2 = 1.0
#: Вершины ближе этого друг к другу — одна точка ДЛЯ ПРОВЕРКИ СВЯЗНОСТИ.
_WELD_TOL_MM = 0.1
#: См. шапку: выведено из 20-мильного предела Revit, а не замерено.
_COORD_MAX_MM = 10_000_000.0


def _bad(diags: list, code: str, oid, field: str, message: str,
         got: Any = None) -> None:
    diags.append(Diagnostic(code=code, op_id=oid, field_name=field, got=got,
                            message_ru=message))


def _components(tris: list, weld: list) -> list:
    """Связные компоненты по СКЛЕЕННЫМ вершинам (union-find).

    `weld[i]` — номер точки, к которой отнесена вершина i. Возвращает список
    компонент, каждая — список индексов треугольников; порядок устойчив.
    """
    parent = list(range(len(tris)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # первый встреченный треугольник на каждую склеенную точку — этого
    # достаточно: любые два треугольника, делящие точку, окажутся в одном
    # множестве через него.
    first: dict[int, int] = {}
    for ti, tri in enumerate(tris):
        for idx in tri:
            w = weld[idx]
            if w in first:
                union(first[w], ti)
            else:
                first[w] = ti
    groups: dict[int, list] = {}
    for ti in range(len(tris)):
        groups.setdefault(find(ti), []).append(ti)
    return [groups[k] for k in sorted(groups)]


def _weld_map(verts: list) -> list:
    """Номер склеенной точки для каждой вершины (только для связности).

    Решётка со стороной _WELD_TOL_MM плюс просмотр 27 соседних ячеек: две
    точки ближе допуска гарантированно попадают либо в одну ячейку, либо в
    соседнюю, поэтому решение не зависит от того, где именно легла граница
    ячейки.
    """
    cells: dict[tuple, int] = {}
    weld = [0] * len(verts)
    for i, v in enumerate(verts):
        key = (int(math.floor(v[0] / _WELD_TOL_MM)),
               int(math.floor(v[1] / _WELD_TOL_MM)),
               int(math.floor(v[2] / _WELD_TOL_MM)))
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    hit = cells.get((key[0] + dx, key[1] + dy, key[2] + dz))
                    if hit is None:
                        continue
                    w = verts[hit]
                    if (abs(w[0] - v[0]) <= _WELD_TOL_MM
                            and abs(w[1] - v[1]) <= _WELD_TOL_MM
                            and abs(w[2] - v[2]) <= _WELD_TOL_MM):
                        found = hit
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            cells[key] = i
            weld[i] = i
        else:
            weld[i] = weld[found]
    return weld


def _tri_metrics(a: list, b: list, c: list) -> tuple:
    """(минимальное ребро, площадь) треугольника в мм и мм²."""
    def d(p, q):
        return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                         + (p[2] - q[2]) ** 2)
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    area = 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return min(d(a, b), d(b, c), d(c, a)), area


def mesh_bbox(verts: list) -> tuple:
    """(xmin, ymin, zmin, xmax, ymax, zmax) в мм."""
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def validate_mesh(mesh: Any, oid, field: str, diags: list) -> Optional[dict]:
    """Значение-меш -> {"vertices_mm": [[x,y,z]...], "triangles": [[i,j,k]...]}.

    Возвращает None и КЛАДЁТ диагностику на любое нарушение. Ничего не
    исправляет и ничего не выбрасывает: вход либо принят целиком, либо назван
    отказ.
    """
    if not isinstance(mesh, dict) or set(mesh) != {"vertices_mm", "triangles"}:
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: меш — {{vertices_mm: [[x,y,z], ...], "
             f"triangles: [[i,j,k], ...]}} и ничего кроме", got=mesh)
        return None

    raw_v = mesh["vertices_mm"]
    if not isinstance(raw_v, list) or not (3 <= len(raw_v) <= MAX_VERTICES):
        _bad(diags, TYPE_BOUNDS, oid, f"{field}.vertices_mm",
             f"{field}: vertices_mm — от 3 до {MAX_VERTICES} вершин "
             f"(предел замерен, см. шапку mesh.py)",
             got=(len(raw_v) if isinstance(raw_v, list) else raw_v))
        return None
    verts: list = []
    for vi, v in enumerate(raw_v):
        if not isinstance(v, list) or len(v) != 3 \
                or not all(is_finite_number(c) for c in v):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.vertices_mm[{vi}]",
                 f"{field}: вершина — [x,y,z] из трёх конечных чисел в мм",
                 got=v)
            return None
        if any(abs(float(c)) > _COORD_MAX_MM for c in v):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.vertices_mm[{vi}]",
                 f"{field}: координата вне ±{_COORD_MAX_MM:.0f} мм — это "
                 f"вне рабочего пространства Revit, а не «далеко»", got=v)
            return None
        verts.append([float(v[0]), float(v[1]), float(v[2])])

    raw_t = mesh["triangles"]
    if not isinstance(raw_t, list) or not (1 <= len(raw_t) <= MAX_TRIANGLES):
        _bad(diags, TYPE_BOUNDS, oid, f"{field}.triangles",
             f"{field}: triangles — от 1 до {MAX_TRIANGLES} треугольников "
             f"(предел замерен, см. шапку mesh.py)",
             got=(len(raw_t) if isinstance(raw_t, list) else raw_t))
        return None
    n = len(verts)
    tris: list = []
    seen_faces: set = set()
    for ti, t in enumerate(raw_t):
        if not isinstance(t, list) or len(t) != 3 \
                or any(isinstance(i, bool) or not isinstance(i, int) for i in t):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник — [i,j,k] из трёх ЦЕЛЫХ номеров вершин",
                 got=t)
            return None
        if any(not (0 <= i < n) for i in t):
            _bad(diags, MESH_INDEX_RANGE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник ссылается на вершину вне списка "
                 f"(вершин {n}, допустимы номера 0..{n - 1})", got=t)
            return None
        if len(set(t)) != 3:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник повторяет вершину — это отрезок, "
                 f"а не грань", got=t)
            return None
        key = tuple(sorted(t))
        if key in seen_faces:
            _bad(diags, MESH_DUPLICATE_FACE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: эта тройка вершин уже описана — сдвоенная грань",
                 got=t)
            return None
        seen_faces.add(key)
        edge, area = _tri_metrics(verts[t[0]], verts[t[1]], verts[t[2]])
        if edge < _MIN_EDGE_MM:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: ребро {edge:.4f} мм короче {_MIN_EDGE_MM} мм "
                 f"(ShortCurveTolerance Revit статически)", got=t)
            return None
        if area < _MIN_AREA_MM2:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: площадь {area:.4f} мм² — три точки лежат на одной "
                 f"прямой", got=t)
            return None
        tris.append([int(t[0]), int(t[1]), int(t[2])])

    used = {i for t in tris for i in t}
    missing = sorted(set(range(n)) - used)
    if missing:
        _bad(diags, MESH_UNUSED_VERTEX, oid, f"{field}.vertices_mm",
             f"{field}: вершины {missing[:8]}"
             f"{' и ещё ' + str(len(missing) - 8) if len(missing) > 8 else ''} "
             f"не участвуют ни в одном треугольнике — построен был бы не тот "
             f"меш, который прислан", got=len(missing))
        return None

    comps = _components(tris, _weld_map(verts))
    if len(comps) != 1:
        _bad(diags, MESH_DISCONNECTED, oid, field,
             f"{field}: меш распадается на {len(comps)} несвязных кусков "
             f"(размеры {sorted((len(c) for c in comps), reverse=True)[:6]} "
             f"треугольников). Один DirectShape строится ОДНИМ связным "
             f"набором граней — отправь по операции на кусок",
             got=len(comps))
        return None

    return {"vertices_mm": verts, "triangles": tris}
