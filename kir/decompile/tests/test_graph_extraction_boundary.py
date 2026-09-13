"""THE EXTRACTION BOUNDARY IS ONE CONCEPT, BUT NOT ONE CLASS.

The temptation was to call everything "a target outside extraction" with one
word. THE MEASUREMENT of 10.08.2026 (raw decompile of `L0.jsonl`, corpus
`backend/backend/data/decompile`, machine-local) did NOT CONFIRM this: a
dangling `host_id` and a dangling `bounds_room` are DIFFERENT populations, and
they diverge by three orders of magnitude.

    `snowdon_elec_v1`   host 959 edges -> A TOTAL OF 3 distinct targets,
                        and all three are `link` records of the same stream
    `snowdon_plumb_v5`  host  86 edges ->   4 targets; bounds_room 0
    `демо-v3`           host   0;  bounds_room 4 352 edges -> 2 146 targets,
                        median 2 edges per target, `link` records in the stream 0
    `sob62_r23_v5`      host   1;  bounds_room 340 -> 184 targets

Intersection of the target sets: 0 across three buildings, 1 on
`sob62_r23_v5` — and that one is a `link` record, carrying along 88 room
boundary edges.

Classes that must remain separate (clash team's numbers across the whole
corpus: 1 263 dangling edges, of which 1 010 go to a linked file and 86 to
`ReferencePlane`, assigned by `clash/hulls.KIND_TABLE` to `not_a_body`):

  * host in a LINKED FILE — readable further if the link is opened;
  * host CANNOT HAVE A BODY BY NATURE — nothing further to read, ever;
  * room boundary outside extraction — the third, most numerous case.

The difference is exactly in WHAT TO DO WITH THEM, so they cannot be merged
back together.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    Modality,
    OutsideExtraction,
    Relation,
    graph_from_l0,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _el(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


def _rooms(*pairs):
    return {"doc_name": "t", "levels": [], "grids": [],
            "rooms": [{"id": rid, "bounding_element_ids": list(bounds)}
                      for rid, bounds in pairs]}


class LinkIsAPositiveFactNotBlindness(unittest.TestCase):
    """The 959 edges of `snowdon_elec_v1` were naming OUR blindness. L0 knew
    the answer."""

    def test_host_that_is_a_link_resolves_and_is_proven(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            link_ids=["LNK-1"])
        edges = graph.relation_edges(Relation.HOSTED_IN_LINK)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN,
                      "связь названа неразрешённой целью — это наша слепота")
        self.assertEqual(edges[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)
        self.assertEqual(graph.unresolved_targets(), ())

    def test_without_the_link_list_the_same_edge_stays_unresolved(self) -> None:
        """The absence of an input must read as "was not asked", not as
        "there is no relation": the difference is whether to read further."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")])
        self.assertEqual(len(graph.unresolved_targets()), 1)
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)


class BodilessHostIsItsOwnClass(unittest.TestCase):
    """86 of 1 263 dangling ones are `ReferencePlane`, which will NEVER become
    a body."""

    def test_caller_supplied_bodiless_target_is_named_apart(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")],
            bodiless_target_ids=["RP-9"])
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value)

    def test_the_graph_NEVER_guesses_this_class_from_L0(self) -> None:
        """There is no address for such a target in the stream at all, so
        there is nothing from which to state a category. The class comes from
        the caller with the kind table — otherwise this would be a guess by
        category, which is exactly what the whole module moves away from."""
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")])
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)


class RoomBoundaryIsAThirdClass(unittest.TestCase):
    """4 352 edges of `демо-v3` against 0 dangling hosts on the same building."""

    def test_boundary_outside_extraction_has_its_own_name(self) -> None:
        graph = graph_from_l0(_rooms(("R1", ["W-MISSING"])),
                              [_el("R1", "OST_Rooms")])
        edges = graph.relation_edges(Relation.BOUNDS_ROOM)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(
            edges[0].evidence["why"],
            OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED.value)

    def test_a_link_bounding_a_room_is_named_as_a_link(self) -> None:
        """`sob62_r23_v5`: one `link` record carries 88 boundary edges."""
        graph = graph_from_l0(_rooms(("R1", ["LNK-1"])),
                              [_el("R1", "OST_Rooms")], link_ids=["LNK-1"])
        edge = graph.relation_edges(Relation.BOUNDS_ROOM)[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_the_three_classes_do_not_share_a_name(self) -> None:
        values = {OutsideExtraction.RESOLVED_TO_LINK.value,
                  OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value,
                  OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED.value,
                  OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value}
        self.assertEqual(len(values), 4)


class EveryUnresolvedEdgeNamesItsReason(unittest.TestCase):
    """"A target outside extraction" without a sub-reason is again one word
    for different facts."""

    def test_no_unresolved_edge_is_left_without_a_why(self) -> None:
        graph = graph_from_l0(
            _rooms(("R1", ["W-MISSING"])),
            [_el("R1", "OST_Rooms"),
             _el("F1", "OST_ElectricalFixtures", host_id="X-1"),
             _el("F2", "OST_Windows", level_id="L-MISSING")])
        unresolved = graph.unresolved_targets()
        self.assertTrue(unresolved)
        for edge in unresolved:
            self.assertIn("why", edge.evidence, f"{edge.relation} без причины")
            self.assertIn(edge.evidence["why"],
                          {e.value for e in OutsideExtraction})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
