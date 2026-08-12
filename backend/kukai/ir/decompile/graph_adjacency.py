"""ПРЕДИКАТ B смежности комнат — `opening_point_touches_room`, и почему он
ОБЯЗАН называться иначе, чем предикат A.

Одно слово на два разных предиката — дефект того же класса, что зелёный
свидетель по непрочитанной оси: обе стороны уверены, что говорят об одном, и
расхождение читается как факт о здании, а не как ошибка в нас.

═══════════════════════════════════════════════════════════════════════════
ЗАМЕР (10.08.2026, прибор — сырой разбор `L0.jsonl`, корпус
`backend/backend/data/decompile`, машинно-локальный)
═══════════════════════════════════════════════════════════════════════════

A = `bounded_by_same_wall` (`fold._semantic_fold`): комнаты, ограниченные
    ХОЗЯИНОМ двери; ребро только при РОВНО двух.
B = `opening_point_touches_room` (`design_check._openings.touching`): комнаты,
    чей полигон в 300 мм (`OPENING_JOIN_TOL_MM`) от ТОЧКИ двери.

| здание | дверей | A рёбер | B рёбер | общих | ЖАККАР | только A | только B |
|---|---|---|---|---|---|---|---|
| `демо` (демо-v3)              | 5 941 | 1 035 | 3 272 | 963 | **0.288** | 72 | 2 309 |
| `13A-RD-AR-K2_v33` (v7)       | 2 096 |   975 | 1 438 | 950 | **0.649** | 25 |   488 |
| `Snowdon …Architectural` (v5) |   143 |    22 |    23 |  11 | **0.324** | 11 |    12 |
| `SOB6.2…AR_R23` (v5)          |   153 |    40 |   117 |  35 | **0.287** |  5 |    82 |

**Жаккар НЕ константа — он гуляет 0.287 … 0.649.** Расхождение идёт в ОБЕ
стороны на каждом здании, то есть ни один предикат не является огрублением
другого: это два разных вопроса. A спрашивает «объявил ли Revit, что эта стена
разделяет две комнаты»; B спрашивает «стоит ли точка проёма у полигонов двух
комнат». Совпадать они не обязаны и не будут.

═══════════════════════════════════════════════════════════════════════════
ДЕФЕКТ ВНУТРИ B, найденный по дороге (Ш5): МОЛЧАЛИВОЕ УСЕЧЕНИЕ ДО ДВУХ
═══════════════════════════════════════════════════════════════════════════

`design_check._openings` берёт `near = sorted(touching(...))` и заполняет
`from_room_id=near[0]`, `to_room_id=near[1] if len(near) > 1`. Когда точка
касается ТРЁХ и более комнат, две выбираются **по алфавитному порядку
идентификатора комнаты** — величине, не имеющей отношения ни к геометрии, ни к
зданию. Третья и далее исчезают молча.

Замер, сколько дверей попадают в эту ветку:

    `демо-v3`      распределение {0: 52, 1: 1211, 2: 3307, 3: 65, 4: 1}
                   → **66 дверей усечены** (плюс 1 305 дверей вообще без точки)
    `k2_ar_rd_v7`  распределение {0: 42, 1: 573, 2: 1447, 3: 34}
                   → **34 двери усечены**

Сотня дверей на двух зданиях — немного, и НЕ размер здесь довод. Довод в том,
что выбор пары ЗАВИСИТ ОТ СТРОКОВОГО ПОРЯДКА ИДЕНТИФИКАТОРОВ: перенумеруй
комнаты — и смежность здания изменится, не изменившись. Это ровно «граница,
заведённая рассуждением, а не замером», только в форме сортировки.

Здесь усечения нет вовсе: ребро выпускается на КАЖДУЮ пару касаемых комнат, а
их число едет в свидетельстве. Пара, выбранная сортировкой, не выпускается
никогда.

Второй факт того же рода: **1 305 дверей `демо-v3` (22.0 %) не имеют ни точки,
ни рамки**, и в `design_check` они молча выпадают из смежности. Здесь они
получают названный отказ `opening_without_position`.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping

from kukai.ir.decompile.building_graph import (
    GraphBuildError,
    GraphEdge,
    Modality,
    Relation,
)

__all__ = [
    "OPENING_JOIN_TOL_MM",
    "REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO",
    "AdjacencyCensus",
    "opening_point_touches_room_edges",
]

#: Тот же допуск, что у `design_check.OPENING_JOIN_TOL_MM` — величина
#: НАЗНАЧЕННАЯ, не выведенная; повторена здесь ссылкой на владельца, чтобы два
#: предиката не разъехались по допуску молча.
OPENING_JOIN_TOL_MM: float = 300.0

#: Правила, снимающие ребро предиката B. Опровергнутое ребро ОСТАЁТСЯ.
REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO = "opening_touches_fewer_than_two_rooms"
REFUSAL_NO_POSITION = "opening_without_position"
REFUSAL_NO_LEVEL = "opening_without_level"
REFUSAL_NO_MEASURED_ROOMS_ON_LEVEL = "no_measured_room_polygons_on_level"


@dataclass(frozen=True, slots=True)
class AdjacencyCensus:
    """Скольких проёмов предикат КОСНУЛСЯ — без этого «смежности нет» пусто.

    Закон тот же, что у переписи CLASH: ответ «рёбер нет» ничего не значит,
    пока не сказано, скольких проёмов поиск коснулся и почему остальные выпали.
    """

    openings_seen: int
    openings_evaluated: int
    refusals: Mapping[str, int]
    touch_degree: Mapping[int, int]

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    def assert_balanced(self) -> None:
        if self.openings_evaluated + self.refused != self.openings_seen:
            raise GraphBuildError(
                f"перепись смежности не сходится: проёмов {self.openings_seen}, "
                f"оценено {self.openings_evaluated}, названных отказов "
                f"{self.refused}")

    @property
    def truncated_by_design_check(self) -> int:
        """Сколько проёмов `design_check` усёк бы до двух комнат сортировкой."""
        return sum(count for degree, count in self.touch_degree.items()
                   if degree >= 3)


def _polygon(boundary: Any):
    from shapely.geometry import Polygon
    if not boundary or len(boundary) < 3:
        return None
    poly = Polygon([(float(x), float(y)) for x, y in boundary])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type == "MultiPolygon":
        if poly.is_empty:
            return None
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.is_empty or poly.area <= 0.0:
        return None
    return poly


def _position(element: Mapping[str, Any]) -> tuple[float, float] | None:
    """Точка проёма: `p0_mm`, а если её нет — ЦЕНТР ПРОЧИТАННОГО bbox.

    Запасной ход — не догадка о Revit, а середина того самого ящика, который
    вернуло чтение (замер 03.08: все 49 окон башни сняты `bbox_only`). Провенанс
    едет в свидетельстве ребра, а не теряется.
    """
    p0 = element.get("p0_mm")
    if p0 is not None:
        return float(p0[0]), float(p0[1])
    lo, hi = element.get("bbox_min_mm"), element.get("bbox_max_mm")
    if lo is not None and hi is not None:
        return ((float(lo[0]) + float(hi[0])) / 2.0,
                (float(lo[1]) + float(hi[1])) / 2.0)
    return None


def opening_point_touches_room_edges(
    header: Mapping[str, Any],
    elements: Mapping[str, Mapping[str, Any]],
    *,
    opening_categories: Iterable[str] = ("OST_Doors",),
    tol_mm: float = OPENING_JOIN_TOL_MM,
) -> tuple[tuple[GraphEdge, ...], AdjacencyCensus]:
    """ПРЕДИКАТ B, без усечения до двух и без молчаливых выпадений.

    Возвращает рёбра и перепись. Каждый проём попадает ЛИБО в оценённые, ЛИБО в
    названный отказ — третьего не предусмотрено, и `assert_balanced` это держит.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    wanted = frozenset(opening_categories)
    rooms = [r for r in (header.get("rooms") or []) if isinstance(r, Mapping)]
    polys: dict[str, Any] = {}
    level_of_room: dict[str, Any] = {}
    for room in rooms:
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        poly = _polygon(room.get("boundary_mm"))
        if poly is None:
            continue
        polys[room_id] = poly
        level_of_room[room_id] = room.get("level_id")

    per_level: dict[Any, list[str]] = defaultdict(list)
    for room_id in polys:
        per_level[level_of_room.get(room_id)].append(room_id)
    trees: dict[Any, tuple[list[str], Any]] = {}
    for level_id, room_ids in per_level.items():
        room_ids.sort()
        trees[level_id] = (room_ids, STRtree([polys[r] for r in room_ids]))

    edges: list[GraphEdge] = []
    refusals: Counter[str] = Counter()
    degree: Counter[int] = Counter()
    seen = 0
    evaluated = 0

    for node_id in sorted(elements):
        element = elements[node_id]
        if element.get("category") not in wanted:
            continue
        seen += 1

        point = _position(element)
        if point is None:
            refusals[REFUSAL_NO_POSITION] += 1
            continue
        host = element.get("host_id")
        level_id = element.get("level_id")
        if not level_id and isinstance(host, str):
            level_id = (elements.get(host) or {}).get("level_id")
        if not level_id:
            refusals[REFUSAL_NO_LEVEL] += 1
            continue
        got = trees.get(level_id)
        if got is None:
            refusals[REFUSAL_NO_MEASURED_ROOMS_ON_LEVEL] += 1
            continue

        room_ids, tree = got
        pt = Point(point)
        probe = pt.buffer(tol_mm)
        near: list[str] = []
        for index in tree.query(probe):
            room_id = room_ids[int(index)]
            poly = polys[room_id]
            if poly.exterior.distance(pt) <= tol_mm or poly.contains(pt):
                near.append(room_id)
        near.sort()
        evaluated += 1
        degree[len(near)] += 1

        provenance = ("p0_mm" if element.get("p0_mm") is not None
                      else "bbox_centre")
        if len(near) < 2:
            # НАЗВАННОЕ опровержение: «коснулись и не хватило» отличимо от
            # «не смотрели». `design_check` здесь молчит.
            edges.append(GraphEdge(
                relation=Relation.OPENING_POINT_TOUCHES_ROOM,
                src=node_id, dst=(near[0] if near else node_id),
                modality=Modality.REFUTED,
                refuted_by=REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO,
                evidence={"source": "design_check._openings predicate",
                          "rooms_touched": len(near), "tol_mm": tol_mm,
                          "position_from": provenance}))
            continue

        # БЕЗ УСЕЧЕНИЯ: ребро на каждую пару, число касаний — в свидетельстве.
        # `design_check` взял бы near[0], near[1] — пару, выбранную алфавитом.
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                edges.append(GraphEdge(
                    relation=Relation.OPENING_POINT_TOUCHES_ROOM,
                    src=near[i], dst=near[j], modality=Modality.PROVEN,
                    evidence={"source": "design_check._openings predicate",
                              "opening": node_id, "rooms_touched": len(near),
                              "tol_mm": tol_mm, "position_from": provenance}))

    census = AdjacencyCensus(openings_seen=seen, openings_evaluated=evaluated,
                             refusals=dict(refusals), touch_degree=dict(degree))
    census.assert_balanced()
    return tuple(edges), census
