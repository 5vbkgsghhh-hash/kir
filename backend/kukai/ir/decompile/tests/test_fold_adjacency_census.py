"""ПЕРЕПИСЬ СМЕЖНОСТИ ФОЛДА — 82.6 % дверей выпадали молча.

`fold._semantic_fold` строит ребро смежности ТОЛЬКО когда хозяин двери
ограничивает РОВНО ДВЕ комнаты, а на любом другом числе не делает ничего и не
говорит ничего. Предикат при этом звался «смежностью комнат».

ЗАМЕР 10.08.2026 (сырой разбор `L0.jsonl`, корпус
`backend/backend/data/decompile`, машинно-локальный) — число комнат,
ограниченных хозяином двери:

    `демо-v3`      5 941 дверь: {0: 2816, 1: 154, 2: 1036, 3: 966, 4: 648,
                   5: 50, 6: 76, 7: 25, 8: 55, 9: 113, 30: 1, 34: 1}
                   -> ребро получают 1 036 дверей, 17.4 %
    `k2_ar_rd_v7`  2 096 дверей: {0: 66, 1: 449, 2: 1054, 3: 326, 4: 125,
                   5: 25, 8: 8, 9: 1} -> 50.3 %
    `sob62_r23_v5`   153 двери: {0: 15, 1: 79, 2: 47, 3: 12}

ПОЧЕМУ ИСХОД ДАН ПЕРЕПИСЬЮ, А НЕ ДРУГИМ РЕБРОМ. Форма фолда входит в дайджест:
`merkle._build_merkle_node` считает хеш узла как `_hash_parts(content_json,
edges)`, где `edges` — хеши ДЕТЕЙ. Иная раскладка комнат по контейнерам сдвинула
бы хеш каждого узла выше листьев и обесценила бы сохранённые индексы — дедуп
(×9.96 на Snowdon Plumbing) и отсечение диффом (33 617 поддеревьев на паре
`k2_ar_rd_v7`->`v8`). При этом `BuildingState` НЕ пострадал бы: это
мультимножество `canon_op` ЛИСТЬЕВ, а листья держит `assert_preservation`,
поэтому воспроизведение журнала (18/18, 5/5, 3/3, 2/2) и `merge3` к форме
контейнеров нечувствительны.

Поэтому перепись считает то, о чём фолд молчал, и НЕ ТРОГАЕТ дерево, а
типизированное ребро-опровержение живёт в `building_graph`.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.fold import (
    FoldError,
    RoomAdjacencyCensus,
    room_adjacency_census,
)
from kukai.ir.decompile.schema import GeometryKind, L0Element, RoomInfo


def _door(source_id, host_id):
    return {"kind": "op", "_id": f"op:{source_id}",
            "source_element_id": source_id, "level_name": None,
            "anchor_mm": None, "op": "create_door", "params": {}}


def _element(element_id, category, host_id=None):
    return L0Element(
        element_id=element_id, category=category, category_ru="",
        type_id="t", type_name="T", level_id=None, level_name=None,
        # ВИД ГЕОМЕТРИИ ОБЪЯВЛЯЛСЯ ОДИН, А НЕСЁЛСЯ ДРУГОЙ. Здесь стояло
        # `POINT` при `p0_mm=None`, то есть «точка без точки»; схема этого не
        # допускает (`point geometry requires only p0_mm`) и шесть тестов
        # переписи падали на конструкторе, не дойдя ни до одной проверки —
        # то есть файл шесть раз сообщал не о том, что проверяет.
        # Тесту геометрия безразлична — он про смежность и перепись, — и
        # ровно эту форму схема называет `BBOX_ONLY`: все три поля точки и
        # кривой пусты. Объявляем то, что несём.
        # И ВТОРАЯ ПОЛОВИНА, БЕЗ КОТОРОЙ ПЕРВАЯ ЧИТАЕТСЯ КАК ПОСЛАБЛЕНИЕ:
        # `POINT` без `p0_mm` — НЕВЕРНАЯ строка L0, и прод-схема обязана
        # отвергать её и дальше. Чинилась фикстура, а не правило.
        # (Две сессии пришли к этой правке независимо и написали её
        # одинаково; обе половины комментария сведены при слиянии.)
        geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=host_id)


def _room(room_id, bounds):
    return RoomInfo(id=room_id, name=room_id, level_id=None, level_name=None,
                    area_m2=1.0, boundary_mm=(), boundary_loops_mm=(),
                    bounding_element_ids=tuple(bounds))


class CensusCountsWhatFoldWasSilentAbout(unittest.TestCase):
    """Ключ 2 — единственный, дающий ребро. Все прочие суть НАЗВАННЫЙ исход."""

    def _census(self, degrees):
        """degrees: сколько комнат ограничивает хозяин каждой двери."""
        nodes, elements, rooms = [], {}, []
        for index, degree in enumerate(degrees):
            door_id, host_id = f"D{index}", f"W{index}"
            nodes.append(_door(door_id, host_id))
            elements[door_id] = _element(door_id, "OST_Doors", host_id)
            elements[host_id] = _element(host_id, "OST_Walls")
            for room_index in range(degree):
                rooms.append(_room(f"R{index}_{room_index}", [host_id]))
        return room_adjacency_census(nodes, rooms, elements)

    def test_exactly_two_is_the_only_edge_building_degree(self) -> None:
        census = self._census([2, 2, 3])
        self.assertEqual(census.edges_built, 2)
        self.assertEqual(census.refuted, 1)
        self.assertEqual(census.by_degree, {2: 2, 3: 1})

    def test_zero_bounded_rooms_is_counted_not_dropped(self) -> None:
        """2 816 дверей `демо-v3` попадают ровно сюда."""
        census = self._census([0, 0, 2])
        self.assertEqual(census.by_degree[0], 2)
        self.assertEqual(census.refuted, 2)
        self.assertEqual(census.edges_built, 1)

    def test_high_degree_survives_as_a_number(self) -> None:
        """У `демо-v3` есть хозяин, ограничивающий 34 комнаты."""
        census = self._census([34])
        self.assertEqual(census.by_degree, {34: 1})
        self.assertEqual(census.edges_built, 0)

    def test_census_balances(self) -> None:
        census = self._census([0, 1, 2, 3, 4])
        census.assert_balanced()
        self.assertEqual(census.doors_seen, 5)
        self.assertEqual(census.doors_with_host, 5)

    def test_door_without_a_host_is_its_own_named_bucket(self) -> None:
        nodes = [_door("D1", None)]
        elements = {"D1": _element("D1", "OST_Doors", None)}
        census = room_adjacency_census(nodes, [], elements)
        self.assertEqual(census.doors_without_host, 1)
        self.assertEqual(census.doors_with_host, 0)
        census.assert_balanced()

    def test_non_doors_are_not_counted_at_all(self) -> None:
        nodes = [_door("W1", None)]
        elements = {"W1": _element("W1", "OST_Walls")}
        census = room_adjacency_census(nodes, [], elements)
        self.assertEqual(census.doors_seen, 0)


class UnbalancedCensusIsUnconstructible(unittest.TestCase):
    """Перепись, которая не сходится, врёт молча так же, как врал бы фолд."""

    def test_mismatched_totals_refuse(self) -> None:
        census = RoomAdjacencyCensus(doors_seen=10, doors_without_host=1,
                                     by_degree={2: 3})
        with self.assertRaises(FoldError):
            census.assert_balanced()


class TheRatioThisExistsToShow(unittest.TestCase):
    """Доля, ради которой перепись и написана."""

    def test_demo_v3_shape_reproduces_the_measured_ratio(self) -> None:
        degrees = ([0] * 2816 + [1] * 154 + [2] * 1036 + [3] * 966
                   + [4] * 648 + [5] * 50 + [6] * 76 + [7] * 25 + [8] * 55
                   + [9] * 113 + [30] + [34])
        self.assertEqual(len(degrees), 5941)
        census = RoomAdjacencyCensus(
            doors_seen=5941, doors_without_host=0,
            by_degree={d: degrees.count(d) for d in set(degrees)})
        census.assert_balanced()
        self.assertEqual(census.edges_built, 1036)
        self.assertEqual(census.refuted, 4905)
        share = census.edges_built / census.doors_seen
        self.assertAlmostEqual(share, 0.1744, places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
