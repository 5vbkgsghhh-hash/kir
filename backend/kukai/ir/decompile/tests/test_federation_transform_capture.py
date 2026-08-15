from __future__ import annotations

import copy
import math

import pytest

from kukai.ir.decompile.dependencies import (
    DependencyManifestError,
    DependencyResolution,
    ExternalResource,
)
from kukai.ir.decompile.extract import (
    ExtractionProtocolError,
    _parse_metadata,
    build_category_batch_cs,
    build_metadata_cs,
)
from kukai.ir.decompile.schema import (
    FEDERATION_TRANSFORM_CONVENTION,
    FEDERATION_TRANSFORM_SCHEMA,
    FederationTransformEvidence,
    FederationTransformGap,
    FederationTransformStatus,
    FederationTransformSubject,
    FederationTransformTarget,
    L0SchemaError,
    federation_transform_digest,
    identity_federation_transform,
)
from kukai.ir.decompile.side_contract import source_binding_cs
from kukai.ir.decompile.tests.fixtures_decompile import project1_metadata


IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
SUBJECT = FederationTransformSubject(
    source_document_key="revit:test:root",
    target_document_key="revit:test:root",
    link_instance_chain=(),
    target_link_instance_chain=(),
)


def bridge_transform(matrix=IDENTITY, target="federation_root") -> dict:
    return {
        "matrix": list(matrix), "status": "authoritative", "gaps": [],
        "target_frame": target,
    }


def test_transform_schema_round_trip_and_digest_are_deterministic() -> None:
    evidence = identity_federation_transform()
    parsed = FederationTransformEvidence.from_dict(evidence.to_dict())
    assert parsed == evidence
    assert parsed.content_digest == federation_transform_digest(
        IDENTITY, subject_context=parsed.subject_context)
    assert parsed.to_dict() == {
        "schema_version": FEDERATION_TRANSFORM_SCHEMA,
        "convention": FEDERATION_TRANSFORM_CONVENTION,
        "matrix": list(IDENTITY),
        "status": "authoritative",
        "gaps": [],
        "content_digest": evidence.content_digest,
        "target_frame": "federation_root",
        "subject_context": evidence.subject_context.to_dict(),
    }
    replay = evidence.to_dict()
    replay["subject_context"]["link_instance_chain"] = ["other-instance"]
    with pytest.raises(L0SchemaError, match="content_digest mismatch"):
        FederationTransformEvidence.from_dict(replay)

    matrix_replay = evidence.to_dict()
    matrix_replay["matrix"][3] = 1.0
    with pytest.raises(L0SchemaError, match="content_digest mismatch"):
        FederationTransformEvidence.from_dict(matrix_replay)

    target_replay = evidence.to_dict()
    target_replay["target_frame"] = "parent_source"
    with pytest.raises(L0SchemaError, match="content_digest mismatch"):
        FederationTransformEvidence.from_dict(target_replay)


@pytest.mark.parametrize("mutation", [
    lambda matrix: matrix.__setitem__(0, 2.0),
    lambda matrix: matrix.__setitem__(1, 0.25),
    lambda matrix: matrix.__setitem__(15, 0.0),
    lambda matrix: matrix.__setitem__(3, float("nan")),
])
def test_scale_shear_nonaffine_and_nan_are_rejected(mutation) -> None:
    matrix = list(IDENTITY)
    mutation(matrix)
    with pytest.raises(L0SchemaError):
        FederationTransformEvidence.from_bridge_dict(
            bridge_transform(matrix), subject_context=SUBJECT)


def test_affine_last_row_is_exact_and_negative_zero_is_canonical() -> None:
    # The Bridge emits this row from literals.  A near-projective row cannot
    # be accepted because point application ignores W while the digest would
    # attest those projective bytes.
    near_projective = list(IDENTITY)
    near_projective[12] = 1e-12
    with pytest.raises(L0SchemaError, match="affine last row"):
        FederationTransformEvidence.from_bridge_dict(
            bridge_transform(near_projective), subject_context=SUBJECT)

    negative_zero = list(IDENTITY)
    negative_zero[12] = -0.0
    evidence = FederationTransformEvidence.from_bridge_dict(
        bridge_transform(negative_zero), subject_context=SUBJECT)
    assert evidence.matrix is not None
    assert evidence.matrix[12] == 0.0
    assert math.copysign(1.0, evidence.matrix[12]) == 1.0


def test_reflection_is_valid_revit_isometry() -> None:
    matrix = list(IDENTITY)
    matrix[0] = -1.0
    evidence = FederationTransformEvidence.from_bridge_dict(
        bridge_transform(matrix), subject_context=SUBJECT)
    assert evidence.authoritative
    assert evidence.determinant == -1.0


def test_missing_transform_requires_one_closed_gap() -> None:
    evidence = FederationTransformEvidence.from_bridge_dict({
        "matrix": None,
        "status": "incomplete",
        "gaps": ["transform_unavailable"],
        "target_frame": "federation_root",
    }, subject_context=SUBJECT)
    assert evidence.gaps == (FederationTransformGap.TRANSFORM_UNAVAILABLE,)
    assert evidence.content_digest is None
    assert evidence.target_frame is FederationTransformTarget.FEDERATION_ROOT
    malformed = evidence.to_dict()
    malformed["unexpected"] = True
    with pytest.raises(L0SchemaError, match="keys mismatch"):
        FederationTransformEvidence.from_dict(malformed)


def test_bridge_metadata_is_validated_and_digested_before_l0() -> None:
    payload = project1_metadata()
    payload["federation_transform"] = bridge_transform()
    parsed = _parse_metadata(copy.deepcopy(payload), "stamp")
    assert parsed.federation_transform is not None
    assert parsed.federation_transform.authoritative
    assert parsed.metadata_dict()["federation_transform"]["content_digest"]

    broken = copy.deepcopy(payload)
    broken["federation_transform"]["matrix"][5] = 4.0
    with pytest.raises(ExtractionProtocolError, match="federation transform"):
        _parse_metadata(broken, "stamp")


def test_bridge_link_transform_digest_binds_both_documents_and_instance() -> None:
    payload = project1_metadata()
    root_fact = {
        "source": "cloud_project_model_guid", "value": "project/root",
    }
    child_fact = {
        "source": "revit_server_central_guid", "value": "child-guid",
    }
    payload["identity"] = {
        "schema_version": "kir-l0-revit-identity/1",
        "source_kind": "root",
        "document_identity": root_fact,
        "federation_root_identity": root_fact,
        "link_instance_chain": [],
        "status": "authoritative",
        "gaps": [],
    }
    payload["federation_transform"] = bridge_transform()
    payload["links"] = [{
        "element_id": "10", "name": "MEP", "loaded": True,
        "element_count": 1, "bbox_min_mm": None, "bbox_max_mm": None,
        "discipline": "mechanical",
        "identity": {
            "schema_version": "kir-l0-revit-identity/1",
            "instance_unique_id": "exact-link-instance",
            "linked_document_identity": child_fact,
            "status": "authoritative", "gaps": [],
        },
        "transform": bridge_transform(target="parent_source"),
    }]
    parsed = _parse_metadata(payload, "stamp")
    evidence = parsed.links[0].transform
    assert evidence is not None
    assert evidence.subject_context.to_dict() == {
        "source_document_key": "revit:revit_server_central_guid:child-guid",
        "target_document_key": "revit:cloud_project_model_guid:project/root",
        "link_instance_chain": ["exact-link-instance"],
        "target_link_instance_chain": [],
    }
    assert evidence.to_dict()["target_frame"] == "parent_source"


def test_transform_subject_rejects_an_unrelated_parent_chain() -> None:
    with pytest.raises(L0SchemaError, match="prefix of source chain"):
        FederationTransformSubject(
            source_document_key="revit:test:child",
            target_document_key="revit:test:not-the-parent",
            link_instance_chain=("direct", "nested"),
            target_link_instance_chain=("different-direct",),
        )


def test_emitter_captures_source_and_child_total_transforms_in_mm() -> None:
    body = build_metadata_cs()
    assert "__sourceLinkInstance.GetTotalTransform()" in body
    assert "__link.GetTotalTransform()" in body
    assert '"federation_transform"' in body
    assert '__linkRow["transform"]' in body
    assert '"parent_source"' in body
    assert "__MM(__origin.X)" in body
    assert "__bx.X, __by.X, __bz.X, __ox" in body
    assert '"transform_invalid"' in body
    assert "Math.Abs(Math.Abs(__det) - 1.0)" in body


def test_exact_link_instance_unique_id_is_the_preferred_selector() -> None:
    uid = 'link-instance-uid"with-quote'
    binding = source_binding_cs(None, uid)
    assert "__candidateUniqueId ==" in binding
    assert "GetLinkDocument" in binding
    assert "link instance UniqueId not found" in binding
    assert 'uid\\"with-quote' in binding
    body = build_category_batch_cs(
        "OST_Walls", link_instance_unique_id=uid)
    assert binding in body
    assert "Title ==" not in binding
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_metadata_cs(
            link_title="same title", link_instance_unique_id=uid)


def test_legacy_title_selector_remains_ambiguity_refusing() -> None:
    binding = source_binding_cs("MEP")
    assert "__srcLd.Title ==" in binding
    assert "if (__sourceLinkMatches > 1) throw" in binding
    assert "linked document title is ambiguous" in binding


def test_external_resource_accepts_only_typed_transform_evidence() -> None:
    base = dict(
        key="link:1", kind="revit_link", source_element_id="1", name="MEP",
        fingerprint=None, resolution=DependencyResolution.UNSUPPORTED,
        loaded=True, discipline="mechanical", identity_note="measured",
    )
    resource = ExternalResource(
        **base, transform=identity_federation_transform())
    assert resource.to_dict()["transform"]["content_digest"]
    with pytest.raises(DependencyManifestError, match="validated evidence"):
        ExternalResource(**base, transform=IDENTITY)  # type: ignore[arg-type]
