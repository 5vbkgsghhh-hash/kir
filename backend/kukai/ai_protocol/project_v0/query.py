"""Deterministic, ledger-authorized paging over one retained BuildIndex."""
from __future__ import annotations

from typing import Any

from kukai.design_source import canonical_bytes, canonical_digest
from kukai.design_source.errors import DesignSourceError

from .contracts import (
    CoverageV0,
    CursorRecordV0,
    ModelQueryCommandV0,
    ModelQueryResultV0,
)
from .errors import (
    CursorAuthorityError,
    ProjectConflictError,
    ProjectContractError,
    ProjectLimitError,
    ProjectQueryError,
)
from .receipts import clone_receipt, issue_read_receipt
from .schemas import MAX_PAGE_BYTES
from .state import KernelTransitionV0, ProjectStateV0, evolve_state


def _resolve_cursor(
    state: ProjectStateV0,
    command: ModelQueryCommandV0,
) -> tuple[int, str]:
    seed = canonical_digest("kir.ai-model-query-chain-seed.v0", command.binding_data())
    if command.cursor is None:
        return 0, seed
    cursor = state.cursor_map.get(command.cursor.cursor_id)
    if cursor is None:
        raise CursorAuthorityError("cursor is not in the host ledger")
    if cursor.cursor_digest != command.cursor.cursor_digest:
        raise CursorAuthorityError("cursor digest does not match host ledger")
    if (
        cursor.project_id != command.project_id
        or cursor.revision_digest != command.revision_digest
        or cursor.build_digest != command.build_digest
        or cursor.scope != command.scope
        or cursor.limit != command.limit
        or canonical_bytes(cursor.filters) != canonical_bytes(command.filters)
    ):
        raise CursorAuthorityError("cursor binding does not match query")
    return cursor.offset, cursor.chain_digest


def _query_records(
    state: ProjectStateV0,
    command: ModelQueryCommandV0,
) -> tuple[tuple[dict[str, Any], ...], int]:
    try:
        if command.scope == "summary":
            summary = state.build_index.summary()
            return (({
                "build_digest": summary.build_digest,
                "counts_by_semantic_type": summary.counts_by_semantic_type,
                "entity_count": summary.entity_count,
                "schema": summary.schema,
            }),), 1
        if command.scope == "logical_id":
            entity = state.build_index.by_logical_id(command.filters["logical_id"])
            return (entity.to_data(),), 1
        if command.scope == "origin":
            result = state.build_index.by_origin(**dict(command.filters.items()))
            records = tuple(item.to_data() for item in result.entities)
            return records, result.requested
    except DesignSourceError as exc:
        raise ProjectQueryError(str(exc)) from exc
    raise ProjectContractError("model.query scope escaped command admission")


def _page_result(
    state: ProjectStateV0,
    command: ModelQueryCommandV0,
    records: tuple[dict[str, Any], ...],
    requested: int,
    offset: int,
    end: int,
    previous_chain_digest: str,
) -> tuple[CursorRecordV0 | None, Any, ModelQueryResultV0]:
    items = records[offset:end]
    item_keys = tuple(
        item.get("logical_id", "summary") for item in items)
    chain_digest = canonical_digest("kir.ai-model-query-chain.v0", {
        "end_offset": end,
        "item_keys": item_keys,
        "previous_chain_digest": previous_chain_digest,
        "start_offset": offset,
    })
    partial = end < len(records)
    cursor = None
    if partial:
        cursor = CursorRecordV0(
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=command.build_digest,
            scope=command.scope,
            filters=command.filters,
            offset=end,
            limit=command.limit,
            chain_digest=chain_digest,
        )
    coverage = CoverageV0(
        "PARTIAL" if partial else "COMPLETE",
        requested,
        requested,
        len(items),
    )
    core = {
        "build_digest": command.build_digest,
        "chain_digest": chain_digest,
        "coverage": coverage.to_data(),
        "filters": command.filters,
        "items": items,
        "project_id": command.project_id,
        "revision_digest": command.revision_digest,
        "scope": command.scope,
    }
    result_digest = canonical_digest("kir.ai-model-query-result-body.v0", core)
    receipt = issue_read_receipt(
        kind="MODEL_QUERY",
        authority="INFORMATIONAL",
        project_id=command.project_id,
        revision_digest=command.revision_digest,
        build_digest=command.build_digest,
        scope=command.scope,
        selector=dict(command.filters.items()),
        present=None,
        object_digest=None,
        result_digest=result_digest,
        coverage=coverage,
        chain_digest=chain_digest,
    )
    result = ModelQueryResultV0(
        project_id=command.project_id,
        revision_digest=command.revision_digest,
        build_digest=command.build_digest,
        scope=command.scope,
        filters=command.filters,
        items=items,
        coverage=CoverageV0(
            coverage.state,
            coverage.requested,
            coverage.evaluated,
            coverage.returned,
        ),
        cursor=None if cursor is None else cursor.ref,
        receipt=clone_receipt(receipt),
    )
    return cursor, receipt, result


def model_query(
    state: ProjectStateV0,
    command: ModelQueryCommandV0,
) -> KernelTransitionV0:
    if type(state) is not ProjectStateV0:
        raise ProjectContractError("model_query requires exact ProjectStateV0")
    if type(command) is not ModelQueryCommandV0:
        raise ProjectContractError("model_query requires exact ModelQueryCommandV0")
    if command.project_id != state.project_id:
        raise ProjectConflictError("model.query crosses project authority")
    if command.revision_digest != state.head.revision_digest:
        raise ProjectConflictError("model.query is current-head-only")
    if command.build_digest != state.build.manifest.build_digest:
        raise ProjectConflictError("model.query build is not the retained head build")

    offset, previous_chain = _resolve_cursor(state, command)
    records, requested = _query_records(state, command)
    if offset > len(records):
        raise CursorAuthorityError("cursor offset exceeds query result")
    end = min(offset + command.limit, len(records))
    while True:
        cursor, receipt, result = _page_result(
            state,
            command,
            records,
            requested,
            offset,
            end,
            previous_chain,
        )
        page_fits = len(canonical_bytes(result.to_data())) <= MAX_PAGE_BYTES
        if page_fits and (end > offset or end == len(records)):
            break
        if end == offset:
            raise ProjectLimitError("one query item exceeds the 1MB page limit")
        end -= 1
    next_state = evolve_state(state, receipt=receipt, cursor=cursor)
    return KernelTransitionV0(next_state, result)


__all__ = ["model_query"]
