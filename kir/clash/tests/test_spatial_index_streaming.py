"""Contracts for the shared grid, lazy search, and an independent post-check."""
from __future__ import annotations

import collections
import itertools
import tracemalloc

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import resolve as R
from kir.clash import snapshot as S
from kir.clash.spatial_index import SpatialIndex


def _record(source_id: str, hull: G.Hull, *, side: str = "struct",
            label: str = "wall") -> H.HullRecord:
    category = "OST_PipeCurves" if side == "mep" else "OST_Walls"
    return H.HullRecord(
        source_id=source_id, category=category, label=label,
        mvp_side=side, hull=hull, grade="coarse", hull_source="bbox")


def _snapshot(records: list[H.HullRecord]) -> S.ClashGeometrySnapshot:
    census = S.Census()
    for record in records:
        census.eligible[record.category] += 1
        census.hulled[record.category] += 1
        if record.category in H.SECTION_RULES:
            census.section_absent[record.category] += 1
        if record.mvp_side in H.MVP_PAIR:
            census.mvp_eligible[record.mvp_side] += 1
            census.mvp_hulled[record.mvp_side] += 1
        kind = H.hull_degeneracy(record.hull)
        census.degenerate_hulls[kind] += 1
        if kind != "ok":
            census.degenerate_by_category.setdefault(
                record.category, collections.Counter())[kind] += 1
    return S.ClashGeometrySnapshot(
        records=records, census=census,
        origin={"run_dir": "spatial-index-contract"})


def test_index_matches_independent_brute_force_at_boundaries_and_slack():
    """Negative cells, boundaries, a sliver, and a giant — all in one scene."""
    records = [
        _record("z-negative", G.Aabb((-20.0, -2.0, -2.0),
                                      (-10.0, 2.0, 2.0))),
        _record("a-border", G.Aabb((-9.0, -1.0, -1.0),
                                    (0.0, 1.0, 1.0)), side="mep"),
        _record("m-next-cell", G.Aabb((1.25, -1.0, -1.0),
                                       (2.0, 1.0, 1.0))),
        _record("thin", G.Aabb((-500.0, 9.999, -0.001),
                                (500.0, 10.001, 0.001)), side="mep"),
        _record("giant", G.Aabb((-1e6, -1e6, -1e6),
                                 (1e6, 1e6, 1e6))),
        _record("far", G.Aabb((2e6, 2e6, 2e6),
                               (2e6 + 1.0, 2e6 + 1.0, 2e6 + 1.0))),
    ]
    for slack in (0.0, 1.25, 25.0):
        index = SpatialIndex(records, cell=10.0, slack=slack)
        streamed = list(index.iter_candidate_pairs(
            slack=slack, pair_filter=D.any_physical_pair_filter))
        brute = D.brute_pairs(
            records, slack=slack, pair_filter=D.any_physical_pair_filter)
        assert set(streamed) == set(brute)
        assert len(streamed) == len(set(streamed)), "пара выдана дважды"
        assert D.candidate_pairs(
            records, index, slack=slack,
            pair_filter=D.any_physical_pair_filter) == brute


def test_compatibility_filter_still_receives_lower_record_index_first():
    records = [
        _record("z", G.Aabb((0.0, 0.0, 0.0), (2.0, 2.0, 2.0))),
        _record("a", G.Aabb((1.0, 1.0, 1.0), (3.0, 3.0, 3.0))),
    ]
    grid = D.build_grid(records, cell=10.0)
    assert D.candidate_pairs(
        records, grid,
        pair_filter=lambda first, _second: first.source_id == "z",
    ) == [(0, 1)]


def test_stream_search_and_report_keep_one_canonical_finding_order():
    records = [
        _record(source_id, G.Aabb((0.0, 0.0, 0.0),
                                  (10.0, 10.0, 10.0)),
                side="mep" if index % 2 else "struct")
        for index, source_id in enumerate(("z", "a", "q", "b", "m"))
    ]
    snapshot = _snapshot(records)
    stream = D.iter_findings(
        snapshot, pair_filter=D.any_physical_pair_filter)
    streamed = list(stream)
    search = D.search(snapshot, pair_filter=D.any_physical_pair_filter)
    report = D.detect(snapshot, pair_filter=D.any_physical_pair_filter)

    wire = [finding.as_dict() for finding in streamed]
    assert stream.exhausted
    assert stream.candidate_count == 10
    assert stream.narrow_evaluations == 10
    assert wire == [finding.as_dict() for finding in search.findings]
    assert wire == report["findings"]
    assert [finding.finding_id for finding in streamed] == sorted(
        finding.finding_id for finding in streamed)
    assert report["search"]["candidate_pairs"] == 10


def test_resolution_postcheck_does_not_trust_neighbourhood_candidates(
        monkeypatch):
    """Even a fully blind index cannot certify a dangerous move."""
    mover = _record(
        "m", G.Aabb((0.0, 0.0, 0.0), (100.0, 100.0, 100.0)),
        side="mep", label="pipe")
    fixed = _record(
        "f", G.Aabb((50.0, 0.0, 0.0), (150.0, 100.0, 100.0)))
    blocker = _record(
        "n", G.Aabb((-55.0, 0.0, 0.0), (-5.0, 100.0, 100.0)))
    hood = R.Neighbourhood([mover, fixed, blocker], cell=10.0)
    monkeypatch.setattr(hood, "near", lambda _lo, _hi: set())

    proposal = R.propose(mover, fixed, hood=hood)
    moves = [move for move in (proposal.chosen, proposal.alternative)
             if move is not None]
    moved_pipe = next(move for move in moves if move.element_id == "m")
    assert not moved_pipe.legal
    assert moved_pipe.hits == ("n",)
    assert moved_pipe.hits_total == 1
    assert "hits_third_body" in moved_pipe.blockers


def test_partial_stream_does_not_materialize_the_dense_pair_universe():
    """1.27M possible pairs: the first 128 must not allocate the full list of them."""
    count = 1600
    records = [
        _record(f"e{index:04d}", G.Aabb((0.0, 0.0, 0.0),
                                        (10.0, 10.0, 10.0)))
        for index in range(count)
    ]
    snapshot = _snapshot(records)

    tracemalloc.start()
    try:
        stream = D.iter_findings(
            snapshot, pair_filter=D.any_physical_pair_filter,
            cell_mm=100.0)
        prefix = list(itertools.islice(stream, 128))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(prefix) == 128
    assert stream.candidate_count == 128
    assert not stream.exhausted
    assert peak < 16 * 1024 * 1024, (
        f"ленивый префикс занял {peak / 1024 / 1024:.1f} MiB")


def test_index_does_not_silently_coerce_its_memory_ceiling() -> None:
    record = _record(
        "one", G.Aabb((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    for invalid in (True, 0, 1.5):
        try:
            SpatialIndex([record], max_cells_per_hull=invalid)
        except ValueError:
            pass
        else:  # pragma: no cover — this line only makes a failure explainable
            raise AssertionError(
                f"потолок ячеек молча принят как {invalid!r}")
