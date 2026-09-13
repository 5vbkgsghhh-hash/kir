"""ADJACENCY REFUSALS WERE COMPUTED AND THROWN AWAY (RV-03).

MEASURED (04.09.2026). `graph_from_l0(..., room_adjacency=True)` was
calling predicate B and taking TWO values from it:

    adjacency_edges, _adjacency_census = opening_point_touches_room_edges(…)

The edges reached the graph; the census went into a `_` variable and
vanished. A door with no `p0` and no `bbox` gives ZERO edges and a NAMED
refusal `opening_without_position` — the refusal was computed and
reached nowhere. In the graph, the source meanwhile remains "measured"
(`room_adjacency` does not land in `sources_absent`), meaning zero edges
was read as a fact about the BUILDING, and the artifact on disk froze it
as such.

This is exactly the class `sources_absent` stands guard against in the
same file, and right next to the call site the correct rule is written
verbatim: "The absence of a computation is therefore NAMED
(`sources_absent`), not silent." The rule was carried out for the case
"the predicate was not called" and not carried out for the case "it was
called, and it refused" — the prose was broader than the behavior by
exactly one outcome out of three.

THE THREE OUTCOMES NOW DISTINGUISHABLE IN THE GRAPH ITSELF:

    the predicate was not called   -> census.adjacency is None
                                       (+ `room_adjacency` in sources_absent)
    called, the opening was scored -> census.adjacency.openings_evaluated
    called, the opening refused    -> census.adjacency.refusals[rule name]

WHAT IS NOT DONE HERE, AND WHY. The predicate's `room_geometry` is
folded into A COUNT BY KIND: a by-name list on a live building is tens
of thousands of rows, and the graph's census would become a copy of the
side index. By name it remains where it already was — with
`AdjacencyCensus`.
"""
from __future__ import annotations

import json
import unittest

from kir.decompile.building_graph import (
    GraphBuildError,
    GraphCensus,
    Relation,
    graph_from_dict,
    graph_from_l0,
)
from kir.decompile.graph_adjacency import opening_point_touches_room_edges


def _header() -> dict:
    return {"levels": [{"id": "L1", "name": "1", "elevation_mm": 0.0}],
            "rooms": [
                {"id": "R1", "level_id": "L1",
                 "boundary_mm": [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]},
                {"id": "R2", "level_id": "L1",
                 "boundary_mm": [[4000, 0], [8000, 0],
                                 [8000, 4000], [4000, 4000]]}]}


#: A door WITHOUT a point and without a frame: zero edges, a named refusal.
_DOOR_WITHOUT_POSITION = {"element_id": "D1", "category": "OST_Doors",
                          "level_id": "L1"}
#: A door WITHOUT a level: also zero edges, and a DIFFERENT refusal.
_DOOR_WITHOUT_LEVEL = {"element_id": "D0", "category": "OST_Doors",
                       "p0_mm": [4000.0, 2000.0]}
#: A door AT THE SEAM of two rooms: there is an edge, no refusal.
_DOOR_ON_THE_SEAM = {"element_id": "D2", "category": "OST_Doors",
                     "level_id": "L1", "p0_mm": [4000.0, 2000.0]}


def _graph(elements, **kwargs):
    return graph_from_l0(_header(), elements, joins={}, link_ids=(), **kwargs)


class ОтказПредикатаДоезжаетДоГрафа(unittest.TestCase):
    """The axis of CAPABILITY: what the graph can now say about its own zero."""

    def test_a_door_without_a_position_is_NAMED_in_the_graph_census(self):
        graph = _graph([_DOOR_WITHOUT_POSITION], room_adjacency=True)
        row = graph.census.adjacency
        self.assertIsNotNone(row, "перепись предиката снова выброшена")
        self.assertEqual(row["openings_seen"], 1)
        self.assertEqual(row["openings_evaluated"], 0)
        self.assertEqual(dict(row["refusals"]),
                         {"opening_without_position": 1})
        self.assertEqual(graph.relation_counts().get(
            "opening_point_touches_room", 0), 0,
            "рёбер по-прежнему ноль — меняется не он, а то, что о нём известно")

    def test_two_zeroes_with_DIFFERENT_causes_are_no_longer_one_zero(self):
        """A door with no point and a door with no level: both give ZERO edges.

        Measured for both (04.09.2026):

            no point    edges 0  evaluated 0  refusal opening_without_position
            no level    edges 0  evaluated 0  refusal opening_without_level

        Before the fix the graph said the SAME THING about both —
        nothing. Each is cured by something DIFFERENT (one needs a
        position capture, the other a level), and one zero for two cures
        sent the reader off to guess.
        """
        no_point = _graph([_DOOR_WITHOUT_POSITION],
                          room_adjacency=True).census.adjacency
        no_level = _graph([_DOOR_WITHOUT_LEVEL],
                          room_adjacency=True).census.adjacency
        self.assertEqual(dict(no_point["refusals"]),
                         {"opening_without_position": 1})
        self.assertEqual(dict(no_level["refusals"]),
                         {"opening_without_level": 1})
        self.assertNotEqual(dict(no_point), dict(no_level))

    def test_an_EVALUATED_opening_is_told_apart_from_a_refused_one(self):
        """A door standing far from every room is EVALUATED, not refused.

        It still emits a CAPTURED negative edge ("these rooms are not
        adjacent") — a positive assertion the predicate is entitled to
        make only because it looked. A refused door makes no such
        assertion at all, and the census must hold this distinction in
        numbers.
        """
        far = dict(_DOOR_ON_THE_SEAM, p0_mm=[500000.0, 500000.0])
        measured = _graph([far], room_adjacency=True).census.adjacency
        refused = _graph([_DOOR_WITHOUT_POSITION],
                         room_adjacency=True).census.adjacency
        self.assertEqual(measured["openings_evaluated"], 1)
        self.assertEqual(dict(measured["refusals"]), {})
        self.assertEqual(dict(measured["touch_degree"]), {"0": 1})
        self.assertEqual(refused["openings_evaluated"], 0)
        self.assertEqual(dict(refused["touch_degree"]), {})

    def test_the_census_matches_the_predicate_that_produced_it(self):
        """The graph's census is a PROJECTION of the predicate's census,
        not a recomputation of it."""
        elements = [_DOOR_WITHOUT_POSITION, _DOOR_ON_THE_SEAM]
        graph = _graph(elements, room_adjacency=True)
        raw = {row["element_id"]: row for row in elements}
        _edges, census = opening_point_touches_room_edges(
            _header(), raw, known_node_ids=raw.keys())
        self.assertEqual(dict(graph.census.adjacency),
                         {key: dict(value) if isinstance(value, dict) else value
                          for key, value in census.as_census_row().items()})

    def test_not_asking_the_predicate_stays_a_separate_answer(self):
        graph = _graph([_DOOR_WITHOUT_POSITION])
        self.assertIsNone(graph.census.adjacency,
                          "`None` значит «не звали», и другого носителя у "
                          "этого факта нет")
        self.assertIn("room_adjacency", graph.census.sources_absent)


class Перепись_ЕДЕТ_НА_ДИСК(unittest.TestCase):
    """The axis of the ARTIFACT: what is not in the file will tomorrow become silence again."""

    def test_the_row_survives_the_round_trip(self):
        graph = _graph([_DOOR_WITHOUT_POSITION, _DOOR_ON_THE_SEAM],
                       room_adjacency=True)
        payload = json.loads(json.dumps(graph.to_dict()))
        back = graph_from_dict(payload)
        self.assertEqual(dict(back.census.adjacency),
                         dict(graph.census.adjacency))
        self.assertEqual(back.to_dict()["census"], graph.to_dict()["census"])

    def test_an_artifact_written_before_this_field_still_loads(self):
        """The schema does NOT migrate: what was captured yesterday reads
        as "was not asked."

        The same move as `slopes` in `sketch_extract`: a field added
        after records have already landed on disk must be optional on
        read — otherwise the fix declares the whole previous corpus
        unreadable.
        """
        payload = _graph([_DOOR_WITHOUT_POSITION]).to_dict()
        payload["census"].pop("adjacency")
        self.assertIsNone(graph_from_dict(payload).census.adjacency)

    def test_a_census_that_does_not_add_up_is_REFUSED_when_read(self):
        """A corrupted file refuses, rather than handing back a lying census.

        The law is held by `AdjacencyCensus.assert_balanced` at
        construction, but there is no artifact reader there at all:
        `graph_from_dict` creates not a single `AdjacencyCensus`. So it
        is re-run here — for exactly the same reason `GraphCensus` is
        re-run.
        """
        payload = _graph([_DOOR_WITHOUT_POSITION],
                         room_adjacency=True).to_dict()
        payload["census"]["adjacency"]["refusals"] = {}
        with self.assertRaises(GraphBuildError) as caught:
            graph_from_dict(payload)
        self.assertIn("смежност", str(caught.exception))

    def test_measured_and_unmeasured_at_once_is_REFUSED(self):
        """The census exists, and the input is declared not submitted — a contradiction."""
        with self.assertRaises(GraphBuildError):
            GraphCensus(rows_seen=0, nodes=0, refusals={},
                        sources_absent=("room_adjacency",),
                        adjacency={"openings_seen": 0, "openings_evaluated": 0,
                                   "refusals": {}, "touch_degree": {},
                                   "rooms_seen": 0, "rooms_by_geometry": {}})

    def test_an_invented_field_in_the_row_is_REFUSED(self):
        with self.assertRaises(GraphBuildError):
            GraphCensus(rows_seen=0, nodes=0, refusals={},
                        adjacency={"openings_seen": 0, "openings_evaluated": 0,
                                   "refusals": {}, "touch_degree": {},
                                   "rooms_seen": 0, "rooms_by_geometry": {},
                                   "выдуманное": 1})


class КонтрольFail(unittest.TestCase):
    """FAIL CONTROL: throw the census back away — the property must disappear.

    What is checked is the BEHAVIOR of the old law, not the source text.
    """

    def test_dropping_the_census_makes_the_two_zeroes_identical(self):
        """The old law verbatim: the predicate's census is thrown away.

        Two doors refused by DIFFERENT rules then give, byte for byte,
        one artifact (down to the door's own address) — and this is
        exactly the loss the fix removes.
        """
        no_point = _graph([_DOOR_WITHOUT_POSITION], room_adjacency=True)
        no_level = _graph([dict(_DOOR_WITHOUT_LEVEL, element_id="D1")],
                          room_adjacency=True)

        def then(graph):
            """ALL that predicate B was leaving in the graph before the
            fix — edges alone.

            What is compared is them and the census WITHOUT its row: the
            other kinds of edges are beside the point, and dragging them
            into the comparison would mean measuring a level difference
            instead of a difference in causes.
            """
            edges = sorted(
                edge.key for edge in graph.edges
                if edge.relation is Relation.OPENING_POINT_TOUCHES_ROOM)
            row = dict(graph.to_dict()["census"])
            row.pop("adjacency")
            return json.dumps([edges, row], sort_keys=True, ensure_ascii=False)

        self.assertEqual(then(no_point), then(no_level),
                         "прежний закон давал ОДИН ответ на две разные "
                         "причины пустоты")
        self.assertNotEqual(dict(no_point.census.adjacency),
                            dict(no_level.census.adjacency),
                            "нынешний закон обязан их различать")


if __name__ == "__main__":
    unittest.main()
