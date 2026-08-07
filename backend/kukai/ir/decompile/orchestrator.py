"""Single offline entry point for the composed DECOMPILE pipeline.

The read-side extractors run before this module.  Their parsed products enter
here as a frozen-L0 :class:`L0Document` and optional side indexes; no bridge,
Revit process, or emitted C# is involved.  Offline and live orchestration both
cross the same ``cached_lift_document_detailed`` boundary.  The offline path
keeps its default cache-disabled behaviour while preserving the exact lift
input contract used by the live path.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kukai.ir.decompile.dependencies import (
    DependencyManifest,
    TargetContract,
    build_dependency_manifest,
)
from kukai.ir.decompile.fold import TreeNode, fold_document
from kukai.ir.decompile.geom_extract import GeometryExtraction
from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    parse_family_placement_index,
)
from kukai.ir.decompile.group_extract import GroupExtraction, parse_group_index
from kukai.ir.decompile.l1_schema import L1Node
from kukai.ir.decompile.lift_cache import cached_lift_document_detailed
from kukai.ir.decompile.name import NameResult, name_document
from kukai.ir.decompile.honesty import (
    BuildStatuses,
    EquivalenceClaim,
    EquivalenceScope,
)
from kukai.ir.decompile.passport import Passport, build_passport
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.verify import VerifyResult, verify_document


@dataclass(frozen=True, slots=True)
class DecompileResult:
    """Materialized output of every offline DECOMPILE stage.

    ``passport`` is the final serving artifact.  The intermediate values stay
    available for audits and exact leaf-preservation checks, while
    ``failed_count`` and ``metrics`` are direct views of VERIFY and therefore
    can never soften or hide a failed verdict.

    When a complete :class:`GeometryExtraction` (or its persisted bundle) is
    supplied, Tier-G definitions are joined into ``passport``.  The direct
    element index remains available separately for audits and compatibility.
    """

    passport: Passport
    verify_result: VerifyResult
    l1_nodes: tuple[L1Node, ...]
    tree: TreeNode
    name_result: NameResult
    geometry_index: dict[str, Any] | None = None
    # Appended after the original fields so legacy positional construction
    # still treats argument six as geometry_index.
    dependency_manifest: DependencyManifest | None = None
    build_status: BuildStatuses | None = None
    equivalence: EquivalenceClaim | None = None
    family_placement_index: dict[str, Any] | None = None
    group_index: dict[str, Any] | None = None

    @property
    def failed_count(self) -> int:
        """Return VERIFY's honest failed-verdict count."""

        return self.verify_result.summary.failed_count

    @property
    def metrics(self) -> dict[str, int | float]:
        """Return legacy §8.4 metrics plus additive fidelity metrics."""

        return {
            **self.verify_result.summary.to_dict(),
            **self.verify_result.fidelity_summary.to_dict(),
        }

    @property
    def verify(self) -> VerifyResult:
        """Short pipeline-oriented alias for :attr:`verify_result`."""

        return self.verify_result

    def to_dict(self) -> dict[str, Any]:
        """Return the final Passport, VERIFY facts, and Tier-G side index."""

        result = {
            "passport": self.passport.to_dict(),
            "verify": self.verify_result.to_dict(),
            "metrics": self.metrics,
            "failed_count": self.failed_count,
            "dependencies": (
                self.dependency_manifest.to_dict()
                if self.dependency_manifest is not None else None
            ),
            "build_status": (
                self.build_status.to_dict()
                if self.build_status is not None else None
            ),
            "equivalence": (
                self.equivalence.to_dict()
                if self.equivalence is not None else None
            ),
            "geometry_index": copy.deepcopy(self.geometry_index),
        }
        # Optional R1 side indexes are omitted, rather than serialized as new
        # null keys, so no-index DecompileResult JSON remains byte-compatible.
        if self.family_placement_index is not None:
            result["family_placement_index"] = copy.deepcopy(
                self.family_placement_index)
        if self.group_index is not None:
            result["group_index"] = copy.deepcopy(self.group_index)
        return result


def _snapshot_geometry_index(
    document: L0Document,
    geometry_index: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if geometry_index is None:
        return None
    if not isinstance(geometry_index, Mapping):
        raise TypeError("geometry_index must be an element-id mapping or None")
    if any(not isinstance(element_id, str) for element_id in geometry_index):
        raise TypeError("geometry_index keys must be element-id strings")
    source_ids = {element.element_id for element in document.elements}
    foreign_ids = sorted(set(geometry_index) - source_ids)
    if foreign_ids:
        raise ValueError(
            "geometry_index contains ids absent from L0: "
            + ", ".join(foreign_ids[:5]))
    return {
        element_id: copy.deepcopy(geometry_index[element_id])
        for element_id in sorted(geometry_index)
    }


def _geometry_inputs(
    document: L0Document,
    geometry: GeometryExtraction | Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, GeometryExtraction | Mapping[str, Any] | None]:
    if geometry is None:
        return None, None
    if isinstance(geometry, GeometryExtraction):
        return (
            _snapshot_geometry_index(document, geometry.geometry_index),
            geometry,
        )
    if not isinstance(geometry, Mapping):
        raise TypeError(
            "geometry_index must be a GeometryExtraction, mapping, or None")

    bundle_fields = {"geometry_index", "geometry_store", "nodes"}
    present_bundle_fields = bundle_fields & set(geometry)
    if present_bundle_fields:
        missing = sorted(bundle_fields - set(geometry))
        if missing:
            raise TypeError(
                "geometry bundle is missing: " + ", ".join(missing))
        raw_index = geometry.get("geometry_index")
        if not isinstance(raw_index, Mapping):
            raise TypeError("geometry.geometry_index must be a mapping")
        return _snapshot_geometry_index(document, raw_index), geometry

    # An index-only legacy input has no definitions to resolve. Retain it on
    # DecompileResult, but do not fabricate an incomplete Passport section.
    return _snapshot_geometry_index(document, geometry), None


def decompile(
    document: L0Document,
    *,
    geometry_index: GeometryExtraction | Mapping[str, Any] | None = None,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: Any = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    mep_system_index: Any = None,
    group_index: GroupExtraction | Mapping[str, Any] | None = None,
    target_contract: TargetContract | str = TargetContract.SAME_ENVIRONMENT,
    equivalence_scope: EquivalenceScope | str = EquivalenceScope.NATIVE_SEMANTIC,
) -> DecompileResult:
    """Run LIFT → FOLD → NAME → VERIFY → Passport entirely offline."""

    retained_geometry, passport_geometry = _geometry_inputs(
        document, geometry_index)
    retained_placements = (
        None if family_placement_index is None
        else parse_family_placement_index(family_placement_index)
    )
    retained_groups = parse_group_index(group_index)
    lift_result = cached_lift_document_detailed(
        document,
        profile_index=profile_index,
        family_placement_index=retained_placements,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        mep_system_index=mep_system_index,
    )
    l1_nodes = lift_result.nodes
    tree = fold_document(
        document,
        l1_nodes,
        group_index=retained_groups,
    )
    name_result = name_document(document, tree)
    dependency_manifest = build_dependency_manifest(
        document, target_contract=target_contract)
    build_status = BuildStatuses.initial(
        unresolved_dependencies=dependency_manifest.unresolved_count)
    equivalence = EquivalenceClaim.unverified(equivalence_scope)
    verify_result = verify_document(
        document,
        tree,
        l1_nodes,
        dependency_manifest=dependency_manifest,
    )
    passport = build_passport(
        document,
        tree,
        name_result,
        verify_result,
        geometry=passport_geometry,
        dependencies=dependency_manifest,
        build_status=build_status,
        equivalence=equivalence,
        group_index=retained_groups,
    )
    return DecompileResult(
        passport=passport,
        verify_result=verify_result,
        l1_nodes=l1_nodes,
        tree=tree,
        name_result=name_result,
        geometry_index=retained_geometry,
        dependency_manifest=dependency_manifest,
        build_status=build_status,
        equivalence=equivalence,
        family_placement_index=retained_placements,
        group_index=retained_groups,
    )


__all__ = ["DecompileResult", "decompile"]
