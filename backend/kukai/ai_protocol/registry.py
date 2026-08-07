"""Deterministic AP-01 schema and capability registry."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any, ClassVar, Literal, TypeAlias

from kukai.design_source.canonical import (
    CANONICAL_VERSION,
    STRICT_JSON_MAX_DEPTH,
    STRICT_JSON_MAX_INPUT_BYTES,
    UNICODE_DATA_VERSION,
    CanonicalError,
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    digest_text,
    freeze,
)

from .contracts import (
    CAPABILITIES_ARGUMENTS_SCHEMA,
    CAPABILITIES_RESULT_SCHEMA,
    CAPABILITIES_TOOL,
    COVERAGE_SCHEMA,
    DECLARED_TOOL_NAMES,
    ERROR_SCHEMA,
    PROTOCOL_VERSION,
    READ_RECEIPT_SCHEMA,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    MAX_WIRE_BYTES,
    ProtocolContractV0,
    WIRE_MILESTONE,
    _exact_digest_bytes,
)
from .errors import ProtocolContractError


SCHEMA_DESCRIPTOR_SCHEMA = "kir-ai-schema-descriptor/0"
TOOL_CAPABILITY_SCHEMA = "kir-ai-tool-capability/0"
FEATURE_CAPABILITY_SCHEMA = "kir-ai-feature-capability/0"
PUBLISH_NOT_AVAILABLE_BEFORE_SRV1 = "PUBLISH_NOT_AVAILABLE_BEFORE_SRV1"
NOT_AVAILABLE_IN_AP01 = "NOT_AVAILABLE_IN_AP01"

AvailabilityV0: TypeAlias = Literal["AVAILABLE", "UNAVAILABLE"]
_AVAILABILITIES = frozenset({"AVAILABLE", "UNAVAILABLE"})
_REASON_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_POINTER_FIELDS = frozenset({"uri", "digest"})
_PROFILE_FIELDS = frozenset({
    "canonical_version",
    "unicode_data_version",
    "max_input_bytes",
    "max_depth",
})
_REGISTRY_FIELDS = frozenset({
    "schema",
    "protocol",
    "milestone",
    "canonical_profile",
    "registry_digest",
    "schemas",
    "tools",
    "features",
})
_SCHEMA_DESCRIPTOR_FIELDS = frozenset({
    "schema", "schema_id", "uri", "digest", "definition",
})
_TOOL_CAPABILITY_FIELDS = frozenset({
    "schema",
    "name",
    "availability",
    "reason_code",
    "request_envelope_schema",
    "arguments_schema",
    "response_envelope_schema",
    "result_schema",
    "side_effects",
})
_FEATURE_CAPABILITY_FIELDS = frozenset({
    "schema", "name", "availability", "reason_code",
})


def _admit_map(value: Mapping[str, Any], path: str) -> FrozenMap[str, Any]:
    try:
        admitted = freeze(value)
    except CanonicalError as exc:
        raise ProtocolContractError(f"{path}: {exc}") from exc
    if type(admitted) is not FrozenMap:
        raise ProtocolContractError(f"{path} must be an object")
    return admitted


def _text(value: Any, path: str, *, max_length: int = 4_096) -> str:
    if type(value) is not str or not value:
        raise ProtocolContractError(f"{path} must be exact non-empty text")
    try:
        admitted = freeze(value)
    except CanonicalError as exc:
        raise ProtocolContractError(f"{path}: {exc}") from exc
    if len(admitted) > max_length:
        raise ProtocolContractError(f"{path} exceeds its length limit")
    return admitted


def _digest(value: Any, path: str) -> str:
    try:
        return digest_text(_text(value, path, max_length=71), path)
    except CanonicalError as exc:
        raise ProtocolContractError(f"{path}: {exc}") from exc


def _reason(value: Any, path: str) -> str:
    admitted = _text(value, path, max_length=128)
    if _REASON_RE.fullmatch(admitted) is None:
        raise ProtocolContractError(f"{path} must be an uppercase symbol")
    return admitted


def _exact_object(
    value: Any,
    path: str,
    fields: frozenset[str],
) -> FrozenMap[str, Any]:
    if type(value) is not FrozenMap:
        raise ProtocolContractError(f"{path} must be an exact object")
    keys = frozenset(value)
    if keys != fields:
        raise ProtocolContractError(
            f"{path} fields mismatch: missing={sorted(fields - keys)}, "
            f"extra={sorted(keys - fields)}")
    return value


def _array(value: Any, path: str, *, exact_length: int) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise ProtocolContractError(f"{path} must be an exact array")
    if len(value) != exact_length:
        raise ProtocolContractError(
            f"{path} must contain exactly {exact_length} items")
    return value


def _literal(value: Any, expected: Any, path: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ProtocolContractError(f"{path} must equal {expected!r}")


def _schema_uri(schema_id: str) -> str:
    slug = schema_id.removeprefix("kir-ai-").removesuffix("/0")
    return f"urn:kir:ai-protocol:schema:{slug}:0"


def _field(kind: str, **constraints: Any) -> dict[str, Any]:
    return {"kind": kind, "required": True, **constraints}


def _schema_pointer_field() -> dict[str, Any]:
    return _field(
        "schema_pointer_or_null",
        unknown_fields="REFUSE",
        fields={
            "uri": _field("text", min_length=1, max_length=4_096),
            "digest": _field("sha256"),
        },
    )


def _object_definition(
    schema_id: str,
    fields: Mapping[str, Any],
    *,
    canonical_max_bytes: int | None = None,
    invariants: tuple[str, ...] = (),
) -> dict[str, Any]:
    definition = {
        "schema": "kir-ai-closed-shape-definition/0",
        "shape_id": schema_id,
        "kind": "object",
        "unknown_fields": "REFUSE",
        "fields": fields,
        "invariants": invariants,
    }
    if canonical_max_bytes is not None:
        definition["canonical_max_bytes"] = canonical_max_bytes
    return definition


_SCHEMA_DEFINITIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        REQUEST_SCHEMA,
        _object_definition(REQUEST_SCHEMA, {
            "protocol": _field("literal", value=PROTOCOL_VERSION),
            "request_id": _field("identifier", max_length=64),
            "tool": _field("enum", values=DECLARED_TOOL_NAMES),
            "arguments": _field("object", canonical_max_bytes=1_000_000),
        }, canonical_max_bytes=MAX_WIRE_BYTES, invariants=(
            "arguments follow the selected available tool arguments schema",
            "unavailable-tool refusal probes require exact empty arguments",
            "model arguments cannot contain principal, author, authority, "
            "approval, or token fields",
        )),
    ),
    (
        RESPONSE_SCHEMA,
        _object_definition(RESPONSE_SCHEMA, {
            "protocol": _field("literal", value=PROTOCOL_VERSION),
            "request_id": _field("identifier", max_length=64),
            "tool": _field("enum", values=DECLARED_TOOL_NAMES),
            "status": _field("enum", values=("FAILED", "OK", "REFUSED")),
            "coverage": _field("schema_ref", schema=COVERAGE_SCHEMA),
            "result": _field("object_or_null", canonical_max_bytes=2_000_000),
            "error": _field("schema_or_null", schema=ERROR_SCHEMA),
            "read_receipt": _field(
                "schema_or_null", schema=READ_RECEIPT_SCHEMA),
        }, canonical_max_bytes=MAX_WIRE_BYTES, invariants=(
            "OK requires result and excludes error and REFUSED coverage",
            "capabilities.get OK requires COMPLETE 1-of-1 coverage",
            "capabilities.get OK requires null read_receipt",
            "REFUSED requires error, null result, REFUSED coverage, and null "
            "read_receipt",
            "FAILED requires error, null result, non-COMPLETE non-REFUSED "
            "coverage, and null read_receipt",
            "tools declared UNAVAILABLE cannot return OK",
            "each UNAVAILABLE tool has one exact sealed refusal body and reason",
            "capabilities.get OK result equals the packaged registry value",
        )),
    ),
    (
        COVERAGE_SCHEMA,
        _object_definition(COVERAGE_SCHEMA, {
            "schema": _field("literal", value=COVERAGE_SCHEMA),
            "state": _field("enum", values=(
                "COMPLETE",
                "NOT_EVALUATED",
                "PARTIAL",
                "REFUSED",
                "TRUNCATED",
                "UNKNOWN",
            )),
            "requested": _field(
                "count_object",
                field="items",
                integer_min=0,
                integer_max=1_000_000_000,
                unknown_fields="REFUSE",
            ),
            "evaluated": _field(
                "count_object",
                field="items",
                integer_min=0,
                integer_max=1_000_000_000,
                unknown_fields="REFUSE",
            ),
            "omitted": _field(
                "unique_text_array",
                max_items=4_096,
                item_min_length=1,
                item_max_length=4_096,
                order="lexicographic",
            ),
            "failed": _field(
                "unique_text_array",
                max_items=4_096,
                item_min_length=1,
                item_max_length=4_096,
                order="lexicographic",
            ),
        }, canonical_max_bytes=1_000_000, invariants=(
            "evaluated items cannot exceed requested items",
            "COMPLETE requires equal counts and empty omitted and failed arrays",
            "NOT_EVALUATED and REFUSED require zero evaluated items",
        )),
    ),
    (
        ERROR_SCHEMA,
        _object_definition(ERROR_SCHEMA, {
            "schema": _field("literal", value=ERROR_SCHEMA),
            "code": _field("uppercase_symbol", max_length=128),
            "message": _field("text", min_length=1, max_length=4_096),
            "retryable": _field("bool"),
            "details": _field("object", canonical_max_bytes=65_536),
        }),
    ),
    (
        READ_RECEIPT_SCHEMA,
        _object_definition(READ_RECEIPT_SCHEMA, {
            "schema": _field("literal", value=READ_RECEIPT_SCHEMA),
            "protocol": _field("literal", value=PROTOCOL_VERSION),
            "request_id": _field("identifier", max_length=64),
            "tool": _field("enum", values=DECLARED_TOOL_NAMES),
            "project_id": _field("identifier", max_length=64),
            "revision_digest": _field("sha256"),
            "request_digest": _field("sha256"),
            "result_digests": _field(
                "unique_sha256_array",
                min_items=1,
                max_items=4_096,
                order="lexicographic",
            ),
            "coverage": _field("schema_ref", schema=COVERAGE_SCHEMA),
            "schema_registry_digest": _field("sha256"),
            "continuation": _field(
                "text_or_null", min_length=1, max_length=1_024),
            "receipt_digest": _field("sha256"),
        }, invariants=(
            "receipt_digest commits to every other read_receipt field",
            "request_id, tool, and coverage match the enclosing response",
            "schema_registry_digest matches the packaged registry",
        )),
    ),
    (
        CAPABILITIES_ARGUMENTS_SCHEMA,
        _object_definition(CAPABILITIES_ARGUMENTS_SCHEMA, {}),
    ),
    (
        CAPABILITIES_RESULT_SCHEMA,
        _object_definition(CAPABILITIES_RESULT_SCHEMA, {
            "schema": _field("literal", value=CAPABILITIES_RESULT_SCHEMA),
            "protocol": _field("literal", value=PROTOCOL_VERSION),
            "milestone": _field("literal", value=WIRE_MILESTONE),
            "canonical_profile": _field(
                "closed_object",
                unknown_fields="REFUSE",
                fields={
                    "canonical_version": _field(
                        "literal", value=CANONICAL_VERSION),
                    "unicode_data_version": _field(
                        "literal", value=UNICODE_DATA_VERSION),
                    "max_input_bytes": _field(
                        "literal", value=STRICT_JSON_MAX_INPUT_BYTES),
                    "max_depth": _field(
                        "literal", value=STRICT_JSON_MAX_DEPTH),
                },
            ),
            "registry_digest": _field("sha256"),
            "schemas": _field(
                "schema_descriptor_array", exact_items=10, order="schema_id"),
            "tools": _field(
                "tool_capability_array", exact_items=9, order="name"),
            "features": _field(
                "feature_capability_array", exact_items=9, order="name"),
        }, invariants=(
            "every child digest is recomputed before registry_digest",
            "registry_digest commits to the result body excluding registry_digest",
        )),
    ),
    (
        SCHEMA_DESCRIPTOR_SCHEMA,
        _object_definition(SCHEMA_DESCRIPTOR_SCHEMA, {
            "schema": _field("literal", value=SCHEMA_DESCRIPTOR_SCHEMA),
            "schema_id": _field(
                "text", min_length=1, max_length=4_096),
            "uri": _field("text", min_length=1, max_length=4_096),
            "digest": _field("sha256"),
            "definition": _field("object"),
        }, invariants=(
            "definition.shape_id equals schema_id",
            "digest commits to schema_id, uri, and definition",
        )),
    ),
    (
        TOOL_CAPABILITY_SCHEMA,
        _object_definition(TOOL_CAPABILITY_SCHEMA, {
            "schema": _field("literal", value=TOOL_CAPABILITY_SCHEMA),
            "name": _field("enum", values=DECLARED_TOOL_NAMES),
            "availability": _field(
                "enum", values=("AVAILABLE", "UNAVAILABLE")),
            "reason_code": _field(
                "uppercase_symbol_or_null", max_length=128),
            "request_envelope_schema": _schema_pointer_field(),
            "arguments_schema": _schema_pointer_field(),
            "response_envelope_schema": _schema_pointer_field(),
            "result_schema": _schema_pointer_field(),
            "side_effects": _field("literal", value="NONE"),
        }, invariants=(
            "AVAILABLE requires null reason_code and all four schema pointers",
            "UNAVAILABLE requires reason_code and four null schema pointers",
        )),
    ),
    (
        FEATURE_CAPABILITY_SCHEMA,
        _object_definition(FEATURE_CAPABILITY_SCHEMA, {
            "schema": _field("literal", value=FEATURE_CAPABILITY_SCHEMA),
            "name": _field("text", min_length=1, max_length=4_096),
            "availability": _field(
                "enum", values=("AVAILABLE", "UNAVAILABLE")),
            "reason_code": _field(
                "uppercase_symbol_or_null", max_length=128),
        }, invariants=(
            "AVAILABLE requires null reason_code",
            "UNAVAILABLE requires non-null reason_code",
        )),
    ),
)

_FEATURE_MATRIX: tuple[tuple[str, AvailabilityV0, str | None], ...] = (
    ("build", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("capability_discovery", "AVAILABLE", None),
    ("events", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("model_query", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("project_read", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("publish", "UNAVAILABLE", PUBLISH_NOT_AVAILABLE_BEFORE_SRV1),
    ("scene", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("source_patch", "UNAVAILABLE", NOT_AVAILABLE_IN_AP01),
    ("wire_admission", "AVAILABLE", None),
)
_EXPECTED_SCHEMA_IDS = tuple(sorted(
    schema_id for schema_id, _definition in _SCHEMA_DEFINITIONS))
_EXPECTED_SCHEMA_DEFINITIONS = {
    schema_id: freeze(definition)
    for schema_id, definition in _SCHEMA_DEFINITIONS
}


@dataclass(frozen=True, slots=True)
class SchemaDescriptorV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = SCHEMA_DESCRIPTOR_SCHEMA

    schema_id: str
    uri: str
    definition: Mapping[str, Any]
    _schema_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _canonical_hasher=canonical_digest) -> None:
        schema_id = _text(self.schema_id, "schema_id", max_length=4_096)
        uri = _text(self.uri, "schema_uri", max_length=4_096)
        if not uri.startswith("urn:kir:ai-protocol:schema:"):
            raise ProtocolContractError("schema URI is outside AP-01")
        definition = _admit_map(self.definition, "schema_definition")
        if definition.get("shape_id") != schema_id:
            raise ProtocolContractError("schema definition identity mismatch")
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "definition", definition)
        object.__setattr__(
            self,
            "_schema_digest",
            _canonical_hasher("kir.ai-protocol-schema.v0", {
                "schema_id": schema_id,
                "uri": uri,
                "definition": definition,
            }),
        )

    @property
    def schema_digest(self) -> str:
        return self._schema_digest

    def verify_integrity(
        self,
        _canonical_hasher=canonical_digest,
        _digest_encoder=_exact_digest_bytes,
        _contract_error_type=ProtocolContractError,
    ) -> None:
        try:
            actual = _canonical_hasher("kir.ai-protocol-schema.v0", {
                "schema_id": self.schema_id,
                "uri": self.uri,
                "definition": self.definition,
            })
            if _digest_encoder(
                actual, "expected schema digest"
            ) != _digest_encoder(self.schema_digest, "schema.schema_digest"):
                raise _contract_error_type("schema descriptor digest drift")
        except _contract_error_type:
            raise
        except Exception as exc:
            raise _contract_error_type(
                "schema descriptor integrity verification failed safely"
            ) from exc

    def pointer_data(self) -> dict[str, Any]:
        return {"uri": self.uri, "digest": self.schema_digest}

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "schema_id": self.schema_id,
            "uri": self.uri,
            "digest": self.schema_digest,
            "definition": self.definition,
        }


@dataclass(frozen=True, slots=True)
class ToolCapabilityV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = TOOL_CAPABILITY_SCHEMA

    name: str
    availability: AvailabilityV0
    reason_code: str | None
    request_envelope_schema: SchemaDescriptorV0 | None = None
    arguments_schema: SchemaDescriptorV0 | None = None
    response_envelope_schema: SchemaDescriptorV0 | None = None
    result_schema: SchemaDescriptorV0 | None = None

    def __post_init__(self) -> None:
        name = _text(self.name, "tool.name")
        if name not in DECLARED_TOOL_NAMES:
            raise ProtocolContractError("tool capability name is not declared")
        if (
            type(self.availability) is not str
            or self.availability not in _AVAILABILITIES
        ):
            raise ProtocolContractError("tool availability is unsupported")
        if self.availability == "AVAILABLE":
            if self.reason_code is not None:
                raise ProtocolContractError("available tool cannot have a reason")
            schemas = (
                self.request_envelope_schema,
                self.arguments_schema,
                self.response_envelope_schema,
                self.result_schema,
            )
            if any(type(item) is not SchemaDescriptorV0 for item in schemas):
                raise ProtocolContractError(
                    "available tool requires envelope and payload schemas")
        else:
            if self.reason_code is None:
                raise ProtocolContractError("unavailable tool requires a reason")
            reason = _reason(self.reason_code, "tool.reason_code")
            schemas = (
                self.request_envelope_schema,
                self.arguments_schema,
                self.response_envelope_schema,
                self.result_schema,
            )
            if any(item is not None for item in schemas):
                raise ProtocolContractError(
                    "unavailable AP-01 tool cannot advertise admitted schemas")
        object.__setattr__(self, "name", name)
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", reason)

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "name": self.name,
            "availability": self.availability,
            "reason_code": self.reason_code,
            "request_envelope_schema": (
                None
                if self.request_envelope_schema is None
                else self.request_envelope_schema.pointer_data()
            ),
            "arguments_schema": (
                None
                if self.arguments_schema is None
                else self.arguments_schema.pointer_data()
            ),
            "response_envelope_schema": (
                None
                if self.response_envelope_schema is None
                else self.response_envelope_schema.pointer_data()
            ),
            "result_schema": (
                None
                if self.result_schema is None
                else self.result_schema.pointer_data()
            ),
            "side_effects": "NONE",
        }


@dataclass(frozen=True, slots=True)
class FeatureCapabilityV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = FEATURE_CAPABILITY_SCHEMA

    name: str
    availability: AvailabilityV0
    reason_code: str | None

    def __post_init__(self) -> None:
        name = _text(self.name, "feature.name")
        if (
            type(self.availability) is not str
            or self.availability not in _AVAILABILITIES
        ):
            raise ProtocolContractError("feature availability is unsupported")
        if (self.availability == "AVAILABLE") != (self.reason_code is None):
            raise ProtocolContractError("feature availability/reason mismatch")
        if self.reason_code is not None:
            reason = _reason(self.reason_code, "feature.reason_code")
            object.__setattr__(self, "reason_code", reason)
        object.__setattr__(self, "name", name)

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "name": self.name,
            "availability": self.availability,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRegistryV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = CAPABILITIES_RESULT_SCHEMA

    schemas: tuple[SchemaDescriptorV0, ...]
    tools: tuple[ToolCapabilityV0, ...]
    features: tuple[FeatureCapabilityV0, ...]
    _registry_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _canonical_hasher=canonical_digest) -> None:
        if type(self.schemas) not in {list, tuple}:
            raise ProtocolContractError(
                "registry.schemas must be an exact list or tuple")
        if type(self.tools) not in {list, tuple}:
            raise ProtocolContractError(
                "registry.tools must be an exact list or tuple")
        if type(self.features) not in {list, tuple}:
            raise ProtocolContractError(
                "registry.features must be an exact list or tuple")
        if any(type(item) is not SchemaDescriptorV0 for item in self.schemas):
            raise ProtocolContractError("registry has a non-schema descriptor")
        if any(type(item) is not ToolCapabilityV0 for item in self.tools):
            raise ProtocolContractError("registry has a non-tool capability")
        if any(type(item) is not FeatureCapabilityV0 for item in self.features):
            raise ProtocolContractError("registry has a non-feature capability")
        schemas = tuple(sorted(self.schemas, key=lambda item: item.schema_id))
        tools = tuple(sorted(self.tools, key=lambda item: item.name))
        features = tuple(sorted(self.features, key=lambda item: item.name))
        if len({item.schema_id for item in schemas}) != len(schemas):
            raise ProtocolContractError("registry has duplicate schema IDs")
        if len({item.uri for item in schemas}) != len(schemas):
            raise ProtocolContractError("registry has duplicate schema URIs")
        if tuple(item.schema_id for item in schemas) != _EXPECTED_SCHEMA_IDS:
            raise ProtocolContractError("registry schema census is not exact")
        for descriptor in schemas:
            if descriptor.uri != _schema_uri(descriptor.schema_id):
                raise ProtocolContractError(
                    f"schema {descriptor.schema_id!r} URI is not exact")
            if (
                descriptor.definition
                != _EXPECTED_SCHEMA_DEFINITIONS[descriptor.schema_id]
            ):
                raise ProtocolContractError(
                    f"schema {descriptor.schema_id!r} definition is not exact")
        if tuple(item.name for item in tools) != DECLARED_TOOL_NAMES:
            raise ProtocolContractError("registry tool census is not exact")
        expected_tools = tuple(
            (
                name,
                "AVAILABLE" if name == CAPABILITIES_TOOL else "UNAVAILABLE",
                (
                    None
                    if name == CAPABILITIES_TOOL
                    else (
                        PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
                        if name == "publish.prepare"
                        else NOT_AVAILABLE_IN_AP01
                    )
                ),
            )
            for name in DECLARED_TOOL_NAMES
        )
        actual_tools = tuple(
            (item.name, item.availability, item.reason_code)
            for item in tools
        )
        if actual_tools != expected_tools:
            raise ProtocolContractError("registry tool matrix is not exact")
        actual_features = tuple(
            (item.name, item.availability, item.reason_code)
            for item in features
        )
        if actual_features != _FEATURE_MATRIX:
            raise ProtocolContractError("registry feature matrix is not exact")
        schema_by_id = {item.schema_id: item for item in schemas}
        available = tuple(
            item.name for item in tools if item.availability == "AVAILABLE")
        if available != (CAPABILITIES_TOOL,):
            raise ProtocolContractError(
                "AP-01 must expose only capabilities.get")
        publish = next(item for item in tools if item.name == "publish.prepare")
        if publish.reason_code != PUBLISH_NOT_AVAILABLE_BEFORE_SRV1:
            raise ProtocolContractError("publish reason is not SRV1-bound")
        required_schema_ids = frozenset({
            REQUEST_SCHEMA,
            CAPABILITIES_ARGUMENTS_SCHEMA,
            RESPONSE_SCHEMA,
            CAPABILITIES_RESULT_SCHEMA,
        })
        if not required_schema_ids.issubset(schema_by_id):
            raise ProtocolContractError(
                "capabilities.get schemas are missing from registry")
        discovery = next(
            item for item in tools if item.name == CAPABILITIES_TOOL)
        expected_bindings = (
            (discovery.request_envelope_schema, REQUEST_SCHEMA),
            (discovery.arguments_schema, CAPABILITIES_ARGUMENTS_SCHEMA),
            (discovery.response_envelope_schema, RESPONSE_SCHEMA),
            (discovery.result_schema, CAPABILITIES_RESULT_SCHEMA),
        )
        if any(
            descriptor is not schema_by_id[schema_id]
            for descriptor, schema_id in expected_bindings
        ):
            raise ProtocolContractError(
                "capabilities.get schema bindings are not exact registry members")
        object.__setattr__(self, "schemas", schemas)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "features", features)
        object.__setattr__(
            self,
            "_registry_digest",
            _canonical_hasher(
                "kir.ai-capability-registry.v0", self._body_data()),
        )

    @property
    def registry_digest(self) -> str:
        return self._registry_digest

    def verify_integrity(
        self,
        _canonical_hasher=canonical_digest,
        _canonical_encoder=canonical_bytes,
        _digest_encoder=_exact_digest_bytes,
        _contract_error_type=ProtocolContractError,
    ) -> None:
        try:
            for schema in self.schemas:
                schema.verify_integrity()
            rebuilt = self.__class__(self.schemas, self.tools, self.features)
            if (
                _digest_encoder(
                    rebuilt.registry_digest, "rebuilt registry digest"
                )
                != _digest_encoder(
                    self.registry_digest, "registry.registry_digest")
                or _canonical_encoder(rebuilt.to_data())
                != _canonical_encoder(self.to_data())
            ):
                raise _contract_error_type(
                    "packaged capability registry value drift")
            actual = _canonical_hasher(
                "kir.ai-capability-registry.v0", self._body_data())
            if _digest_encoder(
                actual, "expected registry digest"
            ) != _digest_encoder(
                self.registry_digest, "registry.registry_digest"):
                raise _contract_error_type(
                    "packaged capability registry digest drift")
        except _contract_error_type:
            raise
        except Exception as exc:
            raise _contract_error_type(
                "capability registry integrity verification failed safely"
            ) from exc

    def schema_for_id(self, schema_id: str) -> SchemaDescriptorV0:
        matches = tuple(
            item for item in self.schemas if item.schema_id == schema_id)
        if len(matches) != 1:
            raise ProtocolContractError(f"schema {schema_id!r} is unavailable")
        return matches[0]

    def tool_for_name(self, name: str) -> ToolCapabilityV0 | None:
        return next((item for item in self.tools if item.name == name), None)

    def _body_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "protocol": PROTOCOL_VERSION,
            "milestone": WIRE_MILESTONE,
            "canonical_profile": {
                "canonical_version": CANONICAL_VERSION,
                "unicode_data_version": UNICODE_DATA_VERSION,
                "max_input_bytes": STRICT_JSON_MAX_INPUT_BYTES,
                "max_depth": STRICT_JSON_MAX_DEPTH,
            },
            "schemas": tuple(item.to_data() for item in self.schemas),
            "tools": tuple(item.to_data() for item in self.tools),
            "features": tuple(item.to_data() for item in self.features),
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._body_data(), "registry_digest": self.registry_digest}


def _parse_schema_descriptor(
    value: Any,
    path: str,
    *,
    _digest_encoder=_exact_digest_bytes,
) -> SchemaDescriptorV0:
    raw = _exact_object(value, path, _SCHEMA_DESCRIPTOR_FIELDS)
    _literal(raw["schema"], SCHEMA_DESCRIPTOR_SCHEMA, f"{path}.schema")
    if type(raw["definition"]) is not FrozenMap:
        raise ProtocolContractError(f"{path}.definition must be an exact object")
    descriptor = SchemaDescriptorV0(
        schema_id=raw["schema_id"],
        uri=raw["uri"],
        definition=raw["definition"],
    )
    claimed_digest = _digest(raw["digest"], f"{path}.digest")
    if _digest_encoder(
        claimed_digest, f"{path}.digest"
    ) != _digest_encoder(
        descriptor.schema_digest, f"admitted {path}.digest"
    ):
        raise ProtocolContractError(f"{path}.digest does not match definition")
    return descriptor


def _parse_schema_pointer(
    value: Any,
    path: str,
    descriptors: Mapping[tuple[str, str], SchemaDescriptorV0],
) -> SchemaDescriptorV0 | None:
    if value is None:
        return None
    raw = _exact_object(value, path, _POINTER_FIELDS)
    uri = _text(raw["uri"], f"{path}.uri", max_length=4_096)
    digest = _digest(raw["digest"], f"{path}.digest")
    descriptor = descriptors.get((uri, digest))
    if descriptor is None:
        raise ProtocolContractError(
            f"{path} does not resolve to an admitted schema descriptor")
    return descriptor


def _parse_tool_capability(
    value: Any,
    path: str,
    descriptors: Mapping[tuple[str, str], SchemaDescriptorV0],
) -> ToolCapabilityV0:
    raw = _exact_object(value, path, _TOOL_CAPABILITY_FIELDS)
    _literal(raw["schema"], TOOL_CAPABILITY_SCHEMA, f"{path}.schema")
    _literal(raw["side_effects"], "NONE", f"{path}.side_effects")
    reason = (
        None
        if raw["reason_code"] is None
        else _reason(raw["reason_code"], f"{path}.reason_code")
    )
    return ToolCapabilityV0(
        name=raw["name"],
        availability=raw["availability"],
        reason_code=reason,
        request_envelope_schema=_parse_schema_pointer(
            raw["request_envelope_schema"],
            f"{path}.request_envelope_schema",
            descriptors,
        ),
        arguments_schema=_parse_schema_pointer(
            raw["arguments_schema"],
            f"{path}.arguments_schema",
            descriptors,
        ),
        response_envelope_schema=_parse_schema_pointer(
            raw["response_envelope_schema"],
            f"{path}.response_envelope_schema",
            descriptors,
        ),
        result_schema=_parse_schema_pointer(
            raw["result_schema"],
            f"{path}.result_schema",
            descriptors,
        ),
    )


def _parse_feature_capability(value: Any, path: str) -> FeatureCapabilityV0:
    raw = _exact_object(value, path, _FEATURE_CAPABILITY_FIELDS)
    _literal(raw["schema"], FEATURE_CAPABILITY_SCHEMA, f"{path}.schema")
    reason = (
        None
        if raw["reason_code"] is None
        else _reason(raw["reason_code"], f"{path}.reason_code")
    )
    return FeatureCapabilityV0(
        name=raw["name"],
        availability=raw["availability"],
        reason_code=reason,
    )


def admit_capability_registry(
    value: Any,
    *,
    _digest_encoder=_exact_digest_bytes,
) -> CapabilityRegistryV0:
    """Admit only the exact, self-consistent packaged AP-01 registry result."""

    raw = _exact_object(value, "capabilities.result", _REGISTRY_FIELDS)
    _literal(
        raw["schema"],
        CAPABILITIES_RESULT_SCHEMA,
        "capabilities.result.schema",
    )
    _literal(
        raw["protocol"], PROTOCOL_VERSION, "capabilities.result.protocol")
    _literal(
        raw["milestone"], WIRE_MILESTONE, "capabilities.result.milestone")
    profile = _exact_object(
        raw["canonical_profile"],
        "capabilities.result.canonical_profile",
        _PROFILE_FIELDS,
    )
    expected_profile = {
        "canonical_version": CANONICAL_VERSION,
        "unicode_data_version": UNICODE_DATA_VERSION,
        "max_input_bytes": STRICT_JSON_MAX_INPUT_BYTES,
        "max_depth": STRICT_JSON_MAX_DEPTH,
    }
    for key, expected in expected_profile.items():
        _literal(
            profile[key],
            expected,
            f"capabilities.result.canonical_profile.{key}",
        )

    schema_values = _array(
        raw["schemas"],
        "capabilities.result.schemas",
        exact_length=len(_SCHEMA_DEFINITIONS),
    )
    schemas = tuple(
        _parse_schema_descriptor(
            item, f"capabilities.result.schemas[{index}]")
        for index, item in enumerate(schema_values)
    )
    if tuple(item.schema_id for item in schemas) != _EXPECTED_SCHEMA_IDS:
        raise ProtocolContractError(
            "capabilities.result.schemas order or census is not exact")
    descriptors = {
        (item.uri, item.schema_digest): item
        for item in schemas
    }
    if len(descriptors) != len(schemas):
        raise ProtocolContractError(
            "capabilities.result.schemas has duplicate pointers")

    tool_values = _array(
        raw["tools"],
        "capabilities.result.tools",
        exact_length=len(DECLARED_TOOL_NAMES),
    )
    tools = tuple(
        _parse_tool_capability(
            item,
            f"capabilities.result.tools[{index}]",
            descriptors,
        )
        for index, item in enumerate(tool_values)
    )
    if tuple(item.name for item in tools) != DECLARED_TOOL_NAMES:
        raise ProtocolContractError(
            "capabilities.result.tools order or census is not exact")

    feature_values = _array(
        raw["features"],
        "capabilities.result.features",
        exact_length=len(_FEATURE_MATRIX),
    )
    features = tuple(
        _parse_feature_capability(
            item, f"capabilities.result.features[{index}]")
        for index, item in enumerate(feature_values)
    )
    if tuple(item.name for item in features) != tuple(
        name for name, _availability, _reason_code in _FEATURE_MATRIX
    ):
        raise ProtocolContractError(
            "capabilities.result.features order or census is not exact")

    registry = CapabilityRegistryV0(schemas, tools, features)
    claimed_digest = _digest(
        raw["registry_digest"], "capabilities.result.registry_digest")
    if _digest_encoder(
        claimed_digest, "capabilities.result.registry_digest"
    ) != _digest_encoder(
        registry.registry_digest, "admitted registry digest"
    ):
        raise ProtocolContractError(
            "capabilities.result.registry_digest does not match its body")
    if freeze(registry.to_data()) != raw:
        raise ProtocolContractError(
            "capabilities.result is not the exact canonical registry value")
    return registry


def _build_registry() -> CapabilityRegistryV0:
    schemas = tuple(
        SchemaDescriptorV0(
            schema_id=schema_id,
            uri=_schema_uri(schema_id),
            definition=definition,
        )
        for schema_id, definition in _SCHEMA_DEFINITIONS
    )
    schema_map = {item.schema_id: item for item in schemas}
    tools = []
    for name in DECLARED_TOOL_NAMES:
        if name == CAPABILITIES_TOOL:
            tools.append(ToolCapabilityV0(
                name=name,
                availability="AVAILABLE",
                reason_code=None,
                request_envelope_schema=schema_map[REQUEST_SCHEMA],
                arguments_schema=schema_map[CAPABILITIES_ARGUMENTS_SCHEMA],
                response_envelope_schema=schema_map[RESPONSE_SCHEMA],
                result_schema=schema_map[CAPABILITIES_RESULT_SCHEMA],
            ))
            continue
        reason = (
            PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
            if name == "publish.prepare"
            else NOT_AVAILABLE_IN_AP01
        )
        tools.append(ToolCapabilityV0(
            name=name,
            availability="UNAVAILABLE",
            reason_code=reason,
        ))
    features = tuple(
        FeatureCapabilityV0(name, availability, reason)
        for name, availability, reason in _FEATURE_MATRIX
    )
    return CapabilityRegistryV0(schemas, tuple(tools), features)


CAPABILITY_REGISTRY = _build_registry()


__all__ = [
    "AvailabilityV0",
    "CAPABILITIES_ARGUMENTS_SCHEMA",
    "CAPABILITIES_RESULT_SCHEMA",
    "CAPABILITY_REGISTRY",
    "CapabilityRegistryV0",
    "FeatureCapabilityV0",
    "NOT_AVAILABLE_IN_AP01",
    "PUBLISH_NOT_AVAILABLE_BEFORE_SRV1",
    "SchemaDescriptorV0",
    "ToolCapabilityV0",
    "admit_capability_registry",
]
