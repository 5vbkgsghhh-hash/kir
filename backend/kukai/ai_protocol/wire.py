"""Strict offline AP-01 JSON admission and pure capability handling."""
from __future__ import annotations

from typing import Any

from kukai.design_source.canonical import (
    CanonicalError,
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    identifier,
    strict_json_loads,
)

from .contracts import (
    CAPABILITIES_TOOL,
    COVERAGE_SCHEMA,
    ERROR_SCHEMA,
    MAX_WIRE_BYTES,
    PROTOCOL_VERSION,
    READ_RECEIPT_SCHEMA,
    CoverageV0,
    ProtocolErrorV0,
    ReadReceiptV0,
    ToolRequestV0,
    ToolResponseV0,
    _exact_digest_bytes,
    reject_model_authority_fields,
)
from .errors import (
    AiProtocolError,
    ProtocolContractError,
    WireDecodeError,
    WireShapeError,
)
from .registry import CAPABILITY_REGISTRY as _PACKAGED_CAPABILITY_REGISTRY


_UNAVAILABLE_MESSAGE = "The requested tool is unavailable in AP-01."
_REQUEST_FIELDS = frozenset({
    "protocol", "request_id", "tool", "arguments",
})
_RESPONSE_FIELDS = frozenset({
    "protocol",
    "request_id",
    "tool",
    "status",
    "coverage",
    "result",
    "error",
    "read_receipt",
})
_COVERAGE_FIELDS = frozenset({
    "schema", "state", "requested", "evaluated", "omitted", "failed",
})
_COUNT_FIELDS = frozenset({"items"})
_ERROR_FIELDS = frozenset({
    "schema", "code", "message", "retryable", "details",
})
_READ_RECEIPT_FIELDS = frozenset({
    "schema",
    "protocol",
    "request_id",
    "tool",
    "project_id",
    "revision_digest",
    "request_digest",
    "result_digests",
    "coverage",
    "schema_registry_digest",
    "continuation",
    "receipt_digest",
})


def _decode_json(
    blob: str | bytes,
    path: str,
    *,
    strict_loader=strict_json_loads,
    canonical_error_type=CanonicalError,
    frozen_type=FrozenMap,
    decode_error_type=WireDecodeError,
    shape_error_type=WireShapeError,
) -> FrozenMap[str, Any]:
    try:
        value = strict_loader(blob)
    except canonical_error_type as exc:
        raise decode_error_type(
            f"{path} is not strict JSON: {exc}") from exc
    if type(value) is not frozen_type:
        raise shape_error_type(
            f"{path} must be an object", code="WIRE_TOP_LEVEL_NOT_OBJECT")
    return value


def _object(
    value: Any,
    path: str,
    fields: frozenset[str],
    *,
    frozen_type=FrozenMap,
    shape_error_type=WireShapeError,
) -> FrozenMap[str, Any]:
    if type(value) is not frozen_type:
        raise shape_error_type(f"{path} must be an exact object")
    keys = frozenset(value)
    if keys != fields:
        raise shape_error_type(
            f"{path} fields mismatch: missing={sorted(fields - keys)}, "
            f"extra={sorted(keys - fields)}",
            code="WIRE_FIELDS_MISMATCH",
        )
    return value


def _literal(
    value: Any,
    expected: str,
    path: str,
    *,
    shape_error_type=WireShapeError,
) -> None:
    if type(value) is not str or value != expected:
        raise shape_error_type(
            f"{path} must equal {expected!r}",
            code="WIRE_LITERAL_MISMATCH",
        )


def _contract(
    callable_,
    *args: Any,
    code: str = "WIRE_SHAPE_INVALID",
    contract_error_type=ProtocolContractError,
    shape_error_type=WireShapeError,
) -> Any:
    try:
        return callable_(*args)
    except contract_error_type as exc:
        raise shape_error_type(str(exc), code=code) from exc
    except Exception as exc:
        raise shape_error_type(
            "contract evaluation failed safely",
            code="WIRE_CONTRACT_EVALUATION_FAILED",
        ) from exc


def _capture_registry(
    registry,
    *,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    strict_loader=strict_json_loads,
    frozen_type=FrozenMap,
) -> tuple[
    FrozenMap[str, Any],
    str,
    FrozenMap[str, Any],
    frozenset[str],
]:
    """Copy the packaged registry into a private primitive-only wire snapshot."""

    registry.verify_integrity()
    data = strict_loader(canonical_encoder(registry.to_data()))
    if type(data) is not frozen_type:
        raise ProtocolContractError("packaged registry did not freeze to an object")
    claimed_registry_digest = data["registry_digest"]
    body = {
        key: value
        for key, value in data.items()
        if key != "registry_digest"
    }
    expected_registry_digest = canonical_hasher(
        "kir.ai-capability-registry.v0", body)
    if digest_encoder(
        claimed_registry_digest, "capabilities.registry_digest"
    ) != digest_encoder(
        expected_registry_digest, "expected capabilities.registry_digest"
    ):
        raise ProtocolContractError("packaged registry digest is not exact")
    for descriptor in data["schemas"]:
        expected = canonical_hasher(
            "kir.ai-protocol-schema.v0",
            {
                "schema_id": descriptor["schema_id"],
                "uri": descriptor["uri"],
                "definition": descriptor["definition"],
            },
        )
        if digest_encoder(
            descriptor["digest"], "capabilities.schema.digest"
        ) != digest_encoder(expected, "expected capabilities.schema.digest"):
            raise ProtocolContractError(
                "packaged registry has an invalid schema digest")

    capabilities: dict[str, Any] = {}
    for capability in data["tools"]:
        name = capability["name"]
        availability = capability["availability"]
        reason = capability["reason_code"]
        refusal = None
        if availability == "UNAVAILABLE":
            refusal = {
                "status": "REFUSED",
                "coverage": {
                    "schema": COVERAGE_SCHEMA,
                    "state": "REFUSED",
                    "requested": {"items": 1},
                    "evaluated": {"items": 0},
                    "omitted": (),
                    "failed": (reason,),
                },
                "result": None,
                "error": {
                    "schema": ERROR_SCHEMA,
                    "code": "TOOL_UNAVAILABLE",
                    "message": _UNAVAILABLE_MESSAGE,
                    "retryable": False,
                    "details": {"reason_code": reason},
                },
                "read_receipt": None,
            }
        capabilities[name] = {
            "availability": availability,
            "reason_code": reason,
            "refusal": refusal,
        }
    capability_map = strict_loader(canonical_encoder(capabilities))
    if type(capability_map) is not frozen_type:
        raise ProtocolContractError(
            "packaged capability map did not freeze to an object")
    return (
        data,
        claimed_registry_digest,
        capability_map,
        frozenset(capability_map),
    )


def _decode_request_core(
    blob: str | bytes,
    declared_tool_names: frozenset[str],
    *,
    decode_json=_decode_json,
    object_admitter=_object,
    literal_admitter=_literal,
    identifier_admitter=identifier,
    canonical_error_type=CanonicalError,
    frozen_type=FrozenMap,
    shape_error_type=WireShapeError,
    contract_error_type=ProtocolContractError,
    authority_rejecter=reject_model_authority_fields,
    contract_admitter=_contract,
    request_type=ToolRequestV0,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    request_fields=_REQUEST_FIELDS,
    protocol_version=PROTOCOL_VERSION,
) -> ToolRequestV0:
    raw = object_admitter(
        decode_json(blob, "request"), "request", request_fields)
    literal_admitter(raw["protocol"], protocol_version, "request.protocol")
    if type(raw["request_id"]) is not str:
        raise shape_error_type("request.request_id must be exact text")
    try:
        identifier_admitter(raw["request_id"], "request_id")
    except canonical_error_type as exc:
        raise shape_error_type(
            str(exc), code="WIRE_REQUEST_ID_INVALID") from exc
    if type(raw["arguments"]) is not frozen_type:
        raise shape_error_type(
            "request.arguments must be an exact object",
            code="WIRE_ARGUMENTS_INVALID",
        )
    tool = raw["tool"]
    if type(tool) is not str:
        raise shape_error_type("request.tool must be exact text")
    try:
        authority_rejecter(raw["arguments"], "request.arguments")
    except contract_error_type as exc:
        raise shape_error_type(
            str(exc), code="MODEL_AUTHORITY_FIELD_FORBIDDEN") from exc
    if tool not in declared_tool_names:
        raise shape_error_type(
            "request names an unknown tool", code="UNKNOWN_TOOL")
    request = contract_admitter(
        request_type,
        raw["request_id"],
        tool,
        raw["arguments"],
        code="WIRE_ARGUMENTS_INVALID",
    )
    expected_digest = canonical_hasher("kir.ai-tool-request.v0", raw)
    if (
        canonical_encoder(request.to_data()) != canonical_encoder(raw)
        or digest_encoder(
            request.request_digest, "request.request_digest"
        ) != digest_encoder(expected_digest, "expected request.request_digest")
    ):
        raise shape_error_type(
            "request contract runtime bindings drifted",
            code="WIRE_RUNTIME_BINDING_DRIFT",
        )
    return request


def _make_request_decoder(
    declared_tool_names: frozenset[str],
    *,
    request_core=_decode_request_core,
):
    def closed_decode_request(blob: str | bytes) -> ToolRequestV0:
        return request_core(blob, declared_tool_names)

    closed_decode_request.__name__ = "decode_request"
    return closed_decode_request


def _parse_coverage(
    value: Any,
    *,
    object_admitter=_object,
    literal_admitter=_literal,
    contract_admitter=_contract,
    coverage_type=CoverageV0,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    shape_error_type=WireShapeError,
    coverage_fields=_COVERAGE_FIELDS,
    count_fields=_COUNT_FIELDS,
    coverage_schema=COVERAGE_SCHEMA,
) -> CoverageV0:
    raw = object_admitter(value, "response.coverage", coverage_fields)
    literal_admitter(
        raw["schema"], coverage_schema, "response.coverage.schema")
    requested = object_admitter(
        raw["requested"], "response.coverage.requested", count_fields)
    evaluated = object_admitter(
        raw["evaluated"], "response.coverage.evaluated", count_fields)
    coverage = contract_admitter(
        coverage_type,
        raw["state"],
        requested["items"],
        evaluated["items"],
        raw["omitted"],
        raw["failed"],
    )
    if canonical_encoder(coverage.to_data()) != canonical_encoder(raw):
        raise shape_error_type(
            "response.coverage is not in canonical contract order",
            code="WIRE_CANONICAL_VALUE_MISMATCH",
        )
    expected_digest = canonical_hasher(
        "kir.ai-protocol-coverage.v0", raw)
    if digest_encoder(
        coverage.coverage_digest, "response.coverage.coverage_digest"
    ) != digest_encoder(expected_digest, "expected coverage digest"):
        raise shape_error_type(
            "coverage contract runtime bindings drifted",
            code="WIRE_RUNTIME_BINDING_DRIFT",
        )
    return coverage


def _parse_error(
    value: Any,
    *,
    object_admitter=_object,
    literal_admitter=_literal,
    contract_admitter=_contract,
    error_type=ProtocolErrorV0,
    canonical_encoder=canonical_bytes,
    shape_error_type=WireShapeError,
    error_fields=_ERROR_FIELDS,
    error_schema=ERROR_SCHEMA,
) -> ProtocolErrorV0:
    raw = object_admitter(value, "response.error", error_fields)
    literal_admitter(raw["schema"], error_schema, "response.error.schema")
    error = contract_admitter(
        error_type,
        raw["code"],
        raw["message"],
        raw["retryable"],
        raw["details"],
    )
    if canonical_encoder(error.to_data()) != canonical_encoder(raw):
        raise shape_error_type(
            "response.error is not its canonical contract value",
            code="WIRE_CANONICAL_VALUE_MISMATCH",
        )
    return error


def _parse_read_receipt(
    value: Any,
    *,
    object_admitter=_object,
    literal_admitter=_literal,
    contract_admitter=_contract,
    receipt_type=ReadReceiptV0,
    coverage_parser=_parse_coverage,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    shape_error_type=WireShapeError,
    receipt_fields=_READ_RECEIPT_FIELDS,
    receipt_schema=READ_RECEIPT_SCHEMA,
    protocol_version=PROTOCOL_VERSION,
) -> ReadReceiptV0:
    raw = object_admitter(
        value, "response.read_receipt", receipt_fields)
    literal_admitter(
        raw["schema"], receipt_schema, "response.read_receipt.schema")
    literal_admitter(
        raw["protocol"], protocol_version, "response.read_receipt.protocol")
    receipt = contract_admitter(
        receipt_type,
        raw["request_id"],
        raw["tool"],
        raw["project_id"],
        raw["revision_digest"],
        raw["request_digest"],
        raw["result_digests"],
        coverage_parser(raw["coverage"]),
        raw["schema_registry_digest"],
        raw["continuation"],
    )
    if type(raw["receipt_digest"]) is not str:
        raise shape_error_type("read receipt digest must be exact text")
    body = {
        key: item
        for key, item in raw.items()
        if key != "receipt_digest"
    }
    expected_digest = canonical_hasher("kir.ai-read-receipt.v0", body)
    if (
        digest_encoder(
            raw["receipt_digest"], "response.read_receipt.receipt_digest"
        )
        != digest_encoder(expected_digest, "expected read_receipt digest")
        or digest_encoder(
            receipt.receipt_digest,
            "admitted response.read_receipt.receipt_digest",
        )
        != digest_encoder(expected_digest, "expected read_receipt digest")
    ):
        raise shape_error_type(
            "read receipt digest mismatch",
            code="READ_RECEIPT_DIGEST_MISMATCH",
        )
    if canonical_encoder(receipt.to_data()) != canonical_encoder(raw):
        raise shape_error_type(
            "response.read_receipt is not in canonical contract order",
            code="WIRE_CANONICAL_VALUE_MISMATCH",
        )
    return receipt


def _decode_response_core(
    blob: str | bytes,
    registry_data: FrozenMap[str, Any],
    expected_registry_digest: str,
    capability_map: FrozenMap[str, Any],
    *,
    decode_json=_decode_json,
    object_admitter=_object,
    literal_admitter=_literal,
    coverage_parser=_parse_coverage,
    error_parser=_parse_error,
    receipt_parser=_parse_read_receipt,
    contract_admitter=_contract,
    response_type=ToolResponseV0,
    frozen_type=FrozenMap,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    shape_error_type=WireShapeError,
    response_fields=_RESPONSE_FIELDS,
    protocol_version=PROTOCOL_VERSION,
    capabilities_tool=CAPABILITIES_TOOL,
) -> ToolResponseV0:
    raw = object_admitter(
        decode_json(blob, "response"), "response", response_fields)
    literal_admitter(raw["protocol"], protocol_version, "response.protocol")
    if type(raw["tool"]) is not str:
        raise shape_error_type("response.tool must be exact text")
    if type(raw["status"]) is not str:
        raise shape_error_type("response.status must be exact text")
    capability = capability_map.get(raw["tool"])
    if capability is not None and capability["availability"] == "UNAVAILABLE":
        refusal = capability["refusal"]
        if (
            raw["status"] != refusal["status"]
            or raw["coverage"] != refusal["coverage"]
            or raw["result"] != refusal["result"]
            or raw["error"] != refusal["error"]
            or raw["read_receipt"] != refusal["read_receipt"]
        ):
            raise shape_error_type(
                "unavailable tool response is not its sealed refusal",
                code="UNAVAILABLE_REFUSAL_MISMATCH",
            )
    result = raw["result"]
    if result is not None and type(result) is not frozen_type:
        raise shape_error_type("response.result must be an object or null")
    coverage = coverage_parser(raw["coverage"])
    error = None if raw["error"] is None else error_parser(raw["error"])
    receipt = (
        None
        if raw["read_receipt"] is None
        else receipt_parser(raw["read_receipt"])
    )
    if (
        receipt is not None
        and digest_encoder(
            receipt.schema_registry_digest,
            "response.read_receipt.schema_registry_digest",
        )
        != digest_encoder(
            expected_registry_digest, "expected schema_registry_digest")
    ):
        raise shape_error_type(
            "read receipt names a different schema registry",
            code="READ_RECEIPT_REGISTRY_MISMATCH",
        )
    if raw["tool"] == capabilities_tool and raw["status"] == "OK":
        if result is None or result != registry_data:
            raise shape_error_type(
                "capabilities.get OK requires the exact packaged registry",
                code="CAPABILITY_RESULT_INVALID",
            )
    if (
        raw["tool"] == capabilities_tool
        and raw["status"] == "OK"
        and receipt is not None
        and receipt.request_id == raw["request_id"]
        and receipt.tool == raw["tool"]
        and canonical_encoder(receipt.coverage.to_data())
        == canonical_encoder(coverage.to_data())
    ):
        raise shape_error_type(
            "capabilities.get cannot carry a project read receipt",
            code="CAPABILITY_READ_RECEIPT_FORBIDDEN",
        )
    response = contract_admitter(
        response_type,
        raw["request_id"],
        raw["tool"],
        raw["status"],
        coverage,
        result,
        error,
        receipt,
    )
    if canonical_encoder(response.to_data()) != canonical_encoder(raw):
        raise shape_error_type(
            "response contract runtime bindings drifted",
            code="WIRE_RUNTIME_BINDING_DRIFT",
        )
    expected_response_digest = canonical_hasher(
        "kir.ai-tool-response.v0", raw)
    if digest_encoder(
        response.response_digest, "response.response_digest"
    ) != digest_encoder(expected_response_digest, "expected response digest"):
        raise shape_error_type(
            "response digest runtime bindings drifted",
            code="WIRE_RUNTIME_BINDING_DRIFT",
        )
    return response


def _make_response_decoder(
    registry_data: FrozenMap[str, Any],
    expected_registry_digest: str,
    capability_map: FrozenMap[str, Any],
    *,
    response_core=_decode_response_core,
):
    def closed_decode_response(blob: str | bytes) -> ToolResponseV0:
        return response_core(
            blob,
            registry_data,
            expected_registry_digest,
            capability_map,
        )

    closed_decode_response.__name__ = "decode_response"
    return closed_decode_response


def _make_request_handler(
    registry_data: FrozenMap[str, Any],
    capability_map: FrozenMap[str, Any],
    request_decoder,
    response_decoder,
    *,
    request_type=ToolRequestV0,
    canonical_encoder=canonical_bytes,
    canonical_hasher=canonical_digest,
    digest_encoder=_exact_digest_bytes,
    contract_error_type=ProtocolContractError,
    canonical_error_type=CanonicalError,
    protocol_version=PROTOCOL_VERSION,
    capabilities_tool=CAPABILITIES_TOOL,
    coverage_schema=COVERAGE_SCHEMA,
    max_wire_bytes=MAX_WIRE_BYTES,
):
    def closed_handle_request(request: ToolRequestV0) -> ToolResponseV0:
        """Pure handler closed over a primitive packaged registry snapshot."""

        if type(request) is not request_type:
            raise contract_error_type(
                "handler requires an exact ToolRequestV0")
        try:
            request_data = request.to_data()
            source_request_digest = digest_encoder(
                request.request_digest, "request.request_digest")
            request_payload = canonical_encoder(request_data)
        except contract_error_type:
            raise
        except canonical_error_type as exc:
            raise contract_error_type(
                f"handler request is not canonical: {exc}") from exc
        except Exception as exc:
            raise contract_error_type(
                "handler request snapshot failed safely") from exc
        if len(request_payload) > max_wire_bytes:
            raise contract_error_type(
                "request exceeds the AP-01 wire byte limit")
        try:
            admitted_request = request_decoder(request_payload)
        except Exception as exc:
            raise contract_error_type(
                "handler request is not admitted by its wire decoder") from exc
        if source_request_digest != digest_encoder(
            admitted_request.request_digest,
            "admitted request.request_digest",
        ):
            raise contract_error_type(
                "handler request digest does not match its current value")
        if (
            type(admitted_request) is not request_type
            or canonical_encoder(admitted_request.to_data()) != request_payload
        ):
            raise contract_error_type(
                "handler request value/digest admission mismatch")
        capability = capability_map.get(admitted_request.tool)
        if capability is None:
            raise contract_error_type(
                "request tool escaped packaged registry snapshot")
        expected = {
            "protocol": protocol_version,
            "request_id": admitted_request.request_id,
            "tool": admitted_request.tool,
            **(
                {
                    "status": "OK",
                    "coverage": {
                        "schema": coverage_schema,
                        "state": "COMPLETE",
                        "requested": {"items": 1},
                        "evaluated": {"items": 1},
                        "omitted": (),
                        "failed": (),
                    },
                    "result": registry_data,
                    "error": None,
                    "read_receipt": None,
                }
                if admitted_request.tool == capabilities_tool
                else capability["refusal"]
            ),
        }
        expected_payload = canonical_encoder(expected)
        try:
            response = response_decoder(expected_payload)
        except Exception as exc:
            raise contract_error_type(
                "handler response admission failed safely") from exc
        if canonical_encoder(response.to_data()) != expected_payload:
            raise contract_error_type("handler response admission drifted")
        expected_digest = canonical_hasher(
            "kir.ai-tool-response.v0", expected)
        if digest_encoder(
            response.response_digest, "handler response.response_digest"
        ) != digest_encoder(expected_digest, "expected handler response digest"):
            raise contract_error_type(
                "handler response digest runtime bindings drifted")
        return response

    closed_handle_request.__name__ = "handle_request"
    return closed_handle_request


def _make_response_encoder(
    response_decoder,
    *,
    response_type=ToolResponseV0,
    canonical_encoder=canonical_bytes,
    digest_encoder=_exact_digest_bytes,
    canonical_error_type=CanonicalError,
    protocol_error_type=AiProtocolError,
    contract_error_type=ProtocolContractError,
    max_wire_bytes=MAX_WIRE_BYTES,
):
    def closed_encode_response(response: ToolResponseV0) -> bytes:
        if type(response) is not response_type:
            raise contract_error_type(
                "encode_response requires ToolResponseV0")
        try:
            response_data = response.to_data()
            source_response_digest = digest_encoder(
                response.response_digest, "response.response_digest")
            payload = canonical_encoder(response_data)
        except contract_error_type:
            raise
        except canonical_error_type as exc:
            raise contract_error_type(
                f"response is not canonical: {exc}") from exc
        except Exception as exc:
            raise contract_error_type(
                "response snapshot failed safely") from exc
        if len(payload) > max_wire_bytes:
            raise contract_error_type(
                "response exceeds the AP-01 wire byte limit")
        try:
            admitted = response_decoder(payload)
        except protocol_error_type as exc:
            raise contract_error_type(
                f"response is not admitted by its own decoder: {exc}") from exc
        if source_response_digest != digest_encoder(
            admitted.response_digest, "admitted response.response_digest"
        ):
            raise contract_error_type(
                "response digest does not match its encoded value")
        if (
            canonical_encoder(admitted.to_data()) != payload
        ):
            raise contract_error_type(
                "response encode/decode canonical closure failed")
        return payload

    closed_encode_response.__name__ = "encode_response"
    return closed_encode_response


def _make_wire_request_handler(
    request_decoder,
    request_handler,
    response_encoder,
):
    def closed_handle_wire_request(blob: str | bytes) -> bytes:
        return response_encoder(request_handler(request_decoder(blob)))

    closed_handle_wire_request.__name__ = "handle_wire_request"
    return closed_handle_wire_request


(
    _REGISTRY_DATA_SNAPSHOT,
    _REGISTRY_DIGEST_SNAPSHOT,
    _CAPABILITY_MAP_SNAPSHOT,
    _DECLARED_TOOL_NAMES_SNAPSHOT,
) = _capture_registry(_PACKAGED_CAPABILITY_REGISTRY)

decode_request = _make_request_decoder(_DECLARED_TOOL_NAMES_SNAPSHOT)
decode_response = _make_response_decoder(
    _REGISTRY_DATA_SNAPSHOT,
    _REGISTRY_DIGEST_SNAPSHOT,
    _CAPABILITY_MAP_SNAPSHOT,
)
handle_request = _make_request_handler(
    _REGISTRY_DATA_SNAPSHOT,
    _CAPABILITY_MAP_SNAPSHOT,
    decode_request,
    decode_response,
)
encode_response = _make_response_encoder(decode_response)
handle_wire_request = _make_wire_request_handler(
    decode_request, handle_request, encode_response)
del _REGISTRY_DATA_SNAPSHOT
del _REGISTRY_DIGEST_SNAPSHOT
del _CAPABILITY_MAP_SNAPSHOT
del _DECLARED_TOOL_NAMES_SNAPSHOT
del _PACKAGED_CAPABILITY_REGISTRY


__all__ = [
    "decode_request",
    "decode_response",
    "encode_response",
    "handle_request",
    "handle_wire_request",
]
