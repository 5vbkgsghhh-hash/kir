"""A CLASH REACHES THE GRAPH — a seam that was unreachable BY
CONSTRUCTION.

🔴 WHAT THIS GUARDS, MEASURED 19.08.2026. `graph_clash_query` had ZERO
production importers, and this read as "built and not wired up." The
measurement showed something different and worse: **the input was
unreachable by construction**. `edge_from_finding` accepts a typed
`clash_detect.Finding`; `detect()`, at the report boundary, returned
`[f.as_dict() ...]` — dicts. The one bridge from a clash into the graph
did not accept what the detector's one production output actually
produces.

The addresses, meanwhile, had reconciled the entire time: on
`sob62_r23_v5`, **298 of 298** subjects among the first 400 findings are
present in the graph as nodes, because the key on both sides is the same
`element_id` from L0. What was missing was exactly the wire, and the wire
was impossible because of TYPE, not because of address.

WHY IT WAS FIXED FROM THE DETECTOR'S SIDE, NOT BY A SECOND DOOR ON THE
ADAPTER. The body of `edge_from_finding` is already wire-shaped
(`wire = finding.as_dict()`), and the temptation to open a door "from a
dict" existed. But the `SEPARATED` branch carries a deliberate guarantee,
stated there in words: `PROVEN/SEPARATED` is minted "from the live typed
detector object, not from a deserialized mapping." The door on types is
LOAD-BEARING — accepting a dict there would let a forged record mint a
proven separation.

WHAT EXACTLY IS PINNED HERE, AND WHY THIS SPECIFICALLY. The test does NOT
touch the decompile corpus (it is machine-local): what is pinned is the
TYPE CONTRACT — exactly the quantity whose mismatch broke the seam open
in the first place. If `search()` starts returning dicts again, or
`detect()` stops building a report, red will arrive right here, not a
day later in someone else's wave.
"""
from __future__ import annotations

import pytest

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import snapshot as S
from kir.decompile import graph_clash_query as Q


def _record(element_id: str, hull: G.Hull) -> H.HullRecord:
    return H.HullRecord(
        source_id=element_id, category="OST_Floors", label="floor",
        mvp_side="struct", hull=hull, grade="conservative",
        hull_source="clash_reaches_graph_fixture")


def _overlapping_pair() -> S.ClashGeometrySnapshot:
    """Two overlapping solids — the minimum on which a finding ARISES.

    The census must reconcile: `eligible = hulled + refusals`. The
    detector rejects, AT THE INPUT, a snapshot whose census does not
    reconcile, and rightly so — otherwise it would find zero clashes and
    look sound.
    """
    a = _record("1001", G.Aabb((0, 0, 0), (1000, 1000, 1000)))
    b = _record("1002", G.Aabb((500, 500, 500), (1500, 1500, 1500)))
    census = S.Census()
    census.eligible["OST_Floors"] = 2
    census.hulled["OST_Floors"] = 2
    census.mvp_eligible["struct"] = 2
    census.mvp_hulled["struct"] = 2
    # The degeneracy census is a THIRD axis of the same law, and it must
    # reconcile separately: 9.7% of the store (64,357 of 664,870) are
    # zero-volume shells with nothing to intersect, and their silent
    # dropout would understate clashes without a single refusal.
    census.degenerate_hulls["ok"] = 2
    snapshot = S.ClashGeometrySnapshot(
        [a, b], census, {"run_dir": "clash_reaches_graph"})
    snapshot.validate()
    return snapshot


class TheSeamIsWholeOrAbsent:
    pass


def test_search_hands_back_typed_findings_not_wire_dicts() -> None:
    """THE VERY THING THAT WAS MISSING. A dict here is a broken-open
    seam."""
    found = D.search(_overlapping_pair(),
                     pair_filter=D.any_physical_pair_filter)
    assert found.findings, "фикстура обязана дать хотя бы одну находку, иначе тест вакуумен"
    for finding in found.findings:
        assert isinstance(finding, D.Finding), (
            "search() отдал НЕ типизированную находку — мост в граф "
            "разомкнут ровно этим")


def test_the_adapter_accepts_exactly_what_search_produces() -> None:
    """Closing the seam: one's output must be the other's input."""
    found = D.search(_overlapping_pair(),
                     pair_filter=D.any_physical_pair_filter)
    edge = Q.edge_from_finding(found.findings[0])
    assert edge.a and edge.b and edge.a < edge.b
    assert edge.relation in tuple(Q.ClashRelation)


def test_the_adapter_still_refuses_a_wire_mapping() -> None:
    """A FAIL control, and also a guarantee. The door on types must stay
    closed to a dict: `PROVEN/SEPARATED` is minted through it, and a
    forged record has no right to obtain it."""
    found = D.search(_overlapping_pair(),
                     pair_filter=D.any_physical_pair_filter)
    wire = found.findings[0].as_dict()
    with pytest.raises(Exception):
        Q.edge_from_finding(wire)


def test_detect_still_returns_a_report_of_wire_records() -> None:
    """Extracting the search has no right to change the report: it has a
    different consumer.

    Byte-for-byte equality of the report before and after the extraction
    has been checked on TWO real buildings (`sob62_r23_v5` 3,759 findings,
    `graph_check` 10,906) — what is pinned here is the SHAPE, available
    without the machine-local corpus.
    """
    report = D.detect(_overlapping_pair(),
                      pair_filter=D.any_physical_pair_filter)
    assert isinstance(report, dict)
    assert report["findings"], "отчёт обязан нести находки"
    for row in report["findings"]:
        assert isinstance(row, dict), (
            "отчёт обязан остаться JSON-представимым: типы здесь сломали бы "
            "всех его читателей")


def test_search_and_detect_agree_on_the_same_pass() -> None:
    """One bearer of the overcount, two forms. A count mismatch means a
    second search."""
    snapshot = _overlapping_pair()
    found = D.search(snapshot, pair_filter=D.any_physical_pair_filter)
    report = D.detect(snapshot, pair_filter=D.any_physical_pair_filter)
    assert len(found.findings) == len(report["findings"])
