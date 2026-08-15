from __future__ import annotations

import math

import pytest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash.federation_transform import (
    FEDERATION_LEVEL_GAP,
    FEDERATION_PROOF_GAP,
    FederationGeometryGapReason,
    HullFederationSource,
    federate_hulls,
    transform_hull,
)
from kukai.ir.decompile.identity import (
    DefinitionIdentity,
    DocumentIdentity,
    FederationContext,
    OccurrenceIdentity,
)
from kukai.ir.decompile.federation import LinkAuthorityBinding
from kukai.ir.decompile.schema import (
    FederationTransformEvidence,
    FederationTransformSubject,
)


ROOT = "root-model"
IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def transform(
    matrix,
    bound_occurrence: OccurrenceIdentity | None = None,
    *,
    target_frame: str = "federation_root",
) -> FederationTransformEvidence:
    if bound_occurrence is None:
        bound_occurrence = occurrence("math-doc", "math-element")
    target_chain = ()
    return FederationTransformEvidence.from_bridge_dict({
        "matrix": list(matrix), "status": "authoritative", "gaps": [],
        "target_frame": target_frame,
    }, subject_context=FederationTransformSubject(
        source_document_key=bound_occurrence.definition.document.value,
        target_document_key=bound_occurrence.federation_root,
        link_instance_chain=bound_occurrence.link_instance_chain,
        target_link_instance_chain=target_chain,
    ))


def occurrence(
    document: str,
    element: str,
    chain: tuple[str, ...] = ("link-instance",),
) -> OccurrenceIdentity:
    return OccurrenceIdentity(
        federation_root=ROOT,
        link_instance_chain=chain,
        definition=DefinitionIdentity(DocumentIdentity(document), element),
    )


def record(source_id: str, hull: G.Hull, *, inner=None) -> H.HullRecord:
    return H.HullRecord(
        source_id=source_id, category="OST_DuctCurves", label="duct",
        mvp_side="mep", hull=hull, grade="exact", hull_source="fixture",
        inner=inner,
    )


def source(name: str, rows, identities, matrix) -> HullFederationSource:
    resolved = [value for value in identities.values() if value is not None]
    binding = None
    if resolved and len(resolved[0].link_instance_chain) == 1:
        observed = resolved[0]
        binding = LinkAuthorityBinding(
            expectation_id=f"expectation:{name}",
            parent_document_identity=DocumentIdentity(ROOT),
            parent_context=FederationContext(ROOT, ()),
            local_link_element_id=f"link-alias:{name}",
            link_instance_unique_id=observed.link_instance_chain[0],
            linked_document_identity=observed.definition.document,
            child_context=FederationContext(
                ROOT, observed.link_instance_chain),
        )
    return HullFederationSource(
        source=name, records=tuple(rows),
        occurrence_by_local_id=identities, source_to_root=matrix,
        link_authority_binding=binding)


def assert_point(actual, expected) -> None:
    assert actual == tuple(float(value) for value in expected)


def test_translated_rotated_capsule_is_exact_and_radius_is_invariant() -> None:
    # +90 degrees around Z, then (100, 200, 300) mm.
    matrix = transform((
        0, -1, 0, 100,
        1, 0, 0, 200,
        0, 0, 1, 300,
        0, 0, 0, 1,
    ))
    hull, exact = transform_hull(
        G.Capsule(((1, 2, 3), (4, 5, 6)), 25), matrix)
    assert exact
    assert isinstance(hull, G.Capsule)
    assert_point(hull.path[0], (98, 201, 303))
    assert_point(hull.path[1], (95, 204, 306))
    assert hull.radius == 25


def test_mirrored_vertical_prism_stays_exact_with_valid_order() -> None:
    matrix = transform((
        -1, 0, 0, 10,
        0, 1, 0, 20,
        0, 0, 1, 30,
        0, 0, 0, 1,
    ))
    original = G.Prism(((0, 0), (2, 0), (2, 1), (0, 1)), 3, 7)
    hull, exact = transform_hull(original, matrix)
    assert exact
    assert isinstance(hull, G.Prism)
    assert hull.footprint == ((10.0, 20.0), (8.0, 20.0),
                              (8.0, 21.0), (10.0, 21.0))
    assert (hull.z0, hull.z1) == (33.0, 37.0)


def test_z_reflection_reorders_prism_interval_without_shrinking() -> None:
    matrix = transform((
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, -1, 100,
        0, 0, 0, 1,
    ))
    hull, exact = transform_hull(
        G.Prism(((0, 0), (2, 0), (0, 2)), 10, 40), matrix)
    assert exact and isinstance(hull, G.Prism)
    assert (hull.z0, hull.z1) == (60.0, 90.0)


def test_tilted_prism_downgrades_and_contains_all_eight_vertices() -> None:
    c = math.sqrt(0.5)
    matrix = transform((
        1, 0, 0, 10,
        0, c, -c, 20,
        0, c, c, 30,
        0, 0, 0, 1,
    ))
    prism = G.Prism(((0, 0), (4, 0), (4, 2), (0, 2)), 0, 6)
    hull, exact = transform_hull(prism, matrix)
    assert not exact and isinstance(hull, G.Aabb)
    vertices = [
        (matrix.matrix[0] * x + matrix.matrix[1] * y
         + matrix.matrix[2] * z + matrix.matrix[3],
         matrix.matrix[4] * x + matrix.matrix[5] * y
         + matrix.matrix[6] * z + matrix.matrix[7],
         matrix.matrix[8] * x + matrix.matrix[9] * y
         + matrix.matrix[10] * z + matrix.matrix[11])
        for x, y in prism.footprint for z in (prism.z0, prism.z1)
    ]
    for point in vertices:
        assert all(hull.lo[axis] <= point[axis] <= hull.hi[axis]
                   for axis in range(3))


def test_sub_tolerance_tilt_never_uses_vertical_prism_shortcut() -> None:
    # This near-shear is accepted as numerical Revit transform evidence, but
    # m[8] != 0 makes output Z depend on footprint X.  With a large footprint,
    # a tolerance-based "z preserving" decision would miss 1000 mm.
    epsilon = 1e-9
    matrix = transform((
        1, 0, 0, 0,
        0, 1, 0, 0,
        epsilon, 0, 1, 0,
        0, 0, 0, 1,
    ))
    prism = G.Prism(
        ((0, 0), (1e12, 0), (1e12, 1), (0, 1)), 0, 10)
    hull, exact = transform_hull(prism, matrix)
    assert not exact and isinstance(hull, G.Aabb)
    assert hull.lo[2] == 0.0
    assert hull.hi[2] == pytest.approx(1010.0)


def test_near_isometry_capsule_radius_is_conservatively_inflated() -> None:
    epsilon = 1e-9
    matrix = transform((
        1, 0, 0, 0,
        0, 1, 0, 0,
        epsilon, 0, 1, 0,
        0, 0, 0, 1,
    ))
    hull, exact = transform_hull(
        G.Capsule(((0, 0, 0), (100, 0, 0)), 10), matrix)
    assert not exact and isinstance(hull, G.Capsule)
    assert hull.radius > 10.0
    assert hull.bounds()[0][2] <= -10.0
    assert hull.bounds()[1][2] >= 10.0 + 100 * epsilon


def test_degenerate_and_empty_prism_sets_survive_frame_change() -> None:
    # Point and line pieces are legal lower-dimensional conservative bodies.
    c = math.sqrt(0.5)
    matrix = transform((
        1, 0, 0, 5,
        0, c, -c, 6,
        0, c, c, 7,
        0, 0, 0, 1,
    ))
    degenerate = G.PrismSet((((1, 2),), ((3, 4), (5, 6))), 0, 8)
    hull, exact = transform_hull(degenerate, matrix)
    assert not exact and isinstance(hull, G.Aabb)
    for piece in degenerate.pieces:
        for x, y in piece:
            for z in (degenerate.z0, degenerate.z1):
                point = (
                    matrix.matrix[0] * x + matrix.matrix[1] * y
                    + matrix.matrix[2] * z + matrix.matrix[3],
                    matrix.matrix[4] * x + matrix.matrix[5] * y
                    + matrix.matrix[6] * z + matrix.matrix[7],
                    matrix.matrix[8] * x + matrix.matrix[9] * y
                    + matrix.matrix[10] * z + matrix.matrix[11],
                )
                assert all(hull.lo[axis] <= point[axis] <= hull.hi[axis]
                           for axis in range(3))
    empty, empty_exact = transform_hull(G.PrismSet((), 10, 20), matrix)
    assert empty_exact and empty == G.PrismSet((), 0.0, 0.0)


def test_rotated_aabb_uses_all_corners_and_downgrades_to_coarse() -> None:
    c = math.sqrt(0.5)
    occ = occurrence("linked", "uid-a")
    matrix = transform((
        c, -c, 0, 0,
        c, c, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), occ)
    result = federate_hulls((source(
        "linked", [record("7", G.Aabb((0, 0, 0), (2, 4, 6)))],
        {"7": occ}, matrix),), federation_root=ROOT)
    assert result.census.as_dict() == {"input": 1, "transformed": 1, "gaps": 0}
    assert isinstance(result.records[0].hull, G.Aabb)
    assert result.records[0].grade == "coarse"
    assert result.records[0].hull_source == "federated_conservative_aabb"


def test_same_local_ids_in_different_documents_do_not_collide() -> None:
    left = occurrence("doc-left", "element-left", ("link-left",))
    right = occurrence("doc-right", "element-right", ("link-right",))
    sources = (
        source("left", [record("42", G.Capsule(((0, 0, 0),), 1))],
               {"42": left}, transform(IDENTITY, left)),
        source("right", [record("42", G.Capsule(((0, 0, 0),), 1))],
               {"42": right}, transform(IDENTITY, right)),
    )
    result = federate_hulls(sources, federation_root=ROOT)
    assert result.census.transformed == 2
    assert {row.source_id for row in result.records} == {left.key, right.key}
    assert all(row.extra["federation"]["local_source_id"] == "42"
               for row in result.records)


def test_same_definition_in_two_link_instances_is_two_occurrences() -> None:
    definition = DefinitionIdentity(DocumentIdentity("shared-doc"), "element")
    first = OccurrenceIdentity(ROOT, ("instance-A",), definition)
    second = OccurrenceIdentity(ROOT, ("instance-B",), definition)
    result = federate_hulls((
        source("A", [record("1", G.Capsule(((0, 0, 0),), 1))],
               {"1": first}, transform(IDENTITY, first)),
        source("B", [record("1", G.Capsule(((0, 0, 0),), 1))],
               {"1": second}, transform(IDENTITY, second)),
    ), federation_root=ROOT)
    assert first.definition.key == second.definition.key
    assert first.key != second.key
    assert {row.source_id for row in result.records} == {first.key, second.key}


def test_valid_transform_replay_between_link_instances_is_refused() -> None:
    first = occurrence("shared-doc", "element-a", ("instance-A",))
    second = occurrence("shared-doc", "element-b", ("instance-B",))
    first_transform = transform((
        1, 0, 0, 100,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), first)
    second_transform = transform((
        1, 0, 0, 900,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), second)
    # Both matrices are valid isometries. Swapping them must still fail because
    # the digest subject is the exact occurrence chain, not only matrix bytes.
    result = federate_hulls((
        source("A", [record("1", G.Capsule(((0, 0, 0),), 1))],
               {"1": first}, second_transform.to_dict()),
        source("B", [record("1", G.Capsule(((0, 0, 0),), 1))],
               {"1": second}, first_transform.to_dict()),
    ), federation_root=ROOT)
    assert result.census.as_dict() == {"input": 2, "transformed": 0, "gaps": 2}
    assert {gap.reason for gap in result.gaps} == {
        FederationGeometryGapReason.TRANSFORM_SUBJECT_MISMATCH}


def test_one_source_cannot_mix_occurrence_chains_or_leave_unaccounted_keys() -> None:
    first = occurrence("shared-doc", "a", ("instance-A",))
    second = occurrence("shared-doc", "b", ("instance-B",))
    rows = [record("1", G.Capsule(((0, 0, 0),), 1)),
            record("2", G.Capsule(((0, 0, 0),), 1))]
    with pytest.raises(ValueError, match="mix document/root/link chains"):
        source("mixed", rows, {"1": first, "2": second},
               transform(IDENTITY, first))
    with pytest.raises(ValueError, match="exactly account"):
        source("extra", rows[:1], {"1": first, "ghost": first},
               transform(IDENTITY, first))
    with pytest.raises(ValueError, match="duplicate local source ids"):
        source("duplicate", [rows[0], rows[0]], {"1": first},
               transform(IDENTITY, first))


def test_parent_source_target_is_accepted_only_for_a_direct_link() -> None:
    direct = occurrence("linked-doc", "element", ("direct-instance",))
    parent_transform = transform(
        IDENTITY, direct, target_frame="parent_source")
    accepted = federate_hulls((source(
        "direct", [record("1", G.Capsule(((0, 0, 0),), 1))],
        {"1": direct}, parent_transform),), federation_root=ROOT)
    assert accepted.census.transformed == 1

    root = occurrence("root-doc", "root-element", ())
    root_parent = transform(IDENTITY, root, target_frame="parent_source")
    refused = federate_hulls((source(
        "root", [record("1", G.Capsule(((0, 0, 0),), 1))],
        {"1": root}, root_parent),), federation_root=ROOT)
    assert refused.gaps[0].reason is (
        FederationGeometryGapReason.TRANSFORM_TARGET_MISMATCH)


def test_missing_invalid_nested_and_duplicate_inputs_are_exactly_gapped() -> None:
    missing_transform = occurrence("doc-a", "a")
    invalid_transform = occurrence("doc-b", "b", ("link-b",))
    nested = occurrence("doc-c", "c", ("link-c", "nested-c"))
    duplicate = occurrence("doc-d", "d", ("link-d",))
    malformed = transform(IDENTITY, invalid_transform).to_dict()
    malformed["matrix"][0] = 2.0
    rows = (
        source("missing", [record("1", G.Capsule(((0, 0, 0),), 1))],
               {"1": missing_transform}, None),
        source("invalid", [record("2", G.Capsule(((0, 0, 0),), 1))],
               {"2": invalid_transform}, malformed),
        source("nested", [record("3", G.Capsule(((0, 0, 0),), 1))],
               {"3": nested}, transform(IDENTITY, nested)),
        source("dup-a", [record("4", G.Capsule(((0, 0, 0),), 1))],
               {"4": duplicate}, transform(IDENTITY, duplicate)),
        source("dup-b", [record("5", G.Capsule(((0, 0, 0),), 1))],
               {"5": duplicate}, transform(IDENTITY, duplicate)),
    )
    result = federate_hulls(rows, federation_root=ROOT)
    assert result.census.as_dict() == {"input": 5, "transformed": 0, "gaps": 5}
    reasons = [gap.reason for gap in result.gaps]
    assert FederationGeometryGapReason.MISSING_TRANSFORM in reasons
    assert FederationGeometryGapReason.INVALID_TRANSFORM in reasons
    assert FederationGeometryGapReason.NESTED_LINK_CHAIN_NOT_EXTRACTED in reasons
    assert reasons.count(FederationGeometryGapReason.DUPLICATE_OCCURRENCE_KEY) == 2


def test_root_non_identity_transform_is_a_gap() -> None:
    root_occurrence = occurrence("root-doc", "root-element", ())
    translated = transform((
        1, 0, 0, 1,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), root_occurrence)
    result = federate_hulls((source(
        "root", [record("1", G.Capsule(((0, 0, 0),), 1))],
        {"1": root_occurrence}, translated),), federation_root=ROOT)
    assert result.gaps[0].reason is (
        FederationGeometryGapReason.ROOT_TRANSFORM_NOT_IDENTITY)


def test_root_near_identity_is_not_applied_as_a_hidden_shift() -> None:
    root_occurrence = occurrence("root-doc", "root-element", ())
    shifted = transform((
        1, 0, 0, 1e-10,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), root_occurrence)
    result = federate_hulls((source(
        "root", [record("1", G.Capsule(((0, 0, 0),), 1))],
        {"1": root_occurrence}, shifted),), federation_root=ROOT)
    assert result.census.as_dict() == {"input": 1, "transformed": 0, "gaps": 1}
    assert result.gaps[0].reason is (
        FederationGeometryGapReason.ROOT_TRANSFORM_NOT_IDENTITY)


def test_inner_certificate_is_dropped_and_named_not_replayed() -> None:
    outer = G.Aabb((0, 0, 0), (10, 10, 10))
    body = G.Aabb((1, 1, 1), (9, 9, 9))
    inner = G.Aabb((2, 2, 2), (8, 8, 8))
    evidence = H.certify_analytic_inner_for_test(
        inner=inner, body=body, outer=outer, subject_source_id="1",
        body_source_digest=H.analytic_hull_digest(body),
        body_source_revision="fixture-body-r1")
    occ = occurrence("root-doc", "element", ())
    result = federate_hulls((source(
        "root", [record("1", outer, inner=evidence)], {"1": occ},
        transform(IDENTITY, occ)),), federation_root=ROOT)
    assert result.records[0].inner is None
    assert result.records[0].extra["federation"]["proof_gaps"] == [
        FEDERATION_PROOF_GAP]


def test_local_level_ids_are_never_joinable_after_federation() -> None:
    # Both documents legitimately use local level id "7" at unrelated
    # elevations.  The transformed hull carries provenance but no executable
    # level_id that resolve._level_band could join to the root level table.
    left = occurrence("doc-left", "left", ("instance-left",))
    right = occurrence("doc-right", "right", ("instance-right",))
    rows = []
    for name, occ, z in (("left", left, 0), ("right", right, 9000)):
        rec = record("1", G.Capsule(((0, 0, z),), 1))
        rec.level_id = "7"
        rows.append(source(name, [rec], {"1": occ}, transform(IDENTITY, occ)))
    result = federate_hulls(rows, federation_root=ROOT)
    assert result.census.transformed == 2
    for federated in result.records:
        assert federated.level_id is None
        metadata = federated.extra["federation"]
        assert metadata["local_level_id"] == "7"
        assert FEDERATION_LEVEL_GAP in metadata["proof_gaps"]


def test_non_json_metadata_and_overflow_are_balanced_per_record_gaps() -> None:
    invalid = occurrence("doc-invalid", "invalid", ("instance-invalid",))
    overflow = occurrence("doc-overflow", "overflow", ("instance-overflow",))
    malformed = occurrence("doc-malformed", "malformed", ("instance-malformed",))
    valid = occurrence("doc-valid", "valid", ("instance-valid",))
    bad_extra = record("1", G.Capsule(((0, 0, 0),), 1))
    bad_extra.extra = {"not_finite": float("nan")}
    huge_transform = transform((
        1, 0, 0, 1e308,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ), overflow)
    result = federate_hulls((
        source("invalid", [bad_extra], {"1": invalid},
               transform(IDENTITY, invalid)),
        source("overflow", [record(
            "2", G.Capsule(((1e308, 0, 0),), 1))],
            {"2": overflow}, huge_transform),
        source("malformed", [record(
            "4", G.Aabb((0,), (1,)))],  # type: ignore[arg-type]
            {"4": malformed}, transform(IDENTITY, malformed)),
        source("valid", [record("3", G.Capsule(((0, 0, 0),), 1))],
               {"3": valid}, transform(IDENTITY, valid)),
    ), federation_root=ROOT)
    assert result.census.as_dict() == {"input": 4, "transformed": 1, "gaps": 3}
    assert {gap.reason for gap in result.gaps} == {
        FederationGeometryGapReason.INVALID_RECORD_METADATA,
        FederationGeometryGapReason.UNTRANSFORMABLE_HULL,
    }


def test_transformed_geometry_normalizes_negative_zero() -> None:
    matrix = transform(IDENTITY)
    hull, exact = transform_hull(
        G.Capsule(((-0.0, 0.0, -0.0),), -0.0), matrix)
    assert exact and isinstance(hull, G.Capsule)
    assert all(math.copysign(1.0, value) == 1.0 for value in hull.path[0])
    assert math.copysign(1.0, hull.radius) == 1.0


def test_serialization_and_digest_are_deterministic_across_source_order() -> None:
    a = occurrence("doc-a", "a", ("instance-a",))
    b = occurrence("doc-b", "b", ("instance-b",))
    left = source("a", [record("1", G.Capsule(((1, 2, 3),), 4))],
                  {"1": a}, transform(IDENTITY, a))
    right = source("b", [record("1", G.Capsule(((4, 5, 6),), 7))],
                   {"1": b}, transform(IDENTITY, b))
    first = federate_hulls((left, right), federation_root=ROOT)
    second = federate_hulls((right, left), federation_root=ROOT)
    assert first.content_digest == second.content_digest
    assert first.as_dict() == second.as_dict()


def test_federated_content_cannot_mutate_before_query_or_serialization() -> None:
    """The digest must remain the exact payload consumed by clash search."""

    a = occurrence("doc-a", "a", ("instance-a",))
    b = occurrence("doc-b", "b", ("instance-b",))
    left = source("a", [record(
        "1", G.Aabb((0, 0, 0), (10, 10, 10)))],
        {"1": a}, transform(IDENTITY, a))
    right = source("b", [record(
        "1", G.Aabb((5, 0, 0), (15, 10, 10)))],
        {"1": b}, transform(IDENTITY, b))
    result = federate_hulls((left, right), federation_root=ROOT)
    canonical = result.as_dict()
    row = result.records[0]

    with pytest.raises(TypeError, match="immutable"):
        row.hull = G.Aabb((100, 100, 100), (110, 110, 110))
    with pytest.raises(TypeError, match="immutable"):
        row.extra["forged"] = True
    with pytest.raises(TypeError, match="immutable"):
        row.extra["federation"]["proof_gaps"].append("forged")

    assert result.as_dict() == canonical
    grid = D.build_grid(list(result.records))
    assert D.candidate_pairs(
        list(result.records), grid,
        pair_filter=D.any_physical_pair_filter) == [(0, 1)]
