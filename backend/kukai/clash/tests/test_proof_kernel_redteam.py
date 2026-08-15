"""Adversarial invariants for clash proof issuance and candidate coverage."""

from __future__ import annotations

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash import snapshot as S


def _record(element_id: str, hull: G.Hull, *, grade: str = "conservative",
            inner: H.CertifiedInnerHull | None = None) -> H.HullRecord:
    return H.HullRecord(
        source_id=element_id, category="OST_Floors", label="floor",
        mvp_side="struct", hull=hull, grade=grade,
        hull_source="redteam_fixture", inner=inner)


def _certified(element_id: str, inner: G.Hull, outer: G.Hull
               ) -> H.HullRecord:
    evidence = H.certify_analytic_inner_for_test(
        inner=inner, body=inner, outer=outer,
        subject_source_id=element_id,
        body_source_digest=H.analytic_hull_digest(inner),
        body_source_revision=f"fixture:{element_id}:body-r1")
    return _record(element_id, outer, inner=evidence)


def test_negative_clearance_cannot_shrink_broad_phase_and_hide_overlap() -> None:
    a = _record("a", G.Aabb((0, 0, 0), (10, 10, 10)))
    b = _record("b", G.Aabb((5, 0, 0), (15, 10, 10)))

    for invalid in (-6.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="finite non-negative"):
            D.build_grid([a, b], cell=10.0, slack=invalid)
        with pytest.raises(ValueError, match="finite non-negative"):
            D.evaluate(a, b, clearance_mm=invalid)


def test_invalid_grid_cell_is_rejected_before_candidate_claim() -> None:
    record = _record("a", G.Aabb((0, 0, 0), (10, 10, 10)))
    for invalid in (0.0, -1.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="finite positive"):
            D.build_grid([record], cell=invalid)


def test_scope_capability_cannot_be_spoofed_by_callable_name() -> None:
    def drops_every_pair(_a: H.HullRecord, _b: H.HullRecord) -> bool:
        return False

    drops_every_pair.__name__ = "mvp_pair_filter"
    with pytest.raises(ValueError, match="неизвестный фильтр"):
        D.scope_id_of(drops_every_pair)


def test_balanced_census_cannot_hide_a_missing_hull_record() -> None:
    hull = G.Aabb((0, 0, 0), (10, 10, 10))
    record = _record("a", hull)
    census = S.Census()
    census.eligible[record.category] = 1
    census.hulled[record.category] = 1
    census.mvp_eligible["struct"] = 1
    census.mvp_hulled["struct"] = 1
    census.degenerate_hulls["ok"] = 1
    snapshot = S.ClashGeometrySnapshot(
        [record], census, {"run_dir": "redteam"})
    snapshot.validate()

    snapshot.records.clear()
    with pytest.raises(S.SnapshotIntegrityError, match="hulled"):
        snapshot.validate()


def test_census_refusal_denominator_must_have_exact_rows() -> None:
    census = S.Census()
    census.eligible["OST_Floors"] = 1
    census.missing_geometry["OST_Floors"] = 1
    census.reasons["missing"] = 1
    census.mvp_eligible["struct"] = 1
    census.no_hull_mvp_side["struct"] = 1
    census.no_hull_by_category["OST_Floors"] = 1
    refusal = H.Refusal(
        "a", "OST_Floors", "missing_geometry", "missing")
    snapshot = S.ClashGeometrySnapshot(
        [], census, {"run_dir": "redteam"}, [refusal])
    snapshot.validate()

    snapshot.refusals.clear()
    with pytest.raises(S.SnapshotIntegrityError, match="missing_geometry"):
        snapshot.validate()


def test_boolean_census_count_is_not_integer_evidence() -> None:
    census = S.Census()
    census.eligible["OST_Floors"] = True
    census.hulled["OST_Floors"] = True
    snapshot = S.ClashGeometrySnapshot(
        [], census, {"run_dir": "redteam"})
    with pytest.raises(S.SnapshotIntegrityError, match="неверные счётчики"):
        snapshot.validate()


def test_confirmed_pair_proof_cannot_be_minted_by_public_dataclass() -> None:
    a = _certified(
        "a", G.Aabb((0, 0, 0), (10, 10, 10)),
        G.Aabb((0, 0, 0), (10, 10, 10)))
    b = _certified(
        "b", G.Aabb((100, 0, 0), (110, 10, 10)),
        G.Aabb((100, 0, 0), (110, 10, 10)))
    aa = H.assess_inner_hull(a).as_dict()
    bb = H.assess_inner_hull(b).as_dict()

    with pytest.raises(PermissionError, match="narrow kernel"):
        D.PhysicalOverlapProof(
            status="confirmed", basis="certified_inner_overlap", reason=None,
            subject_a="a", subject_b="b", a=aa, b=bb,
            inner_relation="overlap", inner_signed_distance_mm=-5.0,
            inner_overlap_depth_mm=5.0,
            required_margin_mm=D.EPS_NUMERIC_MM)


def test_issued_pair_proof_cannot_drift_before_serialization() -> None:
    outer = G.Aabb((0, 0, 0), (20, 20, 20))
    a = _certified("a", G.Aabb((1, 1, 1), (12, 12, 12)), outer)
    b = _certified("b", G.Aabb((8, 1, 1), (19, 12, 12)), outer)
    finding = D.evaluate(a, b)
    assert finding is not None and finding.verdict == "confirmed"
    proof = finding.physical_overlap_proof

    with pytest.raises(TypeError):
        proof.a["status"] = "forged"  # type: ignore[index]
    with pytest.raises(TypeError):
        proof.a["certificate"]["body_source_revision"] = "stale"  # type: ignore[index]
    wire = proof.as_dict()
    assert D.verify_serialized_physical_overlap_proof(
        wire, subject_a="a", subject_b="b")


def test_exact_label_without_issued_body_authority_never_proves_equality() -> None:
    hull = G.Prism(((0, 0), (10, 0), (10, 10), (0, 10)), 0, 10)
    finding = D.evaluate(
        _record("a", hull, grade="exact"),
        _record("b", hull, grade="exact"))
    assert finding is not None
    proof = finding.as_dict()["exact_body_equality_proof"]
    assert proof["status"] == "not_proven"
    assert "exact_body_authority_absent" in proof["reason"]


def test_inner_subset_certificate_does_not_authorize_exact_outer_body() -> None:
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    inner = G.Aabb((2, 2, 2), (8, 8, 8))
    a = _certified("a", inner, outer)
    b = _certified("b", inner, outer)
    a.grade = "exact"
    b.grade = "exact"
    finding = D.evaluate(a, b)
    assert finding is not None
    proof = finding.as_dict()["exact_body_equality_proof"]
    assert proof["status"] == "not_proven"
    assert "exact_body_authority_not_equal_to_hull" in proof["reason"]


def test_low_level_sealers_require_kernel_issuance_capability() -> None:
    with pytest.raises(PermissionError, match="narrow kernel"):
        H.seal_serialized_pair_proof({}, authority=object())
    with pytest.raises(PermissionError, match="equality kernel"):
        H.seal_serialized_exact_body_equality_proof({}, authority=object())
