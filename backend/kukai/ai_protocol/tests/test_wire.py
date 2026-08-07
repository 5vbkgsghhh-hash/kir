from __future__ import annotations

from collections.abc import Mapping
import copy

import pytest

from kukai.ai_protocol import wire
from kukai.ai_protocol.contracts import (
    CAPABILITIES_TOOL,
    DECLARED_TOOL_NAMES,
    PROTOCOL_VERSION,
    CoverageV0,
    ProtocolErrorV0,
    ReadReceiptV0,
    ToolRequestV0,
    ToolResponseV0,
)
from kukai.ai_protocol.errors import (
    ProtocolContractError,
    WireDecodeError,
    WireShapeError,
)
from kukai.ai_protocol.registry import (
    CAPABILITY_REGISTRY,
    PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
)
from kukai.design_source.canonical import (
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    freeze,
    thaw,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _request_data(
    *,
    request_id: object = "request_1",
    tool: object = CAPABILITIES_TOOL,
    arguments: object = None,
) -> dict:
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "tool": tool,
        "arguments": {} if arguments is None else arguments,
    }


def _request_wire(**changes) -> bytes:
    data = _request_data()
    data.update(changes)
    return canonical_bytes(data)


def _capability_response() -> ToolResponseV0:
    return wire.handle_request(wire.decode_request(_request_wire()))


def _capability_response_data() -> dict:
    return thaw(_capability_response().to_data())


def _error_data() -> dict:
    return thaw(ProtocolErrorV0("BROKEN", "Operation failed.").to_data())


def _receipt(
    *,
    request_id: str = "request_1",
    tool: str = CAPABILITIES_TOOL,
    coverage: CoverageV0 | None = None,
    registry_digest: str | None = None,
) -> ReadReceiptV0:
    return ReadReceiptV0(
        request_id=request_id,
        tool=tool,
        project_id="project_1",
        revision_digest=DIGEST_A,
        request_digest=DIGEST_B,
        result_digests=(DIGEST_A,),
        coverage=CoverageV0.complete() if coverage is None else coverage,
        schema_registry_digest=(
            CAPABILITY_REGISTRY.registry_digest
            if registry_digest is None
            else registry_digest
        ),
    )


def test_capability_request_response_round_trip_is_byte_stable() -> None:
    request = wire.decode_request(_request_wire())
    first = wire.handle_request(request)
    first_bytes = wire.encode_response(first)
    admitted = wire.decode_response(first_bytes)
    second_bytes = wire.handle_wire_request(_request_wire())

    assert request.tool == CAPABILITIES_TOOL
    assert first.status == "OK"
    assert admitted == first
    assert first_bytes == second_bytes
    assert admitted.result["registry_digest"] == CAPABILITY_REGISTRY.registry_digest


def test_every_declared_tool_has_deterministic_empty_probe_behavior() -> None:
    for tool_name in DECLARED_TOOL_NAMES:
        request = wire.decode_request(_request_wire(tool=tool_name))
        response = wire.handle_request(request)
        admitted = wire.decode_response(wire.encode_response(response))

        assert admitted.request_id == "request_1"
        assert admitted.tool == tool_name
        if tool_name == CAPABILITIES_TOOL:
            assert admitted.status == "OK"
            assert admitted.coverage == CoverageV0.complete()
        else:
            assert admitted.status == "REFUSED"
            assert admitted.error.code == "TOOL_UNAVAILABLE"
            assert admitted.error.details["reason_code"] == (
                PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
                if tool_name == "publish.prepare"
                else "NOT_AVAILABLE_IN_AP01"
            )


def test_wire_identifier_accepts_64_and_refuses_65_characters() -> None:
    admitted = "A" + "a" * 63
    refused = admitted + "a"

    assert wire.decode_request(_request_wire(request_id=admitted)).request_id == admitted
    with pytest.raises(WireShapeError) as error:
        wire.decode_request(_request_wire(request_id=refused))
    assert error.value.code == "WIRE_REQUEST_ID_INVALID"


@pytest.mark.parametrize(
    "blob",
    [
        None,
        1,
        bytearray(b"{}"),
        b"\xff",
        b"\xff\xfe{\x00}\x00",
        b"\xef\xbb\xbf{}",
        "\ud800",
        "",
        "{",
        "{} trailing",
        "{}{}",
        '{"x":1,"x":2}',
        '{"\u00e9":1,"e\u0301":2}',
        '{"x":1.0}',
        '{"x":1e3}',
        '{"x":NaN}',
        '{"x":Infinity}',
    ],
)
def test_strict_json_negative_corpus(blob) -> None:
    with pytest.raises(WireDecodeError):
        wire.decode_request(blob)


def test_strict_json_refuses_oversize_and_excessive_depth() -> None:
    with pytest.raises(WireDecodeError, match="byte-size"):
        wire.decode_request(" " * 4_000_001)
    with pytest.raises(WireDecodeError, match="depth"):
        wire.decode_request("[" * 129 + "]" * 129)


@pytest.mark.parametrize("blob", [b"null", b"[]", b'"text"', b"1", b"true"])
def test_request_requires_top_level_object(blob: bytes) -> None:
    with pytest.raises(WireShapeError) as error:
        wire.decode_request(blob)
    assert error.value.code == "WIRE_TOP_LEVEL_NOT_OBJECT"


def test_request_requires_exact_outer_fields_before_authority_scan() -> None:
    data = _request_data()
    data["authority"] = "model"

    with pytest.raises(WireShapeError) as error:
        wire.decode_request(canonical_bytes(data))
    assert error.value.code == "WIRE_FIELDS_MISMATCH"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("protocol"),
        lambda data: data.update({"extra": True}),
        lambda data: data.update({"protocol": "kir-ai/1"}),
        lambda data: data.update({"request_id": 1}),
        lambda data: data.update({"tool": 1}),
        lambda data: data.update({"arguments": None}),
        lambda data: data.update({"arguments": []}),
        lambda data: data.update({"arguments": {"query": "x"}}),
    ],
)
def test_request_shape_negative_matrix(mutation) -> None:
    data = _request_data()
    mutation(data)

    with pytest.raises(WireShapeError):
        wire.decode_request(canonical_bytes(data))


def test_authority_refusal_precedes_unknown_tool_refusal() -> None:
    blob = _request_wire(
        tool="unknown.tool",
        arguments={"nested": {"approval-id": "model"}},
    )

    with pytest.raises(WireShapeError) as error:
        wire.decode_request(blob)
    assert error.value.code == "MODEL_AUTHORITY_FIELD_FORBIDDEN"


def test_unknown_tool_with_empty_arguments_is_explicitly_refused() -> None:
    with pytest.raises(WireShapeError) as error:
        wire.decode_request(_request_wire(tool="unknown.tool"))
    assert error.value.code == "UNKNOWN_TOOL"


def test_capabilities_ok_requires_exact_registry_result() -> None:
    data = _capability_response_data()
    data["result"] = {"x": 1}

    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(data))
    assert error.value.code == "CAPABILITY_RESULT_INVALID"


def test_capabilities_result_recomputes_child_digest() -> None:
    data = _capability_response_data()
    data["result"]["schemas"][0]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(data))
    assert error.value.code == "CAPABILITY_RESULT_INVALID"


def test_encoder_refuses_every_capability_digest_with_lying_equality() -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    original = thaw(_capability_response().result)
    paths = []

    def visit(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, (*path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*path, index))
        elif isinstance(value, str) and value.startswith("sha256:"):
            paths.append(path)

    visit(original)
    assert len(paths) == 15

    for path in paths:
        result = copy.deepcopy(original)
        parent = result
        for part in path[:-1]:
            parent = parent[part]
        parent[path[-1]] = LyingDigest("sha256:" + "0" * 64)
        response = _capability_response()
        object.__setattr__(response, "result", result)
        object.__setattr__(
            response,
            "_response_digest",
            canonical_digest("kir.ai-tool-response.v0", response.to_data()),
        )

        with pytest.raises(ProtocolContractError, match="own decoder"):
            wire.encode_response(response)


def test_unavailable_tool_response_cannot_claim_ok() -> None:
    data = _capability_response_data()
    data.update({"tool": "project.read", "result": {}})

    with pytest.raises(WireShapeError, match="unavailable"):
        wire.decode_response(canonical_bytes(data))


def test_all_unavailable_tools_require_their_exact_reason() -> None:
    unavailable = tuple(
        name for name in DECLARED_TOOL_NAMES if name != CAPABILITIES_TOOL)
    for tool_name in unavailable:
        response = wire.handle_request(
            wire.decode_request(_request_wire(tool=tool_name)))
        data = thaw(response.to_data())
        data["coverage"]["failed"] = ["FORGED_OTHER_REASON"]

        with pytest.raises(WireShapeError) as error:
            wire.decode_response(canonical_bytes(data))
        assert error.value.code == "UNAVAILABLE_REFUSAL_MISMATCH"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update({"status": "FAILED"}),
        lambda data: data["coverage"].update(
            {"failed": ["FORGED_OTHER_REASON"]}),
        lambda data: data["error"].update({"code": "SOMETHING_ELSE"}),
        lambda data: data["error"].update({"message": "Forged."}),
        lambda data: data["error"].update({"retryable": True}),
        lambda data: data["error"].update(
            {"details": {"reason_code": "FORGED_OTHER_REASON"}}),
        lambda data: data.update({"result": {}}),
        lambda data: data.update({"read_receipt": {}}),
    ],
)
def test_publish_refusal_body_is_fully_sealed(mutator) -> None:
    response = wire.handle_request(
        wire.decode_request(_request_wire(tool="publish.prepare")))
    data = thaw(response.to_data())
    mutator(data)

    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(data))
    assert error.value.code == "UNAVAILABLE_REFUSAL_MISMATCH"


@pytest.mark.parametrize(
    ("source_tool", "substituted_tool"),
    [
        ("build.run", "publish.prepare"),
        ("publish.prepare", "project.read"),
    ],
)
def test_unavailable_refusals_cannot_be_substituted_across_tools(
    source_tool: str,
    substituted_tool: str,
) -> None:
    response = wire.handle_request(
        wire.decode_request(_request_wire(tool=source_tool)))
    data = thaw(response.to_data())
    data["tool"] = substituted_tool

    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(data))
    assert error.value.code == "UNAVAILABLE_REFUSAL_MISMATCH"


@pytest.mark.parametrize("coverage", [CoverageV0.complete(), CoverageV0.refused("x")])
def test_wire_failed_excludes_complete_and_refused_coverage(
    coverage: CoverageV0,
) -> None:
    data = _capability_response_data()
    data.update({
        "status": "FAILED",
        "coverage": thaw(coverage.to_data()),
        "result": None,
        "error": _error_data(),
    })

    with pytest.raises(WireShapeError, match="FAILED requires"):
        wire.decode_response(canonical_bytes(data))


def test_wire_admits_failed_with_not_evaluated_coverage() -> None:
    data = _capability_response_data()
    data.update({
        "status": "FAILED",
        "coverage": thaw(CoverageV0("NOT_EVALUATED", 1, 0).to_data()),
        "result": None,
        "error": _error_data(),
    })

    admitted = wire.decode_response(canonical_bytes(data))

    assert admitted.status == "FAILED"
    assert admitted.coverage.state == "NOT_EVALUATED"


def test_capability_ok_refuses_non_singleton_complete_coverage() -> None:
    data = _capability_response_data()
    data["coverage"] = thaw(CoverageV0.complete(2).to_data())

    with pytest.raises(WireShapeError, match="COMPLETE 1-of-1"):
        wire.decode_response(canonical_bytes(data))


def test_response_refuses_bool_counter_and_nested_extra_field() -> None:
    bool_count = _capability_response_data()
    bool_count["coverage"]["requested"]["items"] = True
    with pytest.raises(WireShapeError):
        wire.decode_response(canonical_bytes(bool_count))

    extra = _capability_response_data()
    extra["coverage"]["requested"]["extra"] = 0
    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(extra))
    assert error.value.code == "WIRE_FIELDS_MISMATCH"


def test_wire_refuses_noncanonical_semantic_array_order() -> None:
    coverage = _capability_response_data()
    coverage["coverage"] = thaw(
        CoverageV0("PARTIAL", 3, 1, omitted=("a", "z")).to_data())
    coverage["coverage"]["omitted"].reverse()
    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(coverage))
    assert error.value.code == "WIRE_CANONICAL_VALUE_MISMATCH"

    receipt = _capability_response_data()
    admitted_receipt = ReadReceiptV0(
        request_id="request_1",
        tool=CAPABILITIES_TOOL,
        project_id="project_1",
        revision_digest=DIGEST_A,
        request_digest=DIGEST_B,
        result_digests=(DIGEST_A, DIGEST_B),
        coverage=CoverageV0.complete(),
        schema_registry_digest=CAPABILITY_REGISTRY.registry_digest,
    )
    receipt["read_receipt"] = thaw(admitted_receipt.to_data())
    receipt["read_receipt"]["result_digests"].reverse()
    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(receipt))
    assert error.value.code == "READ_RECEIPT_DIGEST_MISMATCH"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("status"),
        lambda data: data.update({"extra": True}),
        lambda data: data.update({"protocol": "kir-ai/1"}),
        lambda data: data.update({"request_id": 1}),
        lambda data: data.update({"tool": "unknown.tool"}),
        lambda data: data.update({"status": "UNKNOWN"}),
        lambda data: data.update({"result": []}),
    ],
)
def test_response_shape_negative_matrix(mutation) -> None:
    data = _capability_response_data()
    mutation(data)

    with pytest.raises(WireShapeError):
        wire.decode_response(canonical_bytes(data))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda error: error.pop("details"),
        lambda error: error.update({"extra": True}),
        lambda error: error.update({"schema": "wrong"}),
        lambda error: error.update({"code": "lowercase"}),
        lambda error: error.update({"retryable": 0}),
        lambda error: error.update({"details": []}),
    ],
)
def test_error_shape_negative_matrix(mutation) -> None:
    data = _capability_response_data()
    error = _error_data()
    mutation(error)
    data.update({
        "status": "FAILED",
        "coverage": thaw(CoverageV0("NOT_EVALUATED", 1, 0).to_data()),
        "result": None,
        "error": error,
    })

    with pytest.raises(WireShapeError):
        wire.decode_response(canonical_bytes(data))


def test_read_receipt_digest_registry_and_envelope_binding_are_verified() -> None:
    invalid_digest = _capability_response_data()
    invalid_digest["read_receipt"] = thaw(_receipt().to_data())
    invalid_digest["read_receipt"]["receipt_digest"] = "sha256:" + "0" * 64
    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(invalid_digest))
    assert error.value.code == "READ_RECEIPT_DIGEST_MISMATCH"

    wrong_registry = _capability_response_data()
    wrong_registry["read_receipt"] = thaw(_receipt(
        registry_digest="sha256:" + "0" * 64).to_data())
    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(wrong_registry))
    assert error.value.code == "READ_RECEIPT_REGISTRY_MISMATCH"

    wrong_request = _capability_response_data()
    wrong_request["read_receipt"] = thaw(_receipt(request_id="other").to_data())
    with pytest.raises(WireShapeError, match="request_id"):
        wire.decode_response(canonical_bytes(wrong_request))


def test_capability_discovery_cannot_masquerade_as_project_read() -> None:
    data = _capability_response_data()
    data["read_receipt"] = thaw(_receipt().to_data())

    with pytest.raises(WireShapeError) as error:
        wire.decode_response(canonical_bytes(data))
    assert error.value.code == "CAPABILITY_READ_RECEIPT_FORBIDDEN"


def test_public_decoders_and_handler_ignore_registry_module_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_wire = _request_wire()
    before_request = wire.decode_request(request_wire)
    before_response = wire.handle_wire_request(request_wire)
    before_admitted_response = wire.decode_response(before_response)
    fake = object()

    monkeypatch.setattr(
        wire, "_PACKAGED_CAPABILITY_REGISTRY", fake, raising=False)
    monkeypatch.setattr(wire, "_REGISTRY_DATA_SNAPSHOT", fake, raising=False)
    monkeypatch.setattr(wire, "_CAPABILITY_MAP_SNAPSHOT", fake, raising=False)
    monkeypatch.setattr(wire, "_decode_request_core", fake)
    monkeypatch.setattr(wire, "_decode_response_core", fake)
    monkeypatch.setattr(wire, "_parse_coverage", fake)
    monkeypatch.setattr(wire, "_parse_error", fake)
    monkeypatch.setattr(wire, "_parse_read_receipt", fake)
    monkeypatch.setattr(wire, "_contract", fake)
    monkeypatch.setattr(wire, "strict_json_loads", fake)
    monkeypatch.setattr(wire, "canonical_bytes", fake)
    monkeypatch.setattr(wire, "ToolRequestV0", fake)
    monkeypatch.setattr(wire, "ToolResponseV0", fake)
    monkeypatch.setattr(wire, "CoverageV0", fake)
    monkeypatch.setattr(wire, "ProtocolErrorV0", fake)
    import kukai.ai_protocol.registry as registry_module
    monkeypatch.setattr(registry_module, "CAPABILITY_REGISTRY", fake)

    assert wire.decode_request(request_wire) == before_request
    assert wire.decode_response(before_response) == before_admitted_response
    assert wire.handle_wire_request(request_wire) == before_response


def test_live_registry_object_and_digest_helper_cannot_change_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.registry as registry_module

    registry = registry_module.CAPABILITY_REGISTRY
    publish = registry.tool_for_name("publish.prepare")
    assert publish is not None
    original_reason = publish.reason_code
    original_hasher = registry_module.canonical_digest

    def forged_hasher(domain, value):
        if domain == "kir.ai-capability-registry.v0":
            return registry.registry_digest
        return original_hasher(domain, value)

    monkeypatch.setattr(registry_module, "canonical_digest", forged_hasher)
    object.__setattr__(publish, "reason_code", "FORGED_RUNTIME_REASON")
    try:
        with pytest.raises(ProtocolContractError):
            registry.verify_integrity()
        request = wire.decode_request(_request_wire(tool="publish.prepare"))
        response = wire.handle_request(request)
        payload = wire.encode_response(response)

        assert response.coverage.failed == (
            PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,)
        assert response.error.details == {
            "reason_code": PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
        }
        assert wire.decode_response(payload) == response
    finally:
        object.__setattr__(publish, "reason_code", original_reason)


def test_programmatic_handler_and_encoder_require_exact_contract_types() -> None:
    with pytest.raises(ProtocolContractError):
        wire.handle_request(object())  # type: ignore[arg-type]
    with pytest.raises(ProtocolContractError):
        wire.encode_response(object())  # type: ignore[arg-type]


def test_handler_refuses_request_value_mutated_after_construction() -> None:
    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    object.__setattr__(request, "request_id", "request_2")

    with pytest.raises(ProtocolContractError, match="digest"):
        wire.handle_request(request)


@pytest.mark.parametrize("use_correct_text", [False, True])
def test_handler_refuses_digest_subclass_even_when_equality_lies(
    use_correct_text: bool,
) -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    text = request.request_digest if use_correct_text else DIGEST_A
    object.__setattr__(request, "_request_digest", LyingDigest(text))

    with pytest.raises(ProtocolContractError, match="exact digest text"):
        wire.handle_request(request)


def test_handler_refuses_non_text_digest_with_lying_equality() -> None:
    class LyingDigest:
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    object.__setattr__(request, "_request_digest", LyingDigest())

    with pytest.raises(ProtocolContractError, match="exact digest text"):
        wire.handle_request(request)


@pytest.mark.parametrize(
    ("field", "value", "recompute_digest"),
    [
        ("arguments", {"authority": "model"}, True),
        ("arguments", {"query": "ignored"}, True),
        ("tool", "unknown.tool", True),
        ("tool", "project.read", False),
        ("request_id", "request_2", False),
        ("_request_digest", DIGEST_A, False),
    ],
)
def test_handler_refuses_invalid_or_stale_current_request_matrix(
    field: str,
    value,
    recompute_digest: bool,
) -> None:
    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    object.__setattr__(
        request,
        field,
        freeze(value) if field == "arguments" else value,
    )
    if recompute_digest:
        object.__setattr__(
            request,
            "_request_digest",
            canonical_digest("kir.ai-tool-request.v0", request.to_data()),
        )

    with pytest.raises(ProtocolContractError):
        wire.handle_request(request)


def test_handler_accepts_fully_valid_current_value_and_redigest() -> None:
    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    second = ToolRequestV0("request_2", "project.read", {})
    object.__setattr__(request, "request_id", second.request_id)
    object.__setattr__(request, "tool", second.tool)
    object.__setattr__(request, "arguments", {})
    object.__setattr__(request, "_request_digest", second.request_digest)

    response = wire.handle_request(request)

    assert response.request_id == "request_2"
    assert response.tool == "project.read"
    assert response.status == "REFUSED"
    assert wire.handle_request(second).status == "REFUSED"


def test_handler_accepts_copy_and_representation_equivalent_scalars() -> None:
    class TextValue(str):
        pass

    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    object.__setattr__(request, "request_id", TextValue("request_1"))
    object.__setattr__(request, "tool", TextValue(CAPABILITIES_TOOL))
    object.__setattr__(request, "arguments", {})

    shallow = wire.handle_request(copy.copy(request))

    assert shallow.status == "OK"
    assert type(shallow.request_id) is str
    assert type(shallow.tool) is str


def test_handler_decides_only_from_the_admitted_request_snapshot() -> None:
    request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})

    class MutatingEmptyArguments(Mapping):
        def __getitem__(self, key):
            raise KeyError(key)

        def __iter__(self):
            object.__setattr__(request, "tool", "project.read")
            return iter(())

        def __len__(self):
            return 0

    object.__setattr__(request, "arguments", MutatingEmptyArguments())

    response = wire.handle_request(request)

    assert request.tool == "project.read"
    assert response.tool == CAPABILITIES_TOOL
    assert response.status == "OK"


def test_returned_response_mutation_cannot_poison_handler_templates() -> None:
    baseline = {
        tool: wire.handle_wire_request(_request_wire(tool=tool))
        for tool in DECLARED_TOOL_NAMES
    }

    for tool in DECLARED_TOOL_NAMES:
        response = wire.handle_request(
            ToolRequestV0("request_1", tool, {}))
        object.__setattr__(response, "request_id", "mutated")
        object.__setattr__(response, "status", "FAILED")
        object.__setattr__(response.coverage, "state", "UNKNOWN")
        object.__setattr__(response.coverage, "requested_items", 99)
        object.__setattr__(response.coverage, "omitted", ["mutated"])
        object.__setattr__(response.coverage, "_coverage_digest", DIGEST_A)
        if response.result is not None:
            nested = response.result["schemas"][0]["definition"]
            object.__setattr__(nested, "_items", (("forged", True),))
            object.__setattr__(
                response.result, "_items", (("schema", "forged"),))
        if response.error is not None:
            object.__setattr__(response.error, "code", "FORGED")
            object.__setattr__(
                response.error.details,
                "_items",
                (("reason_code", "FORGED"),),
            )

    after = {
        tool: wire.handle_wire_request(_request_wire(tool=tool))
        for tool in DECLARED_TOOL_NAMES
    }

    assert after == baseline


def test_capability_results_are_fresh_at_every_decoder_and_handler_layer() -> None:
    payload = wire.handle_wire_request(_request_wire())
    first = wire.decode_response(payload)
    second = wire.decode_response(payload)
    handled = wire.handle_request(ToolRequestV0(
        "request_1", CAPABILITIES_TOOL, {}))

    def frozen_paths(value, path="root"):
        found = {}
        if type(value) is FrozenMap:
            found[path] = value
            for key, item in value.items():
                found.update(frozen_paths(item, f"{path}.{key}"))
        elif type(value) is tuple:
            for index, item in enumerate(value):
                found.update(frozen_paths(item, f"{path}[{index}]"))
        return found

    first_maps = frozen_paths(first.result)
    second_maps = frozen_paths(second.result)
    handled_maps = frozen_paths(handled.result)

    assert first is not second
    assert first.coverage is not second.coverage
    assert first_maps.keys() == second_maps.keys() == handled_maps.keys()
    assert all(
        first_maps[path] is not second_maps[path]
        and first_maps[path] is not handled_maps[path]
        and second_maps[path] is not handled_maps[path]
        for path in first_maps
    )

    object.__setattr__(first.result, "_items", (("schema", "forged"),))
    assert wire.decode_response(payload) == second


def test_handler_refuses_uninitialized_exact_request_safely() -> None:
    request = object.__new__(ToolRequestV0)

    with pytest.raises(ProtocolContractError, match="snapshot failed safely"):
        wire.handle_request(request)


def test_encoder_refuses_capability_result_not_admitted_by_decoder() -> None:
    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "OK",
        CoverageV0.complete(),
        {},
        None,
    )

    with pytest.raises(ProtocolContractError, match="own decoder"):
        wire.encode_response(response)


def test_encoder_refuses_noncanonical_unavailable_refusal() -> None:
    response = ToolResponseV0(
        "request_1",
        "project.read",
        "REFUSED",
        CoverageV0.refused("FORGED_OTHER_REASON"),
        None,
        ProtocolErrorV0(
            "TOOL_UNAVAILABLE",
            "The requested tool is unavailable in AP-01.",
            details={"reason_code": "FORGED_OTHER_REASON"},
        ),
    )

    with pytest.raises(ProtocolContractError, match="own decoder"):
        wire.encode_response(response)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda response: object.__setattr__(response, "status", "FAILED"),
        lambda response: object.__setattr__(
            response.coverage, "failed", ("FORGED_OTHER_REASON",)),
        lambda response: object.__setattr__(
            response.error, "code", "SOMETHING_ELSE"),
        lambda response: object.__setattr__(
            response.error, "message", "Forged."),
        lambda response: object.__setattr__(
            response.error, "retryable", True),
        lambda response: object.__setattr__(
            response.error,
            "details",
            freeze({"reason_code": "FORGED_OTHER_REASON"}),
        ),
        lambda response: object.__setattr__(response, "result", freeze({})),
        lambda response: object.__setattr__(
            response, "read_receipt", _receipt()),
    ],
)
def test_encoder_refuses_every_redigested_publish_refusal_mutation(
    mutator,
) -> None:
    response = wire.handle_request(
        ToolRequestV0("request_1", "publish.prepare", {}))
    mutator(response)
    object.__setattr__(
        response,
        "_response_digest",
        canonical_digest("kir.ai-tool-response.v0", response.to_data()),
    )

    with pytest.raises(ProtocolContractError, match="own decoder"):
        wire.encode_response(response)


def test_every_encodable_failed_response_self_decodes() -> None:
    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        ProtocolErrorV0("BROKEN", "Operation failed."),
    )

    payload = wire.encode_response(response)

    assert wire.decode_response(payload) == response


@pytest.mark.parametrize(
    ("field", "recompute_digest"),
    [
        ("request_id", False),
        ("tool", True),
        ("status", True),
        ("result", True),
        ("error", True),
        ("coverage", True),
        ("read_receipt", True),
        ("_response_digest", False),
    ],
)
def test_encoder_refuses_invalid_or_stale_current_response_matrix(
    field: str,
    recompute_digest: bool,
) -> None:
    response = _capability_response()
    values = {
        "request_id": "request_2",
        "tool": "project.read",
        "status": "FAILED",
        "result": freeze({}),
        "error": ProtocolErrorV0("BROKEN", "Operation failed."),
        "coverage": CoverageV0("PARTIAL", 1, 0),
        "read_receipt": _receipt(),
        "_response_digest": DIGEST_A,
    }
    object.__setattr__(response, field, values[field])
    if recompute_digest:
        object.__setattr__(
            response,
            "_response_digest",
            canonical_digest("kir.ai-tool-response.v0", response.to_data()),
        )

    with pytest.raises(ProtocolContractError):
        wire.encode_response(response)


def test_encoder_accepts_fully_valid_response_grafted_from_second_value() -> None:
    response = _capability_response()
    second = wire.handle_request(
        ToolRequestV0("request_2", "project.read", {}))
    for field in (
        "request_id",
        "tool",
        "status",
        "coverage",
        "result",
        "error",
        "read_receipt",
    ):
        object.__setattr__(response, field, getattr(second, field))
    object.__setattr__(response, "_response_digest", second.response_digest)

    payload = wire.encode_response(response)

    assert payload == wire.encode_response(second)
    assert wire.decode_response(payload) == second


def test_encoder_accepts_valid_child_graft_with_parent_redigest() -> None:
    response = _capability_response()
    second = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        ProtocolErrorV0("BROKEN", "Operation failed."),
    )
    for field in (
        "status",
        "coverage",
        "result",
        "error",
        "read_receipt",
    ):
        object.__setattr__(response, field, getattr(second, field))
    object.__setattr__(
        response,
        "_response_digest",
        canonical_digest("kir.ai-tool-response.v0", response.to_data()),
    )

    payload = wire.encode_response(response)

    assert payload == wire.encode_response(second)
    assert wire.decode_response(wire.encode_response(second)) == second


def test_encoder_accepts_copy_of_current_valid_value() -> None:
    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        ProtocolErrorV0("BROKEN", "Operation failed."),
    )

    shallow = wire.encode_response(copy.copy(response))

    assert shallow == wire.encode_response(response)
    assert wire.decode_response(shallow) == response


def test_encoder_accepts_representation_equivalent_capability_value() -> None:
    class TextValue(str):
        pass

    class CoverageLookalike:
        def __init__(self, data) -> None:
            self._data = data
            self.calls = 0

        def to_data(self):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("source coverage was read more than once")
            return self._data

    response = _capability_response()
    expected = wire.encode_response(response)
    object.__setattr__(response, "status", TextValue("OK"))
    lookalike = CoverageLookalike(thaw(response.coverage.to_data()))
    object.__setattr__(response, "coverage", lookalike)
    object.__setattr__(response, "result", thaw(response.result))

    payload = wire.encode_response(response)
    admitted = wire.decode_response(payload)

    assert payload == expected
    assert lookalike.calls == 1
    assert type(admitted.status) is str
    assert type(admitted.coverage) is CoverageV0
    assert type(admitted.result) is type(freeze({}))


def test_encoder_accepts_equivalent_nested_values_and_ignores_private_cache() -> None:
    class TextValue(str):
        pass

    class IntValue(int):
        pass

    class ErrorLookalike:
        def __init__(self, data) -> None:
            self._data = data

        def to_data(self):
            return self._data

    coverage = CoverageV0(
        "PARTIAL", 2, 1, omitted=("entity_2",), failed=())
    error = ProtocolErrorV0(
        "BROKEN", "Operation failed.", details={"reason": "fixture"})
    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        coverage,
        None,
        error,
    )
    expected = wire.encode_response(response)
    object.__setattr__(coverage, "state", TextValue("PARTIAL"))
    object.__setattr__(coverage, "requested_items", IntValue(2))
    object.__setattr__(coverage, "evaluated_items", IntValue(1))
    object.__setattr__(coverage, "omitted", ["entity_2"])
    object.__setattr__(coverage, "failed", [])
    object.__setattr__(coverage, "_coverage_digest", DIGEST_A)
    object.__setattr__(response, "status", TextValue("FAILED"))
    object.__setattr__(response, "error", ErrorLookalike(thaw(error.to_data())))

    payload = wire.encode_response(response)
    admitted = wire.decode_response(payload)

    assert payload == expected
    assert admitted.coverage.coverage_digest != DIGEST_A
    assert type(admitted.coverage.requested_items) is int
    assert type(admitted.coverage.omitted) is tuple
    assert type(admitted.error) is ProtocolErrorV0


def test_encoder_refuses_uninitialized_exact_response_safely() -> None:
    response = object.__new__(ToolResponseV0)

    with pytest.raises(ProtocolContractError, match="snapshot failed safely"):
        wire.encode_response(response)


@pytest.mark.parametrize("use_correct_text", [False, True])
def test_encoder_refuses_digest_subclass_even_when_equality_lies(
    use_correct_text: bool,
) -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        ProtocolErrorV0("BROKEN", "Operation failed."),
    )
    text = response.response_digest if use_correct_text else DIGEST_A
    object.__setattr__(response, "_response_digest", LyingDigest(text))

    with pytest.raises(ProtocolContractError, match="exact digest text"):
        wire.encode_response(response)


def test_encoder_refuses_non_text_digest_with_lying_equality() -> None:
    class LyingDigest:
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    response = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        ProtocolErrorV0("BROKEN", "Operation failed."),
    )
    object.__setattr__(response, "_response_digest", LyingDigest())

    with pytest.raises(ProtocolContractError, match="exact digest text"):
        wire.encode_response(response)


def test_request_and_response_digests_are_deterministic() -> None:
    first_request = wire.decode_request(_request_wire())
    second_request = ToolRequestV0("request_1", CAPABILITIES_TOOL, {})
    first_response = wire.handle_request(first_request)
    second_response = wire.handle_request(second_request)

    assert first_request.request_digest == second_request.request_digest
    assert first_response.response_digest == second_response.response_digest
