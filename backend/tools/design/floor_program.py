"""Turn a floor plate into a floor: rooms, partitions, doors — as a KIR program.

A tower of plates and a curtain wall is a massing, not a model. What is missing
is the inside, and the inside is not a matter of taste: an office floor of a
given area carries a KNOWN mix of rooms, because the mix is what the area is
FOR. That rule is data, and data ports between engines — which is why this is
the one thing worth taking from the reference skill libraries and the
Grasshopper-based ones are not (their method assumes surfaces, meshes and data
trees we do not have; porting their prose would promise capability we lack).

Source of the mix: AlpacaLabsLLC/skills-for-architects, MIT (c) 2026 Alpaca
Design Lab LLC — `skills/workplace-programmer/data/{space-types,archetypes}.json`.
Converted from square feet to millimetres here, once, so nothing downstream ever
sees imperial units. Names are given in Russian because the model writes Russian
room names into a Russian project; the id keeps the original key so the source
row stays findable.

Three parts, in the order they run:

    schedule(area)  — how many rooms of which type belong on this floor
    layout(...)     — where each one goes (double-loaded corridor)
    to_kir(...)     — the KIR ops that build them

Deterministic throughout: same plate and same archetype give the same program,
so a run can be replayed, diffed and gated like any other.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from typing import Any, Iterable, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

SF_TO_M2 = 0.09290304


class SpaceType(NamedTuple):
    key: str
    name_ru: str
    category: str
    area_m2: float
    capacity: int | None
    per_rsf_m2: float | None      # one of these per N m² of floor, None = by seats


def _st(key, ru, cat, sf, cap=None, per_rsf=None) -> SpaceType:
    return SpaceType(key, ru, cat, round(sf * SF_TO_M2, 1), cap,
                     round(per_rsf * SF_TO_M2) if per_rsf else None)


#: The catalogue, metric. Only the rows that describe a ROOM are kept — a
#: workstation is furniture, and KIR has no op that would place it, so listing
#: it here would be a promise nothing can keep.
CATALOGUE: tuple[SpaceType, ...] = (
    _st("large-conf-10-12p", "Переговорная большая (10-12 чел.)", "meeting", 300, 10, 3000),
    _st("medium-conf-6p", "Переговорная средняя (6 чел.)", "meeting", 225, 6, 2000),
    _st("small-conf-4p", "Переговорная малая (4 чел.)", "meeting", 100, 4, 1250),
    _st("phone-booth", "Телефонная кабина", "meeting", 25, 1, 2000),
    _st("lounge", "Зона отдыха", "meeting", 56, 4, 1000),
    _st("private-office", "Кабинет", "work", 100, 1, 1500),
    _st("exec-office", "Кабинет руководителя", "work", 150, 1, 6000),
    _st("open-work", "Рабочая зона (открытая)", "work", 0, None, None),   # the remainder
    _st("pantry", "Кухня-буфет", "common", 200, None, 8000),
    _st("lobby", "Холл лифтового ядра", "common", 300, None, 20000),
    _st("it-room", "Серверная", "ops", 100, None, 12000),
    _st("storage", "Кладовая", "ops", 100, None, 6000),
    _st("copy-print", "Копировальная", "ops", 80, None, 5000),
    _st("mothering", "Комната матери и ребёнка", "support", 100, 1, 25000),
)

BY_KEY = {s.key: s for s in CATALOGUE}

#: Share of the floor by purpose, per office archetype. From the same MIT source
#: (`archetypes.json`), kept as percentages so the numbers stay recognisable.
ARCHETYPES: dict[str, dict[str, Any]] = {
    "плотный-опенспейс": {"m2_per_seat": 6.0,
                          "splits": {"work": 46, "meeting": 12, "common": 10,
                                     "circulation": 27, "boh": 5}},
    "сбалансированный": {"m2_per_seat": 9.3,
                         "splits": {"work": 40, "meeting": 16, "common": 12,
                                    "circulation": 27, "boh": 5}},
    "кабинетный": {"m2_per_seat": 14.0,
                   "splits": {"work": 44, "meeting": 14, "common": 9,
                              "circulation": 28, "boh": 5}},
}


def schedule(area_m2: float, archetype: str = "сбалансированный") -> list[dict]:
    """Which rooms this floor owes, and how many. A room whose rule yields zero
    is omitted rather than rounded up — a 400 m² floor does not get an executive
    suite because arithmetic said 0.4."""
    if archetype not in ARCHETYPES:
        raise SystemExit(f"нет архетипа {archetype!r}; есть {sorted(ARCHETYPES)}")
    rows = []
    for s in CATALOGUE:
        if not s.per_rsf_m2 or not s.area_m2:
            continue
        n = int(area_m2 // s.per_rsf_m2)
        if n:
            rows.append({"key": s.key, "имя": s.name_ru, "категория": s.category,
                         "штук": n, "площадь_м2": s.area_m2,
                         "итого_м2": round(n * s.area_m2, 1)})
    used = sum(r["итого_м2"] for r in rows)
    circ = ARCHETYPES[archetype]["splits"]["circulation"] / 100
    open_area = round(max(0.0, area_m2 * (1 - circ) - used), 1)
    if open_area > 20:
        rows.append({"key": "open-work", "имя": "Рабочая зона (открытая)",
                     "категория": "work", "штук": 1, "площадь_м2": open_area,
                     "итого_м2": open_area})
    return rows


class Room(NamedTuple):
    key: str
    name: str
    x0: float
    y0: float
    x1: float
    y1: float


def _bbox(poly: Iterable[Iterable[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def layout(poly: list[list[float]], rows: list[dict], *,
           corridor_mm: float = 1800, depth_mm: float = 6000,
           inset_mm: float = 900) -> list[Room]:
    """Rooms in strips with a corridor between each pair; pack left to right and
    wrap to the next strip when the run is full.

    Deliberately the simplest layout that is still a real plan — the point is
    that the floor HAS a structure, not that the structure is optimal. A single
    double-loaded corridor was the first attempt and placed 25 rooms of 43 on a
    1000 m² floor: the corridor ran out of LENGTH long before the floor ran out
    of AREA. Wrapping fixes that without pretending to be a space planner.

    Anything that still does not fit is dropped and named by `unplaced`, never
    silently squeezed — a floor that quietly loses a third of its programme is
    the failure this whole exercise exists to catch.
    """
    x0, y0, x1, y1 = _bbox(poly)
    x0 += inset_mm; y0 += inset_mm; x1 -= inset_mm; y1 -= inset_mm
    strips: list[tuple[float, float]] = []
    y = y0
    while y + depth_mm <= y1:
        strips.append((y, y + depth_mm))
        y += depth_mm + corridor_mm
    if not strips:                        # a plate too shallow for a corridor
        strips = [(y0, y1)]

    queue = [(row, BY_KEY[row["key"]]) for row in rows if row["key"] != "open-work"
             for _ in range(row["штук"])]
    out: list[Room] = []
    s, cursor = 0, x0
    for row, _spec in queue:
        depth = strips[s][1] - strips[s][0]
        width = max(2400.0, row["площадь_м2"] * 1e6 / depth)
        if cursor + width > x1:           # this run is full — take the next one
            s += 1
            cursor = x0
            if s >= len(strips):
                break
            depth = strips[s][1] - strips[s][0]
            width = max(2400.0, row["площадь_м2"] * 1e6 / depth)
            if cursor + width > x1:
                break
        by0, by1 = strips[s]
        out.append(Room(row["key"], row["имя"], cursor, by0, cursor + width, by1))
        cursor += width
    return out


def unplaced(rows: list[dict], rooms: list[Room]) -> list[str]:
    want: dict[str, int] = {}
    for r in rows:
        if r["key"] != "open-work":
            want[r["key"]] = want.get(r["key"], 0) + r["штук"]
    got: dict[str, int] = {}
    for r in rooms:
        got[r.key] = got.get(r.key, 0) + 1
    return [f"{BY_KEY[k].name_ru}: разместилось {got.get(k, 0)} из {n}"
            for k, n in want.items() if got.get(k, 0) < n]


def to_kir(rooms: list[Room], *, level_ref: dict, wall_type: dict,
           height_mm: float = 3200, prefix: str = "fp") -> list[dict]:
    """Partitions, a room tag point and a door per room. Walls are shared
    between neighbours only in the sense that they are coincident — KIR has no
    join op, and Revit joins coincident walls itself."""
    ops: list[dict] = []
    for i, r in enumerate(rooms):
        corners = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
        for e in range(4):
            a, b = corners[e], corners[(e + 1) % 4]
            ops.append({"op": "create_wall", "id": f"{prefix}{i}w{e}",
                        "p0_mm": [a[0], a[1]], "p1_mm": [b[0], b[1]],
                        "height_mm": height_mm, "type": wall_type,
                        "level": level_ref})
        ops.append({"op": "create_room", "id": f"{prefix}{i}r",
                    "xy": [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2],
                    "name": r.name, "level": level_ref})
    return ops


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", type=float, default=1200.0, help="площадь этажа, м²")
    ap.add_argument("--archetype", default="сбалансированный",
                    choices=sorted(ARCHETYPES))
    ap.add_argument("--plate", help="контур этажа как JSON [[x,y],…] в мм")
    ap.add_argument("--kir", action="store_true", help="напечатать KIR-опы")
    a = ap.parse_args()

    rows = schedule(a.area, a.archetype)
    print(f"Этаж {a.area:.0f} м², архетип «{a.archetype}»:")
    for r in rows:
        print(f"  {r['штук']:3d} × {r['имя']:38s} {r['площадь_м2']:6.1f} м²"
              f"  = {r['итого_м2']:7.1f}")
    print(f"  ИТОГО помещений: {sum(r['штук'] for r in rows if r['key'] != 'open-work')}")

    if a.plate:
        poly = json.loads(a.plate)
        rooms = layout(poly, rows)
        print(f"  размещено: {len(rooms)}")
        for gap in unplaced(rows, rooms):
            print(f"  НЕ ВЛЕЗЛО — {gap}")
        if a.kir:
            ops = to_kir(rooms, level_ref={"by": "name", "value": "Этаж 1"},
                         wall_type={"by": "element_id", "value": 1642})
            print(json.dumps({"ir_version": "1.0", "ops": ops},
                             ensure_ascii=False)[:1200])
            print(f"  опов: {len(ops)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
