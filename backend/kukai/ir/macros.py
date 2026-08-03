"""KIR macro layer — compact programs expand to flat IR before validation
(SPEC 12.3: bounded expressiveness — no loops in the language, only named,
capped, deterministic macro patterns; v0 stack discipline preserved).

stack — a typical floor times N storeys:
    {"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
     "base_elev_mm": 0, "name_prefix": "Level",
     "floor": [ ...create_wall / create_pipe ops, WITHOUT level... ]}
  Expands to N create_level ops (ids L1..LN) + per-storey clones of the floor
  ops (ids "L{k}_<oid>"), their `level` rewritten to {"by":"ref","value":"L{k}"}.
  Grids inside `floor` are refused — grids are not per-storey objects.

grid_array — a rectangular grid net:
    {"op": "grid_array", "id": "net", "nx": 5, "ny": 4,
     "dx_mm": 6000, "dy_mm": 6000, "origin_mm": [0,0],
     "prefix_x": "", "prefix_y": "А", "margin_mm": 1000}
  Expands to nx vertical + ny horizontal create_grid ops with deterministic
  names (X: "1".."nx" with prefix_x; Y: prefix_y+index).

series — one template repeated N times, with NAMED NUMERIC PARAMETERS read off a
PIECEWISE-LINEAR track indexed by the repetition number:
    {"op": "series", "id": "leg", "count": 20,
     "track": {"hw": [[0, 62500], [5, 30000], [10, 24000], [20, 5000]],
               "z":  [[0,     0], [5, 57000], [10, 115000], [20, 276000]]},
     "items": [{"op": "create_beam", "id": "sw",
                "p0_mm": ["-$hw",      "-$hw",      "$z"],
                "p1_mm": ["-$hw@next", "-$hw@next", "$z@next"],
                "level": {"by": "ref", "value": "L0"}}]}
  Expands to count x len(items) ops with ids "{id}_{k}_{item-id}"; every "$name"
  in a VALUE slot is replaced by the track value at index k, "$name@next" by the
  value at k+1 (so N repetitions can chain N segments over N+1 stations).

Expansion is pure and deterministic: same input -> same flat ops (goldens and
the idempotency stamp depend on this).
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any

from kukai.ir.diag import Diagnostic, KirRefusal
from kukai.ir.emit_utils import is_finite_number

MACRO_ERROR = "KIR-M001"

MAX_STACK_LEVELS = 40          # v0 cap
MAX_GRID_AXIS = 50
MAX_EXPANDED_OPS = 300         # anti-blowup, checked by compiler after expansion

#: Развёртка ОДНОГО series. Число намеренно ОТДЕЛЬНОЕ от MAX_EXPANDED_OPS и
#: меньше его: 300 — бюджет ВСЕЙ программы после экспансии, и если один макрос
#: может выбрать его целиком, то программе, которая строит башню, не остаётся
#: места на уровень, сетку и типы, с которых она обязана начаться. 200 = 2/3
#: бюджета, то есть один series всегда оставляет 100 опов остальной программе.
#: Замер 28.07 (башня Эйфеля, плечо KIR): 118 балок перечислением — влезает в
#: один series с запасом 40%. Плечо C# в том же прогоне поставило 343 балки
#: одной программой, и ЭТО В ОДИН series НЕ ВЛЕЗАЕТ — осознанно: 343 элемента в
#: одной транзакции Revit это живое число, которого никто не мерил, а мост режет
#: execute на 200 с. Поднимать потолок без живого замера значит гадать; нужно
#: 343 — это два series, и отказ говорит об этом прямо, а не молча тянет.
MAX_SERIES_OPS = 200
MAX_SERIES_COUNT = 200         # повторов; при items из одного опа совпадает с ↑

#: Именованных параметров в треке: хватает на полное состояние станции
#: (x, y, z + ширина, высота, поворот, смещение, радиус).
MAX_TRACK_PARAMS = 8

#: Узлов в одном треке. 32 узла = 31 излом силуэта; у Эйфелевой башни их 3, у
#: типового небоскрёба с отступами 2..5. Предел тут не про память, а про смысл:
#: трек, у которого узлов столько же, сколько повторов, — то же перечисление в
#: другом костюме, и ни одного раунда оно не экономит.
MAX_TRACK_NODES = 32

MACRO_OPS = ("stack", "grid_array", "series")

#: What a typical floor may contain. Originally walls and pipes only, which
#: made the macro unusable for the thing it is named after: a storey is a slab,
#: columns, beams, partitions, doors, windows and rooms, and `stack` refused
#: every one of them. Measured 2026-07-27 — a 60-storey tower spent its first
#: four rounds writing 69 `create_level` ops by hand because the one macro that
#: exists for exactly that could not carry the floor with them.
#:
#: The rule for membership is mechanical, not taste: the op must take `level`
#: (so the per-storey rewrite means something) and must not be a whole-network
#: op whose nodes carry their own elevations. Hosted ops (door/window) stay out
#: because their host is addressed by `ref` to a sibling op, and the expansion
#: renames ids per storey — a hosted op would point at storey 1 forever.
_STACKABLE = (
    "create_wall", "create_pipe", "create_column", "create_beam",
    "create_floor", "create_floor_by_contour", "create_room",
    "create_foundation", "create_duct", "create_cable_tray", "create_roof",
)

#: Ops whose points carry an explicit Z: the macro keeps them storey-local and
#: makes them absolute on expansion. Ops that locate by `level` + 2D need no
#: shift — the rewritten level ref already places them.
_Z_SHIFTED = {
    "create_pipe": ("p0_mm", "p1_mm"),
    "create_beam": ("p0_mm", "p1_mm"),
    "create_duct": ("p0_mm", "p1_mm"),
    "create_cable_tray": ("p0_mm", "p1_mm"),
}


def _err(msg: str, op_id: str = None, **kw) -> KirRefusal:
    return KirRefusal([Diagnostic(code=MACRO_ERROR, op_id=op_id,
                                  message_ru=msg, **kw)])


def _num(x) -> bool:
    return is_finite_number(x)


def _macro_id(m: dict, default: str) -> str:
    if "id" not in m:
        return default
    value = m.get("id")
    if not isinstance(value, str) or not (1 <= len(value) <= 64):
        raise _err("id макроса — строка длиной 1..64", default, got=value)
    return value


def _closed_fields(m: dict, allowed: set[str], mid: str) -> None:
    extra = set(m) - allowed
    if extra:
        raise _err(f"неизвестное поле макроса '{sorted(extra)[0]}'", mid,
                   field_name=sorted(extra)[0], got=m.get(sorted(extra)[0]))


#: Point-bearing fields a per-storey transform may move. Only the XY plane is
#: touched — Z belongs to the storey, and the level rewrite already owns it.
_XY_FIELDS = ("p0_mm", "p1_mm", "xy", "top_xy")


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _xform_point(pt, pivot, sx, sy, ang, dx, dy):
    """Scale about the pivot, then rotate about it, then translate. A 3-component
    point keeps its Z: the storey owns elevation, the transform owns the plan."""
    x, y = float(pt[0]), float(pt[1])
    px, py = pivot
    x, y = (x - px) * sx, (y - py) * sy
    c, s = math.cos(ang), math.sin(ang)
    x, y = x * c - y * s, x * s + y * c
    out = [px + x + dx, py + y + dy]
    return out + [pt[2]] if len(pt) == 3 else out


def _validate_transform(t: Any, mid: str) -> dict:
    """The per-storey transform, checked into a plain dict of end-state values.

    Bounded expressiveness (SPEC 12.3) says no loops in the language — but a
    macro that can only repeat a storey BYTE-IDENTICALLY cannot describe any
    building whose plan changes with height, which is every interesting tower:
    a taper, a twist, a setback. `stack` was that macro, so the only way to get
    scale was `create_group`, which also repeats identically. Measured
    2026-07-27: the model could produce a 179-element tower with a silhouette,
    or 12 000 identical columns, and nothing in the language let it have both.
    Interpolation is still not a loop: the k-th storey is a pure function of k.
    """
    if t is None:
        return {}
    if not isinstance(t, dict):
        raise _err("stack.transform — объект", mid, got=t)
    allowed = {"scale_xy_top", "twist_deg_total", "offset_mm_top", "pivot_mm"}
    extra = set(t) - allowed
    if extra:
        raise _err(f"stack.transform: неизвестное поле '{sorted(extra)[0]}' "
                   f"(допустимы {sorted(allowed)})", mid, got=sorted(extra)[0])
    out: dict = {}
    scale = t.get("scale_xy_top", [1.0, 1.0])
    if (not isinstance(scale, list) or len(scale) != 2
            or not all(_num(v) and 0.05 <= v <= 20 for v in scale)):
        raise _err("stack.transform.scale_xy_top — [sx, sy], каждый 0.05..20 "
                   "(во сколько раз план верхнего этажа отличается от нижнего)",
                   mid, got=scale)
    out["scale"] = [float(scale[0]), float(scale[1])]
    twist = t.get("twist_deg_total", 0)
    if not _num(twist) or not (-3600 <= twist <= 3600):
        raise _err("stack.transform.twist_deg_total — число -3600..3600 "
                   "(суммарный поворот от низа к верху)", mid, got=twist)
    out["twist"] = float(twist)
    off = t.get("offset_mm_top", [0, 0])
    if (not isinstance(off, list) or len(off) != 2
            or not all(_num(v) and abs(v) <= 1_000_000 for v in off)):
        raise _err("stack.transform.offset_mm_top — [dx, dy] в мм, |v| <= 1e6",
                   mid, got=off)
    out["offset"] = [float(off[0]), float(off[1])]
    piv = t.get("pivot_mm", [0, 0])
    if (not isinstance(piv, list) or len(piv) != 2
            or not all(_num(v) and abs(v) <= 1_000_000 for v in piv)):
        raise _err("stack.transform.pivot_mm — [x, y] в мм, центр сужения и "
                   "поворота", mid, got=piv)
    out["pivot"] = [float(piv[0]), float(piv[1])]
    return out


def _apply_transform(op: dict, tr: dict, t: float, mid: str) -> None:
    """Move op's plan geometry to storey fraction `t` (0 at the base, 1 at the
    top). Mutates in place — the caller already deep-copied."""
    if not tr:
        return
    sx = _lerp(1.0, tr["scale"][0], t)
    sy = _lerp(1.0, tr["scale"][1], t)
    ang = math.radians(_lerp(0.0, tr["twist"], t))
    dx = _lerp(0.0, tr["offset"][0], t)
    dy = _lerp(0.0, tr["offset"][1], t)
    piv = tr["pivot"]
    c, s = math.cos(ang), math.sin(ang)

    def move(pt):
        return _xform_point(pt, piv, sx, sy, ang, dx, dy)

    for key in _XY_FIELDS:
        v = op.get(key)
        if isinstance(v, list) and 2 <= len(v) <= 3 and all(_num(x) for x in v):
            op[key] = move(v)

    # A curved wall is how a facade reads smooth inside the op budget — six arcs
    # per storey beat twenty-four chords. The arc must ride the transform with
    # its endpoints or the compiler's endpoint cross-check refuses the storey.
    arc = op.get("arc")
    if isinstance(arc, dict) and arc.get("curve_type") == "Arc":
        if abs(sx - sy) > 1e-9:
            raise _err(
                "stack.transform: дуговая стена не переносит НЕРАВНОМЕРНОЕ "
                "сужение — дуга стала бы эллипсом, а Revit Arc его не "
                "выражает. Сделай scale_xy_top равным по осям, либо замени "
                "дугу отрезками (у ломаной такого ограничения нет)",
                mid, field_name="arc", got=[sx, sy])
        centre = arc.get("center_mm")
        if isinstance(centre, list) and len(centre) == 3 \
                and all(_num(x) for x in centre):
            arc["center_mm"] = move(centre)
        if _num(arc.get("radius_mm")):
            arc["radius_mm"] = float(arc["radius_mm"]) * sx
        # Axes are DIRECTIONS: they rotate, and they neither scale nor shift.
        for key in ("x_axis", "y_axis"):
            v = arc.get(key)
            if isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v):
                arc[key] = [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]
    contour = op.get("contour")
    outer = contour.get("outer") if isinstance(contour, dict) else None
    if isinstance(outer, dict):
        if outer.get("shape") != "poly":
            raise _err(
                "stack.transform + create_floor_by_contour: контур должен быть "
                "shape='poly' — rect и l не переносят сужение и поворот без "
                "потери смысла; перечисли углы точками", mid,
                got=outer.get("shape"))
        pts = outer.get("points_mm")
        if isinstance(pts, list):
            outer["points_mm"] = [move(p) if isinstance(p, list) and len(p) >= 2
                                  and all(_num(x) for x in p[:2]) else p
                                  for p in pts]


def _expand_stack(m: dict) -> list[dict]:
    mid = _macro_id(m, "stack")
    _closed_fields(m, {"op", "id", "levels", "h_mm", "base_elev_mm",
                       "name_prefix", "floor", "transform"}, mid)
    n = m.get("levels")
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_STACK_LEVELS):
        raise _err(f"stack.levels — целое 1..{MAX_STACK_LEVELS}", mid, got=n)
    h = m.get("h_mm", 3000)
    if not _num(h) or not (1000 <= h <= 10000):
        raise _err("stack.h_mm — число 1000..10000 мм", mid, got=h)
    e0 = m.get("base_elev_mm", 0)
    if not _num(e0):
        raise _err("stack.base_elev_mm — число (мм)", mid, got=e0)
    prefix = m.get("name_prefix", "Level")
    if not isinstance(prefix, str) or len(prefix) > 32:
        raise _err("stack.name_prefix — строка <=32", mid, got=prefix)
    floor = m.get("floor")
    if not isinstance(floor, list) or not floor:
        raise _err("stack.floor — непустой список опов", mid)
    expanded_count = n * (1 + len(floor))
    if expanded_count > MAX_EXPANDED_OPS:
        raise _err(f"stack развернётся в {expanded_count} опов — предел "
                   f"{MAX_EXPANDED_OPS}", mid, got=expanded_count)
    for f in floor:
        if not isinstance(f, dict):
            raise _err("stack.floor: op должен быть объектом", mid)
        if f.get("op") not in _STACKABLE:
            raise _err(f"stack.floor: '{f.get('op')}' не тиражируется по этажам "
                       f"(допустимы {list(_STACKABLE)})", mid, got=f.get("op"))
        if "level" in f:
            raise _err("stack.floor: у опов внутри stack не задаётся level — "
                       "его назначает экспансия", mid, op_id=None)
        if "id" in f and (not isinstance(f.get("id"), str)
                           or not (1 <= len(f["id"]) <= 64)):
            raise _err("stack.floor[].id — строка длиной 1..64", mid,
                       got=f.get("id"))
    tr = _validate_transform(m.get("transform"), mid)
    out: list[dict] = []
    for k in range(1, n + 1):
        out.append({"op": "create_level", "id": f"{mid}_L{k}",
                    "elev_mm": e0 + (k - 1) * h, "name": f"{prefix} {k}"})
    for k in range(1, n + 1):
        frac = (k - 1) / (n - 1) if n > 1 else 0.0
        for f in floor:
            c = copy.deepcopy(f)
            base = c.get("id") or c["op"]
            c["id"] = f"{mid}_L{k}_{base}"
            c["level"] = {"by": "ref", "value": f"{mid}_L{k}"}
            _apply_transform(c, tr, frac, mid)
            # per-storey Z shift for ops whose points carry an explicit Z:
            # points stay storey-local in the macro, absolute after expansion
            for key in _Z_SHIFTED.get(c["op"], ()):
                if isinstance(c.get(key), list) and len(c[key]) == 3 \
                        and all(_num(v) for v in c[key]):
                    c[key] = [c[key][0], c[key][1],
                              c[key][2] + e0 + (k - 1) * h]
            out.append(c)
    return out


def _expand_grid_array(m: dict) -> list[dict]:
    mid = _macro_id(m, "grid_array")
    _closed_fields(m, {"op", "id", "nx", "ny", "dx_mm", "dy_mm",
                       "origin_mm", "margin_mm", "prefix_x", "prefix_y"}, mid)
    nx, ny = m.get("nx", 0), m.get("ny", 0)
    for label, v in (("nx", nx), ("ny", ny)):
        if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= MAX_GRID_AXIS):
            raise _err(f"grid_array.{label} — целое 0..{MAX_GRID_AXIS}", mid, got=v)
    if nx + ny == 0:
        raise _err("grid_array: nx+ny должно быть > 0", mid)
    dx, dy = m.get("dx_mm", 6000), m.get("dy_mm", 6000)
    for label, v in (("dx_mm", dx), ("dy_mm", dy)):
        if not _num(v) or not (100 <= v <= 100000):
            raise _err(f"grid_array.{label} — число 100..100000 мм", mid, got=v)
    origin = m.get("origin_mm", [0, 0])
    if not (isinstance(origin, list) and len(origin) == 2 and all(_num(v) for v in origin)):
        raise _err("grid_array.origin_mm — [x,y] мм", mid, got=origin)
    margin = m.get("margin_mm", 1000)
    if not _num(margin) or not (0 <= margin <= 10000):
        raise _err("grid_array.margin_mm — число 0..10000 мм", mid, got=margin)
    px, py = m.get("prefix_x", ""), m.get("prefix_y", "А")
    for label, v in (("prefix_x", px), ("prefix_y", py)):
        if not isinstance(v, str) or len(v) > 8:
            raise _err(f"grid_array.{label} — строка <=8", mid, got=v)
    ox, oy = origin
    y_span = (ny - 1) * dy if ny > 1 else 0
    x_span = (nx - 1) * dx if nx > 1 else 0
    out = []
    for i in range(nx):    # vertical grids, varying X
        x = ox + i * dx
        out.append({"op": "create_grid", "id": f"{mid}_X{i + 1}",
                    "p0_mm": [x, oy - margin], "p1_mm": [x, oy + y_span + margin],
                    "name": f"{px}{i + 1}"})
    for j in range(ny):    # horizontal grids, varying Y
        y = oy + j * dy
        out.append({"op": "create_grid", "id": f"{mid}_Y{j + 1}",
                    "p0_mm": [ox - margin, y], "p1_mm": [ox + x_span + margin, y],
                    "name": f"{py}{j + 1}"})
    return out


#: Что можно тиражировать в series. Правило членства механическое, как у
#: _STACKABLE, но граница проходит по другому месту: series НЕ создаёт уровней и
#: НЕ переписывает `level` — значит требование «оп принимает level» здесь не
#: нужно, и create_grid, которому в stack отказано как не-поэтажному объекту,
#: сюда входит законно (переменный шаг осей — ровно то, зачем макрос нужен).
#: Остаётся одно ограничение, общее со stack: оп не должен адресовать СОСЕДНИЙ
#: оп по `ref` как хост, потому что экспансия переименовывает id на каждом шаге,
#: и hosted-оп (door/window) навсегда указал бы на шаг 0.
_SERIES_ABLE = _STACKABLE + ("create_grid",)

#: Грамматика ссылки на параметр трека. ЗАКРЫТАЯ, четыре формы, без композиции:
#:     $имя   -$имя   $имя@next   -$имя@next
#: Знак минуса — единственная уступка, и она не арифметика: у симметричного
#: здания зеркальная сторона это ТО ЖЕ ЧИСЛО, прочитанное с другой стороны оси,
#: и без знака модель обязана вести второй трек-двойник, где опечатка делает
#: башню незаметно кривой. Композиции нет и не будет: «-$a + $b» не разбирается,
#: приоритетов нет, вычислителя нет — резолвер это подстановка по таблице из
#: четырёх форм. Как только здесь появится бинарный оператор, 12.3 сломается.
_REF_RE = re.compile(r"^(-?)\$([A-Za-z_][A-Za-z0-9_]{0,31})(@next)?$")


def _parse_ref(s: str):
    """-> (name, negate, use_next) либо None, если строка не ссылка."""
    m = _REF_RE.match(s)
    return (m.group(2), m.group(1) == "-", m.group(3) is not None) if m else None


def _scan_refs(node: Any, found: dict, mid: str) -> None:
    """Собрать {имя: нужен_ли_@next} по шаблону.

    Строка, которая открывается '$' или '-$' и НЕ разбирается, — опечатка, а не
    литерал: отказываем здесь. Иначе '$hwd' уехал бы текстом в числовое поле, и
    модель получила бы отказ компилятора про тип значения — правдивый, но не про
    ту ошибку, которую она сделала."""
    if isinstance(node, dict):
        for v in node.values():
            _scan_refs(v, found, mid)
    elif isinstance(node, list):
        for v in node:
            _scan_refs(v, found, mid)
    elif isinstance(node, str) and (node.startswith("$") or node.startswith("-$")):
        ref = _parse_ref(node)
        if ref is None:
            raise _err(f"series.items: '{node}' похоже на ссылку на параметр "
                       f"трека, но не разбирается. Допустимы ровно четыре формы: "
                       f"$имя, -$имя, $имя@next, -$имя@next", mid, got=node)
        name, _neg, nxt = ref
        found[name] = found.get(name, False) or nxt


def _substitute(node: Any, at_k: dict, at_next: dict) -> Any:
    """Вернуть копию шаблона, где каждая ссылка заменена числом. Ссылки уже
    провалидированы в _scan_refs, имена — в _expand_series."""
    if isinstance(node, dict):
        return {k: _substitute(v, at_k, at_next) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, at_k, at_next) for v in node]
    if isinstance(node, str) and (node.startswith("$") or node.startswith("-$")):
        name, neg, nxt = _parse_ref(node)
        v = (at_next if nxt else at_k)[name]
        return -v if neg else v
    return node


def _tidy(v: float):
    """Округление до 6 знаков + возврат к int, если значение целое.

    Округление: интерполяция даёт 46052.63157894737, а плоский IR читают глазами
    и диффают голденами. 1e-6 мм — нанометр, ниже любого допуска в системе, и
    round детерминирован (одинаковый вход → одинаковый бит).

    Возврат к int — не косметика: без него каждая целая координата уезжает в
    программу как "8000.0", и на башне из 160 балок это ~1.9 КБ чистых ".0".
    Развёрнутый IR — то, что читает человек и во что упирается бюджет байт."""
    r = round(v, 6)
    return int(r) if r == int(r) else r


def _track_at(nodes: list, x: float) -> float:
    """Значение кусочно-линейного трека в точке x. Покрытие уже проверено, так
    что x всегда внутри [первый узел, последний узел] — ветки на концах стоят
    поясом поверх подтяжек и в норме недостижимы."""
    if x <= nodes[0][0]:
        return _tidy(nodes[0][1])
    for (x0, v0), (x1, v1) in zip(nodes, nodes[1:]):
        if x <= x1:
            return _tidy(v0 + (v1 - v0) * (x - x0) / (x1 - x0))
    return _tidy(nodes[-1][1])


def _validate_track(m: dict, mid: str) -> dict:
    """track -> {имя: [(индекс, значение), ...]}, узлы строго по возрастанию."""
    track = m.get("track")
    if not isinstance(track, dict) or not track:
        raise _err("series.track — непустой объект {имя: [[индекс, значение], "
                   "...]}", mid, got=track)
    if len(track) > MAX_TRACK_PARAMS:
        raise _err(f"series.track: параметров {len(track)} — предел "
                   f"{MAX_TRACK_PARAMS}", mid, got=len(track))
    parsed: dict[str, list] = {}
    for name, nodes in track.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", name):
            raise _err(f"series.track: имя параметра '{name}' — латиница/цифры/"
                       f"подчёркивание, 1..32, не с цифры", mid, got=name)
        if not isinstance(nodes, list) or len(nodes) < 2:
            raise _err(f"series.track['{name}'] — минимум ДВА узла: одному узлу "
                       f"нечего интерполировать, это константа, и её место "
                       f"прямо в шаблоне числом", mid, field_name=name, got=nodes)
        if len(nodes) > MAX_TRACK_NODES:
            raise _err(f"series.track['{name}']: узлов {len(nodes)} — предел "
                       f"{MAX_TRACK_NODES}", mid, field_name=name, got=len(nodes))
        out = []
        for node in nodes:
            if not (isinstance(node, list) and len(node) == 2):
                raise _err(f"series.track['{name}']: узел — пара [индекс, "
                           f"значение]", mid, field_name=name, got=node)
            idx, val = node
            if not _num(idx) or not (0 <= idx <= 100000):
                raise _err(f"series.track['{name}']: индекс узла — конечное "
                           f"число 0..100000", mid, field_name=name, got=idx)
            if not _num(val) or abs(val) > 1e9:
                raise _err(f"series.track['{name}']: значение узла — КОНЕЧНОЕ "
                           f"число, |v| <= 1e9", mid, field_name=name, got=val)
            if out and float(idx) <= out[-1][0]:
                raise _err(f"series.track['{name}']: индексы узлов строго по "
                           f"возрастанию (узел {idx} после {out[-1][0]}); равные "
                           f"или убывающие индексы делают значение в точке "
                           f"неоднозначным", mid, field_name=name, got=idx)
            out.append((float(idx), float(val)))
        parsed[name] = out
    return parsed


def _expand_series(m: dict) -> list[dict]:
    """Повтор N раз с интерполяцией именованных параметров по индексу.

    ЗАЧЕМ. stack повторяет этаж, grid_array раскладывает сетку — оба повторяют
    ОДИНАКОВОЕ (stack.transform умеет линейное сужение, но одно на всю башню, от
    низа к верху). Замер 28.07 на башне Эйфеля: силуэт кусочно-линейный, три
    излома, и лучшее возможное ОДНО линейное сужение промахивается на 20.62 м
    (69%) на отметке первой площадки. Выразить это в KIR можно было только
    перечислением: 118 балок литеральными координатами, 7 раундов, ~4 минуты
    набора координат — при том, что 85% времени хода занимает раздумье модели.
    Плечо C# выразило тот же силуэт функцией в три строки. series закрывает
    ровно этот разрыв: за один раунд уезжает больше смысла, а не больше байт.

    ФОРМА ТРЕКА. {имя: [[индекс, значение], ...]} — узлы «индекс → значение»,
    между узлами ЛИНЕЙНАЯ интерполяция. Почему именно эта форма, а не сплайн и
    не формула: кусочно-линейный трек — самая простая вещь, которая покрывает
    все три живых случая одним механизмом (сужение = убывающая полуширина, скат
    = растущая отметка, переменный шаг = неравномерная координата), и при этом
    остаётся ДАННЫМИ. Сплайн потребовал бы решателя, формула — вычислителя;
    и то и другое втащило бы в язык то, что 12.3 держит снаружи.

    ЧТО ВНЕ ДИАПАЗОНА УЗЛОВ. Ничего: трек ОБЯЗАН покрывать каждый индекс, в
    котором его будут читать, иначе отказ. Экстраполяция запрещена (за пределом
    узлов линия уходит в бессмыслицу тем быстрее, чем дальше), зажим к крайнему
    узлу — тоже отказ, а не поведение: трек с узлами до 10 при count=40 дал бы
    30 одинаковых повторов, и модель бы этого не заметила. Молчаливой правки
    здесь нет по тому же правилу, по которому её нет во всём компиляторе.

    СКОЛЬКО ПАРАМЕТРОВ. До MAX_TRACK_PARAMS (8) имён, до MAX_TRACK_NODES (32)
    узлов в каждом. Объявленный, но ни разу не использованный параметр — отказ:
    это либо опечатка с другой стороны, либо мёртвый код в программе, которую
    никто потом не редактирует.

    ПРЕДЕЛ РАЗВЁРТКИ. MAX_SERIES_OPS (200) = count x len(items), отдельное число
    от общепрограммного MAX_EXPANDED_OPS (300) — обоснование при константе.

    ОБРАТНЫЙ ХОД — ОДНОСТОРОННИЙ, и это надо сказать прямо. Разбор чужой модели
    макроса не увидит и увидеть не может: в Revit нет «макросов», есть 160
    отдельных балок, и после экспансии в IR их тоже 160. Ни один декомпайл не
    вернёт из них series — он вернёт перечисление, побайтово то самое, которое
    макрос и был призван заменить. Значит series живёт ТОЛЬКО на пути «модель →
    модель здания», roundtrip на нём не замыкается, и мерить им покрытие разбора
    нельзя. Распознавание регулярности при разборе (увидеть в 160 балках трек) —
    отдельная будущая работа, честно НЕ сделанная здесь: это поиск структуры в
    геометрии, а не обращение функции, и у него своя цена ошибки.
    """
    mid = _macro_id(m, "series")
    _closed_fields(m, {"op", "id", "count", "track", "items"}, mid)

    n = m.get("count")
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_SERIES_COUNT):
        raise _err(f"series.count — целое 1..{MAX_SERIES_COUNT}", mid, got=n)

    items = m.get("items")
    if not isinstance(items, list) or not items:
        raise _err("series.items — непустой список опов", mid)

    expanded_count = n * len(items)
    if expanded_count > MAX_SERIES_OPS:
        raise _err(f"series развернётся в {expanded_count} опов ({n} x "
                   f"{len(items)}) — предел {MAX_SERIES_OPS}. Разбей на "
                   f"несколько series", mid, got=expanded_count)

    seen_base: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            raise _err("series.items: op должен быть объектом", mid, got=it)
        op_name = it.get("op")
        if op_name in MACRO_OPS:
            raise _err(f"series.items: макрос '{op_name}' внутри макроса не "
                       f"разворачивается — вложенность превратила бы экспансию в "
                       f"рекурсию, которой в языке нет (SPEC 12.3)", mid,
                       got=op_name)
        if op_name not in _SERIES_ABLE:
            raise _err(f"series.items: '{op_name}' не тиражируется "
                       f"(допустимы {list(_SERIES_ABLE)})", mid, got=op_name)
        base = it.get("id", op_name)
        if not isinstance(base, str) or not (1 <= len(base) <= 64):
            raise _err("series.items[].id — строка длиной 1..64", mid, got=base)
        if base in seen_base:
            raise _err(f"series.items: повторяющийся id '{base}' — после "
                       f"экспансии два опа на одном шаге получили бы один id",
                       mid, got=base)
        seen_base.add(base)

    # Тело шаблона = всё, кроме op/id: подстановка не должна уметь собирать
    # имя опа или id из числа, а id всё равно назначает экспансия.
    bodies = [{k: v for k, v in it.items() if k not in ("op", "id")}
              for it in items]

    used: dict[str, bool] = {}
    _scan_refs(bodies, used, mid)

    parsed = _validate_track(m, mid)

    unknown = sorted(set(used) - set(parsed))
    if unknown:
        raise _err(f"series.items: ссылка на параметр '{unknown[0]}', которого "
                   f"нет в series.track (объявлены: {sorted(parsed)})", mid,
                   field_name=unknown[0], got=unknown[0])
    unused = sorted(set(parsed) - set(used))
    if unused:
        raise _err(f"series.track: параметр '{unused[0]}' объявлен, но ни разу "
                   f"не использован в items — либо опечатка в ссылке, либо "
                   f"мёртвый трек", mid, field_name=unused[0], got=unused[0])

    for name, needs_next in used.items():
        top = n if needs_next else n - 1
        lo, hi = parsed[name][0][0], parsed[name][-1][0]
        if lo > 0 or hi < top:
            raise _err(
                f"series.track['{name}'] покрывает индексы {lo:g}..{hi:g}, а "
                f"читается на 0..{top} (count={n}"
                f"{', используется @next' if needs_next else ''}). Трек обязан "
                f"покрывать каждый индекс: экстраполяция запрещена, а зажим к "
                f"крайнему узлу дал бы одинаковые повторы молча",
                mid, field_name=name, expected=f"0..{top}", got=f"{lo:g}..{hi:g}")

    out: list[dict] = []
    for k in range(n):
        at_k = {name: _track_at(nodes, k) for name, nodes in parsed.items()}
        at_next = {name: _track_at(parsed[name], k + 1)
                   for name, needs_next in used.items() if needs_next}
        for it, body in zip(items, bodies):
            base = it.get("id", it["op"])
            c = {"op": it["op"], "id": f"{mid}_{k}_{base}"}
            c.update(_substitute(body, at_k, at_next))
            out.append(c)
    return out


_EXPANDERS = {"stack": _expand_stack, "grid_array": _expand_grid_array,
              "series": _expand_series}


@dataclass(frozen=True, slots=True)
class ExpansionOrigin:
    """Source-envelope location of one flat op after macro expansion."""

    source_index: int
    source_op: str | None
    source_id: str | None
    macro_name: str | None = None


def _origin(source_index: int, op: Any, *, macro_name: str | None = None
            ) -> ExpansionOrigin:
    source_op = op.get("op") if isinstance(op, dict) else None
    source_id = op.get("id") if isinstance(op, dict) else None
    if macro_name is not None and source_id is None:
        # Macro expanders use the macro name as their documented default id.
        source_id = macro_name
    return ExpansionOrigin(
        source_index=source_index,
        source_op=source_op if isinstance(source_op, str) else None,
        source_id=source_id if isinstance(source_id, str) else None,
        macro_name=macro_name,
    )


def expand_with_origins(
    ops: Any,
) -> tuple[Any, tuple[ExpansionOrigin, ...]]:
    """Flatten macros and retain a 1:1 source trace for every flat op.

    Non-list input still passes through unchanged so the compiler owns its
    typed shape diagnostic, matching :func:`expand`'s historical contract.
    """
    if not isinstance(ops, list):
        return ops, ()
    has_macros = any(
        isinstance(o, dict) and o.get("op") in MACRO_OPS for o in ops
    )
    if not has_macros:
        return ops, tuple(_origin(i, op) for i, op in enumerate(ops))
    out: list[dict] = []
    origins: list[ExpansionOrigin] = []
    for source_index, o in enumerate(ops):
        if isinstance(o, dict) and o.get("op") in MACRO_OPS:
            macro_name = o["op"]
            expanded = _EXPANDERS[macro_name](o)
            out.extend(expanded)
            origins.extend(
                _origin(source_index, o, macro_name=macro_name)
                for _ in expanded
            )
        else:
            out.append(o)
            origins.append(_origin(source_index, o))
    if len(out) > MAX_EXPANDED_OPS:
        raise _err(f"экспансия макросов превысила бюджет {MAX_EXPANDED_OPS} опов "
                   f"(получилось {len(out)})")
    return out, tuple(origins)


def expand(ops: Any) -> Any:
    """Flatten macros (deterministic), preserving the legacy public API."""
    return expand_with_origins(ops)[0]
