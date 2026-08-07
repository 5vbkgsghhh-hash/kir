from __future__ import annotations

from dataclasses import replace

import pytest

from kukai.ai_protocol.contracts import (
    CAPABILITIES_ARGUMENTS_SCHEMA,
    CAPABILITIES_RESULT_SCHEMA,
    CAPABILITIES_TOOL,
    DECLARED_TOOL_NAMES,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
)
from kukai.ai_protocol.errors import ProtocolContractError
from kukai.ai_protocol.registry import (
    CAPABILITY_REGISTRY,
    NOT_AVAILABLE_IN_AP01,
    PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
    CapabilityRegistryV0,
    FeatureCapabilityV0,
    SchemaDescriptorV0,
    admit_capability_registry,
)
from kukai.design_source.canonical import (
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
    thaw,
)


def _plain_registry() -> dict:
    return thaw(CAPABILITY_REGISTRY.to_data())


def _admit_plain(value) -> CapabilityRegistryV0:
    return admit_capability_registry(strict_json_loads(canonical_bytes(value)))


def _schema(data: dict, schema_id: str) -> dict:
    return next(item for item in data["schemas"] if item["schema_id"] == schema_id)


def test_registry_is_exact_closed_and_only_discovery_is_available() -> None:
    registry = CAPABILITY_REGISTRY
    available = tuple(
        item.name for item in registry.tools if item.availability == "AVAILABLE")

    assert tuple(item.name for item in registry.tools) == DECLARED_TOOL_NAMES
    assert available == (CAPABILITIES_TOOL,)
    assert registry.to_data()["schema"] == CAPABILITIES_RESULT_SCHEMA
    assert len(registry.schemas) == 10
    assert len(registry.tools) == 9
    assert len(registry.features) == 9
    registry.verify_integrity()


def test_discovery_binds_distinct_envelope_and_payload_schemas() -> None:
    discovery = CAPABILITY_REGISTRY.tool_for_name(CAPABILITIES_TOOL)
    assert discovery is not None
    assert discovery.request_envelope_schema is CAPABILITY_REGISTRY.schema_for_id(
        REQUEST_SCHEMA)
    assert discovery.arguments_schema is CAPABILITY_REGISTRY.schema_for_id(
        CAPABILITIES_ARGUMENTS_SCHEMA)
    assert discovery.response_envelope_schema is CAPABILITY_REGISTRY.schema_for_id(
        RESPONSE_SCHEMA)
    assert discovery.result_schema is CAPABILITY_REGISTRY.schema_for_id(
        CAPABILITIES_RESULT_SCHEMA)
    assert len({
        discovery.request_envelope_schema.schema_digest,
        discovery.arguments_schema.schema_digest,
        discovery.response_envelope_schema.schema_digest,
        discovery.result_schema.schema_digest,
    }) == 4


def test_unavailable_capabilities_advertise_no_schema_or_side_effect() -> None:
    for capability in CAPABILITY_REGISTRY.tools:
        data = capability.to_data()
        assert data["side_effects"] == "NONE"
        if capability.name == CAPABILITIES_TOOL:
            continue
        assert capability.availability == "UNAVAILABLE"
        assert data["request_envelope_schema"] is None
        assert data["arguments_schema"] is None
        assert data["response_envelope_schema"] is None
        assert data["result_schema"] is None

    publish = CAPABILITY_REGISTRY.tool_for_name("publish.prepare")
    assert publish is not None
    assert publish.reason_code == PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
    assert all(
        item.reason_code == NOT_AVAILABLE_IN_AP01
        for item in CAPABILITY_REGISTRY.tools
        if item.availability == "UNAVAILABLE" and item.name != "publish.prepare"
    )


def test_scene_is_an_unavailable_feature_not_an_invented_tool() -> None:
    features = {item.name: item for item in CAPABILITY_REGISTRY.features}
    assert features["scene"].availability == "UNAVAILABLE"
    assert features["scene"].reason_code == NOT_AVAILABLE_IN_AP01
    assert "scene.read" not in DECLARED_TOOL_NAMES

    payload = canonical_bytes(CAPABILITY_REGISTRY.to_data())
    assert b"scene.read" not in payload
    assert b"package.pin" not in payload
    assert b"module.remove" not in payload


def test_schema_descriptors_state_executable_limits_truthfully() -> None:
    request = CAPABILITY_REGISTRY.schema_for_id(REQUEST_SCHEMA).definition
    response = CAPABILITY_REGISTRY.schema_for_id(RESPONSE_SCHEMA).definition
    coverage = CAPABILITY_REGISTRY.schema_for_id(
        "kir-ai-coverage/0").definition
    error = CAPABILITY_REGISTRY.schema_for_id("kir-ai-error/0").definition
    receipt = CAPABILITY_REGISTRY.schema_for_id(
        "kir-ai-read-receipt/0").definition
    result = CAPABILITY_REGISTRY.schema_for_id(
        CAPABILITIES_RESULT_SCHEMA).definition

    assert request["unknown_fields"] == "REFUSE"
    assert request["canonical_max_bytes"] == 4_000_000
    assert request["fields"]["request_id"]["max_length"] == 64
    assert request["fields"]["arguments"]["canonical_max_bytes"] == 1_000_000
    assert response["fields"]["request_id"]["max_length"] == 64
    assert response["canonical_max_bytes"] == 4_000_000
    assert response["fields"]["result"]["canonical_max_bytes"] == 2_000_000
    assert coverage["fields"]["requested"]["integer_max"] == 1_000_000_000
    assert coverage["canonical_max_bytes"] == 1_000_000
    assert coverage["fields"]["omitted"]["max_items"] == 4_096
    assert coverage["fields"]["omitted"]["order"] == "lexicographic"
    assert error["fields"]["message"]["min_length"] == 1
    assert error["fields"]["details"]["canonical_max_bytes"] == 65_536
    assert receipt["fields"]["result_digests"]["max_items"] == 4_096
    assert receipt["fields"]["result_digests"]["order"] == "lexicographic"
    assert receipt["fields"]["continuation"]["max_length"] == 1_024
    assert result["fields"]["schemas"]["exact_items"] == 10
    assert result["fields"]["tools"]["exact_items"] == 9
    assert result["fields"]["features"]["exact_items"] == 9


def test_exact_registry_result_round_trips_through_wire_vocabulary() -> None:
    admitted = _admit_plain(_plain_registry())

    assert admitted.registry_digest == CAPABILITY_REGISTRY.registry_digest
    assert canonical_bytes(admitted.to_data()) == canonical_bytes(
        CAPABILITY_REGISTRY.to_data())


def test_registry_admission_requires_frozen_decoded_object() -> None:
    with pytest.raises(ProtocolContractError, match="exact object"):
        admit_capability_registry(_plain_registry())


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update({"extra": True}),
        lambda data: data.pop("milestone"),
        lambda data: data.update({"schema": "wrong"}),
        lambda data: data["canonical_profile"].update({"extra": True}),
        lambda data: data["canonical_profile"].update({"max_depth": True}),
        lambda data: data["schemas"].reverse(),
        lambda data: data["tools"].reverse(),
        lambda data: data["features"].reverse(),
        lambda data: data["tools"][0].update({"extra": True}),
        lambda data: data["tools"][0].update({"side_effects": "WRITE"}),
        lambda data: data["features"][0].update({"availability": "AVAILABLE"}),
        lambda data: data.update({"registry_digest": "sha256:" + "0" * 64}),
    ],
)
def test_registry_admission_refuses_shape_matrix(mutator) -> None:
    data = _plain_registry()
    mutator(data)

    with pytest.raises(ProtocolContractError):
        _admit_plain(data)


def test_registry_admission_recomputes_every_schema_digest() -> None:
    data = _plain_registry()
    data["schemas"][0]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(ProtocolContractError, match="digest"):
        _admit_plain(data)


def test_registry_admission_resolves_schema_pointers_by_uri_and_digest() -> None:
    data = _plain_registry()
    discovery = next(
        item for item in data["tools"] if item["name"] == CAPABILITIES_TOOL)
    discovery["arguments_schema"]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(ProtocolContractError, match="resolve"):
        _admit_plain(data)


def test_fully_rehashed_forged_schema_is_still_outside_closed_registry() -> None:
    data = _plain_registry()
    descriptor = _schema(data, CAPABILITIES_ARGUMENTS_SCHEMA)
    old_digest = descriptor["digest"]
    descriptor["definition"]["invented_rule"] = "ALLOW"
    descriptor["digest"] = canonical_digest(
        "kir.ai-protocol-schema.v0",
        {
            "schema_id": descriptor["schema_id"],
            "uri": descriptor["uri"],
            "definition": descriptor["definition"],
        },
    )
    for tool in data["tools"]:
        for field in (
            "request_envelope_schema",
            "arguments_schema",
            "response_envelope_schema",
            "result_schema",
        ):
            pointer = tool[field]
            if pointer is not None and pointer["digest"] == old_digest:
                pointer["digest"] = descriptor["digest"]
    body = {key: value for key, value in data.items() if key != "registry_digest"}
    data["registry_digest"] = canonical_digest(
        "kir.ai-capability-registry.v0", body)

    with pytest.raises(ProtocolContractError, match="definition is not exact"):
        _admit_plain(data)


def test_registry_constructor_refuses_feature_matrix_drift() -> None:
    altered = replace(
        CAPABILITY_REGISTRY.features[0],
        availability="AVAILABLE",
        reason_code=None,
    )
    with pytest.raises(ProtocolContractError, match="feature matrix"):
        CapabilityRegistryV0(
            CAPABILITY_REGISTRY.schemas,
            CAPABILITY_REGISTRY.tools,
            (altered, *CAPABILITY_REGISTRY.features[1:]),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemas", None),
        ("tools", 1),
        ("features", {}),
    ],
)
def test_registry_constructor_normalizes_wrong_container_types(
    field: str,
    value,
) -> None:
    values = {
        "schemas": CAPABILITY_REGISTRY.schemas,
        "tools": CAPABILITY_REGISTRY.tools,
        "features": CAPABILITY_REGISTRY.features,
    }
    values[field] = value

    with pytest.raises(ProtocolContractError, match="exact list or tuple"):
        CapabilityRegistryV0(**values)


def test_reason_code_contract_matches_uppercase_symbol_schema() -> None:
    with pytest.raises(ProtocolContractError, match="uppercase symbol"):
        FeatureCapabilityV0("new_feature", "UNAVAILABLE", "lowercase")


def test_registry_refuses_rehashed_child_digest_subclass_with_lying_equality(
) -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    registry = CAPABILITY_REGISTRY
    descriptor = registry.schemas[0]
    original_schema_digest = descriptor.schema_digest
    original_registry_digest = registry.registry_digest
    object.__setattr__(descriptor, "_schema_digest", LyingDigest(
        "sha256:" + "0" * 64))
    object.__setattr__(
        registry,
        "_registry_digest",
        canonical_digest(
            "kir.ai-capability-registry.v0", registry._body_data()),
    )
    try:
        with pytest.raises(ProtocolContractError, match="exact digest text"):
            descriptor.verify_integrity()
        with pytest.raises(ProtocolContractError, match="exact digest text"):
            registry.verify_integrity()
    finally:
        object.__setattr__(descriptor, "_schema_digest", original_schema_digest)
        object.__setattr__(registry, "_registry_digest", original_registry_digest)


@pytest.mark.parametrize("use_correct_text", [False, True])
def test_registry_refuses_own_digest_subclass_even_when_equality_lies(
    use_correct_text: bool,
) -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    registry = CAPABILITY_REGISTRY
    original = registry.registry_digest
    text = original if use_correct_text else "sha256:" + "0" * 64
    object.__setattr__(registry, "_registry_digest", LyingDigest(text))
    try:
        with pytest.raises(ProtocolContractError, match="exact digest text"):
            registry.verify_integrity()
    finally:
        object.__setattr__(registry, "_registry_digest", original)


def test_registry_refuses_non_text_digest_with_lying_equality() -> None:
    class LyingDigest:
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    registry = CAPABILITY_REGISTRY
    original = registry.registry_digest
    object.__setattr__(registry, "_registry_digest", LyingDigest())
    try:
        with pytest.raises(ProtocolContractError, match="exact digest text"):
            registry.verify_integrity()
    finally:
        object.__setattr__(registry, "_registry_digest", original)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_id", object()),
        ("uri", object()),
        ("definition", {1: "non-text-key"}),
        ("definition", object()),
    ],
)
def test_schema_integrity_verifier_contains_current_representation_failures(
    field: str,
    value,
) -> None:
    descriptor = CAPABILITY_REGISTRY.schemas[0]
    original = getattr(descriptor, field)
    object.__setattr__(descriptor, field, value)
    try:
        with pytest.raises(
            ProtocolContractError,
            match="integrity verification failed safely",
        ):
            descriptor.verify_integrity()
    finally:
        object.__setattr__(descriptor, field, original)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemas", None),
        ("schemas", (object(),)),
        ("tools", (object(),)),
        ("features", (object(),)),
    ],
)
def test_registry_integrity_verifier_contains_current_representation_failures(
    field: str,
    value,
) -> None:
    registry = CAPABILITY_REGISTRY
    original = getattr(registry, field)
    object.__setattr__(registry, field, value)
    try:
        with pytest.raises(ProtocolContractError):
            registry.verify_integrity()
    finally:
        object.__setattr__(registry, field, original)


def test_registry_integrity_verifier_contains_invalid_child_definition() -> None:
    registry = CAPABILITY_REGISTRY
    descriptor = registry.schemas[0]
    original = descriptor.definition
    object.__setattr__(descriptor, "definition", {1: "non-text-key"})
    try:
        with pytest.raises(
            ProtocolContractError,
            match="integrity verification failed safely",
        ):
            registry.verify_integrity()
    finally:
        object.__setattr__(descriptor, "definition", original)


def test_integrity_verifiers_do_not_mask_protocol_contract_errors() -> None:
    schema_error = ProtocolContractError("schema sentinel")
    registry_error = ProtocolContractError("registry sentinel")
    descriptor = CAPABILITY_REGISTRY.schemas[0]
    registry = CAPABILITY_REGISTRY

    def schema_failure(*_args, **_kwargs):
        raise schema_error

    class BrokenSchemas:
        def __iter__(self):
            raise registry_error

    with pytest.raises(ProtocolContractError) as schema_info:
        descriptor.verify_integrity(_canonical_hasher=schema_failure)
    assert schema_info.value is schema_error

    original = registry.schemas
    object.__setattr__(registry, "schemas", BrokenSchemas())
    try:
        with pytest.raises(ProtocolContractError) as registry_info:
            registry.verify_integrity()
        assert registry_info.value is registry_error
    finally:
        object.__setattr__(registry, "schemas", original)


@pytest.mark.parametrize(
    "value",
    [object.__new__(SchemaDescriptorV0), object.__new__(CapabilityRegistryV0)],
)
def test_uninitialized_integrity_verifiers_fail_with_protocol_error(value) -> None:
    with pytest.raises(
        ProtocolContractError,
        match="integrity verification failed safely",
    ):
        value.verify_integrity()
