from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.project_v0 import (
    ModelQueryCommandV0,
    ModulePutV0,
    ProjectReadCommandV0,
    ReceiptRefV0,
    SourcePatchCommandV0,
)
from kukai.ai_protocol.project_v0.wire_v0 import decode_request
from kukai.ai_protocol.project_v0.wire_v0.contracts import (
    AVAILABLE_TOOL_NAMES,
    DECLARED_TOOL_NAMES,
    MAX_ARGUMENT_BYTES,
    MAX_WIRE_BYTES,
    PROTOCOL_VERSION,
    fresh_object,
)
from kukai.ai_protocol.project_v0.wire_v0.errors import (
    AddressableRequestError,
    WireContractError,
    WireDecodeError,
    WireShapeError,
)
from kukai.design_source import canonical_bytes
from kukai.design_source.examples import make_tower_source


DIGEST_A = "sha256:" + "a" * 64


def _request(*, tool="capabilities.get", arguments=None, request_id="request_1"):
    return {
        "arguments": {} if arguments is None else arguments,
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "tool": tool,
    }


def _wire(**changes) -> bytes:
    data = _request()
    data.update(changes)
    return canonical_bytes(data)


def test_request_decode_is_fresh_and_byte_stable() -> None:
    data = _request()
    first = decode_request(canonical_bytes(data))
    second = decode_request(canonical_bytes(data))
    data["arguments"]["mutated"] = True

    assert first is not second
    assert first.arguments is not second.arguments
    assert first.arguments == {}
    assert canonical_bytes(first.to_data()) == canonical_bytes(second.to_data())


@pytest.mark.parametrize(
    "blob",
    [
        None,
        "{}",
        bytearray(b"{}"),
        b"",
        b"{",
        b"{}{}",
        b'{"x":1,"x":2}',
        br'{"\u00e9":1,"e\u0301":2}'.replace(b"\\\\", b"\\"),
        b'{"x":1.0}',
        b'{"x":1e3}',
        b'{"x":NaN}',
        br'{"x":"\ud800"}'.replace(b"\\\\", b"\\"),
        b"\xff",
    ],
)
def test_strict_json_negative_corpus_is_unaddressable(blob) -> None:
    with pytest.raises(WireDecodeError):
        decode_request(blob)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("request_id"),
        lambda data: data.update({"request_id": 1}),
        lambda data: data.update({"request_id": "1bad"}),
        lambda data: data.pop("tool"),
        lambda data: data.update({"tool": 1}),
        lambda data: data.update({"tool": "unknown.tool"}),
    ],
)
def test_unaddressable_identity_never_invents_response_address(mutation) -> None:
    data = _request()
    mutation(data)

    with pytest.raises(WireShapeError):
        decode_request(canonical_bytes(data))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data.update({"extra": True}), "WIRE_FIELDS_MISMATCH"),
        (lambda data: data.pop("protocol"), "WIRE_FIELDS_MISMATCH"),
        (
            lambda data: data.update({"protocol": "kir-ai/1"}),
            "WIRE_PROTOCOL_MISMATCH",
        ),
        (
            lambda data: data.update({"arguments": None}),
            "WIRE_ARGUMENTS_INVALID",
        ),
    ],
)
def test_addressable_envelope_failure_preserves_exact_identity(mutation, code) -> None:
    data = _request()
    mutation(data)

    with pytest.raises(AddressableRequestError) as caught:
        decode_request(canonical_bytes(data))
    assert caught.value.request_id == "request_1"
    assert caught.value.tool == "capabilities.get"
    assert caught.value.code == code


@pytest.mark.parametrize(
    "key",
    [
        "principal",
        "author_id",
        "Authority",
        "approval-token",
        "accessToken",
        "auth",
        "authentication",
        "authorization",
        "claimedAuthorization",
        "auth-id",
        "claimedAuthorId",
        "claimedauthorid",
        "authorityid",
    ],
)
def test_forbidden_authority_fields_are_recursive_and_precede_k_parse(key) -> None:
    arguments = {"invalid_anyway": [{"nested": {key: "model"}}]}

    with pytest.raises(AddressableRequestError) as caught:
        decode_request(_wire(tool="project.read", arguments=arguments))
    assert caught.value.code == "MODEL_AUTHORITY_FIELD_FORBIDDEN"


def test_available_tool_arguments_go_through_exact_k_parsers() -> None:
    source = make_tower_source(n_floors=3)
    read = ProjectReadCommandV0(
        source.project_id, source.revision_digest, "manifest")
    query = ModelQueryCommandV0(
        project_id=source.project_id,
        revision_digest=source.revision_digest,
        build_digest=DIGEST_A,
        scope="summary",
        filters={},
        limit=1,
    )
    patch = SourcePatchCommandV0(
        project_id=source.project_id,
        base_revision_digest=source.revision_digest,
        patch_id="patch_1",
        receipt_refs=(ReceiptRefV0("rr_" + "a" * 40, DIGEST_A),),
        operations=(ModulePutV0("put", source.modules[0]),),
    )

    for tool, arguments in (
        ("project.read", read.to_data()),
        ("model.query", query.to_data()),
        ("source.patch", patch.to_data()),
    ):
        admitted = decode_request(_wire(tool=tool, arguments=arguments))
        assert admitted.tool == tool
        assert canonical_bytes(admitted.arguments) == canonical_bytes(arguments)

    invalid = read.to_data()
    invalid["extra"] = True
    with pytest.raises(AddressableRequestError) as caught:
        decode_request(_wire(tool="project.read", arguments=invalid))
    assert caught.value.code == "PROJECT_CONTRACT_INVALID"


def test_capability_and_unavailable_probe_arguments_are_exact_empty() -> None:
    probe_tools = (
        "capabilities.get",
        *(tool for tool in DECLARED_TOOL_NAMES if tool not in AVAILABLE_TOOL_NAMES),
    )
    for tool in probe_tools:
        admitted = decode_request(_wire(tool=tool))
        assert admitted.arguments == {}

    with pytest.raises(AddressableRequestError) as caught:
        decode_request(_wire(tool="build.run", arguments={"probe": True}))
    assert caught.value.code == "WIRE_CONTRACT_INVALID"


def test_argument_canonical_budget_accepts_exact_and_refuses_plus_one() -> None:
    empty_size = len(canonical_bytes({"padding": ""}))
    exact = {"padding": "x" * (MAX_ARGUMENT_BYTES - empty_size)}
    assert len(canonical_bytes(exact)) == MAX_ARGUMENT_BYTES
    assert fresh_object(
        exact, "arguments", max_bytes=MAX_ARGUMENT_BYTES)["padding"]

    too_large = {"padding": exact["padding"] + "x"}
    with pytest.raises(WireContractError, match="exceeds"):
        fresh_object(too_large, "arguments", max_bytes=MAX_ARGUMENT_BYTES)


def test_wire_budget_accepts_exact_json_then_refuses_plus_one_before_parse() -> None:
    data = _request()
    data["extra"] = ""
    empty_size = len(canonical_bytes(data))
    data["extra"] = "x" * (MAX_WIRE_BYTES - empty_size)
    exact = canonical_bytes(data)
    assert len(exact) == MAX_WIRE_BYTES
    with pytest.raises(AddressableRequestError) as caught:
        decode_request(exact)
    assert caught.value.code == "WIRE_FIELDS_MISMATCH"

    plus_one = exact[:-2] + b'x"}'
    assert len(plus_one) == MAX_WIRE_BYTES + 1
    with pytest.raises(WireDecodeError) as caught:
        decode_request(plus_one)
    assert caught.value.code == "WIRE_BYTE_LIMIT_EXCEEDED"


def test_excessive_depth_is_typed_decode_failure() -> None:
    blob = b"[" * 129 + b"]" * 129
    with pytest.raises(WireDecodeError, match="depth"):
        decode_request(blob)
