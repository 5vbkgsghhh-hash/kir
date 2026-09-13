"""MEASURED CROSS-SECTION AND THE VIEWER PROJECTION — refuting tests.

WHAT WAS BEING LOST. L0 carries the outer diameter of EVERY pipe, while
`lift._lift_pipe` reads only `RBS_PIPE_DIAMETER_PARAM` (the nominal). The
10.08.2026 measurement (raw decompile of `L0.jsonl`, `snowdon_plumb_v4`,
machine-local corpus):

    pipes 15 342, with outer 15 342, with nominal 15 342 — i.e. 100 % carry BOTH
    distinct pairs (nominal -> outer): 14
        12.7  -> 15.875   x7318      50.8  -> 60.325  x1835
        25.4  -> 28.575   x3300      50.8  -> 53.975  x530
        101.6 -> 114.3    x1424      152.4 -> 168.275 x430
    outer EQUALS nominal for only 20 of 15 342 pipes

THE KEY FACT, AND NOT JUST A LOSS: **nominal 50.8 corresponds to both 60.325
and 53.975**, so the nominal -> outer mapping is NOT A FUNCTION, and
recovering the outer diameter from what the op carries is IMPOSSIBLE IN
PRINCIPLE — it is determined by the TYPE.

And this is not only pipes: `snowdon_elec_v1` carries
`RBS_CONDUIT_OUTER_DIAM_PARAM` on 530 of 605 nodes with a measured
cross-section. Nobody named the category.

WHY THE FACT LANDED ON THE NODE, NOT IN THE OP'S OPERAND. The outer diameter
is something Revit DERIVES from the type; the op already carries `pipe_type`
by name (`_catalog_ref`), so REASSEMBLY loses nothing: Revit will derive the
outer diameter from the same type. What loses it are the OFFLINE READERS —
clash and the viewer — which have no access to the document's type-size
table. Making it a witnessable operand would mean claiming as our own
something Revit assigns, and getting a witness demanding something nobody
asked for — exactly the class closed off in
`tests/test_silent_defaults.py` ("either the emitter SETS the value, or Revit
decides").
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    Existence,
    graph_from_l0,
    graph_view,
    outer_size_mm,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _pipe(element_id, params):
    return {"element_id": element_id, "category": "OST_PipeCurves",
            "type_id": "T1", "type_name": "Труба", "level_id": None,
            "host_id": None, "params": params}


class NominalNeverStandsInForOuter(unittest.TestCase):
    """REFUTING CASE: one nominal — two outer diameters."""

    def test_the_same_nominal_carries_two_different_outers(self) -> None:
        """Measurement `snowdon_plumb_v4`: 50.8 -> 60.325 (1 835 pipes) AND
        50.8 -> 53.975 (530 pipes). No table keyed by nominal can distinguish
        them — the outer diameter is a function of TYPE."""
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_DIAMETER_PARAM": 50.8,
                         "RBS_PIPE_OUTER_DIAMETER": 60.325}),
            _pipe("P2", {"RBS_PIPE_DIAMETER_PARAM": 50.8,
                         "RBS_PIPE_OUTER_DIAMETER": 53.975})])
        self.assertEqual(outer_size_mm(graph.node("P1"))[0], 60.325)
        self.assertEqual(outer_size_mm(graph.node("P2"))[0], 53.975)
        self.assertEqual(graph.node("P1").section["RBS_PIPE_DIAMETER_PARAM"],
                         graph.node("P2").section["RBS_PIPE_DIAMETER_PARAM"])

    def test_nominal_alone_yields_None_not_a_substitute(self) -> None:
        """Substituting the nominal would mean declaring the type-size's NAME
        to be the body, and undersizing the body by 9.525 mm — in the
        dangerous direction: a clash would go undetected."""
        graph = graph_from_l0(
            _HEADER, [_pipe("P1", {"RBS_PIPE_DIAMETER_PARAM": 50.8})])
        self.assertIsNone(outer_size_mm(graph.node("P1")))

    def test_the_measured_source_rides_with_the_value(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325})])
        value, source = outer_size_mm(graph.node("P1"))
        self.assertEqual(source, "RBS_PIPE_OUTER_DIAMETER")
        self.assertEqual(value, 60.325)

    def test_conduits_are_covered_too(self) -> None:
        """`snowdon_elec_v1`: 530 conduits carry the outer diameter. The
        category that nobody named is closed by the same closed list."""
        row = _pipe("C1", {"RBS_CONDUIT_OUTER_DIAM_PARAM": 55.8038})
        row["category"] = "OST_Conduit"
        graph = graph_from_l0(_HEADER, [row])
        self.assertEqual(outer_size_mm(graph.node("C1"))[1],
                         "RBS_CONDUIT_OUTER_DIAM_PARAM")


class SectionComesFromOneClosedList(unittest.TestCase):
    """Two dictionaries for one fact diverge — the list is taken from the
    reading."""

    def test_the_list_is_the_extractor_list_not_a_copy(self) -> None:
        from kir.decompile.extract import SECTION_PARAM_NAMES
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {name: 1.0 for name in SECTION_PARAM_NAMES})])
        self.assertEqual(set(graph.node("P1").section),
                         set(SECTION_PARAM_NAMES))

    def test_unlisted_params_do_not_leak_into_section(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325,
                         "SOME_OTHER_PARAM": 7.0})])
        self.assertNotIn("SOME_OTHER_PARAM", graph.node("P1").section)

    def test_absent_section_is_empty_not_zero(self) -> None:
        graph = graph_from_l0(_HEADER, [_pipe("P1", {})])
        self.assertEqual(dict(graph.node("P1").section), {})
        self.assertIsNone(outer_size_mm(graph.node("P1")))


class ViewerReadsStateNotHulls(unittest.TestCase):
    """The viewer was reading SHELLS: on `демо-v3` 99.89 % of them are
    bounding boxes, and 38.24 % are degenerate. The projection answers the
    question "what kind of node is this"."""

    def _graph(self):
        return graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325}),
            _pipe("P2", {})])

    def test_projection_carries_both_honesty_axes(self) -> None:
        view = graph_view(self._graph())
        self.assertEqual(view.authority, {"declared": 2})
        self.assertEqual(view.existence, {Existence.MATERIALIZED.value: 2})
        for node in view.nodes:
            self.assertTrue(node.authority_source,
                            "ось без свидетеля не читается")

    def test_projection_carries_no_body_geometry(self) -> None:
        """Boundary of responsibility: the projection does NOT draw. Offline
        3D shows what was declared; what Revit derives does not exist offline,
        and drawing it as the same body would mean signing off on an axis
        that was never read."""
        node = graph_view(self._graph()).nodes[0]
        for banned in ("bbox", "hull", "solid", "mesh", "vertices"):
            self.assertFalse(hasattr(node, banned))

    def test_without_l1_distinguishes_not_asked_from_none(self) -> None:
        """`None` means "was not asked", an empty tuple means "asked, there
        are none". The same law as for `hosted` in clashes."""
        graph = self._graph()
        self.assertIsNone(graph_view(graph).without_l1)
        self.assertEqual(graph_view(graph, l1_source_ids=["P1", "P2"]).without_l1,
                         ())
        self.assertEqual(graph_view(graph, l1_source_ids=["P1"]).without_l1,
                         ("P2",))

    def test_census_and_honesty_counters_ride_in_the_projection(self) -> None:
        view = graph_view(self._graph())
        self.assertEqual(view.census_rows, 2)
        self.assertEqual(dict(view.census_refusals), {})
        self.assertEqual(dict(view.unresolved_by_reason), {})
        self.assertEqual(dict(view.refuted_by_rule), {})

    def test_unresolved_reasons_reach_the_viewer_named(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [{"element_id": "F1", "category": "OST_ElectricalFixtures",
              "type_id": "t", "type_name": "T", "level_id": None,
              "host_id": "LNK-1", "params": {}}])
        view = graph_view(graph)
        self.assertEqual(sum(view.unresolved_by_reason.values()), 1)
        self.assertNotIn("unnamed", view.unresolved_by_reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
