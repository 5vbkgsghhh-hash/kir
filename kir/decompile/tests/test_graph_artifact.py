"""THE GRAPH ARTIFACT: the round trip must be EXACT, and a corrupted
file must FAIL.

The guard pins down three distinct claims, and they do not reduce to
one another:

1. `to_dict` -> `graph_from_dict` returns THE SAME OBJECTS. Not
   "similar," not "matching in count": nodes and edges are compared in
   full, together with `evidence`, `refuted_by`, `section`, and both
   identities. Comparing counts here would be exactly the mistake the
   canon rebukes as form 12 — "the count matched, the names diverged";
2. FAIL CONTROL: the round trip IS ABLE to fail. Losing one field must
   make it fail, otherwise a green result on point 1 means nothing;
3. a corrupted, foreign, or non-converging artifact gives a FAILURE,
   not `None` and not a lying graph. "We did not build it" and "we
   read a lie" must arrive as different values.

THE CARDINALITY AT WHICH THE CONTROL IS ABLE TO FAIL is stated: the
synthetic graph carries AT LEAST THREE nodes and edges of THREE
DIFFERENT modalities. On one node and one edge, the round trip is
green by construction — there is nothing to lose there, and a
degenerate input would confirm only itself.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from kir.decompile.building_graph import (
    GRAPH_ARTIFACT_SCHEMA,
    Authority,
    AuthoritySource,
    BuildingGraph,
    Existence,
    GraphBuildError,
    GraphCensus,
    GraphEdge,
    GraphNode,
    Modality,
    OutsideExtraction,
    Relation,
    graph_from_dict,
)
from kir.decompile import graph_store as gs

#: The corpus is machine-local. Its absence is a NAMED skip with a
#: path, not a silent green: a guard without its own instrument must
#: be distinguishable from a guard with no findings.
_CORPUS = Path(
    os.getenv("KUKAI_DECOMPILE_DATA")
    or Path(__file__).resolve().parents[4] / "backend" / "data" / "decompile")


def _corpus_runs(limit: int = 3) -> list[Path]:
    if not _CORPUS.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(_CORPUS.iterdir()):
        if not entry.is_dir():
            continue
        if gs.l0_path(entry).exists() or gs.l0_path(entry).with_suffix(
                ".jsonl.gz").exists():
            found.append(entry)
        if len(found) >= limit:
            break
    return found


def _synthetic_graph() -> BuildingGraph:
    """A graph that touches EVERY field the round trip must carry through.

    Three nodes are the minimum at which a positional loss is
    noticeable; three edge modalities are the minimum at which
    `refuted_by` and `evidence` are checked in both directions
    (required exactly under REFUTED, forbidden otherwise).
    """
    nodes = [
        GraphNode(
            node_id="1001",
            category="OST_Walls",
            authority=Authority.DECLARED,
            authority_source=AuthoritySource.L0_ELEMENT,
            existence=Existence.MATERIALIZED,
            level_id="7",
            type_id="55",
            type_name="199_Железобетон 250",
        ),
        GraphNode(
            node_id="1002",
            category="OST_Doors",
            authority=Authority.DECLARED,
            authority_source=AuthoritySource.L0_ELEMENT,
            existence=Existence.MATERIALIZED,
            level_id="7",
        ),
        GraphNode(
            node_id="1003",
            category="OST_PipeCurves",
            authority=Authority.DERIVED_BY_REVIT,
            authority_source=AuthoritySource.LIFTER_GENERATOR_CHILD,
            existence=Existence.MATERIALIZED,
            # SECTION is a nested quantity: if the round trip loses it,
            # the node count will not budge, and catching this is only
            # possible by comparing objects.
            section={"RBS_PIPE_OUTER_DIAMETER": 60.325,
                     "RBS_PIPE_DIAMETER_PARAM": 50.8},
        ),
    ]
    edges = [
        GraphEdge(relation=Relation.HOSTED_IN, src="1002", dst="1001",
                  modality=Modality.PROVEN,
                  evidence={"source": "L0Element.host_id"}),
        GraphEdge(relation=Relation.ON_LEVEL, src="1001", dst="7",
                  modality=Modality.POSSIBLE),
        GraphEdge(relation=Relation.BOUNDED_BY_SAME_WALL, src="1001",
                  dst="1002", modality=Modality.REFUTED,
                  refuted_by="host_does_not_separate_exactly_two_rooms"),
        GraphEdge(relation=Relation.HOSTED_IN, src="1003", dst="99999",
                  modality=Modality.UNRESOLVED_TARGET,
                  evidence={
                      "why": OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value}),
    ]
    # Level `7` must be a node: an ordinary edge requires two local endpoints.
    nodes.append(GraphNode(
        node_id="7", category="OST_Levels", authority=Authority.DECLARED,
        authority_source=AuthoritySource.L0_ELEMENT,
        existence=Existence.MATERIALIZED))
    return BuildingGraph(
        doc_name="СИНТЕТИКА",
        nodes=nodes,
        edges=edges,
        census=GraphCensus(rows_seen=6, nodes=4,
                           refusals={"no_address": 2}),
    )


class TheRoundTripIsExact(unittest.TestCase):
    """The round trip compares OBJECTS. A matching count is not a match."""

    def test_synthetic_graph_survives_the_round_trip_whole(self):
        graph = _synthetic_graph()
        back = graph_from_dict(json.loads(json.dumps(graph.to_dict())))
        self.assertEqual(dict(graph.nodes), dict(back.nodes))
        self.assertEqual(list(graph.edges), list(back.edges))
        self.assertEqual(graph.doc_name, back.doc_name)
        self.assertEqual(graph.to_dict()["census"], back.to_dict()["census"])

    def test_a_dropped_field_reddens_the_round_trip(self):
        """A FAIL CONTROL, and it is SURGICAL: it drops ONE field, not
        the whole decompile.

        A broad control ("break serialization altogether") would turn
        red the same way for a real loss and for a broken probe — the
        canon calls such conviction a mark of a BLUNT instrument, not
        a strong one.
        """
        graph = _synthetic_graph()
        payload = json.loads(json.dumps(graph.to_dict()))
        dropped = 0
        for row in payload["edges"]:
            if "evidence" in row:
                del row["evidence"]
                dropped += 1
        self.assertGreaterEqual(
            dropped, 1, "проба не нашла, что портить — она ничего не доказала")
        # `evidence.why` is mandatory for UNRESOLVED_TARGET, so its
        # loss is caught by a construction FAILURE, not a silent
        # discrepancy — exactly what we want from a load-bearing field.
        with self.assertRaises(GraphBuildError):
            graph_from_dict(payload)

    def test_a_dropped_section_reddens_without_refusing(self):
        """The other half of the control: a field whose loss is NOT caught by the schema.

        `section` is optional, so its disappearance does not make
        construction fail — it is visible ONLY by comparing objects.
        If the round trip were checked by node count, this loss would
        pass silently.
        """
        graph = _synthetic_graph()
        payload = json.loads(json.dumps(graph.to_dict()))
        dropped = 0
        for row in payload["nodes"]:
            if "section" in row:
                del row["section"]
                dropped += 1
        self.assertEqual(dropped, 1, "в графе ровно один узел с сечением")
        back = graph_from_dict(payload)
        self.assertEqual(len(graph.nodes), len(back.nodes),
                         "счёт узлов НЕ дрогнул — в этом и весь смысл случая")
        self.assertNotEqual(dict(graph.nodes), dict(back.nodes))


class ACorruptArtifactRefusesRatherThanLies(unittest.TestCase):

    def test_a_foreign_schema_version_refuses(self):
        payload = _synthetic_graph().to_dict()
        payload["schema"] = "building-graph/99"
        with self.assertRaises(GraphBuildError) as ctx:
            graph_from_dict(payload)
        self.assertIn("building-graph/99", str(ctx.exception))

    def test_an_unbalanced_census_refuses(self):
        """The census is a CONDITION of reading, not a report alongside it.

        🔴 TWO CASES, NOT ONE, AND THIS WAS PAID FOR BY A CONTROL. The
        first edition perturbed `nodes` and required the word "census"
        in the failure. A mutation that removed the BODY of the
        balance law did NOT make the guard fail: perturbing `nodes`
        also breaks identity arithmetic, whose failure carries the
        same word, and the guard turned green on a NEIGHBORING law.
        The probe reported on a law it never touched.

        Now each case perturbs a quantity read by EXACTLY ONE law, and
        is checked against that law's own text.
        """
        # (a) the balance law: rows != nodes + named failures.
        # `rows_seen` does not enter any identity check.
        payload = json.loads(json.dumps(_synthetic_graph().to_dict()))
        payload["census"]["rows_seen"] = payload["census"]["rows_seen"] + 1
        with self.assertRaises(GraphBuildError) as ctx:
            graph_from_dict(payload)
        self.assertIn("перепись графа не сходится", str(ctx.exception))
        self.assertIn("молчаливое выпадение", str(ctx.exception))

        # (b) identity arithmetic is a separate law with its own separate text.
        payload = json.loads(json.dumps(_synthetic_graph().to_dict()))
        payload["census"]["identity_authoritative_nodes"] = 1
        with self.assertRaises(GraphBuildError) as ctx:
            graph_from_dict(payload)
        self.assertNotIn("перепись графа не сходится", str(ctx.exception))

    def test_an_unknown_relation_refuses_by_name(self):
        payload = json.loads(json.dumps(_synthetic_graph().to_dict()))
        payload["edges"][0]["relation"] = "overlap"
        with self.assertRaises(GraphBuildError) as ctx:
            graph_from_dict(payload)
        self.assertIn("Relation", str(ctx.exception))

    def test_a_refuted_edge_without_its_rule_refuses(self):
        payload = json.loads(json.dumps(_synthetic_graph().to_dict()))
        for row in payload["edges"]:
            row.pop("refuted_by", None)
        with self.assertRaises(GraphBuildError):
            graph_from_dict(payload)


class ClashEdgesAreUnstorableByConstruction(unittest.TestCase):
    """The prohibition is held by the type system, not by convention.

    This is checked NOT by a comment and not by grepping for the word
    "clash": the clash relation names are taken from
    `graph_clash_query.ClashRelation` — the authority — and it is
    demonstrated that not one of them is expressible in `Relation`,
    i.e. in the artifact.
    """

    def test_no_clash_relation_is_expressible_in_the_stored_vocabulary(self):
        from kir.decompile.graph_clash_query import ClashRelation

        stored = {item.value for item in Relation}
        clash = {item.value for item in ClashRelation}
        self.assertTrue(clash, "авторитет пуст — проба не проверила ничего")
        self.assertEqual(
            set(), stored & clash,
            "клеш-отношение стало выразимо в хранимом словаре — "
            "порог 9.15 ребра на узел вернётся вместе с ним")


class AnAbsentSourceIsNotAZero(unittest.TestCase):
    """"Zero join edges" and "the join index was never supplied" are DIFFERENT facts.

    This was paid for by measurement F3 on the tower: `k2_ar_rd_v15`
    has no `join.index.json`, yet has 15,341 walls. The graph answered
    "0 joins," and the artifact would have frozen that zero to disk as
    a property of the building.
    """

    _HEADER = {"doc_name": "Т"}
    _ROWS = [{"element_id": "1", "category": "OST_Walls"},
             {"element_id": "2", "category": "OST_Walls"},
             {"element_id": "3", "category": "OST_Walls"}]

    def _graph(self, **kwargs):
        from kir.decompile.building_graph import graph_from_l0
        return graph_from_l0(self._HEADER, list(self._ROWS), **kwargs)

    def test_a_missing_source_refuses_instead_of_answering_zero(self):
        graph = self._graph()
        self.assertIn("joins", graph.census.sources_absent)
        with self.assertRaises(GraphBuildError) as ctx:
            graph.relation_count(Relation.JOINED_TO)
        self.assertIn("НЕ ИЗМЕРЕН", str(ctx.exception))
        self.assertIn("joins", str(ctx.exception))

    def test_a_supplied_source_answers_zero_as_a_fact_about_the_building(self):
        """The other side: supplied and empty is an HONEST zero, not a failure."""
        graph = self._graph(joins={"1": {"joined_to": []}})
        self.assertNotIn("joins", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.JOINED_TO))

    def test_an_empty_generator_is_a_SUPPLIED_source(self):
        """An empty generator is a SUPPLIED source: a true zero, not a failure.

        🔴 RETARGETED, NOT REMOVED (F-056). The previous edition's
        argument — "the generator is truthy even when empty, checking
        the raw argument would lie" — REMAINS VALID and is even
        strengthened: the check now goes by the identity of the
        sentinel `_NOT_GIVEN`, the iterator is not touched at all,
        whereas the previous `frozenset(...)` exhausted it BEFORE the
        check. What changed is not the argument, but the expected
        outcome: an explicitly supplied empty value is the MIDDLE
        outcome of the three-outcome `relation_count` law, not the third.
        """
        graph = self._graph(link_ids=(item for item in []))
        self.assertNotIn("link_ids", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.HOSTED_IN_LINK))

    def test_an_omitted_source_is_still_absent(self):
        """NEGATIVE CONTROL, without which the guard is green by construction.

        An edit that removed `sources_absent` entirely would pass the check above.
        """
        graph = self._graph()
        self.assertIn("link_ids", graph.census.sources_absent)
        with self.assertRaises(GraphBuildError):
            graph.relation_count(Relation.HOSTED_IN_LINK)

    def test_the_absence_survives_the_artifact(self):
        graph = self._graph()
        back = graph_from_dict(json.loads(json.dumps(graph.to_dict())))
        self.assertEqual(graph.census.sources_absent,
                         back.census.sources_absent)
        with self.assertRaises(GraphBuildError):
            back.relation_count(Relation.JOINED_AT_END)

    def test_the_table_covers_every_input_that_can_silence_a_relation(self):
        """THE TABLE IS COMPLETE BY CONSTRUCTION — and this is checked, not promised.

        The authority here is the SIGNATURE of `graph_from_l0` ITSELF: the list
        of its optional inputs is taken by reflection. The test cannot prove
        which input suppresses which kind (that would require reading the
        builders' bodies), so it proves something weaker and checkable: EVERY
        name in `OPTIONAL_SOURCES` exists as an argument. The reverse
        direction — that no unnamed input suppresses a kind — rests on the
        analysis in the table's comment and is NOT automated; this is written
        down explicitly, instead of a silent
        "complete by construction".
        """
        import inspect
        from kir.decompile.building_graph import (
            OPTIONAL_SOURCES, graph_from_l0)

        params = set(inspect.signature(graph_from_l0).parameters)
        self.assertTrue(OPTIONAL_SOURCES, "таблица пуста — проба ничего не даёт")
        for name in OPTIONAL_SOURCES:
            self.assertIn(
                name, params,
                f"{name!r} назван источником, а такого аргумента у "
                f"graph_from_l0 нет — таблица разошлась с сигнатурой")

    def test_an_unknown_source_name_refuses(self):
        from kir.decompile.building_graph import GraphCensus
        with self.assertRaises(GraphBuildError):
            GraphCensus(rows_seen=1, nodes=1, refusals={},
                        sources_absent=("выдуманный_вход",))


class TheStoreOnDisk(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="graph-artifact."))
        self.run = self.tmp / "run"
        self.run.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_absent_artifact_is_none_and_nothing_else(self):
        self.assertIsNone(gs.load_graph(self.run))

    def test_write_then_load_is_exact(self):
        graph = _synthetic_graph()
        path = gs.write_graph(self.run, graph)
        self.assertTrue(path.is_file())
        back = gs.load_graph(self.run)
        self.assertIsNotNone(back)
        self.assertEqual(dict(graph.nodes), dict(back.nodes))
        self.assertEqual(list(graph.edges), list(back.edges))

    def test_a_gzipped_artifact_reads_through_the_same_call(self):
        """The cleaner gzips what has cooled off. A direct `open()` would give "no data"."""
        graph = _synthetic_graph()
        path = gs.write_graph(self.run, graph)
        with gzip.open(str(path) + ".gz", "wb") as out:
            out.write(path.read_bytes())
        path.unlink()
        back = gs.load_graph(self.run)
        self.assertIsNotNone(back)
        self.assertEqual(dict(graph.nodes), dict(back.nodes))

    def test_a_corrupt_artifact_refuses_and_never_reads_as_absent(self):
        gs.graph_path(self.run).write_text("{]", encoding="utf-8")
        with self.assertRaises(ValueError):
            gs.load_graph(self.run)

    def test_a_missing_l0_refuses_with_the_path(self):
        with self.assertRaises(GraphBuildError) as ctx:
            gs.build_graph_for_run(self.run)
        self.assertIn("L0.jsonl", str(ctx.exception))


class OnRealBuildings(unittest.TestCase):
    """The input is built by PROD CODE from a real decompile, not a handwritten fixture.

    A handwritten input is dangerous not for its inaccuracy — it answers NO, and a
    negative answer closes the question. Here the loop is checked on buildings from disk.
    """

    def test_round_trip_is_exact_on_stored_decompiles(self):
        runs = _corpus_runs()
        if not runs:
            self.skipTest(
                f"корпус разборов недоступен: {_CORPUS} — это НЕ «дефектов "
                f"нет», а отсутствие прибора; задать KUKAI_DECOMPILE_DATA")
        for run in runs:
            with self.subTest(run=run.name):
                graph = gs.build_graph_for_run(run)
                back = graph_from_dict(
                    json.loads(json.dumps(graph.to_dict())))
                self.assertEqual(dict(graph.nodes), dict(back.nodes))
                self.assertEqual(list(graph.edges), list(back.edges))
                # The census law holds for what was read too, not only for
                # what was built.
                self.assertEqual(
                    back.census.nodes + back.census.refused,
                    back.census.rows_seen)

    def test_stored_edges_stay_proportional_to_nodes(self):
        """THE NUMBER THAT MAKES STORAGE LEGITIMATE AT ALL.

        A stable edge describes an ASSEMBLY and grows linearly; a clash edge
        describes a PAIR and grows quadratically — the demo-v3 measurement gave
        9.15 edges per node, a 666 MB report, a 2.66 GB peak. The threshold here
        stands with a MARGIN (3.0 against the measured 0.80…1.71), because what
        it guards is not the measurement's precision but a CHANGE OF KIND: if a
        pairwise relation ever slips into the artifact, the ratio will jump past
        the threshold long before reaching 9.15.
        """
        runs = _corpus_runs()
        if not runs:
            self.skipTest(f"корпус разборов недоступен: {_CORPUS}")
        for run in runs:
            with self.subTest(run=run.name):
                graph = gs.build_graph_for_run(run)
                if len(graph) < 100:
                    continue
                ratio = len(graph.edges) / len(graph)
                self.assertLess(
                    ratio, 3.0,
                    f"{run.name}: {ratio:.2f} ребра на узел — попарное "
                    f"отношение в артефакте, а хранить их нельзя")


class ОтсутствующийИндексСоединенийНеСтановитсяНулём(unittest.TestCase):
    """🔴 A GUARD OF THE END-TO-END LINK, not a new capability (2026-08-29).

    "There are no joins in the building" and "joins were not asked about" ARE
    ALREADY DISTINGUISHED today, and the distinction rides through to the
    stage's receipt. No core edit is needed for this — a guard is: the link
    runs through FOUR modules and breaks silently.

        no index on disk
          -> build_graph_for_run passes joins=None
          -> graph_from_l0 puts 'joins' into census.sources_absent
          -> unmeasured_relations() names joined_to and joined_at_end
          -> pipeline prints sources_absent in the receipt

    Break any one link — and the graph will say "there are no joins" about the
    BUILDING where it is actually a fact about the MACHINE, and there will be
    no way to tell them apart.
    """

    def _run_dir(self, tmp):
        import json as _json
        d = Path(tmp)
        (d / "L0.jsonl").write_text(
            _json.dumps({"record": "header",
                         "document": {"doc_name": "проба",
                                      "revit_version": "2026"}},
                        ensure_ascii=False) + "\n"
            + _json.dumps({"record": "element",
                           "element": {"id": "1", "category": "Walls",
                                       "type_name": "Т", "params": {}}},
                          ensure_ascii=False) + "\n",
            encoding="utf-8")
        return d

    def test_absent_join_index_is_named_not_counted_as_zero(self) -> None:
        from kir.decompile import graph_store as gs
        with tempfile.TemporaryDirectory() as tmp:
            d = self._run_dir(tmp)
            self.assertFalse((d / "join.index.json").exists())
            graph = gs.build_graph_for_run(d)
            self.assertIn("joins", graph.census.sources_absent,
                          "индекс соединений не читался — это обязано быть "
                          "названо, а не пройти нулём рёбер")
            named = {r.value for r in graph.census.unmeasured_relations()}
            self.assertIn("joined_to", named)
            self.assertIn("joined_at_end", named)

    def test_the_clash_query_feeds_the_same_absence(self) -> None:
        """Without the artifact, the clash adapter calls the canonical graph builder."""
        from kir.decompile import graph_clash_query as Q
        with tempfile.TemporaryDirectory() as tmp:
            d = self._run_dir(tmp)
            graph = Q.graph_for_clash_query(d)
            self.assertIn("joins", graph.census.sources_absent,
                          "canonical fallback must retain named absence")

    def test_the_clash_query_prefers_the_exact_stored_graph(self) -> None:
        """The full canonical artifact cannot be rebuilt from a trimmed L0."""
        from unittest import mock
        from kir.decompile import graph_clash_query as Q
        from kir.decompile import graph_store as gs

        with tempfile.TemporaryDirectory() as tmp:
            d = self._run_dir(tmp)
            expected = gs.build_graph_for_run(d, joins={"1": []})
            gs.write_graph(d, expected)
            with mock.patch.object(
                    gs, "build_graph_for_run",
                    side_effect=AssertionError("stored graph was ignored")):
                actual = Q.graph_for_clash_query(d)
            self.assertEqual(expected.to_dict(), actual.to_dict())

    def test_a_present_join_index_is_not_reported_absent(self) -> None:
        """Positive control: a source that was supplied does not end up among
        the absent ones, otherwise the guard is green by construction."""
        from kir.decompile.building_graph import graph_from_l0
        header = {"doc_name": "проба", "revit_version": "2026"}
        element = {"record": "element",
                   "element": {"id": "1", "category": "Walls",
                               "type_name": "Т", "params": {}}}
        graph = graph_from_l0(header, iter([element]), joins={"1": []})
        self.assertNotIn("joins", graph.census.sources_absent)
        named = {r.value for r in graph.census.unmeasured_relations()}
        self.assertNotIn("joined_to", named)


if __name__ == "__main__":
    unittest.main()
