"""Closed immutable value contracts for the AP02-W offline wire."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal, TypeAlias

from kukai.design_source import (
    CanonicalError,
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)

from .errors import WireContractError


PROTOCOL_VERSION = "kir-ai/0"
WIRE_REQUEST_SCHEMA = "kir-ai-project-wire-request/0"
WIRE_RESPONSE_SCHEMA = "kir-ai-project-wire-response/0"
WIRE_COVERAGE_SCHEMA = "kir-ai-project-wire-coverage/0"
WIRE_ERROR_SCHEMA = "kir-ai-project-wire-error/0"

CAPABILITIES_TOOL = "capabilities.get"
PROJECT_READ_TOOL = "project.read"
MODEL_QUERY_TOOL = "model.query"
SOURCE_PATCH_TOOL = "source.patch"

DECLARED_TOOL_NAMES = (
    "build.run",
    CAPABILITIES_TOOL,
    "events.read",
    MODEL_QUERY_TOOL,
    PROJECT_READ_TOOL,
    "publish.prepare",
    "run.cancel",
    "selection.resolve",
    SOURCE_PATCH_TOOL,
)
AVAILABLE_TOOL_NAMES = (
    CAPABILITIES_TOOL,
    MODEL_QUERY_TOOL,
    PROJECT_READ_TOOL,
    SOURCE_PATCH_TOOL,
)

MAX_WIRE_BYTES = 4_000_000
MAX_ARGUMENT_BYTES = 1_000_000
MAX_RESULT_BYTES = 2_000_000
MAX_COVERAGE_BYTES = 1_000_000
MAX_ERROR_DETAIL_BYTES = 65_536
MAX_DEPTH = 128

CoverageStateV0: TypeAlias = Literal[
    "COMPLETE", "PARTIAL", "NOT_EVALUATED", "REFUSED"
]
ResponseStatusV0: TypeAlias = Literal[
    "OK", "CONFLICT", "REFUSED", "FAILED"
]

_COVERAGE_STATES = frozenset({
    "COMPLETE", "PARTIAL", "NOT_EVALUATED", "REFUSED"
})
_RESPONSE_STATUSES = frozenset({"OK", "CONFLICT", "REFUSED", "FAILED"})
_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")


def exact_identifier(value: Any, path: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise WireContractError(f"{path} must be an exact V0 identifier")
    return value


def exact_text(
    value: Any,
    path: str,
    *,
    max_length: int = 4_096,
) -> str:
    if type(value) is not str or not value:
        raise WireContractError(f"{path} must be exact non-empty text")
    if len(value) > max_length:
        raise WireContractError(f"{path} exceeds its text limit")
    try:
        admitted = strict_json_loads(canonical_bytes(value))
    except (CanonicalError, TypeError, ValueError) as exc:
        raise WireContractError(f"{path} is not canonical text: {exc}") from exc
    if type(admitted) is not str:
        raise WireContractError(f"{path} did not remain exact text")
    return admitted


def exact_count(value: Any, path: str) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise WireContractError(
            f"{path} must be an exact bounded non-negative integer")
    return value


def fresh_value(value: Any, path: str, *, max_bytes: int) -> Any:
    try:
        payload = canonical_bytes(value)
        if len(payload) > max_bytes:
            raise WireContractError(
                f"{path} exceeds {max_bytes} canonical bytes")
        return strict_json_loads(payload)
    except WireContractError:
        raise
    except (CanonicalError, TypeError, ValueError, RecursionError) as exc:
        raise WireContractError(f"{path} is not canonical: {exc}") from exc


def fresh_object(value: Any, path: str, *, max_bytes: int) -> FrozenMap:
    admitted = fresh_value(value, path, max_bytes=max_bytes)
    if type(admitted) is not FrozenMap:
        raise WireContractError(f"{path} must be an exact object")
    return admitted


@dataclass(frozen=True, slots=True)
class WireCoverageV0:
    state: CoverageStateV0
    requested: int
    evaluated: int
    returned: int

    def __post_init__(self) -> None:
        if self.state not in _COVERAGE_STATES:
            raise WireContractError("coverage.state is unsupported")
        for name in ("requested", "evaluated", "returned"):
            exact_count(getattr(self, name), f"coverage.{name}")
        if self.returned > self.evaluated or self.evaluated > self.requested:
            raise WireContractError("coverage census is inconsistent")
        if self.state in {"COMPLETE", "PARTIAL"}:
            if self.evaluated != self.requested:
                raise WireContractError(
                    "evaluated coverage must evaluate every requested item")
        if self.state == "PARTIAL" and (
            self.requested == 0
            or self.returned == 0
            or self.returned >= self.requested
        ):
            raise WireContractError("PARTIAL coverage must expose a real page")
        if self.state in {"NOT_EVALUATED", "REFUSED"} and (
            self.evaluated != 0 or self.returned != 0
        ):
            raise WireContractError(
                "non-evaluated coverage cannot claim evaluated or returned items")
        if len(canonical_bytes(self.to_data())) > MAX_COVERAGE_BYTES:
            raise WireContractError("coverage exceeds its canonical byte limit")

    @classmethod
    def complete(cls, count: int = 1, *, returned: int | None = None):
        admitted = exact_count(count, "coverage count")
        return cls(
            "COMPLETE",
            admitted,
            admitted,
            admitted if returned is None else returned,
        )

    @classmethod
    def refused(cls, requested: int = 1):
        return cls("REFUSED", requested, 0, 0)

    @classmethod
    def not_evaluated(cls, requested: int = 1):
        return cls("NOT_EVALUATED", requested, 0, 0)

    def to_data(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "requested": self.requested,
            "returned": self.returned,
            "schema": WIRE_COVERAGE_SCHEMA,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class WireErrorV0:
    code: str
    message: str
    retryable: bool = False
    details: FrozenMap | dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = exact_text(self.code, "error.code", max_length=128)
        if _ERROR_CODE_RE.fullmatch(code) is None:
            raise WireContractError("error.code must be an uppercase symbol")
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self, "message", exact_text(self.message, "error.message"))
        if type(self.retryable) is not bool:
            raise WireContractError("error.retryable must be exact bool")
        object.__setattr__(self, "details", fresh_object(
            self.details,
            "error.details",
            max_bytes=MAX_ERROR_DETAIL_BYTES,
        ))

    def to_data(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "details": self.details,
            "message": self.message,
            "retryable": self.retryable,
            "schema": WIRE_ERROR_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class WireRequestV0:
    request_id: str
    tool: str
    arguments: FrozenMap | dict[str, Any]
    _request_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", exact_identifier(
            self.request_id, "request.request_id"))
        if type(self.tool) is not str or self.tool not in DECLARED_TOOL_NAMES:
            raise WireContractError("request.tool is not exactly declared")
        object.__setattr__(self, "arguments", fresh_object(
            self.arguments,
            "request.arguments",
            max_bytes=MAX_ARGUMENT_BYTES,
        ))
        object.__setattr__(
            self,
            "_request_digest",
            canonical_digest("kir.ai-project-wire-request.v0", self.to_data()),
        )

    @property
    def request_digest(self) -> str:
        return self._request_digest

    def to_data(self) -> dict[str, Any]:
        return {
            "arguments": self.arguments,
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "tool": self.tool,
        }


@dataclass(frozen=True, slots=True)
class WireResponseV0:
    request_id: str
    tool: str
    status: ResponseStatusV0
    coverage: WireCoverageV0
    result: FrozenMap | dict[str, Any] | None
    error: WireErrorV0 | None
    read_receipt: FrozenMap | dict[str, Any] | None
    _response_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", exact_identifier(
            self.request_id, "response.request_id"))
        if type(self.tool) is not str or self.tool not in DECLARED_TOOL_NAMES:
            raise WireContractError("response.tool is not exactly declared")
        if self.status not in _RESPONSE_STATUSES:
            raise WireContractError("response.status is unsupported")
        if type(self.coverage) is not WireCoverageV0:
            raise WireContractError(
                "response.coverage must be exact WireCoverageV0")
        if self.error is not None and type(self.error) is not WireErrorV0:
            raise WireContractError("response.error has wrong concrete type")
        result = None
        if self.result is not None:
            result = fresh_object(
                self.result, "response.result", max_bytes=MAX_RESULT_BYTES)
        receipt = None
        if self.read_receipt is not None:
            receipt = fresh_object(
                self.read_receipt,
                "response.read_receipt",
                max_bytes=MAX_RESULT_BYTES,
            )
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "read_receipt", receipt)

        if self.status == "OK":
            if self.tool not in AVAILABLE_TOOL_NAMES:
                raise WireContractError("unavailable tool cannot return OK")
            if result is None or self.error is not None:
                raise WireContractError("OK requires result and excludes error")
            if self.coverage.state not in {"COMPLETE", "PARTIAL"}:
                raise WireContractError("OK requires evaluated coverage")
            if self.tool in {CAPABILITIES_TOOL, SOURCE_PATCH_TOOL}:
                if receipt is not None:
                    raise WireContractError(
                        "capabilities/source.patch OK requires null receipt")
            else:
                if receipt is None or "receipt" not in result:
                    raise WireContractError(
                        "read/query OK requires mirrored read receipt")
                if canonical_bytes(result["receipt"]) != canonical_bytes(receipt):
                    raise WireContractError(
                        "outer receipt does not equal result receipt")
        else:
            if result is not None or receipt is not None or self.error is None:
                raise WireContractError(
                    "non-success requires error and null result/receipt")
            expected_state = (
                "REFUSED" if self.status == "REFUSED" else "NOT_EVALUATED")
            if self.coverage.state != expected_state:
                raise WireContractError(
                    "non-success status/coverage state mismatch")

        object.__setattr__(
            self,
            "_response_digest",
            canonical_digest("kir.ai-project-wire-response.v0", self.to_data()),
        )

    @property
    def response_digest(self) -> str:
        return self._response_digest

    def to_data(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage.to_data(),
            "error": None if self.error is None else self.error.to_data(),
            "protocol": PROTOCOL_VERSION,
            "read_receipt": self.read_receipt,
            "request_id": self.request_id,
            "result": self.result,
            "status": self.status,
            "tool": self.tool,
        }


__all__ = [
    "AVAILABLE_TOOL_NAMES",
    "CAPABILITIES_TOOL",
    "CoverageStateV0",
    "DECLARED_TOOL_NAMES",
    "MAX_ARGUMENT_BYTES",
    "MAX_COVERAGE_BYTES",
    "MAX_DEPTH",
    "MAX_ERROR_DETAIL_BYTES",
    "MAX_RESULT_BYTES",
    "MAX_WIRE_BYTES",
    "MODEL_QUERY_TOOL",
    "PROJECT_READ_TOOL",
    "PROTOCOL_VERSION",
    "ResponseStatusV0",
    "SOURCE_PATCH_TOOL",
    "WIRE_COVERAGE_SCHEMA",
    "WIRE_ERROR_SCHEMA",
    "WIRE_REQUEST_SCHEMA",
    "WIRE_RESPONSE_SCHEMA",
    "WireCoverageV0",
    "WireErrorV0",
    "WireRequestV0",
    "WireResponseV0",
    "exact_count",
    "exact_identifier",
    "exact_text",
    "fresh_object",
    "fresh_value",
]
