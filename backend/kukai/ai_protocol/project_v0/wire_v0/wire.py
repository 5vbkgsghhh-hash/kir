"""Strict codecs for the isolated AP02-W offline fixture wire."""
from __future__ import annotations

import re
from typing import Any

from kukai.design_source import (
    CanonicalError,
    FrozenMap,
    canonical_bytes,
    strict_json_loads,
)
from kukai.design_source.errors import DesignSourceError

from ..errors import ProjectKernelError
from ..source_codec import (
    parse_model_query_command,
    parse_project_read_command,
    parse_source_patch_command,
)
from .contracts import (
    AVAILABLE_TOOL_NAMES,
    CAPABILITIES_TOOL,
    DECLARED_TOOL_NAMES,
    MAX_ARGUMENT_BYTES,
    MAX_COVERAGE_BYTES,
    MAX_RESULT_BYTES,
    MAX_WIRE_BYTES,
    MODEL_QUERY_TOOL,
    PROJECT_READ_TOOL,
    PROTOCOL_VERSION,
    SOURCE_PATCH_TOOL,
    WIRE_COVERAGE_SCHEMA,
    WIRE_ERROR_SCHEMA,
    WireCoverageV0,
    WireErrorV0,
    WireRequestV0,
    WireResponseV0,
    exact_identifier,
)
from .errors import (
    AddressableRequestError,
    ProjectWireError,
    WireContractError,
    WireDecodeError,
    WireEncodeError,
    WireShapeError,
)
from .registry import CAPABILITY_REGISTRY, admit_capability_registry
from .result_codec import (
    parse_model_query_result,
    parse_project_read_result,
    parse_source_patch_result,
)


_REQUEST_FIELDS = frozenset({"arguments", "protocol", "request_id", "tool"})
_RESPONSE_FIELDS = frozenset({
    "coverage",
    "error",
    "protocol",
    "read_receipt",
    "request_id",
    "result",
    "status",
    "tool",
})
_COVERAGE_FIELDS = frozenset({
    "evaluated",
    "requested",
    "returned",
    "schema",
    "state",
})
_ERROR_FIELDS = frozenset({
    "code",
    "details",
    "message",
    "retryable",
    "schema",
})
_FORBIDDEN_MODEL_KEYS = frozenset({
    "access_token",
    "approval",
    "approval_id",
    "auth",
    "authentication",
    "authorization",
    "author",
    "author_id",
    "authority",
    "authority_id",
    "claimed_author_id",
    "principal",
    "principal_id",
    "token",
})
_FORBIDDEN_MODEL_COMPACT_KEYS = frozenset(
    item.replace("_", "") for item in _FORBIDDEN_MODEL_KEYS)
_SENSITIVE_MODEL_KEY_PARTS = frozenset({
    "approval",
    "auth",
    "authentication",
    "authorization",
    "author",
    "authority",
    "principal",
    "token",
})
_CONFLICT_CODES = frozenset({
    "PATCH_ID_CONTRADICTION",
    "PROJECT_STATE_CONFLICT",
})
_FAILED_ERROR = WireErrorV0(
    "INTERNAL_FAILURE",
    "offline fixture request failed unexpectedly",
    False,
    {},
)
_FAILED_ERROR_BYTES = canonical_bytes(_FAILED_ERROR.to_data())
_CAPABILITY_RESULT_BYTES = canonical_bytes(CAPABILITY_REGISTRY.to_data())
_UNAVAILABLE_REASONS = {
    item["name"]: item["reason_code"]
    for item in CAPABILITY_REGISTRY.to_data()["tools"]
    if item["availability"] == "UNAVAILABLE"
}
_UNAVAILABLE_ERROR_BYTES = {
    tool: canonical_bytes(WireErrorV0(
        reason,
        "declared tool is unavailable in the offline project V0 fixture",
        False,
        {"tool": tool},
    ).to_data())
    for tool, reason in _UNAVAILABLE_REASONS.items()
}


def _decode_json(blob: bytes, path: str) -> FrozenMap:
    if type(blob) is not bytes:
        raise WireDecodeError(
            f"{path} must be exact bytes", code="WIRE_BYTES_REQUIRED")
    if len(blob) > MAX_WIRE_BYTES:
        raise WireDecodeError(
            f"{path} exceeds {MAX_WIRE_BYTES} bytes",
            code="WIRE_BYTE_LIMIT_EXCEEDED",
        )
    try:
        value = strict_json_loads(blob)
    except CanonicalError as exc:
        raise WireDecodeError(
            f"{path} is not strict JSON: {exc}", code="WIRE_JSON_INVALID") from exc
    if type(value) is not FrozenMap:
        raise WireShapeError(
            f"{path} must be an object", code="WIRE_TOP_LEVEL_NOT_OBJECT")
    return value


def _request_address(raw: FrozenMap) -> tuple[str, str]:
    request_id = raw.get("request_id")
    try:
        request_id = exact_identifier(request_id, "request.request_id")
    except WireContractError as exc:
        raise WireShapeError(
            str(exc), code="WIRE_REQUEST_ID_INVALID") from exc
    tool = raw.get("tool")
    if type(tool) is not str:
        raise WireShapeError(
            "request.tool must be exact text", code="WIRE_TOOL_INVALID")
    if tool not in DECLARED_TOOL_NAMES:
        raise WireShapeError(
            "request names an undeclared tool", code="UNKNOWN_TOOL")
    return request_id, tool


def _addressable(
    message: str,
    *,
    request_id: str,
    tool: str,
    code: str,
    details: dict[str, Any] | None = None,
) -> AddressableRequestError:
    return AddressableRequestError(
        message,
        request_id=request_id,
        tool=tool,
        refusal_code=code,
        details=details,
    )


def _reject_authority_fields(
    value: Any,
    *,
    request_id: str,
    tool: str,
) -> None:
    stack = [(value, "request.arguments")]
    while stack:
        current, path = stack.pop()
        if type(current) is FrozenMap:
            for key, item in current.items():
                expanded = re.sub(r"(?<=[A-Za-z0-9])(?=[A-Z])", "_", key)
                normalized = re.sub(
                    r"[^A-Za-z0-9]+", "_", expanded).strip("_").casefold()
                compact = normalized.replace("_", "")
                parts = frozenset(normalized.split("_"))
                if (
                    normalized in _FORBIDDEN_MODEL_KEYS
                    or compact in _FORBIDDEN_MODEL_COMPACT_KEYS
                    or not parts.isdisjoint(_SENSITIVE_MODEL_KEY_PARTS)
                ):
                    raise _addressable(
                        f"caller cannot set {path}.{key}",
                        request_id=request_id,
                        tool=tool,
                        code="MODEL_AUTHORITY_FIELD_FORBIDDEN",
                    )
                stack.append((item, f"{path}.{key}"))
        elif type(current) is tuple:
            stack.extend(
                (item, f"{path}[{index}]")
                for index, item in enumerate(current)
            )


def _parse_tool_arguments(tool: str, arguments: FrozenMap) -> Any:
    if tool == PROJECT_READ_TOOL:
        return parse_project_read_command(arguments)
    if tool == MODEL_QUERY_TOOL:
        return parse_model_query_command(arguments)
    if tool == SOURCE_PATCH_TOOL:
        return parse_source_patch_command(arguments)
    if tool == CAPABILITIES_TOOL:
        if len(arguments) != 0:
            raise WireContractError(
                "capabilities.get arguments must be exact empty object")
        return None
    if len(arguments) != 0:
        raise WireContractError(
            "sealed unavailable probe arguments must be exact empty object")
    return None


def decode_request(blob: bytes) -> WireRequestV0:
    """Decode one request; never invent an address for malformed input."""

    raw = _decode_json(blob, "request")
    request_id, tool = _request_address(raw)
    if set(raw) != _REQUEST_FIELDS:
        raise _addressable(
            "request fields are not exact",
            request_id=request_id,
            tool=tool,
            code="WIRE_FIELDS_MISMATCH",
            details={
                "extra": tuple(sorted(set(raw) - _REQUEST_FIELDS)),
                "missing": tuple(sorted(_REQUEST_FIELDS - set(raw))),
            },
        )
    if type(raw["protocol"]) is not str or raw["protocol"] != PROTOCOL_VERSION:
        raise _addressable(
            f"request.protocol must equal {PROTOCOL_VERSION!r}",
            request_id=request_id,
            tool=tool,
            code="WIRE_PROTOCOL_MISMATCH",
        )
    arguments = raw["arguments"]
    if type(arguments) is not FrozenMap:
        raise _addressable(
            "request.arguments must be an exact object",
            request_id=request_id,
            tool=tool,
            code="WIRE_ARGUMENTS_INVALID",
        )
    if len(canonical_bytes(arguments)) > MAX_ARGUMENT_BYTES:
        raise _addressable(
            f"request.arguments exceeds {MAX_ARGUMENT_BYTES} canonical bytes",
            request_id=request_id,
            tool=tool,
            code="PROJECT_LIMIT_EXCEEDED",
        )
    _reject_authority_fields(
        arguments, request_id=request_id, tool=tool)
    try:
        _parse_tool_arguments(tool, arguments)
        request = WireRequestV0(request_id, tool, arguments)
    except ProjectKernelError as exc:
        raise _addressable(
            str(exc),
            request_id=request_id,
            tool=tool,
            code=exc.code,
            details=exc.details,
        ) from exc
    except WireContractError as exc:
        raise _addressable(
            str(exc),
            request_id=request_id,
            tool=tool,
            code=exc.code,
        ) from exc
    if canonical_bytes(request.to_data()) != canonical_bytes(raw):
        raise _addressable(
            "request canonical admission drifted",
            request_id=request_id,
            tool=tool,
            code="WIRE_CANONICAL_VALUE_MISMATCH",
        )
    return request


def _response_coverage(value: Any) -> WireCoverageV0:
    if type(value) is not FrozenMap or set(value) != _COVERAGE_FIELDS:
        raise WireContractError("response.coverage fields are not exact")
    if value["schema"] != WIRE_COVERAGE_SCHEMA:
        raise WireContractError("response.coverage.schema is not exact")
    coverage = WireCoverageV0(
        value["state"],
        value["requested"],
        value["evaluated"],
        value["returned"],
    )
    if canonical_bytes(coverage.to_data()) != canonical_bytes(value):
        raise WireContractError("response.coverage canonical value mismatch")
    return coverage


def _response_error(value: Any) -> WireErrorV0 | None:
    if value is None:
        return None
    if type(value) is not FrozenMap or set(value) != _ERROR_FIELDS:
        raise WireContractError("response.error fields are not exact")
    if value["schema"] != WIRE_ERROR_SCHEMA:
        raise WireContractError("response.error.schema is not exact")
    error = WireErrorV0(
        value["code"],
        value["message"],
        value["retryable"],
        value["details"],
    )
    if canonical_bytes(error.to_data()) != canonical_bytes(value):
        raise WireContractError("response.error canonical value mismatch")
    return error


def _require_complete_one(coverage: WireCoverageV0, path: str) -> None:
    expected = WireCoverageV0.complete(1)
    if canonical_bytes(coverage.to_data()) != canonical_bytes(expected.to_data()):
        raise WireContractError(f"{path} requires exact 1/1/1 coverage")


def _require_not_evaluated_one(
    coverage: WireCoverageV0,
    path: str,
) -> None:
    if coverage.requested != 1:
        raise WireContractError(f"{path} requires exact one requested call")


def _require_coverage_mirror(
    wire_coverage: WireCoverageV0,
    kernel_coverage: Any,
    path: str,
) -> None:
    actual = (
        wire_coverage.state,
        wire_coverage.requested,
        wire_coverage.evaluated,
        wire_coverage.returned,
    )
    expected = (
        kernel_coverage.state,
        kernel_coverage.requested,
        kernel_coverage.evaluated,
        kernel_coverage.returned,
    )
    if actual != expected:
        raise WireContractError(f"{path} does not mirror the K result")


def _verify_ok_result(
    tool: str,
    result: FrozenMap,
    read_receipt: Any,
    coverage: WireCoverageV0,
) -> None:
    if tool == CAPABILITIES_TOOL:
        if canonical_bytes(result) != _CAPABILITY_RESULT_BYTES:
            raise WireContractError(
                "capabilities.get result is not the captured registry")
        admit_capability_registry(result)
        _require_complete_one(coverage, "capabilities.get")
        if read_receipt is not None:
            raise WireContractError("capabilities.get receipt must be null")
        return
    if tool == PROJECT_READ_TOOL:
        admitted = parse_project_read_result(result)
        _require_coverage_mirror(
            coverage, admitted.coverage, "project.read coverage")
        if canonical_bytes(read_receipt) != canonical_bytes(
            admitted.receipt.to_data()
        ):
            raise WireContractError("project.read outer receipt is not exact")
        return
    if tool == MODEL_QUERY_TOOL:
        admitted = parse_model_query_result(result)
        _require_coverage_mirror(
            coverage, admitted.coverage, "model.query coverage")
        if canonical_bytes(read_receipt) != canonical_bytes(
            admitted.receipt.to_data()
        ):
            raise WireContractError("model.query outer receipt is not exact")
        return
    if tool == SOURCE_PATCH_TOOL:
        parse_source_patch_result(result)
        _require_complete_one(coverage, "source.patch")
        if read_receipt is not None:
            raise WireContractError("source.patch receipt must be null")
        return
    raise WireContractError("unavailable tool cannot carry an OK result")


def _verify_non_success(
    tool: str,
    status: str,
    coverage: WireCoverageV0,
    error: WireErrorV0,
) -> None:
    _require_not_evaluated_one(coverage, f"{tool} {status}")
    if error.retryable:
        raise WireContractError("offline fixture errors are not retryable")
    if tool not in AVAILABLE_TOOL_NAMES:
        if status != "REFUSED":
            raise WireContractError("unavailable tool requires REFUSED")
        expected = _UNAVAILABLE_ERROR_BYTES[tool]
        if canonical_bytes(error.to_data()) != expected:
            raise WireContractError("unavailable tool error is not exact")
        return
    if status == "CONFLICT":
        if error.code == "PATCH_ID_CONTRADICTION":
            if tool != SOURCE_PATCH_TOOL:
                raise WireContractError(
                    "PATCH_ID_CONTRADICTION requires source.patch")
        elif error.code == "PROJECT_STATE_CONFLICT":
            if tool not in {
                MODEL_QUERY_TOOL,
                PROJECT_READ_TOOL,
                SOURCE_PATCH_TOOL,
            }:
                raise WireContractError(
                    "PROJECT_STATE_CONFLICT requires a state-bound tool")
        else:
            raise WireContractError(
                "CONFLICT requires an exact conflict code")
    if status == "FAILED" and canonical_bytes(error.to_data()) != (
        _FAILED_ERROR_BYTES
    ):
        raise WireContractError("FAILED must be exact and caller-safe")
    if status == "REFUSED" and error.code in (
        _CONFLICT_CODES | {"INTERNAL_FAILURE"}
    ):
        raise WireContractError("REFUSED cannot impersonate another status")


def _decode_response_value(raw: FrozenMap) -> WireResponseV0:
    if set(raw) != _RESPONSE_FIELDS:
        raise WireContractError("response fields are not exact")
    if raw["protocol"] != PROTOCOL_VERSION:
        raise WireContractError(
            f"response.protocol must equal {PROTOCOL_VERSION!r}")
    request_id = exact_identifier(raw["request_id"], "response.request_id")
    tool = raw["tool"]
    if type(tool) is not str or tool not in DECLARED_TOOL_NAMES:
        raise WireContractError("response.tool is not exactly declared")
    if raw["result"] is not None:
        if type(raw["result"]) is not FrozenMap:
            raise WireContractError("response.result must be an exact object")
        if len(canonical_bytes(raw["result"])) > MAX_RESULT_BYTES:
            raise WireContractError("response.result exceeds its byte limit")
    if len(canonical_bytes(raw["coverage"])) > MAX_COVERAGE_BYTES:
        raise WireContractError("response.coverage exceeds its byte limit")
    coverage = _response_coverage(raw["coverage"])
    error = _response_error(raw["error"])
    response = WireResponseV0(
        request_id=request_id,
        tool=tool,
        status=raw["status"],
        coverage=coverage,
        result=raw["result"],
        error=error,
        read_receipt=raw["read_receipt"],
    )
    if response.status == "OK":
        assert response.result is not None
        _verify_ok_result(
            tool,
            response.result,
            response.read_receipt,
            coverage,
        )
    else:
        assert error is not None
        _verify_non_success(tool, response.status, coverage, error)
    if canonical_bytes(response.to_data()) != canonical_bytes(raw):
        raise WireContractError("response canonical admission drifted")
    return response


def decode_response(blob: bytes) -> WireResponseV0:
    """Decode and semantically verify one exact AP02-W response."""

    raw = _decode_json(blob, "response")
    try:
        return _decode_response_value(raw)
    except WireContractError as exc:
        raise WireDecodeError(
            f"response semantic value is invalid: {exc}",
            code="WIRE_RESPONSE_INVALID",
        ) from exc
    except (ProjectKernelError, DesignSourceError) as exc:
        raise WireDecodeError(
            f"response semantic value is invalid: {exc}",
            code="WIRE_RESPONSE_INVALID",
        ) from exc
    except (CanonicalError, TypeError, ValueError, RecursionError) as exc:
        raise WireDecodeError(
            f"response semantic value is invalid: {exc}",
            code="WIRE_RESPONSE_INVALID",
        ) from exc


def _make_response_encoder(response_decoder: Any):
    """Close an encoder over one decoder identity for mutation-safe admission."""

    captured_decoder = response_decoder

    def closed_encode(response: WireResponseV0) -> bytes:
        if type(response) is not WireResponseV0:
            raise WireEncodeError(
                "response must be exact WireResponseV0",
                code="WIRE_RESPONSE_TYPE_INVALID",
            )
        try:
            payload = canonical_bytes(response.to_data())
            if len(payload) > MAX_WIRE_BYTES:
                raise WireEncodeError(
                    "response exceeds the wire byte limit",
                    code="WIRE_BYTE_LIMIT_EXCEEDED",
                )
            admitted = captured_decoder(payload)
            if canonical_bytes(admitted.to_data()) != payload:
                raise WireEncodeError(
                    "response self-admission drifted",
                    code="WIRE_RESPONSE_SELF_ADMISSION_FAILED",
                )
            return payload
        except WireEncodeError:
            raise
        except (ProjectWireError, CanonicalError, TypeError, ValueError) as exc:
            raise WireEncodeError(
                "response failed semantic self-admission",
                code="WIRE_RESPONSE_SELF_ADMISSION_FAILED",
            ) from exc
        except Exception:
            raise WireEncodeError(
                "response failed semantic self-admission",
                code="WIRE_RESPONSE_SELF_ADMISSION_FAILED",
            ) from None

    return closed_encode


_CLOSED_RESPONSE_ENCODER = _make_response_encoder(decode_response)


def encode_response(response: WireResponseV0) -> bytes:
    """Encode through the immutable decoder captured at module admission."""

    return _CLOSED_RESPONSE_ENCODER(response)


__all__ = ["decode_request", "decode_response", "encode_response"]
