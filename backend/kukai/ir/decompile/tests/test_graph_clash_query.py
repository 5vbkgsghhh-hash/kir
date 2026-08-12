"""КЛЕШ КАК ЗАПРОС С ОБЛАСТЬЮ — опровергающие тесты.

Порог назван заранее и замерен командой CLASH: `демо-v3` — 84 120 узлов против
770 234 пар-кандидатов (отношение **9.15**), отчёт **666 МБ**, пик RSS
**2.66 ГБ**, при том что сама сетка стоит 0.81 с. Если материализация рёбер
обязательна, граф для клеша не годится — так и было записано заранее.

Три склеенных отношения, разводимые здесь по осям `relation` × `modality`:
касание (~треть всех пар: 7 804 из 27 327 на фасаде), взаимопроникновение тел
(недоказуемо: `exact` = 0 на 664 870 оболочках 65 разборов) и пересечение
оболочек (факт о нашем ОПИСАНИИ).

Догадка, которую заменяет ребро: `resolve.ASSEMBLY_PAIRS` относит к сборке
**467 из 3 348 перекрытий (14.0 %)** на `sob62_r23_v5` по ПАРЕ ЯРЛЫКОВ. Замер
`host_id` 10.08 показывает, куда догадка не достаёт: на `sob62_fas_r23_v17`
**9 из 14** дверей имеют хозяином `OST_CurtainWallPanels`; на
`snowdon_plumb_v5` **89 из 1 425** импостов — панель, **23 из 640** панелей —
другую панель, а **21** `OST_GenericModel` — вовсе `OST_Levels`.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    GraphBuildError,
    Modality,
    graph_from_l0,
)
from kukai.ir.decompile.graph_clash_query import (
    ClashQuery,
    ClashRelation,
    ClashRelationEdge,
    ClashScope,
    ScopeCensus,
    assembly_relation_of,
)


def _element(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _census(n):
    return ScopeCensus(nodes_in_scope=n, nodes_with_hull=n, refusals={})


class ClashEdgeIsTypedTwice(unittest.TestCase):
    """`relation` и `modality` — две ОРТОГОНАЛЬНЫЕ оси, а не одно слово."""

    def test_contact_is_not_a_finding_but_an_assembly_relation(self) -> None:
        edge = ClashRelationEdge("1", "2", ClashRelation.CONTACT,
                                 Modality.PROVEN)
        self.assertIs(edge.relation, ClashRelation.CONTACT)

    def test_PROVEN_OVERLAP_is_structurally_unconstructible(self) -> None:
        """`exact` недостижим — 65 разборов, 664 870 оболочек, 0 случаев.
        Значит вердикт `confirmed` был мёртвым кодом. Отказ структурный, чтобы
        он не воскрес молча."""
        with self.assertRaises(GraphBuildError):
            ClashRelationEdge("1", "2", ClashRelation.OVERLAP, Modality.PROVEN)

    def test_possible_overlap_is_the_honest_form(self) -> None:
        edge = ClashRelationEdge("1", "2", ClashRelation.OVERLAP,
                                 Modality.POSSIBLE,
                                 evidence={"hull_source": "bbox"})
        self.assertIs(edge.modality, Modality.POSSIBLE)


class RefutationKeepsTheEdge(unittest.TestCase):
    """Опровержение — ЭТО РЕБРО, а не отсутствие ребра."""

    def test_refuted_without_the_coarsening_name_is_unconstructible(self) -> None:
        with self.assertRaises(GraphBuildError):
            ClashRelationEdge("1", "2", ClashRelation.OVERLAP, Modality.REFUTED)

    def test_refuted_by_names_the_coarsening_and_the_edge_survives(self) -> None:
        edge = ClashRelationEdge("1", "2", ClashRelation.OVERLAP,
                                 Modality.REFUTED,
                                 refuted_by="profile_convexified")
        self.assertEqual(edge.refuted_by, "profile_convexified")

    def test_name_without_refutation_is_a_false_trail(self) -> None:
        with self.assertRaises(GraphBuildError):
            ClashRelationEdge("1", "2", ClashRelation.CONTACT, Modality.POSSIBLE,
                              refuted_by="какое_то_правило")


class ScopeIsMandatory(unittest.TestCase):
    """Клеш без области есть слой рёбер под другим именем."""

    def test_empty_scope_id_is_refused(self) -> None:
        with self.assertRaises(GraphBuildError):
            ClashScope(scope_id="", node_ids=frozenset({"1"}))

    def test_scope_must_name_nodes_that_exist(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls")])
        with self.assertRaises(GraphBuildError):
            ClashQuery(graph, ClashScope("s", frozenset({"1", "НЕТ-ТАКОГО"})),
                       candidate_pairs=lambda: (),
                       classify=lambda a, b: None, census=_census(2))


class QueryNeverMaterialises(unittest.TestCase):
    """Отсутствие метода, возвращающего список, — это и есть запрет."""

    def test_there_is_no_method_returning_a_list_of_edges(self) -> None:
        public = {name for name in dir(ClashQuery) if not name.startswith("_")}
        self.assertEqual(public, {"tally", "graph", "scope", "census"},
                         "появился накопитель клеш-рёбер — 666 МБ уже "
                         "замерены, порог назван заранее")

    def test_iteration_is_the_only_way_and_it_streams(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls"),
                                        _element("2", "OST_Walls")])
        seen = []

        def pairs():
            seen.append("сетка построена")
            yield ("1", "2")

        query = ClashQuery(
            graph, ClashScope("s", frozenset({"1", "2"})),
            candidate_pairs=pairs,
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.OVERLAP, Modality.POSSIBLE),
            census=_census(2))
        self.assertEqual(seen, [], "пары посчитаны до обхода — это слой")
        edges = list(query)
        self.assertEqual(len(edges), 1)
        self.assertEqual(seen, ["сетка построена"])


class AssemblyComesFromTheGraphNotFromLabels(unittest.TestCase):
    """Ребро `hosted_in` превращает 14 % отчёта из догадки в свидетельство."""

    def test_declared_host_is_read_from_the_graph(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        self.assertEqual(assembly_relation_of(graph, "D1", "W1"), "hosted_in")
        self.assertEqual(assembly_relation_of(graph, "W1", "D1"), "hosted_in")

    def test_a_door_hosted_by_a_PANEL_is_still_found(self) -> None:
        """Замер `sob62_fas_r23_v17`: 9 из 14 дверей имеют хозяином
        `OST_CurtainWallPanels`. Пара ярлыков {door, wall} их не описывает."""
        graph = graph_from_l0(_HEADER, [
            _element("P1", "OST_CurtainWallPanels"),
            _element("D1", "OST_Doors", host_id="P1")])
        self.assertEqual(assembly_relation_of(graph, "D1", "P1"), "hosted_in")

    def test_panel_hosted_by_another_PANEL_is_found(self) -> None:
        """Замер `snowdon_plumb_v5`: 23 из 640 панелей имеют хозяином панель.
        Догадка по паре одинаковых ярлыков этого не выражает вовсе."""
        graph = graph_from_l0(_HEADER, [
            _element("P1", "OST_CurtainWallPanels"),
            _element("P2", "OST_CurtainWallPanels", host_id="P1")])
        self.assertEqual(assembly_relation_of(graph, "P2", "P1"), "hosted_in")

    def test_datum_host_is_reported_under_its_own_name(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("L1", "OST_Levels"),
            _element("G1", "OST_GenericModel", host_id="L1")])
        self.assertEqual(assembly_relation_of(graph, "G1", "L1"),
                         "placed_on_datum")

    def test_unrelated_pair_reports_None(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("A", "OST_Walls"),
                                        _element("B", "OST_Walls")])
        self.assertIsNone(assembly_relation_of(graph, "A", "B"))

    def test_host_OUTSIDE_extraction_is_NOT_reported_as_no_relation(self) -> None:
        """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ: `snowdon_elec_v1` — 959 из 1 001 (95.8 %)
        объявленных хозяев лежат в связанном файле. Ответить «отношения нет»
        значило бы выдать нашу слепоту за факт о здании."""
        graph = graph_from_l0(_HEADER, [
            _element("F1", "OST_ElectricalFixtures", host_id="СВЯЗЬ-42"),
            _element("W1", "OST_Walls")])
        self.assertEqual(assembly_relation_of(graph, "F1", "W1"),
                         "host_outside_extraction")


class AssemblyRefutesTheFindingAndSaysSo(unittest.TestCase):
    def test_finding_between_a_host_pair_is_refuted_by_name(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        query = ClashQuery(
            graph, ClashScope("s", frozenset({"W1", "D1"})),
            candidate_pairs=lambda: [("D1", "W1")],
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.OVERLAP, Modality.POSSIBLE),
            census=_census(2))
        edges = list(query)
        self.assertEqual(len(edges), 1, "находка стёрта вместо опровержения")
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertEqual(edges[0].refuted_by, "assembly_relation:hosted_in")
        self.assertEqual(edges[0].evidence["was_modality"], "possible")

    def test_tally_counts_without_storing(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        query = ClashQuery(
            graph, ClashScope("s", frozenset({"W1", "D1"})),
            candidate_pairs=lambda: [("D1", "W1")],
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.CONTACT, Modality.PROVEN),
            census=_census(2))
        tally = query.tally()
        self.assertEqual(tally["refuted_by:assembly_relation:hosted_in"], 1)


class ScopeCensusIsTheDenominator(unittest.TestCase):
    """Ответ «клешей нет» ничего не значит, пока не сказано, скольких узлов
    поиск КОСНУЛСЯ."""

    def test_unbalanced_scope_census_is_refused(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls")])
        with self.assertRaises(GraphBuildError):
            ClashQuery(graph, ClashScope("s", frozenset({"1"})),
                       candidate_pairs=lambda: (),
                       classify=lambda a, b: None,
                       census=ScopeCensus(nodes_in_scope=10, nodes_with_hull=1,
                                          refusals={}))

    def test_named_refusals_make_it_balance(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls")])
        query = ClashQuery(
            graph, ClashScope("s", frozenset({"1"})),
            candidate_pairs=lambda: (), classify=lambda a, b: None,
            census=ScopeCensus(nodes_in_scope=10, nodes_with_hull=1,
                               refusals={"zero_volume_hull": 4,
                                         "missing_geometry": 5}))
        self.assertEqual(query.census.refused, 9)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
