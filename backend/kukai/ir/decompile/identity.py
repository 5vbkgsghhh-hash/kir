"""Typed federated identity for observed Revit elements.

``ElementId`` is deliberately absent from the authoritative keys below.  It
is a document-local, reusable address and remains only a compatibility alias
on ``GraphNode``.  A definition is stable within its source document; an
occurrence additionally names the federation root and the exact chain of
Revit link instances through which that definition is observed.

«У НАС УЖЕ ЕСТЬ IDENTITY В L0» — ПРАВДА ПРО ЗАПИСЬ И ЛОЖЬ ПРО ЧТЕНИЕ
(замерено 11.08.2026, дерево `aecf6cff` + эта волна).

Производитель и потребитель этих фактов закрыты РАЗНЫМИ решениями, и это
сделано осознанно, а не забыто:

* ПИШЕТ — безусловно. C#-блок извлечения (`extract.py`, `__DocumentIdentityFact`
  / `__DocumentIdentityAuthoritative`) не закрыт ни одним флагом; единственная
  переменная окружения того модуля — `KUKAI_DECOMPILE_OUT`, и это путь вывода.
  Факты личности поедут в L0 с первого же живого извлечения.
* ЧИТАЕТ — только за выключенным флагом. `resolve_element_identity` и
  `identity_context_from_l0` вызываются РОВНО ИЗ ДВУХ МЕСТ:
  `building_graph.py:961` и `building_graph.py:992`, а весь этот модуль закрыт
  `building_graph_enabled()` (`KUKAI_IR_BUILDING_GRAPH`, умолчание ВЫКЛ).
  На живом пути типы личности разбираются схемой, но РАЗРЕШЕНИЕ личности не
  выполняется никем.

Следствие, ради которого абзац написан: пока флаг выключен, поле растёт и
никто его не читает. Это цена одного переизвлечения, а не дефект — но
утверждение «identity уже работает» неверно, и проверяется оно двумя
grep'ами по именам выше, а не за день.

Оговорка про хиты, которые НЕ считаются: `.identity` в
`decompile/dependencies.py` и `decompile/passport.py` — ДРУГОЙ тип
(`DependencyIdentity`, `definition.identity`), не поле `L0Document.identity`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

IDENTITY_SCHEMA = "kir-federated-identity/1"
L0_IDENTITY_METADATA_SCHEMA = "kir-l0-revit-identity/1"
PROJECT_INFORMATION_UNIQUE_ID = "project_information_unique_id"
CLOUD_PROJECT_MODEL_GUID = "cloud_project_model_guid"
REVIT_SERVER_CENTRAL_GUID = "revit_server_central_guid"

# ``ProjectInformation.UniqueId`` is still useful lineage evidence, but it is
# an Element.UniqueId.  Autodesk only contracts Element.UniqueId as stable
# *within the document*, so a Save As/copy may carry the same value.  Only
# sources whose Revit contract names the logical cloud/server model are
# promoted into graph authority automatically.
AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES = frozenset({
    CLOUD_PROJECT_MODEL_GUID,
    REVIT_SERVER_CENTRAL_GUID,
})
DOCUMENT_IDENTITY_SOURCES = frozenset({
    *AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES,
    PROJECT_INFORMATION_UNIQUE_ID,
})


class IdentityError(ValueError):
    """Identity input is malformed rather than merely unavailable."""


class IdentityStatus(str, Enum):
    AUTHORITATIVE = "authoritative"
    INCOMPLETE = "incomplete"


class IdentityGap(str, Enum):
    """Why an L0 node cannot carry an authoritative occurrence identity."""

    LEGACY_CONTEXT_ABSENT = "legacy_context_absent"
    MISSING_DOCUMENT_IDENTITY = "missing_document_identity"
    MISSING_FEDERATION_CONTEXT = "missing_federation_context"
    MISSING_ELEMENT_UNIQUE_ID = "missing_element_unique_id"
    SOURCE_DOCUMENT_IDENTITY_UNAVAILABLE = (
        "source_document_identity_unavailable")
    SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE = (
        "source_document_identity_not_authoritative")
    FEDERATION_ROOT_IDENTITY_UNAVAILABLE = (
        "federation_root_identity_unavailable")
    FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE = (
        "federation_root_identity_not_authoritative")
    LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE = (
        "link_instance_unique_id_unavailable")
    LINKED_DOCUMENT_UNAVAILABLE = "linked_document_unavailable"
    LINKED_DOCUMENT_IDENTITY_UNAVAILABLE = (
        "linked_document_identity_unavailable")
    LINKED_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE = (
        "linked_document_identity_not_authoritative")


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(f"{name} must be a non-empty string")
    return value


def _key(kind: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"schema": IDENTITY_SCHEMA, "kind": kind, **payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return f"kir:{kind}:v1:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    """Opaque stable identity supplied by the trusted document collector."""

    value: str

    def __post_init__(self) -> None:
        _required(self.value, "DocumentIdentity.value")

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True)
class FederationContext:
    """Where a source document occurrence lives in a federated model.

    ``link_instance_chain`` contains stable link-instance identities from the
    federation root to the source document.  It is empty for the root host
    document and ordered for nested links.
    """

    federation_root: str
    link_instance_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.federation_root, "FederationContext.federation_root")
        if isinstance(self.link_instance_chain, str):
            raise IdentityError("link_instance_chain must be a sequence, not str")
        chain = tuple(self.link_instance_chain)
        for index, item in enumerate(chain):
            _required(item, f"link_instance_chain[{index}]")
        object.__setattr__(self, "link_instance_chain", chain)

    def as_dict(self) -> dict[str, Any]:
        return {
            "federation_root": self.federation_root,
            "link_instance_chain": list(self.link_instance_chain),
        }


@dataclass(frozen=True, slots=True)
class DefinitionIdentity:
    """One Revit definition: source document identity + Element.UniqueId."""

    document: DocumentIdentity
    element_unique_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.document, DocumentIdentity):
            raise IdentityError("DefinitionIdentity.document must be typed")
        _required(self.element_unique_id,
                  "DefinitionIdentity.element_unique_id")

    @property
    def key(self) -> str:
        return _key("definition", self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document.as_dict(),
            "element_unique_id": self.element_unique_id,
        }


@dataclass(frozen=True, slots=True)
class OccurrenceIdentity:
    """One placement of a definition in a particular federation path."""

    federation_root: str
    link_instance_chain: tuple[str, ...]
    definition: DefinitionIdentity

    def __post_init__(self) -> None:
        _required(self.federation_root,
                  "OccurrenceIdentity.federation_root")
        if isinstance(self.link_instance_chain, str):
            raise IdentityError("link_instance_chain must be a sequence, not str")
        chain = tuple(self.link_instance_chain)
        for index, item in enumerate(chain):
            _required(item, f"link_instance_chain[{index}]")
        object.__setattr__(self, "link_instance_chain", chain)
        if not isinstance(self.definition, DefinitionIdentity):
            raise IdentityError("OccurrenceIdentity.definition must be typed")

    @property
    def key(self) -> str:
        return _key("occurrence", self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "federation_root": self.federation_root,
            "link_instance_chain": list(self.link_instance_chain),
            "definition": self.definition.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    definition: DefinitionIdentity | None
    occurrence: OccurrenceIdentity | None
    status: IdentityStatus
    gaps: tuple[IdentityGap, ...]

    @property
    def authoritative(self) -> bool:
        return self.status is IdentityStatus.AUTHORITATIVE


@dataclass(frozen=True, slots=True)
class IdentityContextResolution:
    """Trusted graph context recovered from an L0 header.

    The result is deliberately separate from per-element resolution: a
    document can be known while one row lacks ``Element.UniqueId``, and a
    linked document definition can be known while its occurrence path is not.
    """

    document_identity: DocumentIdentity | None
    federation_context: FederationContext | None
    status: IdentityStatus
    gaps: tuple[IdentityGap, ...]

    @property
    def authoritative(self) -> bool:
        return self.status is IdentityStatus.AUTHORITATIVE


def _unique_gaps(values: Iterable[IdentityGap]) -> tuple[IdentityGap, ...]:
    result: list[IdentityGap] = []
    seen: set[IdentityGap] = set()
    for value in values:
        if not isinstance(value, IdentityGap):
            raise IdentityError("identity gaps must contain IdentityGap values")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _document_fact(
    value: Any,
    field_name: str,
) -> tuple[DocumentIdentity | None, bool]:
    """Return (authoritative identity, fact-present).

    A weak fact is deliberately not converted to ``DocumentIdentity``.  This
    prevents the graph's definition index from coalescing divergent physical
    copies that retained the same ProjectInformation element UniqueId.
    """
    if value is None:
        return None, False
    if not isinstance(value, Mapping):
        raise IdentityError(f"{field_name} must be an object or null")
    source = value.get("source")
    raw = value.get("value")
    if source not in DOCUMENT_IDENTITY_SOURCES:
        raise IdentityError(
            f"{field_name}.source is unsupported: {source!r}")
    identity = _required(raw, f"{field_name}.value")
    if source not in AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES:
        return None, True
    # The source tag is part of the opaque value.  A future Revit identity
    # source therefore cannot collide with another Revit identity namespace.
    return DocumentIdentity(f"revit:{source}:{identity}"), True


def _metadata_gaps(value: Any) -> tuple[IdentityGap, ...]:
    if not isinstance(value, list):
        raise IdentityError("header.identity.gaps must be an array")
    parsed: list[IdentityGap] = []
    for index, item in enumerate(value):
        try:
            parsed.append(IdentityGap(item))
        except (TypeError, ValueError) as exc:
            raise IdentityError(
                f"header.identity.gaps[{index}] is unknown: {item!r}") from exc
    if len(parsed) != len(set(parsed)):
        raise IdentityError("header.identity.gaps contains duplicates")
    return tuple(parsed)


def identity_context_from_l0(
    header: Mapping[str, Any],
    *,
    document_identity: DocumentIdentity | None = None,
    federation_context: FederationContext | None = None,
) -> IdentityContextResolution:
    """Build the one graph identity context from trusted L0 metadata.

    Explicit typed caller context wins field-by-field.  A legacy header stays
    readable but never gains authority from ``doc_name``, paths, or local
    ``ElementId`` values.  Fresh metadata is strict: an unknown schema or a
    self-contradicting ``authoritative`` claim is rejected instead of being
    normalized into plausible identity.
    """
    if not isinstance(header, Mapping):
        raise IdentityError("L0 header must be a mapping")
    if document_identity is not None and not isinstance(
            document_identity, DocumentIdentity):
        raise IdentityError("document_identity must be DocumentIdentity or None")
    if federation_context is not None and not isinstance(
            federation_context, FederationContext):
        raise IdentityError("federation_context must be FederationContext or None")

    # A fully explicit trusted context is authoritative independently of old
    # or malformed optional metadata.  This is the strongest interpretation
    # of "explicit caller context has priority" and keeps recovery possible.
    if document_identity is not None and federation_context is not None:
        return IdentityContextResolution(
            document_identity, federation_context,
            IdentityStatus.AUTHORITATIVE, ())

    raw_identity = header.get("identity")
    if raw_identity is None:
        if document_identity is None and federation_context is None:
            gaps = (IdentityGap.LEGACY_CONTEXT_ABSENT,)
        elif document_identity is None:
            gaps = (IdentityGap.MISSING_DOCUMENT_IDENTITY,)
        else:
            gaps = (IdentityGap.MISSING_FEDERATION_CONTEXT,)
        return IdentityContextResolution(
            document_identity, federation_context,
            IdentityStatus.INCOMPLETE, gaps)
    if not isinstance(raw_identity, Mapping):
        raise IdentityError("header.identity must be an object")
    if raw_identity.get("schema_version") != L0_IDENTITY_METADATA_SCHEMA:
        raise IdentityError(
            "unsupported header.identity.schema_version: "
            f"{raw_identity.get('schema_version')!r}")

    source_kind = raw_identity.get("source_kind")
    if source_kind not in {"root", "link"}:
        raise IdentityError(
            f"header.identity.source_kind is invalid: {source_kind!r}")
    declared_gaps = _metadata_gaps(raw_identity.get("gaps"))
    declared_status = raw_identity.get("status")
    try:
        status = IdentityStatus(declared_status)
    except (TypeError, ValueError) as exc:
        raise IdentityError(
            f"header.identity.status is invalid: {declared_status!r}") from exc

    raw_document_fact = raw_identity.get("document_identity")
    raw_root_fact = raw_identity.get("federation_root_identity")
    metadata_document, metadata_document_present = _document_fact(
        raw_document_fact,
        "header.identity.document_identity")
    metadata_root, metadata_root_present = _document_fact(
        raw_root_fact,
        "header.identity.federation_root_identity")
    raw_chain = raw_identity.get("link_instance_chain")
    if not isinstance(raw_chain, list):
        raise IdentityError(
            "header.identity.link_instance_chain must be an array")
    chain = tuple(
        _required(item, f"header.identity.link_instance_chain[{index}]")
        for index, item in enumerate(raw_chain))
    if source_kind == "root" and chain:
        raise IdentityError("root L0 identity cannot carry a link chain")
    if (source_kind == "root" and metadata_document_present
            and metadata_root_present):
        assert isinstance(raw_document_fact, Mapping)
        assert isinstance(raw_root_fact, Mapping)
        if ((raw_document_fact.get("source"), raw_document_fact.get("value"))
                != (raw_root_fact.get("source"), raw_root_fact.get("value"))):
            raise IdentityError(
                "root L0 document identity differs from federation root")

    expected_gaps: set[IdentityGap] = set()
    if not metadata_document_present:
        expected_gaps.add(IdentityGap.SOURCE_DOCUMENT_IDENTITY_UNAVAILABLE)
    elif metadata_document is None:
        expected_gaps.add(
            IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE)
    if not metadata_root_present:
        expected_gaps.add(IdentityGap.FEDERATION_ROOT_IDENTITY_UNAVAILABLE)
    elif metadata_root is None:
        expected_gaps.add(
            IdentityGap.FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE)
    if source_kind == "link" and not chain:
        expected_gaps.add(IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE)
    if set(declared_gaps) != expected_gaps:
        raise IdentityError(
            "header.identity.gaps do not exactly describe missing facts")

    metadata_complete = (
        metadata_document is not None
        and metadata_root is not None
        and (source_kind == "root" or bool(chain))
        and not declared_gaps)
    if (status is IdentityStatus.AUTHORITATIVE) != metadata_complete:
        raise IdentityError(
            "header.identity status contradicts its facts/gaps")

    resolved_document = document_identity or metadata_document
    resolved_federation = federation_context
    if resolved_federation is None and metadata_root is not None:
        if source_kind == "root" or chain:
            resolved_federation = FederationContext(
                metadata_root.value, chain)

    gaps: list[IdentityGap] = []
    if document_identity is None and metadata_document is None:
        gaps.extend(gap for gap in declared_gaps if gap in {
            IdentityGap.SOURCE_DOCUMENT_IDENTITY_UNAVAILABLE,
            IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
        })
        gaps.append(IdentityGap.MISSING_DOCUMENT_IDENTITY)
    if federation_context is None and resolved_federation is None:
        gaps.extend(gap for gap in declared_gaps if gap in {
            IdentityGap.FEDERATION_ROOT_IDENTITY_UNAVAILABLE,
            IdentityGap.FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE,
            IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE,
        })
        gaps.append(IdentityGap.MISSING_FEDERATION_CONTEXT)
    gaps_tuple = _unique_gaps(gaps)
    resolved_status = (
        IdentityStatus.AUTHORITATIVE
        if resolved_document is not None and resolved_federation is not None
        and not gaps_tuple
        else IdentityStatus.INCOMPLETE)
    return IdentityContextResolution(
        resolved_document, resolved_federation, resolved_status, gaps_tuple)


def resolve_element_identity(
    *,
    element_unique_id: Any,
    document_identity: DocumentIdentity | None,
    federation_context: FederationContext | None,
    context_gaps: Iterable[IdentityGap] = (),
) -> IdentityResolution:
    """Resolve as much identity as supplied, never inferring missing context."""
    if document_identity is not None and not isinstance(
            document_identity, DocumentIdentity):
        raise IdentityError("document_identity must be DocumentIdentity or None")
    if federation_context is not None and not isinstance(
            federation_context, FederationContext):
        raise IdentityError("federation_context must be FederationContext or None")

    gaps: list[IdentityGap] = list(_unique_gaps(context_gaps))
    if document_identity is None and federation_context is None:
        if not gaps:
            gaps.append(IdentityGap.LEGACY_CONTEXT_ABSENT)
        elif IdentityGap.LEGACY_CONTEXT_ABSENT not in gaps:
            # Fresh metadata was present and named why both facts are absent;
            # do not relabel it as a legacy snapshot.
            gaps.extend((
                IdentityGap.MISSING_DOCUMENT_IDENTITY,
                IdentityGap.MISSING_FEDERATION_CONTEXT,
            ))
    else:
        if document_identity is None:
            gaps.append(IdentityGap.MISSING_DOCUMENT_IDENTITY)
        if federation_context is None:
            gaps.append(IdentityGap.MISSING_FEDERATION_CONTEXT)

    unique_id = (element_unique_id if isinstance(element_unique_id, str)
                 and element_unique_id.strip() else None)
    if unique_id is None:
        gaps.append(IdentityGap.MISSING_ELEMENT_UNIQUE_ID)

    definition = (DefinitionIdentity(document_identity, unique_id)
                  if document_identity is not None and unique_id is not None
                  else None)
    occurrence = (
        OccurrenceIdentity(
            federation_context.federation_root,
            federation_context.link_instance_chain,
            definition,
        )
        if federation_context is not None and definition is not None
        else None
    )
    gaps_tuple = _unique_gaps(gaps)
    status = (IdentityStatus.AUTHORITATIVE
              if occurrence is not None and not gaps_tuple
              else IdentityStatus.INCOMPLETE)
    return IdentityResolution(definition, occurrence, status, gaps_tuple)


__all__ = [
    "AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES",
    "CLOUD_PROJECT_MODEL_GUID",
    "DefinitionIdentity",
    "DOCUMENT_IDENTITY_SOURCES",
    "DocumentIdentity",
    "FederationContext",
    "IDENTITY_SCHEMA",
    "L0_IDENTITY_METADATA_SCHEMA",
    "PROJECT_INFORMATION_UNIQUE_ID",
    "REVIT_SERVER_CENTRAL_GUID",
    "IdentityError",
    "IdentityGap",
    "IdentityContextResolution",
    "IdentityResolution",
    "IdentityStatus",
    "OccurrenceIdentity",
    "identity_context_from_l0",
    "resolve_element_identity",
]
