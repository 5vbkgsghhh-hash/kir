"""Synchronous stateful host for the isolated AP02-W offline fixture."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kukai.ai_protocol.project_v0 import (
    CoverageV0,
    ModelQueryCommandV0,
    PatchContradictionError,
    ProjectConflictError,
    ProjectKernelError,
    ProjectReadCommandV0,
    ProjectStateV0,
    SourcePatchCommandV0,
    create_project_state,
    model_query,
    parse_model_query_command,
    parse_project_read_command,
    parse_source_patch_command,
    project_read,
    source_patch,
)
from kukai.design_source import (
    SourceRevisionV0,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)

from .contracts import (
    AVAILABLE_TOOL_NAMES,
    CAPABILITIES_TOOL,
    MODEL_QUERY_TOOL,
    PROJECT_READ_TOOL,
    SOURCE_PATCH_TOOL,
    WireCoverageV0,
    WireErrorV0,
    WireRequestV0,
    WireResponseV0,
)
from .errors import AddressableRequestError, WireContractError
from .registry import CAPABILITY_REGISTRY
from .result_codec import (
    parse_model_query_result,
    parse_project_read_result,
    parse_source_patch_result,
)
from .wire import (
    _make_response_encoder,
    decode_request,
    decode_response,
)


_CREATE_PROJECT_STATE = create_project_state
_PARSE_PROJECT_READ = parse_project_read_command
_PARSE_MODEL_QUERY = parse_model_query_command
_PARSE_SOURCE_PATCH = parse_source_patch_command
_PROJECT_READ = project_read
_MODEL_QUERY = model_query
_SOURCE_PATCH = source_patch

_CAPTURED_REQUEST_DECODER = decode_request
_CAPTURED_RESPONSE_DECODER = decode_response
_CAPTURED_RESPONSE_ENCODER = _make_response_encoder(
    _CAPTURED_RESPONSE_DECODER)
_PACKAGED_REGISTRY_BYTES = canonical_bytes(CAPABILITY_REGISTRY.to_data())

_UNAVAILABLE_ERROR_BYTES = tuple(sorted(
    (item["name"], canonical_bytes(WireErrorV0(
        item["reason_code"],
        "declared tool is unavailable in the offline project V0 fixture",
        False,
        {"tool": item["name"]},
    ).to_data()))
    for item in CAPABILITY_REGISTRY.to_data()["tools"]
    if item["availability"] == "UNAVAILABLE"
))
_FAILED_ERROR_BYTES = canonical_bytes(WireErrorV0(
    "INTERNAL_FAILURE",
    "offline fixture request failed unexpectedly",
    False,
    {},
).to_data())


@dataclass(frozen=True, slots=True)
class _SessionCodecs:
    request_decoder: Callable[[bytes], WireRequestV0]
    response_encoder: Callable[[WireResponseV0], bytes]
    response_decoder: Callable[[bytes], WireResponseV0]


@dataclass(frozen=True, slots=True)
class _SessionHandlers:
    parse_read: Callable[[Any], ProjectReadCommandV0]
    parse_query: Callable[[Any], ModelQueryCommandV0]
    parse_patch: Callable[[Any], SourcePatchCommandV0]
    read: Callable[[ProjectStateV0, ProjectReadCommandV0], Any]
    query: Callable[[ProjectStateV0, ModelQueryCommandV0], Any]
    patch: Callable[[ProjectStateV0, SourcePatchCommandV0], Any]


_CAPTURED_CODECS = _SessionCodecs(
    _CAPTURED_REQUEST_DECODER,
    _CAPTURED_RESPONSE_ENCODER,
    _CAPTURED_RESPONSE_DECODER,
)
_CAPTURED_HANDLERS = _SessionHandlers(
    _PARSE_PROJECT_READ,
    _PARSE_MODEL_QUERY,
    _PARSE_SOURCE_PATCH,
    _PROJECT_READ,
    _MODEL_QUERY,
    _SOURCE_PATCH,
)


def _make_trusted_transition_verifier(
    parse_read: Callable[[Any], ProjectReadCommandV0],
    parse_query: Callable[[Any], ModelQueryCommandV0],
    parse_patch: Callable[[Any], SourcePatchCommandV0],
    read: Callable[[ProjectStateV0, ProjectReadCommandV0], Any],
    query: Callable[[ProjectStateV0, ModelQueryCommandV0], Any],
    patch: Callable[[ProjectStateV0, SourcePatchCommandV0], Any],
) -> Callable[[ProjectStateV0, WireRequestV0], tuple[Any, Any]]:
    """Capture a non-injectable K oracle for candidate verification."""

    def verify(
        snapshot: ProjectStateV0,
        request: WireRequestV0,
    ) -> tuple[Any, Any]:
        if request.tool == PROJECT_READ_TOOL:
            command = parse_read(request.arguments)
            return command, read(snapshot, command)
        if request.tool == MODEL_QUERY_TOOL:
            command = parse_query(request.arguments)
            return command, query(snapshot, command)
        if request.tool == SOURCE_PATCH_TOOL:
            command = parse_patch(request.arguments)
            return command, patch(snapshot, command)
        raise WireContractError("trusted K verifier received a non-K tool")

    return verify


_VERIFY_TRUSTED_TRANSITION = _make_trusted_transition_verifier(
    _PARSE_PROJECT_READ,
    _PARSE_MODEL_QUERY,
    _PARSE_SOURCE_PATCH,
    _PROJECT_READ,
    _MODEL_QUERY,
    _SOURCE_PATCH,
)


def _fresh_error(payload: bytes) -> WireErrorV0:
    data = strict_json_loads(payload)
    return WireErrorV0(
        data["code"],
        data["message"],
        data["retryable"],
        data["details"],
    )


def _unavailable_error(tool: str) -> WireErrorV0:
    for candidate, payload in _UNAVAILABLE_ERROR_BYTES:
        if candidate == tool:
            return _fresh_error(payload)
    raise WireContractError("unavailable tool escaped the packaged matrix")


def _safe_error(error: Any, fallback_message: str) -> WireErrorV0:
    code = error.code
    message = str(error)
    details = getattr(error, "details", {})
    try:
        return WireErrorV0(code, message, False, details)
    except Exception:
        return WireErrorV0(code, fallback_message, False, {})


def _error_response(
    request_id: str,
    tool: str,
    status: str,
    error: WireErrorV0,
) -> WireResponseV0:
    coverage = (
        WireCoverageV0.refused(1)
        if status == "REFUSED"
        else WireCoverageV0.not_evaluated(1)
    )
    return WireResponseV0(
        request_id=request_id,
        tool=tool,
        status=status,
        coverage=coverage,
        result=None,
        error=error,
        read_receipt=None,
    )


def _same_value(left: Any, right: Any, path: str) -> None:
    if canonical_bytes(left) != canonical_bytes(right):
        raise WireContractError(f"{path} is not canonically exact")


def _same_contract(left: Any, right: Any, path: str) -> None:
    _same_value(left.to_data(), right.to_data(), path)


def _build_index_projection(state: ProjectStateV0) -> dict[str, Any]:
    index = state.build_index
    summary = index.summary()
    return {
        "build_digest": index.build_digest,
        "by_logical_id": {
            logical_id: entity.to_data()
            for logical_id, entity in index._by_id.items()
        },
        "counts_by_semantic_type": summary.counts_by_semantic_type,
        "entities": tuple(entity.to_data() for entity in index.entities),
        "entity_ids": index.entity_ids,
        "summary_build_digest": summary.build_digest,
        "summary_entity_count": summary.entity_count,
    }


def _require_trusted_transition(
    candidate: ProjectStateV0,
    command: Any,
    actual_result: Any,
    trusted_command: Any,
    trusted_transition: Any,
) -> None:
    if type(command) is not type(trusted_command):
        raise WireContractError("dispatched/trusted command type mismatch")
    _same_contract(command, trusted_command, "dispatched/trusted command")
    if type(trusted_transition.state) is not ProjectStateV0:
        raise WireContractError("trusted K transition has wrong state type")
    if type(candidate) is not type(trusted_transition.state):
        raise WireContractError("candidate/trusted state type mismatch")
    _same_value(
        candidate.to_data(),
        trusted_transition.state.to_data(),
        "candidate/trusted state",
    )
    _same_value(
        _build_index_projection(candidate),
        _build_index_projection(trusted_transition.state),
        "candidate/trusted build index",
    )
    if type(actual_result) is not type(trusted_transition.result):
        raise WireContractError("actual/trusted result type mismatch")
    _same_contract(
        actual_result,
        trusted_transition.result,
        "actual/trusted result",
    )


def _expected_ledger(
    before: tuple[Any, ...],
    emitted: Any,
    identity_attribute: str,
    path: str,
) -> tuple[Any, ...]:
    identity = getattr(emitted, identity_attribute)
    existing = next(
        (item for item in before
         if getattr(item, identity_attribute) == identity),
        None,
    )
    if existing is not None:
        _same_contract(existing, emitted, f"{path} retained identity")
        return before
    return (*before, emitted)


def _require_ledger(
    actual: tuple[Any, ...],
    expected: tuple[Any, ...],
    path: str,
) -> None:
    _same_value(
        tuple(item.to_data() for item in actual),
        tuple(item.to_data() for item in expected),
        path,
    )


class OfflineProjectWireV0:
    """One synchronous, offline-only pointer to immutable AP02-K state."""

    __slots__ = (
        "_active",
        "_codecs",
        "_handlers",
        "_state",
    )

    def __init__(self, state: ProjectStateV0):
        self._initialize(state, _CAPTURED_CODECS, _CAPTURED_HANDLERS)

    def _initialize(
        self,
        state: ProjectStateV0,
        codecs: _SessionCodecs,
        handlers: _SessionHandlers,
    ) -> None:
        if type(state) is not ProjectStateV0:
            raise WireContractError(
                "OfflineProjectWireV0 requires exact ProjectStateV0")
        if type(codecs) is not _SessionCodecs:
            raise WireContractError("session codecs have wrong concrete type")
        if type(handlers) is not _SessionHandlers:
            raise WireContractError("session handlers have wrong concrete type")
        self._state = state
        self._codecs = codecs
        self._handlers = handlers
        self._active = False

    @classmethod
    def from_source(cls, source: SourceRevisionV0) -> "OfflineProjectWireV0":
        if type(source) is not SourceRevisionV0:
            raise WireContractError(
                "OfflineProjectWireV0.from_source requires exact SourceRevisionV0")
        return cls(_CREATE_PROJECT_STATE(source))

    @property
    def state(self) -> ProjectStateV0:
        return self._state

    @property
    def state_digest(self) -> str:
        return self._state.state_digest

    def _dispatch_success(
        self,
        snapshot: ProjectStateV0,
        request: WireRequestV0,
    ) -> tuple[ProjectStateV0, Any, Any, WireResponseV0]:
        tool = request.tool
        if tool == CAPABILITIES_TOOL:
            result = strict_json_loads(_PACKAGED_REGISTRY_BYTES)
            response = WireResponseV0(
                request.request_id,
                tool,
                "OK",
                WireCoverageV0.complete(1),
                result,
                None,
                None,
            )
            return snapshot, None, result, response
        if tool == PROJECT_READ_TOOL:
            command = self._handlers.parse_read(request.arguments)
            transition = self._handlers.read(snapshot, command)
            result = transition.result
            coverage = WireCoverageV0(
                result.coverage.state,
                result.coverage.requested,
                result.coverage.evaluated,
                result.coverage.returned,
            )
            response = WireResponseV0(
                request.request_id,
                tool,
                "OK",
                coverage,
                result.to_data(),
                None,
                result.receipt.to_data(),
            )
            return transition.state, command, result, response
        if tool == MODEL_QUERY_TOOL:
            command = self._handlers.parse_query(request.arguments)
            transition = self._handlers.query(snapshot, command)
            result = transition.result
            coverage = WireCoverageV0(
                result.coverage.state,
                result.coverage.requested,
                result.coverage.evaluated,
                result.coverage.returned,
            )
            response = WireResponseV0(
                request.request_id,
                tool,
                "OK",
                coverage,
                result.to_data(),
                None,
                result.receipt.to_data(),
            )
            return transition.state, command, result, response
        if tool == SOURCE_PATCH_TOOL:
            command = self._handlers.parse_patch(request.arguments)
            transition = self._handlers.patch(snapshot, command)
            result = transition.result
            response = WireResponseV0(
                request.request_id,
                tool,
                "OK",
                WireCoverageV0.complete(1),
                result.to_data(),
                None,
                None,
            )
            return transition.state, command, result, response
        raise WireContractError("unavailable tool reached K dispatch")

    @staticmethod
    def _require_read_query_core(
        snapshot: ProjectStateV0,
        candidate: ProjectStateV0,
    ) -> None:
        if (
            candidate.project_id != snapshot.project_id
            or candidate.head is not snapshot.head
            or candidate.build is not snapshot.build
            or candidate.build_index is not snapshot.build_index
        ):
            raise WireContractError("read/query candidate changed the project core")
        _require_ledger(
            candidate.revisions, snapshot.revisions, "candidate revisions")
        _require_ledger(
            candidate.patch_outcomes,
            snapshot.patch_outcomes,
            "candidate patch outcomes",
        )

    @staticmethod
    def _require_actual_result(
        actual_result: Any,
        response: WireResponseV0,
    ) -> None:
        if response.result is None:
            raise WireContractError("OK candidate response lost its result")
        _same_value(
            actual_result.to_data(),
            response.result,
            "actual transition/response result",
        )

    def _validate_read_candidate(
        self,
        snapshot: ProjectStateV0,
        candidate: ProjectStateV0,
        command: ProjectReadCommandV0,
        actual_result: Any,
        response: WireResponseV0,
    ) -> None:
        self._require_actual_result(actual_result, response)
        result = parse_project_read_result(response.result)
        expected_selector = {}
        if command.scope == "module":
            expected_selector = {"module_id": command.target_id}
        elif command.scope == "exception":
            expected_selector = {"exception_id": command.target_id}
        if (
            command.project_id != snapshot.project_id
            or command.revision_digest != snapshot.head.revision_digest
            or result.project_id != command.project_id
            or result.revision_digest != command.revision_digest
            or result.build_digest != snapshot.build.manifest.build_digest
            or result.scope != command.scope
        ):
            raise WireContractError("project.read result/request binding failed")
        _same_value(
            result.selector,
            expected_selector,
            "project.read result/request selector",
        )
        self._require_read_query_core(snapshot, candidate)
        expected_receipts = _expected_ledger(
            snapshot.read_receipts,
            result.receipt,
            "receipt_id",
            "project.read receipt ledger",
        )
        _require_ledger(
            candidate.read_receipts,
            expected_receipts,
            "project.read candidate receipts",
        )
        _require_ledger(
            candidate.cursors,
            snapshot.cursors,
            "project.read candidate cursors",
        )

    def _validate_query_candidate(
        self,
        snapshot: ProjectStateV0,
        candidate: ProjectStateV0,
        command: ModelQueryCommandV0,
        actual_result: Any,
        response: WireResponseV0,
    ) -> None:
        self._require_actual_result(actual_result, response)
        result = parse_model_query_result(response.result)
        if (
            command.project_id != snapshot.project_id
            or command.revision_digest != snapshot.head.revision_digest
            or command.build_digest != snapshot.build.manifest.build_digest
            or result.project_id != command.project_id
            or result.revision_digest != command.revision_digest
            or result.build_digest != command.build_digest
            or result.scope != command.scope
        ):
            raise WireContractError("model.query result/request binding failed")
        _same_value(
            result.filters,
            command.filters,
            "model.query result/request filters",
        )
        if command.cursor is None:
            start_offset = 0
            previous_chain = canonical_digest(
                "kir.ai-model-query-chain-seed.v0",
                command.binding_data(),
            )
        else:
            prior = snapshot.cursor_map.get(command.cursor.cursor_id)
            if prior is None:
                raise WireContractError(
                    "model.query input cursor escaped snapshot ledger")
            _same_value(
                prior.ref.to_data(),
                command.cursor.to_data(),
                "model.query input cursor/snapshot record",
            )
            if (
                prior.project_id != command.project_id
                or prior.revision_digest != command.revision_digest
                or prior.build_digest != command.build_digest
                or prior.scope != command.scope
                or prior.limit != command.limit
            ):
                raise WireContractError(
                    "model.query input cursor binding failed")
            _same_value(
                prior.filters,
                command.filters,
                "model.query input cursor filters",
            )
            start_offset = prior.offset
            previous_chain = prior.chain_digest
        if command.scope == "summary":
            summary = snapshot.build_index.summary()
            records = ({
                "build_digest": summary.build_digest,
                "counts_by_semantic_type": summary.counts_by_semantic_type,
                "entity_count": summary.entity_count,
                "schema": summary.schema,
            },)
            requested = 1
        elif command.scope == "logical_id":
            entity = snapshot.build_index.by_logical_id(
                command.filters["logical_id"])
            records = (entity.to_data(),)
            requested = 1
        elif command.scope == "origin":
            indexed = snapshot.build_index.by_origin(**dict(
                command.filters.items()))
            records = tuple(item.to_data() for item in indexed.entities)
            requested = indexed.requested
        else:
            raise WireContractError("model.query scope escaped admission")
        if start_offset > len(records):
            raise WireContractError("model.query start offset exceeds exact records")
        end_offset = start_offset + len(result.items)
        if (
            end_offset > len(records)
            or len(result.items) > command.limit
            or (end_offset == start_offset and end_offset < len(records))
        ):
            raise WireContractError("model.query page extent is invalid")
        expected_items = records[start_offset:end_offset]
        partial = end_offset < len(records)
        _same_value(
            result.items,
            expected_items,
            "model.query exact indexed page",
        )
        expected_coverage = CoverageV0(
            "PARTIAL" if partial else "COMPLETE",
            requested,
            requested,
            len(expected_items),
        )
        _same_value(
            result.coverage.to_data(),
            expected_coverage.to_data(),
            "model.query exact indexed census",
        )
        if (result.cursor is None) != (not partial):
            raise WireContractError(
                "model.query cursor does not match exact terminal page")
        item_keys = tuple(
            item.get("logical_id", "summary") for item in result.items)
        expected_chain = canonical_digest("kir.ai-model-query-chain.v0", {
            "end_offset": end_offset,
            "item_keys": item_keys,
            "previous_chain_digest": previous_chain,
            "start_offset": start_offset,
        })
        if result.receipt.chain_digest != expected_chain:
            raise WireContractError("model.query result chain binding failed")
        self._require_read_query_core(snapshot, candidate)
        expected_receipts = _expected_ledger(
            snapshot.read_receipts,
            result.receipt,
            "receipt_id",
            "model.query receipt ledger",
        )
        _require_ledger(
            candidate.read_receipts,
            expected_receipts,
            "model.query candidate receipts",
        )

        if result.cursor is None:
            expected_cursors = snapshot.cursors
        else:
            cursor = candidate.cursor_map.get(result.cursor.cursor_id)
            if cursor is None:
                raise WireContractError(
                    "model.query cursor is absent from candidate ledger")
            _same_value(
                cursor.ref.to_data(),
                result.cursor.to_data(),
                "model.query cursor ref/candidate record",
            )
            if (
                cursor.project_id != command.project_id
                or cursor.revision_digest != command.revision_digest
                or cursor.build_digest != command.build_digest
                or cursor.scope != command.scope
                or cursor.limit != command.limit
                or cursor.offset != end_offset
                or cursor.chain_digest != result.receipt.chain_digest
            ):
                raise WireContractError(
                    "model.query candidate cursor binding failed")
            _same_value(
                cursor.filters,
                command.filters,
                "model.query candidate cursor filters",
            )
            expected_cursors = _expected_ledger(
                snapshot.cursors,
                cursor,
                "cursor_id",
                "model.query cursor ledger",
            )
        _require_ledger(
            candidate.cursors,
            expected_cursors,
            "model.query candidate cursors",
        )

    def _validate_patch_candidate(
        self,
        snapshot: ProjectStateV0,
        candidate: ProjectStateV0,
        command: SourcePatchCommandV0,
        actual_result: Any,
        response: WireResponseV0,
    ) -> None:
        self._require_actual_result(actual_result, response)
        result = parse_source_patch_result(response.result)
        if (
            command.project_id != snapshot.project_id
            or result.project_id != command.project_id
            or result.base_revision_digest != command.base_revision_digest
            or result.patch_id != command.patch_id
        ):
            raise WireContractError("source.patch result/request binding failed")
        _require_ledger(
            candidate.read_receipts,
            snapshot.read_receipts,
            "source.patch candidate receipts",
        )
        _require_ledger(
            candidate.cursors,
            snapshot.cursors,
            "source.patch candidate cursors",
        )
        prior = snapshot.outcome_map.get(command.patch_id)
        if prior is not None:
            if candidate is not snapshot:
                raise WireContractError("source.patch replay changed state identity")
            _same_value(
                prior.result.to_data(),
                result.to_data(),
                "source.patch replay result",
            )
            return
        if command.base_revision_digest != snapshot.head.revision_digest:
            raise WireContractError("new source.patch did not bind current head")
        if candidate is snapshot:
            raise WireContractError("new source.patch did not produce a candidate")
        if candidate.project_id != snapshot.project_id:
            raise WireContractError("source.patch candidate crossed projects")
        if candidate.head.revision_digest != result.revision_digest:
            raise WireContractError("source.patch candidate head/result mismatch")
        if candidate.head.source_digest != result.source_digest:
            raise WireContractError("source.patch candidate source/result mismatch")
        if candidate.build.manifest.build_digest != result.build_digest:
            raise WireContractError("source.patch candidate build/result mismatch")
        if candidate.build_index is snapshot.build_index:
            raise WireContractError("source.patch candidate reused the old index")
        expected_revisions = (*snapshot.revisions, candidate.head)
        _require_ledger(
            candidate.revisions,
            expected_revisions,
            "source.patch candidate revisions",
        )
        outcome = candidate.outcome_map.get(command.patch_id)
        if outcome is None:
            raise WireContractError("source.patch candidate outcome is absent")
        _same_value(
            outcome.result.to_data(),
            result.to_data(),
            "source.patch outcome/result",
        )
        expected_outcomes = (*snapshot.patch_outcomes, outcome)
        _require_ledger(
            candidate.patch_outcomes,
            expected_outcomes,
            "source.patch candidate outcomes",
        )

    def _validate_success(
        self,
        snapshot: ProjectStateV0,
        request: WireRequestV0,
        candidate: ProjectStateV0,
        command: Any,
        actual_result: Any,
        response: WireResponseV0,
    ) -> None:
        if type(candidate) is not ProjectStateV0:
            raise WireContractError("K candidate state has wrong concrete type")
        if (
            response.status != "OK"
            or response.request_id != request.request_id
            or response.tool != request.tool
        ):
            raise WireContractError("candidate response/request binding failed")
        if request.tool == CAPABILITIES_TOOL:
            if candidate is not snapshot:
                raise WireContractError("capabilities.get changed state identity")
            if canonical_bytes(response.result) != _PACKAGED_REGISTRY_BYTES:
                raise WireContractError("capabilities.get escaped packaged registry")
            return
        trusted_command, trusted_transition = _VERIFY_TRUSTED_TRANSITION(
            snapshot,
            request,
        )
        _require_trusted_transition(
            candidate,
            command,
            actual_result,
            trusted_command,
            trusted_transition,
        )
        if request.tool == PROJECT_READ_TOOL:
            self._validate_read_candidate(
                snapshot,
                candidate,
                trusted_command,
                actual_result,
                response,
            )
            return
        if request.tool == MODEL_QUERY_TOOL:
            self._validate_query_candidate(
                snapshot,
                candidate,
                trusted_command,
                actual_result,
                response,
            )
            return
        if request.tool == SOURCE_PATCH_TOOL:
            self._validate_patch_candidate(
                snapshot,
                candidate,
                trusted_command,
                actual_result,
                response,
            )
            return
        raise WireContractError("unavailable tool entered success validation")

    def _encode_and_verify(
        self,
        response: WireResponseV0,
    ) -> tuple[bytes, WireResponseV0]:
        payload = self._codecs.response_encoder(response)
        admitted = self._codecs.response_decoder(payload)
        if (
            type(admitted) is not WireResponseV0
            or canonical_bytes(admitted.to_data()) != payload
            or canonical_bytes(response.to_data()) != payload
        ):
            raise WireContractError(
                "session response failed exact private self-admission")
        return payload, admitted

    def _require_cas(
        self,
        snapshot: ProjectStateV0,
        snapshot_digest: str,
    ) -> None:
        if (
            self._state is not snapshot
            or self._state.state_digest != snapshot_digest
        ):
            raise WireContractError(
                "offline fixture state changed before commit")

    def _finish_without_commit(
        self,
        snapshot: ProjectStateV0,
        snapshot_digest: str,
        response: WireResponseV0,
    ) -> bytes:
        payload, _ = self._encode_and_verify(response)
        self._require_cas(snapshot, snapshot_digest)
        return payload

    def handle_wire_request(self, blob: bytes) -> bytes:
        """Run one synchronous request and commit its verified candidate last."""

        if self._active:
            raise WireContractError(
                "OfflineProjectWireV0 rejects reentrant calls",
                code="WIRE_REENTRANT_CALL",
            )
        self._active = True
        snapshot = self._state
        snapshot_digest = snapshot.state_digest
        try:
            try:
                request = self._codecs.request_decoder(blob)
            except AddressableRequestError as exc:
                error = (
                    _unavailable_error(exc.tool)
                    if exc.tool not in AVAILABLE_TOOL_NAMES
                    else _safe_error(
                        exc, "offline fixture refused the request")
                )
                response = _error_response(
                    exc.request_id,
                    exc.tool,
                    "REFUSED",
                    error,
                )
                return self._finish_without_commit(
                    snapshot, snapshot_digest, response)

            if request.tool not in AVAILABLE_TOOL_NAMES:
                response = _error_response(
                    request.request_id,
                    request.tool,
                    "REFUSED",
                    _unavailable_error(request.tool),
                )
                return self._finish_without_commit(
                    snapshot, snapshot_digest, response)

            try:
                candidate, command, actual_result, response = (
                    self._dispatch_success(snapshot, request)
                )
                payload, admitted = self._encode_and_verify(response)
                self._validate_success(
                    snapshot,
                    request,
                    candidate,
                    command,
                    actual_result,
                    admitted,
                )
                self._require_cas(snapshot, snapshot_digest)
                self._state = candidate
                return payload
            except (PatchContradictionError, ProjectConflictError) as exc:
                response = _error_response(
                    request.request_id,
                    request.tool,
                    "CONFLICT",
                    _safe_error(exc, "offline fixture state conflict"),
                )
                return self._finish_without_commit(
                    snapshot, snapshot_digest, response)
            except ProjectKernelError as exc:
                response = _error_response(
                    request.request_id,
                    request.tool,
                    "REFUSED",
                    _safe_error(exc, "offline fixture refused the request"),
                )
                return self._finish_without_commit(
                    snapshot, snapshot_digest, response)
            except Exception:
                response = _error_response(
                    request.request_id,
                    request.tool,
                    "FAILED",
                    _fresh_error(_FAILED_ERROR_BYTES),
                )
                return self._finish_without_commit(
                    snapshot, snapshot_digest, response)
        finally:
            self._active = False


def _make_offline_project_wire(
    state: ProjectStateV0,
    *,
    codecs: _SessionCodecs,
    handlers: _SessionHandlers = _CAPTURED_HANDLERS,
) -> OfflineProjectWireV0:
    """Internal failure-injection factory; not a public constructor hook."""

    host = object.__new__(OfflineProjectWireV0)
    host._initialize(state, codecs, handlers)
    return host


__all__ = ["OfflineProjectWireV0"]
