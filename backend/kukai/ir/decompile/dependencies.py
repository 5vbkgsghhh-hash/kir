"""Deterministic dependency manifest derived from frozen L0 1.0 facts.

The manifest is deliberately a side contract: it does not add fields to
``L0Element`` and it does not claim that a matching type name identifies the
same Revit definition.  Current L0 can name a category/type pair, phases,
worksets, design options, and link summaries.  It cannot provide family names,
definition fingerprints, link paths, or resource fingerprints, so those facts
remain explicit unresolved records until a later extractor supplies evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from kukai.ir.decompile.l1_schema import FidelityReason
from kukai.ir.decompile.schema import L0Document, NamedReference


DEPENDENCY_MANIFEST_SCHEMA_VERSION = "1.0"
FAMILY_IDENTITY_NOTE = "family_name_unavailable_l0_1_0"
LINK_IDENTITY_NOTE = "link_path_and_fingerprint_unavailable_l0_1_0"


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
        }


def _dependency_kind(_category: str) -> DependencyKind:
    # Frozen L0 has category/type ids but no Revit runtime class or
    # is_family_instance witness.  A category whitelist would misclassify
    # in-place/custom cases in arbitrary models, so STEP-0 stays generic.
    return DependencyKind.ELEMENT_TYPE


def _definition_key(
    kind: DependencyKind,
    identity: DependencyIdentity,
) -> str:
    # This is a readable stable key, not a content fingerprint.
    encoded = json.dumps(
        {
            "category": identity.category,
            "kind": kind.value,
            "type_name": identity.type_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"definition:{encoded}"


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
) -> DependencyManifest:
    """Build the strongest honest manifest available from current L0 1.0.

    Every distinct category/type pair is recorded conservatively because an
    opaque atom can still depend on its source definition.  No category is
    silently treated as portable merely because its current L1 op omits a type
    parameter.
    """

    if not isinstance(document, L0Document):
        raise DependencyManifestError("document must be an L0Document")
    contract = _coerce_target_contract(target_contract)
    grouped: dict[tuple[DependencyKind, str, str], list[str]] = {}
    for element in document.elements:
        kind = _dependency_kind(element.category)
        grouped.setdefault(
            (kind, element.category, element.type_name), []).append(
                element.element_id)

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
    for kind, category, type_name in sorted(
            grouped, key=lambda item: (item[0].value, item[1], item[2])):
        identity = DependencyIdentity(category=category, type_name=type_name)
        key = _definition_key(kind, identity)
        required_by = tuple(sorted(set(grouped[(kind, category, type_name)])))
        identity_note = FAMILY_IDENTITY_NOTE
        definitions.append(DependencyDefinition(
            key=key,
            kind=kind,
            identity=identity,
            fingerprint=None,
            required_by=required_by,
            requires=(),
            resolution=DependencyResolution.TARGET_MATCH,
            identity_note=identity_note,
        ))
        unresolved.append(UnresolvedDependency(
            key=key,
            reason=FidelityReason.DEPENDENCY_UNRESOLVED,
            detail=(
                "target name match is unverified and frozen L0 1.0 carries "
                "no definition fingerprint"
            ),
            affected_source_ids=required_by,
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
    "SourceEnvironment",
    "StateReference",
    "TargetContract",
    "UnresolvedDependency",
    "build_dependency_manifest",
]
