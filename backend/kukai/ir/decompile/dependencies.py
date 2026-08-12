"""Deterministic dependency manifest derived from frozen L0 1.0 facts.

The manifest is deliberately a side contract: it does not add fields to
``L0Element`` and it does not claim that a matching type name identifies the
same Revit definition.  Current L0 can name a category/type pair, phases,
worksets, design options, and link summaries.  It cannot provide family names,
definition fingerprints, link paths, or resource fingerprints, so those facts
remain explicit unresolved records until a later extractor supplies evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from kukai.ir.decompile.l1_schema import FidelityReason
from kukai.ir.decompile.schema import L0Document, NamedReference


DEPENDENCY_MANIFEST_SCHEMA_VERSION = "1.0"
FAMILY_IDENTITY_NOTE = "family_name_unavailable_l0_1_0"
LINK_IDENTITY_NOTE = "link_path_and_fingerprint_unavailable_l0_1_0"
TYPE_FINGERPRINT_SCHEMA_VERSION = "type-fingerprint/1"

TYPE_FINGERPRINT_SCOPE = (
    "document_local: the digest separates definitions INSIDE this snapshot "
    "along the named axes and nothing more.  It is not a content fingerprint "
    "of the Revit definition, so it can never certify that a same-named type "
    "in a target document is the same definition."
)

# Blind reasons are a CLOSED vocabulary.  Every one was measured over the 67
# stored decompiles in `backend/backend/data/decompile` on 2026-08-11; none was
# reasoned into existence.
FINGERPRINT_BLIND_NO_TYPE_ID = "l0_element_carries_no_type_id"
FINGERPRINT_BLIND_NO_NAME = "type_name_empty_and_no_family_evidence"
FINGERPRINT_BLIND_INDEX_ABSENT = "family_placement_index_absent"
FINGERPRINT_BLIND_INDEX_REJECTED = (
    "family_placement_index_symbol_id_disagrees_with_l0_type_id")
FINGERPRINT_BLIND_FAMILY_UNSTABLE = "family_name_disagrees_across_instances"
FINGERPRINT_BLIND_NO_ROW = "no_family_placement_row_for_this_type"
FINGERPRINT_BLIND_REASONS = frozenset({
    FINGERPRINT_BLIND_NO_TYPE_ID,
    FINGERPRINT_BLIND_NO_NAME,
    FINGERPRINT_BLIND_INDEX_ABSENT,
    FINGERPRINT_BLIND_INDEX_REJECTED,
    FINGERPRINT_BLIND_FAMILY_UNSTABLE,
    FINGERPRINT_BLIND_NO_ROW,
})


class TypeIdentityState(str, Enum):
    """THREE outcomes of identifying a type, not two.

    A fingerprint that matches the WRONG type is worse than an absent one, so
    'not identified, for a named reason' and 'identified ambiguously, with the
    rival candidates listed' are separate states rather than shades of one
    refusal.
    """

    IDENTIFIED = "identified"
    AMBIGUOUS = "ambiguous"
    UNIDENTIFIED = "unidentified"


@dataclass(frozen=True, slots=True)
class TypeFingerprint:
    """A type fingerprint: the digest PLUS the axes it stands on.

    The axes travel beside the digest on purpose.  A bare hash cannot be
    refuted -- a reader cannot see what went into it, and 'the fingerprints
    differ' is indistinguishable from 'we compared different things'.  Here
    every axis is named, so a mismatch always points at one axis.
    """

    schema_version: str
    state: TypeIdentityState
    digest: str | None
    axes: tuple[tuple[str, str], ...]
    scope: str
    candidates: tuple[str, ...] = ()
    blind_reason: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != TYPE_FINGERPRINT_SCHEMA_VERSION:
            raise DependencyManifestError(
                "unsupported type fingerprint schema_version")
        if not isinstance(self.state, TypeIdentityState):
            raise DependencyManifestError(
                "type fingerprint state must be typed")
        if not isinstance(self.scope, str) or not self.scope:
            raise DependencyManifestError(
                "type fingerprint scope must be named")
        if not isinstance(self.axes, tuple) or any(
                not isinstance(pair, tuple)
                or len(pair) != 2
                or not isinstance(pair[0], str) or not pair[0]
                or not isinstance(pair[1], str)
                for pair in self.axes):
            raise DependencyManifestError(
                "type fingerprint axes must be (name, value) string pairs")
        names = tuple(pair[0] for pair in self.axes)
        if len(set(names)) != len(names):
            raise DependencyManifestError(
                "type fingerprint axes must be unique")
        if not isinstance(self.candidates, tuple) or any(
                not isinstance(value, str) or not value
                for value in self.candidates):
            raise DependencyManifestError(
                "type fingerprint candidates must be non-empty strings")
        if tuple(sorted(set(self.candidates))) != self.candidates:
            raise DependencyManifestError(
                "type fingerprint candidates must be sorted and unique")
        if (self.blind_reason is not None
                and self.blind_reason not in FINGERPRINT_BLIND_REASONS):
            raise DependencyManifestError(
                f"unknown fingerprint blind reason: {self.blind_reason!r}")
        if self.state is TypeIdentityState.UNIDENTIFIED:
            # NOT IDENTIFIED must say WHY: a silent refusal is
            # indistinguishable from a broken instrument.
            if self.digest is not None:
                raise DependencyManifestError(
                    "an unidentified type cannot carry a digest")
            if self.candidates:
                raise DependencyManifestError(
                    "an unidentified type cannot list candidates")
            if self.blind_reason is None:
                raise DependencyManifestError(
                    "an unidentified type must name its blind reason")
            return
        if not isinstance(self.digest, str) or not self.digest:
            raise DependencyManifestError(
                "an identified/ambiguous type requires a digest")
        if not self.axes:
            raise DependencyManifestError(
                "a digest without axes is unfalsifiable")
        if self.state is TypeIdentityState.AMBIGUOUS and not self.candidates:
            # AMBIGUOUS without the rival list is exactly .FirstOrDefault()
            # with a better reputation: the reader cannot see the choice.
            raise DependencyManifestError(
                "an ambiguous type must list its rival definition keys")
        if self.state is TypeIdentityState.IDENTIFIED and self.candidates:
            raise DependencyManifestError(
                "an identified type cannot have rival candidates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "digest": self.digest,
            "axes": [list(pair) for pair in self.axes],
            "scope": self.scope,
            "candidates": list(self.candidates),
            "blind_reason": self.blind_reason,
        }


class DependencyManifestError(ValueError):
    """A dependency manifest would contain an invalid or overstated fact."""


class TargetContract(str, Enum):
    """Environment in which a rebuild is intended to be grounded."""

    SAME_ENVIRONMENT = "same_environment"
    PORTABLE_EMPTY_DOCUMENT = "portable_empty_document"


class DependencyKind(str, Enum):
    """Kinds inferable without changing the frozen L0 schema."""

    FAMILY_SYMBOL = "family_symbol"
    SYSTEM_TYPE = "system_type"
    ELEMENT_TYPE = "element_type"


class DependencyResolution(str, Enum):
    """How a dependency is or will be grounded in the target.

    ``TARGET_MATCH`` is only a requested name-based lookup strategy.  It is
    intentionally not a resolved state without target inspection and a
    fingerprint comparison.
    """

    TARGET_MATCH = "target_match"
    EMBEDDED = "embedded"
    ARTIFACT_URI = "artifact_uri"
    UNSUPPORTED = "unsupported"


_RESOLVED = frozenset({
    DependencyResolution.TARGET_MATCH,
    DependencyResolution.EMBEDDED,
    DependencyResolution.ARTIFACT_URI,
})


@dataclass(frozen=True, slots=True)
class DependencyIdentity:
    category: str
    type_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category:
            raise DependencyManifestError("dependency category must be non-empty")
        if not isinstance(self.type_name, str):
            raise DependencyManifestError("dependency type_name must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category, "type_name": self.type_name}


@dataclass(frozen=True, slots=True)
class DependencyDefinition:
    key: str
    kind: DependencyKind
    identity: DependencyIdentity
    fingerprint: str | None
    required_by: tuple[str, ...]
    requires: tuple[str, ...]
    resolution: DependencyResolution
    identity_note: str
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    embedded_store_ref: str | None = None
    # APPEND-AT-THE-TAIL LAW (the same one L0Element.curve_kind follows):
    # the fields above are a positional contract of code already written,
    # and the defaults keep older manifests readable record for record.
    source_type_id: str = ""
    type_identity: "TypeFingerprint | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise DependencyManifestError("dependency key must be non-empty")
        if not isinstance(self.kind, DependencyKind):
            raise DependencyManifestError("dependency kind must be typed")
        if not isinstance(self.identity, DependencyIdentity):
            raise DependencyManifestError("dependency identity must be typed")
        if self.fingerprint is not None and (
                not isinstance(self.fingerprint, str) or not self.fingerprint):
            raise DependencyManifestError(
                "dependency fingerprint must be a non-empty string or null")
        if (not isinstance(self.required_by, tuple)
                or not self.required_by
                or any(not isinstance(value, str) or not value
                       for value in self.required_by)
                or tuple(sorted(set(self.required_by))) != self.required_by):
            raise DependencyManifestError(
                "dependency required_by must be sorted unique element ids")
        if (not isinstance(self.requires, tuple)
                or any(not isinstance(value, str) or not value
                       for value in self.requires)
                or tuple(sorted(set(self.requires))) != self.requires):
            raise DependencyManifestError(
                "dependency requires must be sorted unique keys")
        if not isinstance(self.resolution, DependencyResolution):
            raise DependencyManifestError("dependency resolution must be typed")
        if not isinstance(self.identity_note, str) or not self.identity_note:
            raise DependencyManifestError("identity_note must be non-empty")
        for field_name, value in (
            ("artifact_uri", self.artifact_uri),
            ("artifact_hash", self.artifact_hash),
            ("embedded_store_ref", self.embedded_store_ref),
        ):
            if value is not None and (
                    not isinstance(value, str) or not value):
                raise DependencyManifestError(
                    f"dependency {field_name} must be non-empty or null")
        if self.resolution in _RESOLVED and self.fingerprint is None:
            # TARGET_MATCH is also used as the honest current-L0 selector
            # strategy before grounding.  ``resolved`` remains false until a
            # fingerprint exists; embedded/artifact modes cannot omit one.
            if self.resolution is not DependencyResolution.TARGET_MATCH:
                raise DependencyManifestError(
                    "embedded/artifact dependency requires a fingerprint")
        if (self.resolution is DependencyResolution.EMBEDDED
                and self.embedded_store_ref is None):
            raise DependencyManifestError(
                "embedded dependency requires embedded_store_ref")
        if (self.resolution is DependencyResolution.ARTIFACT_URI
                and (self.artifact_uri is None or self.artifact_hash is None)):
            raise DependencyManifestError(
                "artifact_uri dependency requires URI and artifact_hash")
        if not isinstance(self.source_type_id, str):
            raise DependencyManifestError(
                "dependency source_type_id must be a string")
        if self.type_identity is not None and not isinstance(
                self.type_identity, TypeFingerprint):
            raise DependencyManifestError(
                "dependency type_identity must be a TypeFingerprint or null")
        if (self.type_identity is not None
                and self.type_identity.state is TypeIdentityState.IDENTIFIED
                and self.fingerprint is None
                and self.resolved):
            # A forbidden state, stated out loud: "identified in the SOURCE"
            # is not "resolved in the TARGET".  Resolution still demands a
            # digest of the definition itself, which frozen L0 1.0 does not
            # carry.  Without this line the first reader of the report will
            # read identified as ok.
            raise DependencyManifestError(
                "an identified type fingerprint does not resolve a "
                "dependency: a target inspection is still missing")

    @property
    def resolved(self) -> bool:
        return self.resolution in _RESOLVED and self.fingerprint is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "identity": self.identity.to_dict(),
            "fingerprint": self.fingerprint,
            "required_by": list(self.required_by),
            "requires": list(self.requires),
            "resolution": self.resolution.value,
            "identity_note": self.identity_note,
            "artifact_uri": self.artifact_uri,
            "artifact_hash": self.artifact_hash,
            "embedded_store_ref": self.embedded_store_ref,
            "source_type_id": self.source_type_id,
            "type_identity": (
                None if self.type_identity is None
                else self.type_identity.to_dict()),
        }


@dataclass(frozen=True, slots=True)
class StateReference:
    source_id: str
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise DependencyManifestError("state source_id must be non-empty")
        if not isinstance(self.name, str):
            raise DependencyManifestError("state name must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "name": self.name}


@dataclass(frozen=True, slots=True)
class DocumentState:
    phases: tuple[StateReference, ...]
    worksets: tuple[StateReference, ...]
    design_options: tuple[StateReference, ...]
    design_option_sets: None = None
    coordinates_sites: None = None
    parameter_bindings: None = None

    def __post_init__(self) -> None:
        for field_name, values in (
            ("phases", self.phases),
            ("worksets", self.worksets),
            ("design_options", self.design_options),
        ):
            if (not isinstance(values, tuple)
                    or not all(isinstance(value, StateReference)
                               for value in values)):
                raise DependencyManifestError(
                    f"document_state.{field_name} must be typed")
            ids = tuple(value.source_id for value in values)
            if ids != tuple(sorted(set(ids))):
                raise DependencyManifestError(
                    f"document_state.{field_name} must be sorted and unique")
        if any(value is not None for value in (
                self.design_option_sets,
                self.coordinates_sites,
                self.parameter_bindings,
        )):
            raise DependencyManifestError(
                "current L0 1.0 cannot populate extended document state")

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            "phases": [value.to_dict() for value in self.phases],
            "worksets": [value.to_dict() for value in self.worksets],
            "design_options": [value.to_dict() for value in self.design_options],
            "design_option_sets": self.design_option_sets,
            "coordinates_sites": self.coordinates_sites,
            "parameter_bindings": self.parameter_bindings,
        }


@dataclass(frozen=True, slots=True)
class SourceEnvironment:
    doc_name: str
    revit_version: str
    units: str
    revit_build: str | None = None
    document_kind: str | None = None
    locale: str | None = None
    template_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("doc_name", self.doc_name),
            ("revit_version", self.revit_version),
            ("units", self.units),
        ):
            if not isinstance(value, str) or not value:
                raise DependencyManifestError(
                    f"source_environment.{field_name} must be non-empty")
        for field_name, value in (
            ("revit_build", self.revit_build),
            ("document_kind", self.document_kind),
            ("locale", self.locale),
            ("template_fingerprint", self.template_fingerprint),
        ):
            if value is not None and (
                    not isinstance(value, str) or not value):
                raise DependencyManifestError(
                    f"source_environment.{field_name} must be non-empty or null")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "doc_name": self.doc_name,
            "revit_version": self.revit_version,
            "units": self.units,
            "revit_build": self.revit_build,
            "document_kind": self.document_kind,
            "locale": self.locale,
            "template_fingerprint": self.template_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ExternalResource:
    key: str
    kind: str
    source_element_id: str
    name: str
    fingerprint: str | None
    resolution: DependencyResolution
    loaded: bool
    discipline: str
    identity_note: str
    attachment_mode: str | None = None
    transform: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("key", self.key),
            ("kind", self.kind),
            ("source_element_id", self.source_element_id),
            ("identity_note", self.identity_note),
        ):
            if not isinstance(value, str) or not value:
                raise DependencyManifestError(
                    f"external_resource.{field_name} must be non-empty")
        if not isinstance(self.name, str):
            raise DependencyManifestError("external_resource.name must be a string")
        if self.fingerprint is not None and (
                not isinstance(self.fingerprint, str) or not self.fingerprint):
            raise DependencyManifestError(
                "external resource fingerprint must be non-empty or null")
        if not isinstance(self.resolution, DependencyResolution):
            raise DependencyManifestError("resource resolution must be typed")
        if not isinstance(self.loaded, bool):
            raise DependencyManifestError("external resource loaded must be bool")
        if not isinstance(self.discipline, str):
            raise DependencyManifestError(
                "external resource discipline must be a string")
        if self.attachment_mode is not None and (
                not isinstance(self.attachment_mode, str)
                or not self.attachment_mode):
            raise DependencyManifestError(
                "external resource attachment_mode must be non-empty or null")
        if self.transform is not None:
            raise DependencyManifestError(
                "current manifest cannot claim a link transform absent from L0")
        if self.resolution in _RESOLVED and self.fingerprint is None:
            raise DependencyManifestError(
                "resolved external resource requires a fingerprint")

    @property
    def resolved(self) -> bool:
        return self.resolution in _RESOLVED and self.fingerprint is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "source_element_id": self.source_element_id,
            "name": self.name,
            "identity": {"name": self.name},
            "fingerprint": self.fingerprint,
            "resolution": self.resolution.value,
            "loaded": self.loaded,
            "discipline": self.discipline,
            "identity_note": self.identity_note,
            "attachment_mode": self.attachment_mode,
            "transform": self.transform,
        }


@dataclass(frozen=True, slots=True)
class UnresolvedDependency:
    key: str
    reason: FidelityReason
    detail: str
    affected_source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise DependencyManifestError("unresolved key must be non-empty")
        if not isinstance(self.reason, FidelityReason):
            raise DependencyManifestError("unresolved reason must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise DependencyManifestError("unresolved detail must be non-empty")
        if (not isinstance(self.affected_source_ids, tuple)
                or any(not isinstance(value, str) or not value
                       for value in self.affected_source_ids)
                or tuple(sorted(set(self.affected_source_ids)))
                != self.affected_source_ids):
            raise DependencyManifestError(
                "unresolved affected_source_ids must be sorted unique ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "reason": self.reason.value,
            "detail": self.detail,
            "affected_source_ids": list(self.affected_source_ids),
        }


@dataclass(frozen=True, slots=True)
class DependencyManifest:
    schema_version: str
    target_contract: TargetContract
    source_environment: SourceEnvironment
    definitions: tuple[DependencyDefinition, ...]
    document_state: DocumentState
    external_resources: tuple[ExternalResource, ...]
    unresolved: tuple[UnresolvedDependency, ...]

    def __post_init__(self) -> None:
        if self.schema_version != DEPENDENCY_MANIFEST_SCHEMA_VERSION:
            raise DependencyManifestError(
                "unsupported dependency manifest schema_version")
        if not isinstance(self.target_contract, TargetContract):
            raise DependencyManifestError("target_contract must be typed")
        if not isinstance(self.source_environment, SourceEnvironment):
            raise DependencyManifestError("source_environment must be typed")
        if not isinstance(self.document_state, DocumentState):
            raise DependencyManifestError("document_state must be typed")
        for field_name, values, expected in (
            ("definitions", self.definitions, DependencyDefinition),
            ("external_resources", self.external_resources, ExternalResource),
            ("unresolved", self.unresolved, UnresolvedDependency),
        ):
            if not isinstance(values, tuple) or not all(
                    isinstance(value, expected) for value in values):
                raise DependencyManifestError(
                    f"manifest {field_name} must be a typed tuple")
        definition_keys = tuple(value.key for value in self.definitions)
        resource_keys = tuple(value.key for value in self.external_resources)
        unresolved_keys = tuple(value.key for value in self.unresolved)
        if definition_keys != tuple(sorted(set(definition_keys))):
            raise DependencyManifestError(
                "definition keys must be sorted and unique")
        if resource_keys != tuple(sorted(set(resource_keys))):
            raise DependencyManifestError(
                "external resource keys must be sorted and unique")
        if unresolved_keys != tuple(sorted(set(unresolved_keys))):
            raise DependencyManifestError(
                "unresolved keys must be sorted and unique")
        definitions_by_key = {
            value.key: value for value in self.definitions
        }
        for definition in self.definitions:
            missing_requires = sorted(
                set(definition.requires) - definitions_by_key.keys())
            if missing_requires:
                raise DependencyManifestError(
                    f"dependency {definition.key!r} requires unknown key(s): "
                    + ", ".join(missing_requires))
            if definition.key in definition.requires:
                raise DependencyManifestError(
                    f"dependency {definition.key!r} cannot require itself")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise DependencyManifestError(
                    "dependency graph contains an unsupported cycle")
            visiting.add(key)
            for required_key in definitions_by_key[key].requires:
                visit(required_key)
            visiting.remove(key)
            visited.add(key)

        for key in definition_keys:
            visit(key)

        unresolved_key_set = set(unresolved_keys)
        for definition in self.definitions:
            if not definition.resolved and definition.key not in unresolved_key_set:
                raise DependencyManifestError(
                    f"unresolved dependency {definition.key!r} is not listed")
        for resource in self.external_resources:
            if not resource.resolved and resource.key not in unresolved_key_set:
                raise DependencyManifestError(
                    f"unresolved resource {resource.key!r} is not listed")

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved)

    @property
    def type_identity_counts(self) -> dict[str, int]:
        """How many definitions land in each of the THREE outcomes.

        A manifest whose every record repeats one sentence tells a reader
        nothing about which types are actually in trouble; measured
        2026-08-11, all 569 unresolved records of `k2_ar_rd_v7` carried
        the identical detail string.  These counts are the smallest thing
        that makes the difference visible without opening the array.
        """

        counts = {state.value: 0 for state in TypeIdentityState}
        for definition in self.definitions:
            if definition.type_identity is not None:
                counts[definition.type_identity.state.value] += 1
        return counts

    def dependency_resolved_for(self, source_element_id: str) -> bool:
        """Return true only when every recorded requirement has evidence.

        A missing source id is unresolved by design.  Current L0 1.0 manifests
        therefore return false for element leaves: name matching has not been
        inspected in a target and no definition fingerprint is available.
        """

        if not isinstance(source_element_id, str) or not source_element_id:
            return False
        if any(
            source_element_id in unresolved.affected_source_ids
            for unresolved in self.unresolved
        ):
            return False
        requirements = [
            definition for definition in self.definitions
            if source_element_id in definition.required_by
        ]
        if not requirements:
            return False
        definitions_by_key = {
            definition.key: definition for definition in self.definitions
        }
        unresolved_keys = {value.key for value in self.unresolved}

        def resolved(
            definition: DependencyDefinition,
            checked: frozenset[str],
        ) -> bool:
            if (not definition.resolved
                    or definition.key in unresolved_keys
                    or definition.key in checked):
                return False
            next_checked = checked | {definition.key}
            return all(resolved(
                definitions_by_key[required_key], next_checked)
                for required_key in definition.requires)

        return all(resolved(definition, frozenset())
                   for definition in requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_contract": self.target_contract.value,
            "source_environment": self.source_environment.to_dict(),
            "definitions": [value.to_dict() for value in self.definitions],
            "document_state": self.document_state.to_dict(),
            "external_resources": [
                value.to_dict() for value in self.external_resources],
            "unresolved": [value.to_dict() for value in self.unresolved],
            "type_identity_counts": self.type_identity_counts,
        }


def _dependency_kind(_category: str) -> DependencyKind:
    # Frozen L0 has category/type ids but no Revit runtime class or
    # is_family_instance witness.  A category whitelist would misclassify
    # in-place/custom cases in arbitrary models, so STEP-0 stays generic.
    return DependencyKind.ELEMENT_TYPE


def _definition_key(
    kind: DependencyKind,
    identity: DependencyIdentity,
    source_type_id: str,
) -> str:
    # This is a readable stable key, not a content fingerprint.
    #
    # ``source_type_id`` joined the key on 2026-08-11 because the key WITHOUT
    # it is not unique per definition, and the manifest silently merged real
    # definitions.  Measured over the 67 stored decompiles: 8700 distinct
    # ElementType ids collapsed into 7945 records, i.e. 755 definitions were
    # LOST; the worst single cell is `k2_ar_rd_v15`, where 18 different
    # in-place wall types all named "Pilastre" became one record claiming all
    # 18 elements.  Grounding that record picks ONE type for eighteen.
    encoded = json.dumps(
        {
            "category": identity.category,
            "kind": kind.value,
            "source_type_id": source_type_id,
            "type_name": identity.type_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"definition:{encoded}"


def _fingerprint_digest(axes: tuple[tuple[str, str], ...]) -> str:
    encoded = json.dumps(
        [list(pair) for pair in axes],
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _family_axis_by_type(
    document: L0Document,
    family_placement: Mapping[str, Any] | None,
) -> tuple[dict[str, str], frozenset[str], int, str | None]:
    """type_id -> family name, unstable ids, rejected rows, document reason.

    PROVENANCE IS CHECKED, NEVER ASSUMED.  The side index is keyed by
    element id, and an element id means nothing outside the document it came
    from.  Measured 2026-08-11 over the 58 stored runs that carry this index:
    242 040 rows, and ``symbol_id`` equals the L0 ``type_id`` of the same
    element in 242 020 of them.  All 20 disagreements sit in ONE run --
    `snowdon_elec_v1`, whose stage reported 1837 `element_unresolved`
    failures and returned 20 rows belonging to a DIFFERENT model: an
    OST_LightingFixtures element carrying the family "Round Elbow", an
    OST_ElectricalFixtures element carrying "Bend - PVC - Sch 40 - DWV".
    Those rows would have attached plumbing families to electrical fixtures
    -- a fingerprint matching the WRONG type, which is worse than none.

    A single disagreeing row therefore rejects the WHOLE index as type
    evidence, and the reason travels to every definition.  Rejecting only the
    offending row would keep the surviving rows of a demonstrably foreign
    index, and there is nothing in the snapshot that tells the two apart.
    """

    if family_placement is None:
        return {}, frozenset(), 0, FINGERPRINT_BLIND_INDEX_ABSENT
    if not isinstance(family_placement, Mapping):
        raise DependencyManifestError(
            "family_placement must be a mapping of element_id to row or null")
    if not family_placement:
        # An EMPTY index and an ABSENT index are different facts, but neither
        # supplies an axis; the reason is the same word to the reader and the
        # difference stays visible in the side manifest.
        return {}, frozenset(), 0, FINGERPRINT_BLIND_INDEX_ABSENT
    type_by_element = {
        element.element_id: element.type_id for element in document.elements}
    observed: dict[str, set[str]] = {}
    rejected = 0
    for element_id, row in family_placement.items():
        if not isinstance(row, Mapping):
            raise DependencyManifestError(
                f"family placement row {element_id!r} must be a mapping")
        type_id = type_by_element.get(str(element_id))
        if not type_id:
            # A row about an element this L0 does not carry, or about an
            # element with no ElementType.  Silence here is correct: that is
            # a fact for the side-stage receipt, not evidence about a type.
            continue
        symbol_id = row.get("symbol_id")
        if symbol_id is None or str(symbol_id) != type_id:
            rejected += 1
            continue
        family_name = row.get("family_name")
        if not isinstance(family_name, str) or not family_name:
            continue
        observed.setdefault(type_id, set()).add(family_name)
    if rejected:
        return {}, frozenset(), rejected, FINGERPRINT_BLIND_INDEX_REJECTED
    stable = {
        type_id: next(iter(names))
        for type_id, names in observed.items() if len(names) == 1
    }
    unstable = frozenset(
        type_id for type_id, names in observed.items() if len(names) > 1)
    return stable, unstable, 0, None


def _resource_key(source_element_id: str) -> str:
    return f"external_resource:revit_link:{source_element_id}"


def _state_references(
    values: Iterable[NamedReference | None],
) -> tuple[StateReference, ...]:
    by_id: dict[str, str] = {}
    for value in values:
        if value is None:
            continue
        previous = by_id.get(value.id)
        if previous is not None and previous != value.name:
            raise DependencyManifestError(
                f"state reference {value.id!r} has conflicting names")
        by_id[value.id] = value.name
    return tuple(
        StateReference(source_id=source_id, name=by_id[source_id])
        for source_id in sorted(by_id)
    )


def _coerce_target_contract(
    value: TargetContract | str,
) -> TargetContract:
    try:
        return value if isinstance(value, TargetContract) else TargetContract(value)
    except (TypeError, ValueError) as exc:
        raise DependencyManifestError(
            f"unsupported target_contract: {value!r}") from exc


def build_dependency_manifest(
    document: L0Document,
    *,
    target_contract: TargetContract | str = TargetContract.SAME_ENVIRONMENT,
    family_placement: Mapping[str, Any] | None = None,
) -> DependencyManifest:
    """Build the strongest honest manifest available from current L0 1.0.

    Every distinct ElementType is recorded conservatively because an opaque
    atom can still depend on its source definition.  No category is silently
    treated as portable merely because its current L1 op omits a type
    parameter.

    ``family_placement`` is the parsed FamilyInstance placement side index
    (``parse_family_placement_index``); ``None`` means the caller has none and
    the family axis is simply absent, named as such rather than guessed.

    THE SCOPE OF WHAT THIS PRODUCES, stated before anything reads it as more.
    The fingerprint is DOCUMENT-LOCAL and PARTIAL.  Measured 2026-08-11 over
    the 67 stored decompiles (1 139 477 elements, 8700 distinct ElementType
    ids): 275 (category, type_name) cells hold more than one ElementType --
    i.e. a type name is not unique even INSIDE one document -- covering 1029
    ids; the family axis separates 115 of those cells completely and 0
    partially.  What it cannot separate is measured too: 692 ids stay
    ambiguous, 216 of them OST_Walls, and their heart is the in-place family,
    where Revit mints one type per instance and the snapshot carries no field
    that differs.  Nothing here claims a match in a TARGET document: L0 1.0
    holds no content digest of a Revit definition, so ``resolution`` stays
    TARGET_MATCH and ``fingerprint`` stays None even for an identified type.
    """

    if not isinstance(document, L0Document):
        raise DependencyManifestError("document must be an L0Document")
    contract = _coerce_target_contract(target_contract)
    family_axis, unstable_types, rejected_rows, index_reason = (
        _family_axis_by_type(document, family_placement))
    grouped: dict[tuple[DependencyKind, str, str, str], list[str]] = {}
    for element in document.elements:
        kind = _dependency_kind(element.category)
        grouped.setdefault(
            (kind, element.category, element.type_name, element.type_id),
            []).append(element.element_id)

    definitions: list[DependencyDefinition] = []
    all_source_ids = tuple(sorted(
        element.element_id for element in document.elements))
    unresolved: list[UnresolvedDependency] = [
        UnresolvedDependency(
            key="source_environment:l0_1_0",
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=(
                "frozen L0 1.0 carries no Revit build, document kind, "
                "locale, or template fingerprint"
            ),
            affected_source_ids=all_source_ids,
        ),
        UnresolvedDependency(
            key="document_state:l0_1_0",
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=(
                "frozen L0 1.0 carries no design-option-set graph, "
                "coordinate/site state, or parameter-binding ledger"
            ),
            affected_source_ids=all_source_ids,
        ),
    ]
    if rejected_rows:
        # A NEW unresolved FACT, not a louder version of an old one: the type
        # evidence we do hold has been proven to come from another document.
        unresolved.append(UnresolvedDependency(
            key="family_placement_index:provenance",
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=(
                f"family placement side index refused as type evidence: "
                f"{rejected_rows} row(s) carry a symbol_id that disagrees "
                f"with the L0 type_id of the same element, which proves the "
                f"index was not read from this document"
            ),
            affected_source_ids=(),
        ))

    # FIRST PASS -- axes only.  "Unique" is a property of a PAIR of
    # definitions, so no record can be given its state before every record of
    # the document exists.
    drafts: list[dict[str, Any]] = []
    for kind, category, type_name, type_id in sorted(
            grouped,
            key=lambda item: (item[0].value, item[1], item[2], item[3])):
        identity = DependencyIdentity(category=category, type_name=type_name)
        key = _definition_key(kind, identity, type_id)
        required_by = tuple(sorted(set(
            grouped[(kind, category, type_name, type_id)])))
        axes: list[tuple[str, str]] = [("category", category)]
        if type_name:
            axes.append(("type_name", type_name))
        family_name = family_axis.get(type_id) if type_id else None
        blind: str | None
        if family_name:
            axes.append(("family_name", family_name))
            blind = None
        elif not type_id:
            blind = FINGERPRINT_BLIND_NO_TYPE_ID
        elif index_reason is not None:
            blind = index_reason
        elif type_id in unstable_types:
            blind = FINGERPRINT_BLIND_FAMILY_UNSTABLE
        else:
            blind = FINGERPRINT_BLIND_NO_ROW
        if not type_id:
            # An element with no ElementType at all.  Measured 2026-08-11:
            # 123 758 of 1 139 477 elements -- rooms, lines, curtain grids,
            # room separation lines.  There is nothing to identify, and
            # dressing the category up as a type name would INVENT a
            # dependency that the document does not have.
            digest = None
            blind = FINGERPRINT_BLIND_NO_TYPE_ID
        elif not type_name and family_name is None:
            digest = None
            blind = FINGERPRINT_BLIND_NO_NAME
        else:
            digest = _fingerprint_digest(tuple(axes))
        drafts.append({
            "key": key,
            "kind": kind,
            "identity": identity,
            "type_id": type_id,
            "required_by": required_by,
            "axes": tuple(axes),
            "digest": digest,
            "blind": blind,
        })

    shared: dict[str, list[str]] = {}
    for draft in drafts:
        if draft["digest"] is not None:
            shared.setdefault(draft["digest"], []).append(draft["key"])

    # SECOND PASS -- state, and the detail that names the cause.  Before this
    # change every unresolved record of a document carried one identical
    # sentence (569 of them on `k2_ar_rd_v7`, measured 2026-08-11), so a
    # reader could not tell a type we can point at from a type we cannot.
    for draft in drafts:
        digest = draft["digest"]
        axis_names = ", ".join(name for name, _ in draft["axes"])
        if digest is None:
            state = TypeIdentityState.UNIDENTIFIED
            candidates: tuple[str, ...] = ()
            detail = (
                "the source snapshot carries no axis able to identify this "
                f"definition: {draft['blind']}"
            )
        else:
            rivals = tuple(sorted(
                other for other in shared[digest] if other != draft["key"]))
            if rivals:
                state = TypeIdentityState.AMBIGUOUS
                candidates = rivals
                detail = (
                    f"the source snapshot does not separate this definition "
                    f"from {len(rivals)} rival definition(s) sharing "
                    f"({axis_names}); missing axis: {draft['blind']}"
                )
            else:
                state = TypeIdentityState.IDENTIFIED
                candidates = ()
                detail = (
                    "target name match is unverified and frozen L0 1.0 "
                    "carries no definition fingerprint; inside the source "
                    f"snapshot this definition is separated by ({axis_names})"
                )
        type_identity = TypeFingerprint(
            schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
            state=state,
            digest=digest,
            axes=draft["axes"],
            scope=TYPE_FINGERPRINT_SCOPE,
            candidates=candidates,
            blind_reason=draft["blind"],
        )
        definitions.append(DependencyDefinition(
            key=draft["key"],
            kind=draft["kind"],
            identity=draft["identity"],
            fingerprint=None,
            required_by=draft["required_by"],
            requires=(),
            resolution=DependencyResolution.TARGET_MATCH,
            identity_note=FAMILY_IDENTITY_NOTE,
            source_type_id=draft["type_id"],
            type_identity=type_identity,
        ))
        unresolved.append(UnresolvedDependency(
            key=draft["key"],
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=detail,
            affected_source_ids=draft["required_by"],
        ))

    resources: list[ExternalResource] = []
    for link in sorted(document.links, key=lambda value: value.element_id):
        key = _resource_key(link.element_id)
        resources.append(ExternalResource(
            key=key,
            kind="revit_link",
            source_element_id=link.element_id,
            name=link.name,
            fingerprint=None,
            resolution=DependencyResolution.UNSUPPORTED,
            loaded=link.loaded,
            discipline=link.discipline,
            identity_note=LINK_IDENTITY_NOTE,
        ))
        unresolved.append(UnresolvedDependency(
            key=key,
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=(
                "L0 link summary carries no resource path, content "
                "fingerprint, or load attachment"
            ),
            affected_source_ids=(link.element_id,),
        ))

    return DependencyManifest(
        schema_version=DEPENDENCY_MANIFEST_SCHEMA_VERSION,
        target_contract=contract,
        source_environment=SourceEnvironment(
            doc_name=document.doc_name,
            revit_version=document.revit_version,
            units=document.units,
        ),
        definitions=tuple(sorted(definitions, key=lambda value: value.key)),
        document_state=DocumentState(
            phases=_state_references(
                element.phase_created for element in document.elements),
            worksets=_state_references(
                element.workset for element in document.elements),
            design_options=_state_references(
                element.design_option for element in document.elements),
        ),
        external_resources=tuple(
            sorted(resources, key=lambda value: value.key)),
        unresolved=tuple(sorted(unresolved, key=lambda value: value.key)),
    )


__all__ = [
    "DEPENDENCY_MANIFEST_SCHEMA_VERSION",
    "DependencyDefinition",
    "DependencyIdentity",
    "DependencyKind",
    "DependencyManifest",
    "DependencyManifestError",
    "DependencyResolution",
    "DocumentState",
    "ExternalResource",
    "FAMILY_IDENTITY_NOTE",
    "LINK_IDENTITY_NOTE",
    "FINGERPRINT_BLIND_FAMILY_UNSTABLE",
    "FINGERPRINT_BLIND_INDEX_ABSENT",
    "FINGERPRINT_BLIND_INDEX_REJECTED",
    "FINGERPRINT_BLIND_NO_NAME",
    "FINGERPRINT_BLIND_NO_ROW",
    "FINGERPRINT_BLIND_NO_TYPE_ID",
    "FINGERPRINT_BLIND_REASONS",
    "SourceEnvironment",
    "StateReference",
    "TYPE_FINGERPRINT_SCHEMA_VERSION",
    "TYPE_FINGERPRINT_SCOPE",
    "TargetContract",
    "TypeFingerprint",
    "TypeIdentityState",
    "UnresolvedDependency",
    "build_dependency_manifest",
]
