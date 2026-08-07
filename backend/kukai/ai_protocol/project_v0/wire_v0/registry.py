"""Own deterministic capability registry for the AP02-W fixture wire."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from kukai.design_source import (
    CANONICAL_VERSION,
    UNICODE_DATA_VERSION,
    BuildEntityV0,
    BuildOriginV0,
    FrozenMap,
    GeneratorCallV0,
    ModuleV0,
    ParameterSpecV0,
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    SlotSpecV0,
    canonical_bytes,
    canonical_digest,
)
from kukai.design_source.query import BuildSummaryV0

from ..schemas import (
    COVERAGE_SCHEMA as K_COVERAGE_SCHEMA,
    CURSOR_REF_SCHEMA,
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
    MAX_PAGE_BYTES,
    MAX_PAGE_ITEMS,
    MAX_PATCH_OPS,
    MAX_RECEIPT_REFS,
    MODEL_QUERY_COMMAND_SCHEMA,
    MODEL_QUERY_RESULT_SCHEMA,
    MODEL_QUERY_SCOPES,
    MODULE_PUT_SCHEMA,
    PROJECT_READ_COMMAND_SCHEMA,
    PROJECT_READ_RESULT_SCHEMA,
    READ_RECEIPT_SCHEMA,
    RECEIPT_REF_SCHEMA,
    ROOT_PUT_SCHEMA,
    SOURCE_PATCH_COMMAND_SCHEMA,
    SOURCE_PATCH_RESULT_SCHEMA,
    ORIGIN_FILTER_FIELDS,
    PROJECT_READ_SCOPES,
)
from .contracts import (
    AVAILABLE_TOOL_NAMES,
    CAPABILITIES_TOOL,
    DECLARED_TOOL_NAMES,
    MAX_ARGUMENT_BYTES,
    MAX_COVERAGE_BYTES,
    MAX_DEPTH,
    MAX_ERROR_DETAIL_BYTES,
    MAX_RESULT_BYTES,
    MAX_WIRE_BYTES,
    MODEL_QUERY_TOOL,
    PROJECT_READ_TOOL,
    PROTOCOL_VERSION,
    SOURCE_PATCH_TOOL,
    WIRE_COVERAGE_SCHEMA,
    WIRE_ERROR_SCHEMA,
    WIRE_REQUEST_SCHEMA,
    WIRE_RESPONSE_SCHEMA,
    exact_text,
    fresh_object,
)
from .errors import WireContractError


REGISTRY_SCHEMA = "kir-ai-project-capability-registry/0"
SCHEMA_DESCRIPTOR_SCHEMA = "kir-ai-project-schema-descriptor/0"
TOOL_CAPABILITY_SCHEMA = "kir-ai-project-tool-capability/0"
CLOSED_DEFINITION_SCHEMA = "kir-ai-project-closed-shape-definition/0"
CAPABILITIES_ARGUMENTS_SCHEMA = "kir-ai-project-capabilities-get-arguments/0"
CANONICAL_PROFILE_SCHEMA = "kir-ai-project-canonical-profile/0"
SCHEMA_POINTER_SCHEMA = "kir-ai-project-schema-pointer/0"
FIELD_DEFINITION_SCHEMA = "kir-ai-project-field-definition/0"
PATCH_OPERATION_SCHEMA = "kir-ai-project-patch-operation/0"

EMPTY_SELECTOR_SCHEMA = "kir-ai-project-empty-selector/0"
MODULE_SELECTOR_SCHEMA = "kir-ai-project-module-selector/0"
EXCEPTION_SELECTOR_SCHEMA = "kir-ai-project-exception-selector/0"
LOGICAL_ID_FILTER_SCHEMA = "kir-ai-model-query-logical-id-filter/0"
ORIGIN_FILTER_SCHEMA = "kir-ai-model-query-origin-filter/0"
PROJECT_READ_SELECTOR_SCHEMA = "kir-ai-project-read-selector/0"
MODEL_QUERY_FILTER_SCHEMA = "kir-ai-model-query-filter/0"

MANIFEST_VIEW_SCHEMA = "kir-ai-project-manifest-view/0"
MODULE_INDEX_ENTRY_SCHEMA = "kir-ai-module-index-entry/0"
EXCEPTION_INDEX_ENTRY_SCHEMA = "kir-ai-exception-index-entry/0"

_ALLOWED_SCHEMA_PREFIXES = ("kir-ai-", "kir-design-", "kir-build-")
_FIELD_KINDS = (
    "array",
    "bool",
    "canonical_json",
    "enum",
    "identifier",
    "integer",
    "literal",
    "map",
    "null",
    "nullable",
    "object",
    "one_of",
    "ref",
    "sha256",
    "text",
)

_FIELD_VARIANT_SCHEMAS = {
    kind: f"kir-ai-project-field-{kind.replace('_', '-')}/0"
    for kind in _FIELD_KINDS
}
_READ_COMMAND_VARIANT_SCHEMAS = {
    scope: f"kir-ai-project-read-command-{scope.replace('.', '-')}-variant/0"
    for scope in PROJECT_READ_SCOPES
}
_READ_RESULT_VARIANT_NAMES = (
    "exception-absent",
    "exception-present",
    "exception-index",
    "manifest",
    "module-absent",
    "module-present",
    "module-index",
    "root-instance",
)
_READ_RESULT_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-read-result-{name}-variant/0"
    for name in _READ_RESULT_VARIANT_NAMES
}
_QUERY_COMMAND_VARIANT_SCHEMAS = {
    scope: f"kir-ai-model-query-command-{scope.replace('_', '-')}-variant/0"
    for scope in MODEL_QUERY_SCOPES
}
_QUERY_RESULT_VARIANT_NAMES = (
    "logical-id",
    "origin-complete",
    "origin-partial",
    "summary",
)
_QUERY_RESULT_VARIANT_SCHEMAS = {
    name: f"kir-ai-model-query-result-{name}-variant/0"
    for name in _QUERY_RESULT_VARIANT_NAMES
}
_REQUEST_VARIANT_SCHEMAS = {
    tool: f"kir-ai-project-wire-request-{tool.replace('.', '-')}-variant/0"
    for tool in DECLARED_TOOL_NAMES
}
_WIRE_COVERAGE_VARIANT_SCHEMAS = {
    state: f"kir-ai-project-wire-coverage-{state.lower().replace('_', '-')}/0"
    for state in ("COMPLETE", "PARTIAL", "NOT_EVALUATED", "REFUSED")
}
_WIRE_COMPLETE_ONE_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-complete-one/0")
_WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-complete-one-zero/0")
_WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-complete-equal/0")
_WIRE_EVALUATED_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-evaluated/0")
_WIRE_NOT_EVALUATED_ONE_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-not-evaluated-one/0")
_WIRE_REFUSED_ONE_COVERAGE_SCHEMA = (
    "kir-ai-project-wire-coverage-refused-one/0")
_WIRE_RESPONSE_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-wire-response-{name}-variant/0"
    for name in (
        "capabilities-ok",
        "failed",
        "patch-id-contradiction",
        "project-state-conflict",
        "refused-available",
        "source-patch-ok",
    )
}
_WIRE_READ_OK_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-wire-response-project-read-{name}-ok-variant/0"
    for name in _READ_RESULT_VARIANT_NAMES
}
_WIRE_QUERY_OK_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-wire-response-model-query-{name}-ok-variant/0"
    for name in _QUERY_RESULT_VARIANT_NAMES
}
_WIRE_UNAVAILABLE_REFUSAL_VARIANT_SCHEMAS = {
    tool: (
        "kir-ai-project-wire-response-refused-"
        f"{tool.replace('.', '-')}-variant/0"
    )
    for tool in DECLARED_TOOL_NAMES
    if tool not in AVAILABLE_TOOL_NAMES
}
_K_COVERAGE_VARIANT_SCHEMAS = {
    state: f"kir-ai-project-coverage-{state.lower()}/0"
    for state in ("COMPLETE", "PARTIAL")
}
_K_COMPLETE_ONE_COVERAGE_SCHEMA = (
    "kir-ai-project-coverage-complete-one/0")
_K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA = (
    "kir-ai-project-coverage-complete-one-zero/0")
_K_COMPLETE_EQUAL_COVERAGE_SCHEMA = (
    "kir-ai-project-coverage-complete-equal/0")
_READ_RECEIPT_VARIANT_SCHEMAS = {
    kind: f"kir-ai-project-read-receipt-{kind.lower().replace('_', '-')}/0"
    for kind in ("PROJECT_READ", "MODEL_QUERY")
}
_READ_RESULT_RECEIPT_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-read-receipt-{name}-variant/0"
    for name in _READ_RESULT_VARIANT_NAMES
}
_QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS = {
    name: f"kir-ai-model-query-receipt-{name}-variant/0"
    for name in _QUERY_RESULT_VARIANT_NAMES
}
_WIRE_ERROR_VARIANT_SCHEMAS = {
    name: f"kir-ai-project-wire-error-{name}/0"
    for name in (
        "available-refusal",
        "failed",
        "patch-id-contradiction",
        "project-state-conflict",
    )
}
_WIRE_UNAVAILABLE_ERROR_SCHEMAS = {
    tool: f"kir-ai-project-wire-error-{tool.replace('.', '-')}-unavailable/0"
    for tool in DECLARED_TOOL_NAMES
    if tool not in AVAILABLE_TOOL_NAMES
}
_WIRE_UNAVAILABLE_DETAILS_SCHEMAS = {
    tool: f"kir-ai-project-wire-error-{tool.replace('.', '-')}-details/0"
    for tool in DECLARED_TOOL_NAMES
    if tool not in AVAILABLE_TOOL_NAMES
}
REACHABILITY = "OFFLINE_FIXTURE_ONLY"

PUBLISH_NOT_AVAILABLE_BEFORE_SRV1 = "PUBLISH_NOT_AVAILABLE_BEFORE_SRV1"
NOT_AVAILABLE_IN_PROJECT_V0 = "NOT_AVAILABLE_IN_PROJECT_V0"

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REASON_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")


def _exact_digest(value: Any, path: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise WireContractError(f"{path} must be exact lowercase sha256")
    return value


def _schema_uri(schema_id: str) -> str:
    slug = schema_id.removesuffix("/0")
    return f"urn:kir:ai-project-wire:schema:{slug}:0"


def _field(kind: str, *, required: bool = True, **constraints: Any) -> dict:
    return {"kind": kind, "required": required, **constraints}


def _ref(schema_ref: str, *, required: bool = True) -> dict:
    return _field("ref", required=required, schema_ref=schema_ref)


def _nullable(value: dict[str, Any], *, required: bool = True) -> dict:
    return _field("nullable", required=required, value=value)


def _one_of(
    *variants: dict[str, Any],
    required: bool = True,
) -> dict[str, Any]:
    return _field("one_of", required=required, variants=variants)


def _array(
    items: dict[str, Any],
    *,
    minimum: int,
    maximum: int,
    unique_by: str | None = None,
    ordering: str = "PRESERVE",
    required: bool = True,
) -> dict:
    return _field(
        "array",
        required=required,
        items=items,
        minimum=minimum,
        maximum=maximum,
        ordering=ordering,
        unique_by=unique_by,
    )


def _map(
    values: dict[str, Any],
    *,
    minimum: int = 0,
    maximum: int = 1_000_000,
    key_kind: str = "identifier",
    unique_values: bool = False,
    required: bool = True,
) -> dict:
    return _field(
        "map",
        required=required,
        key_kind=key_kind,
        maximum=maximum,
        minimum=minimum,
        unique_values=unique_values,
        values=values,
    )


def _closed_definition(
    schema_id: str,
    fields: dict[str, Any],
    *,
    max_bytes: int,
    invariants: tuple[str, ...] = (),
    variants: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "canonical_max_bytes": max_bytes,
        "fields": fields,
        "invariants": invariants,
        "kind": "one_of" if variants else "object",
        "schema": CLOSED_DEFINITION_SCHEMA,
        "shape_id": schema_id,
        "unknown_fields": "REFUSE",
        "variants": variants,
    }


def _schema_id(value: Any, path: str) -> str:
    admitted = exact_text(value, path, max_length=256)
    if (
        not admitted.endswith("/0")
        or not admitted.startswith(_ALLOWED_SCHEMA_PREFIXES)
    ):
        raise WireContractError(f"{path} is outside packaged schema namespaces")
    return admitted


_FIELD_CONSTRAINTS = {
    "array": frozenset({
        "items", "maximum", "minimum", "ordering", "unique_by"}),
    "bool": frozenset(),
    "canonical_json": frozenset({"max_bytes"}),
    "enum": frozenset({"values"}),
    "identifier": frozenset({"max_length"}),
    "integer": frozenset({"maximum", "minimum"}),
    "literal": frozenset({"value"}),
    "map": frozenset({
        "key_kind", "maximum", "minimum", "unique_values", "values"}),
    "null": frozenset(),
    "nullable": frozenset({"value"}),
    "object": frozenset({"closed"}),
    "one_of": frozenset({"variants"}),
    "ref": frozenset({"schema_ref"}),
    "sha256": frozenset(),
    "text": frozenset({"max_length"}),
}


def _validate_field_spec(value: Any, path: str, refs: set[str]) -> None:
    if type(value) is not FrozenMap:
        raise WireContractError(f"{path} must be an exact field object")
    kind = value.get("kind")
    if type(kind) is not str or kind not in _FIELD_KINDS:
        raise WireContractError(f"{path}.kind is outside the closed vocabulary")
    expected = {"kind", "required"} | set(_FIELD_CONSTRAINTS[kind])
    if set(value) != expected or type(value["required"]) is not bool:
        raise WireContractError(f"{path} constraints are not exact for {kind}")
    if kind == "ref":
        refs.add(_schema_id(value["schema_ref"], f"{path}.schema_ref"))
    elif kind == "nullable":
        _validate_field_spec(value["value"], f"{path}.value", refs)
    elif kind == "one_of":
        variants = value["variants"]
        if type(variants) is not tuple or len(variants) < 2:
            raise WireContractError(f"{path}.variants must be an exact union")
        for index, variant in enumerate(variants):
            _validate_field_spec(variant, f"{path}.variants[{index}]", refs)
    elif kind == "array":
        _validate_field_spec(value["items"], f"{path}.items", refs)
        if (
            type(value["minimum"]) is not int
            or type(value["maximum"]) is not int
            or not 0 <= value["minimum"] <= value["maximum"] <= 1_000_000
            or value["ordering"] not in {
                "LEXICAL_BY_KEY", "LEXICAL_VALUE", "PRESERVE"}
            or type(value["unique_by"]) not in {str, type(None)}
        ):
            raise WireContractError(f"{path} array constraints are invalid")
    elif kind == "map":
        _validate_field_spec(value["values"], f"{path}.values", refs)
        if (
            value["key_kind"] not in {"identifier", "text"}
            or type(value["minimum"]) is not int
            or type(value["maximum"]) is not int
            or not 0 <= value["minimum"] <= value["maximum"] <= 1_000_000
            or type(value["unique_values"]) is not bool
        ):
            raise WireContractError(f"{path} map constraints are invalid")
    elif kind in {"identifier", "text"}:
        if type(value["max_length"]) is not int or not (
            1 <= value["max_length"] <= 1_000_000
        ):
            raise WireContractError(f"{path}.max_length is invalid")
    elif kind == "integer":
        if (
            type(value["minimum"]) is not int
            or type(value["maximum"]) is not int
            or value["minimum"] > value["maximum"]
        ):
            raise WireContractError(f"{path} integer bounds are invalid")
    elif kind == "canonical_json":
        if type(value["max_bytes"]) is not int or not (
            1 <= value["max_bytes"] <= MAX_WIRE_BYTES
        ):
            raise WireContractError(f"{path}.max_bytes is invalid")
    elif kind == "enum":
        values = value["values"]
        if type(values) is not tuple or not values or len(set(values)) != len(values):
            raise WireContractError(f"{path}.values must be a unique exact array")
        for item in values:
            canonical_bytes(item)
    elif kind == "object" and type(value["closed"]) is not bool:
        raise WireContractError(f"{path}.closed must be exact bool")
    elif kind == "literal":
        canonical_bytes(value["value"])


def _validate_definition(value: FrozenMap, schema_id: str) -> frozenset[str]:
    if set(value) != {
        "canonical_max_bytes",
        "fields",
        "invariants",
        "kind",
        "schema",
        "shape_id",
        "unknown_fields",
        "variants",
    }:
        raise WireContractError("schema definition fields are not exact")
    if (
        value["schema"] != CLOSED_DEFINITION_SCHEMA
        or value["shape_id"] != schema_id
        or value["kind"] not in {"object", "one_of"}
        or value["unknown_fields"] != "REFUSE"
        or type(value["fields"]) is not FrozenMap
        or type(value["variants"]) is not tuple
        or type(value["invariants"]) is not tuple
        or type(value["canonical_max_bytes"]) is not int
        or not 0 < value["canonical_max_bytes"] <= MAX_WIRE_BYTES
    ):
        raise WireContractError("schema definition invariants are invalid")
    for invariant in value["invariants"]:
        exact_text(invariant, "schema invariant", max_length=1_024)
    refs: set[str] = set()
    if value["kind"] == "object":
        if value["variants"]:
            raise WireContractError("object definition cannot declare variants")
        for name, spec in value["fields"].items():
            exact_text(name, "schema field name", max_length=128)
            _validate_field_spec(spec, f"schema.fields.{name}", refs)
    else:
        if value["fields"] or len(value["variants"]) < 2:
            raise WireContractError("one_of definition shape is inconsistent")
        for index, spec in enumerate(value["variants"]):
            _validate_field_spec(spec, f"schema.variants[{index}]", refs)
            if spec["kind"] != "ref":
                raise WireContractError("top-level variants must be schema refs")
    return frozenset(refs)


@dataclass(frozen=True, slots=True)
class SchemaDescriptorV0:
    schema_id: str
    definition: FrozenMap | dict[str, Any]
    uri: str = field(init=False)
    digest: str = field(init=False)
    _schema_refs: frozenset[str] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        schema_id = _schema_id(
            self.schema_id, "schema_descriptor.schema_id")
        definition = fresh_object(
            self.definition, "schema_descriptor.definition", max_bytes=MAX_WIRE_BYTES)
        schema_refs = _validate_definition(definition, schema_id)
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "_schema_refs", schema_refs)
        uri = _schema_uri(schema_id)
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "digest", canonical_digest(
            "kir.ai-project-wire-schema.v0",
            {"definition": definition, "schema_id": schema_id, "uri": uri},
        ))

    @property
    def schema_refs(self) -> frozenset[str]:
        return self._schema_refs

    @property
    def pointer(self) -> FrozenMap:
        return fresh_object(
            {"digest": self.digest, "uri": self.uri},
            "schema pointer",
            max_bytes=1_024,
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "definition": self.definition,
            "digest": self.digest,
            "schema": SCHEMA_DESCRIPTOR_SCHEMA,
            "schema_id": self.schema_id,
            "uri": self.uri,
        }


@dataclass(frozen=True, slots=True)
class ToolCapabilityV0:
    name: str
    availability: str
    reason_code: str | None
    request_envelope_schema: FrozenMap | dict[str, Any] | None
    arguments_schema: FrozenMap | dict[str, Any] | None
    response_envelope_schema: FrozenMap | dict[str, Any] | None
    result_schema: FrozenMap | dict[str, Any] | None
    state_effect: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or self.name not in DECLARED_TOOL_NAMES:
            raise WireContractError("tool capability name is not declared")
        if (
            type(self.availability) is not str
            or self.availability not in {"AVAILABLE", "UNAVAILABLE"}
        ):
            raise WireContractError("tool availability is unsupported")
        reason = self.reason_code
        if self.availability == "AVAILABLE":
            if self.name not in AVAILABLE_TOOL_NAMES or reason is not None:
                raise WireContractError("available tool matrix is inconsistent")
            if any(pointer is None for pointer in (
                self.request_envelope_schema,
                self.arguments_schema,
                self.response_envelope_schema,
                self.result_schema,
            )):
                raise WireContractError(
                    "available tool requires four schema pointers")
        else:
            if self.name in AVAILABLE_TOOL_NAMES:
                raise WireContractError("available tool cannot be sealed unavailable")
            if (
                type(reason) is not str
                or _REASON_RE.fullmatch(reason) is None
                or any(pointer is not None for pointer in (
                    self.request_envelope_schema,
                    self.arguments_schema,
                    self.response_envelope_schema,
                    self.result_schema,
                ))
                or self.state_effect != "NONE"
            ):
                raise WireContractError("unavailable tool matrix is inconsistent")
        for name in (
            "request_envelope_schema",
            "arguments_schema",
            "response_envelope_schema",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _admit_pointer(
                    value, f"tool.{name}"))
        if self.result_schema is not None:
            object.__setattr__(self, "result_schema", _admit_pointer(
                self.result_schema, "tool.result_schema"))
        if type(self.state_effect) is not str or self.state_effect not in {
            "NONE",
            "OFFLINE_FIXTURE_LEDGER_TRANSITION",
            "OFFLINE_FIXTURE_REVISION_TRANSITION",
        }:
            raise WireContractError("tool state_effect is unsupported")

    def to_data(self) -> dict[str, Any]:
        return {
            "arguments_schema": self.arguments_schema,
            "availability": self.availability,
            "name": self.name,
            "reason_code": self.reason_code,
            "request_envelope_schema": self.request_envelope_schema,
            "response_envelope_schema": self.response_envelope_schema,
            "result_schema": self.result_schema,
            "schema": TOOL_CAPABILITY_SCHEMA,
            "state_effect": self.state_effect,
        }


def _admit_pointer(value: Any, path: str) -> FrozenMap:
    pointer = fresh_object(value, path, max_bytes=1_024)
    if set(pointer) != {"digest", "uri"}:
        raise WireContractError(f"{path} fields are not exact")
    _exact_digest(pointer["digest"], f"{path}.digest")
    exact_text(pointer["uri"], f"{path}.uri")
    return pointer


@dataclass(frozen=True, slots=True)
class CapabilityRegistryV0:
    canonical_profile: FrozenMap | dict[str, Any]
    schemas: tuple[SchemaDescriptorV0, ...] | list[SchemaDescriptorV0]
    tools: tuple[ToolCapabilityV0, ...] | list[ToolCapabilityV0]
    _registry_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        profile = fresh_object(
            self.canonical_profile, "registry.canonical_profile", max_bytes=4_096)
        if set(profile) != {
            "canonical_version",
            "max_argument_bytes",
            "max_coverage_bytes",
            "max_depth",
            "max_result_bytes",
            "max_wire_bytes",
            "unicode_data_version",
        }:
            raise WireContractError("canonical profile fields are not exact")
        expected_profile = _canonical_profile()
        if canonical_bytes(profile) != canonical_bytes(expected_profile):
            raise WireContractError("canonical profile values are not exact")
        schemas = tuple(self.schemas)
        tools = tuple(self.tools)
        if any(type(item) is not SchemaDescriptorV0 for item in schemas):
            raise WireContractError("registry schema child type is invalid")
        if any(type(item) is not ToolCapabilityV0 for item in tools):
            raise WireContractError("registry tool child type is invalid")
        schemas = tuple(sorted(schemas, key=lambda item: item.schema_id))
        if len({item.schema_id for item in schemas}) != len(schemas):
            raise WireContractError("registry has duplicate schema_id")
        expected_definitions = tuple(sorted(
            _schema_definitions(), key=lambda item: item[0]))
        expected_ids = tuple(item[0] for item in expected_definitions)
        if len(expected_ids) != len(set(expected_ids)):
            raise WireContractError("packaged schema census has duplicate schema_id")
        if tuple(item.schema_id for item in schemas) != expected_ids:
            raise WireContractError("registry schema census is not exact")
        for descriptor, (schema_id, definition) in zip(
            schemas,
            expected_definitions,
            strict=True,
        ):
            if (
                descriptor.schema_id != schema_id
                or canonical_bytes(descriptor.definition)
                != canonical_bytes(definition)
            ):
                raise WireContractError(
                    "registry schema definition is not the packaged value")
        schema_ids = frozenset(expected_ids)
        refs = frozenset(
            schema_ref
            for descriptor in schemas
            for schema_ref in descriptor.schema_refs
        )
        if not refs.issubset(schema_ids):
            raise WireContractError(
                "registry schema refs do not close inside the exact census")
        if tuple(item.name for item in tools) != DECLARED_TOOL_NAMES:
            raise WireContractError("registry tool census/order is not exact")
        expected_tools = _build_tools(schemas)
        if canonical_bytes(tuple(item.to_data() for item in tools)) != (
            canonical_bytes(tuple(item.to_data() for item in expected_tools))
        ):
            raise WireContractError("registry tool matrix is not exact")
        pointers = {(item.uri, item.digest) for item in schemas}
        for tool in tools:
            for pointer in (
                tool.request_envelope_schema,
                tool.arguments_schema,
                tool.response_envelope_schema,
                tool.result_schema,
            ):
                if pointer is not None and (
                    pointer["uri"], pointer["digest"]
                ) not in pointers:
                    raise WireContractError(
                        "tool schema pointer is outside this registry")
        object.__setattr__(self, "canonical_profile", profile)
        object.__setattr__(self, "schemas", schemas)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "_registry_digest", canonical_digest(
            "kir.ai-project-capability-registry.v0", self.body_data()))

    @property
    def registry_digest(self) -> str:
        return self._registry_digest

    def body_data(self) -> dict[str, Any]:
        return {
            "canonical_profile": self.canonical_profile,
            "protocol": PROTOCOL_VERSION,
            "reachability": REACHABILITY,
            "schema": REGISTRY_SCHEMA,
            "schemas": tuple(item.to_data() for item in self.schemas),
            "tools": tuple(item.to_data() for item in self.tools),
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.body_data(), "registry_digest": self.registry_digest}

    def verify_integrity(self) -> None:
        for descriptor in self.schemas:
            rebuilt = SchemaDescriptorV0(
                descriptor.schema_id, descriptor.definition)
            if canonical_bytes(rebuilt.to_data()) != canonical_bytes(
                descriptor.to_data()
            ):
                raise WireContractError("schema descriptor integrity failed")
        rebuilt = CapabilityRegistryV0(
            self.canonical_profile, self.schemas, self.tools)
        if canonical_bytes(rebuilt.to_data()) != canonical_bytes(self.to_data()):
            raise WireContractError("capability registry integrity failed")


def _canonical_profile() -> dict[str, Any]:
    return {
        "canonical_version": CANONICAL_VERSION,
        "max_argument_bytes": MAX_ARGUMENT_BYTES,
        "max_coverage_bytes": MAX_COVERAGE_BYTES,
        "max_depth": MAX_DEPTH,
        "max_result_bytes": MAX_RESULT_BYTES,
        "max_wire_bytes": MAX_WIRE_BYTES,
        "unicode_data_version": UNICODE_DATA_VERSION,
    }


def _schema_definitions() -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return the exact packaged, recursively closed schema census."""

    return (
        *_field_schema_definitions(),
        *_meta_schema_definitions(),
        *_selector_schema_definitions(),
        *_design_schema_definitions(),
        *_kernel_value_schema_definitions(),
        *_patch_schema_definitions(),
        *_project_read_schema_definitions(),
        *_model_query_schema_definitions(),
        *_wire_request_schema_definitions(),
        *_wire_response_schema_definitions(),
    )


def _field_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    definitions = []
    for kind in _FIELD_KINDS:
        fields = {
            "kind": _field("literal", value=kind),
            "required": _field("bool"),
        }
        invariants = ()
        if kind == "array":
            fields.update({
                "items": _ref(FIELD_DEFINITION_SCHEMA),
                "maximum": _field(
                    "integer", minimum=0, maximum=1_000_000),
                "minimum": _field(
                    "integer", minimum=0, maximum=1_000_000),
                "ordering": _field("enum", values=(
                    "LEXICAL_BY_KEY", "LEXICAL_VALUE", "PRESERVE")),
                "unique_by": _nullable(
                    _field("text", max_length=128)),
            })
            invariants = ("minimum <= maximum",)
        elif kind == "canonical_json":
            fields["max_bytes"] = _field(
                "integer", minimum=1, maximum=MAX_WIRE_BYTES)
        elif kind == "enum":
            fields["values"] = _array(
                _field("canonical_json", max_bytes=MAX_WIRE_BYTES),
                minimum=1,
                maximum=1_000_000,
            )
            invariants = ("values are canonically unique",)
        elif kind in {"identifier", "text"}:
            fields["max_length"] = _field(
                "integer", minimum=1, maximum=1_000_000)
        elif kind == "integer":
            fields.update({
                "maximum": _field(
                    "integer", minimum=-1_000_000_000, maximum=1_000_000_000),
                "minimum": _field(
                    "integer", minimum=-1_000_000_000, maximum=1_000_000_000),
            })
            invariants = ("minimum <= maximum",)
        elif kind == "literal":
            fields["value"] = _field(
                "canonical_json", max_bytes=MAX_WIRE_BYTES)
        elif kind == "map":
            fields.update({
                "key_kind": _field(
                    "enum", values=("identifier", "text")),
                "maximum": _field(
                    "integer", minimum=0, maximum=1_000_000),
                "minimum": _field(
                    "integer", minimum=0, maximum=1_000_000),
                "unique_values": _field("bool"),
                "values": _ref(FIELD_DEFINITION_SCHEMA),
            })
            invariants = ("minimum <= maximum",)
        elif kind == "nullable":
            fields["value"] = _ref(FIELD_DEFINITION_SCHEMA)
        elif kind == "object":
            fields["closed"] = _field("bool")
        elif kind == "one_of":
            fields["variants"] = _array(
                _ref(FIELD_DEFINITION_SCHEMA),
                minimum=2,
                maximum=1_000_000,
            )
        elif kind == "ref":
            fields["schema_ref"] = _field("text", max_length=256)
        definitions.append((
            _FIELD_VARIANT_SCHEMAS[kind],
            _closed_definition(
                _FIELD_VARIANT_SCHEMAS[kind],
                fields,
                max_bytes=MAX_COVERAGE_BYTES,
                invariants=invariants,
            ),
        ))
    definitions.append((
        FIELD_DEFINITION_SCHEMA,
        _closed_definition(
            FIELD_DEFINITION_SCHEMA,
            {},
            max_bytes=MAX_COVERAGE_BYTES,
            variants=tuple(
                _ref(_FIELD_VARIANT_SCHEMAS[kind])
                for kind in _FIELD_KINDS
            ),
        ),
    ))
    return tuple(definitions)


def _meta_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    pointer = _nullable(_ref(SCHEMA_POINTER_SCHEMA))
    return (
        (CLOSED_DEFINITION_SCHEMA, _closed_definition(
            CLOSED_DEFINITION_SCHEMA,
            {
                "canonical_max_bytes": _field(
                    "integer", minimum=1, maximum=MAX_WIRE_BYTES),
                "fields": _map(
                    _ref(FIELD_DEFINITION_SCHEMA),
                    key_kind="text",
                    maximum=1_000_000,
                ),
                "invariants": _array(
                    _field("text", max_length=1_024),
                    minimum=0,
                    maximum=1_000_000,
                ),
                "kind": _field("enum", values=("object", "one_of")),
                "schema": _field(
                    "literal", value=CLOSED_DEFINITION_SCHEMA),
                "shape_id": _field("text", max_length=256),
                "unknown_fields": _field("literal", value="REFUSE"),
                "variants": _array(
                    _ref(FIELD_DEFINITION_SCHEMA),
                    minimum=0,
                    maximum=1_000_000,
                ),
            },
            max_bytes=MAX_WIRE_BYTES,
            invariants=(
                "object definitions use fields and no variants",
                "one_of definitions use at least two ref variants and no fields",
                "shape_id equals the owning descriptor schema_id",
            ),
        )),
        (SCHEMA_POINTER_SCHEMA, _closed_definition(
            SCHEMA_POINTER_SCHEMA,
            {
                "digest": _field("sha256"),
                "uri": _field("text", max_length=4_096),
            },
            max_bytes=1_024,
        )),
        (CANONICAL_PROFILE_SCHEMA, _closed_definition(
            CANONICAL_PROFILE_SCHEMA,
            {
                "canonical_version": _field(
                    "literal", value=CANONICAL_VERSION),
                "max_argument_bytes": _field(
                    "literal", value=MAX_ARGUMENT_BYTES),
                "max_coverage_bytes": _field(
                    "literal", value=MAX_COVERAGE_BYTES),
                "max_depth": _field("literal", value=MAX_DEPTH),
                "max_result_bytes": _field(
                    "literal", value=MAX_RESULT_BYTES),
                "max_wire_bytes": _field(
                    "literal", value=MAX_WIRE_BYTES),
                "unicode_data_version": _field(
                    "literal", value=UNICODE_DATA_VERSION),
            },
            max_bytes=4_096,
        )),
        (SCHEMA_DESCRIPTOR_SCHEMA, _closed_definition(
            SCHEMA_DESCRIPTOR_SCHEMA,
            {
                "definition": _ref(CLOSED_DEFINITION_SCHEMA),
                "digest": _field("sha256"),
                "schema": _field(
                    "literal", value=SCHEMA_DESCRIPTOR_SCHEMA),
                "schema_id": _field("text", max_length=256),
                "uri": _field("text", max_length=4_096),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "digest is recomputed from schema_id, uri, and definition",
                "uri is the deterministic AP02-W URI for schema_id",
            ),
        )),
        (TOOL_CAPABILITY_SCHEMA, _closed_definition(
            TOOL_CAPABILITY_SCHEMA,
            {
                "arguments_schema": pointer,
                "availability": _field(
                    "enum", values=("AVAILABLE", "UNAVAILABLE")),
                "name": _field("enum", values=DECLARED_TOOL_NAMES),
                "reason_code": _nullable(
                    _field("text", max_length=128)),
                "request_envelope_schema": pointer,
                "response_envelope_schema": pointer,
                "result_schema": pointer,
                "schema": _field(
                    "literal", value=TOOL_CAPABILITY_SCHEMA),
                "state_effect": _field("enum", values=(
                    "NONE",
                    "OFFLINE_FIXTURE_LEDGER_TRANSITION",
                    "OFFLINE_FIXTURE_REVISION_TRANSITION",
                )),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "AVAILABLE requires four in-registry pointers and null reason_code",
                "UNAVAILABLE requires four null pointers, a reason_code, and NONE effect",
            ),
        )),
        (REGISTRY_SCHEMA, _closed_definition(
            REGISTRY_SCHEMA,
            {
                "canonical_profile": _ref(CANONICAL_PROFILE_SCHEMA),
                "protocol": _field("literal", value=PROTOCOL_VERSION),
                "reachability": _field("literal", value=REACHABILITY),
                "registry_digest": _field("sha256"),
                "schema": _field("literal", value=REGISTRY_SCHEMA),
                "schemas": _array(
                    _ref(SCHEMA_DESCRIPTOR_SCHEMA),
                    minimum=1,
                    maximum=1_000,
                    unique_by="schema_id",
                    ordering="LEXICAL_BY_KEY",
                ),
                "tools": _array(
                    _ref(TOOL_CAPABILITY_SCHEMA),
                    minimum=len(DECLARED_TOOL_NAMES),
                    maximum=len(DECLARED_TOOL_NAMES),
                    unique_by="name",
                    ordering="PRESERVE",
                ),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "schemas equal the exact packaged schema census",
                "all schema refs and tool pointers close inside this registry",
                "tools equal the declared tool order and exact availability matrix",
                "registry_digest is recomputed from the complete body",
            ),
        )),
        (CAPABILITIES_ARGUMENTS_SCHEMA, _closed_definition(
            CAPABILITIES_ARGUMENTS_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
    )


def _selector_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    return (
        (EMPTY_SELECTOR_SCHEMA, _closed_definition(
            EMPTY_SELECTOR_SCHEMA, {}, max_bytes=MAX_ARGUMENT_BYTES)),
        (MODULE_SELECTOR_SCHEMA, _closed_definition(
            MODULE_SELECTOR_SCHEMA,
            {"module_id": _field("identifier", max_length=64)},
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
        (EXCEPTION_SELECTOR_SCHEMA, _closed_definition(
            EXCEPTION_SELECTOR_SCHEMA,
            {"exception_id": _field("identifier", max_length=64)},
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
        (LOGICAL_ID_FILTER_SCHEMA, _closed_definition(
            LOGICAL_ID_FILTER_SCHEMA,
            {"logical_id": _field("identifier", max_length=64)},
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
        (ORIGIN_FILTER_SCHEMA, _closed_definition(
            ORIGIN_FILTER_SCHEMA,
            {
                name: _field(
                    "identifier", required=False, max_length=64)
                for name in ORIGIN_FILTER_FIELDS
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "at least one origin filter field is present",
                "no field outside the indexed origin filter set is admitted",
            ),
        )),
        (PROJECT_READ_SELECTOR_SCHEMA, _closed_definition(
            PROJECT_READ_SELECTOR_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
            variants=(
                _ref(EMPTY_SELECTOR_SCHEMA),
                _ref(EXCEPTION_SELECTOR_SCHEMA),
                _ref(MODULE_SELECTOR_SCHEMA),
            ),
        )),
        (MODEL_QUERY_FILTER_SCHEMA, _closed_definition(
            MODEL_QUERY_FILTER_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
            variants=(
                _ref(EMPTY_SELECTOR_SCHEMA),
                _ref(LOGICAL_ID_FILTER_SCHEMA),
                _ref(ORIGIN_FILTER_SCHEMA),
            ),
        )),
    )


def _design_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    canonical_value = _field(
        "canonical_json", max_bytes=MAX_ARGUMENT_BYTES)
    return (
        (ParameterSpecV0.SCHEMA, _closed_definition(
            ParameterSpecV0.SCHEMA,
            {
                "kind": _field("enum", values=(
                    "length",
                    "stable_key",
                    "stable_keys",
                    "module_ref",
                    "logical_id",
                )),
                "parameter_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=ParameterSpecV0.SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "length values normalize to canonical decimal text",
                "stable_key, module_ref, and logical_id values normalize to "
                "V0 identifiers",
                "stable_keys values normalize to a nonempty unique array of "
                "V0 identifiers while preserving caller order",
                "module_ref values resolve to an existing module",
            ),
        )),
        (SlotSpecV0.SCHEMA, _closed_definition(
            SlotSpecV0.SCHEMA,
            {
                "cardinality": _field(
                    "enum", values=("one", "optional", "keyed_many")),
                "kind": _field(
                    "enum", values=("entity", "module_instance")),
                "required_target_properties": _array(
                    _field("identifier", max_length=64),
                    minimum=0,
                    maximum=1_000_000,
                    ordering="LEXICAL_VALUE",
                ),
                "schema": _field("literal", value=SlotSpecV0.SCHEMA),
                "semantic_type": _field("identifier", max_length=64),
                "slot_id": _field("identifier", max_length=64),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "required_target_properties are sorted and unique",
            ),
        )),
        (GeneratorCallV0.SCHEMA, _closed_definition(
            GeneratorCallV0.SCHEMA,
            {
                "arguments": _map(
                    _field("identifier", max_length=64),
                    maximum=1_000_000,
                ),
                "bindings": _map(
                    _field("identifier", max_length=64),
                    maximum=1_000_000,
                    unique_values=True,
                ),
                "call_id": _field("identifier", max_length=64),
                "generator_digest": _field("sha256"),
                "generator_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=GeneratorCallV0.SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "argument values reference owning module parameter ids",
                "binding values reference owning module slot ids",
                "Generator calls expose only observed call identifiers, digests, "
                "argument references, and slot bindings; this registry declares "
                "no generator catalog and no arbitrary generator synthesis.",
            ),
        )),
        (ModuleV0.SCHEMA, _closed_definition(
            ModuleV0.SCHEMA,
            {
                "generator_calls": _map(
                    _ref(GeneratorCallV0.SCHEMA),
                    minimum=1,
                    maximum=1_000_000,
                ),
                "module_id": _field("identifier", max_length=64),
                "parameters": _map(
                    _ref(ParameterSpecV0.SCHEMA),
                    maximum=1_000_000,
                ),
                "schema": _field("literal", value=ModuleV0.SCHEMA),
                "slots": _map(
                    _ref(SlotSpecV0.SCHEMA),
                    maximum=1_000_000,
                ),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "map keys equal each child's id",
                "call parameter and slot references close inside this module",
                "this is semantic_data only; presentation metadata is forbidden",
            ),
        )),
        (RootInstanceV0.SCHEMA, _closed_definition(
            RootInstanceV0.SCHEMA,
            {
                "arguments": _map(
                    canonical_value,
                    maximum=1_000_000,
                ),
                "instance_id": _field("identifier", max_length=64),
                "module_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=RootInstanceV0.SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "arguments exactly cover the referenced module parameters and "
                "use each owning ParameterSpec normalization",
            ),
        )),
        (SetInstanceArgumentExceptionV0.SCHEMA, _closed_definition(
            SetInstanceArgumentExceptionV0.SCHEMA,
            {
                "exception_id": _field("identifier", max_length=64),
                "expected_value": canonical_value,
                "parameter_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=SetInstanceArgumentExceptionV0.SCHEMA),
                "target_instance_id": _field("identifier", max_length=64),
                "value": canonical_value,
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "parameter_id resolves in the target instance module and value "
                "and expected_value use its owning ParameterSpec normalization",
            ),
        )),
        (BuildOriginV0.SCHEMA, _closed_definition(
            BuildOriginV0.SCHEMA,
            {
                "call_id": _field("identifier", max_length=64),
                "exception_digests": _array(
                    _field("sha256"),
                    minimum=0,
                    maximum=1_000_000,
                    ordering="LEXICAL_VALUE",
                ),
                "generator_digest": _field("sha256"),
                "generator_id": _field("identifier", max_length=64),
                "identity_namespace_digest": _field("sha256"),
                "instance_id": _field("identifier", max_length=64),
                "module_digest": _field("sha256"),
                "module_id": _field("identifier", max_length=64),
                "occurrence_key": _field("identifier", max_length=64),
                "schema": _field("literal", value=BuildOriginV0.SCHEMA),
                "slot_id": _field("identifier", max_length=64),
                "source_digest": _field("sha256"),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=("exception_digests are sorted and unique",),
        )),
        (BuildEntityV0.SCHEMA, _closed_definition(
            BuildEntityV0.SCHEMA,
            {
                "dependencies": _array(
                    _field("identifier", max_length=64),
                    minimum=0,
                    maximum=1_000_000,
                    ordering="LEXICAL_VALUE",
                ),
                "geometry": _map(
                    _field("canonical_json", max_bytes=MAX_RESULT_BYTES),
                    key_kind="text",
                    maximum=1_000_000,
                ),
                "logical_id": _field("identifier", max_length=64),
                "origin": _ref(BuildOriginV0.SCHEMA),
                "properties": _map(
                    _field("canonical_json", max_bytes=MAX_RESULT_BYTES),
                    key_kind="text",
                    maximum=1_000_000,
                ),
                "schema": _field("literal", value=BuildEntityV0.SCHEMA),
                "semantic_type": _field("identifier", max_length=64),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=("dependencies are sorted and unique",),
        )),
        (BuildSummaryV0.schema, _closed_definition(
            BuildSummaryV0.schema,
            {
                "build_digest": _field("sha256"),
                "counts_by_semantic_type": _map(
                    _field(
                        "integer", minimum=0, maximum=1_000_000_000),
                    maximum=1_000_000,
                ),
                "entity_count": _field(
                    "integer", minimum=0, maximum=1_000_000_000),
                "schema": _field(
                    "literal", value=BuildSummaryV0.schema),
            },
            max_bytes=MAX_PAGE_BYTES,
            invariants=(
                "entity_count equals the sum of counts_by_semantic_type",
            ),
        )),
        (MANIFEST_VIEW_SCHEMA, _closed_definition(
            MANIFEST_VIEW_SCHEMA,
            {
                "build_digest": _field("sha256"),
                "entity_count": _field(
                    "integer", minimum=0, maximum=1_000_000_000),
                "exception_count": _field(
                    "integer", minimum=0, maximum=1_000_000_000),
                "instance_count": _field(
                    "integer", minimum=0, maximum=1_000_000_000),
                "module_count": _field(
                    "integer", minimum=0, maximum=1_000_000_000),
                "package_lock_digest": _field("sha256"),
                "project_id": _field("identifier", max_length=64),
                "revision_digest": _field("sha256"),
                "root_instance_id": _field("identifier", max_length=64),
                "root_module_id": _field("identifier", max_length=64),
                "schema": _field("literal", value=MANIFEST_VIEW_SCHEMA),
                "source_digest": _field("sha256"),
            },
            max_bytes=MAX_RESULT_BYTES,
        )),
        (MODULE_INDEX_ENTRY_SCHEMA, _closed_definition(
            MODULE_INDEX_ENTRY_SCHEMA,
            {
                "module_digest": _field("sha256"),
                "module_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=MODULE_INDEX_ENTRY_SCHEMA),
            },
            max_bytes=MAX_RESULT_BYTES,
        )),
        (EXCEPTION_INDEX_ENTRY_SCHEMA, _closed_definition(
            EXCEPTION_INDEX_ENTRY_SCHEMA,
            {
                "exception_digest": _field("sha256"),
                "exception_id": _field("identifier", max_length=64),
                "schema": _field(
                    "literal", value=EXCEPTION_INDEX_ENTRY_SCHEMA),
                "target_instance_id": _field("identifier", max_length=64),
            },
            max_bytes=MAX_RESULT_BYTES,
        )),
    )


def _coverage_fields(state: str) -> dict[str, Any]:
    minimum = 1 if state == "PARTIAL" else 0
    return {
        "evaluated": _field(
            "integer", minimum=minimum, maximum=1_000_000_000),
        "requested": _field(
            "integer", minimum=minimum, maximum=1_000_000_000),
        "returned": _field(
            "integer", minimum=minimum, maximum=1_000_000_000),
        "schema": _field("literal", value=K_COVERAGE_SCHEMA),
        "state": _field("literal", value=state),
    }


def _exact_k_complete_coverage_fields(
    requested: int,
    evaluated: int,
    returned: int,
) -> dict[str, Any]:
    fields = _coverage_fields("COMPLETE")
    for name, value in (
        ("requested", requested),
        ("evaluated", evaluated),
        ("returned", returned),
    ):
        fields[name] = _field(
            "integer", minimum=value, maximum=value)
    return fields


def _kernel_value_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    definitions = []
    for state, schema_id in _K_COVERAGE_VARIANT_SCHEMAS.items():
        invariants = ["evaluated equals requested"]
        if state == "COMPLETE":
            invariants.append("returned <= evaluated")
        else:
            invariants.extend((
                "0 < returned < requested",
                "requested is nonzero",
            ))
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                _coverage_fields(state),
                max_bytes=MAX_COVERAGE_BYTES,
                invariants=tuple(invariants),
            ),
        ))
    definitions.extend((
        (_K_COMPLETE_ONE_COVERAGE_SCHEMA, _closed_definition(
            _K_COMPLETE_ONE_COVERAGE_SCHEMA,
            _exact_k_complete_coverage_fields(1, 1, 1),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (_K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA, _closed_definition(
            _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
            _exact_k_complete_coverage_fields(1, 1, 0),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (_K_COMPLETE_EQUAL_COVERAGE_SCHEMA, _closed_definition(
            _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            _coverage_fields("COMPLETE"),
            max_bytes=MAX_COVERAGE_BYTES,
            invariants=("returned equals evaluated equals requested",),
        )),
    ))
    definitions.append((
        K_COVERAGE_SCHEMA,
        _closed_definition(
            K_COVERAGE_SCHEMA,
            {},
            max_bytes=MAX_COVERAGE_BYTES,
            variants=tuple(
                _ref(_K_COVERAGE_VARIANT_SCHEMAS[state])
                for state in ("COMPLETE", "PARTIAL")
            ),
        ),
    ))
    definitions.extend((
        (RECEIPT_REF_SCHEMA, _closed_definition(
            RECEIPT_REF_SCHEMA,
            {
                "receipt_digest": _field("sha256"),
                "receipt_id": _field("identifier", max_length=64),
                "schema": _field("literal", value=RECEIPT_REF_SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
        (CURSOR_REF_SCHEMA, _closed_definition(
            CURSOR_REF_SCHEMA,
            {
                "cursor_digest": _field("sha256"),
                "cursor_id": _field("identifier", max_length=64),
                "schema": _field("literal", value=CURSOR_REF_SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
        )),
    ))

    project_receipt = _READ_RECEIPT_VARIANT_SCHEMAS["PROJECT_READ"]
    query_receipt = _READ_RECEIPT_VARIANT_SCHEMAS["MODEL_QUERY"]

    def receipt_fields(
        *,
        kind: str,
        authority: str,
        scope: str,
        selector_schema: str,
        coverage_schema: str,
        present: dict[str, Any],
        object_digest: dict[str, Any],
        chain_digest: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "authority": _field("literal", value=authority),
            "build_digest": _field("sha256"),
            "chain_digest": chain_digest,
            "coverage": _ref(coverage_schema),
            "kind": _field("literal", value=kind),
            "object_digest": object_digest,
            "present": present,
            "project_id": _field("identifier", max_length=64),
            "receipt_digest": _field("sha256"),
            "receipt_id": _field("identifier", max_length=64),
            "result_digest": _field("sha256"),
            "revision_digest": _field("sha256"),
            "schema": _field("literal", value=READ_RECEIPT_SCHEMA),
            "scope": _field("literal", value=scope),
            "selector": _ref(selector_schema),
        }

    read_receipts = (
        (
            "manifest", "manifest", "INFORMATIONAL",
            EMPTY_SELECTOR_SCHEMA, _K_COMPLETE_ONE_COVERAGE_SCHEMA,
            _field("literal", value=True), _field("null"),
        ),
        (
            "module-index", "module.index", "INFORMATIONAL",
            EMPTY_SELECTOR_SCHEMA, _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            _field("null"), _field("null"),
        ),
        (
            "exception-index", "exception.index", "INFORMATIONAL",
            EMPTY_SELECTOR_SCHEMA, _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            _field("null"), _field("null"),
        ),
        (
            "root-instance", "root_instance", "OWNER",
            EMPTY_SELECTOR_SCHEMA, _K_COMPLETE_ONE_COVERAGE_SCHEMA,
            _field("literal", value=True), _field("sha256"),
        ),
        (
            "module-present", "module", "OWNER",
            MODULE_SELECTOR_SCHEMA, _K_COMPLETE_ONE_COVERAGE_SCHEMA,
            _field("literal", value=True), _field("sha256"),
        ),
        (
            "module-absent", "module", "OWNER",
            MODULE_SELECTOR_SCHEMA, _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
            _field("literal", value=False), _field("null"),
        ),
        (
            "exception-present", "exception", "OWNER",
            EXCEPTION_SELECTOR_SCHEMA, _K_COMPLETE_ONE_COVERAGE_SCHEMA,
            _field("literal", value=True), _field("sha256"),
        ),
        (
            "exception-absent", "exception", "OWNER",
            EXCEPTION_SELECTOR_SCHEMA, _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
            _field("literal", value=False), _field("null"),
        ),
    )
    for (
        name,
        scope,
        authority,
        selector_schema,
        coverage_schema,
        present,
        object_digest,
    ) in read_receipts:
        schema_id = _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                receipt_fields(
                    kind="PROJECT_READ",
                    authority=authority,
                    scope=scope,
                    selector_schema=selector_schema,
                    coverage_schema=coverage_schema,
                    present=present,
                    object_digest=object_digest,
                    chain_digest=_field("null"),
                ),
                max_bytes=MAX_RESULT_BYTES,
                invariants=(
                    "receipt_id and receipt_digest are recomputed from the exact body",
                ),
            ),
        ))
    definitions.append((
        project_receipt,
        _closed_definition(
            project_receipt,
            {},
            max_bytes=MAX_RESULT_BYTES,
            variants=tuple(
                _ref(_READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name])
                for name in _READ_RESULT_VARIANT_NAMES
            ),
        ),
    ))

    query_receipts = (
        (
            "summary", "summary", EMPTY_SELECTOR_SCHEMA,
            _K_COMPLETE_ONE_COVERAGE_SCHEMA,
        ),
        (
            "logical-id", "logical_id", LOGICAL_ID_FILTER_SCHEMA,
            _K_COMPLETE_ONE_COVERAGE_SCHEMA,
        ),
        (
            "origin-complete", "origin", ORIGIN_FILTER_SCHEMA,
            _K_COVERAGE_VARIANT_SCHEMAS["COMPLETE"],
        ),
        (
            "origin-partial", "origin", ORIGIN_FILTER_SCHEMA,
            _K_COVERAGE_VARIANT_SCHEMAS["PARTIAL"],
        ),
    )
    for name, scope, selector_schema, coverage_schema in query_receipts:
        schema_id = _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                receipt_fields(
                    kind="MODEL_QUERY",
                    authority="INFORMATIONAL",
                    scope=scope,
                    selector_schema=selector_schema,
                    coverage_schema=coverage_schema,
                    present=_field("null"),
                    object_digest=_field("null"),
                    chain_digest=_field("sha256"),
                ),
                max_bytes=MAX_RESULT_BYTES,
                invariants=(
                    "chain_digest binds page order and the prior cursor chain",
                    "receipt_id and receipt_digest are recomputed from the exact body",
                ),
            ),
        ))
    definitions.extend((
        (query_receipt, _closed_definition(
            query_receipt,
            {},
            max_bytes=MAX_RESULT_BYTES,
            variants=tuple(
                _ref(_QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name])
                for name in _QUERY_RESULT_VARIANT_NAMES
            ),
        )),
        (READ_RECEIPT_SCHEMA, _closed_definition(
            READ_RECEIPT_SCHEMA,
            {},
            max_bytes=MAX_RESULT_BYTES,
            variants=(
                _ref(project_receipt),
                _ref(query_receipt),
            ),
        )),
    ))
    return tuple(definitions)


def _patch_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    operation_definitions = (
        (MODULE_PUT_SCHEMA, {
            "module": _ref(ModuleV0.SCHEMA),
            "op_id": _field("identifier", max_length=64),
            "schema": _field("literal", value=MODULE_PUT_SCHEMA),
        }, ("module is exact semantic ModuleV0 without metadata",)),
        (ROOT_PUT_SCHEMA, {
            "op_id": _field("identifier", max_length=64),
            "root": _ref(RootInstanceV0.SCHEMA),
            "schema": _field("literal", value=ROOT_PUT_SCHEMA),
        }, ()),
        (EXCEPTION_PUT_SCHEMA, {
            "exception": _ref(SetInstanceArgumentExceptionV0.SCHEMA),
            "op_id": _field("identifier", max_length=64),
            "schema": _field("literal", value=EXCEPTION_PUT_SCHEMA),
        }, ()),
        (EXCEPTION_REMOVE_SCHEMA, {
            "exception_id": _field("identifier", max_length=64),
            "op_id": _field("identifier", max_length=64),
            "schema": _field("literal", value=EXCEPTION_REMOVE_SCHEMA),
        }, ()),
    )
    definitions = [
        (
            schema_id,
            _closed_definition(
                schema_id,
                fields,
                max_bytes=MAX_ARGUMENT_BYTES,
                invariants=invariants,
            ),
        )
        for schema_id, fields, invariants in operation_definitions
    ]
    definitions.extend((
        (PATCH_OPERATION_SCHEMA, _closed_definition(
            PATCH_OPERATION_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
            variants=tuple(_ref(schema_id) for schema_id in (
                MODULE_PUT_SCHEMA,
                ROOT_PUT_SCHEMA,
                EXCEPTION_PUT_SCHEMA,
                EXCEPTION_REMOVE_SCHEMA,
            )),
            invariants=("exactly these four patch operation shapes are admitted",),
        )),
        (SOURCE_PATCH_COMMAND_SCHEMA, _closed_definition(
            SOURCE_PATCH_COMMAND_SCHEMA,
            {
                "base_revision_digest": _field("sha256"),
                "operations": _array(
                    _ref(PATCH_OPERATION_SCHEMA),
                    minimum=1,
                    maximum=MAX_PATCH_OPS,
                    unique_by="op_id",
                    ordering="PRESERVE",
                ),
                "patch_id": _field("identifier", max_length=64),
                "project_id": _field("identifier", max_length=64),
                "receipt_refs": _array(
                    _ref(RECEIPT_REF_SCHEMA),
                    minimum=1,
                    maximum=MAX_RECEIPT_REFS,
                    unique_by="receipt_id",
                    ordering="LEXICAL_BY_KEY",
                ),
                "schema": _field(
                    "literal", value=SOURCE_PATCH_COMMAND_SCHEMA),
            },
            max_bytes=MAX_ARGUMENT_BYTES,
            invariants=(
                "operations preserve caller order and have unique op_id",
                "receipt_refs are sorted by receipt_id and unique",
                "only the four referenced operation variants are accepted",
                "a new patch is current-head-only and every receipt ref resolves "
                "exactly in the host ledger for the current project, revision, "
                "and build",
                "module, root, and exception writes require the corresponding "
                "exact OWNER project.read receipt",
                "exception changes require root ownership plus OWNER receipts "
                "for the old and new target ancestry module closure",
                "exception targets bind retained-base instances; structural target "
                "changes and exception changes must be staged across revisions",
                "a reused patch_id succeeds only for the same normalized semantic "
                "patch and otherwise returns PATCH_ID_CONTRADICTION",
            ),
        )),
        (SOURCE_PATCH_RESULT_SCHEMA, _closed_definition(
            SOURCE_PATCH_RESULT_SCHEMA,
            {
                "base_revision_digest": _field("sha256"),
                "build_digest": _field("sha256"),
                "patch_id": _field("identifier", max_length=64),
                "project_id": _field("identifier", max_length=64),
                "revision_digest": _field("sha256"),
                "schema": _field(
                    "literal", value=SOURCE_PATCH_RESULT_SCHEMA),
                "semantic_patch_digest": _field("sha256"),
                "source_digest": _field("sha256"),
                "transition_digest": _field("sha256"),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "transition_digest is recomputed from project, revisions, "
                "source, build, and semantic patch",
            ),
        )),
    ))
    return tuple(definitions)


def _read_command_fields(scope: str) -> dict[str, Any]:
    fields = {
        "project_id": _field("identifier", max_length=64),
        "revision_digest": _field("sha256"),
        "schema": _field("literal", value=PROJECT_READ_COMMAND_SCHEMA),
        "scope": _field("literal", value=scope),
    }
    if scope == "module":
        fields["module_id"] = _field("identifier", max_length=64)
    elif scope == "exception":
        fields["exception_id"] = _field("identifier", max_length=64)
    return fields


def _project_read_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    definitions = []
    for scope in PROJECT_READ_SCOPES:
        schema_id = _READ_COMMAND_VARIANT_SCHEMAS[scope]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                _read_command_fields(scope),
                max_bytes=MAX_ARGUMENT_BYTES,
                invariants=(
                    "project_id and revision_digest must bind the retained current head",
                ),
            ),
        ))
    definitions.append((
        PROJECT_READ_COMMAND_SCHEMA,
        _closed_definition(
            PROJECT_READ_COMMAND_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
            variants=tuple(
                _ref(_READ_COMMAND_VARIANT_SCHEMAS[scope])
                for scope in PROJECT_READ_SCOPES
            ),
        ),
    ))

    def result_fields(
        scope: str,
        selector_schema: str,
        coverage_schema: str,
        receipt_schema: str,
        present: dict[str, Any],
        value: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "build_digest": _field("sha256"),
            "coverage": _ref(coverage_schema),
            "cursor": _field("null"),
            "present": present,
            "project_id": _field("identifier", max_length=64),
            "receipt": _ref(receipt_schema),
            "revision_digest": _field("sha256"),
            "schema": _field("literal", value=PROJECT_READ_RESULT_SCHEMA),
            "scope": _field("literal", value=scope),
            "selector": _ref(selector_schema),
            "value": value,
        }

    read_variants = (
        (
            "manifest",
            "manifest",
            EMPTY_SELECTOR_SCHEMA,
            _field("literal", value=True),
            _ref(MANIFEST_VIEW_SCHEMA),
            ("coverage is exact COMPLETE 1/1/1",),
        ),
        (
            "module-index",
            "module.index",
            EMPTY_SELECTOR_SCHEMA,
            _field("null"),
            _array(
                _ref(MODULE_INDEX_ENTRY_SCHEMA),
                minimum=0,
                maximum=1_000_000,
                unique_by="module_id",
                ordering="LEXICAL_BY_KEY",
            ),
            ("coverage is COMPLETE N/N/N for the exact module census",),
        ),
        (
            "exception-index",
            "exception.index",
            EMPTY_SELECTOR_SCHEMA,
            _field("null"),
            _array(
                _ref(EXCEPTION_INDEX_ENTRY_SCHEMA),
                minimum=0,
                maximum=1_000_000,
                unique_by="exception_id",
                ordering="LEXICAL_BY_KEY",
            ),
            ("coverage is COMPLETE N/N/N for the exact exception census",),
        ),
        (
            "root-instance",
            "root_instance",
            EMPTY_SELECTOR_SCHEMA,
            _field("literal", value=True),
            _ref(RootInstanceV0.SCHEMA),
            ("coverage is exact COMPLETE 1/1/1",),
        ),
        (
            "module-present",
            "module",
            MODULE_SELECTOR_SCHEMA,
            _field("literal", value=True),
            _ref(ModuleV0.SCHEMA),
            ("coverage is exact COMPLETE 1/1/1",),
        ),
        (
            "module-absent",
            "module",
            MODULE_SELECTOR_SCHEMA,
            _field("literal", value=False),
            _field("null"),
            ("coverage is exact COMPLETE 1/1/0",),
        ),
        (
            "exception-present",
            "exception",
            EXCEPTION_SELECTOR_SCHEMA,
            _field("literal", value=True),
            _ref(SetInstanceArgumentExceptionV0.SCHEMA),
            ("coverage is exact COMPLETE 1/1/1",),
        ),
        (
            "exception-absent",
            "exception",
            EXCEPTION_SELECTOR_SCHEMA,
            _field("literal", value=False),
            _field("null"),
            ("coverage is exact COMPLETE 1/1/0",),
        ),
    )
    for (
        name,
        scope,
        selector_schema,
        present,
        value,
        coverage_invariants,
    ) in read_variants:
        schema_id = _READ_RESULT_VARIANT_SCHEMAS[name]
        coverage_schema = {
            "module-index": _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            "exception-index": _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            "module-absent": _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
            "exception-absent": _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
        }.get(name, _K_COMPLETE_ONE_COVERAGE_SCHEMA)
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                result_fields(
                    scope,
                    selector_schema,
                    coverage_schema,
                    _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name],
                    present,
                    value,
                ),
                max_bytes=MAX_RESULT_BYTES,
                invariants=(
                    *coverage_invariants,
                    "receipt is byte-identical to the exact result receipt",
                    "receipt authority, object digest, selector, presence, "
                    "and coverage bind this variant",
                ),
            ),
        ))
    definitions.append((
        PROJECT_READ_RESULT_SCHEMA,
        _closed_definition(
            PROJECT_READ_RESULT_SCHEMA,
            {},
            max_bytes=MAX_RESULT_BYTES,
            variants=tuple(
                _ref(_READ_RESULT_VARIANT_SCHEMAS[name])
                for name in _READ_RESULT_VARIANT_NAMES
            ),
        ),
    ))
    return tuple(definitions)


def _query_command_fields(
    scope: str,
    filter_schema: str,
) -> dict[str, Any]:
    return {
        "build_digest": _field("sha256"),
        "cursor": _nullable(_ref(CURSOR_REF_SCHEMA)),
        "filters": _ref(filter_schema),
        "limit": _field(
            "integer", minimum=1, maximum=MAX_PAGE_ITEMS),
        "project_id": _field("identifier", max_length=64),
        "revision_digest": _field("sha256"),
        "schema": _field("literal", value=MODEL_QUERY_COMMAND_SCHEMA),
        "scope": _field("literal", value=scope),
    }


def _model_query_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    definitions = []
    filter_schemas = {
        "summary": EMPTY_SELECTOR_SCHEMA,
        "logical_id": LOGICAL_ID_FILTER_SCHEMA,
        "origin": ORIGIN_FILTER_SCHEMA,
    }
    for scope in MODEL_QUERY_SCOPES:
        schema_id = _QUERY_COMMAND_VARIANT_SCHEMAS[scope]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                _query_command_fields(scope, filter_schemas[scope]),
                max_bytes=MAX_ARGUMENT_BYTES,
                invariants=(
                    "project, revision, and build bind the retained current head",
                    "a non-null cursor is resolved only from the host ledger "
                    "and binds every command field",
                ),
            ),
        ))
    definitions.append((
        MODEL_QUERY_COMMAND_SCHEMA,
        _closed_definition(
            MODEL_QUERY_COMMAND_SCHEMA,
            {},
            max_bytes=MAX_ARGUMENT_BYTES,
            variants=tuple(
                _ref(_QUERY_COMMAND_VARIANT_SCHEMAS[scope])
                for scope in MODEL_QUERY_SCOPES
            ),
        ),
    ))

    def result_fields(
        scope: str,
        filter_schema: str,
        coverage_schema: str,
        receipt_schema: str,
        items: dict[str, Any],
        cursor: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "build_digest": _field("sha256"),
            "coverage": _ref(coverage_schema),
            "cursor": cursor,
            "filters": _ref(filter_schema),
            "items": items,
            "project_id": _field("identifier", max_length=64),
            "receipt": _ref(receipt_schema),
            "revision_digest": _field("sha256"),
            "schema": _field("literal", value=MODEL_QUERY_RESULT_SCHEMA),
            "scope": _field("literal", value=scope),
        }

    query_variants = (
        (
            "summary",
            "summary",
            EMPTY_SELECTOR_SCHEMA,
            _array(
                _ref(BuildSummaryV0.schema),
                minimum=1,
                maximum=1,
            ),
            _field("null"),
            ("coverage is exact COMPLETE 1/1/1",),
        ),
        (
            "logical-id",
            "logical_id",
            LOGICAL_ID_FILTER_SCHEMA,
            _array(
                _ref(BuildEntityV0.SCHEMA),
                minimum=1,
                maximum=1,
                unique_by="logical_id",
                ordering="LEXICAL_BY_KEY",
            ),
            _field("null"),
            (
                "coverage is exact COMPLETE 1/1/1",
                "the entity logical_id equals filters.logical_id",
            ),
        ),
        (
            "origin-complete",
            "origin",
            ORIGIN_FILTER_SCHEMA,
            _array(
                _ref(BuildEntityV0.SCHEMA),
                minimum=0,
                maximum=MAX_PAGE_ITEMS,
                unique_by="logical_id",
                ordering="LEXICAL_BY_KEY",
            ),
            _field("null"),
            (
                "coverage is COMPLETE and may return fewer entities than "
                "the full evaluated census",
            ),
        ),
        (
            "origin-partial",
            "origin",
            ORIGIN_FILTER_SCHEMA,
            _array(
                _ref(BuildEntityV0.SCHEMA),
                minimum=1,
                maximum=MAX_PAGE_ITEMS,
                unique_by="logical_id",
                ordering="LEXICAL_BY_KEY",
            ),
            _ref(CURSOR_REF_SCHEMA),
            (
                "coverage is PARTIAL with 0 < returned < requested",
            ),
        ),
    )
    for (
        name,
        scope,
        filter_schema,
        items,
        cursor,
        coverage_invariants,
    ) in query_variants:
        schema_id = _QUERY_RESULT_VARIANT_SCHEMAS[name]
        coverage_schema = {
            "origin-complete": _K_COVERAGE_VARIANT_SCHEMAS["COMPLETE"],
            "origin-partial": _K_COVERAGE_VARIANT_SCHEMAS["PARTIAL"],
        }.get(name, _K_COMPLETE_ONE_COVERAGE_SCHEMA)
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                result_fields(
                    scope,
                    filter_schema,
                    coverage_schema,
                    _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name],
                    items,
                    cursor,
                ),
                max_bytes=MAX_PAGE_BYTES,
                invariants=(
                    *coverage_invariants,
                    "items satisfy the exact filter and are sorted by logical_id",
                    "receipt selector equals filters and its chain binds page order",
                    "the complete canonical result is at most 1,000,000 bytes",
                ),
            ),
        ))
    definitions.append((
        MODEL_QUERY_RESULT_SCHEMA,
        _closed_definition(
            MODEL_QUERY_RESULT_SCHEMA,
            {},
            max_bytes=MAX_PAGE_BYTES,
            variants=tuple(
                _ref(_QUERY_RESULT_VARIANT_SCHEMAS[name])
                for name in _QUERY_RESULT_VARIANT_NAMES
            ),
        ),
    ))
    return tuple(definitions)


def _wire_request_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    argument_schemas = {
        CAPABILITIES_TOOL: CAPABILITIES_ARGUMENTS_SCHEMA,
        MODEL_QUERY_TOOL: MODEL_QUERY_COMMAND_SCHEMA,
        PROJECT_READ_TOOL: PROJECT_READ_COMMAND_SCHEMA,
        SOURCE_PATCH_TOOL: SOURCE_PATCH_COMMAND_SCHEMA,
    }
    definitions = []
    for tool in DECLARED_TOOL_NAMES:
        schema_id = _REQUEST_VARIANT_SCHEMAS[tool]
        arguments_schema = argument_schemas.get(
            tool, CAPABILITIES_ARGUMENTS_SCHEMA)
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                {
                    "arguments": _ref(arguments_schema),
                    "protocol": _field(
                        "literal", value=PROTOCOL_VERSION),
                    "request_id": _field("identifier", max_length=64),
                    "tool": _field("literal", value=tool),
                },
                max_bytes=MAX_WIRE_BYTES,
                invariants=(
                    "arguments are at most 1,000,000 canonical bytes",
                    "caller authority, author, authentication, token, "
                    "principal, and approval fields are recursively forbidden",
                ),
            ),
        ))
    definitions.append((
        WIRE_REQUEST_SCHEMA,
        _closed_definition(
            WIRE_REQUEST_SCHEMA,
            {},
            max_bytes=MAX_WIRE_BYTES,
            variants=tuple(
                _ref(_REQUEST_VARIANT_SCHEMAS[tool])
                for tool in DECLARED_TOOL_NAMES
            ),
            invariants=(
                "sealed unavailable tools accept only the exact empty arguments object",
            ),
        ),
    ))
    return tuple(definitions)


def _wire_coverage_fields(
    state: str,
    *,
    exact_one: bool = False,
) -> dict[str, Any]:
    requested_minimum = 1 if state == "PARTIAL" else 0
    requested_maximum = 1_000_000_000
    evaluated_minimum = requested_minimum
    evaluated_maximum = 1_000_000_000
    returned_minimum = requested_minimum
    returned_maximum = 1_000_000_000
    if state in {"NOT_EVALUATED", "REFUSED"}:
        evaluated_minimum = evaluated_maximum = 0
        returned_minimum = returned_maximum = 0
    if exact_one:
        requested_minimum = requested_maximum = 1
        if state == "COMPLETE":
            evaluated_minimum = evaluated_maximum = 1
            returned_minimum = returned_maximum = 1
    return {
        "evaluated": _field(
            "integer",
            minimum=evaluated_minimum,
            maximum=evaluated_maximum,
        ),
        "requested": _field(
            "integer",
            minimum=requested_minimum,
            maximum=requested_maximum,
        ),
        "returned": _field(
            "integer",
            minimum=returned_minimum,
            maximum=returned_maximum,
        ),
        "schema": _field("literal", value=WIRE_COVERAGE_SCHEMA),
        "state": _field("literal", value=state),
    }


def _exact_wire_complete_coverage_fields(
    requested: int,
    evaluated: int,
    returned: int,
) -> dict[str, Any]:
    fields = _wire_coverage_fields("COMPLETE")
    for name, value in (
        ("requested", requested),
        ("evaluated", evaluated),
        ("returned", returned),
    ):
        fields[name] = _field(
            "integer", minimum=value, maximum=value)
    return fields


def _wire_response_schema_definitions(
) -> tuple[tuple[str, dict[str, Any]], ...]:
    definitions = []
    for state, schema_id in _WIRE_COVERAGE_VARIANT_SCHEMAS.items():
        invariants = []
        if state in {"COMPLETE", "PARTIAL"}:
            invariants.append("evaluated equals requested")
        if state == "PARTIAL":
            invariants.append("0 < returned < requested")
        elif state in {"NOT_EVALUATED", "REFUSED"}:
            invariants.append("evaluated and returned are zero")
        else:
            invariants.append("returned <= evaluated")
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                _wire_coverage_fields(state),
                max_bytes=MAX_COVERAGE_BYTES,
                invariants=tuple(invariants),
            ),
        ))
    definitions.extend((
        (_WIRE_COMPLETE_ONE_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA,
            _wire_coverage_fields("COMPLETE", exact_one=True),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (_WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
            _exact_wire_complete_coverage_fields(1, 1, 0),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (_WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
            _wire_coverage_fields("COMPLETE"),
            max_bytes=MAX_COVERAGE_BYTES,
            invariants=("returned equals evaluated equals requested",),
        )),
        (_WIRE_EVALUATED_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_EVALUATED_COVERAGE_SCHEMA,
            {},
            max_bytes=MAX_COVERAGE_BYTES,
            variants=(
                _ref(_WIRE_COVERAGE_VARIANT_SCHEMAS["COMPLETE"]),
                _ref(_WIRE_COVERAGE_VARIANT_SCHEMAS["PARTIAL"]),
            ),
        )),
        (_WIRE_NOT_EVALUATED_ONE_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_NOT_EVALUATED_ONE_COVERAGE_SCHEMA,
            _wire_coverage_fields("NOT_EVALUATED", exact_one=True),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (_WIRE_REFUSED_ONE_COVERAGE_SCHEMA, _closed_definition(
            _WIRE_REFUSED_ONE_COVERAGE_SCHEMA,
            _wire_coverage_fields("REFUSED", exact_one=True),
            max_bytes=MAX_COVERAGE_BYTES,
        )),
        (WIRE_COVERAGE_SCHEMA, _closed_definition(
            WIRE_COVERAGE_SCHEMA,
            {},
            max_bytes=MAX_COVERAGE_BYTES,
            variants=tuple(
                _ref(_WIRE_COVERAGE_VARIANT_SCHEMAS[state])
                for state in (
                    "COMPLETE", "PARTIAL", "NOT_EVALUATED", "REFUSED")
            ),
        )),
        (WIRE_ERROR_SCHEMA, _closed_definition(
            WIRE_ERROR_SCHEMA,
            {
                "code": _field("text", max_length=128),
                "details": _map(
                    _field(
                        "canonical_json", max_bytes=MAX_ERROR_DETAIL_BYTES),
                    key_kind="text",
                    maximum=1_000_000,
                ),
                "message": _field("text", max_length=4_096),
                "retryable": _field("bool"),
                "schema": _field("literal", value=WIRE_ERROR_SCHEMA),
            },
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "code matches the uppercase symbol grammar",
                "details are at most 65,536 canonical bytes",
                "offline fixture responses always set retryable false",
            ),
        )),
    ))

    def error_fields(
        code: dict[str, Any],
        message: dict[str, Any],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "code": code,
            "details": details,
            "message": message,
            "retryable": _field("literal", value=False),
            "schema": _field("literal", value=WIRE_ERROR_SCHEMA),
        }

    generic_details = _map(
        _field("canonical_json", max_bytes=MAX_ERROR_DETAIL_BYTES),
        key_kind="text",
        maximum=1_000_000,
    )
    for name, code in (
        ("project-state-conflict", "PROJECT_STATE_CONFLICT"),
        ("patch-id-contradiction", "PATCH_ID_CONTRADICTION"),
    ):
        schema_id = _WIRE_ERROR_VARIANT_SCHEMAS[name]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                error_fields(
                    _field("literal", value=code),
                    _field("text", max_length=4_096),
                    generic_details,
                ),
                max_bytes=MAX_RESULT_BYTES,
                invariants=(
                    "details are at most 65,536 canonical bytes",
                ),
            ),
        ))
    definitions.extend((
        (_WIRE_ERROR_VARIANT_SCHEMAS["available-refusal"], _closed_definition(
            _WIRE_ERROR_VARIANT_SCHEMAS["available-refusal"],
            error_fields(
                _field("text", max_length=128),
                _field("text", max_length=4_096),
                generic_details,
            ),
            max_bytes=MAX_RESULT_BYTES,
            invariants=(
                "code is an uppercase symbol other than PROJECT_STATE_CONFLICT, "
                "PATCH_ID_CONTRADICTION, or INTERNAL_FAILURE",
                "details are at most 65,536 canonical bytes",
            ),
        )),
        (_WIRE_ERROR_VARIANT_SCHEMAS["failed"], _closed_definition(
            _WIRE_ERROR_VARIANT_SCHEMAS["failed"],
            error_fields(
                _field("literal", value="INTERNAL_FAILURE"),
                _field(
                    "literal",
                    value="offline fixture request failed unexpectedly",
                ),
                _ref(EMPTY_SELECTOR_SCHEMA),
            ),
            max_bytes=MAX_RESULT_BYTES,
        )),
    ))
    for tool, error_schema in _WIRE_UNAVAILABLE_ERROR_SCHEMAS.items():
        details_schema = _WIRE_UNAVAILABLE_DETAILS_SCHEMAS[tool]
        reason = (
            PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
            if tool == "publish.prepare"
            else NOT_AVAILABLE_IN_PROJECT_V0
        )
        definitions.extend((
            (details_schema, _closed_definition(
                details_schema,
                {"tool": _field("literal", value=tool)},
                max_bytes=MAX_ERROR_DETAIL_BYTES,
            )),
            (error_schema, _closed_definition(
                error_schema,
                error_fields(
                    _field("literal", value=reason),
                    _field(
                        "literal",
                        value=(
                            "declared tool is unavailable in the offline "
                            "project V0 fixture"
                        ),
                    ),
                    _ref(details_schema),
                ),
                max_bytes=MAX_RESULT_BYTES,
            )),
        ))

    def response_fields(
        tool: dict[str, Any],
        status: str,
        coverage_schema: str,
        result: dict[str, Any],
        error: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "coverage": _ref(coverage_schema),
            "error": error,
            "protocol": _field("literal", value=PROTOCOL_VERSION),
            "read_receipt": receipt,
            "request_id": _field("identifier", max_length=64),
            "result": result,
            "status": _field("literal", value=status),
            "tool": tool,
        }

    ok_variants = (
        (
            "capabilities-ok",
            CAPABILITIES_TOOL,
            _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA,
            REGISTRY_SCHEMA,
            _field("null"),
            ("result is byte-identical to the captured packaged registry",),
        ),
        (
            "source-patch-ok",
            SOURCE_PATCH_TOOL,
            _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA,
            SOURCE_PATCH_RESULT_SCHEMA,
            _field("null"),
            ("success creates or replays an offline revision; it does not publish",),
        ),
    )
    for (
        name,
        tool,
        coverage_schema,
        result_schema,
        receipt,
        invariants,
    ) in ok_variants:
        schema_id = _WIRE_RESPONSE_VARIANT_SCHEMAS[name]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                response_fields(
                    _field("literal", value=tool),
                    "OK",
                    coverage_schema,
                    _ref(result_schema),
                    _field("null"),
                    receipt,
                ),
                max_bytes=MAX_WIRE_BYTES,
                invariants=invariants,
            ),
        ))

    read_wire_coverage = {
        "module-index": _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "exception-index": _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "module-absent": _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
        "exception-absent": _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
    }
    for name in _READ_RESULT_VARIANT_NAMES:
        schema_id = _WIRE_READ_OK_VARIANT_SCHEMAS[name]
        coverage_schema = read_wire_coverage.get(
            name, _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA)
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                response_fields(
                    _field("literal", value=PROJECT_READ_TOOL),
                    "OK",
                    coverage_schema,
                    _ref(_READ_RESULT_VARIANT_SCHEMAS[name]),
                    _field("null"),
                    _ref(_READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name]),
                ),
                max_bytes=MAX_WIRE_BYTES,
                invariants=(
                    "wire coverage exactly mirrors result coverage",
                    "outer read_receipt is byte-identical to result.receipt",
                ),
            ),
        ))

    query_wire_coverage = {
        "origin-complete": _WIRE_COVERAGE_VARIANT_SCHEMAS["COMPLETE"],
        "origin-partial": _WIRE_COVERAGE_VARIANT_SCHEMAS["PARTIAL"],
    }
    for name in _QUERY_RESULT_VARIANT_NAMES:
        schema_id = _WIRE_QUERY_OK_VARIANT_SCHEMAS[name]
        coverage_schema = query_wire_coverage.get(
            name, _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA)
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                response_fields(
                    _field("literal", value=MODEL_QUERY_TOOL),
                    "OK",
                    coverage_schema,
                    _ref(_QUERY_RESULT_VARIANT_SCHEMAS[name]),
                    _field("null"),
                    _ref(_QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name]),
                ),
                max_bytes=MAX_WIRE_BYTES,
                invariants=(
                    "wire coverage exactly mirrors result coverage",
                    "outer read_receipt is byte-identical to result.receipt",
                ),
            ),
        ))

    conflict_variants = (
        (
            "project-state-conflict",
            _field("enum", values=(
                MODEL_QUERY_TOOL,
                PROJECT_READ_TOOL,
                SOURCE_PATCH_TOOL,
            )),
            _WIRE_ERROR_VARIANT_SCHEMAS["project-state-conflict"],
        ),
        (
            "patch-id-contradiction",
            _field("literal", value=SOURCE_PATCH_TOOL),
            _WIRE_ERROR_VARIANT_SCHEMAS["patch-id-contradiction"],
        ),
    )
    for name, tools, error_schema in conflict_variants:
        schema_id = _WIRE_RESPONSE_VARIANT_SCHEMAS[name]
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                response_fields(
                    tools,
                    "CONFLICT",
                    _WIRE_NOT_EVALUATED_ONE_COVERAGE_SCHEMA,
                    _field("null"),
                    _ref(error_schema),
                    _field("null"),
                ),
                max_bytes=MAX_WIRE_BYTES,
            ),
        ))

    available_refused = _WIRE_RESPONSE_VARIANT_SCHEMAS["refused-available"]
    definitions.append((
        available_refused,
        _closed_definition(
            available_refused,
            response_fields(
                _field("enum", values=AVAILABLE_TOOL_NAMES),
                "REFUSED",
                _WIRE_REFUSED_ONE_COVERAGE_SCHEMA,
                _field("null"),
                _ref(_WIRE_ERROR_VARIANT_SCHEMAS["available-refusal"]),
                _field("null"),
            ),
            max_bytes=MAX_WIRE_BYTES,
        ),
    ))
    for tool, schema_id in _WIRE_UNAVAILABLE_REFUSAL_VARIANT_SCHEMAS.items():
        definitions.append((
            schema_id,
            _closed_definition(
                schema_id,
                response_fields(
                    _field("literal", value=tool),
                    "REFUSED",
                    _WIRE_REFUSED_ONE_COVERAGE_SCHEMA,
                    _field("null"),
                    _ref(_WIRE_UNAVAILABLE_ERROR_SCHEMAS[tool]),
                    _field("null"),
                ),
                max_bytes=MAX_WIRE_BYTES,
            ),
        ))

    failed_schema = _WIRE_RESPONSE_VARIANT_SCHEMAS["failed"]
    definitions.append((
        failed_schema,
        _closed_definition(
            failed_schema,
            response_fields(
                _field("enum", values=AVAILABLE_TOOL_NAMES),
                "FAILED",
                _WIRE_NOT_EVALUATED_ONE_COVERAGE_SCHEMA,
                _field("null"),
                _ref(_WIRE_ERROR_VARIANT_SCHEMAS["failed"]),
                _field("null"),
            ),
            max_bytes=MAX_WIRE_BYTES,
        ),
    ))

    response_variants = (
        _ref(_WIRE_RESPONSE_VARIANT_SCHEMAS["capabilities-ok"]),
        *(
            _ref(_WIRE_READ_OK_VARIANT_SCHEMAS[name])
            for name in _READ_RESULT_VARIANT_NAMES
        ),
        *(
            _ref(_WIRE_QUERY_OK_VARIANT_SCHEMAS[name])
            for name in _QUERY_RESULT_VARIANT_NAMES
        ),
        _ref(_WIRE_RESPONSE_VARIANT_SCHEMAS["source-patch-ok"]),
        _ref(_WIRE_RESPONSE_VARIANT_SCHEMAS["project-state-conflict"]),
        _ref(_WIRE_RESPONSE_VARIANT_SCHEMAS["patch-id-contradiction"]),
        _ref(available_refused),
        *(
            _ref(_WIRE_UNAVAILABLE_REFUSAL_VARIANT_SCHEMAS[tool])
            for tool in DECLARED_TOOL_NAMES
            if tool not in AVAILABLE_TOOL_NAMES
        ),
        _ref(failed_schema),
    )
    definitions.append((
        WIRE_RESPONSE_SCHEMA,
        _closed_definition(
            WIRE_RESPONSE_SCHEMA,
            {},
            max_bytes=MAX_WIRE_BYTES,
            variants=response_variants,
            invariants=("no unavailable tool can return OK",),
        ),
    ))
    return tuple(definitions)


def _build_tools(
    descriptors: tuple[SchemaDescriptorV0, ...],
) -> tuple[ToolCapabilityV0, ...]:
    by_id = {item.schema_id: item for item in descriptors}
    request_pointer = by_id[WIRE_REQUEST_SCHEMA].pointer
    response_pointer = by_id[WIRE_RESPONSE_SCHEMA].pointer
    argument_ids = {
        CAPABILITIES_TOOL: CAPABILITIES_ARGUMENTS_SCHEMA,
        MODEL_QUERY_TOOL: MODEL_QUERY_COMMAND_SCHEMA,
        PROJECT_READ_TOOL: PROJECT_READ_COMMAND_SCHEMA,
        SOURCE_PATCH_TOOL: SOURCE_PATCH_COMMAND_SCHEMA,
    }
    result_ids = {
        CAPABILITIES_TOOL: REGISTRY_SCHEMA,
        MODEL_QUERY_TOOL: MODEL_QUERY_RESULT_SCHEMA,
        PROJECT_READ_TOOL: PROJECT_READ_RESULT_SCHEMA,
        SOURCE_PATCH_TOOL: SOURCE_PATCH_RESULT_SCHEMA,
    }
    tools = []
    for name in DECLARED_TOOL_NAMES:
        available = name in AVAILABLE_TOOL_NAMES
        reason = None
        if not available:
            reason = (
                PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
                if name == "publish.prepare"
                else NOT_AVAILABLE_IN_PROJECT_V0
            )
        effect = "NONE"
        if name in {MODEL_QUERY_TOOL, PROJECT_READ_TOOL}:
            effect = "OFFLINE_FIXTURE_LEDGER_TRANSITION"
        elif name == SOURCE_PATCH_TOOL:
            effect = "OFFLINE_FIXTURE_REVISION_TRANSITION"
        tools.append(ToolCapabilityV0(
            name=name,
            availability="AVAILABLE" if available else "UNAVAILABLE",
            reason_code=reason,
            request_envelope_schema=request_pointer if available else None,
            arguments_schema=(
                by_id[argument_ids[name]].pointer if available else None),
            response_envelope_schema=response_pointer if available else None,
            result_schema=(
                by_id[result_ids[name]].pointer if available else None),
            state_effect=effect,
        ))
    return tuple(tools)


def _build_registry() -> CapabilityRegistryV0:
    descriptors = tuple(
        SchemaDescriptorV0(schema_id, definition)
        for schema_id, definition in _schema_definitions()
    )
    return CapabilityRegistryV0(
        _canonical_profile(),
        descriptors,
        _build_tools(descriptors),
    )


def admit_capability_registry(value: Any) -> CapabilityRegistryV0:
    """Recompute every child and registry digest from one fresh exact value."""

    raw = fresh_object(value, "capability registry", max_bytes=MAX_RESULT_BYTES)
    if set(raw) != {
        "canonical_profile",
        "protocol",
        "reachability",
        "registry_digest",
        "schema",
        "schemas",
        "tools",
    }:
        raise WireContractError("capability registry fields are not exact")
    if (
        raw["schema"] != REGISTRY_SCHEMA
        or raw["protocol"] != PROTOCOL_VERSION
        or raw["reachability"] != REACHABILITY
    ):
        raise WireContractError("capability registry literals are not exact")
    if type(raw["schemas"]) is not tuple or type(raw["tools"]) is not tuple:
        raise WireContractError("capability registry arrays are not exact")

    descriptors = []
    for index, item in enumerate(raw["schemas"]):
        if type(item) is not FrozenMap or set(item) != {
            "definition", "digest", "schema", "schema_id", "uri"
        }:
            raise WireContractError(
                f"registry.schemas[{index}] fields are not exact")
        if item["schema"] != SCHEMA_DESCRIPTOR_SCHEMA:
            raise WireContractError("schema descriptor literal is not exact")
        descriptor = SchemaDescriptorV0(item["schema_id"], item["definition"])
        if canonical_bytes(descriptor.to_data()) != canonical_bytes(item):
            raise WireContractError("schema descriptor digest/value mismatch")
        descriptors.append(descriptor)

    tools = []
    for index, item in enumerate(raw["tools"]):
        if type(item) is not FrozenMap or set(item) != {
            "arguments_schema",
            "availability",
            "name",
            "reason_code",
            "request_envelope_schema",
            "response_envelope_schema",
            "result_schema",
            "schema",
            "state_effect",
        }:
            raise WireContractError(
                f"registry.tools[{index}] fields are not exact")
        if item["schema"] != TOOL_CAPABILITY_SCHEMA:
            raise WireContractError("tool capability literal is not exact")
        tools.append(ToolCapabilityV0(
            name=item["name"],
            availability=item["availability"],
            reason_code=item["reason_code"],
            request_envelope_schema=item["request_envelope_schema"],
            arguments_schema=item["arguments_schema"],
            response_envelope_schema=item["response_envelope_schema"],
            result_schema=item["result_schema"],
            state_effect=item["state_effect"],
        ))
    admitted = CapabilityRegistryV0(
        raw["canonical_profile"], tuple(descriptors), tuple(tools))
    _exact_digest(raw["registry_digest"], "registry.registry_digest")
    if canonical_bytes(admitted.to_data()) != canonical_bytes(raw):
        raise WireContractError("capability registry digest/value mismatch")
    if canonical_bytes(raw) != _PACKAGED_REGISTRY_BYTES:
        raise WireContractError(
            "capability registry is not the exact packaged value")
    return admitted


CAPABILITY_REGISTRY = _build_registry()
_PACKAGED_REGISTRY_BYTES = canonical_bytes(CAPABILITY_REGISTRY.to_data())
CAPABILITY_REGISTRY.verify_integrity()


__all__ = [
    "CAPABILITIES_ARGUMENTS_SCHEMA",
    "CAPABILITY_REGISTRY",
    "CLOSED_DEFINITION_SCHEMA",
    "CapabilityRegistryV0",
    "NOT_AVAILABLE_IN_PROJECT_V0",
    "PUBLISH_NOT_AVAILABLE_BEFORE_SRV1",
    "REACHABILITY",
    "REGISTRY_SCHEMA",
    "SCHEMA_DESCRIPTOR_SCHEMA",
    "SchemaDescriptorV0",
    "TOOL_CAPABILITY_SCHEMA",
    "ToolCapabilityV0",
    "admit_capability_registry",
]
