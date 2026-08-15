"""Geometry proof never becomes permission to delete a BIM element."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash import resolve as R


def _prism(x0: float = 0.0) -> G.Prism:
    return G.Prism(
        ((x0, 0.0), (x0 + 10.0, 0.0),
         (x0 + 10.0, 10.0), (x0, 10.0)),
        0.0, 10.0)


def _record(element_id: str, hull: G.Hull, *, grade: str = "exact",
            with_inner: bool = True) -> H.HullRecord:
    inner = None
    if with_inner:
        inner = H.certify_analytic_inner_for_test(
            inner=hull, body=hull, outer=hull,
            subject_source_id=element_id,
            body_source_digest=H.analytic_hull_digest(hull),
            body_source_revision=f"fixture:{element_id}:body-r1")
    return H.HullRecord(
        source_id=element_id, category="OST_Floors", label="floor",
        mvp_side="struct", hull=hull, grade=grade,
        hull_source="analytic_exact_fixture", inner=inner)


def _proven_finding() -> dict:
    finding = D.evaluate(_record("a", _prism()), _record("b", _prism()))
    assert finding is not None
    return finding.as_dict()


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_exact_equal_bodies_receive_a_sealed_destructive_proof():
    finding = _proven_finding()
    proof = finding["exact_body_equality_proof"]
    assert finding["pair_kind"] == "coincident_duplicate"
    assert finding["verdict"] == "confirmed"
    assert proof["status"] == "proven"
    assert proof["outcome"] == "equal"
    assert len(proof["proof_digest"]) == 64
    assert len(proof["equality_integrity_tag"]) == 64
    assert proof["a"]["hull_digest"] == proof["b"]["hull_digest"]
    assert D.duplicate_claim_is_proven(finding) is True


def test_even_sealed_geometry_emits_verify_not_delete_recommendation():
    """Semantic/dependency equivalence is outside the geometry API."""

    a = _record("a", _prism())
    b = _record("b", _prism())
    proposal = R.propose(a, b, pair_kind="coincident_duplicate")
    assert proposal.recommendation == "verify_duplicate"
    assert "удаление запрещено" in proposal.as_dict()["recommendation_note"]
    assert "delete" not in proposal.recommendation


def test_review_tolerance_never_becomes_destructive_equality_tolerance():
    """A 0.5 mm offset is a useful near-duplicate candidate, not equality."""

    finding = D.evaluate(
        _record("a", _prism(0.0)),
        _record("b", _prism(0.5)))
    assert finding is not None
    serialized = finding.as_dict()
    # The broad classifier deliberately groups this for human review.
    assert serialized["pair_kind"] == "coincident_duplicate"
    # The destructive capability uses only the numeric equality epsilon.
    assert serialized["exact_body_equality_proof"]["status"] == "not_proven"
    assert serialized["exact_body_equality_proof"]["reason"] == (
        "exact_hulls_not_equal")
    assert D.duplicate_claim_is_proven(serialized) is False


def test_equality_without_physical_confirmation_is_not_actionable_evidence():
    finding = D.evaluate(
        _record("a", _prism(), with_inner=False),
        _record("b", _prism(), with_inner=False))
    assert finding is not None
    serialized = finding.as_dict()
    assert serialized["verdict"] == "possible"
    # A caller-written ``grade=exact`` label is not issuance authority.  The
    # equality claim needs a trusted Body == Hull chain of its own.
    assert serialized["exact_body_equality_proof"]["status"] == "not_proven"
    assert "exact_body_authority_absent" in (
        serialized["exact_body_equality_proof"]["reason"] or "")
    assert D.duplicate_claim_is_proven(serialized) is False


def test_certified_inner_overlap_never_proves_body_equality():
    finding = D.evaluate(
        _record("a", _prism(), grade="conservative"),
        _record("b", _prism(), grade="conservative"))
    assert finding is not None
    serialized = finding.as_dict()
    assert serialized["verdict"] == "confirmed"
    assert serialized["physical_overlap_proof"]["status"] == "confirmed"
    assert serialized["exact_body_equality_proof"]["status"] == "not_proven"
    assert serialized["exact_body_equality_proof"]["reason"] == (
        "exact_body_contract_absent")
    assert D.duplicate_claim_is_proven(serialized) is False


def test_public_pair_kind_grade_and_source_cannot_manufacture_equality():
    finding = D.evaluate(
        _record("a", _prism(), grade="conservative"),
        _record("b", _prism(), grade="conservative"))
    assert finding is not None
    forged = finding.as_dict()
    forged["pair_kind"] = "coincident_duplicate"
    forged["hull_grade"] = "exact"
    for side in (forged["a"], forged["b"]):
        side["hull_grade"] = "exact"
        side["hull_source"] = "analytic_exact_fixture"
    assert D.duplicate_claim_is_proven(forged) is False


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("status",), "not_proven"),
        (("outcome",), "unknown"),
        (("subject_a",), "replayed"),
        (("a", "grade"), "conservative"),
        (("a", "hull_source"), "bbox"),
        (("a", "category"), "OST_Walls"),
        (("a", "hull_digest"), "0" * 64),
        (("a", "hull_evidence", "z1_mm"), 20.0),
        (("proof_digest",), "0" * 64),
        (("equality_integrity_tag",), "0" * 64),
    ],
)
def test_any_equality_proof_tamper_fails_closed(
        path: tuple[str, ...], replacement: object):
    tampered = copy.deepcopy(_proven_finding())
    target = tampered["exact_body_equality_proof"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    assert D.duplicate_claim_is_proven(tampered) is False


def test_public_sha_recalculation_cannot_forge_equality_authority():
    forged = copy.deepcopy(_proven_finding())
    proof = forged["exact_body_equality_proof"]
    proof["a"]["hull_evidence"]["z1_mm"] = 100.0
    proof["a"]["hull_digest"] = _digest(proof["a"]["hull_evidence"])
    public_payload = {
        key: proof[key] for key in D._EXACT_BODY_EQUALITY_PAYLOAD_KEYS}
    proof["proof_digest"] = _digest(public_payload)
    proof["equality_integrity_tag"] = "f" * 64
    assert D.duplicate_claim_is_proven(forged) is False


def test_equality_proof_cannot_be_replayed_for_another_subject():
    replayed = copy.deepcopy(_proven_finding())
    replayed["a"]["source_element_id"] = "another-a"
    assert D.duplicate_claim_is_proven(replayed) is False


def test_process_restart_invalidates_process_local_equality_authority():
    code = (
        "import json,sys; "
        "from kukai.clash import detect as D; "
        "print(D.duplicate_claim_is_proven(json.load(sys.stdin)))")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (
        os.fspath(pathlib.Path(__file__).resolve().parents[3]),
        env.get("PYTHONPATH", ""))))
    result = subprocess.run(
        [sys.executable, "-c", code], input=json.dumps(_proven_finding()),
        text=True, capture_output=True, check=True, env=env)
    assert result.stdout.strip() == "False"


def test_missing_equality_proof_or_tag_fails_closed():
    for key in ("exact_body_equality_proof",):
        missing = copy.deepcopy(_proven_finding())
        missing.pop(key)
        assert D.duplicate_claim_is_proven(missing) is False
    missing_tag = copy.deepcopy(_proven_finding())
    missing_tag["exact_body_equality_proof"].pop("equality_integrity_tag")
    assert D.duplicate_claim_is_proven(missing_tag) is False
