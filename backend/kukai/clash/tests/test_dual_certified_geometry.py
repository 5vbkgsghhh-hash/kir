"""Vertical contract tests for dual certified clash geometry."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.ir import clash_judgement as J


def record(element_id: str, outer: G.Hull, *,
           evidence: H.CertifiedInnerHull | object | None = None
           ) -> H.HullRecord:
    return H.HullRecord(
        source_id=element_id, category="OST_DuctCurves", label="duct",
        mvp_side="mep", hull=outer, grade="conservative",
        hull_source="analytic_outer", inner=evidence)


def certified_record(element_id: str, outer: G.Hull, inner: G.Hull, *,
                     body: G.Hull | None = None,
                     revision: str = "test-r1", error: float = 0.0,
                     tolerance: float = 0.0) -> H.HullRecord:
    body = inner if body is None else body
    evidence = H.certify_analytic_inner_for_test(
        inner=inner, body=body, outer=outer,
        subject_source_id=element_id,
        body_source_digest=H.analytic_hull_digest(body),
        body_source_revision=f"fixture:{element_id}:body-r1",
        revision=revision, error_bound_mm=error,
        tolerance_mm=tolerance)
    return record(element_id, outer, evidence=evidence)


def certified_pair() -> tuple[H.HullRecord, H.HullRecord]:
    a_outer = G.Aabb((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
    a = certified_record(
        "a", a_outer,
        G.Aabb((2.0, 2.0, 2.0), (8.0, 8.0, 8.0)),
        body=G.Aabb((1.0, 1.0, 1.0), (9.0, 9.0, 9.0)),
        revision="a-r1")
    b_outer = G.Prism(
        ((5.0, 0.0), (15.0, 0.0), (15.0, 10.0), (5.0, 10.0)),
        0.0, 10.0)
    b_inner = G.Prism(
        ((6.0, 2.0), (12.0, 2.0), (12.0, 8.0), (6.0, 8.0)),
        2.0, 8.0)
    b_body = G.Prism(
        ((5.5, 1.0), (14.0, 1.0), (14.0, 9.0), (5.5, 9.0)),
        1.0, 9.0)
    b = certified_record(
        "b", b_outer, b_inner, body=b_body, revision="b-r1")
    return a, b


def test_outer_separation_remains_a_proven_clear_without_inner_evidence():
    a = record("a", G.Aabb((0, 0, 0), (10, 10, 10)))
    b = record("b", G.Aabb((20, 0, 0), (30, 10, 10)))
    finding, reason = D.evaluate_with_reason(a, b)
    assert finding is None
    assert reason is None


def test_outer_only_overlap_is_possible_not_confirmed():
    a = record("a", G.Aabb((0, 0, 0), (10, 10, 10)))
    b = record("b", G.Aabb((5, 0, 0), (15, 10, 10)))
    finding = D.evaluate(a, b)
    assert finding is not None
    assert finding.verdict == "possible"
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["status"] == "not_proven"
    assert proof["reason"] == (
        "a:inner_evidence_absent;b:inner_evidence_absent")


def test_positive_overlap_of_two_certified_inners_is_confirmed():
    finding = D.evaluate(*certified_pair())
    assert finding is not None
    assert finding.hull_grade == "conservative"
    assert finding.verdict == "confirmed"
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["status"] == "confirmed"
    assert proof["basis"] == "certified_inner_overlap"
    assert proof["inner_relation"] == "overlap"
    assert proof["inner_overlap_depth_mm"] > proof["required_margin_mm"]
    assert proof["a"]["certificate"]["revision"] == "a-r1"
    assert proof["b"]["certificate"]["revision"] == "b-r1"


def test_touching_certified_inners_are_not_positive_volume_overlap():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    a = certified_record("a", outer, G.Aabb((1, 1, 1), (5, 9, 9)))
    b = certified_record("b", outer, G.Aabb((5, 1, 1), (9, 9, 9)))
    finding = D.evaluate(a, b)
    assert finding is not None and finding.verdict == "possible"
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["inner_relation"] == "contact"
    assert proof["reason"] == "certified_inners_touch_only"


def assert_invalid_evidence_is_named(
        evidence: H.CertifiedInnerHull, reason: str) -> None:
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    a = record("a", outer, evidence=evidence)
    b = certified_record(
        "b", outer, G.Aabb((2, 2, 2), (8, 8, 8)))
    finding = D.evaluate(a, b)
    assert finding is not None and finding.verdict == "possible"
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["status"] == "not_proven"
    assert proof["a"]["status"] == "rejected"
    assert proof["a"]["reason"] == reason
    assert f"a:{reason}" in proof["reason"]


def test_missing_certificate_is_named_and_never_becomes_proof():
    evidence = H.CertifiedInnerHull(
        G.Aabb((1, 1, 1), (9, 9, 9)), None)
    assert_invalid_evidence_is_named(evidence, "inner_certificate_missing")


def test_issued_certificate_cannot_be_reused_for_an_unsupported_hull():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    issued = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="a",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1")
    evidence = H.CertifiedInnerHull(
        G.Capsule(((1, 1, 1), (9, 1, 1)), 1.0), issued.certificate)
    assert_invalid_evidence_is_named(
        evidence, "inner_hull_type_unsupported:Capsule")


def test_certificate_is_bound_to_the_inner_geometry():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    issued = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="a",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1")
    evidence = H.CertifiedInnerHull(
        G.Aabb((-1, 1, 1), (9, 9, 9)), issued.certificate)
    assert_invalid_evidence_is_named(
        evidence, "inner_certificate_inner_digest_mismatch")


def test_certificate_cannot_be_reused_for_another_source_element():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    issued = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="original",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1")
    assessment = H.assess_inner_hull(
        record("different", outer, evidence=issued))
    assert assessment.status == "rejected"
    assert assessment.reason == "inner_certificate_subject_mismatch"


def test_tampered_error_bound_never_weakens_proof():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    issued = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="a",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1", tolerance_mm=1.0)
    assert issued.certificate is not None
    object.__setattr__(issued.certificate, "error_bound_mm", 2.0)
    assert_invalid_evidence_is_named(
        issued, "inner_certificate_error_exceeds_tolerance")


def test_analytic_issuer_refuses_inner_not_contained_in_body():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    body = G.Aabb((2, 2, 2), (8, 8, 8))
    with pytest.raises(ValueError, match="inner_not_contained_in_body"):
        H.certify_analytic_inner_for_test(
            inner=G.Aabb((1, 1, 1), (9, 9, 9)), body=body, outer=outer,
            subject_source_id="a",
            body_source_digest=H.analytic_hull_digest(body),
            body_source_revision="fixture:body-r1")


def test_analytic_issuer_refuses_body_not_contained_in_outer():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    body = G.Aabb((-1, 1, 1), (9, 9, 9))
    with pytest.raises(ValueError, match="body_not_contained_in_outer"):
        H.certify_analytic_inner_for_test(
            inner=G.Aabb((0, 2, 2), (8, 8, 8)), body=body, outer=outer,
            subject_source_id="a",
            body_source_digest=H.analytic_hull_digest(body),
            body_source_revision="fixture:body-r1")


def test_analytic_issuer_refuses_a_contradictory_body_source_digest():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    body = G.Aabb((1, 1, 1), (9, 9, 9))
    other = G.Aabb((2, 2, 2), (8, 8, 8))
    with pytest.raises(ValueError, match="body_source_digest_mismatch"):
        H.certify_analytic_inner_for_test(
            inner=other, body=body, outer=outer,
            subject_source_id="a",
            body_source_digest=H.analytic_hull_digest(other),
            body_source_revision="fixture:body-r1")


def test_direct_or_forged_certificate_has_no_issuance_authority():
    with pytest.raises(TypeError, match="opaque"):
        H.InnerHullCertificate(
            issuer=H.ANALYTIC_TEST_INNER_ISSUER,
            proof_kind=H.ANALYTIC_SUBSET_PROOF_KIND,
            provenance=H.ANALYTIC_BODY_PROVENANCE,
            revision="forged-r1", subject_source_id="a",
            body_source_digest="0" * 64,
            body_source_revision="forged-body-r1", inner_digest="0" * 64,
            outer_digest="0" * 64, error_bound_mm=0.0,
            tolerance_mm=0.0, certificate_digest="0" * 64,
            schema_version=H.INNER_CERTIFICATE_SCHEMA)

    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    legitimate = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="a",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1")
    assert legitimate.certificate is not None
    forged = object.__new__(H.InnerHullCertificate)
    for name, value in legitimate.certificate.as_dict().items():
        object.__setattr__(forged, name, value)
    evidence = H.CertifiedInnerHull(legitimate.hull, forged)
    assert_invalid_evidence_is_named(evidence, "inner_certificate_not_issued")


def test_raw_certificate_mapping_has_no_authority():
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    legitimate = H.certify_analytic_inner_for_test(
        inner=G.Aabb((1, 1, 1), (9, 9, 9)),
        body=G.Aabb((1, 1, 1), (9, 9, 9)), outer=outer,
        subject_source_id="a",
        body_source_digest=H.analytic_hull_digest(
            G.Aabb((1, 1, 1), (9, 9, 9))),
        body_source_revision="fixture:body-r1")
    evidence = H.CertifiedInnerHull(
        legitimate.hull, legitimate.certificate.as_dict())  # type: ignore[arg-type]
    assert_invalid_evidence_is_named(
        evidence, "inner_certificate_type_invalid")


def test_judgement_accepts_the_complete_confirmed_inner_chain():
    finding = D.evaluate(*certified_pair())
    assert finding is not None and finding.verdict == "confirmed"
    judged = J.judge([finding.as_dict()]).judged[0]
    assert judged.geometry_verdict == "confirmed"
    assert judged.proven is True
    assert judged.kind == "collision"
    assert judged.rung == "fix"
    assert "сдвинуть" in judged.next_move_ru

    proof = finding.as_dict()["physical_overlap_proof"]
    assert len(proof["proof_digest"]) == 64
    assert len(proof["pair_integrity_tag"]) == 64
    assert len(proof["a"]["certificate"]["integrity_tag"]) == 64
    assert len(proof["b"]["certificate"]["integrity_tag"]) == 64


def test_judgement_rejects_a_confirmed_word_without_the_proof_chain():
    finding = D.evaluate(*certified_pair())
    assert finding is not None
    forged = finding.as_dict()
    forged.pop("physical_overlap_proof")
    judged = J.judge([forged]).judged[0]
    assert judged.proven is None
    assert judged.rung == "look"
    assert "сдвинуть" not in judged.next_move_ru


def public_digest(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recalculate_public_certificate_digest(certificate: dict) -> None:
    payload = {
        key: certificate[key]
        for key in (
            "schema_version", "issuer", "proof_kind", "provenance",
            "revision", "subject_source_id", "body_source_digest",
            "body_source_revision", "inner_digest", "outer_digest",
            "error_bound_mm", "tolerance_mm")
    }
    certificate["certificate_digest"] = public_digest(payload)


def recalculate_public_pair_digest(proof: dict) -> None:
    payload = {
        key: proof[key]
        for key in D._PAIR_PROOF_PAYLOAD_KEYS
    }
    proof["proof_digest"] = public_digest(payload)


def assert_judgement_has_no_proven_repair(finding: dict) -> None:
    judged = J.judge([finding]).judged[0]
    assert judged.proven is not True
    assert judged.rung != "fix"
    assert "сдвинуть" not in judged.next_move_ru


def test_publicly_recalculated_sha_mapping_cannot_forge_proof_authority():
    """Regression: public SHA fields used to be a self-signed assertion."""

    finding = D.evaluate(*certified_pair())
    assert finding is not None
    forged = copy.deepcopy(finding.as_dict())
    proof = forged["physical_overlap_proof"]
    for side_name, fill in (("a", "a"), ("b", "b")):
        certificate = proof[side_name]["certificate"]
        certificate["body_source_digest"] = fill * 64
        certificate["inner_digest"] = fill * 64
        certificate["outer_digest"] = fill * 64
        recalculate_public_certificate_digest(certificate)
        # A serializer can invent a well-shaped tag but cannot calculate the
        # process-local HMAC.
        certificate["integrity_tag"] = ("c" if side_name == "a" else "d") * 64
        assert not H.verify_serialized_inner_certificate(
            certificate, expected_subject_source_id=side_name)
    proof["inner_signed_distance_mm"] = -100.0
    proof["inner_overlap_depth_mm"] = 100.0
    proof["required_margin_mm"] = 0.000001
    recalculate_public_pair_digest(proof)
    proof["pair_integrity_tag"] = "e" * 64

    assert not D.verify_serialized_physical_overlap_proof(
        proof, subject_a="a", subject_b="b")
    assert_judgement_has_no_proven_repair(forged)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("inner_overlap_depth_mm",), 100.0),
        (("required_margin_mm",), 0.0),
        (("a", "certificate", "body_source_revision"), "replayed-r2"),
        (("a", "certificate", "integrity_tag"), "0" * 64),
    ],
)
def test_pair_or_certificate_tamper_cannot_retain_proof(
        path: tuple[str, ...], replacement: object):
    finding = D.evaluate(*certified_pair())
    assert finding is not None
    tampered = copy.deepcopy(finding.as_dict())
    target = tampered["physical_overlap_proof"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    assert_judgement_has_no_proven_repair(tampered)


def test_pair_proof_and_certificate_are_bound_to_finding_subjects():
    finding = D.evaluate(*certified_pair())
    assert finding is not None
    replayed = copy.deepcopy(finding.as_dict())
    certificate = replayed["physical_overlap_proof"]["a"]["certificate"]
    assert H.verify_serialized_inner_certificate(
        certificate, expected_subject_source_id="a")
    assert not H.verify_serialized_inner_certificate(
        certificate, expected_subject_source_id="different-a")
    replayed["a"]["source_element_id"] = "different-a"
    assert_judgement_has_no_proven_repair(replayed)


def test_missing_integrity_tags_fail_closed():
    finding = D.evaluate(*certified_pair())
    assert finding is not None
    for path in (
            ("pair_integrity_tag",),
            ("a", "certificate", "integrity_tag")):
        missing = copy.deepcopy(finding.as_dict())
        target = missing["physical_overlap_proof"]
        for key in path[:-1]:
            target = target[key]
        target.pop(path[-1])
        assert_judgement_has_no_proven_repair(missing)
