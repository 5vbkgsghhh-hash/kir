"""OPENING ADJACENCY MUST NOT DEPEND ON THE ALPHABET — disproving tests.

`design_check._openings` took `near[0]`, `near[1]` from a list sorted BY ROOM
IDENTIFIER. When an opening's point touched three or more rooms, the pair was
chosen by lexicography, meaning RENAMING ROOMS CHANGED THE BUILDING'S
ADJACENCY WITHOUT CHANGING THE BUILDING. Adjacency becomes an edge in
`checker/graph.py`, and from there feeds apartment inference and evacuation
rules.

MEASURED 10.08.2026 (instrument: raw decompilation of `L0.jsonl`, corpus
`backend/backend/data/decompile`, machine-local):

    doors with degree >=3   `демо-v3` 66, `k2_ar_rd_v7` 34,
                            `snowdon_plumb_v5` 0, `sob62_r23_v5` 0
    gap d3-d2               SPLITS IN TWO: either EXACTLY 0.0, or
                            >= 115.242 mm; the strip between the halves has
                            NOT A SINGLE observation
    ties                    `демо-v3` 36 of 66 (54.5%), `k2_ar_rd_v7` 0 of 34
    windows                 `sob62_r23_v5` 24 of 31 touch two rooms,
                            and ALL 24 are equidistant; no other building has
                            any like this

The empty strip is itself the argument against a "take the two nearest" rule:
in 54.5% of cases the second place is tied, and "nearest" would again be
asking the alphabet.
"""
from __future__ import annotations

import unittest

from shapely.geometry import Polygon

from kir.design_check import (
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
    """An opening as seen by the accessor functions passed into
    `_openings`."""

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


#: The room CONTAINING point (0,0) -> distance 0.
_CONTAINS = _square(-500.0, -500.0)
#: A room 100 mm to the east.
_AT_100 = _square(100.0, -500.0)
#: A room 100 mm to the north — EXACTLY the same distance as the previous one.
_AT_100_TIED = _square(-500.0, 100.0)
#: A room 250 mm to the north — the distance differs.
_AT_250 = _square(-500.0, 250.0)


class GeometryDecidesNotTheAlphabet(unittest.TestCase):
    """DISPROVING CASE: alphabet and geometry give DIFFERENT pairs."""

    #: Names are chosen so the alphabetical order is the REVERSE of the
    #: geometric one: alphabetically the first two are "A" (100 mm) and "B"
    #: (250 mm), while geometry names "Z" (0 mm) and "A" (100 mm).
    _ROOMS = {"Z": _CONTAINS, "A": _AT_100, "B": _AT_250}

    def test_pair_is_two_nearest_not_two_first_by_name(self) -> None:
        doors, _ = _run(self._ROOMS)
        self.assertEqual(len(doors), 1)
        pair = {doors[0].from_room_id, doors[0].to_room_id}
        self.assertEqual(pair, {"Z", "A"},
                         "пара выбрана сортировкой строк, а не геометрией")
        self.assertNotIn("B", pair)

    def test_renaming_rooms_does_not_move_adjacency(self) -> None:
        """The property everything is for: adjacency is a fact about the
        BUILD.

        The same geometry under different names must give the same pair BY
        POSITION. The old code changed the answer here.
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
    """54.5% of `демо-v3` cases: the second place is a TIE."""

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
    """An ordinary door between two rooms must not have changed."""

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
    """For a window a refusal WOULD BLAME THE BUILDING — the choice is
    refined, not dropped.

    The window's `room_id` carries HAB030 ("no window in the room"). Dropping
    it on a tie would spawn a false BLOCKING — exactly the class the v2
    checker's `APARTMENT_MARKERS` and `_caveats` exceptions exist against.
    For a door the cost runs the other way: a wrong edge makes the
    evacuation rule UNABLE TO REFUSE. The thresholds differ, and each is
    named for its own cost.
    """

    def test_window_prefers_nearest_room(self) -> None:
        wins, witness = _run({"Z": _CONTAINS, "A": _AT_100}, windows=True)
        self.assertEqual(wins[0].room_id, "Z")
        self.assertEqual([n.code for n in witness.notes], [])

    def test_window_tie_keeps_a_room_and_names_ambiguity(self) -> None:
        """`sob62_r23_v5`: 24 of 31 windows are equidistant from two rooms."""
        wins, witness = _run({"A": _AT_100, "B": _AT_100_TIED}, windows=True)
        self.assertIsNotNone(
            wins[0].room_id,
            "окно осталось без помещения — HAB030 обвинит здание")
        self.assertIn("window_room_undecidable",
                      {note.code for note in witness.notes})


class HelpersAreExactAboutTies(unittest.TestCase):
    """The decision units are pure functions, and a tie inside them is
    EXACT.

    The `_ADJACENCY_TIE_EPS_MM` threshold guards against binary-arithmetic
    noise and decides nothing: the measured strip between a tie (0.0) and
    the nearest real gap (115.242 mm) is empty.
    """

    def test_gap_between_second_and_third_decides(self) -> None:
        self.assertEqual(
            _adjacent_pair([(0.0, "Z"), (40.0, "A"), (155.242, "B")],
                           _witness()), ("Z", "A"))

    def test_tie_at_first_place_still_yields_a_pair(self) -> None:
        """`k2_ar_rd_v7`: d = [40.0, 40.0, 155.242] — the pair is defined AS
        A SET, even though it contains a tie internally. All 34 doors of the
        tower are like this."""
        first, second = _adjacent_pair(
            [(40.0, "A"), (40.0, "B"), (155.242, "C")], _witness())
        self.assertEqual({first, second}, {"A", "B"})

    def test_tie_at_second_third_boundary_withholds(self) -> None:
        """`демо-v3`: d = [0.0, 150.0, 150.0] — 36 doors."""
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
