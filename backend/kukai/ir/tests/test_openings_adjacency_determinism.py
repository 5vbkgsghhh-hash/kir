"""СМЕЖНОСТЬ ПРОЁМА НЕ СМЕЛА ЗАВИСЕТЬ ОТ АЛФАВИТА — опровергающие тесты.

`design_check._openings` брал `near[0]`, `near[1]` из списка, отсортированного
ПО ИДЕНТИФИКАТОРУ ПОМЕЩЕНИЯ. Когда точка проёма касалась трёх и более
помещений, пара выбиралась лексикографикой, то есть ПЕРЕИМЕНОВАНИЕ ПОМЕЩЕНИЙ
МЕНЯЛО СМЕЖНОСТЬ ЗДАНИЯ, НЕ МЕНЯЯ ЗДАНИЯ. Смежность идёт ребром в
`checker/graph.py`, оттуда в вывод квартир и в правила эвакуации.

ЗАМЕР 10.08.2026 (прибор — сырой разбор `L0.jsonl`, корпус
`backend/backend/data/decompile`, машинно-локальный):

    двери со степенью >=3   `демо-v3` 66, `k2_ar_rd_v7` 34,
                            `snowdon_plumb_v5` 0, `sob62_r23_v5` 0
    зазор d3-d2             РАСПАДАЕТСЯ НАДВОЕ: либо РОВНО 0.0, либо
                            >= 115.242 мм; в полосе между половинами НЕТ НИ
                            ОДНОГО наблюдения
    ничьих                  `демо-v3` 36 из 66 (54.5 %), `k2_ar_rd_v7` 0 из 34
    окна                    `sob62_r23_v5` 24 из 31 касаются двух помещений,
                            и ВСЕ 24 равноудалены; на прочих зданиях таких нет

Пустая полоса и есть довод против правила «взять две ближайшие»: в 54.5 %
случаев второе место занято вничью, и «ближайшие» снова спросили бы алфавит.
"""
from __future__ import annotations

import unittest

from shapely.geometry import Polygon

from kukai.ir.design_check import (
    BuildWitness,
    ModelSource,
    _adjacent_pair,
    _nearest_room,
    _openings,
)


def _witness():
    return BuildWitness(source=ModelSource.PARSE, building_id="t")


def _square(x0, y0, size=1000.0):
    return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size),
                    (x0, y0 + size)])


class _Op:
    """Проём, каким его видят передаваемые в `_openings` функции доступа."""

    def __init__(self, oid, point):
        self.oid = oid
        self.point = point


def _run(room_polys, *, door_point=(0.0, 0.0), windows=False):
    witness = _witness()
    element = _Op("D1", door_point)
    doors, wins = _openings(
        door_elements=[] if windows else [element],
        window_elements=[element] if windows else [],
        walls_by_id={},
        room_polys=room_polys,
        rooms_by_level={"L1": sorted(room_polys)},
        witness=witness,
        profile=None,
        location_of=lambda e: e.point,
        size_of=lambda e: (900.0, 2100.0),
        host_of=lambda e: None,
        id_of=lambda e: e.oid,
        level_of=lambda e: "L1",
    )
    return (wins if windows else doors), witness


#: Помещение, СОДЕРЖАЩЕЕ точку (0,0) -> расстояние 0.
_CONTAINS = _square(-500.0, -500.0)
#: Помещение на 100 мм восточнее.
_AT_100 = _square(100.0, -500.0)
#: Помещение на 100 мм севернее — РОВНО то же расстояние, что и предыдущее.
_AT_100_TIED = _square(-500.0, 100.0)
#: Помещение на 250 мм севернее — расстояние отличается.
_AT_250 = _square(-500.0, 250.0)


class GeometryDecidesNotTheAlphabet(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ: алфавит и геометрия дают РАЗНЫЕ пары."""

    #: Имена подобраны так, что алфавитный порядок ОБРАТЕН геометрическому:
    #: по алфавиту первые две — "A" (100 мм) и "B" (250 мм), а геометрия
    #: называет "Z" (0 мм) и "A" (100 мм).
    _ROOMS = {"Z": _CONTAINS, "A": _AT_100, "B": _AT_250}

    def test_pair_is_two_nearest_not_two_first_by_name(self) -> None:
        doors, _ = _run(self._ROOMS)
        self.assertEqual(len(doors), 1)
        pair = {doors[0].from_room_id, doors[0].to_room_id}
        self.assertEqual(pair, {"Z", "A"},
                         "пара выбрана сортировкой строк, а не геометрией")
        self.assertNotIn("B", pair)

    def test_renaming_rooms_does_not_move_adjacency(self) -> None:
        """Свойство, ради которого всё: смежность есть факт о ПОСТРОЙКЕ.

        Та же геометрия под другими именами обязана дать ту же пару ПО
        ПОЛОЖЕНИЮ. Прежний код здесь менял ответ.
        """
        first, _ = _run(self._ROOMS)
        renamed = {"A1": _CONTAINS, "Z9": _AT_100, "M5": _AT_250}
        second, _ = _run(renamed)
        by_geometry = {"Z": "A1", "A": "Z9", "B": "M5"}
        expected = {by_geometry[r] for r in
                    (first[0].from_room_id, first[0].to_room_id)}
        self.assertEqual(
            {second[0].from_room_id, second[0].to_room_id}, expected,
            "переименование помещений сдвинуло смежность здания")


class ATieIsNamedNotGuessed(unittest.TestCase):
    """54.5 % случаев `демо-v3`: второе место занято ВНИЧЬЮ."""

    _ROOMS = {"Z": _CONTAINS, "A": _AT_100, "B": _AT_100_TIED}

    def test_second_side_withheld_and_reason_recorded(self) -> None:
        doors, witness = _run(self._ROOMS)
        self.assertEqual(doors[0].from_room_id, "Z",
                         "определённая сторона потеряна с неопределённой")
        self.assertIsNone(doors[0].to_room_id,
                          "вторая сторона выбрана вничью — это снова алфавит")
        codes = {note.code for note in witness.notes}
        self.assertIn("opening_second_side_undecidable", codes)

    def test_note_carries_a_count(self) -> None:
        _doors, witness = _run(self._ROOMS)
        note = next(n for n in witness.notes
                    if n.code == "opening_second_side_undecidable")
        self.assertEqual(note.count, 1)


class TwoRoomsStayUntouched(unittest.TestCase):
    """Обычная дверь между двумя помещениями не должна была измениться."""

    def test_plain_pair_unchanged(self) -> None:
        doors, witness = _run({"Z": _CONTAINS, "A": _AT_100})
        self.assertEqual({doors[0].from_room_id, doors[0].to_room_id},
                         {"Z", "A"})
        self.assertEqual([n.code for n in witness.notes], [])

    def test_single_room_gives_one_side(self) -> None:
        doors, _ = _run({"Z": _CONTAINS})
        self.assertEqual(doors[0].from_room_id, "Z")
        self.assertIsNone(doors[0].to_room_id)


class WindowsAreNamedNotRefused(unittest.TestCase):
    """У окна отказ ОБВИНИЛ БЫ ЗДАНИЕ — выбор уточняется, а не снимается.

    На `room_id` окна стоит HAB030 («в помещении нет окна»). Снять его при
    ничьей значило бы породить ложный BLOCKING — ровно тот класс, против
    которого в чекере v2 заведены `APARTMENT_MARKERS` и оговорки `_caveats`.
    У двери цена обратная: неверное ребро делает правило эвакуации НЕСПОСОБНЫМ
    ОТКАЗАТЬ. Пороги разные, и каждый назван своей ценой.
    """

    def test_window_prefers_nearest_room(self) -> None:
        wins, witness = _run({"Z": _CONTAINS, "A": _AT_100}, windows=True)
        self.assertEqual(wins[0].room_id, "Z")
        self.assertEqual([n.code for n in witness.notes], [])

    def test_window_tie_keeps_a_room_and_names_ambiguity(self) -> None:
        """`sob62_r23_v5`: 24 окна из 31 равноудалены от двух помещений."""
        wins, witness = _run({"A": _AT_100, "B": _AT_100_TIED}, windows=True)
        self.assertIsNotNone(
            wins[0].room_id,
            "окно осталось без помещения — HAB030 обвинит здание")
        self.assertIn("window_room_undecidable",
                      {note.code for note in witness.notes})


class HelpersAreExactAboutTies(unittest.TestCase):
    """Единицы решения — чистые функции, и ничья в них ТОЧНАЯ.

    Порог `_ADJACENCY_TIE_EPS_MM` защищает от шума двоичной арифметики и не
    решает ничего: замеренная полоса между ничьей (0.0) и ближайшим реальным
    зазором (115.242 мм) пуста.
    """

    def test_gap_between_second_and_third_decides(self) -> None:
        self.assertEqual(
            _adjacent_pair([(0.0, "Z"), (40.0, "A"), (155.242, "B")],
                           _witness()), ("Z", "A"))

    def test_tie_at_first_place_still_yields_a_pair(self) -> None:
        """`k2_ar_rd_v7`: d = [40.0, 40.0, 155.242] — пара определена КАК
        МНОЖЕСТВО, хотя внутри неё ничья. Все 34 двери башни таковы."""
        first, second = _adjacent_pair(
            [(40.0, "A"), (40.0, "B"), (155.242, "C")], _witness())
        self.assertEqual({first, second}, {"A", "B"})

    def test_tie_at_second_third_boundary_withholds(self) -> None:
        """`демо-v3`: d = [0.0, 150.0, 150.0] — 36 дверей."""
        self.assertEqual(
            _adjacent_pair([(0.0, "Z"), (150.0, "A"), (150.0, "B")],
                           _witness()), ("Z", None))

    def test_three_way_tie_withholds_both(self) -> None:
        self.assertEqual(
            _adjacent_pair([(0.0, "Z"), (0.0, "A"), (0.0, "B")], _witness()),
            (None, None))

    def test_empty_is_no_sides(self) -> None:
        self.assertEqual(_adjacent_pair([], _witness()), (None, None))
        self.assertIsNone(_nearest_room([], _witness()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
