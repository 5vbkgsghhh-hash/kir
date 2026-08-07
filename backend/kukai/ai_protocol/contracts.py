"""Closed immutable contracts for isolated AP-01 wire admission."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any, ClassVar, Literal, TypeAlias

from kukai.design_source.canonical import (
    STRICT_JSON_MAX_INPUT_BYTES,
    CanonicalError,
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    digest_text,
    freeze,
    identifier,
)

from .errors import ProtocolContractError


PROTOCOL_VERSION = "kir-ai/0"
WIRE_MILESTONE = "wire-contract-admission-v0"
REQUEST_SCHEMA = "kir-ai-tool-request/0"
RESPONSE_SCHEMA = "kir-ai-tool-response/0"
COVERAGE_SCHEMA = "kir-ai-coverage/0"
ERROR_SCHEMA = "kir-ai-error/0"
READ_RECEIPT_SCHEMA = "kir-ai-read-receipt/0"
CAPABILITIES_ARGUMENTS_SCHEMA = "kir-ai-capabilities-get-arguments/0"
CAPABILITIES_RESULT_SCHEMA = "kir-ai-capabilities-get-result/0"
CAPABILITIES_TOOL = "capabilities.get"
MAX_WIRE_BYTES = STRICT_JSON_MAX_INPUT_BYTES

DECLARED_TOOL_NAMES = (
    "build.run",
    CAPABILITIES_TOOL,
    "events.read",
    "model.query",
    "project.read",
    "publish.prepare",
    "run.cancel",
    "selection.resolve",
    "source.patch",
)
AVAILABLE_TOOL_NAMES = (CAPABILITIES_TOOL,)

CoverageStateV0: TypeAlias = Literal[
    "COMPLETE",
    "PARTIAL",
    "TRUNCATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "REFUSED",
]
ResponseStatusV0: TypeAlias = Literal["OK", "REFUSED", "FAILED"]

_COVERAGE_STATES = frozenset({
    "COMPLETE",
    "PARTIAL",
    "TRUNCATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "REFUSED",
})
_RESPONSE_STATUSES = frozenset({"OK", "REFUSED", "FAILED"})
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
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
_MAX_ARGUMENT_BYTES = 1_000_000
_MAX_RESULT_BYTES = 2_000_000
_MAX_DETAIL_BYTES = 65_536
_MAX_COVERAGE_BYTES = 1_000_000
_MAX_COVERAGE_ENTRIES = 4_096
_MAX_RECEIPT_DIGESTS = 4_096


class ProtocolContractV0:
    """Marker sealed to the isolated AP-01 implementation modules."""

    __slots__ = ()
    _ALLOWED_MODULES = frozenset({
        "kukai.ai_protocol.contracts",
        "kukai.ai_protocol.registry",
    })

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ not in ProtocolContractV0._ALLOWED_MODULES:
            raise TypeError("ProtocolContractV0 is sealed to ai_protocol")


def _canonical(callable_, *args: Any) -> Any:
    try:
        return callable_(*args)
    except CanonicalError as exc:
        raise ProtocolContractError(str(exc)) from exc


def _text(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
    max_length: int = 4_096,
) -> str:
    if type(value) is not str:
        raise ProtocolContractError(f"{path} must be exact text")
    admitted = _canonical(freeze, value)
    if not allow_empty and not admitted:
        raise ProtocolContractError(f"{path} must not be empty")
    if len(admitted) > max_length:
        raise ProtocolContractError(f"{path} exceeds its length limit")
    return admitted


def _identifier(value: Any, path: str) -> str:
    return _canonical(identifier, _text(value, path), path)


def _digest(value: Any, path: str) -> str:
    return _canonical(digest_text, _text(value, path), path)


def _exact_digest_bytes(
    value: Any,
    path: str,
    *,
    digest_admitter=digest_text,
    canonical_encoder=canonical_bytes,
    canonical_error_type=CanonicalError,
    contract_error_type=ProtocolContractError,
) -> bytes:
    """Admit one exact digest scalar and return comparison-safe bytes."""

    if type(value) is not str:
        raise contract_error_type(f"{path} must be exact digest text")
    try:
        digest_admitter(value, path)
        return canonical_encoder(value)
    except canonical_error_type as exc:
        raise contract_error_type(str(exc)) from exc


def _count(value: Any, path: str) -> int:
    if type(value) is not int or value < 0 or value > 1_000_000_000:
        raise ProtocolContractError(
            f"{path} must be a bounded non-negative integer")
    return value


def _frozen_map(value: Any, path: str, max_bytes: int) -> FrozenMap[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolContractError(f"{path} must be an object")
    admitted = _canonical(freeze, value)
    if type(admitted) is not FrozenMap:
        raise ProtocolContractError(f"{path} must become an exact FrozenMap")
    if len(_canonical(canonical_bytes, admitted)) > max_bytes:
        raise ProtocolContractError(f"{path} exceeds its canonical byte limit")
    return admitted


def _text_tuple(value: Any, path: str, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProtocolContractError(f"{path} must be an array of text")
    if len(value) > limit:
        raise ProtocolContractError(f"{path} exceeds its item limit")
    admitted = tuple(
        _text(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    )
    if len(admitted) != len(set(admitted)):
        raise ProtocolContractError(f"{path} contains duplicates")
    return tuple(sorted(admitted))


def _digest_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProtocolContractError(f"{path} must be an array of digests")
    if not value or len(value) > _MAX_RECEIPT_DIGESTS:
        raise ProtocolContractError(f"{path} has invalid cardinality")
    admitted = tuple(
        _digest(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    )
    if len(admitted) != len(set(admitted)):
        raise ProtocolContractError(f"{path} contains duplicates")
    return tuple(sorted(admitted))


def reject_model_authority_fields(value: Any, path: str = "arguments") -> None:
    """Reject identity/approval fields at every model-controlled object depth."""

    stack = [(value, path)]
    while stack:
        current, current_path = stack.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                if type(key) is not str:
                    raise ProtocolContractError(
                        f"{current_path} object keys must be exact text")
                expanded = re.sub(
                    r"(?<=[A-Za-z0-9])(?=[A-Z])", "_", key)
                normalized = re.sub(
                    r"[^A-Za-z0-9]+", "_", expanded).strip("_").casefold()
                compact = normalized.replace("_", "")
                parts = frozenset(normalized.split("_"))
                if (
                    normalized in _FORBIDDEN_MODEL_KEYS
                    or compact in _FORBIDDEN_MODEL_COMPACT_KEYS
                    or not parts.isdisjoint(_SENSITIVE_MODEL_KEY_PARTS)
                ):
                    raise ProtocolContractError(
                        f"model payload cannot set {current_path}.{key}")
                stack.append((item, f"{current_path}.{key}"))
        elif isinstance(current, (list, tuple)):
            for index, item in enumerate(current):
                stack.append((item, f"{current_path}[{index}]"))


@dataclass(frozen=True, slots=True)
class CoverageV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = COVERAGE_SCHEMA

    state: CoverageStateV0
    requested_items: int
    evaluated_items: int
    omitted: tuple[str, ...] | list[str] = ()
    failed: tuple[str, ...] | list[str] = ()
    _coverage_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.state) is not str or self.state not in _COVERAGE_STATES:
            raise ProtocolContractError("coverage.state is unsupported")
        requested = _count(self.requested_items, "coverage.requested.items")
        evaluated = _count(self.evaluated_items, "coverage.evaluated.items")
        if evaluated > requested:
            raise ProtocolContractError("coverage evaluated exceeds requested")
        omitted = _text_tuple(
            self.omitted, "coverage.omitted", limit=_MAX_COVERAGE_ENTRIES)
        failed = _text_tuple(
            self.failed, "coverage.failed", limit=_MAX_COVERAGE_ENTRIES)
        if self.state == "COMPLETE" and (
            evaluated != requested or omitted or failed
        ):
            raise ProtocolContractError(
                "COMPLETE coverage requires exact accounting and no gaps")
        if self.state in {"NOT_EVALUATED", "REFUSED"} and evaluated != 0:
            raise ProtocolContractError(
                f"{self.state} coverage cannot report evaluated items")
        object.__setattr__(self, "requested_items", requested)
        object.__setattr__(self, "evaluated_items", evaluated)
        object.__setattr__(self, "omitted", omitted)
        object.__setattr__(self, "failed", failed)
        if len(_canonical(canonical_bytes, self.to_data())) > _MAX_COVERAGE_BYTES:
            raise ProtocolContractError(
                "coverage exceeds its canonical byte limit")
        object.__setattr__(
            self,
            "_coverage_digest",
            canonical_digest("kir.ai-protocol-coverage.v0", self.to_data()),
        )

    @classmethod
    def complete(cls, items: int = 1) -> "CoverageV0":
        return cls("COMPLETE", items, items)

    @classmethod
    def refused(cls, reason: str) -> "CoverageV0":
        return cls("REFUSED", 1, 0, failed=(reason,))

    @property
    def coverage_digest(self) -> str:
        return self._coverage_digest

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "state": self.state,
            "requested": {"items": self.requested_items},
            "evaluated": {"items": self.evaluated_items},
            "omitted": self.omitted,
            "failed": self.failed,
        }


@dataclass(frozen=True, slots=True)
class ProtocolErrorV0(ProtocolContractV0):
    SCHEMA: ClassVar[str] = ERROR_SCHEMA

    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = _text(self.code, "error.code", max_length=128)
        if _ERROR_CODE_RE.fullmatch(code) is None:
            raise ProtocolContractError("error.code must be an uppercase symbol")
        message = _text(self.message, "error.message")
        if type(self.retryable) is not bool:
            raise ProtocolContractError("error.retryable must be exact bool")
        details = _frozen_map(self.details, "error.details", _MAX_DETAIL_BYTES)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", details)

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ReadReceiptV0(ProtocolContractV0):
    """Pure value shape; AP-01 does not issue authoritative project reads."""

    SCHEMA: ClassVar[str] = READ_RECEIPT_SCHEMA

    request_id: str
    tool: str
    project_id: str
    revision_digest: str
    request_digest: str
    result_digests: tuple[str, ...] | list[str]
    coverage: CoverageV0
    schema_registry_digest: str
    continuation: str | None = None
    _receipt_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        request_id = _identifier(self.request_id, "read_receipt.request_id")
        tool = _identifier(self.tool, "read_receipt.tool")
        if tool not in DECLARED_TOOL_NAMES:
            raise ProtocolContractError("read_receipt.tool is not declared")
        project_id = _identifier(self.project_id, "read_receipt.project_id")
        revision_digest = _digest(
            self.revision_digest, "read_receipt.revision_digest")
        request_digest = _digest(
            self.request_digest, "read_receipt.request_digest")
        result_digests = _digest_tuple(
            self.result_digests, "read_receipt.result_digests")
        if type(self.coverage) is not CoverageV0:
            raise ProtocolContractError("read_receipt.coverage has wrong type")
        schema_registry_digest = _digest(
            self.schema_registry_digest,
            "read_receipt.schema_registry_digest",
        )
        continuation = (
            None
            if self.continuation is None
            else _text(
                self.continuation,
                "read_receipt.continuation",
                max_length=1_024,
            )
        )
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "revision_digest", revision_digest)
        object.__setattr__(self, "request_digest", request_digest)
        object.__setattr__(self, "result_digests", result_digests)
        object.__setattr__(
            self, "schema_registry_digest", schema_registry_digest)
        object.__setattr__(self, "continuation", continuation)
        object.__setattr__(
            self,
            "_receipt_digest",
            canonical_digest("kir.ai-read-receipt.v0", self._body_data()),
        )

    @property
    def receipt_digest(self) -> str:
        return self._receipt_digest

    def _body_data(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "tool": self.tool,
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
            "request_digest": self.request_digest,
            "result_digests": self.result_digests,
            "coverage": self.coverage.to_data(),
            "schema_registry_digest": self.schema_registry_digest,
            "continuation": self.continuation,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._body_data(), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class ToolRequestV0(ProtocolContractV0):
    request_id: str
    tool: str
    arguments: Mapping[str, Any]
    _request_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        request_id = _identifier(self.request_id, "request_id")
        tool = _identifier(self.tool, "tool")
        if tool not in DECLARED_TOOL_NAMES:
            raise ProtocolContractError(f"unknown tool {tool!r}")
        arguments = _frozen_map(
            self.arguments, "arguments", _MAX_ARGUMENT_BYTES)
        reject_model_authority_fields(arguments)
        if len(arguments) != 0:
            raise ProtocolContractError(
                f"{tool} has no admitted AP-01 arguments; "
                "expected exact empty object")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(
            self,
            "_request_digest",
            canonical_digest("kir.ai-tool-request.v0", self.to_data()),
        )

    @property
    def request_digest(self) -> str:
        return self._request_digest

    def to_data(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "tool": self.tool,
            "arguments": self.arguments,
        }


@dataclass(frozen=True, slots=True)
class ToolResponseV0(ProtocolContractV0):
    request_id: str
    tool: str
    status: ResponseStatusV0
    coverage: CoverageV0
    result: Mapping[str, Any] | None
    error: ProtocolErrorV0 | None
    read_receipt: ReadReceiptV0 | None = None
    _response_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _digest_encoder=_exact_digest_bytes) -> None:
        request_id = _identifier(self.request_id, "response.request_id")
        tool = _identifier(self.tool, "response.tool")
        if tool not in DECLARED_TOOL_NAMES:
            raise ProtocolContractError("response.tool is not declared")
        if type(self.status) is not str or self.status not in _RESPONSE_STATUSES:
            raise ProtocolContractError("response.status is unsupported")
        if type(self.coverage) is not CoverageV0:
            raise ProtocolContractError("response.coverage has wrong type")
        result = (
            None
            if self.result is None
            else _frozen_map(self.result, "response.result", _MAX_RESULT_BYTES)
        )
        if self.error is not None and type(self.error) is not ProtocolErrorV0:
            raise ProtocolContractError("response.error has wrong type")
        if (
            self.read_receipt is not None
            and type(self.read_receipt) is not ReadReceiptV0
        ):
            raise ProtocolContractError("response.read_receipt has wrong type")
        if self.status == "OK":
            if result is None or self.error is not None:
                raise ProtocolContractError("OK requires result and no error")
            if self.coverage.state == "REFUSED":
                raise ProtocolContractError("OK cannot carry REFUSED coverage")
            if tool not in AVAILABLE_TOOL_NAMES:
                raise ProtocolContractError(
                    "an unavailable AP-01 tool cannot return OK")
            if tool == CAPABILITIES_TOOL and (
                self.coverage.state != "COMPLETE"
                or self.coverage.requested_items != 1
                or self.coverage.evaluated_items != 1
            ):
                raise ProtocolContractError(
                    "capabilities.get OK requires COMPLETE 1-of-1 coverage")
        elif self.status == "REFUSED":
            if result is not None or self.error is None:
                raise ProtocolContractError("REFUSED requires only an error")
            if self.coverage.state != "REFUSED":
                raise ProtocolContractError(
                    "REFUSED status requires REFUSED coverage")
            if self.read_receipt is not None:
                raise ProtocolContractError("REFUSED cannot carry a read receipt")
        else:
            if result is not None or self.error is None:
                raise ProtocolContractError("FAILED requires only an error")
            if self.coverage.state in {"COMPLETE", "REFUSED"}:
                raise ProtocolContractError(
                    "FAILED requires non-COMPLETE non-REFUSED coverage")
            if self.read_receipt is not None:
                raise ProtocolContractError("FAILED cannot carry a read receipt")
        if self.read_receipt is not None:
            if self.read_receipt.request_id != request_id:
                raise ProtocolContractError(
                    "read receipt request_id does not match response")
            if self.read_receipt.tool != tool:
                raise ProtocolContractError(
                    "read receipt tool does not match response")
            if (
                _digest_encoder(
                    self.read_receipt.coverage.coverage_digest,
                    "response.read_receipt.coverage_digest",
                )
                != _digest_encoder(
                    self.coverage.coverage_digest,
                    "response.coverage_digest",
                )
            ):
                raise ProtocolContractError(
                    "read receipt coverage does not match response")
            if tool == CAPABILITIES_TOOL and self.status == "OK":
                raise ProtocolContractError(
                    "capabilities.get cannot carry a project read receipt")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "result", result)
        if len(_canonical(canonical_bytes, self.to_data())) > MAX_WIRE_BYTES:
            raise ProtocolContractError(
                "response exceeds the AP-01 wire byte limit")
        object.__setattr__(
            self,
            "_response_digest",
            canonical_digest("kir.ai-tool-response.v0", self.to_data()),
        )

    @property
    def response_digest(self) -> str:
        return self._response_digest

    def to_data(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "tool": self.tool,
            "status": self.status,
            "coverage": self.coverage.to_data(),
            "result": self.result,
            "error": None if self.error is None else self.error.to_data(),
            "read_receipt": (
                None
                if self.read_receipt is None
                else self.read_receipt.to_data()
            ),
        }


__all__ = [
    "AVAILABLE_TOOL_NAMES",
    "CAPABILITIES_ARGUMENTS_SCHEMA",
    "CAPABILITIES_RESULT_SCHEMA",
    "CAPABILITIES_TOOL",
    "COVERAGE_SCHEMA",
    "CoverageStateV0",
    "CoverageV0",
    "DECLARED_TOOL_NAMES",
    "ERROR_SCHEMA",
    "MAX_WIRE_BYTES",
    "ProtocolContractV0",
    "ProtocolErrorV0",
    "PROTOCOL_VERSION",
    "READ_RECEIPT_SCHEMA",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "ReadReceiptV0",
    "ResponseStatusV0",
    "ToolRequestV0",
    "ToolResponseV0",
    "WIRE_MILESTONE",
    "reject_model_authority_fields",
]
