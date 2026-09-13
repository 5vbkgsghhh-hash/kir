"""The graph layer in the viewer: the authority line and "not in Revit yet".

The main thing these tests hold is the SEPARATENESS OF THE AXES. Shape
accuracy, node existence, and relation refutation are three distinct facts,
and every time they were merged, the result was a green screen about
something unread.
"""

import os
import unittest

from kir.viewer import graph as G
from kir.viewer import honesty as H


class VocabularyIsBorrowedNotCopied(unittest.TestCase):

    def test_codes_cover_the_owner_enums_exactly(self):
        """The building has one dictionary. A local copy of
        `Authority`/`Existence` values would drift from the graph, and a
        month from now `planned` in the viewer would turn out to be a
        different `planned`."""
        from kir.decompile.building_graph import Authority, Existence
        self.assertEqual(set(G.AUTHORITY_CODE) - {"unknown"},
                         {a.value for a in Authority})
        self.assertEqual(set(G.EXISTENCE_CODE) - {"unknown"},
                         {e.value for e in Existence})

    def test_unknown_exists_on_both_axes(self):
        """A scene without a graph layer must say "not asked", not pass
        everything off as built."""
        self.assertIn("unknown", G.AUTHORITY_CODE)
        self.assertIn("unknown", G.EXISTENCE_CODE)

    def test_codes_fit_a_single_byte(self):
        for table in (G.AUTHORITY_CODE, G.EXISTENCE_CODE):
            self.assertTrue(all(0 <= v <= 255 for v in table.values()))

    def test_flags_are_distinct_bits(self):
        self.assertEqual(G.FLAG_REFUTED & G.FLAG_UNRESOLVED, 0)


class RefutationBelongsToTheRelation(unittest.TestCase):
    """REVERSAL OF MY OWN STATE, recorded by a test.

    The viewer had `Trust.CLASH_REFUTED`. It was removed not because the
    source failed to appear — it did appear (`Modality.REFUTED` +
    `GraphEdge.refuted_by`, live measurement `демо-v3`: 5 941 edges removed
    by the rule `host_does_not_separate_exactly_two_rooms`) — but because it
    was an axis substitution: `Trust` judges the ELEMENT, refutation
    belongs to the RELATION. A door whose edge to a room was removed by the
    rule is read perfectly fine.
    """

    def test_trust_no_longer_carries_it(self):
        self.assertNotIn("clash_refuted", {t.value for t in H.Trust})

    def test_the_signal_lives_on_its_own_axis(self):
        self.assertTrue(G.FLAG_REFUTED)

    def test_the_edge_type_requires_a_rule_name(self):
        """Refutation without the rule's name is that very silence: "not
        found" becomes indistinguishable from "did not look". The graph's
        owner holds this as a type, and the viewer relies on exactly that."""
        from kir.decompile.building_graph import (GraphBuildError,
                                                       GraphEdge, Modality,
                                                       Relation)
        with self.assertRaises(GraphBuildError):
            GraphEdge(relation=Relation.HOSTED_IN, src="a", dst="b",
                      modality=Modality.REFUTED)


class TheForeignFlagIsRespected(unittest.TestCase):
    """The `KUKAI_IR_BUILDING_GRAPH` flag does NOT belong to the viewer, and
    the viewer asks it rather than deciding on its own.

    🔴 THE FLAG'S DEFAULT WAS FLIPPED BY ITS OWNER ON 22.08.2026 (the census
    converged at 76 out of 76 corpus decompiles, 0 refusals). This class
    therefore checks NOT the default value — that belongs to someone else
    — but that the viewer ASKS: a flag explicitly turned off yields a named
    absence, not silence.
    """

    def test_a_disabled_flag_gives_a_named_absence_not_silence(self):
        previous = os.environ.get("KUKAI_IR_BUILDING_GRAPH")
        os.environ["KUKAI_IR_BUILDING_GRAPH"] = "0"
        try:
            facts, note = G.facts_for_decompile(
                {"doc_name": "проба"}, [], generator_child_ids=(),
                l1_source_ids=())
            self.assertEqual(facts, {})
            self.assertFalse(note["available"])
            self.assertIn("KUKAI_IR_BUILDING_GRAPH", note["reason"])
        finally:
            if previous is None:
                os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            else:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = previous

    def test_the_default_now_BUILDS_the_layer(self):
        """CONTROL IN THE REVERSE DIRECTION: without it the test cannot
        tell "respects the flag" from "the layer is never built"."""
        previous = os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
        try:
            _facts, note = G.facts_for_decompile(
                {"doc_name": "проба"}, [], generator_child_ids=(),
                l1_source_ids=())
            self.assertTrue(note["available"])
            self.assertEqual(note["source"], "graph_from_l0")
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = previous

    def test_unavailable_still_publishes_every_key(self):
        """The consumer is not obligated to know whether there was a
        reason. A missing key would read as zero, and zero as "asked,
        found nothing"."""
        note = G.unavailable("нипочему")
        for key in ("authority", "existence", "relations", "refuted_by_rule",
                    "unresolved_by_reason", "without_l1", "nodes"):
            self.assertIn(key, note)
        self.assertIsNone(note["without_l1"])


class PlannedIsAssertedByTheViewerAndSaysSo(unittest.TestCase):
    """A builder of the graph FROM PROGRAMS does not exist: `graph_from_l0`
    is the only one, and it assigns `MATERIALIZED` to everything. So
    `planned` is assigned by the viewer, and this must be written in the
    summary, not merely implied."""

    def test_every_program_element_is_planned(self):
        facts, note = G.facts_for_programs(
            {"p1/w0": {"op": "create_wall"}, "p1/d0": {"op": "create_door"}})
        self.assertEqual({f.existence for f in facts.values()}, {"planned"})
        self.assertEqual(note["existence"], {"planned": 2})

    def test_the_authority_source_is_the_program_op(self):
        facts, _ = G.facts_for_programs({"p1/w0": {"op": "create_wall"}})
        self.assertEqual(facts["p1/w0"].authority_source, "program_op")
        self.assertEqual(facts["p1/w0"].authority, "declared")

    def test_the_viewer_admits_that_it_is_the_one_asserting(self):
        _, note = G.facts_for_programs({"p1/w0": {"op": "create_wall"}})
        self.assertEqual(note["source"], "viewer_asserts_planned")
        self.assertIn("ВЬЮЕР", note["source_ru"])

    def test_what_revit_will_add_beyond_the_declaration_is_named(self):
        """A curtain wall spawns cells, panels and mullions; a stair spawns
        flights, landings and railings. The viewer cannot show them (only
        Revit knows the count), but staying silent about it would mean
        promising that the whole building is on screen."""
        _, note = G.facts_for_programs({"p1/st": {"op": "create_stairs"}})
        self.assertIn("OST_StairsRuns", note["will_derive"])
        self.assertTrue(note["will_derive_ru"])

    def test_an_op_without_derived_children_adds_nothing(self):
        _, note = G.facts_for_programs({"p1/p0": {"op": "create_pipe"}})
        self.assertEqual(note["will_derive"], {})


class LiveEdgesAreACCEPTEDNotResolvedTwice(unittest.TestCase):
    """🔴 THE LIVE SESSION HAD NO EDGES AT ALL, AND THIS WAS SILENT.

    The summary returned `relations: {}` and `unresolved_by_reason: {}`
    UNCONDITIONALLY — meaning "asked, there are no edges" and "did not ask"
    were printed identically, even though the client ALREADY knows how to
    show edges (`FLAG_REFUTED`, `FLAG_UNRESOLVED` arrive from the
    decompile).

    References here are NOT re-resolved: the `BundleGeometry.hosted` index
    is built by `clash_judgement.hosted_from_ops`, and it is computed by
    the same frame BEFORE this call. A second instance of resolution would
    silently drift from the first — and accepting the ready-made one costs
    nothing.
    """

    def test_without_the_index_the_zero_is_a_fact_about_the_CALL(self):
        _, note = G.facts_for_programs({"p1/w0": {"op": "create_wall"}})
        self.assertTrue(note["edges_unmeasured"])
        self.assertEqual(note["relations"], {})

    def test_with_the_index_a_resolved_host_becomes_a_counted_edge(self):
        facts, note = G.facts_for_programs(
            {"p1/w0": {"op": "create_wall"}, "p1/d0": {"op": "create_door"}},
            {"p1/d0": {"host_element_id": "p1/w0", "host_ref": "w0",
                       "host_class": "create_wall",
                       "source": "program_host_ref"}})
        self.assertFalse(note["edges_unmeasured"])
        self.assertEqual(note["relations"], {"hosted_in": 1})
        self.assertEqual(facts["p1/d0"].flags, 0)

    def test_a_host_NAMED_but_not_found_flags_its_element(self):
        """`hosted_from_ops` writes `host_element_id = None` there and
        says, verbatim: "a host was named but not found" is closer to a
        contradiction than to an absence. This is exactly
        `Modality.UNRESOLVED_TARGET`."""
        facts, note = G.facts_for_programs(
            {"p1/d0": {"op": "create_door"}},
            {"p1/d0": {"host_element_id": None, "host_ref": "w404",
                       "host_class": None, "source": "program_host_ref"}})
        self.assertEqual(facts["p1/d0"].flags & G.FLAG_UNRESOLVED,
                         G.FLAG_UNRESOLVED)
        self.assertEqual(note["unresolved_by_reason"],
                         {"host_named_but_not_found": 1})
        self.assertEqual(note["relations"], {"hosted_in": 0})

    def test_an_empty_index_means_asked_and_none_declared(self):
        """CONTROL IN THE REVERSE DIRECTION: an empty index ≠ a missing one."""
        _, note = G.facts_for_programs({"p1/w0": {"op": "create_wall"}}, {})
        self.assertFalse(note["edges_unmeasured"])
        self.assertEqual(note["relations"], {"hosted_in": 0})

    def test_the_price_of_datum_edges_is_NAMED_not_silently_skipped(self):
        """There are no edges to the level/room, and the summary must say why."""
        _, note = G.facts_for_programs({"p1/w0": {"op": "create_wall"}}, {})
        self.assertIn("СЕЛЕКТОР", note["datum_edges_ru"])


class ExistenceIsNotFidelity(unittest.TestCase):
    """All four combinations are meaningful, and that is the whole point of
    the two axes.

    `NO_BODY` — "the element is declared, we don't know the body".
    `PLANNED` — "the element does not yet exist in the model".
    A body can be known exactly while the element does not exist in Revit:
    the engineer wrote the program and did not press the button. Merging
    the two would turn the "send to Revit" button into a lottery.
    """

    def test_they_are_carried_by_different_tables(self):
        from kir.viewer.scene import FIDELITY_CODE
        self.assertIn("no_body", FIDELITY_CODE)
        self.assertNotIn("no_body", G.EXISTENCE_CODE)
        self.assertNotIn("planned", FIDELITY_CODE)

    def test_a_planned_element_can_still_have_a_known_body(self):
        """A live scene with a type snapshot gives real bodies to planned
        elements — measured: a body exists when `existence=planned`."""
        from kir.viewer import live_scene as L
        snapshot = {
            "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
            "pipe_types": [{"id": 30, "name": "Сталь",
                            "section": {"kind": "nominal_table",
                                        "source": "PipeSegment.GetSizes",
                                        "sizes": [[100.0, 114.3]]}}]}
        ops = [{"op": "create_pipe", "id": "p0",
                "p0_mm": [0.0, 0.0, 2800.0], "p1_mm": [12000.0, 0.0, 2800.0],
                "diameter_mm": 100.0,
                "pipe_type": {"by": "name", "value": "Сталь"},
                "level": {"by": "name", "value": "L1"}}]
        _, meta = L.scene_from_programs([{"ops": ops}], snapshot=snapshot)
        self.assertEqual(meta["bodies"], 1)
        self.assertEqual(meta["graph"]["existence"], {"planned": 1})
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body", 0), 0)


class BothEndsOfARefutedEdgeAreMarked(unittest.TestCase):
    """A refuted relation touches BOTH ends, and staying silent about the
    second one is not allowed. Measured on `sob62_fas_r23_v19` with the
    flag on: 14 removed edges give 28 flagged elements."""

    def test_the_marking_is_derived_from_edges_not_nodes(self):
        import inspect
        source = inspect.getsource(G.facts_for_decompile)
        self.assertIn("graph.edges", source)
        self.assertIn("edge.src", source)
        self.assertIn("edge.dst", source)
