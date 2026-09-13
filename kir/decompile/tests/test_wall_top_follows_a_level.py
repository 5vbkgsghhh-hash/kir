"""THE WALL TOP FOLLOWS THE LEVEL — the building's most numerous relation,
which was absent from the graph. Refuting tests.

🔴 WHAT WAS MEASURED (22.08.2026, production model MNVNK, 33 944
elements,
`backend/data/decompile/mnvnk_atr_pd_b14_k6_ar_r2022_отсоединено_отсоединено`):

    walls total                                     10 646
    `WALL_HEIGHT_TYPE` present                       7 007   (65.8 %)
      of those the target resolved to an `OST_Levels` node   7 007   (7 007 of 7 007)
      of those the top coincided with the BASE (`level_id`)    292   (4.2 %)
    no parameter, the wall block was READ                838  -> top is a NUMBER
    no parameter, not a single `WALL_*` key            2 801  -> NOT ASKED
    `WALL_BASE_CONSTRAINT`                            None on 10 646 of 10 646

Before this wave, the number traveled in the `params` string, and the
graph could not be asked "what would move if this level were raised" —
even though the BASE (`ON_LEVEL`) already was a relation. The top and the
base coincide for 4.2 % of walls: merging them would repeat exactly the
conflation this module was written to take apart.

🔴 THE THIRD LINE OF THE REMAINDER IS NOT A FACT ABOUT THE BUILDING. For
2 801 walls the string parameters are something else entirely
(`FLOOR_HEIGHTABOVELEVEL_PARAM`, `INSTANCE_SILL_HEIGHT_PARAM`,
`SLANTED_COLUMN_TYPE_PARAM`): the reading mask never reached the wall
block. A reader subtracting 7 007 from 10 646 would get "3 639 walls have
a top not bound to a level" — a claim FALSE for 2 801 of them.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    REFUTED_TOP_CONSTRAINT_IS_NOT_A_LEVEL,
    REFUTED_TOP_IS_UNCONNECTED_HEIGHT,
    Modality,
    OutsideExtraction,
    Relation,
    graph_from_l0,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}

#: The wall's row whose parameter block is READ: without this witness
#: "did not ask" and "top given as a number" would have collapsed into
#: one value.
_READ_BLOCK = {"WALL_USER_HEIGHT_PARAM": 3000.0, "WALL_TOP_OFFSET": -300.0,
               "WALL_TOP_IS_ATTACHED": 0}


def _element(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


def _graph(rows):
    return graph_from_l0(_HEADER, rows)


def _edges(graph):
    return graph.relation_edges(Relation.TOP_CONSTRAINED_TO_LEVEL)


class TheTopConstraintIsARelationNotAParameter(unittest.TestCase):

    def test_a_level_target_is_proven(self) -> None:
        graph = _graph([
            _element("L1", "OST_Levels"), _element("L9", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1",
                     params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "L9"})])
        edges = _edges(graph)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual((edges[0].src, edges[0].dst), ("W1", "L9"))
        self.assertEqual(edges[0].evidence["source"], "params.WALL_HEIGHT_TYPE")
        self.assertFalse(edges[0].evidence["same_as_base_level"])
        self.assertEqual(edges[0].evidence["top_offset_mm"], -300.0)

    def test_the_top_is_NOT_the_base_and_the_edge_says_so(self) -> None:
        """292 MNVNK walls out of 7 007 (4.2 %) — top and base coincide.

        The evidence row exists precisely so that `ON_LEVEL` and this
        kind cannot be taken for one fact.
        """
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1",
                     params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "L1"})])
        edge = _edges(graph)[0]
        self.assertTrue(edge.evidence["same_as_base_level"])
        on_level = graph.relation_edges(Relation.ON_LEVEL)
        self.assertEqual(len(on_level), 1)
        self.assertIsNot(on_level[0].relation, edge.relation)

    def test_a_target_outside_the_snapshot_is_unresolved_not_silent(self) -> None:
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1",
                     params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "L404"})])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value)

    def test_a_target_that_is_not_a_level_is_a_NAMED_refutation(self) -> None:
        """Not observed across the corpus; the law holds by verification, not luck."""
        graph = _graph([
            _element("G1", "OST_Grids"),
            _element("W1", "OST_Walls", level_id=None,
                     params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "G1"})])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.REFUTED)
        self.assertEqual(edge.refuted_by, REFUTED_TOP_CONSTRAINT_IS_NOT_A_LEVEL)
        self.assertEqual(edge.evidence["target_category"], "OST_Grids")


class UnconnectedHeightIsRefutedNotAbsent(unittest.TestCase):
    """838 MNVNK walls: the block is read, there is no binding — the top is given as a NUMBER."""

    def test_a_read_block_without_the_param_refutes_against_the_base(self) -> None:
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1", params=dict(_READ_BLOCK))])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.REFUTED)
        self.assertEqual(edge.refuted_by, REFUTED_TOP_IS_UNCONNECTED_HEIGHT)
        self.assertEqual((edge.src, edge.dst), ("W1", "L1"))
        self.assertEqual(edge.evidence["unconnected_height_mm"], 3000.0)

    def test_without_a_base_node_the_refutation_becomes_a_self_edge(self) -> None:
        """The second end is not invented: there is no base in the snapshot."""
        graph = _graph([
            _element("W1", "OST_Walls", level_id="L404",
                     params=dict(_READ_BLOCK))])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.REFUTED)
        self.assertEqual((edge.src, edge.dst), ("W1", "W1"))
        self.assertIsNone(edge.evidence["base_level"])

    def test_the_refutation_is_countable(self) -> None:
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1", params=dict(_READ_BLOCK)),
            _element("W2", "OST_Walls", level_id="L1", params=dict(_READ_BLOCK))])
        self.assertEqual(graph.refuted_by_counts()[
            REFUTED_TOP_IS_UNCONNECTED_HEIGHT], 2)


class AnUnreadParameterBlockIsNotANegativeFact(unittest.TestCase):
    """🔴 THE REFUTING CASE: 2 801 MNVNK walls. Silence here would have lied."""

    def test_a_wall_without_the_wall_block_is_POSSIBLE_not_refuted(self) -> None:
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1",
                     params={"FLOOR_HEIGHTABOVELEVEL_PARAM": 0.0,
                             "INSTANCE_SILL_HEIGHT_PARAM": 0.0,
                             "SLANTED_COLUMN_TYPE_PARAM": 0})])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.POSSIBLE)
        self.assertEqual((edge.src, edge.dst), ("W1", "W1"))
        self.assertEqual(edge.evidence["why"], "wall_parameter_block_not_read")
        self.assertIsNone(edge.refuted_by, "не опровергнуто — не спрашивали")

    def test_the_two_absences_are_DIFFERENT_edges(self) -> None:
        """Exactly what the witness of the read block was set up for."""
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1", params=dict(_READ_BLOCK)),
            _element("W2", "OST_Walls", level_id="L1",
                     params={"INSTANCE_SILL_HEIGHT_PARAM": 0.0})])
        by_src = {e.src: e for e in _edges(graph)}
        self.assertIs(by_src["W1"].modality, Modality.REFUTED)
        self.assertIs(by_src["W2"].modality, Modality.POSSIBLE)

    def test_a_row_WITHOUT_ANY_param_gets_no_edge_at_all(self) -> None:
        """🔴 THE BOUNDARY OF THE CLAIM ITSELF, AND IT IS MEASURED.

        `POSSIBLE` says something narrow: the string's parameters are
        READ, and the wall block is not among them — the mask never
        reached it. A string with not a single parameter has no such
        witness, and "possible" about it is a claim about nothing.

        Measured across the whole corpus (297 076 walls in 76
        decompiles): rows with a WALL and a completely empty `params` —
        **0**. The distinction subtracts nothing from what was measured
        and guards against a degenerate input.
        """
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("W1", "OST_Walls", level_id="L1", params={})])
        self.assertEqual(_edges(graph), ())

    def test_a_non_address_value_is_also_named(self) -> None:
        graph = _graph([
            _element("W1", "OST_Walls",
                     params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": -1})])
        edge = _edges(graph)[0]
        self.assertIs(edge.modality, Modality.POSSIBLE)
        self.assertEqual(edge.evidence["why"], "top_constraint_is_not_an_address")


class EveryWallIsAccountedFor(unittest.TestCase):
    """The census law applied to a kind: EVERY wall has its own edge."""

    def test_no_wall_leaves_the_relation_without_an_edge(self) -> None:
        rows = [_element("L1", "OST_Levels"), _element("L2", "OST_Levels")]
        rows += [_element("A", "OST_Walls", level_id="L1",
                          params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "L2"}),
                 _element("B", "OST_Walls", level_id="L1",
                          params=dict(_READ_BLOCK)),
                 _element("C", "OST_Walls", level_id="L1",
                          params={"INSTANCE_SILL_HEIGHT_PARAM": 0.0}),
                 _element("D", "OST_Walls", level_id="L1",
                          params={**_READ_BLOCK, "WALL_HEIGHT_TYPE": "L404"})]
        graph = _graph(rows)
        walls = {row["element_id"] for row in rows
                 if row["category"] == "OST_Walls"}
        self.assertEqual({e.src for e in _edges(graph)}, walls)
        self.assertEqual(len(_edges(graph)), len(walls))

    def test_non_walls_do_not_produce_the_relation(self) -> None:
        """CONTROL IN THE REVERSE DIRECTION: the instrument does not cry wolf at everything."""
        graph = _graph([
            _element("L1", "OST_Levels"),
            _element("F1", "OST_Floors", level_id="L1",
                     params={"WALL_HEIGHT_TYPE": "L1"})])
        self.assertEqual(_edges(graph), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
