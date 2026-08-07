#!/usr/bin/env python3
"""bounds_audit.py — перепись числовых границ KIR и ЗАМЕР их вреда.

Инструмент отвечает на один вопрос про каждую границу компилятора:
**сколько НАСТОЯЩИХ элементов она отвергает.**

Два раздела:

* ``--census`` — перепись: все числовые границы пакета ``kukai/ir`` (реестр
  опов + модульные константы + допуски свидетелей), с местом объявления.
  Вердикт (ЗАМЕРЕНА / НАЗНАЧЕНА / НЕЯСНО) ставит человек по комментарию
  рядом; инструмент даёт ПОЛНЫЙ список, чтобы «не нашёл» нельзя было спутать
  с «нет».
* ``--measure <dir>...`` — замер: по сохранённым разборам (L0.jsonl + боковые
  индексы) считает, сколько элементов каждая измеримая граница отвергла бы.

ЗАМЕР ВОСПРОИЗВОДИТ ПУТЬ ЛИФТЕРА, А НЕ ПРИБЛИЖАЕТ ЕГО. Значение, которое
проверяется границей, считается ровно так же, как его считает
``decompile/lift.py`` (``_bounded_param`` — параметр L0 напрямую;
``_bounded_number`` — вычисленная величина: проекция на ось стены, отметка от
уровня СТЕНЫ-НОСИТЕЛЯ, адрес ячейки витража). Иначе число мерило бы
инструмент, а не компилятор.

Запуск (из backend/):
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --census
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --measure backend/data/decompile/k2_ar_rd_v7
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --measure-all
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import os
import pathlib
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kukai.ir import spec  # noqa: E402

_BACKEND = pathlib.Path(
    os.environ.get("KUKAI_BACKEND_ROOT", "/opt/kukai-rebuild1/backend"))
try:
    if (pathlib.Path(__file__).resolve().parent.parent / "kukai" / "ir").is_dir():
        _BACKEND = pathlib.Path(__file__).resolve().parent.parent
except OSError:
    pass
IR_ROOT = _BACKEND / "kukai" / "ir"
DATA_ROOT = _BACKEND / "backend" / "data" / "decompile"

# Имена, по которым модульная константа считается ГРАНИЦЕЙ или ДОПУСКОМ.
BOUNDISH = re.compile(
    r"TOL|LIMIT|MAX|MIN|MARGIN|EPS|THRESH|CAP|BUDGET|STEP|SIZE|COUNT|"
    r"_MM|_S$|_MS$|DEG|RATIO|FACTOR|BATCH|ROUNDS|SAMPLES|TOKENS|DECIMALS|"
    r"LEVELS|AXIS|OPS|ROW|ARRAY|COVERAGE|DEGREE|VERTICES|TRIANGLES|N_PBT",
)


# ─────────────────────────── ПЕРЕПИСЬ ────────────────────────────────────────

def registry_bounds() -> list[dict[str, Any]]:
    rows = []
    for op_name, op in sorted(spec.OPS.items()):
        for p in op.params:
            if p.min_val is None and p.max_val is None:
                continue
            rows.append({
                "where": "registry",
                "id": f"{op_name}.{p.name}",
                "kind": p.kind,
                "min": p.min_val,
                "max": p.max_val,
            })
    return rows


def registry_tolerances() -> list[dict[str, Any]]:
    rows = []
    for op_name, op in sorted(spec.OPS.items()):
        for key, value in sorted(op.tolerances.items()):
            rows.append({
                "where": "registry.tolerances",
                "id": f"{op_name}.{key}",
                "kind": "tolerance",
                "min": None,
                "max": value,
            })
    return rows


def module_constants() -> list[dict[str, Any]]:
    """Все числовые константы модулей пакета (module/class/function scope)."""
    rows: list[dict[str, Any]] = []
    for path in sorted(IR_ROOT.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(IR_ROOT.parent.parent))

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: list[str] = []

            def visit_FunctionDef(self, node):  # noqa: N802
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node):  # noqa: N802
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def record(self, node, names, value_node):
                if value_node is None:
                    return
                try:
                    value = ast.literal_eval(value_node)
                except Exception:
                    try:
                        value = eval(  # noqa: S307 - literal arithmetic only
                            compile(ast.Expression(value_node), "<c>", "eval"),
                            {"__builtins__": {}}, {})
                    except Exception:
                        return
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return
                for name in names:
                    rows.append({
                        "where": rel,
                        "line": node.lineno,
                        "scope": ".".join(self.scope),
                        "id": name,
                        "kind": "constant",
                        "value": value,
                        "boundish": bool(BOUNDISH.search(name)),
                    })

            def visit_Assign(self, node):  # noqa: N802
                self.record(
                    node,
                    [t.id for t in node.targets if isinstance(t, ast.Name)],
                    node.value)
                self.generic_visit(node)

            def visit_AnnAssign(self, node):  # noqa: N802
                if isinstance(node.target, ast.Name):
                    self.record(node, [node.target.id], node.value)
                self.generic_visit(node)

        Visitor().visit(tree)
    return rows


# ─────────────────────────── ЧТЕНИЕ РАЗБОРА ──────────────────────────────────

class Dump:
    """Сохранённый разбор: L0 + боковые индексы. Только чтение."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.name = path.name
        self.header: dict[str, Any] = {}
        self.elements: list[dict[str, Any]] = []
        with (path / "L0.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                kind = record.get("record")
                if kind == "header" or (not kind and "document" in record):
                    self.header = record.get("document", {})
                elif kind == "element":
                    self.elements.append(record["element"])
                elif "document" in record and not self.header:
                    self.header = record["document"]
        self.by_id = {e["element_id"]: e for e in self.elements}
        self.levels = {
            str(lv["id"]): lv for lv in (self.header.get("levels") or [])}
        self.rooms = self.header.get("rooms") or []
        self.grids = self.header.get("grids") or []
        self.doc_name = self.header.get("doc_name", path.name)

    def side(self, filename: str) -> dict[str, Any]:
        p = self.path / filename
        if not p.exists():
            return {}
        try:
            return json.load(p.open(encoding="utf-8"))
        except Exception:
            return {}

    def of_category(self, *cats: str) -> Iterable[dict[str, Any]]:
        wanted = set(cats)
        for e in self.elements:
            if e.get("category") in wanted:
                yield e


# ─────────────────────────── ЗАМЕР ───────────────────────────────────────────

def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _bound_of(op: str, param: str) -> tuple[float | None, float | None]:
    p = next(x for x in spec.OPS[op].params if x.name == param)
    return p.min_val, p.max_val


class Result:
    """Одна измеренная граница на одном здании."""

    def __init__(self, bound_id: str, bound_repr: str) -> None:
        self.bound_id = bound_id
        self.bound_repr = bound_repr
        self.denominator = 0     # сколько элементов вообще подпадают
        self.below = 0
        self.above = 0
        self.worst_low: float | None = None
        self.worst_high: float | None = None
        self.observed_min: float | None = None
        self.observed_max: float | None = None

    def feed(self, value: float, lo: float | None, hi: float | None) -> None:
        self.denominator += 1
        self.observed_min = (value if self.observed_min is None
                             else min(self.observed_min, value))
        self.observed_max = (value if self.observed_max is None
                             else max(self.observed_max, value))
        if lo is not None and value < lo:
            self.below += 1
            self.worst_low = (value if self.worst_low is None
                              else min(self.worst_low, value))
        if hi is not None and value > hi:
            self.above += 1
            self.worst_high = (value if self.worst_high is None
                               else max(self.worst_high, value))

    @property
    def rejected(self) -> int:
        return self.below + self.above


def _param_bound(dump: Dump, out: dict[str, Result], *, categories: tuple[str, ...],
                 source: str, op: str, param: str) -> None:
    """Ровно путь lift._bounded_param: значение параметра L0 против границы."""
    lo, hi = _bound_of(op, param)
    key = f"{op}.{param}"
    res = out.setdefault(key, Result(key, f"[{lo}, {hi}]  ← L0 {source}"))
    for e in dump.of_category(*categories):
        value = _finite((e.get("params") or {}).get(source))
        if value is None:
            continue
        res.feed(value, lo, hi)


def _host_level_elev(dump: Dump, element: dict[str, Any]) -> float | None:
    host = dump.by_id.get(element.get("host_id") or "")
    if host is None:
        return None
    level = dump.levels.get(str(host.get("level_id") or ""))
    if level is None or not host.get("level_name"):
        return None
    return _finite(level.get("elevation_mm"))


def _hosted_sill(dump: Dump, element: dict[str, Any]) -> float | None:
    """lift._host_level_sill: z вставки минус отметка уровня СТЕНЫ."""
    p0 = element.get("p0_mm")
    if not (isinstance(p0, list) and len(p0) == 3):
        return None
    z = _finite(p0[2])
    elev = _host_level_elev(dump, element)
    if z is None or elev is None:
        return None
    sill = z - elev
    if -1.0 < sill < 0.0:          # тот же клэмп субмиллиметрового шума
        sill = 0.0
    return sill


def _hosted_offset(dump: Dump, element: dict[str, Any]) -> float | None:
    """lift._host_offset: проекция вставки на ось стены (прямой случай)."""
    host = dump.by_id.get(element.get("host_id") or "")
    if host is None or host.get("category") != "OST_Walls":
        return None
    hp0, hp1 = host.get("p0_mm"), host.get("p1_mm")
    p0 = element.get("p0_mm")
    if not all(isinstance(x, list) and len(x) >= 2 for x in (hp0, hp1, p0)):
        return None
    dx, dy = hp1[0] - hp0[0], hp1[1] - hp0[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        return None
    return ((p0[0] - hp0[0]) * dx + (p0[1] - hp0[1]) * dy) / length


def measure_dump(dump: Dump) -> dict[str, Result]:
    out: dict[str, Result] = {}

    # ── 1. Реестровые границы, которые ЛИФТЕР применяет к параметру L0 ──────
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_USER_HEIGHT_PARAM",
                 op="create_wall", param="height_mm")
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_BASE_OFFSET",
                 op="create_wall", param="base_offset_mm")
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_TOP_OFFSET",
                 op="create_wall", param="top_offset_mm")
    _param_bound(dump, out, categories=("OST_Floors",),
                 source="FLOOR_HEIGHTABOVELEVEL_PARAM",
                 op="create_floor", param="height_offset_mm")
    _param_bound(dump, out, categories=("OST_Ceilings",),
                 source="CEILING_HEIGHTABOVELEVEL_PARAM",
                 op="create_ceiling", param="height_offset_mm")
    _param_bound(dump, out, categories=("OST_StructuralColumns", "OST_Columns"),
                 source="FAMILY_BASE_LEVEL_OFFSET_PARAM",
                 op="create_column", param="base_offset_mm")
    _param_bound(dump, out, categories=("OST_StructuralColumns", "OST_Columns"),
                 source="FAMILY_TOP_LEVEL_OFFSET_PARAM",
                 op="create_column", param="top_offset_mm")
    _param_bound(dump, out, categories=("OST_PipeCurves",),
                 source="RBS_PIPE_DIAMETER_PARAM",
                 op="create_pipe", param="diameter_mm")
    _param_bound(dump, out, categories=("OST_DuctCurves",),
                 source="RBS_CURVE_DIAMETER_PARAM",
                 op="create_duct", param="diameter_mm")

    # ── 2. Реестровые границы на ВЫЧИСЛЕННОЙ величине (_bounded_number) ─────
    for category, op in (("OST_Doors", "create_door"),
                         ("OST_Windows", "create_window")):
        lo_s, hi_s = _bound_of(op, "sill_mm")
        lo_o, hi_o = _bound_of(op, "offset_mm")
        ks = f"{op}.sill_mm"
        ko = f"{op}.offset_mm"
        rs = out.setdefault(ks, Result(
            ks, f"[{lo_s}, {hi_s}]  ← z вставки − отметка уровня стены"))
        ro = out.setdefault(ko, Result(
            ko, f"[{lo_o}, {hi_o}]  ← проекция вставки на ось стены"))
        for e in dump.of_category(category):
            sill = _hosted_sill(dump, e)
            # У двери sill попадает в параметры только при |sill| >= 1 мм.
            if sill is not None and (op == "create_window" or abs(sill) >= 1.0):
                rs.feed(sill, lo_s, hi_s)
            offset = _hosted_offset(dump, e)
            if offset is not None:
                ro.feed(offset, lo_o, hi_o)

    lo, hi = _bound_of("create_level", "elev_mm")
    res = out.setdefault("create_level.elev_mm", Result(
        "create_level.elev_mm", f"[{lo}, {hi}]  ← отметка уровня"))
    for level in dump.levels.values():
        value = _finite(level.get("elevation_mm"))
        if value is not None:
            res.feed(value, lo, hi)

    # set_curtain_panel.u/v — адрес ячейки из бокового индекса витражей
    curtain = dump.side("curtain.index.json").get("curtain_index") or {}
    for axis in ("u", "v"):
        lo, hi = _bound_of("set_curtain_panel", axis)
        key = f"set_curtain_panel.{axis}"
        res = out.setdefault(key, Result(key, f"[{lo}, {hi}]  ← адрес ячейки"))
        for row in curtain.values():
            if not isinstance(row, dict) or not row.get("curtain_available"):
                continue
            for panel in row.get("panels") or []:
                value = _finite(panel.get(f"{axis}_index"))
                if value is not None:
                    res.feed(value, lo, hi)

    # ── 3. Строковые потолки: ТОЛЬКО параметры вида `str`. ─────────────────
    # Селекторы (`{"by":"name","value":...}`) потолка НЕ имеют — проверено по
    # ветке `p.kind == "sel"` в authoring.py, у неё нет проверки длины. Мерить
    # длину type_name против «64» значило бы мерить границу, которой нет.
    res_lvl = out.setdefault("create_level.name (str cap 64)", Result(
        "create_level.name", "len <= 64  ← имя уровня"))
    for level in dump.levels.values():
        n = level.get("name")
        if isinstance(n, str) and n:
            res_lvl.feed(float(len(n)), None, 64.0)
    res_grid = out.setdefault("create_grid.name (str cap 64)", Result(
        "create_grid.name", "len <= 64  ← имя оси"))
    for grid in dump.grids:
        n = grid.get("name")
        if isinstance(n, str) and n:
            res_grid.feed(float(len(n)), None, 64.0)
    res_room = out.setdefault("create_room.name (str cap 64)", Result(
        "create_room.name", "len <= 64  ← имя помещения"))
    for room in dump.rooms:
        n = room.get("name")
        if isinstance(n, str) and n:
            res_room.feed(float(len(n)), None, 64.0)

    # ── 4. Немодульные (константные) границы, которые видят данные ─────────
    # 4.1 контурные пределы: число точек кольца и площадь
    sketch = dump.side("sketch.index.json").get("profile_index") or {}
    res_pts = out.setdefault("lift._CONTOUR_MAX_POINTS", Result(
        "lift._CONTOUR_MAX_POINTS", "len(ring) <= 64  ← кольцо контура"))
    res_area = out.setdefault("contour._MIN_AREA", Result(
        "contour._MIN_AREA", ">= 10000 мм²  ← площадь кольца"))
    res_edge = out.setdefault("contour/_EDGE_TOL", Result(
        "contour/geom._EDGE_TOL", ">= 1.0 мм  ← кратчайшее ребро кольца"))
    res_bulge = out.setdefault("contour._MAX_BULGE", Result(
        "contour._MAX_BULGE", "|bulge| <= 1.5  ← дуга контура"))
    for row in sketch.values():
        if not isinstance(row, dict) or not row.get("profile_available"):
            continue
        rings = [row.get("exterior_loop") or []]
        rings.extend(row.get("holes") or [])
        for ring in rings:
            pts = [p for p in ring if isinstance(p, list) and len(p) >= 2]
            if len(pts) < 3:
                continue
            res_pts.feed(float(len(pts)), None, 64.0)
            area2 = 0.0
            shortest = float("inf")
            for i in range(len(pts)):
                x0, y0 = float(pts[i][0]), float(pts[i][1])
                x1, y1 = float(pts[(i + 1) % len(pts)][0]), float(pts[(i + 1) % len(pts)][1])
                area2 += x0 * y1 - x1 * y0
                shortest = min(shortest, math.hypot(x1 - x0, y1 - y0))
            res_area.feed(abs(area2) / 2.0, 10_000.0, None)
            if math.isfinite(shortest):
                res_edge.feed(shortest, 1.0, None)
        # bulge дуг профиля — та же формула, что в lift._bulge_from_midpoint
        loops = [row.get("exterior_loop") or []] + list(row.get("holes") or [])
        mids_all = row.get("arc_midpoints") or []
        for loop, mids in zip(loops, mids_all):
            pts = [p for p in loop if isinstance(p, list) and len(p) >= 2]
            if len(pts) < 3 or not isinstance(mids, list):
                continue
            for i, mid in enumerate(mids):
                if not (isinstance(mid, list) and len(mid) >= 2):
                    continue
                p0, p1 = pts[i % len(pts)], pts[(i + 1) % len(pts)]
                dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
                chord = math.hypot(dx, dy)
                if chord < 1e-9:
                    continue
                nx, ny = -dy / chord, dx / chord
                cx = (float(p0[0]) + float(p1[0])) / 2.0
                cy = (float(p0[1]) + float(p1[1])) / 2.0
                sagitta = -((float(mid[0]) - cx) * nx + (float(mid[1]) - cy) * ny)
                res_bulge.feed(abs(2.0 * sagitta / chord), None, 1.5)

    # 4.1b ВСТРОЕННЫЕ (не именованные) пределы профиля — lift.py:1118-1120,1688
    res_holes = out.setdefault("lift: len(holes) <= 8", Result(
        "lift.py:1119  len(holes) <= 8", "отверстий в профиле <= 8"))
    res_hole_pts = out.setdefault("lift: len(hole ring) <= 32", Result(
        "lift.py:1120  len(кольцо отверстия) <= 32", "точек в отверстии <= 32"))
    res_ext_pts = out.setdefault("lift: len(exterior) <= 64", Result(
        "lift.py:1118  len(внешнее кольцо) <= 64", "точек во внешнем кольце <= 64"))
    for row in sketch.values():
        if not isinstance(row, dict) or not row.get("profile_available"):
            continue
        ext = row.get("exterior_loop") or []
        holes = row.get("holes") or []
        res_ext_pts.feed(float(len(ext)), None, 64.0)
        res_holes.feed(float(len(holes)), None, 8.0)
        for hole in holes:
            res_hole_pts.feed(float(len(hole)), None, 32.0)

    # 4.1c макро-пределы, проверяемые против настоящей геометрии здания
    res_h = out.setdefault("macros.stack.h_mm", Result(
        "macros stack.h_mm [1000, 10000]", "высота этажа, мм"))
    elevations = sorted(
        v for v in (_finite(lv.get("elevation_mm")) for lv in dump.levels.values())
        if v is not None)
    for a, b in zip(elevations, elevations[1:]):
        delta = b - a
        if delta > 0.5:                      # дубли отметок не считаем этажом
            res_h.feed(delta, 1000.0, 10000.0)

    res_rect = out.setdefault("contour rect size <= 500 000", Result(
        "contour.py:250  size_mm <= 500 000", "габарит элемента, мм"))
    for e in dump.elements:
        lo_b, hi_b = e.get("bbox_min_mm"), e.get("bbox_max_mm")
        if not (isinstance(lo_b, list) and isinstance(hi_b, list)
                and len(lo_b) == 3 and len(hi_b) == 3):
            continue
        for i in range(2):
            span = _finite(hi_b[i]) or 0.0
            base = _finite(lo_b[i]) or 0.0
            res_rect.feed(abs(span - base), None, 500_000.0)

    res_doc = out.setdefault("serving doc name <= 120", Result(
        "serving.py:964  len(doc_name) <= 120", "длина имени документа"))
    res_doc.feed(float(len(dump.doc_name)), None, 120.0)

    # 4.2 координатные потолки
    res_coord16 = out.setdefault("authoring._COORD_LIMIT_MM", Result(
        "authoring._COORD_LIMIT_MM", "|коорд| <= 16 000 000 мм"))
    res_coord10 = out.setdefault("mesh._COORD_MAX_MM", Result(
        "mesh._COORD_MAX_MM", "|коорд| <= 10 000 000 мм"))
    for e in dump.elements:
        for key in ("p0_mm", "p1_mm", "bbox_min_mm", "bbox_max_mm"):
            v = e.get(key)
            if not isinstance(v, list):
                continue
            for component in v:
                value = _finite(component)
                if value is None:
                    continue
                res_coord16.feed(abs(value), None, 16_000_000.0)
                res_coord10.feed(abs(value), None, 10_000_000.0)

    # 4.3 предел длины стены-носителя (create_door/window.offset_mm max)
    res_wall_len = out.setdefault("wall_length_vs_offset_max", Result(
        "wall_length_vs_offset_max", "длина стены <= 100 000 мм"))
    for e in dump.of_category("OST_Walls"):
        p0, p1 = e.get("p0_mm"), e.get("p1_mm")
        if not (isinstance(p0, list) and isinstance(p1, list)
                and len(p0) >= 2 and len(p1) >= 2):
            continue
        res_wall_len.feed(math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
                          None, 100_000.0)

    # 4.4 макро-потолки: этажи и оси
    res_lv = out.setdefault("macros.MAX_STACK_LEVELS", Result(
        "macros.MAX_STACK_LEVELS", "<= 40 этажей в одном stack"))
    res_lv.feed(float(len(dump.levels)), None, 40.0)
    res_gr = out.setdefault("macros.MAX_GRID_AXIS", Result(
        "macros.MAX_GRID_AXIS", "<= 50 осей в одном grid"))
    res_gr.feed(float(len(dump.grids)), None, 50.0)

    # 4.5 текстовые аннотации: create_text.width_mm и предел листа
    ann = dump.side("annotation.index.json").get("text_note_index") or {}
    lo, hi = _bound_of("create_text", "width_mm")
    res_sheet = out.setdefault("docspace._SHEET_LIMIT_MM", Result(
        "docspace._SHEET_LIMIT_MM", "|u|,|v| <= 16 000 000 мм  ← точка вида"))
    res_sheet10k = out.setdefault("docspace._SHEET_LIMIT_MM (старое 10 000)", Result(
        "docspace._SHEET_LIMIT_MM (снятое значение 10 000)",
        "|u|,|v| <= 10 000 мм  ← точка вида"))
    for row in ann.values():
        at = row.get("at_view_mm") if isinstance(row, dict) else None
        if isinstance(at, list) and len(at) == 2:
            for component in at:
                value = _finite(component)
                if value is not None:
                    res_sheet.feed(abs(value), None, 16_000_000.0)
                    res_sheet10k.feed(abs(value), None, 10_000.0)

    # 4.6 ДОПУСКИ СВИДЕТЕЛЕЙ — обратная сторона границы: они не отвергают
    # правду, они ПРИНИМАЮТ ошибку. Считаем, у скольких элементов допуск
    # съедает больше десятой доли собственного размера: для такого элемента
    # свидетель подписывает совпадение там, где расхождение видно глазом.
    # Размер, с которым допуск сравнивается, берётся ТОТ, ЧТО ЧИТАЕТ
    # СВИДЕТЕЛЬ: bbox_extents_witness сверяет ТОЛЬКО X и Y (толщину плиты он
    # не смотрит вовсе), а endpoint_mm — концы КРИВОЙ, значит характерный
    # размер там длина, а не габарит.
    key = "допуск свидетеля bbox_mm=50 (пол/кровля/потолок)"
    res = out.setdefault(key, Result(
        key, "допуск <= 10% меньшей стороны В ПЛАНЕ (сторона >= 500 мм)"))
    for e in dump.of_category("OST_Floors", "OST_Roofs", "OST_Ceilings"):
        lo_b, hi_b = e.get("bbox_min_mm"), e.get("bbox_max_mm")
        if not (isinstance(lo_b, list) and isinstance(hi_b, list)
                and len(lo_b) == 3 and len(hi_b) == 3):
            continue
        spans = []
        for i in range(2):                    # ТОЛЬКО X и Y
            a, b = _finite(lo_b[i]), _finite(hi_b[i])
            if a is None or b is None:
                spans = []
                break
            spans.append(abs(b - a))
        spans = [s for s in spans if s > 1e-6]
        if spans:
            res.feed(min(spans), 500.0, None)

    key = "допуск свидетеля endpoint_mm=5 (стена/труба/воздуховод)"
    res = out.setdefault(key, Result(
        key, "допуск <= 10% длины кривой (длина >= 50 мм)"))
    for e in dump.of_category("OST_Walls", "OST_PipeCurves", "OST_DuctCurves",
                              "OST_Conduit", "OST_CableTray"):
        p0, p1 = e.get("p0_mm"), e.get("p1_mm")
        if not (isinstance(p0, list) and isinstance(p1, list)
                and len(p0) == 3 and len(p1) == 3):
            continue
        length = math.dist(
            [float(c) for c in p0], [float(c) for c in p1])
        if length > 1e-6:
            res.feed(length, 50.0, None)

    # 4.7 комнаты: запас _ROOM_INTERIOR_MARGIN_MM
    _measure_rooms(dump, out)

    return out


def _room_clearance(point, exterior, holes) -> float:
    """Расстояние до ближайшей границы; отрицательное — снаружи контура."""
    def seg_dist(px, py, ax, ay, bx, by) -> float:
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 <= 0.0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def inside(px, py, ring) -> bool:
        result = False
        n = len(ring)
        for i in range(n):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % n]
            if (ay > py) != (by > py):
                x = ax + (py - ay) * (bx - ax) / (by - ay)
                if x > px:
                    result = not result
        return result

    px, py = point
    best = min(
        seg_dist(px, py, *ring[i], *ring[(i + 1) % len(ring)])
        for ring in (exterior,) + tuple(holes)
        for i in range(len(ring)))
    if not inside(px, py, exterior):
        return -best
    for hole in holes:
        if inside(px, py, hole):
            return -best
    return best


def _measure_rooms(dump: Dump, out: dict[str, Result]) -> None:
    """Пределы поиска точки помещения — ВЫЗОВОМ САМОГО ЛИФТЕРА.

    Приближать эту логику своими руками уже оказалось неверно: первая версия
    считала ``count_x*count_y`` начальной сетки и получала 2..9 клеток, тогда
    как предел ``_ROOM_INTERIOR_MAX_CELLS`` стоит на СЧЁТЧИКЕ ОБХОДА
    ветвей-и-границ. Поэтому здесь зовётся ``lift._room_interior_point``, а
    вердикт читается по типу отказа.
    """
    from kukai.ir.decompile import lift as _lift

    res_margin = out.setdefault("lift._ROOM_INTERIOR_MARGIN_MM", Result(
        "lift._ROOM_INTERIOR_MARGIN_MM",
        "зазор точки помещения от границы >= 10 мм"))
    res_cells = out.setdefault("lift._ROOM_INTERIOR_MAX_CELLS", Result(
        "lift._ROOM_INTERIOR_MAX_CELLS",
        "клеток обхода ветвей-и-границ <= 50 000"))
    res_ring = out.setdefault("room ring: >= 3 различных вершин", Result(
        "lift._clean_ring", ">= 3 различных вершин в кольце помещения"))

    for room in dump.rooms:
        loops = room.get("boundary_loops_mm") or []
        rings = []
        bad_ring = False
        for loop in loops:
            pts = [(float(p[0]), float(p[1]))
                   for p in loop if isinstance(p, list) and len(p) >= 2]
            while len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(set(pts)) < 3:
                bad_ring = True
                continue
            rings.append(tuple(pts))
        res_ring.feed(0.0 if bad_ring else 1.0, 1.0, None)
        if not rings:
            continue

        def area_of(ring):
            a = 0.0
            for i in range(len(ring)):
                x0, y0 = ring[i]
                x1, y1 = ring[(i + 1) % len(ring)]
                a += x0 * y1 - x1 * y0
            return abs(a) / 2.0

        rings.sort(key=area_of, reverse=True)
        exterior, holes = rings[0], tuple(rings[1:])
        try:
            _lift._room_interior_point(exterior, holes)
        except Exception as exc:                       # _CannotLift
            detail = str(getattr(exc, "detail", exc))
            if "cell budget" in detail:
                res_cells.feed(1.0, None, 0.0)         # отвергнуто пределом
                res_margin.feed(1.0, 0.0, None)
            elif "clearance" in detail:
                res_margin.feed(-1.0, 0.0, None)       # отвергнуто запасом
                res_cells.feed(0.0, None, 0.0)
            else:
                continue
        else:
            res_margin.feed(1.0, 0.0, None)
            res_cells.feed(0.0, None, 0.0)


# ─────────────────────────── ВЫВОД ───────────────────────────────────────────

def inline_literals() -> list[dict[str, Any]]:
    """Числа, работающие границей ПРЯМО В СРАВНЕНИИ, без имени.

    Третий род границ, и его нельзя пропустить: `len(exterior) > 64` в
    lift.py:1118 отвергает 64 элемента башни, а имени у этого числа нет — ни
    один поиск по именованным константам его бы не нашёл. Тривиальные 0/1/2/3
    и −1 отброшены как структурные (пустота, единственность, размерность).
    """
    trivial = {0, 1, 2, 3, -1, 0.0, 1.0}
    rows: list[dict[str, Any]] = []
    for path in sorted(IR_ROOT.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines()
        rel = str(path.relative_to(IR_ROOT.parent.parent))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for operand in [node.left] + list(node.comparators):
                if not (isinstance(operand, ast.Constant)
                        and isinstance(operand.value, (int, float))
                        and not isinstance(operand.value, bool)):
                    continue
                if operand.value in trivial:
                    continue
                rows.append({
                    "where": rel, "line": node.lineno,
                    "value": operand.value,
                    "source": lines[node.lineno - 1].strip()[:110],
                })
    return rows


def print_census() -> None:
    reg = registry_bounds()
    tol = registry_tolerances()
    consts = module_constants()
    boundish = [c for c in consts if c["boundish"] and not c["scope"]]
    other = [c for c in consts if not (c["boundish"] and not c["scope"])]

    print(f"РЕЕСТР: границ параметров {len(reg)}")
    for r in reg:
        print(f"  {r['id']:38s} {r['kind']:5s} [{r['min']}, {r['max']}]")
    print(f"\nРЕЕСТР: допусков свидетелей {len(tol)}")
    for r in tol:
        print(f"  {r['id']:38s} = {r['max']}")
    print(f"\nМОДУЛЬНЫЕ КОНСТАНТЫ, похожие на границу: {len(boundish)}")
    for c in boundish:
        print(f"  {c['where']:46s} :{c['line']:<5d} {c['id']:36s} = {c['value']}")
    inline = inline_literals()
    print(f"\nБЕЗЫМЯННЫЕ ЧИСЛА-ГРАНИЦЫ (литерал прямо в сравнении): {len(inline)}")
    for c in inline:
        print(f"  {c['where']:46s} :{c['line']:<5d} {str(c['value']):>18s}  {c['source']}")
    print(f"\nПРОЧИЕ ЧИСЛОВЫЕ КОНСТАНТЫ (не границы): {len(other)}")
    for c in other:
        scope = f"[{c['scope']}]" if c["scope"] else ""
        print(f"  {c['where']:46s} :{c['line']:<5d} {scope}{c['id']:34s} = {c['value']}")
    print(f"\nПОВЕРХНОСТЬ ГРАНИЦ: реестр {len(reg)} + допуски {len(tol)} "
          f"+ именованные константы {len(boundish)} + безымянные литералы "
          f"{len(inline)} = {len(reg) + len(tol) + len(boundish) + len(inline)}")
    print(f"(и ещё {len(other)} числовых констант, границами не являющихся)")


def print_measurement(dumps: list[pathlib.Path]) -> None:
    per_building: dict[str, dict[str, Result]] = {}
    for path in dumps:
        dump = Dump(path)
        per_building[f"{dump.name} ({dump.doc_name})"] = measure_dump(dump)

    keys = sorted({k for r in per_building.values() for k in r})
    rows = []
    for key in keys:
        total_rej = 0
        buildings_hit = 0
        detail = []
        repr_ = ""
        for building, results in per_building.items():
            res = results.get(key)
            if res is None or res.denominator == 0:
                continue
            repr_ = res.bound_repr
            if res.rejected:
                buildings_hit += 1
                total_rej += res.rejected
            detail.append((building, res))
        rows.append((total_rej, buildings_hit, key, repr_, detail))

    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    print("=" * 100)
    print("ЗАМЕР ГРАНИЦ ПО НАСТОЯЩИМ ЗДАНИЯМ")
    print("=" * 100)
    for total, hit, key, repr_, detail in rows:
        print(f"\n### {key}   {repr_}")
        print(f"    ОТВЕРГНУТО ВСЕГО: {total}   зданий затронуто: {hit}")
        for building, res in detail:
            mark = "  ОТВЕРГАЕТ" if res.rejected else ""
            print(f"      {building:44s} {res.rejected:6d} / {res.denominator:<7d}"
                  f"  наблюдалось [{_fmt(res.observed_min)} … {_fmt(res.observed_max)}]"
                  f"{mark}")
            if res.below:
                print(f"          ниже нижней границы: {res.below}, худшее {_fmt(res.worst_low)}")
            if res.above:
                print(f"          выше верхней границы: {res.above}, худшее {_fmt(res.worst_high)}")


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1e6 or (value and abs(value) < 1e-3):
        return f"{value:.4g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", action="store_true")
    parser.add_argument("--measure", nargs="*", default=None)
    parser.add_argument("--measure-all", action="store_true")
    args = parser.parse_args()

    if args.census:
        print_census()
    targets: list[pathlib.Path] = []
    if args.measure:
        targets = [pathlib.Path(p) for p in args.measure]
    elif args.measure_all:
        seen: dict[str, pathlib.Path] = {}
        for d in sorted(DATA_ROOT.iterdir()):
            if not (d / "L0.jsonl").exists():
                continue
            try:
                header = json.loads((d / "L0.jsonl").open(encoding="utf-8").readline())
            except Exception:
                continue
            name = header.get("document", {}).get("doc_name", d.name)
            size = (d / "L0.jsonl").stat().st_size
            if name not in seen or size > seen[name].stat().st_size:
                seen[name] = d / "L0.jsonl"
        targets = [p.parent for p in seen.values()]
    if targets:
        print_measurement(targets)
    if not args.census and not targets:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
