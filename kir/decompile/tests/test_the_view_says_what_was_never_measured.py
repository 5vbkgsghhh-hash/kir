"""THE GRAPH VIEW DID NOT TELL "NOT MEASURED" APART FROM "MEASURED EMPTY"
(RV-05).

MEASURED (04.09.2026), reproduced by this file:

    graph_from_l0(..., joins=None)  and  graph_from_l0(..., joins={})
       the views (graph_view) are IDENTICAL
       the censuses          DIFFER

That is, the core HOLDS the distinction — `census.sources_absent`
carries `joins` — but the projection for the reader was losing it.
`GraphView.relations` is built by `relation_counts()`, which does not
carry empty kinds AT ALL (and honestly says so in its own docstring:
"AN ABSENT KEY MUST NOT BE READ AS ZERO… ask `relation_count()`"). The
viewer cannot ask `relation_count()`: what it has in hand is a view,
not a graph. So the advice was given to someone unable to follow it —
and "there are no joints in the building" reached a person under the
same shape as "we were never given a joint index."

The cost of this zero is measured and recorded alongside: tower
`k2_ar_rd_v15` has no `join.index.json`, has 15,341 walls, and a live
canon measurement gives 143 joined pairs out of 288. The zero was OUR
OWN blindness.

THE SHAPE IS TAKEN FROM A NEIGHBORING FIELD, NOT INVENTED. In
`graph_view`'s own docstring, the same law is already declared for
`without_l1`: "not submitted -> `None`, meaning 'was not asked'; an
empty tuple means 'asked, there are none.'" Here it is carried through
to edge kinds: `unmeasured_relations` is empty when everything has been
measured, and carries the names of kinds whose zero means nothing.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import Relation, graph_from_l0, graph_view


def _header() -> dict:
    return {"levels": [{"id": "L1", "name": "1", "elevation_mm": 0.0}],
            "rooms": [
                {"id": "R1", "level_id": "L1",
                 "boundary_mm": [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]},
                {"id": "R2", "level_id": "L1",
                 "boundary_mm": [[4000, 0], [8000, 0],
                                 [8000, 4000], [4000, 4000]]}]}


_ELEMENTS = [{"element_id": "W1", "category": "OST_Walls", "level_id": "L1"},
             {"element_id": "W2", "category": "OST_Walls", "level_id": "L1"}]


def _view(**kwargs):
    return graph_view(graph_from_l0(_header(), _ELEMENTS, **kwargs))


class ВидНазываетТо_ЧегоНеМерили(unittest.TestCase):
    """The axis of CAPABILITY: what a reader of the view can now tell apart."""

    def test_the_measured_zero_and_the_unmeasured_one_are_DIFFERENT_views(self):
        not_asked = _view(joins=None)
        asked_and_empty = _view(joins={})
        self.assertNotEqual(not_asked, asked_and_empty,
                            "виды снова совпали — читатель опять не отличит "
                            "нашу слепоту от факта о здании")

    def test_an_unsupplied_index_NAMES_the_relations_it_blinded(self):
        view = _view(joins=None)
        self.assertIn(Relation.JOINED_TO.value, view.unmeasured_relations)
        self.assertIn(Relation.JOINED_AT_END.value, view.unmeasured_relations)
        self.assertIn("joins", view.sources_absent)

    def test_a_supplied_empty_index_leaves_the_zero_MEANING_zero(self):
        """An empty tuple — "asked, there are none," exactly like `without_l1`."""
        view = _view(joins={})
        self.assertNotIn(Relation.JOINED_TO.value, view.unmeasured_relations)
        self.assertNotIn("joins", view.sources_absent)

    def test_the_view_agrees_with_the_graph_it_projects(self):
        """The projection recomputes nothing on its own — otherwise it would silently drift."""
        graph = graph_from_l0(_header(), _ELEMENTS, joins=None)
        view = graph_view(graph)
        self.assertEqual(
            view.unmeasured_relations,
            tuple(rel.value for rel in graph.unmeasured_relations()))
        self.assertEqual(view.sources_absent, graph.census.sources_absent)

    def test_the_adjacency_census_reaches_the_view_too(self):
        """The third outcome of the same law: the predicate was called, and it refused."""
        door = {"element_id": "D1", "category": "OST_Doors", "level_id": "L1"}
        silent = _view(joins={}, link_ids=())
        spoken = graph_view(graph_from_l0(
            _header(), _ELEMENTS + [door], joins={}, link_ids=(),
            room_adjacency=True))
        self.assertIsNone(silent.adjacency, "не звали — не «отказов нет»")
        self.assertEqual(dict(spoken.adjacency["refusals"]),
                         {"opening_without_position": 1})


class ЧестныеПоляНеПострадали(unittest.TestCase):
    """CONTROL: a field added to the view does not move what the view already said."""

    def test_relations_still_omit_empty_kinds_exactly_as_before(self):
        view = _view(joins={})
        self.assertNotIn(Relation.JOINED_TO.value, view.relations)

    def test_a_fully_supplied_graph_names_nothing_as_unmeasured(self):
        view = _view(joins={}, link_ids=(), room_adjacency=True)
        self.assertEqual(view.unmeasured_relations, ())
        self.assertEqual(view.sources_absent, ())

    def test_without_l1_keeps_its_own_three_outcomes(self):
        graph = graph_from_l0(_header(), _ELEMENTS, joins={})
        self.assertIsNone(graph_view(graph).without_l1)
        self.assertEqual(graph_view(graph, l1_source_ids=["W1", "W2"]).without_l1,
                         ())
        self.assertEqual(graph_view(graph, l1_source_ids=["W1"]).without_l1,
                         ("W2",))


class КонтрольFail(unittest.TestCase):
    """FAIL CONTROL: bring back the old view — the property must disappear."""

    def test_the_old_projection_makes_the_two_graphs_indistinguishable(self):
        def then(view):
            """The old view verbatim: vaults and the census WITHOUT the unmeasured."""
            return (dict(view.relations), dict(view.unresolved_by_reason),
                    dict(view.refuted_by_rule), view.without_l1,
                    view.census_rows, dict(view.census_refusals))

        not_asked, asked_and_empty = _view(joins=None), _view(joins={})
        self.assertEqual(then(not_asked), then(asked_and_empty),
                         "прежний вид давал ОДИН ответ на два разных факта")
        self.assertNotEqual(not_asked.unmeasured_relations,
                            asked_and_empty.unmeasured_relations,
                            "нынешний вид обязан их различать")


if __name__ == "__main__":
    unittest.main()
