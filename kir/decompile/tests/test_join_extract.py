"""JOINING IS READ, AND TWO RELATIONS DO NOT FUSE INTO ONE.

THE MEASUREMENT THAT PAID FOR THIS FILE. The owner decompiled a building and
recompiled it back: "walls overlap each other everywhere and nothing is
joined to anything." The cause was not in the forward path — joins were
NEVER being read: ``GetJoinedElements`` occurred in ``kir/decompile/``
**0 times**, join operations in the registry **0**.

🔴 AND A SECOND MEASUREMENT, WITHOUT WHICH THE RESULT WOULD HAVE BEEN ONE
CONFUSED FLAG INSTEAD OF TWO HONEST FIELDS. 800 walls of the owner's live
document:

    both ends ALLOWED and joined            143 of 288
    both ends FORBIDDEN and not joined        27 of 223
    MIXED outcome                             38 of 81

The relations diverge, and so ``joined_to`` (a pair of elements) and
``join_allowed_at_end`` (one wall, one end) are stored separately and are not
derived from one another. The tests below pin down exactly this: half of
them will go red if someone decides to "simplify" the two fields into one.

Run:
    venv/bin/python -m pytest kir/decompile/tests/test_join_extract.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile import join_extract as J
from kir.decompile.building_graph import (
    GraphEdge,
    Modality,
    Relation,
    graph_from_l0,
)

_HEADER = {"doc_name": "join-test", "rooms": []}


def _wall(element_id: str) -> dict:
    return {"element_id": element_id, "category": "OST_Walls",
            "unique_id": f"uid-{element_id}"}


def _payload(*rows: dict, failures: list | None = None) -> dict:
    return {"schema_version": J.JOIN_EXTRACT_SCHEMA_VERSION,
            "elements": list(rows), "failures": failures or []}


class TwoRelationsStayTwo(unittest.TestCase):
    """The stage's main contract: permission and joining are DIFFERENT
    facts."""

    def test_the_measured_mixed_case_is_representable(self):
        """38 of 81 walls in the live measurement — exactly this case.

        Joined, but joining at the ends is FORBIDDEN. A single flag cannot
        say this: it would have to choose one of the two truths and lie
        about the other.
        """
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": ["2"],
             "join_allowed_at_end": [False, False]}))
        record = got.joins[0]
        self.assertEqual(record.joined_to, ("2",))
        self.assertEqual(record.join_allowed_at_end, (False, False))

    def test_no_ends_and_both_ends_forbidden_are_different_answers(self):
        """`None` means "there are no ends at all", `(False, False)` means
        "both are forbidden".

        The measurement gives 27 of the second kind out of 223: a numerous
        case, and fusing it with "the question does not apply" would erase a
        fact about the building.
        """
        floor = J.extract_joins(_payload(
            {"element_id": "9", "joined_to": []})).joins[0]
        wall = J.extract_joins(_payload(
            {"element_id": "9", "joined_to": [],
             "join_allowed_at_end": [False, False]})).joins[0]
        self.assertIsNone(floor.join_allowed_at_end)
        self.assertEqual(wall.join_allowed_at_end, (False, False))
        self.assertNotEqual(floor, wall)


class AnEmptyJoinSetIsData(unittest.TestCase):

    def test_an_element_with_no_joins_gets_a_ROW_not_a_failure(self):
        """"Joined to nothing" is a positive fact about the building.

        Here the stage deliberately diverges from `mep_system_extract`,
        where a pipe without a system goes into the receipt: without a
        system type it cannot be reassembled, while without joins it can
        be.
        """
        got = J.extract_joins(_payload({"element_id": "1", "joined_to": []}))
        self.assertEqual(len(got.joins), 1)
        self.assertEqual(got.failures, ())
        self.assertEqual(got.joins[0].joined_to, ())

    def test_a_failure_means_WE_DID_NOT_LOOK_and_says_so(self):
        got = J.extract_joins(_payload(failures=[
            {"element_id": "7", "reason": "boom", "typed_reason": "read_failed"}]))
        self.assertEqual(got.joins, ())
        self.assertEqual(got.failures[0].typed_reason, "read_failed")
        self.assertEqual(len(got.failures), 1)


class TheIndexRefusesNonsense(unittest.TestCase):

    def test_a_self_join_is_REFUSED_not_silently_dropped(self):
        """A self-loop is not a relation, and silence here would hide a
        malfunction."""
        with self.assertRaises(J.JoinPayloadError) as ctx:
            J.JoinRecord(element_id="1", joined_to=("1",))
        self.assertIn("САМ С СОБОЙ", str(ctx.exception))

    def test_a_duplicate_address_is_refused(self):
        with self.assertRaises(J.JoinPayloadError):
            J.extract_joins(_payload(
                {"element_id": "1", "joined_to": ["2", "2"]}))

    def test_an_unknown_field_is_refused_fail_closed(self):
        with self.assertRaises(J.JoinPayloadError):
            J.extract_joins(_payload(
                {"element_id": "1", "joined_to": [], "surprise": 1}))

    def test_the_order_of_joined_to_does_not_depend_on_revit(self):
        """The decompile's signature must not depend on the order of
        traversal of the document."""
        a = J.extract_joins(_payload({"element_id": "1",
                                      "joined_to": ["30", "4", "200"]}))
        b = J.extract_joins(_payload({"element_id": "1",
                                      "joined_to": ["200", "30", "4"]}))
        self.assertEqual(a.to_json(), b.to_json())
        self.assertEqual(a.joins[0].joined_to, ("4", "30", "200"))


class PairsAreCountedOnce(unittest.TestCase):

    def test_revit_declares_both_sides_and_pairs_does_not_double(self):
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": ["2"]},
            {"element_id": "2", "joined_to": ["1"]}))
        self.assertEqual(got.pairs(), (("1", "2"),))

    def test_the_index_round_trips_through_json(self):
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": ["2"],
             "join_allowed_at_end": [True, False]},
            {"element_id": "2", "joined_to": ["1"]},
            failures=[{"element_id": "3", "reason": "x",
                       "typed_reason": "call_budget_exhausted"}]))
        self.assertEqual(J.JoinExtraction.from_json(got.to_json()), got)

    def test_merge_keeps_every_row_and_every_receipt(self):
        left = J.extract_joins(_payload({"element_id": "1", "joined_to": []}))
        right = J.extract_joins(_payload(
            {"element_id": "2", "joined_to": []},
            failures=[{"element_id": "3", "reason": "x",
                       "typed_reason": "read_failed"}]))
        merged = J.merge_joins([left, right])
        self.assertEqual(len(merged.joins), 2)
        self.assertEqual(len(merged.failures), 1)


class TheGraphGetsTheEdgeAndNothingElse(unittest.TestCase):

    def test_without_the_index_there_are_NO_join_edges(self):
        """FAIL CONTROL: there is no index — the graph must behave as
        before.

        Not "zero joins in the building" but "we did not ask". An edge
        assigned by the graph on its own — by category or by bounding-box
        touch — would be a guess, and it is exactly guesses like these that
        this whole module moves away from.
        """
        graph = graph_from_l0(_HEADER, [_wall("1"), _wall("2")])
        self.assertEqual(graph.relation_edges(Relation.JOINED_TO), ())

    def test_the_index_gives_ONE_symmetric_edge_for_a_mutual_join(self):
        graph = graph_from_l0(
            _HEADER, [_wall("1"), _wall("2")],
            joins={"1": {"joined_to": ["2"]}, "2": {"joined_to": ["1"]}})
        edges = graph.relation_edges(Relation.JOINED_TO)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual(sorted((edges[0].src, edges[0].dst)), ["1", "2"])

    def test_the_RELATION_ITSELF_is_declared_symmetric(self):
        """🔴 THIS TEST WAS PAID FOR BY ITS OWN FAILED CONTROL.

        The FAIL control "remove `JOINED_TO` from `_SYMMETRIC_RELATIONS`"
        left 19 tests GREEN: `_join_edges` collapses the pair with its own
        `seen`, and the test above was checking MY dedup, not the declared
        symmetry of the relation. A classic green-by-construction — inside a
        control written against green-by-construction.

        Symmetry is declared NOT for the sake of `_join_edges`. It is read by
        `GraphEdge.key`, and `BuildingGraph.__init__` catches duplicate edges
        by that key — meaning an edge `1→2`, arriving from ANY other source,
        must be treated as the same thing as `2→1`. What is pinned down is
        the key, not my loop.
        """
        forward = GraphEdge(relation=Relation.JOINED_TO, src="1", dst="2",
                            modality=Modality.PROVEN)
        backward = GraphEdge(relation=Relation.JOINED_TO, src="2", dst="1",
                             modality=Modality.PROVEN)
        self.assertEqual(forward.key, backward.key)

    def test_a_target_outside_the_graph_is_UNRESOLVED_not_REFUTED(self):
        """The boundary of OUR coverage is not a negative fact about the
        building.

        The same modality, for the same reason, as `hosted_in`, where this
        outcome reaches 95.8% on `snowdon_elec_v1`.
        """
        graph = graph_from_l0(
            _HEADER, [_wall("1")], joins={"1": {"joined_to": ["999"]}})
        edge = graph.relation_edges(Relation.JOINED_TO)[0]
        self.assertIs(edge.modality, Modality.UNRESOLVED_TARGET)
        self.assertIsNone(edge.refuted_by)
        self.assertIn("why", edge.evidence)

    def test_the_edge_names_its_source(self):
        """`joined_to` has no right to become the sole relation without a
        witness."""
        graph = graph_from_l0(
            _HEADER, [_wall("1"), _wall("2")],
            joins={"1": {"joined_to": ["2"]}})
        edge = graph.relation_edges(Relation.JOINED_TO)[0]
        self.assertEqual(edge.evidence["source"],
                         "JoinGeometryUtils.GetJoinedElements")

    def test_a_JoinExtraction_can_be_fed_to_the_graph_directly(self):
        """The index and the graph must interface WITHOUT an adapter at the
        caller."""
        index = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": ["2"]},
            {"element_id": "2", "joined_to": ["1"]}))
        graph = graph_from_l0(_HEADER, [_wall("1"), _wall("2")],
                              joins=index.join_index)
        self.assertEqual(len(graph.relation_edges(Relation.JOINED_TO)), 1)


class TheThirdRelationIsItsOwnKind(unittest.TestCase):
    """AN END JOIN — a third kind, and it conflicts with the first on one
    pair of walls.

    THE MEASUREMENT of 18.08.2026 on live Revit, which paid for this entire
    class: two walls butt together — the end is joined, yet
    ``AreElementsJoined`` is **False**, and ``JoinGeometry`` REFUSES with
    "cannot be joined." The joining has already trimmed the curves, there is
    no body overlap, nothing left to merge.

    Before this kind existed, such a pair was recorded as
    ``joined_to: []``, meaning the index was answering "not joined" for
    exactly the case that made the owner say "nothing is joined to
    anything."
    """

    def test_end_joined_while_geometry_is_NOT_joined(self):
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": [],
             "elements_at_end_join": [{"read": True, "elements": ["2"]},
                                      {"read": True, "elements": []}]}))
        self.assertEqual(got.pairs(), (),
                         "геометрия НЕ слита — и это правда, а не пробел")
        self.assertEqual(got.end_join_pairs(), (("1", 0, "2"),),
                         "а стык концом ЕСТЬ, и он обязан пережить первый факт")

    def test_asked_and_empty_is_NOT_the_same_as_not_asked(self):
        """On this kind, a conflation costs the most — the coordinator's
        request, verbatim."""
        asked = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": [],
             "elements_at_end_join": [{"read": True, "elements": []},
                                      {"read": True, "elements": []}]}))
        unasked = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": [],
             "elements_at_end_join": [
                 {"read": False, "why": "Location is not a LocationCurve"},
                 {"read": False, "why": "Location is not a LocationCurve"}]}))
        self.assertEqual(asked.end_join_pairs(), ())
        self.assertEqual(unasked.end_join_pairs(), ())
        # Both gave EMPTY on joins — and differ exactly here:
        self.assertEqual(asked.end_join_refusals(), ())
        self.assertEqual(len(unasked.end_join_refusals()), 2)
        self.assertIn("LocationCurve", unasked.end_join_refusals()[0][2])

    def test_an_unread_end_MUST_name_its_reason(self):
        with self.assertRaises(J.JoinPayloadError) as ctx:
            J.EndJoin(read=False)
        self.assertIn("неотличимо", str(ctx.exception))

    def test_a_read_end_carrying_a_reason_is_a_false_trail(self):
        with self.assertRaises(J.JoinPayloadError):
            J.EndJoin(read=True, why="что-то")

    def test_an_unread_end_cannot_carry_neighbours(self):
        with self.assertRaises(J.JoinPayloadError):
            J.EndJoin(read=False, why="x", elements=("2",))

    def test_a_wall_end_joined_to_ITSELF_is_refused(self):
        with self.assertRaises(J.JoinPayloadError) as ctx:
            J.JoinRecord(element_id="1",
                         elements_at_end_join=(J.EndJoin(True, ("1",)),
                                               J.EndJoin(True, ())))
        self.assertIn("САМА С СОБОЙ", str(ctx.exception))

    def test_the_wire_version_moved_because_the_shape_did(self):
        self.assertTrue(J.JOIN_INDEX_SCHEMA_VERSION.endswith("/2"))
        self.assertTrue(J.JOIN_EXTRACT_SCHEMA_VERSION.endswith("/2"))

    def test_the_third_relation_round_trips(self):
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": ["9"],
             "join_allowed_at_end": [True, False],
             "elements_at_end_join": [{"read": True, "elements": ["2", "3"]},
                                      {"read": False, "why": "boom"}]}))
        self.assertEqual(J.JoinExtraction.from_json(got.to_json()), got)


class AnEmptyEndMeansTwoDifferentThings(unittest.TestCase):
    """LIVE MEASUREMENT of 18.08.2026 — THE SAME GEOMETRY, TWO STATES,
    DIFFERENT ANSWERS.

        JOIN ALLOWED    w1.at(0)=[]  free end
                        w1.at(1)=[18830704, 18830705]
                        w2.at(0)=[18830704, 18830705]
                        w2.at(1)=[]  free end
        JOIN FORBIDDEN  w1.at(1)=[]  w2.at(0)=[]   -- yet the walls STAND
                        BUTTED TOGETHER
        CONTROL         AreElementsJoined = False in BOTH states

    An empty array in the two bottom lines and in the top one means
    DIFFERENT things: "there is no neighbor" versus "a neighbor stands right
    up against it, but the join is forbidden". The difference between a
    correct contour and a hole in it — so the conclusion is drawn and named
    here, rather than left to the consumer.
    """

    def test_the_same_empty_array_splits_into_TWO_named_states(self):
        got = J.extract_joins(_payload(
            # end is empty, join ALLOWED -> free end
            {"element_id": "1", "joined_to": [],
             "join_allowed_at_end": [True, True],
             "elements_at_end_join": [{"read": True, "elements": []},
                                      {"read": True, "elements": []}]},
            # end is empty, join FORBIDDEN -> a neighbor may stand right up
            # against it
            {"element_id": "2", "joined_to": [],
             "join_allowed_at_end": [False, False],
             "elements_at_end_join": [{"read": True, "elements": []},
                                      {"read": True, "elements": []}]}))
        self.assertEqual(got.ends_in_state(J.EndState.FREE_END),
                         (("1", 0), ("1", 1)))
        self.assertEqual(got.ends_in_state(J.EndState.JOIN_FORBIDDEN),
                         (("2", 0), ("2", 1)))

    def test_the_live_pair_reads_free_at_the_outer_ends_and_joined_between(self):
        """The top half of the measurement, verbatim."""
        got = J.extract_joins(_payload(
            {"element_id": "18830704", "joined_to": [],
             "join_allowed_at_end": [True, True],
             "elements_at_end_join": [
                 {"read": True, "elements": []},
                 {"read": True, "elements": ["18830705"]}]},
            {"element_id": "18830705", "joined_to": [],
             "join_allowed_at_end": [True, True],
             "elements_at_end_join": [
                 {"read": True, "elements": ["18830704"]},
                 {"read": True, "elements": []}]}))
        self.assertEqual(got.end_state_census()["joined"], 2)
        self.assertEqual(got.end_state_census()["free_end"], 2)
        self.assertEqual(got.end_state_census()["join_forbidden"], 0)
        self.assertEqual(got.pairs(), (),
                         "AreElementsJoined False в обоих состояниях замера")

    def test_without_the_permission_the_state_says_UNDECIDED_not_free(self):
        """We do not pick a convenient answer when there is nothing to
        distinguish with."""
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": [],
             "elements_at_end_join": [{"read": True, "elements": []},
                                      {"read": True, "elements": []}]}))
        self.assertEqual(got.ends_in_state(J.EndState.EMPTY_UNDECIDED),
                         (("1", 0), ("1", 1)))
        self.assertEqual(got.ends_in_state(J.EndState.FREE_END), ())

    def test_an_unread_end_stays_unread_whatever_the_permission_says(self):
        got = J.extract_joins(_payload(
            {"element_id": "1", "joined_to": [],
             "join_allowed_at_end": [True, False],
             "elements_at_end_join": [{"read": False, "why": "boom"},
                                      {"read": False, "why": "boom"}]}))
        self.assertEqual(got.end_state_census()["not_read"], 2)
        self.assertEqual(got.end_state_census()["free_end"], 0)
        self.assertEqual(got.end_state_census()["join_forbidden"], 0)

    def test_the_census_prints_every_state_including_the_zeroes(self):
        """A missing key would read as "such a thing does not happen"."""
        got = J.extract_joins(_payload({"element_id": "1", "joined_to": []}))
        self.assertEqual(set(got.end_state_census()),
                         {s.value for s in J.EndState})
        self.assertEqual(sum(got.end_state_census().values()), 0)

    def test_the_limit_of_FREE_END_is_NAMED_and_not_pretended_away(self):
        """🔴 THE BOUNDARY IS PINNED DOWN, NOT LEFT IN PROSE.

        `FREE_END` does NOT prove the absence of a neighbor: it proves "there
        is no join, and joining is allowed". A neighbor may stand right up
        against it and not be joined for some other reason. Reading
        `FREE_END` as "this is the edge of the building" is the same mistake
        one floor up, and since the instrument cannot tell the difference, it
        must say so out loud.
        """
        doc = J.EndState.__doc__ or ""
        self.assertIn("does NOT prove there is no neighbor", doc)
        self.assertIn("stand flush", doc)

    def test_the_self_in_the_array_trap_is_named_in_WORDS(self):
        """Live measurement: `w1.at(1)` returned [18830704, 18830705], the
        first one being w1 itself.

        The emitter discards it, but a line of code will not warn the array's
        next reader — so the trap is described in words, and that is pinned
        down here.
        """
        doc = J.EndJoin.__doc__ or ""
        self.assertIn("INCLUDES THE QUERIED WALL ITSELF", doc)
        self.assertIn("18830704", doc)


class TheEndJoinEdgeKeepsItsEnd(unittest.TestCase):

    def _graph(self, joins):
        return graph_from_l0(_HEADER, [_wall("1"), _wall("2")], joins=joins)

    def test_one_stick_gives_TWO_edges_because_the_end_belongs_to_a_wall(self):
        """Not symmetric — unlike `joined_to`, and this is NOT a duplicate.

        "At MY end 0 stands it" and "at ITS end 1 stands me" are two
        different facts about one join with different end numbers.
        """
        graph = self._graph({
            "1": {"joined_to": [],
                  "elements_at_end_join": [{"read": True, "elements": ["2"]},
                                           {"read": True, "elements": []}]},
            "2": {"joined_to": [],
                  "elements_at_end_join": [{"read": True, "elements": []},
                                           {"read": True, "elements": ["1"]}]}})
        edges = graph.relation_edges(Relation.JOINED_AT_END)
        self.assertEqual(len(edges), 2)
        self.assertEqual(
            sorted((e.src, e.dst, e.evidence["ends"]) for e in edges),
            [("1", "2", (0,)), ("2", "1", (1,))])

    def test_the_end_number_survives_into_the_edge(self):
        graph = self._graph({"1": {"joined_to": [], "elements_at_end_join": [
            {"read": True, "elements": []}, {"read": True, "elements": ["2"]}]}})
        edge = graph.relation_edges(Relation.JOINED_AT_END)[0]
        self.assertEqual(edge.evidence["ends"], (1,))
        self.assertEqual(edge.evidence["source"],
                         "LocationCurve.get_ElementsAtJoin")

    def test_a_pair_shut_at_BOTH_ends_is_ONE_edge_carrying_both(self):
        """🔴 THE FIRST GRAPH RUN ON A REAL BUILDING REFUSED HERE.

        MNVNK, 22.08.2026: 33 944 nodes, 49 907 edges — and `BuildingGraph`
        was refusing ENTIRELY ("duplicate relation/src/dst edge truth is
        forbidden") because of TWO pairs of walls butted at both ends
        (`10032505`/`10032585` and `10032574`/`10032584`). The edge key is
        the triple `relation/src/dst`, it carries no end number, while the
        previous revision was producing one edge per end.

        Measurement across the corpus: such a pair occurs in 2 of 5
        decompiles (MNVNK 2, bench_A 4), while the largest index,
        `k2v33_join2` — 17 982 records — has ZERO of them. The only run the
        module had referenced was going over a clean one, so the building
        caught the defect first.
        """
        graph = self._graph({"1": {"joined_to": [], "elements_at_end_join": [
            {"read": True, "elements": ["2"]},
            {"read": True, "elements": ["2"]}]}})
        edges = graph.relation_edges(Relation.JOINED_AT_END)
        self.assertEqual(len(edges), 1, "одна пара — одно ребро")
        self.assertEqual(edges[0].evidence["ends"], (0, 1),
                         "«сомкнуты обоими концами» — факт о здании, и он "
                         "обязан пережить свёртку, а не исчезнуть в ней")

    def test_the_same_end_named_twice_does_not_grow_the_evidence(self):
        """A repeated neighbor AT ONE end is index noise, not a second
        join."""
        graph = self._graph({"1": {"joined_to": [], "elements_at_end_join": [
            {"read": True, "elements": ["2", "2"]},
            {"read": True, "elements": []}]}})
        edges = graph.relation_edges(Relation.JOINED_AT_END)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].evidence["ends"], (0,))

    def test_an_UNREAD_end_gives_no_edge_at_all(self):
        """An edge means "there is a join". "We don't know" is never an
        edge."""
        graph = self._graph({"1": {"joined_to": [], "elements_at_end_join": [
            {"read": False, "why": "boom"}, {"read": False, "why": "boom"}]}})
        self.assertEqual(graph.relation_edges(Relation.JOINED_AT_END), ())

    def test_the_unread_guard_holds_on_a_RAW_mapping_too(self):
        """🔴 A SECOND GREEN-BY-CONSTRUCTION, CAUGHT BY ITS OWN CONTROL.

        The test above was not going red when the `if not read: continue`
        guard was removed — and it could not: `EndJoin` FORBIDS an unread end
        from carrying neighbors, so through the typed path the list is empty
        regardless. The control was checking the data class's invariant, not
        the graph's guard.

        But `graph_from_l0(joins=...)` is declared as `Mapping[str, Any]` and
        accepts a RAW dictionary, bypassing `EndJoin`. That is exactly where
        the guard does its work: without it, "we didn't read it, but here are
        its neighbors anyway" would become a `PROVEN` edge — evidence
        assembled out of a refusal.
        """
        graph = self._graph({"1": {"joined_to": [], "elements_at_end_join": [
            {"read": False, "why": "boom", "elements": ["2"]},
            {"read": True, "elements": []}]}})
        self.assertEqual(graph.relation_edges(Relation.JOINED_AT_END), ())

    def test_the_two_kinds_do_not_collapse_into_each_other(self):
        graph = self._graph({
            "1": {"joined_to": ["2"],
                  "elements_at_end_join": [{"read": True, "elements": ["2"]},
                                           {"read": True, "elements": []}]}})
        self.assertEqual(len(graph.relation_edges(Relation.JOINED_TO)), 1)
        self.assertEqual(len(graph.relation_edges(Relation.JOINED_AT_END)), 1)


class TheEmittedCSharpIsBuiltNotGuessed(unittest.TestCase):

    def test_all_THREE_relations_are_read_by_their_documented_members(self):
        cs = J.build_join_extract_cs(["1", "2"])
        self.assertIn("JoinGeometryUtils.GetJoinedElements", cs)
        self.assertIn("WallUtils.IsWallJoinAllowedAtEnd", cs)
        self.assertIn("get_ElementsAtJoin", cs)

    def test_each_end_is_read_in_its_OWN_try(self):
        """The de-join lesson, not repeated here.

        In `authoring.py:7324` both ends stand under one empty `catch`: if
        the first one throws, the second never runs, and this is
        indistinguishable from success. Here each end has its own catch, and
        the refusal is NAMED.
        """
        cs = J.build_join_extract_cs(["1"])
        body = cs[cs.index("get_ElementsAtJoin") - 2000:]
        self.assertIn("__jnEndIx < 2", body, "концы читаются циклом по двум")
        self.assertIn('__jnCell["why"]', body, "отказ конца назван, а не пуст")
        self.assertNotIn("catch { }", cs, "пустой перехват — тот самый дефект")

    def test_the_reader_never_writes(self):
        """The side stage is a READ. A transaction here would be a write into
        someone else's model."""
        cs = J.build_join_extract_cs(["1"])
        for forbidden in ("new Transaction", "JoinGeometry(", "UnjoinGeometry",
                          "DisallowWallJoinAtEnd", "AllowWallJoinAtEnd"):
            self.assertNotIn(forbidden, cs, f"читающая стадия несёт {forbidden}")

    def test_every_requested_id_reaches_the_body(self):
        cs = J.build_join_extract_cs(["19227219", "456"])
        self.assertIn("19227219", cs)
        self.assertIn("456", cs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
