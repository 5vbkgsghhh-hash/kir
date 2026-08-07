"""Immutable, exact-shape evidence contracts for AP03.

The contracts preserve transport evidence; they do not grant authority to an
actor label or to a stored report.  Verification replays every exchange.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import re
from typing import Any

from kukai.design_source import (
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)

from .schemas import (
    ACTORS,
    CASE_SCHEMA,
    MODEL_OUTPUT_SCHEMA,
    PROMPT_EVENT_SCHEMA,
    REPORT_SCHEMA,
    REPORT_STATUSES,
    RUN_HEADER_SCHEMA,
    SUITE_REPORT_SCHEMA,
    TERMINAL_STATES,
    TRANSCRIPT_SCHEMA,
    WIRE_EXCHANGE_SCHEMA,
)


_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class BenchmarkContractError(ValueError):
    """An AP03 evidence object is not exact."""


def sha256_bytes(blob: bytes) -> str:
    if type(blob) is not bytes:
        raise BenchmarkContractError("hash input must be exact bytes")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def b64url_encode(blob: bytes) -> str:
    if type(blob) is not bytes:
        raise BenchmarkContractError("base64 input must be exact bytes")
    return base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if type(text) is not str or not text or "=" in text:
        raise BenchmarkContractError("base64url must be non-empty and unpadded")
    try:
        blob = base64.b64decode(
            text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise BenchmarkContractError("base64url is invalid") from exc
    if b64url_encode(blob) != text:
        raise BenchmarkContractError("base64url is not canonical")
    return blob


def _identifier(value: Any, path: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise BenchmarkContractError(f"{path} must be an exact identifier")
    return value


def _digest(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise BenchmarkContractError(f"{path} must be exact sha256 text")
    return value


def _count(value: Any, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 1_000_000_000:
        raise BenchmarkContractError(f"{path} must be a bounded exact integer")
    return value


def _text(value: Any, path: str, *, maximum: int = 4_000_000) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise BenchmarkContractError(f"{path} must be bounded non-empty text")
    try:
        admitted = strict_json_loads(canonical_bytes(value))
    except Exception as exc:
        raise BenchmarkContractError(f"{path} is not canonical text") from exc
    if type(admitted) is not str:
        raise BenchmarkContractError(f"{path} did not remain text")
    return admitted


def _fresh(value: Any, path: str, *, maximum: int = 4_000_000) -> Any:
    try:
        blob = canonical_bytes(value)
        if len(blob) > maximum:
            raise BenchmarkContractError(f"{path} exceeds its byte limit")
        return strict_json_loads(blob)
    except BenchmarkContractError:
        raise
    except Exception as exc:
        raise BenchmarkContractError(f"{path} is not canonical JSON") from exc


def _object(value: Any, path: str, *, maximum: int = 4_000_000) -> FrozenMap:
    admitted = _fresh(value, path, maximum=maximum)
    if type(admitted) is not FrozenMap:
        raise BenchmarkContractError(f"{path} must be an exact object")
    return admitted


def _fields(data: Any, expected: frozenset[str], path: str) -> FrozenMap:
    admitted = _object(data, path)
    if set(admitted) != expected:
        raise BenchmarkContractError(f"{path} fields are not exact")
    return admitted


@dataclass(frozen=True, slots=True)
class BenchmarkCaseV0:
    case_id: str
    initial_source_digest: str
    initial_build_digest: str
    expected_final_source_digest: str
    expected_final_build_digest: str
    task: FrozenMap | dict[str, Any]
    limits: FrozenMap | dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        for name in (
            "initial_source_digest", "initial_build_digest",
            "expected_final_source_digest", "expected_final_build_digest",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "task", _object(self.task, "case.task"))
        object.__setattr__(self, "limits", _object(self.limits, "case.limits"))

    @property
    def case_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-case.v0", self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_final_build_digest": self.expected_final_build_digest,
            "expected_final_source_digest": self.expected_final_source_digest,
            "initial_build_digest": self.initial_build_digest,
            "initial_source_digest": self.initial_source_digest,
            "limits": self.limits,
            "schema": CASE_SCHEMA,
            "task": self.task,
        }

    @classmethod
    def from_data(cls, value: Any) -> "BenchmarkCaseV0":
        data = _fields(value, frozenset({
            "case_id", "expected_final_build_digest",
            "expected_final_source_digest", "initial_build_digest",
            "initial_source_digest", "limits", "schema", "task",
        }), "case")
        if data["schema"] != CASE_SCHEMA:
            raise BenchmarkContractError("case schema is not exact")
        result = cls(
            data["case_id"], data["initial_source_digest"],
            data["initial_build_digest"], data["expected_final_source_digest"],
            data["expected_final_build_digest"], data["task"], data["limits"],
        )
        if canonical_bytes(result.to_data()) != canonical_bytes(data):
            raise BenchmarkContractError("case did not round-trip exactly")
        return result


@dataclass(frozen=True, slots=True)
class RunHeaderV0:
    run_id: str
    case_id: str
    case_digest: str
    harness_version: str
    provider: str
    model: str
    model_fingerprint: str
    inference_config: FrozenMap | dict[str, Any]
    registry_digest: str

    def __post_init__(self) -> None:
        for name in ("run_id", "case_id", "provider", "model"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "harness_version", _text(
            self.harness_version, "harness_version", maximum=128))
        object.__setattr__(self, "model_fingerprint", _text(
            self.model_fingerprint, "model_fingerprint", maximum=4096))
        for name in ("case_digest", "registry_digest"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "inference_config", _object(
            self.inference_config, "inference_config"))

    @property
    def header_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-run-header.v0", self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "case_digest": self.case_digest,
            "case_id": self.case_id,
            "harness_version": self.harness_version,
            "inference_config": self.inference_config,
            "model": self.model,
            "model_fingerprint": self.model_fingerprint,
            "provider": self.provider,
            "registry_digest": self.registry_digest,
            "run_id": self.run_id,
            "schema": RUN_HEADER_SCHEMA,
        }

    @classmethod
    def from_data(cls, value: Any) -> "RunHeaderV0":
        expected = frozenset({
            "case_digest", "case_id", "harness_version", "inference_config",
            "model", "model_fingerprint", "provider", "registry_digest",
            "run_id", "schema",
        })
        data = _fields(value, expected, "run_header")
        if data["schema"] != RUN_HEADER_SCHEMA:
            raise BenchmarkContractError("run header schema is not exact")
        result = cls(*(data[name] for name in (
            "run_id", "case_id", "case_digest", "harness_version", "provider",
            "model", "model_fingerprint", "inference_config", "registry_digest",
        )))
        if canonical_bytes(result.to_data()) != canonical_bytes(data):
            raise BenchmarkContractError("run header did not round-trip")
        return result


@dataclass(frozen=True, slots=True)
class PromptEventV0:
    invocation: int
    prompt_text: str
    visible_exchange_seqs: tuple[int, ...] | list[int]

    def __post_init__(self) -> None:
        _count(self.invocation, "prompt.invocation", minimum=1)
        object.__setattr__(self, "prompt_text", _text(
            self.prompt_text, "prompt.prompt_text"))
        seqs = tuple(self.visible_exchange_seqs)
        if any(type(item) is not int or item < 1 for item in seqs):
            raise BenchmarkContractError("prompt visible seqs are invalid")
        if tuple(sorted(set(seqs))) != seqs:
            raise BenchmarkContractError("prompt visible seqs must be unique/sorted")
        object.__setattr__(self, "visible_exchange_seqs", seqs)

    def to_data(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation,
            "prompt_text": self.prompt_text,
            "schema": PROMPT_EVENT_SCHEMA,
            "visible_exchange_seqs": self.visible_exchange_seqs,
        }

    @classmethod
    def from_data(cls, value: Any) -> "PromptEventV0":
        data = _fields(value, frozenset({
            "invocation", "prompt_text", "schema", "visible_exchange_seqs",
        }), "prompt_event")
        if data["schema"] != PROMPT_EVENT_SCHEMA or type(data["visible_exchange_seqs"]) is not tuple:
            raise BenchmarkContractError("prompt event shape is not exact")
        return cls(data["invocation"], data["prompt_text"], data["visible_exchange_seqs"])


@dataclass(frozen=True, slots=True)
class ModelOutputV0:
    invocation: int
    raw_output_json: str
    raw_output_sha256: str
    request_json: str
    request_sha256: str

    def __post_init__(self) -> None:
        _count(self.invocation, "model_output.invocation", minimum=1)
        for name in ("raw_output_json", "request_json"):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"model_output.{name}"))
        raw = self.raw_output_json.encode("utf-8")
        request = self.request_json.encode("utf-8")
        if _digest(self.raw_output_sha256, "raw_output_sha256") != sha256_bytes(raw):
            raise BenchmarkContractError("raw model output hash mismatch")
        if _digest(self.request_sha256, "request_sha256") != sha256_bytes(request):
            raise BenchmarkContractError("model request hash mismatch")

    @classmethod
    def admit_raw(cls, invocation: int, raw_output_json: str) -> "ModelOutputV0":
        _count(invocation, "model_output.invocation", minimum=1)
        raw_output_json = _text(raw_output_json, "raw_output_json")
        try:
            data = strict_json_loads(raw_output_json.encode("utf-8"))
        except Exception as exc:
            raise BenchmarkContractError("raw model output is not strict JSON") from exc
        if type(data) is not FrozenMap or set(data) != {"request_json", "schema"}:
            raise BenchmarkContractError("raw model output fields are not exact")
        if data["schema"] != MODEL_OUTPUT_SCHEMA:
            raise BenchmarkContractError("raw model output schema is not exact")
        request_json = _text(data["request_json"], "request_json")
        return cls(
            invocation,
            raw_output_json,
            sha256_bytes(raw_output_json.encode("utf-8")),
            request_json,
            sha256_bytes(request_json.encode("utf-8")),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation,
            "raw_output_json": self.raw_output_json,
            "raw_output_sha256": self.raw_output_sha256,
            "request_json": self.request_json,
            "request_sha256": self.request_sha256,
            "schema": MODEL_OUTPUT_SCHEMA,
        }

    @classmethod
    def from_data(cls, value: Any) -> "ModelOutputV0":
        data = _fields(value, frozenset({
            "invocation", "raw_output_json", "raw_output_sha256",
            "request_json", "request_sha256", "schema",
        }), "model_output")
        if data["schema"] != MODEL_OUTPUT_SCHEMA:
            raise BenchmarkContractError("model output schema is not exact")
        result = cls(*(data[name] for name in (
            "invocation", "raw_output_json", "raw_output_sha256",
            "request_json", "request_sha256",
        )))
        admitted = cls.admit_raw(result.invocation, result.raw_output_json)
        if canonical_bytes(admitted.to_data()) != canonical_bytes(result.to_data()):
            raise BenchmarkContractError("stored request differs from raw model output")
        return result


@dataclass(frozen=True, slots=True)
class WireExchangeV0:
    seq: int
    actor: str
    model_visible: bool
    provider_invocation: int | None
    request_b64url: str
    request_sha256: str
    request_bytes: int
    response_b64url: str
    response_sha256: str
    response_bytes: int
    before_state_digest: str
    after_state_digest: str
    previous_exchange_digest: str | None

    def __post_init__(self) -> None:
        _count(self.seq, "exchange.seq", minimum=1)
        if self.actor not in ACTORS:
            raise BenchmarkContractError("exchange actor is unsupported")
        if type(self.model_visible) is not bool:
            raise BenchmarkContractError("model_visible must be exact bool")
        if self.actor == "MODEL":
            _count(self.provider_invocation, "provider_invocation", minimum=1)
        elif self.provider_invocation is not None:
            raise BenchmarkContractError("environment exchange has no invocation")
        request = b64url_decode(self.request_b64url)
        response = b64url_decode(self.response_b64url)
        if _digest(self.request_sha256, "request_sha256") != sha256_bytes(request):
            raise BenchmarkContractError("request hash mismatch")
        if _digest(self.response_sha256, "response_sha256") != sha256_bytes(response):
            raise BenchmarkContractError("response hash mismatch")
        if _count(self.request_bytes, "request_bytes", minimum=1) != len(request):
            raise BenchmarkContractError("request byte count mismatch")
        if _count(self.response_bytes, "response_bytes", minimum=1) != len(response):
            raise BenchmarkContractError("response byte count mismatch")
        for name in ("before_state_digest", "after_state_digest"):
            _digest(getattr(self, name), name)
        _digest(self.previous_exchange_digest, "previous_exchange_digest", nullable=True)

    @property
    def request_blob(self) -> bytes:
        return b64url_decode(self.request_b64url)

    @property
    def response_blob(self) -> bytes:
        return b64url_decode(self.response_b64url)

    def body_data(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "after_state_digest": self.after_state_digest,
            "before_state_digest": self.before_state_digest,
            "model_visible": self.model_visible,
            "previous_exchange_digest": self.previous_exchange_digest,
            "provider_invocation": self.provider_invocation,
            "request_b64url": self.request_b64url,
            "request_bytes": self.request_bytes,
            "request_sha256": self.request_sha256,
            "response_b64url": self.response_b64url,
            "response_bytes": self.response_bytes,
            "response_sha256": self.response_sha256,
            "schema": WIRE_EXCHANGE_SCHEMA,
            "seq": self.seq,
        }

    @property
    def exchange_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-wire-exchange.v0", self.body_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.body_data(), "exchange_digest": self.exchange_digest}

    @classmethod
    def create(
        cls, *, seq: int, actor: str, model_visible: bool,
        provider_invocation: int | None, request: bytes, response: bytes,
        before_state_digest: str, after_state_digest: str,
        previous_exchange_digest: str | None,
    ) -> "WireExchangeV0":
        return cls(
            seq, actor, model_visible, provider_invocation,
            b64url_encode(request), sha256_bytes(request), len(request),
            b64url_encode(response), sha256_bytes(response), len(response),
            before_state_digest, after_state_digest, previous_exchange_digest,
        )

    @classmethod
    def from_data(cls, value: Any) -> "WireExchangeV0":
        expected = frozenset({
            "actor", "after_state_digest", "before_state_digest",
            "exchange_digest", "model_visible", "previous_exchange_digest",
            "provider_invocation", "request_b64url", "request_bytes",
            "request_sha256", "response_b64url", "response_bytes",
            "response_sha256", "schema", "seq",
        })
        data = _fields(value, expected, "wire_exchange")
        if data["schema"] != WIRE_EXCHANGE_SCHEMA:
            raise BenchmarkContractError("exchange schema is not exact")
        result = cls(*(data[name] for name in (
            "seq", "actor", "model_visible", "provider_invocation",
            "request_b64url", "request_sha256", "request_bytes",
            "response_b64url", "response_sha256", "response_bytes",
            "before_state_digest", "after_state_digest",
            "previous_exchange_digest",
        )))
        if data["exchange_digest"] != result.exchange_digest:
            raise BenchmarkContractError("exchange digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class TranscriptV0:
    case: BenchmarkCaseV0
    header: RunHeaderV0
    prompts: tuple[PromptEventV0, ...] | list[PromptEventV0]
    model_outputs: tuple[ModelOutputV0, ...] | list[ModelOutputV0]
    exchanges: tuple[WireExchangeV0, ...] | list[WireExchangeV0]
    terminal_state: str

    def __post_init__(self) -> None:
        if type(self.case) is not BenchmarkCaseV0 or type(self.header) is not RunHeaderV0:
            raise BenchmarkContractError("transcript children have wrong type")
        if self.header.case_id != self.case.case_id or self.header.case_digest != self.case.case_digest:
            raise BenchmarkContractError("transcript case/header binding mismatch")
        prompts = tuple(self.prompts)
        outputs = tuple(self.model_outputs)
        exchanges = tuple(self.exchanges)
        if any(type(item) is not PromptEventV0 for item in prompts):
            raise BenchmarkContractError("transcript prompt type mismatch")
        if any(type(item) is not ModelOutputV0 for item in outputs):
            raise BenchmarkContractError("transcript model output type mismatch")
        if any(type(item) is not WireExchangeV0 for item in exchanges):
            raise BenchmarkContractError("transcript exchange type mismatch")
        if self.terminal_state not in TERMINAL_STATES:
            raise BenchmarkContractError("terminal state is unsupported")
        object.__setattr__(self, "prompts", prompts)
        object.__setattr__(self, "model_outputs", outputs)
        object.__setattr__(self, "exchanges", exchanges)

    @property
    def transcript_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-transcript.v0", self.body_data())

    def body_data(self) -> dict[str, Any]:
        return {
            "case": self.case.to_data(),
            "exchanges": tuple(item.to_data() for item in self.exchanges),
            "header": self.header.to_data(),
            "model_outputs": tuple(item.to_data() for item in self.model_outputs),
            "prompts": tuple(item.to_data() for item in self.prompts),
            "schema": TRANSCRIPT_SCHEMA,
            "terminal_state": self.terminal_state,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.body_data(), "transcript_digest": self.transcript_digest}

    @classmethod
    def from_data(cls, value: Any) -> "TranscriptV0":
        data = _fields(value, frozenset({
            "case", "exchanges", "header", "model_outputs", "prompts",
            "schema", "terminal_state", "transcript_digest",
        }), "transcript")
        if data["schema"] != TRANSCRIPT_SCHEMA:
            raise BenchmarkContractError("transcript schema is not exact")
        for name in ("prompts", "model_outputs", "exchanges"):
            if type(data[name]) is not tuple:
                raise BenchmarkContractError(f"transcript {name} must be an array")
        result = cls(
            BenchmarkCaseV0.from_data(data["case"]),
            RunHeaderV0.from_data(data["header"]),
            tuple(PromptEventV0.from_data(item) for item in data["prompts"]),
            tuple(ModelOutputV0.from_data(item) for item in data["model_outputs"]),
            tuple(WireExchangeV0.from_data(item) for item in data["exchanges"]),
            data["terminal_state"],
        )
        if data["transcript_digest"] != result.transcript_digest:
            raise BenchmarkContractError("transcript digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class BenchmarkReportV0:
    run_id: str
    transcript_digest: str
    status: str
    final_state_digest: str
    final_source_digest: str
    final_build_digest: str
    model_attempts: int
    cumulative_request_bytes: int
    model_visible_response_bytes: int
    unique_build_entities: int
    oracle: FrozenMap | dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _identifier(self.run_id, "report.run_id"))
        for name in (
            "transcript_digest", "final_state_digest", "final_source_digest",
            "final_build_digest",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if self.status not in REPORT_STATUSES:
            raise BenchmarkContractError("report status is unsupported")
        for name in (
            "model_attempts", "cumulative_request_bytes",
            "model_visible_response_bytes", "unique_build_entities",
        ):
            _count(getattr(self, name), f"report.{name}")
        object.__setattr__(self, "oracle", _object(self.oracle, "report.oracle"))

    @property
    def report_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-report.v0", self.body_data())

    def body_data(self) -> dict[str, Any]:
        return {
            "cumulative_request_bytes": self.cumulative_request_bytes,
            "final_build_digest": self.final_build_digest,
            "final_source_digest": self.final_source_digest,
            "final_state_digest": self.final_state_digest,
            "model_attempts": self.model_attempts,
            "model_visible_response_bytes": self.model_visible_response_bytes,
            "oracle": self.oracle,
            "run_id": self.run_id,
            "schema": REPORT_SCHEMA,
            "status": self.status,
            "transcript_digest": self.transcript_digest,
            "unique_build_entities": self.unique_build_entities,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.body_data(), "report_digest": self.report_digest}

    @classmethod
    def from_data(cls, value: Any) -> "BenchmarkReportV0":
        expected = frozenset({
            "cumulative_request_bytes", "final_build_digest",
            "final_source_digest", "final_state_digest", "model_attempts",
            "model_visible_response_bytes", "oracle", "report_digest",
            "run_id", "schema", "status", "transcript_digest",
            "unique_build_entities",
        })
        data = _fields(value, expected, "report")
        if data["schema"] != REPORT_SCHEMA:
            raise BenchmarkContractError("report schema is not exact")
        result = cls(*(data[name] for name in (
            "run_id", "transcript_digest", "status", "final_state_digest",
            "final_source_digest", "final_build_digest", "model_attempts",
            "cumulative_request_bytes", "model_visible_response_bytes",
            "unique_build_entities", "oracle",
        )))
        if data["report_digest"] != result.report_digest:
            raise BenchmarkContractError("report digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteReportV0:
    reports: tuple[BenchmarkReportV0, ...] | list[BenchmarkReportV0]

    def __post_init__(self) -> None:
        reports = tuple(self.reports)
        if not reports or any(type(item) is not BenchmarkReportV0 for item in reports):
            raise BenchmarkContractError("suite reports are invalid")
        if len({item.run_id for item in reports}) != len(reports):
            raise BenchmarkContractError("suite has duplicate run_id")
        object.__setattr__(self, "reports", reports)

    @property
    def suite_digest(self) -> str:
        return canonical_digest("kir.ai-authoring-benchmark-suite-report.v0", self.body_data())

    def body_data(self) -> dict[str, Any]:
        return {
            "reports": tuple(item.to_data() for item in self.reports),
            "schema": SUITE_REPORT_SCHEMA,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.body_data(), "suite_digest": self.suite_digest}

    @classmethod
    def from_data(cls, value: Any) -> "BenchmarkSuiteReportV0":
        data = _fields(
            value, frozenset({"reports", "schema", "suite_digest"}), "suite")
        if data["schema"] != SUITE_REPORT_SCHEMA or type(data["reports"]) is not tuple:
            raise BenchmarkContractError("suite shape/schema is not exact")
        result = cls(tuple(BenchmarkReportV0.from_data(item) for item in data["reports"]))
        if data["suite_digest"] != result.suite_digest:
            raise BenchmarkContractError("suite digest mismatch")
        return result


__all__ = [
    "BenchmarkCaseV0", "BenchmarkContractError", "BenchmarkReportV0",
    "BenchmarkSuiteReportV0", "ModelOutputV0", "PromptEventV0",
    "RunHeaderV0", "TranscriptV0", "WireExchangeV0", "b64url_decode",
    "b64url_encode", "sha256_bytes",
]
