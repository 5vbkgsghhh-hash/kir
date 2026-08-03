"""Offline, deterministic verification for the DECOMPILE round trip.

VERIFY proves two deliberately bounded claims:

* every representable L1 op point agrees with the corresponding frozen L0
  point geometry within :data:`VERIFY_TOL_MM`; and
* expanding the folded L3 tree preserves the exact L1 leaf multiset, including
  every full payload.

It does *not* prove that FOLD chose the semantically correct structure.  For a
model without a reference program, labels such as ``apartment`` are measured
inferences, not proven facts.  It also cannot prove geometry absent from the
frozen L0 contract: bbox-only sources and atoms are approximate, and curve
verification covers the stored endpoints rather than an unavailable line/arc
kind.  No bridge, Revit process, or forward rebuild is used.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence, TypeAlias

from kukai.ir.decompile.dependencies import DependencyManifest
from kukai.ir.decompile.fold import TreeNode, iter_l1_leaves
from kukai.ir.decompile.honesty import (
    FidelityAssessment,
    FidelitySummary,
    SourceReason,
)
from kukai.ir.decompile.l1_schema import (
    AtomReason,
    FidelityReason,
    FidelityVerdict,
    L1Node,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    VERIFY_TOL,
)


VERIFY_TOL_MM = float(VERIFY_TOL)

VerdictStatus: TypeAlias = Literal["exact", "approximate", "failed"]
_Point: TypeAlias = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class NodeVerdict:
    """Verification outcome for one L1 leaf expanded from the actual tree."""

    node_id: str
    source_element_id: str
    status: VerdictStatus
    detail: str
    max_deviation_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""

        return {
            "node_id": self.node_id,
            "source_element_id": self.source_element_id,
            "status": self.status,
            "detail": self.detail,
            "max_deviation_mm": self.max_deviation_mm,
        }


@dataclass(frozen=True, slots=True)
class VerifySummary:
    """Aggregate VERIFY counters from Part 8.4.

    Percentages are in the inclusive range 0..100.  ``exact_pct`` and
    ``approximate_pct`` use every expanded leaf as their denominator;
    ``point_geometry_passthrough_pct`` uses only op leaves.
    ``compression_ratio`` is the count of every L3 ``TreeNode`` divided by
    expanded leaves.

    Read ``point_geometry_passthrough_pct`` narrowly.  It compares
    :func:`_predicted_points` — which reads ``params["p0_mm"]/["p1_mm"]`` off
    the lifted L1 node — against :func:`_actual_points`, which reads
    ``element.p0_mm/.p1_mm`` off the L0 source.  LIFT copies the latter into
    the former verbatim, so for every curve op (wall, beam, pipe, duct, tray,
    axis, stair) the deviation is 0.0 *by construction*.  The number therefore
    measures "share of ops whose endpoint coordinates survived LIFT", NOT
    "share of the building that is reproduced" — there is no round trip in it.

    Explicitly NOT covered by this metric: mid-curve geometry (an arc and its
    chord share both endpoints), floor/roof outlines, heights, offsets, flips,
    sills, level bindings, and types.  Fidelity of the rebuilt building is a
    different question, answered by ``fidelity_summary``, not by this field.
    """

    total_leaves: int
    op_count: int
    atom_count: int
    exact: int
    approximate: int
    failed: int
    exact_pct: float
    approximate_pct: float
    failed_count: int
    lift_coverage: float
    point_geometry_passthrough_pct: float
    compression_ratio: float

    def to_dict(self) -> dict[str, int | float]:
        """Return a JSON-ready representation."""

        return {
            "total_leaves": self.total_leaves,
            "op_count": self.op_count,
            "atom_count": self.atom_count,
            "exact": self.exact,
            "approximate": self.approximate,
            "failed": self.failed,
            "exact_pct": self.exact_pct,
            "approximate_pct": self.approximate_pct,
            "failed_count": self.failed_count,
            "lift_coverage": self.lift_coverage,
            "point_geometry_passthrough_pct": (
                self.point_geometry_passthrough_pct),
            "compression_ratio": self.compression_ratio,
        }


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Pure VERIFY output; the frozen input L3 tree is never mutated.

    ``to_dict`` is the explicit serialization boundary.  The dataclass itself
    remains immutable while its returned representation can be passed directly
    to :func:`json.dumps`.
    """

    reversible: bool
    reversibility_detail: str
    summary: VerifySummary
    verdicts: tuple[NodeVerdict, ...]
    fidelity_summary: FidelitySummary = field(
        default_factory=lambda: FidelitySummary.from_assessments(()))
    fidelity_verdicts: tuple[FidelityAssessment, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the complete result as finite JSON-ready data."""

        return {
            "reversible": self.reversible,
            "reversibility_detail": self.reversibility_detail,
            "summary": self.summary.to_dict(),
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
            "fidelity_summary": self.fidelity_summary.to_dict(),
            "fidelity_verdicts": [
                verdict.to_dict() for verdict in self.fidelity_verdicts],
        }


def _payloads_by_id(
    nodes: Sequence[L1Node],
) -> dict[str, list[L1Node]]:
    grouped: dict[str, list[L1Node]] = defaultdict(list)
    for node in nodes:
        grouped[node["_id"]].append(node)
    return grouped


def _same_payload_multiset(
    expected: Sequence[L1Node],
    expanded: Sequence[L1Node],
) -> bool:
    """Compare full mappings with the equality used by FOLD preservation.

    Frozen L1 normally makes every ``_id`` unique, so each sequence contains
    one item.  The small multiset matcher also handles a corrupted tree with
    duplicate ids without allocating serialized copies of every payload.
    """

    if len(expected) != len(expanded):
        return False
    remaining = list(expanded)
    for expected_node in expected:
        match = next((
            index for index, expanded_node in enumerate(remaining)
            if expected_node == expanded_node
        ), None)
        if match is None:
            return False
        remaining.pop(match)
    return not remaining


def _render_counts(counter: Counter[str], *, limit: int = 8) -> str:
    entries = sorted(counter.items())
    rendered = [
        node_id if count == 1 else f"{node_id} x{count}"
        for node_id, count in entries[:limit]
    ]
    if len(entries) > limit:
        rendered.append(f"... +{len(entries) - limit} ids")
    return ", ".join(rendered)


def _render_ids(values: Sequence[str], *, limit: int = 8) -> str:
    rendered = list(values[:limit])
    if len(values) > limit:
        rendered.append(f"... +{len(values) - limit} ids")
    return ", ".join(rendered)


def _check_reversibility(
    expected: Sequence[L1Node],
    expanded: Sequence[L1Node],
) -> tuple[bool, str]:
    expected_ids = Counter(node["_id"] for node in expected)
    expanded_ids = Counter(node["_id"] for node in expanded)
    expected_payloads = _payloads_by_id(expected)
    expanded_payloads = _payloads_by_id(expanded)
    payload_mismatches = sorted(
        node_id
        for node_id in expected_ids.keys() & expanded_ids.keys()
        if not _same_payload_multiset(
            expected_payloads[node_id], expanded_payloads[node_id])
    )

    reversible = (
        expected_ids == expanded_ids
        and not payload_mismatches
    )
    if reversible:
        return (
            True,
            "expanded L3 leaves exactly match the input L1 multiset "
            "by _id and full payload",
        )

    parts: list[str] = []
    missing = expected_ids - expanded_ids
    added = expanded_ids - expected_ids
    if missing:
        parts.append(f"missing _id(s): {_render_counts(missing)}")
    if added:
        parts.append(f"added _id(s): {_render_counts(added)}")
    if payload_mismatches:
        parts.append(
            "payload mismatch for _id(s): "
            f"{_render_ids(payload_mismatches)}")
    return False, "expanded L3 differs from input L1: " + "; ".join(parts)


def _point(value: Any) -> _Point | None:
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        return None
    if any(
        isinstance(component, bool)
        or not isinstance(component, (int, float))
        or not math.isfinite(float(component))
        for component in value
    ):
        return None
    return tuple(float(component) for component in value)


def _predicted_points(node: L1Node) -> tuple[_Point, ...] | None:
    # "Predicted" overstates it: ``p0_mm``/``p1_mm`` were copied into params by
    # LIFT straight from the L0 element that :func:`_actual_points` reads back,
    # so the two agree by construction for curve ops.  This drives
    # ``point_geometry_passthrough_pct`` — endpoint survival, never fidelity.
    if node["kind"] != "op":
        return None
    params = node["params"]
    if "p0_mm" in params and "p1_mm" in params:
        p0 = _point(params["p0_mm"])
        p1 = _point(params["p1_mm"])
        return None if p0 is None or p1 is None else (p0, p1)
    if "xy" in params:
        xy = _point(params["xy"])
        return None if xy is None else (xy,)
    anchor = _point(node["anchor_mm"])
    return None if anchor is None else (anchor,)


def _actual_points(element: L0Element) -> tuple[_Point, ...] | None:
    if element.geom_kind is GeometryKind.CURVE:
        if element.p0_mm is None or element.p1_mm is None:
            return None
        return (tuple(element.p0_mm), tuple(element.p1_mm))
    if element.geom_kind is GeometryKind.POINT:
        if element.p0_mm is None:
            return None
        return (tuple(element.p0_mm),)
    return None


def _node_verdict(
    node: L1Node,
    l0_by_source_id: Mapping[str, L0Element],
) -> NodeVerdict:
    node_id = node["_id"]
    source_id = node["source_element_id"]
    if node["kind"] == "atom":
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="approximate",
            detail=(
                "atom leaf is not geometrically interpretable; its bbox and "
                "provenance remain measured facts"
            ),
        )

    predicted = _predicted_points(node)
    if predicted is None:
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="approximate",
            detail=(
                "op has no interpretable p0/p1, xy, or anchor point geometry"
            ),
        )

    source = l0_by_source_id.get(source_id)
    if source is None:
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="approximate",
            detail="no matching L0 element exists for this source id",
        )
    actual = _actual_points(source)
    if actual is None:
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="approximate",
            detail=(
                "matching L0 source has bbox-only geometry, so point geometry "
                "cannot be verified"
            ),
        )

    if len(predicted) != len(actual):
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="failed",
            detail=(
                "predicted/actual point-count mismatch: "
                f"{len(predicted)} != {len(actual)}"
            ),
        )

    deviations: list[float] = []
    for predicted_point, actual_point in zip(predicted, actual):
        dimensions = min(len(predicted_point), len(actual_point))
        if dimensions == 0:
            return NodeVerdict(
                node_id=node_id,
                source_element_id=source_id,
                status="approximate",
                detail="predicted and actual points have no common dimensions",
            )
        deviations.append(math.dist(
            predicted_point[:dimensions], actual_point[:dimensions]))
    max_deviation = max(deviations)
    if max_deviation <= VERIFY_TOL_MM:
        return NodeVerdict(
            node_id=node_id,
            source_element_id=source_id,
            status="exact",
            detail=(
                "representable point geometry matches L0 within "
                f"{VERIFY_TOL_MM:.3f} mm; maximum deviation "
                f"{max_deviation:.3f} mm"
            ),
            max_deviation_mm=max_deviation,
        )
    return NodeVerdict(
        node_id=node_id,
        source_element_id=source_id,
        status="failed",
        detail=(
            f"maximum deviation {max_deviation:.3f} mm exceeds "
            f"VERIFY tolerance {VERIFY_TOL_MM:.3f} mm"
        ),
        max_deviation_mm=max_deviation,
    )


_FAMILY_STATE_OPS = frozenset({
    "create_beam",
    "create_column",
    "create_door",
    "create_window",
    # Reserved for the ratified R1 wave.  STEP-0 does not add this op.
    "place_family",
})


def _unique_reasons(
    reasons: Sequence[FidelityReason],
) -> tuple[FidelityReason, ...]:
    result: list[FidelityReason] = []
    seen: set[FidelityReason] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        result.append(reason)
    return tuple(result)


def _fidelity_assessment(
    node: L1Node,
    legacy: NodeVerdict | None,
    *,
    dependency_resolved: bool,
) -> FidelityAssessment:
    """Map current evidence onto the stricter scale without upgrading it.

    Legacy ``exact`` only proves agreement of the point geometry represented
    in frozen L0.  It therefore maps to ``approximate``: neither dependency
    fingerprints nor all required native instance-state fields have been
    verified.
    """

    node_id = node["_id"]
    source_id = node["source_element_id"]
    legacy_status = legacy.status if legacy is not None else "unknown"
    dependency_reason = (
        () if dependency_resolved
        else (FidelityReason.DEPENDENCY_UNRESOLVED,)
    )

    if node["kind"] == "atom":
        raw_reason = node["reason"]
        source_reason = SourceReason(
            code=AtomReason(raw_reason["code"]),
            detail=raw_reason["detail"],
        )
        typed_source_reason = FidelityReason(source_reason.code.value)
        if source_reason.code is AtomReason.GENERATOR_CHILD:
            verdict = FidelityVerdict.GENERATED_ACCOUNTED
            detail = (
                "source leaf is explicitly accounted as generator-owned; "
                "it is not claimed as an independently reconstructable op"
            )
        else:
            verdict = FidelityVerdict.OPAQUE
            detail = (
                "opaque L1 atom preserves its measured payload and typed "
                "LIFT refusal without claiming reconstructability"
            )
        return FidelityAssessment(
            node_id=node_id,
            source_element_id=source_id,
            verdict=verdict,
            reasons=_unique_reasons((
                typed_source_reason,
                *dependency_reason,
            )),
            detail=detail,
            dependency_resolved=dependency_resolved,
            legacy_verify_status=legacy_status,
            source_reason=source_reason,
        )

    reasons: list[FidelityReason] = [
        FidelityReason.LEGACY_VERIFY_SCOPE_LIMITED,
    ]
    if legacy_status == "approximate":
        reasons.append(FidelityReason.GEOMETRY_EVIDENCE_INCOMPLETE)
    elif legacy_status == "failed":
        reasons.append(FidelityReason.VERIFICATION_FAILED)
    elif legacy_status == "unknown":
        reasons.append(FidelityReason.VERIFICATION_EVIDENCE_MISSING)

    op_name = node["op_name"]
    if op_name in _FAMILY_STATE_OPS and op_name != "place_family":
        reasons.extend((
            FidelityReason.FLIP_STATE_UNKNOWN,
            FidelityReason.INSTANCE_PARAMS_INCOMPLETE,
        ))
    if op_name == "place_family":
        params = node["params"]
        state_fields = {
            "rotation_deg", "mirrored", "hand_flipped", "facing_flipped",
        }
        symbol = params.get("symbol")
        # R1-A side-index-backed ops make placement kind and all three state
        # bits explicit.  They remain approximate because L0 1.0 has neither
        # a complete instance-parameter snapshot nor dependency fingerprints.
        if not state_fields <= set(params):
            reasons.append(FidelityReason.FLIP_STATE_UNKNOWN)
        if (not isinstance(symbol, dict)
                or symbol.get("by") != "family_type"):
            reasons.append(FidelityReason.PLACEMENT_KIND_UNKNOWN)
        reasons.append(FidelityReason.INSTANCE_PARAMS_INCOMPLETE)
    if (op_name == "create_foundation"
            and node["params"].get("variety") == "point"):
        reasons.extend((
            FidelityReason.FLIP_STATE_UNKNOWN,
            FidelityReason.INSTANCE_PARAMS_INCOMPLETE,
        ))
    reasons.extend(dependency_reason)
    return FidelityAssessment(
        node_id=node_id,
        source_element_id=source_id,
        verdict=FidelityVerdict.APPROXIMATE,
        reasons=_unique_reasons(reasons),
        detail=(
            "legacy VERIFY status "
            f"{legacy_status!r} is bounded to available offline geometry; "
            "current L0 1.0 lacks the dependency fingerprints and required "
            "native-state fields needed for native_exact"
        ),
        dependency_resolved=dependency_resolved,
        legacy_verify_status=legacy_status,
    )


def _percentage(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator * 100.0


def _tree_node_count(root: TreeNode) -> int:
    count = 0
    stack = [root]
    while stack:
        node = stack.pop()
        count += 1
        stack.extend(node["children"])
    return count


def verify(
    l1_nodes: Sequence[L1Node],
    l3_tree: TreeNode,
    l0_by_source_id: Mapping[str, L0Element],
    *,
    dependency_manifest: DependencyManifest | None = None,
) -> VerifyResult:
    """Verify LIFT point fidelity and exact FOLD reversibility offline.

    Verdicts are computed for leaves contained in ``l3_tree`` even when its
    expansion differs from ``l1_nodes``.  ``exact`` is intentionally limited
    to geometry represented by frozen L0 points; no verdict proves the semantic
    correctness of FOLD's inferred hierarchy.
    """

    expected = tuple(l1_nodes)
    expanded = tuple(iter_l1_leaves(l3_tree))
    reversible, reversibility_detail = _check_reversibility(
        expected, expanded)
    verdicts = tuple(
        _node_verdict(node, l0_by_source_id) for node in expanded)
    legacy_by_node_id = {verdict.node_id: verdict for verdict in verdicts}
    fidelity_verdicts = tuple(
        _fidelity_assessment(
            node,
            legacy_by_node_id.get(node["_id"]),
            dependency_resolved=(
                dependency_manifest.dependency_resolved_for(
                    node["source_element_id"])
                if dependency_manifest is not None else False
            ),
        )
        for node in expanded
    )
    fidelity_summary = FidelitySummary.from_assessments(fidelity_verdicts)

    total = len(expanded)
    op_count = sum(node["kind"] == "op" for node in expanded)
    atom_count = total - op_count
    exact = sum(verdict.status == "exact" for verdict in verdicts)
    approximate = sum(
        verdict.status == "approximate" for verdict in verdicts)
    failed = sum(verdict.status == "failed" for verdict in verdicts)
    summary = VerifySummary(
        total_leaves=total,
        op_count=op_count,
        atom_count=atom_count,
        exact=exact,
        approximate=approximate,
        failed=failed,
        exact_pct=_percentage(exact, total),
        approximate_pct=_percentage(approximate, total),
        failed_count=failed,
        lift_coverage=_percentage(op_count, total),
        # Endpoint passthrough, not fidelity: LIFT copies element.p0_mm/.p1_mm
        # into params, which is exactly what the comparison re-reads.  See the
        # VerifySummary docstring before quoting this number anywhere.
        point_geometry_passthrough_pct=_percentage(exact, op_count),
        compression_ratio=(
            0.0 if total == 0 else _tree_node_count(l3_tree) / total),
    )
    return VerifyResult(
        reversible=reversible,
        reversibility_detail=reversibility_detail,
        summary=summary,
        verdicts=verdicts,
        fidelity_summary=fidelity_summary,
        fidelity_verdicts=fidelity_verdicts,
    )


def verify_document(
    document: L0Document,
    l3_tree: TreeNode,
    l1_nodes: Sequence[L1Node],
    *,
    dependency_manifest: DependencyManifest | None = None,
) -> VerifyResult:
    """Build the source-id index for ``document`` and call :func:`verify`."""

    return verify(
        l1_nodes,
        l3_tree,
        {element.element_id: element for element in document.elements},
        dependency_manifest=dependency_manifest,
    )


__all__ = [
    "FidelityAssessment",
    "FidelitySummary",
    "NodeVerdict",
    "VERIFY_TOL_MM",
    "VerdictStatus",
    "VerifyResult",
    "VerifySummary",
    "verify",
    "verify_document",
]
