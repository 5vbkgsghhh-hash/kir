"""REFUTING TESTS for the typed building graph v1.

Discipline §18.7: first a test that reproduces the failure VERBATIM, then
the fix. Every class below reproduces a MEASURED case, not an imagined
one.

Measurements the fixtures rest on (10.08.2026, instrument — a raw parse of
`L0.jsonl` from the `backend/backend/data/decompile` corpus,
machine-local):

* the `source_element_id` ↔ `element_id` bijection — 52 of 52 trees,
  540,461 sheets, 1,139,477 elements, 0 address repeats;
* dangling `host_id` — 1,263 of 213,811 (0.59%), CONCENTRATED:
  `snowdon_elec_v1` 959/1,001 (95.8%), Snowdon Plumbing 54/54 and 50/50
  (100%);
* `host_source` — 0 rows out of 1,139,477;
* a LEVEL-as-host mark: `snowdon_plumb_v5` — 21 `OST_GenericModel` and
  4 `OST_PlumbingFixtures` have `OST_Levels` as their host.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    Authority,
    AuthoritySource,
    Existence,
    GraphBuildError,
    GraphEdge,
    GraphNode,
    Modality,
    NodeRefusal,
    Relation,
    building_graph_enabled,
    graph_from_l0,
)


def _element(element_id, category, **kw):
    row = {"element_id": element_id, "category": category,
           "category_ru": "", "type_id": "t", "type_name": "T",
           "level_id": None, "geom_kind": "point", "p0_mm": None,
           "p1_mm": None, "rotation_deg": None, "bbox_min_mm": None,
           "bbox_max_mm": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


def _header(**kw):
    base = {"doc_name": "тест", "levels": [], "rooms": [], "grids": []}
    base.update(kw)
    return base


class NodeAddressIsTheL0Element(unittest.TestCase):
    """The backbone is the L0 ELEMENT SET ITSELF, not a new
    identifier."""

    def test_node_id_is_the_l0_element_id(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("102", "OST_Doors")])
        self.assertEqual(sorted(graph.nodes), ["101", "102"])
        self.assertEqual(graph.node("101").category, "OST_Walls")

    def test_rooms_and_levels_share_the_address_space(self) -> None:
        """Measured: rooms 7,841/7,841, levels 170/170 — ELEMENTS of the
        same space. A "room" node does not set up its own numbering."""
        graph = graph_from_l0(
            _header(rooms=[{"id": "R1", "bounding_element_ids": ["W1"]}],
                    levels=[{"id": "L1", "elevation_mm": 0.0}]),
            [_element("R1", "OST_Rooms"), _element("L1", "OST_Levels"),
             _element("W1", "OST_Walls", level_id="L1")])
        self.assertIn("R1", graph)
        self.assertIn("L1", graph)
        self.assertEqual(graph.node("R1").category, "OST_Rooms")


class CensusLawHolds(unittest.TestCase):
    """`nodes = evaluated + named refusals`. There are no silent
    dropouts."""

    def test_row_without_address_is_a_NAMED_refusal(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("", "OST_Walls")])
        self.assertEqual(graph.census.rows_seen, 2)
        self.assertEqual(graph.census.nodes, 1)
        self.assertEqual(graph.census.refusals,
                         {NodeRefusal.NO_ADDRESS.value: 1})
        graph.census.assert_balanced()

    def test_duplicate_address_is_named_not_swallowed(self) -> None:
        """Across the corpus, no repeats were OBSERVED (0 out of
        1,139,477), but the law holds by verification, not by the
        corpus's luck."""
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("101", "OST_Doors")])
        self.assertEqual(graph.census.nodes, 1)
        self.assertEqual(graph.census.refusals,
                         {NodeRefusal.DUPLICATE_ADDRESS.value: 1})

    def test_unbalanced_census_is_unconstructible(self) -> None:
        from kir.decompile.building_graph import BuildingGraph, GraphCensus
        with self.assertRaises(GraphBuildError):
            BuildingGraph(
                doc_name="x",
                nodes=[GraphNode("1", "OST_Walls", Authority.DECLARED,
                                 AuthoritySource.L0_ELEMENT,
                                 Existence.MATERIALIZED)],
                edges=[],
                census=GraphCensus(rows_seen=5, nodes=1, refusals={}))


class AuthorityLine(unittest.TestCase):
    """THE LINE OF AUTHORITY is a property of the node, not the author's
    memory."""

    def test_default_is_declared_and_names_its_witness(self) -> None:
        graph = graph_from_l0(_header(), [_element("1", "OST_PipeFitting")])
        node = graph.node("1")
        self.assertIs(node.authority, Authority.DECLARED)
        self.assertIs(node.authority_source, AuthoritySource.L0_ELEMENT)

    def test_category_alone_NEVER_makes_a_node_derived(self) -> None:
        """THE COST OF THE MISTAKE IS MEASURED: turning MEP fittings into
        derived elements would remove 14,713 of 31,998 ops (46.0%) on
        `snowdon_plumb_v4`, and `honest_pct` would shift 99.42% → 98.93%
        — 0.49 percentage points for half a building. A categorical prior
        does not know who creates the element."""
        graph = graph_from_l0(_header(), [
            _element("1", "OST_PipeFitting"), _element("2", "OST_DuctFitting"),
            _element("3", "OST_PipeAccessory")])
        for node_id in ("1", "2", "3"):
            self.assertIs(graph.node(node_id).authority, Authority.DECLARED,
                          "категория объявила элемент выведенным — это ровно "
                          "отозванная 10.08 заявка про фитинги")

    def test_derived_requires_an_EXPLICIT_named_witness(self) -> None:
        graph = graph_from_l0(
            _header(), [_element("1", "OST_GenericModel")],
            generator_child_ids=["1"])
        node = graph.node("1")
        self.assertIs(node.authority, Authority.DERIVED_BY_REVIT)
        self.assertIs(node.authority_source,
                      AuthoritySource.LIFTER_GENERATOR_CHILD)

    def test_authority_without_a_source_is_unconstructible(self) -> None:
        with self.assertRaises(GraphBuildError):
            GraphNode("1", "OST_Walls", Authority.DERIVED_BY_REVIT,
                      None, Existence.MATERIALIZED)  # type: ignore[arg-type]


class ExistenceAxis(unittest.TestCase):
    """An unbuilt building is expressible from day one — the viewer
    requires it."""

    def test_l0_row_is_materialized(self) -> None:
        graph = graph_from_l0(_header(), [_element("1", "OST_Walls")])
        self.assertIs(graph.node("1").existence, Existence.MATERIALIZED)

    def test_both_axes_are_orthogonal(self) -> None:
        """All four combinations make sense; the most interesting is
        planned+derived_by_revit: the program said "connect the pipes,"
        fittings WILL APPEAR, but they do not exist yet and their
        geometry must not be declared."""
        node = GraphNode("1", "OST_PipeFitting", Authority.DERIVED_BY_REVIT,
                         AuthoritySource.OP_DERIVED_CONTRACT, Existence.PLANNED)
        self.assertIs(node.existence, Existence.PLANNED)
        self.assertIs(node.authority, Authority.DERIVED_BY_REVIT)


class RefutationIsAnEdge(unittest.TestCase):
    """A refuted edge STAYS in the graph, carrying the rule's name."""

    def test_refuted_without_a_rule_name_is_unconstructible(self) -> None:
        with self.assertRaises(GraphBuildError):
            GraphEdge(Relation.HOSTED_IN, "1", "2", Modality.REFUTED)

    def test_rule_name_without_refutation_is_unconstructible(self) -> None:
        with self.assertRaises(GraphBuildError):
            GraphEdge(Relation.HOSTED_IN, "1", "2", Modality.PROVEN,
                      refuted_by="некое_правило")

    def test_refuted_edge_survives_and_is_countable(self) -> None:
        edge = GraphEdge(Relation.HOSTED_IN, "1", "2", Modality.REFUTED,
                         refuted_by="правило_X")
        self.assertEqual(edge.refuted_by, "правило_X")


class HostedInHasThreeOutcomes(unittest.TestCase):
    """A MISSING HOST AND A HOST OUTSIDE THE EXTRACTION ARE DIFFERENT
    FACTS.

    A REFUTING CASE, measured verbatim: `snowdon_elec_v1` — 959 of 1,001
    declared hosts (95.8%) are not elements of this snapshot, because they
    live in a LINKED file. Four Snowdon Plumbing snapshots — 100%. A graph
    that erases such an edge makes "we didn't read the relationship"
    indistinguishable from "there is no relationship" — and that is
    exactly why the cross-discipline zone is empty for the pincers.
    """

    def test_host_inside_extraction_is_proven(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        edges = graph.out_edges("D1", Relation.HOSTED_IN)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual(edges[0].dst, "W1")

    def test_host_OUTSIDE_extraction_keeps_the_edge_and_names_why(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("F1", "OST_ElectricalFixtures", host_id="СВЯЗЬ-42")])
        edges = graph.out_edges("F1", Relation.HOSTED_IN)
        self.assertEqual(len(edges), 1, "ребро стёрто — слепота выдана за факт")
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(
            edges[0].evidence["why"], "target_not_in_snapshot")
        self.assertEqual(len(graph.unresolved_targets()), 1)

    def test_no_host_declared_yields_no_edge_at_all(self) -> None:
        graph = graph_from_l0(_header(), [_element("W1", "OST_Walls")])
        self.assertEqual(graph.out_edges("W1", Relation.HOSTED_IN), ())

    def test_unresolved_is_NOT_the_same_bucket_as_possible(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("F1", "OST_ElectricalFixtures", host_id="СВЯЗЬ-42")])
        counts = graph.modality_counts(Relation.HOSTED_IN)
        self.assertEqual(counts, {Modality.UNRESOLVED_TARGET.value: 1})
        self.assertNotIn(Modality.POSSIBLE.value, counts)


class DatumHostIsNotABody(unittest.TestCase):
    """A LEVEL-as-host rides as a separate relationship.

    Measured: `snowdon_plumb_v5` — 21 `OST_GenericModel` and
    4 `OST_PlumbingFixtures` have `OST_Levels` as their host. Lumping
    "sits IN the wall" and "placed ON the level" into one word is the very
    same conflation this module was written to take apart.
    """

    def test_level_host_is_placed_on_datum_not_hosted_in(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("L1", "OST_Levels"),
            _element("G1", "OST_GenericModel", host_id="L1")])
        self.assertEqual(graph.out_edges("G1", Relation.HOSTED_IN), ())
        datum = graph.out_edges("G1", Relation.PLACED_ON_DATUM)
        self.assertEqual(len(datum), 1)
        self.assertIs(datum[0].modality, Modality.PROVEN)


class HostSourceIsUnmeasuredEverywhere(unittest.TestCase):
    """`host_source` — 0 rows out of 1,139,477 in the whole corpus.

    A field from the 09.08 capture wave is written by the emitter and does
    not occur in ANY stored snapshot. Treating `None` as `family_instance`
    is forbidden: an empty field and an unmeasured field are different
    facts.
    """

    def test_absent_host_source_is_carried_as_None_not_defaulted(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        self.assertIsNone(graph.node("D1").host_source)
        edge = graph.out_edges("D1", Relation.HOSTED_IN)[0]
        self.assertIsNone(edge.evidence["host_source"])

    def test_present_host_source_rides_in_the_evidence(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1",
                     host_source="family_instance")])
        self.assertEqual(graph.node("D1").host_source, "family_instance")


class Inertness(unittest.TestCase):
    """🔴 THE DEFAULT WAS FLIPPED ON 22.08.2026 — THIS CLASS WAS REWRITTEN,
    NOT DELETED.

    It held "the flag is off by default," and held it correctly, as long
    as the owner's condition stood: the graph had never once been checked
    against either live Revit or the corpus. That condition was met — the
    22.08 run over `backend/data/decompile` gave **76 of 76 decompiles**,
    **0** refusals, `assert_balanced()` holds everywhere (1,576,343 nodes,
    1,843,930 edges).

    So what must be checked is not the old VALUE, but the reason the flag
    exists in the first place: the decision still rests on a single
    `os.getenv`, and turning it off is possible by an EXPLICIT WORD. A
    test that stayed pinned to the old value would turn red instead of
    guarding anything.
    """

    def test_the_default_is_ON_since_the_corpus_census_balanced(self) -> None:
        import os
        old = os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
        try:
            self.assertTrue(building_graph_enabled())
        finally:
            if old is not None:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = old

    def test_an_explicit_word_still_turns_it_off(self) -> None:
        import os
        old = os.environ.get("KUKAI_IR_BUILDING_GRAPH")
        try:
            for word in ("0", "false", "no", "off", "  Off  "):
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = word
                self.assertFalse(building_graph_enabled(), msg=word)
        finally:
            if old is None:
                os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            else:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = old


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
