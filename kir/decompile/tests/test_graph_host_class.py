"""HOST CLASS IS A MEASURED FACT, NOT A PROPERTY OF THE CATEGORY.

The plan was to put "does the category have physical extent" as a column on
`CategorySpec` next to `discipline`. THE MEASUREMENT of 11.08.2026 (raw
decompile of the corpus `backend/backend/data/decompile`, machine-local)
overturns it for two independent reasons.

**(1) ⛔ OVERTURNED 22.08.2026 — THE ARGUMENT'S TERM EXPIRED.** It read:
"`ReferencePlane` is not a category but a Revit CLASS; the extractor table has
77 rows, and neither `OST_CLines` nor `OST_ReferencePlanes` is among them —
planes are not extracted at all (1 037 of them in the `snowdon_plumb_v5`
census against 0 in the stream); the `CategorySpec` column would have had
nowhere to be written." The first half still holds today, the second half has
died: on that day the row
`CategorySpec("OST_CLines", ".OfClass(typeof(ReferencePlane))")` landed, and
planes became extractable — **9 724 across ten of ten corpus buildings**. The
argument was not a mistake; the corpus grew, and the term expired silently —
the same shape as the window marks on 29.07. The consequence for the GRAPH is
decided separately and by number: `AReferencePlaneHostIsADATUMNotABody` below.

**(2) For a DANGLING host the category is unknowable in principle** — there
is no row for this address in the snapshot. A table keyed by category answers
a question that a dangling target has nothing to ask with.

**And the answer already lies on disk, per element:** `host_class` in
`family_placement.index.json`, taken by reading. Measurement:

    `snowdon_plumb_v5`  Wall 2 647, Ceiling 100, **ReferencePlane 86**,
                        Level 25, FamilyInstance 2 — exactly those 86 dangling
                        ones
    `sob62_r23_v5`      Wall 185, FamilyInstance 3, **RevitLinkInstance 1**
                        — exactly that one single dangling one
    `демо-v3`           Wall 5 941
    `snowdon_elec_v1`   index exists, 20 records, 0 with a host — its 959
                        hosts are not family instances, and this is an HONEST
                        "the index is silent", not "there is no host"

The `fold._discipline` precedent is HONORED here: it prohibits a SECOND
dictionary about one concept, and here no second one is started — what is
already recorded is being read.
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


class MeasuredHostClassDecides(unittest.TestCase):
    """The reason is taken from the class that was read, not from a list
    supplied by the caller."""

    def test_reference_plane_is_named_from_the_index(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")],
            host_classes={"W1": "ReferencePlane"})
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value)
        self.assertEqual(edge.evidence["host_class"], "ReferencePlane")

    def test_link_class_is_named_from_the_index(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            host_classes={"F1": "RevitLinkInstance"})
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_silent_index_stays_honestly_unknown(self) -> None:
        """`snowdon_elec_v1`: the index exists, but is silent about these
        elements. The index's silence is not a fact about the host."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="X-1")],
            host_classes={"OTHER": "Wall"})
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)
        self.assertIsNone(edge.evidence["host_class"])

    def test_measured_class_beats_the_caller_supplied_list(self) -> None:
        """The list remains a fallback, but the MEASURED outranks the guess."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            host_classes={"F1": "RevitLinkInstance"},
            bodiless_target_ids=["LNK-1"])
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_no_index_at_all_changes_nothing(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="X-1")])
        self.assertIs(graph.unresolved_targets()[0].modality,
                      Modality.UNRESOLVED_TARGET)


class TheCategoryTableCannotAnswerThis(unittest.TestCase):
    """WHY THE REASON IS TAKEN FROM THE CLASS, NOT FROM THE CATEGORY TABLE.

    🔴 THIS CLASS HELD TWO ARGUMENTS, AND ONE OF THEM DIED ON 22.08.2026.

    ARGUMENT ONE (⛔ OVERTURNED BY MEASUREMENT): "there simply IS NO row for
    reference planes — they are not extracted at all." On that day the row
    `CategorySpec("OST_CLines", ".OfClass(typeof(ReferencePlane))")` landed in
    the table, and planes became extractable: 9 724 of them across ten of ten
    corpus buildings. The argument was not a mistake — its TERM EXPIRED.

    ARGUMENT TWO (✅ STANDS, and it is load-bearing): for a DANGLING host the
    category is unknowable IN PRINCIPLE — there is no row for this address in
    the snapshot. No completeness of the table changes this, and so the
    sub-reason is taken from the MEASURED `host_class` of the side index, not
    from the category.

    🔴 AND WHY THE ROW COUNTER WAS REMOVED RATHER THAN BUMPED FROM 77 TO 79. It
    had already gone red BEFORE this wave — the window marks made it 78 — and
    under the dead counter lay the premise that the wave overturns: exactly
    the shape of "red for a known reason hides the next one". The row count
    of someone else's table also proves nothing about THIS module: it does
    not ask it for a single row. What is worth checking here is that the
    reason is taken from the class; that is what the tests above check.
    """

    def test_the_dead_premise_is_gone_planes_ARE_extractable_now(self) -> None:
        """REFUTING CONTROL OF THE OVERTURN ITSELF: if planes ever fall out of
        the table again, the argument about `host_class` must not silently
        "fix itself" with the old reason — it must stay on its own."""
        from kir.decompile.extract import _CATEGORY_SPECS
        names = {spec.name for spec in _CATEGORY_SPECS}
        self.assertIn("OST_CLines", names)

    def test_a_dangling_host_has_no_category_to_look_up_at_all(self) -> None:
        """ARGUMENT TWO, CHECKED: a target outside the snapshot has no
        category."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_PlumbingFixtures", host_id="RP-404")])
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.dst, "RP-404")
        self.assertNotIn(edge.dst, graph.nodes)
        # It has no category — so the category table is powerless too; the
        # reason comes from `host_class` if it was supplied, and "not in the
        # snapshot" otherwise.
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)


class AReferencePlaneHostIsADATUMNotABody(unittest.TestCase):
    """🔴 THE DIRECT CONSEQUENCE OF TAKING UP PLANES, AND IT HAD TO BE DECIDED.

    While planes were not extracted, a plane-host could ONLY be dangling — 86
    such edges on `snowdon_plumb_v5`, all with the sub-reason
    `host_cannot_have_a_body`. Since 22.08 a plane becomes an ordinary node,
    and the edge resolves. The question that had to get an answer at this
    point: BY WHICH relation.

    The answer is `PLACED_ON_DATUM`, not `HOSTED_IN`, by the same argument by
    which levels and grids already stand there: a datum is an author's mark,
    not a physical body. Leave `HOSTED_IN` in place, and "a fixture is placed
    IN a reference plane" would stand next to "a door is placed IN a wall" —
    exactly the conflation for the sake of untangling which this whole module
    was written.
    """

    def test_a_resolved_plane_host_is_placed_on_datum(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _el("RP-1", "OST_CLines"),
            _el("F1", "OST_PlumbingFixtures", host_id="RP-1")])
        edges = graph.relation_edges(Relation.PLACED_ON_DATUM)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual((edges[0].src, edges[0].dst), ("F1", "RP-1"))
        self.assertEqual(edges[0].evidence["host_category"], "OST_CLines")
        self.assertEqual(graph.relation_edges(Relation.HOSTED_IN), ())

    def test_a_wall_host_is_STILL_hosted_in(self) -> None:
        """CONTROL IN THE REVERSE DIRECTION: not everything indiscriminately
        became a datum."""
        graph = graph_from_l0(_HEADER, [
            _el("W1", "OST_Walls"),
            _el("D1", "OST_Doors", host_id="W1")])
        self.assertEqual(len(graph.relation_edges(Relation.HOSTED_IN)), 1)
        self.assertEqual(graph.relation_edges(Relation.PLACED_ON_DATUM), ())

    def test_an_UNREAD_plane_still_answers_cannot_have_a_body(self) -> None:
        """The class is not overturned but NARROWED: it is about a target that
        is NOT in the stream.

        All 76 corpus snapshots were taken before the wave and carry 0 planes
        in the stream — today this branch answers for them exactly as before.
        """
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_PlumbingFixtures", host_id="RP-9")],
            host_classes={"F1": "ReferencePlane"})
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
