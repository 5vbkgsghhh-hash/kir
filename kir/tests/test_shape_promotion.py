"""DirectShape stays honest, and raising the LOD is a separate revision."""
from __future__ import annotations

import pytest

from kir import sdk
from kir.compiler import plan_program
from kir.shape_promotion import (
    PromotionCandidate,
    PromotionEvidence,
    PromotionOutcome,
    PromotionState,
    SHAPE_APPROVAL_SCHEMA,
    SHAPE_READBACK_SCHEMA,
    ShapeIntent,
    ShapePromotionError,
    allowed_native_ops,
)


MESH = {"vertices_mm": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]],
        "triangles": [[0, 1, 2]]}


def _source_plan():
    return plan_program({
        "ir_version": "1.0",
        "ops": [sdk.create_directshape(
            mesh=MESH, category="generic_model", name="Концепт", id="shape1")],
    })


def _wall_plan():
    return plan_program({
        "ir_version": "1.0",
        "ops": [sdk.create_wall(
            [0, 0], [5000, 0], "Этаж 1", height_mm=3000, id="wall1")],
    })


def _native_plan(role: str):
    operations = {
        "walls": sdk.create_wall(
            [0, 0], [5000, 0], "Этаж 1", height_mm=3000, id="native1"),
        "floors": sdk.create_floor(
            [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
            "Этаж 1", id="native1"),
        "roofs": sdk.create_roof(
            [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
            "Этаж 1", id="native1"),
        "columns": sdk.create_column(
            [0, 0], "Этаж 1", id="native1"),
        "structural_columns": sdk.create_column(
            [0, 0], "Этаж 1", id="native1"),
        "structural_framing": sdk.create_beam(
            [0, 0, 0], [5000, 0, 0], "Этаж 1", id="native1"),
        "ceilings": sdk.create_ceiling(
            "Этаж 1",
            outline=[[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
            id="native1"),
        "stairs": sdk.create_stairs(
            "Этаж 1", "Этаж 2", p0_mm=[0, 0], p1_mm=[5000, 0],
            width_mm=1200, id="native1"),
    }
    return plan_program({"ir_version": "1.0", "ops": [operations[role]]})


def _intent(role: str = "walls") -> ShapeIntent:
    return ShapeIntent(
        source_plan=_source_plan(), source_op_id="shape1",
        intended_role=role,
        constraints={"height_mm": 3000, "preserve_openings": True})


def _evidence(
    candidate: PromotionCandidate,
    *,
    ids: tuple[int, ...] = (101,),
    authority_verified: bool = True,
) -> PromotionEvidence:
    return PromotionEvidence(
        candidate=candidate,
        authority_verified=authority_verified,
        approval_record={
            "schema": SHAPE_APPROVAL_SCHEMA,
            "candidate_digest": candidate.digest,
            "decision": "approved",
            "approval_ref": "approval:revision-7",
            "approved_by": "user:42",
        },
        readback_record={
            "schema": SHAPE_READBACK_SCHEMA,
            "candidate_digest": candidate.digest,
            "candidate_plan_digest": candidate.candidate_plan_digest,
            "transaction_status": "Committed",
            "independent": True,
            "document_key": "document:model-A",
            "created": {candidate.candidate_op_ids[0]: list(ids)},
        },
    )


def test_intent_is_bound_to_planned_geometry_and_keeps_role_separate() -> None:
    intent = _intent()
    wire = intent.to_dict()
    assert wire["state"] == "provisional"
    assert wire["source_op_name"] == "create_directshape"
    assert wire["intended_role"] == "walls"
    assert wire["constraints"]["height_mm"] == 3000
    assert len(intent.digest) == 64


def test_role_routes_are_read_from_the_existing_impersonation_authority() -> None:
    assert allowed_native_ops("floors") == (
        "create_floor", "create_floor_by_contour")
    with pytest.raises(ShapePromotionError, match="no native route"):
        allowed_native_ops("looks_like_a_wall")


def test_native_candidate_is_a_separate_non_executing_revision() -> None:
    candidate = PromotionCandidate(
        intent=_intent(), candidate_plan=_wall_plan(),
        candidate_op_ids=("wall1",))
    assert candidate.to_dict() == {
        "schema": "kir-shape-promotion/2",
        "state": "candidate",
        "intent_digest": candidate.intent.digest,
        "candidate_plan_digest": _wall_plan().plan_digest,
        "candidate_op_ids": ["wall1"],
        "candidate_op_names": ["create_wall"],
        "candidate_identity_cardinalities": ["one"],
        "requires_user_approval": True,
    }


def test_candidate_cannot_share_the_source_execution_plan() -> None:
    mixed = plan_program({
        "ir_version": "1.0",
        "ops": [
            sdk.create_directshape(
                mesh=MESH, category="generic_model", name="Концепт",
                id="shape1"),
            sdk.create_wall(
                [0, 0], [5000, 0], "Этаж 1", height_mm=3000,
                id="wall1"),
        ],
    })
    intent = ShapeIntent(
        source_plan=mixed, source_op_id="shape1",
        intended_role="walls")
    with pytest.raises(ShapePromotionError, match="separate planned revision"):
        PromotionCandidate(
            intent=intent, candidate_plan=mixed,
            candidate_op_ids=("wall1",))


def test_candidate_ids_must_cover_the_complete_execution_plan() -> None:
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [
            sdk.create_wall(
                [0, 0], [5000, 0], "Этаж 1", height_mm=3000,
                id="approved"),
            sdk.create_wall(
                [0, 1000], [5000, 1000], "Этаж 1", height_mm=3000,
                id="hidden"),
        ],
    })
    with pytest.raises(ShapePromotionError, match="complete candidate plan"):
        PromotionCandidate(
            intent=_intent(), candidate_plan=plan,
            candidate_op_ids=("approved",))


def test_geometry_cannot_be_presented_as_native_promotion() -> None:
    other_geometry = plan_program({
        "ir_version": "1.0",
        "ops": [sdk.create_directshape(
            mesh=MESH, category="generic_model", name="Другой концепт",
            id="shape2")],
    })
    with pytest.raises(ShapePromotionError, match="cannot promote role"):
        PromotionCandidate(
            intent=_intent(), candidate_plan=other_geometry,
            candidate_op_ids=("shape2",))


def test_wrong_native_role_is_rejected_even_when_op_is_valid() -> None:
    with pytest.raises(ShapePromotionError, match="cannot promote role"):
        PromotionCandidate(
            intent=_intent("roofs"), candidate_plan=_wall_plan(),
            candidate_op_ids=("wall1",))


@pytest.mark.parametrize("role", [
    "walls", "floors", "roofs", "columns", "structural_columns",
    "structural_framing", "ceilings", "stairs",
])
def test_all_declared_native_routes_accept_a_valid_planned_candidate(
        role: str) -> None:
    candidate = PromotionCandidate(
        intent=_intent(role), candidate_plan=_native_plan(role),
        candidate_op_ids=("native1",))
    assert candidate.candidate_op_names[0] in allowed_native_ops(role)


def test_promotion_needs_both_approval_and_readback_binding() -> None:
    candidate = PromotionCandidate(
        intent=_intent(), candidate_plan=_wall_plan(),
        candidate_op_ids=("wall1",))
    with pytest.raises(ShapePromotionError, match="verified promotion evidence"):
        PromotionOutcome(
            state=PromotionState.PROMOTED,
            intent=candidate.intent,
            candidate=candidate)
    with pytest.raises(ShapePromotionError, match="authority"):
        _evidence(candidate, authority_verified=False)
    evidence = _evidence(candidate)
    outcome = PromotionOutcome(
        state=PromotionState.PROMOTED,
        intent=candidate.intent,
        candidate=candidate,
        evidence=evidence)
    wire = outcome.to_dict()
    assert wire["state"] == "promoted"
    assert wire["evidence_digest"] == evidence.digest
    assert wire["document_key"] == "document:model-A"
    assert wire["native_element_ids"] == [101]

    with pytest.raises(ShapePromotionError, match="ONE cardinality"):
        _evidence(candidate, ids=(101, 102))


def test_readback_must_be_independent_committed_and_exactly_bound() -> None:
    candidate = PromotionCandidate(
        intent=_intent(), candidate_plan=_wall_plan(),
        candidate_op_ids=("wall1",))
    base = {
        "schema": SHAPE_READBACK_SCHEMA,
        "candidate_digest": candidate.digest,
        "candidate_plan_digest": candidate.candidate_plan_digest,
        "transaction_status": "Committed",
        "independent": True,
        "document_key": "document:model-A",
        "created": {"wall1": [101]},
    }
    approval = {
        "schema": SHAPE_APPROVAL_SCHEMA,
        "candidate_digest": candidate.digest,
        "decision": "approved",
        "approval_ref": "approval:7",
        "approved_by": "user:42",
    }
    for broken, message in (
        ({**base, "independent": False}, "independent"),
        ({**base, "transaction_status": "RolledBack"}, "committed"),
        ({**base, "candidate_plan_digest": "f" * 64}, "candidate plan"),
        ({**base, "created": {"other": [101]}}, "exactly"),
    ):
        with pytest.raises(ShapePromotionError, match=message):
            PromotionEvidence(
                candidate=candidate,
                approval_record=approval,
                readback_record=broken,
                authority_verified=True)


def test_promotion_cannot_bind_candidate_from_another_intent() -> None:
    candidate = PromotionCandidate(
        intent=_intent(), candidate_plan=_wall_plan(),
        candidate_op_ids=("wall1",))
    other_intent = ShapeIntent(
        source_plan=_source_plan(), source_op_id="shape1",
        intended_role="walls", constraints={"variant": "other"})
    with pytest.raises(ShapePromotionError, match="same shape intent"):
        PromotionOutcome(
            state=PromotionState.PROMOTED,
            intent=other_intent,
            candidate=candidate,
            evidence=_evidence(candidate))


def test_irreducible_shape_remains_residual_without_native_claims() -> None:
    outcome = PromotionOutcome(
        state=PromotionState.RESIDUAL,
        intent=_intent(),
        reason="двоякая криволинейная оболочка не имеет нативного wall route")
    assert outcome.to_dict()["native_element_ids"] == []
    candidate = PromotionCandidate(
        intent=_intent(), candidate_plan=_wall_plan(),
        candidate_op_ids=("wall1",))
    with pytest.raises(ShapePromotionError, match="cannot pretend"):
        PromotionOutcome(
            state=PromotionState.RESIDUAL,
            intent=_intent(),
            candidate=candidate,
            evidence=_evidence(candidate),
            reason="непереводимо")


def test_outcome_refuses_string_that_only_looks_like_typed_state() -> None:
    with pytest.raises(ShapePromotionError, match="PromotionState"):
        PromotionOutcome(
            state="residual",  # type: ignore[arg-type]
            intent=_intent(),
            reason="непереводимо",
        )


def test_source_hash_is_derived_from_the_exact_planned_payload() -> None:
    intent = _intent()
    assert len(intent.source_geometry_hash) == 64
    with pytest.raises(ShapePromotionError, match="disagrees"):
        ShapeIntent(
            source_plan=_source_plan(), source_op_id="shape1",
            intended_role="walls", source_geometry_hash="c" * 64)


@pytest.mark.parametrize("reason", [
    "двоякая криволинейная оболочка не имеет нативного маршрута",
    "топология отверстий неоднозначна",
    "для нативного элемента не хватает типа и конструкции",
    "форма должна остаться концептуальной на текущем LOD",
])
def test_four_irreducible_controls_remain_honest_residuals(reason: str) -> None:
    outcome = PromotionOutcome(
        state=PromotionState.RESIDUAL,
        intent=_intent(),
        reason=reason)
    assert outcome.state is PromotionState.RESIDUAL
    assert outcome.native_element_ids == ()
