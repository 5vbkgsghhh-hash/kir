from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from kukai.ai_protocol.project_v0 import (
    CursorAuthorityError,
    CursorRefV0,
    ModelQueryCommandV0,
    ProjectConflictError,
    ProjectContractError,
    ProjectLimitError,
    ProjectQueryError,
    model_query,
)
from kukai.ai_protocol.project_v0.schemas import MAX_PAGE_BYTES
from kukai.design_source import BuildIndexV0, FrozenMap, canonical_bytes


def _query(
    state,
    scope: str,
    filters: dict,
    *,
    limit: int = 128,
    cursor=None,
):
    return model_query(state, ModelQueryCommandV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope=scope,
        filters=filters,
        limit=limit,
        cursor=cursor,
    ))


def test_summary_and_logical_id_queries_use_retained_index(state54) -> None:
    summary = _query(state54, "summary", {})
    item = summary.result.items[0]
    assert item["entity_count"] == 324
    assert dict(item["counts_by_semantic_type"]) == {
        "bim.level": 54,
        "bim.slab": 54,
        "bim.wall": 216,
    }
    assert summary.result.coverage.state == "COMPLETE"
    assert summary.result.cursor is None
    assert summary.result.receipt.authority == "INFORMATIONAL"

    logical_id = state54.build.entities[100].logical_id
    exact = _query(summary.state, "logical_id", {"logical_id": logical_id})
    assert exact.result.items[0]["logical_id"] == logical_id
    assert exact.state.build_index is state54.build_index


def test_origin_query_pages_without_duplicate_or_drop_on_54_floors(state54) -> None:
    state = state54
    cursor = None
    logical_ids = []
    page_sizes = []
    while True:
        transition = _query(
            state,
            "origin",
            {"module_id": "mod_typical_floor"},
            limit=37,
            cursor=cursor,
        )
        state = transition.state
        result = transition.result
        page_ids = [item["logical_id"] for item in result.items]
        logical_ids.extend(page_ids)
        page_sizes.append(len(page_ids))
        assert page_ids == sorted(page_ids)
        assert len(canonical_bytes(result.to_data())) <= MAX_PAGE_BYTES
        assert result.coverage.requested == result.coverage.evaluated == 324
        if result.cursor is None:
            assert result.coverage.state == "COMPLETE"
            break
        assert result.coverage.state == "PARTIAL"
        cursor = result.cursor

    expected = [
        item.logical_id
        for item in state54.build.entities
        if item.origin.module_id == "mod_typical_floor"
    ]
    assert logical_ids == expected
    assert len(logical_ids) == len(set(logical_ids)) == 270
    assert page_sizes[:-1] == [37] * 7
    assert page_sizes[-1] == 11


def test_same_page_is_deterministic_fresh_and_ledger_idempotent(state54) -> None:
    first = _query(
        state54, "origin", {"module_id": "mod_typical_floor"}, limit=10)
    second = _query(
        first.state, "origin", {"module_id": "mod_typical_floor"}, limit=10)

    assert canonical_bytes(first.result.to_data()) == canonical_bytes(
        second.result.to_data())
    assert first.result is not second.result
    assert first.result.items[0] is not second.result.items[0]
    assert len(first.state.cursors) == len(second.state.cursors) == 1
    assert len(first.state.read_receipts) == len(second.state.read_receipts) == 1
    assert second.state.build_index is state54.build_index


@pytest.mark.parametrize("mutation", ["digest", "limit", "filter", "missing"])
def test_cursor_substitution_is_typed_and_state_ledger_is_authority(
    state54,
    mutation: str,
) -> None:
    first = _query(
        state54, "origin", {"module_id": "mod_typical_floor"}, limit=10)
    cursor = first.result.cursor
    assert cursor is not None
    state = first.state
    filters = {"module_id": "mod_typical_floor"}
    limit = 10
    if mutation == "digest":
        cursor = CursorRefV0(cursor.cursor_id, "sha256:" + "0" * 64)
    elif mutation == "limit":
        limit = 11
    elif mutation == "filter":
        filters = {"module_id": "mod_building"}
    else:
        cursor = CursorRefV0("cur_" + "f" * 40, cursor.cursor_digest)
    before = canonical_bytes(state.to_data())

    with pytest.raises(CursorAuthorityError):
        _query(state, "origin", filters, limit=limit, cursor=cursor)

    assert canonical_bytes(state.to_data()) == before


def test_query_cross_revision_and_build_are_current_head_only(state3) -> None:
    for field in ("revision_digest", "build_digest"):
        values = {
            "project_id": state3.project_id,
            "revision_digest": state3.head.revision_digest,
            "build_digest": state3.build.manifest.build_digest,
            "scope": "summary",
            "filters": {},
            "limit": 1,
        }
        values[field] = "sha256:" + "0" * 64
        command = ModelQueryCommandV0(**values)
        with pytest.raises(ProjectConflictError):
            model_query(state3, command)


def test_unknown_logical_id_is_typed_query_failure(state3) -> None:
    with pytest.raises(ProjectQueryError, match="unknown"):
        _query(state3, "logical_id", {"logical_id": "missing_entity"})


def test_retained_project_index_cannot_rebind_query_truth(state3) -> None:
    logical_id = state3.build.entities[0].logical_id
    first = _query(state3, "logical_id", {"logical_id": logical_id})
    before_digest = state3.state_digest

    with pytest.raises(FrozenInstanceError):
        setattr(state3.build_index, "_by_id", FrozenMap({}))

    assert state3.state_digest == before_digest
    second = _query(state3, "logical_id", {"logical_id": logical_id})
    assert canonical_bytes(second.result.to_data()) == canonical_bytes(
        first.result.to_data())
    assert first.state.build_index is state3.build_index
    assert second.state.build_index is state3.build_index

    with pytest.raises(ProjectContractError, match="ProjectBuildIndexV0"):
        replace(state3, build_index=BuildIndexV0(state3.build))


def test_oversized_single_item_never_emits_empty_same_offset_page(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.query as query_module

    monkeypatch.setattr(query_module, "MAX_PAGE_BYTES", 1)
    before = canonical_bytes(state3.to_data())

    with pytest.raises(ProjectLimitError, match="one query item"):
        _query(state3, "origin", {"module_id": "mod_typical_floor"}, limit=1)

    assert canonical_bytes(state3.to_data()) == before
    assert state3.cursors == ()
    assert state3.read_receipts == ()


def test_cursor_capacity_failure_adds_neither_cursor_nor_receipt(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.state as state_module

    monkeypatch.setattr(state_module, "MAX_CURSORS", 0)
    before = canonical_bytes(state3.to_data())

    with pytest.raises(ProjectLimitError, match="cursor ledger is full"):
        _query(state3, "origin", {"module_id": "mod_typical_floor"}, limit=1)

    assert canonical_bytes(state3.to_data()) == before
    assert state3.cursors == ()
    assert state3.read_receipts == ()
