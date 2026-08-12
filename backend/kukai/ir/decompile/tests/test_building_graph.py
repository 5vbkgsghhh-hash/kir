"""ОПРОВЕРГАЮЩИЕ ТЕСТЫ типизированного графа здания v1.

Дисциплина §18.7: сначала тест, воспроизводящий отказ ДОСЛОВНО, потом правка.
Каждый класс ниже воспроизводит ЗАМЕРЕННЫЙ случай, а не воображаемый.

Замеры, на которые опираются фикстуры (10.08.2026, прибор — сырой разбор
`L0.jsonl` корпуса `backend/backend/data/decompile`, машинно-локальный):

* биекция `source_element_id` ↔ `element_id` — 52 дерева из 52, 540 461 лист,
  1 139 477 элементов, 0 повторов адреса;
* `host_id` висячих 1 263 из 213 811 (0.59 %), СОСРЕДОТОЧЕНЫ:
  `snowdon_elec_v1` 959/1 001 (95.8 %), Snowdon Plumbing 54/54 и 50/50 (100 %);
* `host_source` — 0 строк из 1 139 477;
* хозяин-ОТМЕТКА: `snowdon_plumb_v5` — 21 `OST_GenericModel` и
  4 `OST_PlumbingFixtures` имеют хозяином `OST_Levels`.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
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
    """Хребет — САМ НАБОР ЭЛЕМЕНТОВ L0, а не новый идентификатор."""

    def test_node_id_is_the_l0_element_id(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("102", "OST_Doors")])
        self.assertEqual(sorted(graph.nodes), ["101", "102"])
        self.assertEqual(graph.node("101").category, "OST_Walls")

    def test_rooms_and_levels_share_the_address_space(self) -> None:
        """Замерено: комнаты 7 841/7 841, уровни 170/170 — ЭЛЕМЕНТЫ того же
        пространства. Узел «комната» не заводит своей нумерации."""
        graph = graph_from_l0(
            _header(rooms=[{"id": "R1", "bounding_element_ids": ["W1"]}],
                    levels=[{"id": "L1", "elevation_mm": 0.0}]),
            [_element("R1", "OST_Rooms"), _element("L1", "OST_Levels"),
             _element("W1", "OST_Walls", level_id="L1")])
        self.assertIn("R1", graph)
        self.assertIn("L1", graph)
        self.assertEqual(graph.node("R1").category, "OST_Rooms")


class CensusLawHolds(unittest.TestCase):
    """`узлов = оценённых + названных отказов`. Молчаливых выпадений нет."""

    def test_row_without_address_is_a_NAMED_refusal(self) -> None:
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("", "OST_Walls")])
        self.assertEqual(graph.census.rows_seen, 2)
        self.assertEqual(graph.census.nodes, 1)
        self.assertEqual(graph.census.refusals,
                         {NodeRefusal.NO_ADDRESS.value: 1})
        graph.census.assert_balanced()

    def test_duplicate_address_is_named_not_swallowed(self) -> None:
        """По корпусу повторов НЕ НАБЛЮДАЛОСЬ (0 на 1 139 477), но закон
        держится проверкой, а не удачей корпуса."""
        graph = graph_from_l0(_header(), [
            _element("101", "OST_Walls"), _element("101", "OST_Doors")])
        self.assertEqual(graph.census.nodes, 1)
        self.assertEqual(graph.census.refusals,
                         {NodeRefusal.DUPLICATE_ADDRESS.value: 1})

    def test_unbalanced_census_is_unconstructible(self) -> None:
        from kukai.ir.decompile.building_graph import BuildingGraph, GraphCensus
        with self.assertRaises(GraphBuildError):
            BuildingGraph(
                doc_name="x",
                nodes=[GraphNode("1", "OST_Walls", Authority.DECLARED,
                                 AuthoritySource.L0_ELEMENT,
                                 Existence.MATERIALIZED)],
                edges=[],
                census=GraphCensus(rows_seen=5, nodes=1, refusals={}))


class AuthorityLine(unittest.TestCase):
    """ЛИНИЯ АВТОРИТЕТА — свойство узла, а не память автора."""

    def test_default_is_declared_and_names_its_witness(self) -> None:
        graph = graph_from_l0(_header(), [_element("1", "OST_PipeFitting")])
        node = graph.node("1")
        self.assertIs(node.authority, Authority.DECLARED)
        self.assertIs(node.authority_source, AuthoritySource.L0_ELEMENT)

    def test_category_alone_NEVER_makes_a_node_derived(self) -> None:
        """ЦЕНА ОШИБКИ ЗАМЕРЕНА: перевод MEP-фитингов в порождаемые убрал бы
        14 713 из 31 998 опов (46.0 %) на `snowdon_plumb_v4`, а `honest_pct`
        сдвинулся бы 99.42 % → 98.93 % — 0.49 п.п. за половину здания.
        Категорийный приор не знает, кто элемент создаёт."""
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
    """Непостроенное здание выразимо с первого дня — вьюер этого требует."""

    def test_l0_row_is_materialized(self) -> None:
        graph = graph_from_l0(_header(), [_element("1", "OST_Walls")])
        self.assertIs(graph.node("1").existence, Existence.MATERIALIZED)

    def test_both_axes_are_orthogonal(self) -> None:
        """Все четыре сочетания осмысленны; самое интересное —
        planned+derived_by_revit: программа сказала «соедини трубы», фитинги
        ПОЯВЯТСЯ, но их ещё нет и объявлять их геометрию нельзя."""
        node = GraphNode("1", "OST_PipeFitting", Authority.DERIVED_BY_REVIT,
                         AuthoritySource.OP_DERIVED_CONTRACT, Existence.PLANNED)
        self.assertIs(node.existence, Existence.PLANNED)
        self.assertIs(node.authority, Authority.DERIVED_BY_REVIT)


class RefutationIsAnEdge(unittest.TestCase):
    """Опровергнутое ребро ОСТАЁТСЯ в графе с именем правила."""

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
    """ОТСУТСТВУЮЩИЙ ХОЗЯИН И ХОЗЯИН ВНЕ ИЗВЛЕЧЕНИЯ — РАЗНЫЕ ФАКТЫ.

    ОПРОВЕРГАЮЩИЙ СЛУЧАЙ, замерен дословно: `snowdon_elec_v1` — 959 из 1 001
    объявленных хозяев (95.8 %) не являются элементами этого снимка, потому что
    лежат в СВЯЗАННОМ файле. Четыре снимка Snowdon Plumbing — 100 %.
    Граф, стирающий такое ребро, делает «мы не читали связь» неотличимым от
    «связи нет» — и ровно поэтому межраздельная область у клешей пуста.
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
        self.assertEqual(edges[0].evidence["why"], "host_outside_extraction")
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
    """Хозяин-ОТМЕТКА едет отдельным отношением.

    Замер: `snowdon_plumb_v5` — 21 `OST_GenericModel` и 4 `OST_PlumbingFixtures`
    имеют хозяином `OST_Levels`. Сваливать «сидит В стене» и «поставлен НА
    отметку» в одно слово — та же склейка, ради разбора которой писался модуль.
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
    """`host_source` — 0 строк из 1 139 477 во всём корпусе.

    Поле волны захвата 09.08 пишется эмиттером и не встречается НИ В ОДНОМ
    хранимом снимке. Трактовать None как `family_instance` запрещено: пустое
    поле и неизмеренное поле — разные факты.
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
    def test_flag_is_off_by_default(self) -> None:
        import os
        old = os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
        try:
            self.assertFalse(building_graph_enabled())
        finally:
            if old is not None:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = old


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
