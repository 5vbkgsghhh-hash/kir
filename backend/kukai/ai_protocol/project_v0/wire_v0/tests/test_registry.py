from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.project_v0.wire_v0 import (
    AVAILABLE_TOOL_NAMES,
    CAPABILITY_REGISTRY,
    DECLARED_TOOL_NAMES,
)
from kukai.ai_protocol.project_v0.wire_v0.registry import (
    FIELD_DEFINITION_SCHEMA,
    MODEL_QUERY_COMMAND_SCHEMA,
    MODEL_QUERY_RESULT_SCHEMA,
    NOT_AVAILABLE_IN_PROJECT_V0,
    PATCH_OPERATION_SCHEMA,
    PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
    PROJECT_READ_COMMAND_SCHEMA,
    PROJECT_READ_RESULT_SCHEMA,
    REACHABILITY,
    SOURCE_PATCH_COMMAND_SCHEMA,
    WIRE_RESPONSE_SCHEMA,
    _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
    _K_COMPLETE_ONE_COVERAGE_SCHEMA,
    _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
    _K_COVERAGE_VARIANT_SCHEMAS,
    _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS,
    _QUERY_RESULT_VARIANT_NAMES,
    _QUERY_RESULT_VARIANT_SCHEMAS,
    _READ_RECEIPT_VARIANT_SCHEMAS,
    _READ_RESULT_RECEIPT_VARIANT_SCHEMAS,
    _READ_RESULT_VARIANT_NAMES,
    _READ_RESULT_VARIANT_SCHEMAS,
    _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
    _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA,
    _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
    _WIRE_COVERAGE_VARIANT_SCHEMAS,
    _WIRE_ERROR_VARIANT_SCHEMAS,
    _WIRE_QUERY_OK_VARIANT_SCHEMAS,
    _WIRE_READ_OK_VARIANT_SCHEMAS,
    _WIRE_RESPONSE_VARIANT_SCHEMAS,
    _WIRE_UNAVAILABLE_ERROR_SCHEMAS,
    _WIRE_UNAVAILABLE_REFUSAL_VARIANT_SCHEMAS,
    admit_capability_registry,
)
from kukai.ai_protocol.project_v0.schemas import (
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
    MODULE_PUT_SCHEMA,
    ROOT_PUT_SCHEMA,
)
from kukai.design_source import GeneratorCallV0, ModuleV0
from kukai.ai_protocol.project_v0.wire_v0.errors import WireContractError
from kukai.design_source import canonical_bytes, canonical_digest


_FIELD_CONSTRAINTS = {
    "array": {"items", "maximum", "minimum", "ordering", "unique_by"},
    "bool": set(),
    "canonical_json": {"max_bytes"},
    "enum": {"values"},
    "identifier": {"max_length"},
    "integer": {"maximum", "minimum"},
    "literal": {"value"},
    "map": {"key_kind", "maximum", "minimum", "unique_values", "values"},
    "null": set(),
    "nullable": {"value"},
    "object": {"closed"},
    "one_of": {"variants"},
    "ref": {"schema_ref"},
    "sha256": set(),
    "text": {"max_length"},
}


def _descriptor(data, schema_id):
    return next(
        item for item in data["schemas"] if item["schema_id"] == schema_id)


def _recompute_descriptor(descriptor):
    descriptor["digest"] = canonical_digest(
        "kir.ai-project-wire-schema.v0",
        {
            "definition": descriptor["definition"],
            "schema_id": descriptor["schema_id"],
            "uri": descriptor["uri"],
        },
    )


def _recompute_registry(data):
    data["registry_digest"] = canonical_digest(
        "kir.ai-project-capability-registry.v0",
        {key: value for key, value in data.items() if key != "registry_digest"},
    )


def _walk_field_spec(spec, refs):
    kind = spec["kind"]
    assert kind in _FIELD_CONSTRAINTS
    assert set(spec) == {"kind", "required"} | _FIELD_CONSTRAINTS[kind]
    assert type(spec["required"]) is bool
    if kind == "ref":
        refs.add(spec["schema_ref"])
    elif kind == "nullable":
        _walk_field_spec(spec["value"], refs)
    elif kind == "one_of":
        assert len(spec["variants"]) >= 2
        for variant in spec["variants"]:
            _walk_field_spec(variant, refs)
    elif kind == "array":
        _walk_field_spec(spec["items"], refs)
    elif kind == "map":
        _walk_field_spec(spec["values"], refs)


def test_registry_self_verifies_exact_matrix_and_child_digests() -> None:
    CAPABILITY_REGISTRY.verify_integrity()
    data = CAPABILITY_REGISTRY.to_data()

    assert data["reachability"] == REACHABILITY == "OFFLINE_FIXTURE_ONLY"
    assert tuple(item["name"] for item in data["tools"]) == DECLARED_TOOL_NAMES
    available = tuple(
        item["name"] for item in data["tools"]
        if item["availability"] == "AVAILABLE"
    )
    assert available == AVAILABLE_TOOL_NAMES
    for descriptor in data["schemas"]:
        assert descriptor["definition"]["unknown_fields"] == "REFUSE"
        assert descriptor["digest"] == canonical_digest(
            "kir.ai-project-wire-schema.v0",
            {
                "definition": descriptor["definition"],
                "schema_id": descriptor["schema_id"],
                "uri": descriptor["uri"],
            },
        )
    assert data["registry_digest"] == canonical_digest(
        "kir.ai-project-capability-registry.v0",
        {key: value for key, value in data.items() if key != "registry_digest"},
    )

    reasons = {item["name"]: item["reason_code"] for item in data["tools"]}
    assert reasons["publish.prepare"] == PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
    for tool in DECLARED_TOOL_NAMES:
        if tool not in AVAILABLE_TOOL_NAMES and tool != "publish.prepare":
            assert reasons[tool] == NOT_AVAILABLE_IN_PROJECT_V0
    for item in data["tools"]:
        pointers = (
            item["request_envelope_schema"],
            item["arguments_schema"],
            item["response_envelope_schema"],
            item["result_schema"],
        )
        if item["availability"] == "AVAILABLE":
            assert all(pointer is not None for pointer in pointers)
        else:
            assert pointers == (None, None, None, None)


def test_registry_readmission_is_fresh_and_exact() -> None:
    admitted = admit_capability_registry(CAPABILITY_REGISTRY.to_data())

    assert admitted is not CAPABILITY_REGISTRY
    assert admitted.schemas[0] is not CAPABILITY_REGISTRY.schemas[0]
    assert canonical_bytes(admitted.to_data()) == canonical_bytes(
        CAPABILITY_REGISTRY.to_data())


def test_registry_field_grammar_and_schema_refs_are_recursively_closed() -> None:
    data = CAPABILITY_REGISTRY.to_data()
    schema_ids = {item["schema_id"] for item in data["schemas"]}
    assert len(schema_ids) == len(data["schemas"]) == 157
    assert FIELD_DEFINITION_SCHEMA in schema_ids
    assert all(
        schema_id.startswith(("kir-ai-", "kir-design-", "kir-build-"))
        and schema_id.endswith("/0")
        for schema_id in schema_ids
    )

    refs = set()
    for descriptor in data["schemas"]:
        definition = descriptor["definition"]
        assert set(definition) == {
            "canonical_max_bytes",
            "fields",
            "invariants",
            "kind",
            "schema",
            "shape_id",
            "unknown_fields",
            "variants",
        }
        assert definition["shape_id"] == descriptor["schema_id"]
        assert definition["unknown_fields"] == "REFUSE"
        if definition["kind"] == "object":
            assert definition["variants"] == ()
            specs = definition["fields"].values()
        else:
            assert definition["kind"] == "one_of"
            assert definition["fields"] == {}
            assert len(definition["variants"]) >= 2
            specs = definition["variants"]
        for spec in specs:
            _walk_field_spec(spec, refs)
    assert refs <= schema_ids


def test_registry_exposes_exact_semantic_and_conditional_variant_census() -> None:
    data = CAPABILITY_REGISTRY.to_data()
    expected_variants = {
        PROJECT_READ_COMMAND_SCHEMA: 6,
        PROJECT_READ_RESULT_SCHEMA: 8,
        MODEL_QUERY_COMMAND_SCHEMA: 3,
        MODEL_QUERY_RESULT_SCHEMA: 4,
        WIRE_RESPONSE_SCHEMA: 23,
    }
    for schema_id, count in expected_variants.items():
        definition = _descriptor(data, schema_id)["definition"]
        assert definition["kind"] == "one_of"
        assert len(definition["variants"]) == count

    patch_variants = _descriptor(
        data, PATCH_OPERATION_SCHEMA)["definition"]["variants"]
    assert {item["schema_ref"] for item in patch_variants} == {
        MODULE_PUT_SCHEMA,
        ROOT_PUT_SCHEMA,
        EXCEPTION_PUT_SCHEMA,
        EXCEPTION_REMOVE_SCHEMA,
    }
    module_fields = _descriptor(
        data, ModuleV0.SCHEMA)["definition"]["fields"]
    assert set(module_fields) == {
        "generator_calls", "module_id", "parameters", "schema", "slots"}
    assert "metadata" not in module_fields

    generator_definition = _descriptor(
        data, GeneratorCallV0.SCHEMA)["definition"]
    limitation = " ".join(generator_definition["invariants"])
    assert "no generator catalog" in limitation
    assert "no arbitrary generator synthesis" in limitation
    payload = canonical_bytes(data)
    assert b"module.remove" not in payload
    assert b"package.pin" not in payload


def test_registry_structurally_closes_result_receipt_and_response_variants() -> None:
    data = CAPABILITY_REGISTRY.to_data()
    read_coverage = {
        "module-index": _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "exception-index": _K_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "module-absent": _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
        "exception-absent": _K_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
    }
    wire_read_coverage = {
        "module-index": _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "exception-index": _WIRE_COMPLETE_EQUAL_COVERAGE_SCHEMA,
        "module-absent": _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
        "exception-absent": _WIRE_COMPLETE_ONE_ZERO_COVERAGE_SCHEMA,
    }
    for name in _READ_RESULT_VARIANT_NAMES:
        expected_coverage = read_coverage.get(
            name, _K_COMPLETE_ONE_COVERAGE_SCHEMA)
        result = _descriptor(
            data, _READ_RESULT_VARIANT_SCHEMAS[name])["definition"]["fields"]
        receipt = _descriptor(
            data,
            _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name],
        )["definition"]["fields"]
        wire = _descriptor(
            data, _WIRE_READ_OK_VARIANT_SCHEMAS[name])["definition"]["fields"]
        assert result["coverage"]["schema_ref"] == expected_coverage
        assert result["receipt"]["schema_ref"] == (
            _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name])
        assert receipt["coverage"]["schema_ref"] == expected_coverage
        assert wire["coverage"]["schema_ref"] == wire_read_coverage.get(
            name, _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA)
        assert wire["result"]["schema_ref"] == (
            _READ_RESULT_VARIANT_SCHEMAS[name])
        assert wire["read_receipt"]["schema_ref"] == (
            _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name])

    query_coverage = {
        "origin-complete": _K_COVERAGE_VARIANT_SCHEMAS["COMPLETE"],
        "origin-partial": _K_COVERAGE_VARIANT_SCHEMAS["PARTIAL"],
    }
    wire_query_coverage = {
        "origin-complete": _WIRE_COVERAGE_VARIANT_SCHEMAS["COMPLETE"],
        "origin-partial": _WIRE_COVERAGE_VARIANT_SCHEMAS["PARTIAL"],
    }
    for name in _QUERY_RESULT_VARIANT_NAMES:
        expected_coverage = query_coverage.get(
            name, _K_COMPLETE_ONE_COVERAGE_SCHEMA)
        result = _descriptor(
            data, _QUERY_RESULT_VARIANT_SCHEMAS[name])["definition"]["fields"]
        receipt = _descriptor(
            data,
            _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name],
        )["definition"]["fields"]
        wire = _descriptor(
            data, _WIRE_QUERY_OK_VARIANT_SCHEMAS[name])["definition"]["fields"]
        assert result["coverage"]["schema_ref"] == expected_coverage
        assert result["receipt"]["schema_ref"] == (
            _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name])
        assert receipt["coverage"]["schema_ref"] == expected_coverage
        assert wire["coverage"]["schema_ref"] == wire_query_coverage.get(
            name, _WIRE_COMPLETE_ONE_COVERAGE_SCHEMA)
        assert wire["result"]["schema_ref"] == (
            _QUERY_RESULT_VARIANT_SCHEMAS[name])
        assert wire["read_receipt"]["schema_ref"] == (
            _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name])

    project_receipt = _descriptor(
        data, _READ_RECEIPT_VARIANT_SCHEMAS["PROJECT_READ"])["definition"]
    query_receipt = _descriptor(
        data, _READ_RECEIPT_VARIANT_SCHEMAS["MODEL_QUERY"])["definition"]
    assert tuple(item["schema_ref"] for item in project_receipt["variants"]) == (
        tuple(
            _READ_RESULT_RECEIPT_VARIANT_SCHEMAS[name]
            for name in _READ_RESULT_VARIANT_NAMES
        )
    )
    assert tuple(item["schema_ref"] for item in query_receipt["variants"]) == (
        tuple(
            _QUERY_RESULT_RECEIPT_VARIANT_SCHEMAS[name]
            for name in _QUERY_RESULT_VARIANT_NAMES
        )
    )


def test_registry_structurally_closes_conflict_and_unavailable_responses() -> None:
    data = CAPABILITY_REGISTRY.to_data()
    bounded_generic_error_schemas = (
        _WIRE_ERROR_VARIANT_SCHEMAS["project-state-conflict"],
        _WIRE_ERROR_VARIANT_SCHEMAS["patch-id-contradiction"],
        _WIRE_ERROR_VARIANT_SCHEMAS["available-refusal"],
    )
    for schema_id in bounded_generic_error_schemas:
        invariants = _descriptor(data, schema_id)["definition"]["invariants"]
        assert "details are at most 65,536 canonical bytes" in invariants

    project_conflict = _descriptor(
        data,
        _WIRE_RESPONSE_VARIANT_SCHEMAS["project-state-conflict"],
    )["definition"]["fields"]
    assert project_conflict["tool"] == {
        "kind": "enum",
        "required": True,
        "values": ("model.query", "project.read", "source.patch"),
    }
    assert project_conflict["error"]["schema_ref"] == (
        _WIRE_ERROR_VARIANT_SCHEMAS["project-state-conflict"])

    patch_conflict = _descriptor(
        data,
        _WIRE_RESPONSE_VARIANT_SCHEMAS["patch-id-contradiction"],
    )["definition"]["fields"]
    assert patch_conflict["tool"]["value"] == "source.patch"
    assert patch_conflict["error"]["schema_ref"] == (
        _WIRE_ERROR_VARIANT_SCHEMAS["patch-id-contradiction"])

    for tool, schema_id in _WIRE_UNAVAILABLE_REFUSAL_VARIANT_SCHEMAS.items():
        fields = _descriptor(data, schema_id)["definition"]["fields"]
        assert fields["tool"]["value"] == tool
        assert fields["error"]["schema_ref"] == (
            _WIRE_UNAVAILABLE_ERROR_SCHEMAS[tool])


@pytest.mark.parametrize(
    "mutation",
    [
        "invented_definition",
        "ref_outside_census",
        "removed_descriptor",
        "added_descriptor",
        "tool_pointer",
    ],
)
def test_registry_rejects_rehashed_self_consistent_nonpackaged_values(
    mutation,
) -> None:
    data = json.loads(canonical_bytes(CAPABILITY_REGISTRY.to_data()))
    if mutation == "invented_definition":
        descriptor = _descriptor(data, GeneratorCallV0.SCHEMA)
        descriptor["definition"]["invariants"].append(
            "invented but canonically self-consistent claim")
        _recompute_descriptor(descriptor)
    elif mutation == "ref_outside_census":
        descriptor = _descriptor(data, SOURCE_PATCH_COMMAND_SCHEMA)
        descriptor["definition"]["fields"]["operations"]["items"][
            "schema_ref"
        ] = "kir-ai-invented-patch-operation/0"
        _recompute_descriptor(descriptor)
    elif mutation == "removed_descriptor":
        removed = _descriptor(data, GeneratorCallV0.SCHEMA)
        data["schemas"].remove(removed)
    elif mutation == "added_descriptor":
        descriptor = json.loads(canonical_bytes(
            _descriptor(data, GeneratorCallV0.SCHEMA)))
        descriptor["schema_id"] = "kir-ai-invented-closed-shape/0"
        descriptor["definition"]["shape_id"] = descriptor["schema_id"]
        descriptor["uri"] = (
            "urn:kir:ai-project-wire:schema:"
            "kir-ai-invented-closed-shape:0"
        )
        _recompute_descriptor(descriptor)
        data["schemas"].append(descriptor)
        data["schemas"].sort(key=lambda item: item["schema_id"])
    else:
        available = next(
            item for item in data["tools"]
            if item["name"] == "project.read")
        replacement = next(
            item for item in data["tools"]
            if item["name"] == "model.query")
        available["arguments_schema"] = replacement["arguments_schema"]
    _recompute_registry(data)

    with pytest.raises(WireContractError):
        admit_capability_registry(data)


@pytest.mark.parametrize("mutation", ["registry_extra", "child_digest", "tool_matrix"])
def test_registry_mutation_corpus_is_refused(mutation: str) -> None:
    data = json.loads(canonical_bytes(CAPABILITY_REGISTRY.to_data()))
    if mutation == "registry_extra":
        data = dict(data.items())
        data["extra"] = True
    elif mutation == "child_digest":
        data["schemas"][0]["digest"] = "sha256:" + "0" * 64
    else:
        data["tools"][1]["availability"] = "UNAVAILABLE"
        data["tools"][1]["reason_code"] = NOT_AVAILABLE_IN_PROJECT_V0
        data["tools"][1]["result_schema"] = None

    with pytest.raises(WireContractError):
        admit_capability_registry(data)
