"""Streaming clash-query laws: no pair, verdict, or denominator disappears."""
from __future__ import annotations

import pytest

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
)


HEADER = {"doc_name": "query-red-team", "levels": [], "rooms": [], "grids": []}


def _row(node_id: str):
    return {
        "element_id": node_id,
        "category": "OST_Walls",
        "type_id": "t",
        "type_name": "T",
        "level_id": None,
        "host_id": None,
        "params": {},
    }


def _graph(*node_ids: str):
    return graph_from_l0(HEADER, tuple(_row(item) for item in node_ids))


def _edge(a: str, b: str):
    return ClashRelationEdge(
        a, b, ClashRelation.OVERLAP, Modality.POSSIBLE)


def _query(pairs, classify=_edge):
    graph = _graph("a", "b", "c")
    return ClashQuery(
        graph,
        ClashScope("exact", frozenset({"a", "b", "c"})),
        candidate_pairs=lambda: pairs,
        classify=classify,
        census=ScopeCensus(3, 3, {}),
    )


def test_empty_scope_is_a_vacuous_verdict_and_is_rejected() -> None:
    with pytest.raises(GraphBuildError, match="empty ClashScope"):
        ClashScope("empty", frozenset())


def test_candidate_cannot_disappear_as_classifier_none() -> None:
    with pytest.raises(GraphBuildError, match="silently dropped"):
        list(_query((("a", "b"),), classify=lambda _a, _b: None))


def test_classifier_cannot_swap_a_and_b() -> None:
    with pytest.raises(GraphBuildError, match="swapped"):
        list(_query(
            (("a", "b"),),
            classify=lambda _a, _b: _edge("b", "a"),
        ))


def test_candidate_stream_rejects_a_b_swap_before_classification() -> None:
    called = False

    def classify(a, b):
        nonlocal called
        called = True
        return _edge(a, b)

    with pytest.raises(GraphBuildError, match="canonical subject order"):
        list(_query((("b", "a"),), classify=classify))
    assert called is False


@pytest.mark.parametrize(
    "pairs",
    [
        (("a", "b"), ("a", "b")),
        (("b", "c"), ("a", "c")),
    ],
)
def test_candidate_stream_is_strictly_ordered_and_duplicate_free(pairs) -> None:
    with pytest.raises(GraphBuildError, match="strictly ordered"):
        list(_query(pairs))


@pytest.mark.parametrize("candidate", [("a",), ("a", "b", "c"), "ab", 7])
def test_candidate_row_has_exactly_two_typed_keys(candidate) -> None:
    with pytest.raises(GraphBuildError, match="exact two-key"):
        list(_query((candidate,)))


def test_edge_evidence_is_deeply_snapshotted() -> None:
    source = {"side": {"samples": [1.0, 2.0]}}
    edge = ClashRelationEdge(
        "a", "b", ClashRelation.OVERLAP, Modality.POSSIBLE,
        evidence=source,
    )
    source["side"]["samples"].append(99.0)
    assert edge.evidence["side"]["samples"] == (1.0, 2.0)
    with pytest.raises(TypeError):
        edge.evidence["side"]["forged"] = True


def test_reserved_assembly_evidence_cannot_be_forged() -> None:
    graph = graph_from_l0(
        HEADER,
        (
            _row("a"),
            {**_row("b"), "host_id": "a"},
        ),
    )
    query = ClashQuery(
        graph,
        ClashScope("assembly", frozenset({"a", "b"})),
        candidate_pairs=lambda: (("a", "b"),),
        classify=lambda a, b: ClashRelationEdge(
            a, b, ClashRelation.OVERLAP, Modality.POSSIBLE,
            evidence={"assembly_from": "forged"}),
        census=ScopeCensus(2, 2, {}),
    )
    with pytest.raises(GraphBuildError, match="reserved assembly"):
        list(query)


def test_zero_candidate_tally_still_carries_the_exact_denominator() -> None:
    graph = _graph("a", "b", "c")
    query = ClashQuery(
        graph,
        ClashScope("partial-geometry", frozenset({"a", "b", "c"})),
        candidate_pairs=lambda: (),
        classify=lambda _a, _b: None,
        census=ScopeCensus(
            nodes_in_scope=3,
            nodes_with_hull=2,
            refusals={"missing_geometry": 1},
        ),
    )
    tally = query.tally()
    assert tally["scope:nodes"] == 3
    assert tally["scope:hulled"] == 2
    assert tally["scope:complete"] == 0
    assert tally["scope_refusal:missing_geometry"] == 1
    assert tally["candidates:adjudicated"] == 0


def test_each_candidate_contributes_exactly_one_adjudication() -> None:
    tally = _query((("a", "b"), ("a", "c"))).tally()
    assert tally["candidates:adjudicated"] == 2
    assert tally["overlap/possible"] == 2
