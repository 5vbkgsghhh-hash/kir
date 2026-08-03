"""Evidence-bounded group relations derived from the optional side index.

Model-group membership is a relation over canonical L0/L1 leaves, never a
second parent in the FOLD tree.  The raw Revit API order proves an ordinal
inside one instance.  This module projects that ordinal as a reference slot
only when the instance has the reference definition's cardinality; excluded
or otherwise divergent instances retain membership without a guessed slot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TypeAlias

from kukai.ir.decompile.group_extract import (
    GroupExtraction,
    parse_group_index,
)


GroupIndexInput: TypeAlias = GroupExtraction | Mapping[str, Any]


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


@dataclass(frozen=True, slots=True)
class GroupMembershipRelation:
    """One unambiguous direct membership for a represented source leaf."""

    group_instance_id: str
    group_type_id: str
    ordinal: int | None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "group_instance_id": self.group_instance_id,
            "group_type_id": self.group_type_id,
        }
        # A divergent instance is still a real membership, but its member
        # position is not silently equated with the reference definition.
        if self.ordinal is not None:
            result["ordinal"] = self.ordinal
        return result


@dataclass(frozen=True, slots=True)
class GroupTypeProjection:
    """Compact group definition facts needed by the virtual group view."""

    group_type_id: str
    name: str
    reference_instance_id: str
    instance_ids: tuple[str, ...]
    slot_count: int
    mismatch_instance_count: int
    slot_comparison_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reference_instance_id": self.reference_instance_id,
            "slot_count": self.slot_count,
            "instance_count": len(self.instance_ids),
            "instance_ids": list(self.instance_ids),
            "has_composition_mismatch": self.mismatch_instance_count > 0,
            "mismatch_instance_count": self.mismatch_instance_count,
            "slot_comparison_basis": self.slot_comparison_basis,
        }


@dataclass(frozen=True, slots=True)
class GroupRelationsAnalysis:
    """Canonical Passport projection plus FOLD boundary keys."""

    memberships: tuple[tuple[str, GroupMembershipRelation], ...]
    group_types: tuple[GroupTypeProjection, ...]
    boundary_items: tuple[tuple[str, str], ...]
    index_member_occurrences: int
    index_unique_member_ids: int
    absent_from_l0_count: int
    ambiguous_group_claim_count: int

    @property
    def boundary_by_source(self) -> dict[str, str]:
        return dict(self.boundary_items)

    def relations_dict(self) -> dict[str, Any]:
        unmatched = (
            self.absent_from_l0_count
            + self.ambiguous_group_claim_count
        )
        return {
            "group_membership": {
                source_id: relation.to_dict()
                for source_id, relation in self.memberships
            },
            "group_membership_unmatched": {
                "total": unmatched,
                "absent_from_l0_count": self.absent_from_l0_count,
                "ambiguous_group_claim_count": (
                    self.ambiguous_group_claim_count),
                "index_member_occurrences": self.index_member_occurrences,
                "index_unique_member_ids": self.index_unique_member_ids,
                "matched_leaf_count": len(self.memberships),
            },
        }

    def definitions_dict(self) -> dict[str, Any]:
        return {
            "group_types": {
                definition.group_type_id: definition.to_dict()
                for definition in self.group_types
            },
        }


def _as_extraction(value: GroupIndexInput) -> GroupExtraction:
    if isinstance(value, GroupExtraction):
        return value
    canonical = parse_group_index(value)
    if canonical is None:  # pragma: no cover - guarded by the public caller
        raise TypeError("group index unexpectedly normalized to None")
    return GroupExtraction.from_dict(canonical)


def analyze_group_relations(
    value: GroupIndexInput,
    source_element_ids: Sequence[str] | set[str] | frozenset[str],
) -> GroupRelationsAnalysis:
    """Derive membership without inventing L0 leaves or reference slots.

    Cross-instance duplicate member claims are not expected from Revit, but a
    persisted side index can still contain them.  Such a represented source is
    omitted from the singular Passport relation and receives a private FOLD
    boundary, preventing an ambiguous claim from joining any other group.
    """

    source_ids = tuple(source_element_ids)
    if not all(isinstance(source_id, str) and source_id for source_id in source_ids):
        raise TypeError("source_element_ids must contain non-empty strings")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source_element_ids must be unique")
    source_set = set(source_ids)
    extraction = _as_extraction(value)

    mismatches_by_type: dict[str, set[str]] = {}
    for mismatch in extraction.composition_mismatches:
        mismatches_by_type.setdefault(
            mismatch.group_type_id, set()).add(mismatch.instance_id)
    definitions_by_type = {
        definition.group_type_id: definition
        for definition in extraction.definitions
    }
    projections = tuple(
        GroupTypeProjection(
            group_type_id=definition.group_type_id,
            name=definition.group_type_name,
            reference_instance_id=definition.reference_instance_id,
            instance_ids=definition.instance_ids,
            slot_count=len(definition.slots),
            mismatch_instance_count=len(mismatches_by_type.get(
                definition.group_type_id, ())),
            slot_comparison_basis=definition.comparison_basis,
        )
        for definition in extraction.definitions
    )

    claims: dict[str, list[GroupMembershipRelation]] = {}
    occurrences = 0
    for instance in extraction:
        definition = definitions_by_type[instance.group_type_id]
        reference_compatible = (
            instance.element_id not in mismatches_by_type.get(
                instance.group_type_id, ())
            and len(instance.member_ids) == len(definition.slots)
        )
        for ordinal, member_id in enumerate(instance.member_ids):
            occurrences += 1
            claims.setdefault(member_id, []).append(GroupMembershipRelation(
                group_instance_id=instance.element_id,
                group_type_id=instance.group_type_id,
                ordinal=ordinal if reference_compatible else None,
            ))

    memberships: list[tuple[str, GroupMembershipRelation]] = []
    boundary_items: list[tuple[str, str]] = []
    absent = 0
    ambiguous = 0
    for member_id in sorted(claims, key=_element_id_key):
        member_claims = claims[member_id]
        if member_id not in source_set:
            absent += 1
            continue
        if len(member_claims) != 1:
            ambiguous += 1
            boundary_items.append((member_id, "ambiguous:" + member_id))
            continue
        relation = member_claims[0]
        memberships.append((member_id, relation))
        boundary_items.append((
            member_id,
            "group-instance:" + relation.group_instance_id,
        ))

    return GroupRelationsAnalysis(
        memberships=tuple(memberships),
        group_types=projections,
        boundary_items=tuple(boundary_items),
        index_member_occurrences=occurrences,
        index_unique_member_ids=len(claims),
        absent_from_l0_count=absent,
        ambiguous_group_claim_count=ambiguous,
    )


__all__ = [
    "GroupIndexInput",
    "GroupMembershipRelation",
    "GroupRelationsAnalysis",
    "GroupTypeProjection",
    "analyze_group_relations",
]
