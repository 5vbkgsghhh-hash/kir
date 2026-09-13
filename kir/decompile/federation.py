"""Fail-closed assembly of per-document graphs into one federated building.

The local ``ElementId`` address used by :mod:`building_graph` stops at this
boundary.  Every assembled node and edge endpoint is keyed by a typed
``OccurrenceIdentity``.  Missing identity and external endpoints remain in
explicit ledgers; no title/path/ElementId heuristic is allowed to bridge them.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .building_graph import (
    BuildingGraph,
    GraphEdge,
    GraphNode,
    Modality,
    Relation,
)
from .identity import (
    DefinitionIdentity,
    DocumentIdentity,
    FederationContext,
    OccurrenceIdentity,
)


class FederationAssemblyError(ValueError):
    """The supplied federation contradicts its own identity contract."""


class LinkExtractionCapability(str, Enum):
    """How deeply the producer can open expected Revit link occurrences."""

    DIRECT_ONLY = "direct_only"
    RECURSIVE = "recursive"


class FederationRefusalReason(str, Enum):
    GRAPH_CONTEXT_INCOMPLETE = "graph_context_incomplete"
    NODE_OCCURRENCE_INCOMPLETE = "node_occurrence_incomplete"


class FederationGapReason(str, Enum):
    GRAPH_CONTEXT_INCOMPLETE = "graph_context_incomplete"
    EDGE_SOURCE_NOT_IN_GRAPH = "edge_source_not_in_graph"
    EDGE_TARGET_NOT_IN_GRAPH = "edge_target_not_in_graph"
    EDGE_ENDPOINTS_NOT_IN_GRAPH = "edge_endpoints_not_in_graph"
    EDGE_ENDPOINT_IDENTITY_INCOMPLETE = "edge_endpoint_identity_incomplete"
    MANIFEST_COVERAGE_MISSING = "manifest_coverage_missing"
    MANIFEST_DOCUMENT_GRAPH_MISSING = "manifest_document_graph_missing"
    FEDERATION_ROOT_GRAPH_MISSING = "federation_root_graph_missing"
    GRAPH_PATH_NOT_EXPECTED = "graph_path_not_expected"
    EXPECTED_LINK_PARENT_GRAPH_MISSING = "expected_link_parent_graph_missing"
    EXPECTED_LINK_UNLOADED = "expected_link_unloaded"
    EXPECTED_LINK_IDENTITY_MISSING = "expected_link_identity_missing"
    EXPECTED_LINK_PATH_MISSING = "expected_link_path_missing"
    EXPECTED_LINK_GRAPH_MISSING = "expected_link_graph_missing"
    EXTRACTOR_DIRECT_LINK_ONLY = "extractor_direct_link_only"


class FederationGapScope(str, Enum):
    EDGE = "edge"
    MANIFEST = "manifest"
    CAPABILITY = "capability"


_EDGE_GAP_REASONS = frozenset({
    FederationGapReason.GRAPH_CONTEXT_INCOMPLETE,
    FederationGapReason.EDGE_SOURCE_NOT_IN_GRAPH,
    FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH,
    FederationGapReason.EDGE_ENDPOINTS_NOT_IN_GRAPH,
    FederationGapReason.EDGE_ENDPOINT_IDENTITY_INCOMPLETE,
})
_CAPABILITY_GAP_REASONS = frozenset({
    FederationGapReason.EXTRACTOR_DIRECT_LINK_ONLY,
})
_MANIFEST_GAP_REASONS = frozenset(FederationGapReason) - (
    _EDGE_GAP_REASONS | _CAPABILITY_GAP_REASONS)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederationAssemblyError(f"{name} must be a non-empty string")
    return value


def _context_key(context: FederationContext) -> tuple[str, tuple[str, ...]]:
    return context.federation_root, context.link_instance_chain


def _path(
    value: Iterable[str] | None,
    name: str,
    *,
    allow_none: bool = True,
) -> tuple[str, ...] | None:
    if value is None:
        if allow_none:
            return None
        raise FederationAssemblyError(f"{name} must be a link path")
    if isinstance(value, str):
        raise FederationAssemblyError(f"{name} must be a sequence, not str")
    try:
        path = tuple(value)
    except TypeError as exc:
        raise FederationAssemblyError(f"{name} must be a sequence") from exc
    for index, item in enumerate(path):
        _text(item, f"{name}[{index}]")
    return path


def _canonical(value: Any) -> Any:
    """Convert evidence to a deterministic JSON value without inventing data."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FederationAssemblyError(
                "evidence contains a non-finite number")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FederationAssemblyError(
                "evidence object keys must be strings")
        return {key: _canonical(item)
                for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [_canonical(item) for item in value]
        return sorted(converted, key=lambda item: json.dumps(
            item, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    raise FederationAssemblyError(
        f"evidence contains non-serializable {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    """Take an immutable snapshot of JSON evidence at the trust boundary."""

    canonical = _canonical(value)
    if isinstance(canonical, dict):
        return MappingProxyType({
            key: _freeze_json(item) for key, item in canonical.items()})
    if isinstance(canonical, list):
        return tuple(_freeze_json(item) for item in canonical)
    return canonical


@dataclass(frozen=True, slots=True)
class ExpectedLink:
    """One explicitly observed link slot; title is intentionally absent."""

    expectation_id: str
    local_link_element_id: str
    loaded: bool
    instance_unique_id: str | None
    linked_document_identity: DocumentIdentity | None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.expectation_id, "ExpectedLink.expectation_id")
        _text(self.local_link_element_id,
              "ExpectedLink.local_link_element_id")
        if not isinstance(self.loaded, bool):
            raise FederationAssemblyError("ExpectedLink.loaded must be boolean")
        if self.instance_unique_id is not None:
            _text(self.instance_unique_id, "ExpectedLink.instance_unique_id")
        if (self.linked_document_identity is not None
                and not isinstance(self.linked_document_identity,
                                   DocumentIdentity)):
            raise FederationAssemblyError(
                "ExpectedLink.linked_document_identity must be typed or null")
        if not isinstance(self.evidence, Mapping):
            raise FederationAssemblyError("ExpectedLink.evidence must be a mapping")
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "local_link_element_id": self.local_link_element_id,
            "loaded": self.loaded,
            "instance_unique_id": self.instance_unique_id,
            "linked_document_identity": (
                self.linked_document_identity.as_dict()
                if self.linked_document_identity is not None else None),
            "evidence": _canonical(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ExpectedDocumentLinks:
    """Exhaustive link manifest for one document occurrence."""

    document_identity: DocumentIdentity
    context: FederationContext
    links: tuple[ExpectedLink, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.document_identity, DocumentIdentity):
            raise FederationAssemblyError(
                "ExpectedDocumentLinks.document_identity must be typed")
        if not isinstance(self.context, FederationContext):
            raise FederationAssemblyError(
                "ExpectedDocumentLinks.context must be typed")
        links = tuple(self.links)
        if any(not isinstance(link, ExpectedLink) for link in links):
            raise FederationAssemblyError(
                "ExpectedDocumentLinks.links must contain ExpectedLink")
        ids = [link.expectation_id for link in links]
        if len(ids) != len(set(ids)):
            raise FederationAssemblyError(
                "duplicate expected-link id in one document occurrence")
        local_ids = [link.local_link_element_id for link in links]
        if len(local_ids) != len(set(local_ids)):
            raise FederationAssemblyError(
                "duplicate local link ElementId in one document occurrence")
        object.__setattr__(self, "links", links)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_identity": self.document_identity.as_dict(),
            "context": self.context.as_dict(),
            "links": [link.to_dict() for link in sorted(
                self.links,
                key=lambda item: (
                    item.local_link_element_id, item.expectation_id))],
        }


@dataclass(frozen=True, slots=True)
class LinkAuthorityBinding:
    """Joint authority for one measured ``RevitLinkInstance`` occurrence.

    A transform consumer must join on *all* physical facts below.  In
    particular, neither a document identity, a local ``ElementId``, nor a
    transform matrix is sufficient by itself.  The local id is retained only
    as an alias inside the exact parent occurrence; the stable occurrence path
    is extended by the link instance ``UniqueId``.
    """

    expectation_id: str
    parent_document_identity: DocumentIdentity
    parent_context: FederationContext
    local_link_element_id: str
    link_instance_unique_id: str
    linked_document_identity: DocumentIdentity
    child_context: FederationContext

    def __post_init__(self) -> None:
        _text(self.expectation_id, "LinkAuthorityBinding.expectation_id")
        if not isinstance(self.parent_document_identity, DocumentIdentity):
            raise FederationAssemblyError(
                "binding parent_document_identity must be typed")
        if not isinstance(self.parent_context, FederationContext):
            raise FederationAssemblyError("binding parent_context must be typed")
        _text(self.local_link_element_id,
              "LinkAuthorityBinding.local_link_element_id")
        _text(self.link_instance_unique_id,
              "LinkAuthorityBinding.link_instance_unique_id")
        if not isinstance(self.linked_document_identity, DocumentIdentity):
            raise FederationAssemblyError(
                "binding linked_document_identity must be typed")
        if not isinstance(self.child_context, FederationContext):
            raise FederationAssemblyError("binding child_context must be typed")
        if self.parent_context.federation_root != self.child_context.federation_root:
            raise FederationAssemblyError(
                "binding parent and child belong to different federations")
        expected_chain = (*self.parent_context.link_instance_chain,
                          self.link_instance_unique_id)
        if self.child_context.link_instance_chain != expected_chain:
            raise FederationAssemblyError(
                "binding child path is not parent path plus exact link UniqueId")

    @property
    def key(self) -> str:
        payload = json.dumps(
            {
                "schema": "kir-federation-link-binding/1",
                "parent_document_identity": (
                    self.parent_document_identity.value),
                "parent_context": self.parent_context.as_dict(),
                "local_link_element_id": self.local_link_element_id,
                "link_instance_unique_id": self.link_instance_unique_id,
                "linked_document_identity": (
                    self.linked_document_identity.value),
                "child_context": self.child_context.as_dict(),
            },
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return f"kir:link-binding:v1:{hashlib.sha256(payload).hexdigest()}"

    def transform_subject(self) -> dict[str, Any]:
        """Exact subject expected by transform evidence for this link.

        The linked document is the transform source and its parent document is
        the target frame.  The matrix itself remains owned by the transform
        subsystem; this method only supplies the non-swappable authority join.
        """

        return {
            "source_document_key": self.linked_document_identity.value,
            "target_document_key": self.parent_document_identity.value,
            "link_instance_chain": list(
                self.child_context.link_instance_chain),
            "target_link_instance_chain": list(
                self.parent_context.link_instance_chain),
        }

    def assert_transform_subject(self, subject: Mapping[str, Any]) -> None:
        """Reject transform evidence issued for any other link occurrence."""

        if not isinstance(subject, Mapping):
            raise FederationAssemblyError(
                "transform subject must be an exact mapping")
        if _canonical(subject) != self.transform_subject():
            raise FederationAssemblyError(
                "transform subject does not match link authority binding")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "expectation_id": self.expectation_id,
            "parent_document_identity": (
                self.parent_document_identity.as_dict()),
            "parent_context": self.parent_context.as_dict(),
            "local_link_element_id": self.local_link_element_id,
            "link_instance_unique_id": self.link_instance_unique_id,
            "linked_document_identity": (
                self.linked_document_identity.as_dict()),
            "child_context": self.child_context.as_dict(),
            "transform_subject": self.transform_subject(),
        }


@dataclass(frozen=True, slots=True)
class ExpectedLinkManifestCensus:
    """Proof that no manifest row disappeared at the local-id join."""

    records: int
    local_aliases: int
    authority_bindings: int
    unbound_records: int

    def __post_init__(self) -> None:
        self.assert_balanced()

    def assert_balanced(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in values):
            raise FederationAssemblyError(
                "expected-link census counts must be non-negative integers")
        if self.records != self.local_aliases:
            raise FederationAssemblyError(
                "expected-link record/local-id census is unbalanced")
        if self.records != self.authority_bindings + self.unbound_records:
            raise FederationAssemblyError(
                "expected-link binding census is unbalanced")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ExpectedLinkManifest:
    """Explicit, exhaustive expected-link surface for known occurrences."""

    federation_root: str
    documents: tuple[ExpectedDocumentLinks, ...]
    extraction_capability: LinkExtractionCapability = (
        LinkExtractionCapability.DIRECT_ONLY)
    _authority_bindings: tuple[LinkAuthorityBinding, ...] = field(
        init=False, repr=False)
    _census: ExpectedLinkManifestCensus = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _text(self.federation_root, "ExpectedLinkManifest.federation_root")
        if not isinstance(self.extraction_capability, LinkExtractionCapability):
            raise FederationAssemblyError(
                "manifest extraction_capability must be typed")
        documents = tuple(self.documents)
        if any(not isinstance(item, ExpectedDocumentLinks) for item in documents):
            raise FederationAssemblyError(
                "manifest documents must contain ExpectedDocumentLinks")
        context_keys: set[tuple[str, tuple[str, ...]]] = set()
        expected_paths: set[tuple[str, ...]] = set()
        local_aliases: set[tuple[tuple[str, tuple[str, ...]], str]] = set()
        bindings: list[LinkAuthorityBinding] = []
        for item in documents:
            if item.context.federation_root != self.federation_root:
                raise FederationAssemblyError(
                    "manifest document belongs to a different federation root")
            key = _context_key(item.context)
            if key in context_keys:
                raise FederationAssemblyError(
                    "duplicate document occurrence path in expected-link manifest")
            context_keys.add(key)
            for link in item.links:
                local_alias = (key, link.local_link_element_id)
                if local_alias in local_aliases:
                    # ExpectedDocumentLinks already rejects this, but keeping
                    # the law here makes the manifest census self-defending.
                    raise FederationAssemblyError(
                        "duplicate local link alias in expected-link manifest")
                local_aliases.add(local_alias)
                if link.instance_unique_id is None:
                    continue
                child_path = (*item.context.link_instance_chain,
                              link.instance_unique_id)
                if child_path in expected_paths:
                    raise FederationAssemblyError(
                        "duplicate expected link occurrence path")
                expected_paths.add(child_path)
                # An unloaded slot can retain names/ids in Revit metadata, but
                # it cannot authorize a measured child-frame transform.  Keep
                # the row in the census as unbound until it is actually loaded.
                if (link.loaded
                        and link.linked_document_identity is not None):
                    bindings.append(LinkAuthorityBinding(
                        expectation_id=link.expectation_id,
                        parent_document_identity=item.document_identity,
                        parent_context=item.context,
                        local_link_element_id=link.local_link_element_id,
                        link_instance_unique_id=link.instance_unique_id,
                        linked_document_identity=link.linked_document_identity,
                        child_context=FederationContext(
                            self.federation_root, child_path),
                    ))
        records = sum(len(item.links) for item in documents)
        census = ExpectedLinkManifestCensus(
            records=records,
            local_aliases=len(local_aliases),
            authority_bindings=len(bindings),
            unbound_records=records - len(bindings),
        )
        census.assert_balanced()
        object.__setattr__(self, "documents", documents)
        object.__setattr__(self, "_authority_bindings", tuple(sorted(
            bindings, key=lambda item: item.key)))
        object.__setattr__(self, "_census", census)

    @property
    def authority_bindings(self) -> tuple[LinkAuthorityBinding, ...]:
        return self._authority_bindings

    @property
    def census(self) -> ExpectedLinkManifestCensus:
        return self._census

    def authority_binding(
        self,
        *,
        parent_document_identity: DocumentIdentity,
        parent_context: FederationContext,
        local_link_element_id: str,
        link_instance_unique_id: str,
        linked_document_identity: DocumentIdentity,
    ) -> LinkAuthorityBinding:
        """Resolve only a complete five-way authority join.

        There is intentionally no lookup by local id, linked document, or
        path alone: all three can legitimately repeat elsewhere.
        """

        if not isinstance(parent_document_identity, DocumentIdentity):
            raise FederationAssemblyError(
                "authority lookup parent_document_identity must be typed")
        if not isinstance(parent_context, FederationContext):
            raise FederationAssemblyError(
                "authority lookup parent_context must be typed")
        _text(local_link_element_id,
              "authority lookup local_link_element_id")
        _text(link_instance_unique_id,
              "authority lookup link_instance_unique_id")
        if not isinstance(linked_document_identity, DocumentIdentity):
            raise FederationAssemblyError(
                "authority lookup linked_document_identity must be typed")
        matches = tuple(binding for binding in self._authority_bindings if (
            binding.parent_document_identity == parent_document_identity
            and binding.parent_context == parent_context
            and binding.local_link_element_id == local_link_element_id
            and binding.link_instance_unique_id == link_instance_unique_id
            and binding.linked_document_identity == linked_document_identity))
        if len(matches) != 1:
            raise FederationAssemblyError(
                "no exact link authority binding for the complete join")
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "federation_root": self.federation_root,
            "extraction_capability": self.extraction_capability.value,
            "census": self.census.to_dict(),
            "documents": [item.to_dict() for item in sorted(
                self.documents,
                key=lambda row: _context_key(row.context))],
            "authority_bindings": [binding.to_dict()
                                   for binding in self._authority_bindings],
        }


@dataclass(frozen=True, slots=True)
class FederationNodeRefusal:
    reason: FederationRefusalReason
    graph_index: int
    graph_path: tuple[str, ...] | None
    local_element_id: str
    identity_gaps: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reason, FederationRefusalReason):
            raise FederationAssemblyError("node refusal reason must be typed")
        if (isinstance(self.graph_index, bool)
                or not isinstance(self.graph_index, int)
                or self.graph_index < 0):
            raise FederationAssemblyError(
                "node refusal graph_index must be a non-negative int")
        path = _path(self.graph_path, "node refusal graph_path")
        if (self.reason is FederationRefusalReason.NODE_OCCURRENCE_INCOMPLETE
                and path is None):
            raise FederationAssemblyError(
                "node occurrence refusal requires an exact graph path")
        _text(self.local_element_id, "node refusal local_element_id")
        if isinstance(self.identity_gaps, str):
            raise FederationAssemblyError(
                "node refusal identity_gaps must be a sequence")
        gaps = tuple(self.identity_gaps)
        if (not gaps or any(not isinstance(gap, str) or not gap.strip()
                            for gap in gaps)):
            raise FederationAssemblyError(
                "node refusal must name non-empty identity gaps")
        if len(gaps) != len(set(gaps)):
            raise FederationAssemblyError(
                "node refusal identity gaps must be unique")
        object.__setattr__(self, "graph_path", path)
        object.__setattr__(self, "identity_gaps", gaps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "graph_index": self.graph_index,
            "graph_path": (list(self.graph_path)
                           if self.graph_path is not None else None),
            "local_element_id": self.local_element_id,
            "identity_gaps": list(self.identity_gaps),
        }


@dataclass(frozen=True, slots=True)
class FederationGraphRefusal:
    reason: FederationRefusalReason
    graph_index: int
    doc_name: str
    nodes: int
    edges: int

    def __post_init__(self) -> None:
        if self.reason is not FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE:
            raise FederationAssemblyError(
                "graph refusal reason must be graph_context_incomplete")
        if (isinstance(self.graph_index, bool)
                or not isinstance(self.graph_index, int)
                or self.graph_index < 0):
            raise FederationAssemblyError(
                "graph refusal graph_index must be a non-negative int")
        _text(self.doc_name, "graph refusal doc_name")
        for name, count in (("nodes", self.nodes), ("edges", self.edges)):
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise FederationAssemblyError(
                    f"graph refusal {name} must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "graph_index": self.graph_index,
            "doc_name": self.doc_name,
            "nodes": self.nodes,
            "edges": self.edges,
        }


@dataclass(frozen=True, slots=True)
class FederationSourceRowRefusal:
    """An upstream BuildingGraph row refusal retained by the federation."""

    graph_index: int
    graph_path: tuple[str, ...] | None
    doc_name: str
    reason: str
    count: int

    def __post_init__(self) -> None:
        if isinstance(self.graph_index, bool) or not isinstance(
                self.graph_index, int) or self.graph_index < 0:
            raise FederationAssemblyError(
                "source refusal graph_index must be non-negative int")
        _text(self.reason, "source refusal reason")
        _text(self.doc_name, "source refusal doc_name")
        object.__setattr__(
            self, "graph_path",
            _path(self.graph_path, "source refusal graph_path"))
        if isinstance(self.count, bool) or not isinstance(
                self.count, int) or self.count <= 0:
            raise FederationAssemblyError(
                "source refusal count must be a positive int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_index": self.graph_index,
            "graph_path": (list(self.graph_path)
                           if self.graph_path is not None else None),
            "doc_name": self.doc_name,
            "reason": self.reason,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class FederationGap:
    """A preserved edge or manifest fact that could not become topology."""

    scope: FederationGapScope
    reason: FederationGapReason
    graph_path: tuple[str, ...] | None = None
    source_occurrence: OccurrenceIdentity | None = None
    target_occurrence: OccurrenceIdentity | None = None
    relation: Relation | None = None
    local_source: str | None = None
    local_target: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, FederationGapScope):
            raise FederationAssemblyError("federation gap scope must be typed")
        if not isinstance(self.reason, FederationGapReason):
            raise FederationAssemblyError("federation gap reason must be typed")
        if (self.source_occurrence is not None
                and not isinstance(self.source_occurrence, OccurrenceIdentity)):
            raise FederationAssemblyError("gap source occurrence must be typed")
        if (self.target_occurrence is not None
                and not isinstance(self.target_occurrence, OccurrenceIdentity)):
            raise FederationAssemblyError("gap target occurrence must be typed")
        if self.relation is not None and not isinstance(self.relation, Relation):
            raise FederationAssemblyError("gap relation must be typed")
        path = _path(self.graph_path, "federation gap graph_path")
        for name, value in (("local_source", self.local_source),
                            ("local_target", self.local_target)):
            if value is not None:
                _text(value, f"federation gap {name}")
        if self.scope is FederationGapScope.EDGE:
            if self.reason not in _EDGE_GAP_REASONS:
                raise FederationAssemblyError(
                    "edge gap carries a non-edge reason")
            if self.relation is None or self.local_source is None \
                    or self.local_target is None:
                raise FederationAssemblyError(
                    "edge gap must retain relation and both local aliases")
        elif self.scope is FederationGapScope.CAPABILITY:
            if self.reason not in _CAPABILITY_GAP_REASONS:
                raise FederationAssemblyError(
                    "capability gap carries a non-capability reason")
            if (self.relation is not None or self.source_occurrence is not None
                    or self.target_occurrence is not None):
                raise FederationAssemblyError(
                    "capability gap cannot masquerade as an edge")
        else:
            if self.reason not in _MANIFEST_GAP_REASONS:
                raise FederationAssemblyError(
                    "manifest gap carries a non-manifest reason")
            if (self.relation is not None or self.source_occurrence is not None
                    or self.target_occurrence is not None):
                raise FederationAssemblyError(
                    "manifest gap cannot masquerade as an edge")
        occurrences = tuple(item for item in (
            self.source_occurrence, self.target_occurrence) if item is not None)
        if len({item.federation_root for item in occurrences}) > 1:
            raise FederationAssemblyError(
                "gap occurrences belong to different federation roots")
        if path is not None and any(
                item.link_instance_chain != path for item in occurrences):
            raise FederationAssemblyError(
                "gap occurrence does not belong to its exact graph path")
        if not isinstance(self.evidence, Mapping):
            raise FederationAssemblyError("gap evidence must be a mapping")
        object.__setattr__(self, "graph_path", path)
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "reason": self.reason.value,
            "graph_path": (list(self.graph_path)
                           if self.graph_path is not None else None),
            "source_occurrence": (self.source_occurrence.key
                                  if self.source_occurrence is not None else None),
            "target_occurrence": (self.target_occurrence.key
                                  if self.target_occurrence is not None else None),
            "relation": self.relation.value if self.relation is not None else None,
            "local_source": self.local_source,
            "local_target": self.local_target,
            "evidence": _canonical(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ExpectedLinkResolution:
    expectation_id: str
    parent_context: FederationContext
    local_link_element_id: str
    link_instance_unique_id: str | None
    child_context: FederationContext | None
    authority_binding_key: str | None
    satisfied: bool
    reasons: tuple[FederationGapReason, ...]

    def __post_init__(self) -> None:
        _text(self.expectation_id, "link resolution expectation_id")
        if not isinstance(self.parent_context, FederationContext):
            raise FederationAssemblyError(
                "link resolution parent_context must be typed")
        _text(self.local_link_element_id,
              "link resolution local_link_element_id")
        if self.link_instance_unique_id is not None:
            _text(self.link_instance_unique_id,
                  "link resolution link_instance_unique_id")
        if (self.child_context is not None
                and not isinstance(self.child_context, FederationContext)):
            raise FederationAssemblyError(
                "link resolution child_context must be typed or null")
        if self.authority_binding_key is not None:
            _text(self.authority_binding_key,
                  "link resolution authority_binding_key")
        if not isinstance(self.satisfied, bool):
            raise FederationAssemblyError(
                "link resolution satisfied must be boolean")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, FederationGapReason)
               for reason in reasons):
            raise FederationAssemblyError(
                "link resolution reasons must be typed")
        if len(reasons) != len(set(reasons)):
            raise FederationAssemblyError(
                "link resolution reasons must be unique")
        if self.satisfied == bool(reasons):
            raise FederationAssemblyError(
                "link resolution satisfied flag contradicts its reasons")
        if ((self.link_instance_unique_id is None)
                != (self.child_context is None)):
            raise FederationAssemblyError(
                "link resolution path and child context disagree")
        if self.child_context is not None:
            if self.link_instance_unique_id is None:  # guarded above
                raise FederationAssemblyError(
                    "link resolution child context lacks exact link path")
            expected_child = FederationContext(
                self.parent_context.federation_root,
                (*self.parent_context.link_instance_chain,
                 self.link_instance_unique_id),
            )
            if self.child_context != expected_child:
                raise FederationAssemblyError(
                    "link resolution child context contradicts exact link path")
        if (self.authority_binding_key is not None
                and self.child_context is None):
            raise FederationAssemblyError(
                "link resolution binding requires a child context")
        if self.satisfied and self.authority_binding_key is None:
            raise FederationAssemblyError(
                "satisfied link resolution requires authority binding")
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "parent_context": self.parent_context.as_dict(),
            "local_link_element_id": self.local_link_element_id,
            "link_instance_unique_id": self.link_instance_unique_id,
            "child_context": (self.child_context.as_dict()
                              if self.child_context is not None else None),
            "authority_binding_key": self.authority_binding_key,
            "satisfied": self.satisfied,
            "reasons": [reason.value for reason in self.reasons],
        }


@dataclass(frozen=True, slots=True)
class FederatedNode:
    occurrence: OccurrenceIdentity
    local_element_id: str
    document_name: str
    node: GraphNode
    section_snapshot: Mapping[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OccurrenceIdentity):
            raise FederationAssemblyError("FederatedNode occurrence must be typed")
        if not isinstance(self.node, GraphNode):
            raise FederationAssemblyError("FederatedNode node must be GraphNode")
        _text(self.local_element_id, "FederatedNode.local_element_id")
        _text(self.document_name, "FederatedNode.document_name")
        if self.local_element_id != self.node.local_element_id:
            raise FederationAssemblyError(
                "FederatedNode local alias disagrees with its local node")
        if self.node.occurrence_identity != self.occurrence:
            raise FederationAssemblyError(
                "FederatedNode occurrence disagrees with its local node")
        object.__setattr__(
            self, "section_snapshot", _freeze_json(self.node.section))

    @property
    def definition(self) -> DefinitionIdentity:
        return self.occurrence.definition

    @property
    def key(self) -> OccurrenceIdentity:
        return self.occurrence

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.occurrence.key,
            "occurrence": self.occurrence.as_dict(),
            "definition_key": self.definition.key,
            "local_alias": {
                "document_name": self.document_name,
                "element_id": self.local_element_id,
                "level_element_id": self.node.level_id,
                "type_element_id": self.node.type_id,
            },
            "category": self.node.category,
            "authority": self.node.authority.value,
            "authority_source": self.node.authority_source.value,
            "existence": self.node.existence.value,
            "type_name": self.node.type_name,
            "host_source": self.node.host_source,
            "section": _canonical(self.section_snapshot),
        }


@dataclass(frozen=True, slots=True)
class FederatedEdge:
    relation: Relation
    src: OccurrenceIdentity
    dst: OccurrenceIdentity
    modality: Modality
    refuted_by: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.relation, Relation):
            raise FederationAssemblyError("federated edge relation must be typed")
        if not isinstance(self.src, OccurrenceIdentity) \
                or not isinstance(self.dst, OccurrenceIdentity):
            raise FederationAssemblyError(
                "federated edge endpoints must be occurrence identities")
        if not isinstance(self.modality, Modality):
            raise FederationAssemblyError("federated edge modality must be typed")
        if self.modality is Modality.REFUTED:
            _text(self.refuted_by, "FederatedEdge.refuted_by")
        elif self.refuted_by is not None:
            raise FederationAssemblyError(
                "refuted_by is forbidden unless modality is refuted")
        if not isinstance(self.evidence, Mapping):
            raise FederationAssemblyError("edge evidence must be a mapping")
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    @property
    def key(self) -> tuple[str, str, str, str, str, str]:
        evidence = json.dumps(_canonical(self.evidence), ensure_ascii=False,
                              sort_keys=True, separators=(",", ":"))
        return (self.relation.value, self.src.key, self.dst.key,
                self.modality.value, self.refuted_by or "", evidence)

    @property
    def truth_key(self) -> tuple[str, str, str]:
        """One logical relation fact; modality/evidence cannot duplicate it."""

        src, dst = self.src.key, self.dst.key
        if self.relation in {
            Relation.BOUNDED_BY_SAME_WALL,
            Relation.OPENING_POINT_TOUCHES_ROOM,
        }:
            src, dst = sorted((src, dst))
        return (self.relation.value, src, dst)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation.value,
            "src": self.src.key,
            "dst": self.dst.key,
            "modality": self.modality.value,
            "refuted_by": self.refuted_by,
            "evidence": _canonical(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class FederationCensus:
    input_graphs: int
    assembled_graphs: int
    refused_graphs: int
    input_rows: int
    source_refused_rows: int
    input_nodes: int
    assembled_nodes: int
    refused_nodes: int
    input_edges: int
    assembled_edges: int
    edge_gaps: int
    expected_links: int
    satisfied_links: int
    incomplete_links: int

    def __post_init__(self) -> None:
        self.assert_balanced()

    def assert_balanced(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in values):
            raise FederationAssemblyError(
                "federation census counts must be non-negative integers")
        if self.input_graphs != self.assembled_graphs + self.refused_graphs:
            raise FederationAssemblyError("federation graph census is unbalanced")
        if self.input_rows != self.input_nodes + self.source_refused_rows:
            raise FederationAssemblyError(
                "federation source-row census is unbalanced")
        if self.input_nodes != self.assembled_nodes + self.refused_nodes:
            raise FederationAssemblyError("federation node census is unbalanced")
        if self.input_edges != self.assembled_edges + self.edge_gaps:
            raise FederationAssemblyError("federation edge census is unbalanced")
        if self.expected_links != self.satisfied_links + self.incomplete_links:
            raise FederationAssemblyError("expected-link census is unbalanced")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class FederatedScope:
    """Occurrence-key-only scope; local ElementId strings are rejected."""

    scope_id: str
    occurrences: frozenset[OccurrenceIdentity]

    def __post_init__(self) -> None:
        _text(self.scope_id, "FederatedScope.scope_id")
        occurrences = frozenset(self.occurrences)
        if any(not isinstance(item, OccurrenceIdentity) for item in occurrences):
            raise FederationAssemblyError(
                "federated scope accepts OccurrenceIdentity only; local "
                "ElementId aliases are forbidden")
        object.__setattr__(self, "occurrences", occurrences)


@dataclass(frozen=True, slots=True)
class FederationViewSummary:
    federation_root: str
    complete: bool
    graphs: int
    nodes: int
    definitions: int
    edges: int
    max_link_depth: int
    relations: Mapping[str, int]
    gaps: Mapping[str, int]
    refusals: Mapping[str, int]
    census: FederationCensus

    def to_dict(self) -> dict[str, Any]:
        return {
            "federation_root": self.federation_root,
            "complete": self.complete,
            "graphs": self.graphs,
            "nodes": self.nodes,
            "definitions": self.definitions,
            "edges": self.edges,
            "max_link_depth": self.max_link_depth,
            "relations": dict(sorted(self.relations.items())),
            "gaps": dict(sorted(self.gaps.items())),
            "refusals": dict(sorted(self.refusals.items())),
            "census": self.census.to_dict(),
        }


class FederatedBuildingGraph:
    """One federation whose only global address is OccurrenceIdentity."""

    __slots__ = (
        "federation_root", "manifest", "census", "_nodes", "_edges",
        "_gaps", "_node_refusals", "_graph_refusals", "_link_resolutions",
        "_source_row_refusals", "_graph_paths", "_by_definition", "_out",
        "_in",
    )

    def __init__(
        self,
        *,
        federation_root: str,
        manifest: ExpectedLinkManifest,
        graph_paths: Iterable[tuple[str, ...]],
        nodes: Iterable[FederatedNode],
        edges: Iterable[FederatedEdge],
        gaps: Iterable[FederationGap],
        node_refusals: Iterable[FederationNodeRefusal],
        graph_refusals: Iterable[FederationGraphRefusal],
        source_row_refusals: Iterable[FederationSourceRowRefusal],
        link_resolutions: Iterable[ExpectedLinkResolution],
        census: FederationCensus,
    ) -> None:
        self.federation_root = _text(federation_root, "federation_root")
        if not isinstance(manifest, ExpectedLinkManifest):
            raise FederationAssemblyError(
                "federation manifest must be ExpectedLinkManifest")
        if manifest.federation_root != self.federation_root:
            raise FederationAssemblyError(
                "federation manifest belongs to another root")
        self.manifest = manifest
        self._graph_paths = tuple(sorted(
            _path(path, "assembled graph path", allow_none=False)
            for path in graph_paths))
        if len(self._graph_paths) != len(set(self._graph_paths)):
            raise FederationAssemblyError("assembled graph paths are duplicated")
        nodes_by_occurrence: dict[OccurrenceIdentity, FederatedNode] = {}
        by_definition: dict[DefinitionIdentity, list[OccurrenceIdentity]] = (
            defaultdict(list))
        for node in nodes:
            if not isinstance(node, FederatedNode):
                raise FederationAssemblyError(
                    "federation nodes must contain FederatedNode")
            if node.occurrence.federation_root != self.federation_root:
                raise FederationAssemblyError("node belongs to another federation")
            if node.key in nodes_by_occurrence:
                raise FederationAssemblyError(
                    f"duplicate occurrence identity {node.key.key}")
            nodes_by_occurrence[node.key] = node
            by_definition[node.definition].append(node.key)
        for occurrences in by_definition.values():
            occurrences.sort(key=lambda item: item.key)
        self._nodes = MappingProxyType(nodes_by_occurrence)
        self._by_definition = MappingProxyType({
            definition: tuple(occurrences)
            for definition, occurrences in by_definition.items()
        })
        edge_rows = tuple(edges)
        if any(not isinstance(edge, FederatedEdge) for edge in edge_rows):
            raise FederationAssemblyError(
                "federation edges must contain FederatedEdge")
        truth_keys = [edge.truth_key for edge in edge_rows]
        if len(truth_keys) != len(set(truth_keys)):
            raise FederationAssemblyError(
                "duplicate or contradictory federated edge truth")
        self._edges = tuple(sorted(edge_rows, key=lambda edge: edge.key))

        gap_rows = tuple(gaps)
        if any(not isinstance(gap, FederationGap) for gap in gap_rows):
            raise FederationAssemblyError(
                "federation gaps must contain FederationGap")
        gap_keys = [json.dumps(
            gap.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":")) for gap in gap_rows]
        if len(gap_keys) != len(set(gap_keys)):
            raise FederationAssemblyError("duplicate federation gap")
        self._gaps = tuple(sorted(
            gap_rows,
            key=lambda gap: json.dumps(gap.to_dict(), ensure_ascii=False,
                                       sort_keys=True, separators=(",", ":"))))

        node_refusal_rows = tuple(node_refusals)
        if any(not isinstance(item, FederationNodeRefusal)
               for item in node_refusal_rows):
            raise FederationAssemblyError(
                "node refusals must contain FederationNodeRefusal")
        node_refusal_keys = [
            (item.graph_index, item.graph_path, item.local_element_id)
            for item in node_refusal_rows]
        if len(node_refusal_keys) != len(set(node_refusal_keys)):
            raise FederationAssemblyError("duplicate node refusal")
        self._node_refusals = tuple(sorted(
            node_refusal_rows,
            key=lambda item: (item.graph_index, item.local_element_id,
                              item.reason.value)))

        graph_refusal_rows = tuple(graph_refusals)
        if any(not isinstance(item, FederationGraphRefusal)
               for item in graph_refusal_rows):
            raise FederationAssemblyError(
                "graph refusals must contain FederationGraphRefusal")
        if len({item.graph_index for item in graph_refusal_rows}) \
                != len(graph_refusal_rows):
            raise FederationAssemblyError("duplicate graph refusal")
        self._graph_refusals = tuple(sorted(
            graph_refusal_rows,
            key=lambda item: (item.graph_index, item.reason.value)))

        source_refusal_rows = tuple(source_row_refusals)
        if any(not isinstance(item, FederationSourceRowRefusal)
               for item in source_refusal_rows):
            raise FederationAssemblyError(
                "source refusals must contain FederationSourceRowRefusal")
        source_refusal_keys = [
            (item.graph_index, item.graph_path, item.reason)
            for item in source_refusal_rows]
        if len(source_refusal_keys) != len(set(source_refusal_keys)):
            raise FederationAssemblyError("duplicate source-row refusal")
        self._source_row_refusals = tuple(sorted(
            source_refusal_rows,
            key=lambda item: (
                item.graph_index, item.reason, item.graph_path or ())))

        resolution_rows = tuple(link_resolutions)
        if any(not isinstance(item, ExpectedLinkResolution)
               for item in resolution_rows):
            raise FederationAssemblyError(
                "link resolutions must contain ExpectedLinkResolution")
        resolution_keys = [
            (_context_key(item.parent_context), item.expectation_id)
            for item in resolution_rows]
        if len(resolution_keys) != len(set(resolution_keys)):
            raise FederationAssemblyError("duplicate expected-link resolution")
        self._link_resolutions = tuple(sorted(
            resolution_rows,
            key=lambda item: (
                item.parent_context.link_instance_chain,
                item.expectation_id)))
        if not isinstance(census, FederationCensus):
            raise FederationAssemblyError(
                "federation census must be FederationCensus")
        self.census = census
        census.assert_balanced()
        if len(self._nodes) != census.assembled_nodes:
            raise FederationAssemblyError("node census disagrees with assembly")
        if len(self._graph_paths) != census.assembled_graphs:
            raise FederationAssemblyError("graph path census disagrees")
        if len(self._edges) != census.assembled_edges:
            raise FederationAssemblyError("edge census disagrees with assembly")
        if len(self._node_refusals) != census.refused_nodes:
            raise FederationAssemblyError("node refusal census disagrees")
        if len(self._graph_refusals) != census.refused_graphs:
            raise FederationAssemblyError("graph refusal census disagrees")
        if sum(item.count for item in self._source_row_refusals) \
                != census.source_refused_rows:
            raise FederationAssemblyError(
                "source-row refusal census disagrees")
        if sum(gap.scope is FederationGapScope.EDGE for gap in self._gaps) \
                != census.edge_gaps:
            raise FederationAssemblyError("edge gap census disagrees")
        if census.expected_links != manifest.census.records:
            raise FederationAssemblyError(
                "federation and expected-link manifest censuses disagree")
        if len(self._link_resolutions) != census.expected_links:
            raise FederationAssemblyError(
                "expected-link resolution census disagrees")
        if sum(item.satisfied for item in self._link_resolutions) \
                != census.satisfied_links:
            raise FederationAssemblyError(
                "satisfied-link census disagrees with resolutions")
        manifest_rows = {
            (_context_key(document.context), link.expectation_id): link
            for document in manifest.documents for link in document.links}
        for resolution in self._link_resolutions:
            key = (_context_key(resolution.parent_context),
                   resolution.expectation_id)
            link = manifest_rows.get(key)
            if link is None:
                raise FederationAssemblyError(
                    "link resolution has no exact manifest row")
            if (resolution.local_link_element_id
                    != link.local_link_element_id
                    or resolution.link_instance_unique_id
                    != link.instance_unique_id):
                raise FederationAssemblyError(
                    "link resolution contradicts its exact manifest row")
            binding = next((item for item in manifest.authority_bindings
                            if (item.parent_context == resolution.parent_context
                                and item.expectation_id
                                == resolution.expectation_id)), None)
            expected_binding_key = binding.key if binding is not None else None
            if resolution.authority_binding_key != expected_binding_key:
                raise FederationAssemblyError(
                    "link resolution authority binding was swapped")
        out: dict[OccurrenceIdentity, list[FederatedEdge]] = defaultdict(list)
        incoming: dict[OccurrenceIdentity, list[FederatedEdge]] = defaultdict(list)
        for edge in self._edges:
            if edge.src not in self._nodes or edge.dst not in self._nodes:
                raise FederationAssemblyError(
                    "federated edge references an unassembled occurrence")
            out[edge.src].append(edge)
            incoming[edge.dst].append(edge)
        self._out = MappingProxyType({
            occurrence: tuple(items) for occurrence, items in out.items()})
        self._in = MappingProxyType({
            occurrence: tuple(items)
            for occurrence, items in incoming.items()})

    @property
    def nodes(self) -> Mapping[OccurrenceIdentity, FederatedNode]:
        return self._nodes

    @property
    def edges(self) -> tuple[FederatedEdge, ...]:
        return self._edges

    @property
    def graph_paths(self) -> tuple[tuple[str, ...], ...]:
        return self._graph_paths

    @property
    def gaps(self) -> tuple[FederationGap, ...]:
        return self._gaps

    @property
    def node_refusals(self) -> tuple[FederationNodeRefusal, ...]:
        return self._node_refusals

    @property
    def graph_refusals(self) -> tuple[FederationGraphRefusal, ...]:
        return self._graph_refusals

    @property
    def source_row_refusals(self) -> tuple[FederationSourceRowRefusal, ...]:
        return self._source_row_refusals

    @property
    def link_resolutions(self) -> tuple[ExpectedLinkResolution, ...]:
        return self._link_resolutions

    @property
    def link_authority_bindings(self) -> tuple[LinkAuthorityBinding, ...]:
        return self.manifest.authority_bindings

    @property
    def complete(self) -> bool:
        return (not self._gaps and not self._node_refusals
                and not self._graph_refusals
                and not self._source_row_refusals
                and self.census.incomplete_links == 0)

    def node(self, occurrence: OccurrenceIdentity) -> FederatedNode:
        if not isinstance(occurrence, OccurrenceIdentity):
            raise FederationAssemblyError(
                "federation lookup requires OccurrenceIdentity; local "
                "ElementId aliases are forbidden")
        try:
            return self._nodes[occurrence]
        except KeyError:
            raise FederationAssemblyError(
                f"occurrence {occurrence.key} is not assembled") from None

    def occurrences_for_definition(
        self, definition: DefinitionIdentity,
    ) -> tuple[OccurrenceIdentity, ...]:
        if not isinstance(definition, DefinitionIdentity):
            raise FederationAssemblyError(
                "definition lookup requires DefinitionIdentity")
        return tuple(self._by_definition.get(definition, ()))

    def out_edges(self, occurrence: OccurrenceIdentity) -> tuple[FederatedEdge, ...]:
        self.node(occurrence)
        return tuple(self._out.get(occurrence, ()))

    def in_edges(self, occurrence: OccurrenceIdentity) -> tuple[FederatedEdge, ...]:
        self.node(occurrence)
        return tuple(self._in.get(occurrence, ()))

    def scope(
        self, scope_id: str, occurrences: Iterable[OccurrenceIdentity],
    ) -> FederatedScope:
        scope = FederatedScope(scope_id, frozenset(occurrences))
        missing = tuple(sorted(
            (item.key for item in scope.occurrences if item not in self._nodes)))
        if missing:
            raise FederationAssemblyError(
                f"federated scope names unassembled occurrences: {missing}")
        return scope

    def summary(self) -> FederationViewSummary:
        relation_counts = Counter(edge.relation.value for edge in self._edges)
        gap_counts = Counter(gap.reason.value for gap in self._gaps)
        refusal_counts = Counter(
            item.reason.value for item in self._node_refusals)
        refusal_counts.update(
            item.reason.value for item in self._graph_refusals)
        for item in self._source_row_refusals:
            refusal_counts[item.reason] += item.count
        return FederationViewSummary(
            federation_root=self.federation_root,
            complete=self.complete,
            graphs=self.census.assembled_graphs,
            nodes=len(self._nodes),
            definitions=len(self._by_definition),
            edges=len(self._edges),
            max_link_depth=max((len(path) for path in self._graph_paths),
                               default=0),
            relations=dict(sorted(relation_counts.items())),
            gaps=dict(sorted(gap_counts.items())),
            refusals=dict(sorted(refusal_counts.items())),
            census=self.census,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "kir-federated-building-graph/1",
            "summary": self.summary().to_dict(),
            "link_manifest": self.manifest.to_dict(),
            "document_paths": [list(path) for path in self._graph_paths],
            "nodes": [node.to_dict() for node in sorted(
                self._nodes.values(), key=lambda item: item.occurrence.key)],
            "edges": [edge.to_dict() for edge in self._edges],
            "gaps": [gap.to_dict() for gap in self._gaps],
            "node_refusals": [item.to_dict() for item in self._node_refusals],
            "graph_refusals": [item.to_dict() for item in self._graph_refusals],
            "source_row_refusals": [
                item.to_dict() for item in self._source_row_refusals],
            "expected_links": [item.to_dict()
                               for item in self._link_resolutions],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"))


def _edge_gap(
    *, graph_path: tuple[str, ...] | None, edge: GraphEdge,
    src: OccurrenceIdentity | None, dst: OccurrenceIdentity | None,
    reason: FederationGapReason,
) -> FederationGap:
    evidence = dict(edge.evidence)
    evidence["local_modality"] = edge.modality.value
    evidence["local_refuted_by"] = edge.refuted_by
    return FederationGap(
        scope=FederationGapScope.EDGE,
        reason=reason,
        graph_path=graph_path,
        source_occurrence=src,
        target_occurrence=dst,
        relation=edge.relation,
        local_source=edge.src,
        local_target=edge.dst,
        evidence=evidence,
    )


def assemble_federation(
    graphs: Iterable[BuildingGraph],
    *,
    manifest: ExpectedLinkManifest,
) -> FederatedBuildingGraph:
    """Assemble graphs without ever resolving an endpoint by local id globally."""
    if not isinstance(manifest, ExpectedLinkManifest):
        raise FederationAssemblyError(
            "assemble_federation requires an ExpectedLinkManifest")
    graph_list = tuple(graphs)
    if any(not isinstance(graph, BuildingGraph) for graph in graph_list):
        raise FederationAssemblyError("graphs must contain BuildingGraph values")

    path_to_graph: dict[tuple[str, ...], tuple[int, BuildingGraph]] = {}
    graph_refusals: list[FederationGraphRefusal] = []
    node_refusals: list[FederationNodeRefusal] = []
    source_row_refusals: list[FederationSourceRowRefusal] = []
    gaps: list[FederationGap] = []
    accepted: list[tuple[int, BuildingGraph]] = []

    for index, graph in enumerate(graph_list):
        context = graph.federation_context
        for reason, count in sorted(graph.census.refusals.items()):
            if count:
                source_row_refusals.append(FederationSourceRowRefusal(
                    graph_index=index,
                    graph_path=(context.link_instance_chain
                                if context is not None else None),
                    doc_name=graph.doc_name,
                    reason=reason,
                    count=count,
                ))
        if context is not None:
            if context.federation_root != manifest.federation_root:
                raise FederationAssemblyError(
                    "cannot assemble graphs from different federation roots")
            path = context.link_instance_chain
            if path in path_to_graph:
                raise FederationAssemblyError(
                    f"duplicate document occurrence path {path!r}")
            path_to_graph[path] = (index, graph)
        if context is None or graph.document_identity is None:
            graph_refusals.append(FederationGraphRefusal(
                FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE,
                index, graph.doc_name, len(graph.nodes), len(graph.edges)))
            for node in graph.nodes.values():
                node_refusals.append(FederationNodeRefusal(
                    FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE,
                    index,
                    (context.link_instance_chain if context is not None else None),
                    node.local_element_id,
                    tuple(gap.value for gap in node.identity_gaps),
                ))
            for edge in graph.edges:
                gaps.append(_edge_gap(
                    graph_path=(context.link_instance_chain
                                if context is not None else None),
                    edge=edge, src=None, dst=None,
                    reason=FederationGapReason.GRAPH_CONTEXT_INCOMPLETE))
            continue
        accepted.append((index, graph))

    assembled_nodes: dict[OccurrenceIdentity, FederatedNode] = {}
    local_occurrences: dict[int, dict[str, OccurrenceIdentity]] = {}
    for index, graph in accepted:
        assert graph.federation_context is not None
        assert graph.document_identity is not None
        local: dict[str, OccurrenceIdentity] = {}
        for node in graph.nodes.values():
            occurrence = node.occurrence_identity
            if not node.identity_authoritative or occurrence is None:
                node_refusals.append(FederationNodeRefusal(
                    FederationRefusalReason.NODE_OCCURRENCE_INCOMPLETE,
                    index, graph.federation_context.link_instance_chain,
                    node.local_element_id,
                    tuple(gap.value for gap in node.identity_gaps),
                ))
                continue
            if (occurrence.federation_root != manifest.federation_root
                    or occurrence.link_instance_chain
                    != graph.federation_context.link_instance_chain
                    or occurrence.definition.document != graph.document_identity):
                raise FederationAssemblyError(
                    "node occurrence contradicts its per-document graph context")
            if occurrence in assembled_nodes:
                raise FederationAssemblyError(
                    f"duplicate occurrence identity {occurrence.key}")
            wrapped = FederatedNode(
                occurrence, node.local_element_id, graph.doc_name, node)
            assembled_nodes[occurrence] = wrapped
            local[node.local_element_id] = occurrence
        local_occurrences[index] = local

    assembled_edges: list[FederatedEdge] = []
    for index, graph in accepted:
        path = graph.federation_context.link_instance_chain  # type: ignore[union-attr]
        local = local_occurrences[index]
        for edge in graph.edges:
            src = local.get(edge.src)
            dst = local.get(edge.dst)
            if src is not None and dst is not None:
                assembled_edges.append(FederatedEdge(
                    edge.relation, src, dst, edge.modality,
                    edge.refuted_by, edge.evidence))
                continue
            src_exists = edge.src in graph.nodes
            dst_exists = edge.dst in graph.nodes
            if ((src_exists and src is None) or (dst_exists and dst is None)):
                reason = FederationGapReason.EDGE_ENDPOINT_IDENTITY_INCOMPLETE
            elif not src_exists and not dst_exists:
                reason = FederationGapReason.EDGE_ENDPOINTS_NOT_IN_GRAPH
            elif not src_exists:
                reason = FederationGapReason.EDGE_SOURCE_NOT_IN_GRAPH
            else:
                reason = FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH
            gaps.append(_edge_gap(
                graph_path=path, edge=edge, src=src, dst=dst, reason=reason))

    coverage = {
        item.context.link_instance_chain: item for item in manifest.documents}
    for index, graph in accepted:
        context = graph.federation_context
        assert context is not None and graph.document_identity is not None
        item = coverage.get(context.link_instance_chain)
        if item is None:
            gaps.append(FederationGap(
                FederationGapScope.MANIFEST,
                FederationGapReason.MANIFEST_COVERAGE_MISSING,
                graph_path=context.link_instance_chain,
                evidence={"graph_index": index}))
        elif item.document_identity != graph.document_identity:
            raise FederationAssemblyError(
                "manifest document identity contradicts graph at same path")
    for path, item in coverage.items():
        graph_pair = path_to_graph.get(path)
        if graph_pair is None or graph_pair[1].document_identity is None:
            gaps.append(FederationGap(
                FederationGapScope.MANIFEST,
                FederationGapReason.MANIFEST_DOCUMENT_GRAPH_MISSING,
                graph_path=path,
                evidence={"document_identity": item.document_identity.value}))

    if () not in path_to_graph or path_to_graph[()][1].document_identity is None:
        gaps.append(FederationGap(
            FederationGapScope.MANIFEST,
            FederationGapReason.FEDERATION_ROOT_GRAPH_MISSING,
            graph_path=(), evidence={}))

    expected_paths: set[tuple[str, ...]] = set()
    resolutions: list[ExpectedLinkResolution] = []
    satisfied_links = 0
    bindings_by_record = {
        (_context_key(binding.parent_context), binding.expectation_id): binding
        for binding in manifest.authority_bindings
    }
    for document in manifest.documents:
        parent_path = document.context.link_instance_chain
        parent_graph = path_to_graph.get(parent_path)
        for link in document.links:
            reasons: list[FederationGapReason] = []
            child_context = None
            if parent_graph is None or parent_graph[1].document_identity is None:
                reasons.append(
                    FederationGapReason.EXPECTED_LINK_PARENT_GRAPH_MISSING)
            if not link.loaded:
                reasons.append(FederationGapReason.EXPECTED_LINK_UNLOADED)
            if link.linked_document_identity is None:
                reasons.append(
                    FederationGapReason.EXPECTED_LINK_IDENTITY_MISSING)
            if link.instance_unique_id is None:
                reasons.append(FederationGapReason.EXPECTED_LINK_PATH_MISSING)
            else:
                child_context = FederationContext(
                    manifest.federation_root,
                    (*parent_path, link.instance_unique_id))
                expected_paths.add(child_context.link_instance_chain)
                child_graph_pair = path_to_graph.get(
                    child_context.link_instance_chain)
                if not link.loaded and child_graph_pair is not None:
                    raise FederationAssemblyError(
                        "manifest says unloaded but a child graph occupies its path")
                if (link.loaded and link.linked_document_identity is not None):
                    if child_graph_pair is None \
                            or child_graph_pair[1].document_identity is None:
                        reasons.append(
                            FederationGapReason.EXTRACTOR_DIRECT_LINK_ONLY
                            if parent_path and manifest.extraction_capability
                            is LinkExtractionCapability.DIRECT_ONLY
                            else FederationGapReason.EXPECTED_LINK_GRAPH_MISSING)
                    elif (child_graph_pair[1].document_identity
                          != link.linked_document_identity):
                        raise FederationAssemblyError(
                            "expected linked identity contradicts child graph")
            reasons_tuple = tuple(dict.fromkeys(reasons))
            satisfied = not reasons_tuple
            if satisfied:
                satisfied_links += 1
            binding = bindings_by_record.get(
                (_context_key(document.context), link.expectation_id))
            resolutions.append(ExpectedLinkResolution(
                link.expectation_id,
                document.context,
                link.local_link_element_id,
                link.instance_unique_id,
                child_context,
                binding.key if binding is not None else None,
                satisfied,
                reasons_tuple,
            ))
            for reason in reasons_tuple:
                gaps.append(FederationGap(
                    (FederationGapScope.CAPABILITY
                     if reason is FederationGapReason.EXTRACTOR_DIRECT_LINK_ONLY
                     else FederationGapScope.MANIFEST),
                    reason,
                    graph_path=parent_path,
                    local_target=link.local_link_element_id,
                    evidence={
                        "expectation_id": link.expectation_id,
                        "loaded": link.loaded,
                        "instance_unique_id": link.instance_unique_id,
                        "linked_document_identity": (
                            link.linked_document_identity.value
                            if link.linked_document_identity is not None else None),
                        **dict(link.evidence),
                    },
                ))

    for path, (_index, graph) in path_to_graph.items():
        if path and graph.document_identity is not None and path not in expected_paths:
            gaps.append(FederationGap(
                FederationGapScope.MANIFEST,
                FederationGapReason.GRAPH_PATH_NOT_EXPECTED,
                graph_path=path,
                evidence={"document_identity": graph.document_identity.value}))

    edge_gap_count = sum(
        gap.scope is FederationGapScope.EDGE for gap in gaps)
    census = FederationCensus(
        input_graphs=len(graph_list),
        assembled_graphs=len(accepted),
        refused_graphs=len(graph_refusals),
        input_rows=sum(graph.census.rows_seen for graph in graph_list),
        source_refused_rows=sum(
            item.count for item in source_row_refusals),
        input_nodes=sum(len(graph.nodes) for graph in graph_list),
        assembled_nodes=len(assembled_nodes),
        refused_nodes=len(node_refusals),
        input_edges=sum(len(graph.edges) for graph in graph_list),
        assembled_edges=len(assembled_edges),
        edge_gaps=edge_gap_count,
        expected_links=sum(len(item.links) for item in manifest.documents),
        satisfied_links=satisfied_links,
        incomplete_links=(sum(len(item.links) for item in manifest.documents)
                          - satisfied_links),
    )
    return FederatedBuildingGraph(
        federation_root=manifest.federation_root,
        manifest=manifest,
        graph_paths=(
            graph.federation_context.link_instance_chain
            for _index, graph in accepted
            if graph.federation_context is not None),
        nodes=assembled_nodes.values(),
        edges=assembled_edges,
        gaps=gaps,
        node_refusals=node_refusals,
        graph_refusals=graph_refusals,
        source_row_refusals=source_row_refusals,
        link_resolutions=resolutions,
        census=census,
    )


__all__ = [
    "ExpectedDocumentLinks",
    "ExpectedLink",
    "ExpectedLinkManifest",
    "ExpectedLinkManifestCensus",
    "ExpectedLinkResolution",
    "FederatedBuildingGraph",
    "FederatedEdge",
    "FederatedNode",
    "FederatedScope",
    "FederationAssemblyError",
    "FederationCensus",
    "FederationGap",
    "FederationGapReason",
    "FederationGapScope",
    "FederationGraphRefusal",
    "FederationNodeRefusal",
    "FederationRefusalReason",
    "FederationSourceRowRefusal",
    "FederationViewSummary",
    "LinkExtractionCapability",
    "LinkAuthorityBinding",
    "assemble_federation",
]
