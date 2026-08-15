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

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
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
    ConstraintVerdict,
    ScopeCensus,
    VerifiedClashProof,
    assembly_relation_of,
    edge_from_finding,
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
                                 Modality.POSSIBLE)
        self.assertIs(edge.relation, ClashRelation.CONTACT)

    def test_contact_cannot_be_promoted_by_a_word_alone(self) -> None:
        with self.assertRaisesRegex(GraphBuildError, "verified proof"):
            ClashRelationEdge(
                "1", "2", ClashRelation.CONTACT, Modality.PROVEN,
                evidence={"verdict": "confirmed"})

    def test_PROVEN_OVERLAP_is_structurally_unconstructible(self) -> None:
        """A public modality word cannot replace the inner-proof capability."""
        with self.assertRaises(GraphBuildError):
            ClashRelationEdge("1", "2", ClashRelation.OVERLAP, Modality.PROVEN)

    def test_possible_overlap_is_the_honest_form(self) -> None:
        edge = ClashRelationEdge("1", "2", ClashRelation.OVERLAP,
                                 Modality.POSSIBLE,
                                 evidence={"hull_source": "bbox"})
        self.assertIs(edge.modality, Modality.POSSIBLE)


def _hull_record(element_id: str, hull: G.Hull, *,
                 inner: H.CertifiedInnerHull | None = None) -> H.HullRecord:
    return H.HullRecord(
        source_id=element_id,
        category="OST_DuctCurves",
        label="duct",
        mvp_side="mep",
        hull=hull,
        grade="conservative",
        hull_source="analytic_outer",
        inner=inner,
    )


def _certified_record(element_id: str, outer: G.Hull,
                      inner: G.Hull, body: G.Hull) -> H.HullRecord:
    evidence = H.certify_analytic_inner_for_test(
        inner=inner,
        body=body,
        outer=outer,
        subject_source_id=element_id,
        body_source_digest=H.analytic_hull_digest(body),
        body_source_revision=f"fixture:{element_id}:body-r1",
        revision=f"fixture:{element_id}:certificate-r1",
    )
    return _hull_record(element_id, outer, inner=evidence)


class DetectorFindingAdapter(unittest.TestCase):
    def test_outer_overlap_remains_possible(self) -> None:
        finding = D.evaluate(
            _hull_record("a", G.Aabb((0, 0, 0), (10, 10, 10))),
            _hull_record("b", G.Aabb((5, 0, 0), (15, 10, 10))),
        )
        self.assertIsNotNone(finding)
        edge = edge_from_finding(finding)
        self.assertIs(edge.relation, ClashRelation.OVERLAP)
        self.assertIs(edge.modality, Modality.POSSIBLE)
        self.assertIs(
            edge.constraint_verdict, ConstraintVerdict.POSSIBLE_VIOLATION)
        self.assertIsNone(edge.verified_proof)

    def test_certified_inner_overlap_mints_opaque_proven_edge(self) -> None:
        a = _certified_record(
            "a",
            G.Aabb((0, 0, 0), (10, 10, 10)),
            G.Aabb((2, 2, 2), (8, 8, 8)),
            G.Aabb((1, 1, 1), (9, 9, 9)),
        )
        b = _certified_record(
            "b",
            G.Aabb((5, 0, 0), (15, 10, 10)),
            G.Aabb((6, 2, 2), (12, 8, 8)),
            G.Aabb((5.5, 1, 1), (14, 9, 9)),
        )
        finding = D.evaluate(a, b)
        self.assertIsNotNone(finding)
        edge = edge_from_finding(finding)

        self.assertIs(edge.relation, ClashRelation.OVERLAP)
        self.assertIs(edge.modality, Modality.PROVEN)
        self.assertIs(
            edge.constraint_verdict, ConstraintVerdict.PROVEN_VIOLATION)
        self.assertIsNotNone(edge.verified_proof)
        self.assertEqual(len(edge.evidence["proof_digest"]), 64)

        with self.assertRaisesRegex(GraphBuildError, "verified proof"):
            ClashRelationEdge(
                edge.b, edge.a, edge.relation, Modality.PROVEN,
                verified_proof=edge.verified_proof)

    def test_clearance_finding_can_prove_separation_not_the_clearance(self) -> None:
        finding = D.evaluate(
            _hull_record("a", G.Aabb((0, 0, 0), (10, 10, 10))),
            _hull_record("b", G.Aabb((20, 0, 0), (30, 10, 10))),
            clearance_mm=20.0,
        )
        self.assertIsNotNone(finding)
        edge = edge_from_finding(finding)

        self.assertIs(edge.relation, ClashRelation.SEPARATED)
        self.assertIs(edge.modality, Modality.PROVEN)
        self.assertIs(
            edge.constraint_verdict, ConstraintVerdict.POSSIBLE_VIOLATION)
        self.assertGreater(edge.evidence["clearance_deficit_mm"], 0.0)
        self.assertEqual(edge.evidence["geometry_verdict"], "possible")

    def test_serialized_mapping_cannot_mint_a_proof(self) -> None:
        with self.assertRaisesRegex(GraphBuildError, "detector Finding"):
            edge_from_finding({  # type: ignore[arg-type]
                "verdict": "confirmed", "hull_relation": "overlap"})

    def test_verified_proof_is_not_publicly_constructible(self) -> None:
        with self.assertRaisesRegex(TypeError, "opaque"):
            VerifiedClashProof()


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

    def test_scope_node_keys_are_typed_and_immutable(self) -> None:
        with self.assertRaisesRegex(GraphBuildError, "immutable frozenset"):
            ClashScope("s", {"1"})  # type: ignore[arg-type]
        with self.assertRaisesRegex(GraphBuildError, "non-empty strings"):
            ClashScope("s", frozenset({"1", 2}))  # type: ignore[arg-type]

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

    def test_classifier_cannot_replay_another_pairs_evidence(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [_element("1", "OST_Walls"),
             _element("2", "OST_Walls"),
             _element("3", "OST_Walls")],
        )
        query = ClashQuery(
            graph,
            ClashScope("s", frozenset({"1", "2", "3"})),
            candidate_pairs=lambda: [("1", "2")],
            classify=lambda _a, _b: ClashRelationEdge(
                "1", "3", ClashRelation.OVERLAP, Modality.POSSIBLE),
            census=_census(3),
        )
        with self.assertRaisesRegex(GraphBuildError, "another candidate"):
            list(query)

    def test_self_pair_is_refused_before_classification(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls")])
        query = ClashQuery(
            graph,
            ClashScope("s", frozenset({"1"})),
            candidate_pairs=lambda: [("1", "1")],
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.OVERLAP, Modality.POSSIBLE),
            census=_census(1),
        )
        with self.assertRaisesRegex(GraphBuildError, "one node twice"):
            list(query)


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

    def test_external_host_is_not_pair_relation_with_unrelated_node(self) -> None:
        """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ: `snowdon_elec_v1` — 959 из 1 001 (95.8 %)
        объявленных хозяев лежат в связанном файле. Ответить «отношения нет»
        значило бы выдать нашу слепоту за факт о здании."""
        graph = graph_from_l0(_HEADER, [
            _element("F1", "OST_ElectricalFixtures", host_id="СВЯЗЬ-42"),
            _element("W1", "OST_Walls")])
        self.assertIsNone(assembly_relation_of(graph, "F1", "W1"))


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

    def test_external_host_never_refutes_unrelated_proven_overlap(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("F1", "OST_ElectricalFixtures", host_id="LINK-HOST"),
            _element("P1", "OST_PipeCurves"),
        ])
        first = _certified_record(
            "F1",
            G.Aabb((0, 0, 0), (10, 10, 10)),
            G.Aabb((2, 2, 2), (8, 8, 8)),
            G.Aabb((1, 1, 1), (9, 9, 9)),
        )
        second = _certified_record(
            "P1",
            G.Aabb((5, 0, 0), (15, 10, 10)),
            G.Aabb((6, 2, 2), (12, 8, 8)),
            G.Aabb((5.5, 1, 1), (14, 9, 9)),
        )
        finding = D.evaluate(first, second)
        self.assertIsNotNone(finding)
        classified = edge_from_finding(finding)
        self.assertIs(classified.modality, Modality.PROVEN)
        self.assertIs(
            classified.constraint_verdict,
            ConstraintVerdict.PROVEN_VIOLATION,
        )
        proof = classified.verified_proof

        query = ClashQuery(
            graph,
            ClashScope("external-host", frozenset({"F1", "P1"})),
            candidate_pairs=lambda: [("F1", "P1")],
            classify=lambda _a, _b: classified,
            census=_census(2),
        )
        edge = next(iter(query))

        self.assertIs(edge.modality, Modality.PROVEN)
        self.assertIs(edge.verified_proof, proof)
        self.assertIsNone(edge.refuted_by)
        self.assertIs(
            edge.constraint_verdict,
            ConstraintVerdict.PROVEN_VIOLATION,
        )
        self.assertEqual(
            edge.evidence["assembly_semantic_verdict"], "unresolved")
        uncertainty = edge.evidence["assembly_uncertainty"]
        self.assertEqual(len(uncertainty), 1)
        self.assertEqual(uncertainty[0]["source_node_id"], "F1")
        self.assertEqual(
            uncertainty[0]["declared_local_target"], "LINK-HOST")

    def test_tally_counts_without_storing(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _element("W1", "OST_Walls"),
            _element("D1", "OST_Doors", host_id="W1")])
        query = ClashQuery(
            graph, ClashScope("s", frozenset({"W1", "D1"})),
            candidate_pairs=lambda: [("D1", "W1")],
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.CONTACT, Modality.POSSIBLE),
            census=_census(2))
        tally = query.tally()
        self.assertEqual(tally["refuted_by:assembly_relation:hosted_in"], 1)
        self.assertEqual(tally["constraint:satisfied"], 1)


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
        rows = [_element(str(index), "OST_Walls") for index in range(10)]
        graph = graph_from_l0(_HEADER, rows)
        scope = ClashScope("s", frozenset(str(index) for index in range(10)))
        query = ClashQuery(
            graph, scope,
            candidate_pairs=lambda: (), classify=lambda a, b: None,
            census=ScopeCensus(nodes_in_scope=10, nodes_with_hull=1,
                               refusals={"zero_volume_hull": 4,
                                         "missing_geometry": 5}))
        self.assertEqual(query.census.refused, 9)

    def test_negative_bool_and_malformed_refusal_counts_fail_closed(self) -> None:
        invalid = (
            {"nodes_in_scope": -1, "nodes_with_hull": 0, "refusals": {}},
            {"nodes_in_scope": True, "nodes_with_hull": 1, "refusals": {}},
            {"nodes_in_scope": 1, "nodes_with_hull": False, "refusals": {}},
            {"nodes_in_scope": 1, "nodes_with_hull": 2,
             "refusals": {"fraud": -1}},
            {"nodes_in_scope": 1, "nodes_with_hull": 0,
             "refusals": {"fraud": True}},
            {"nodes_in_scope": 1, "nodes_with_hull": 0,
             "refusals": {"": 1}},
            {"nodes_in_scope": 1, "nodes_with_hull": 0,
             "refusals": {7: 1}},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(GraphBuildError):
                    ScopeCensus(**payload)  # type: ignore[arg-type]

    def test_census_denominator_must_equal_exact_scope_keys(self) -> None:
        graph = graph_from_l0(_HEADER, [_element("1", "OST_Walls")])
        with self.assertRaisesRegex(GraphBuildError, "exact declared"):
            ClashQuery(
                graph,
                ClashScope("s", frozenset({"1"})),
                candidate_pairs=lambda: (),
                classify=lambda _a, _b: None,
                census=ScopeCensus(
                    nodes_in_scope=2,
                    nodes_with_hull=1,
                    refusals={"missing_geometry": 1},
                ),
            )

    def test_candidate_pair_cannot_escape_exact_scope_keys(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [_element("1", "OST_Walls"), _element("2", "OST_Walls")],
        )
        query = ClashQuery(
            graph,
            ClashScope("one", frozenset({"1"})),
            candidate_pairs=lambda: [("1", "2")],
            classify=lambda a, b: ClashRelationEdge(
                a, b, ClashRelation.OVERLAP, Modality.POSSIBLE),
            census=_census(1),
        )
        with self.assertRaisesRegex(GraphBuildError, "escapes"):
            list(query)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
