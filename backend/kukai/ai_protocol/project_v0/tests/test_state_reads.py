from __future__ import annotations

import pytest

from kukai.ai_protocol.project_v0 import (
    ProjectConflictError,
    ProjectLimitError,
    ProjectReadCommandV0,
    project_read,
)
from kukai.design_source import canonical_bytes


def _read(state, scope: str, target_id: str | None = None):
    return project_read(state, ProjectReadCommandV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        scope=scope,
        target_id=target_id,
    ))


def test_state_retains_exact_complete_three_floor_build(state3) -> None:
    assert state3.build.manifest.status == "COMPLETE"
    assert state3.build.manifest.entity_count == 18
    assert state3.build.manifest.instance_count == 4
    assert state3.build.manifest.source_occurrence_count == 22
    assert state3.build_index.build_digest == state3.build.manifest.build_digest
    assert state3.revisions == (state3.head,)
    assert state3.read_receipts == ()


def test_every_project_read_scope_is_current_head_and_truthful(state3) -> None:
    cases = (
        ("manifest", None),
        ("module.index", None),
        ("exception.index", None),
        ("root_instance", None),
        ("module", "mod_typical_floor"),
        ("exception", "exc_missing"),
    )
    state = state3
    results = {}
    for scope, target in cases:
        transition = _read(state, scope, target)
        state = transition.state
        results[scope] = transition.result

    assert results["manifest"].value["entity_count"] == 18
    assert len(results["module.index"].value) == 2
    assert results["exception.index"].value == ()
    assert results["root_instance"].present is True
    assert results["module"].present is True
    assert "metadata" not in results["module"].value
    assert results["exception"].present is False
    assert results["exception"].value is None
    assert results["exception"].coverage.state == "COMPLETE"
    assert results["exception"].cursor is None
    assert results["manifest"].receipt.authority == "INFORMATIONAL"
    assert results["module.index"].receipt.authority == "INFORMATIONAL"
    assert results["root_instance"].receipt.authority == "OWNER"
    assert results["module"].receipt.authority == "OWNER"
    assert results["exception"].receipt.authority == "OWNER"
    assert len(state.read_receipts) == len(cases)


def test_exact_present_and_absent_reads_issue_distinct_owner_receipts(state3) -> None:
    present = _read(state3, "module", "mod_typical_floor")
    absent = _read(present.state, "module", "mod_new")

    assert present.result.present is True
    assert present.result.receipt.object_digest == (
        state3.head.module_map["mod_typical_floor"].module_digest)
    assert absent.result.present is False
    assert absent.result.receipt.object_digest is None
    assert present.result.receipt.receipt_id != absent.result.receipt.receipt_id


def test_repeated_read_is_idempotent_fresh_and_reuses_retained_index(state3) -> None:
    first = _read(state3, "module", "mod_typical_floor")
    second = _read(first.state, "module", "mod_typical_floor")

    assert len(first.state.read_receipts) == len(second.state.read_receipts) == 1
    assert canonical_bytes(first.result.to_data()) == canonical_bytes(
        second.result.to_data())
    assert first.result is not second.result
    assert first.result.receipt is not second.result.receipt
    assert first.state.build_index is state3.build_index
    assert second.state.build_index is state3.build_index


@pytest.mark.parametrize(
    ("project_id", "revision_digest"),
    [
        ("other_project", None),
        (None, "sha256:" + "0" * 64),
    ],
)
def test_read_cross_project_or_revision_refusal_leaves_state_exact(
    state3,
    project_id,
    revision_digest,
) -> None:
    before = canonical_bytes(state3.to_data())
    command = ProjectReadCommandV0(
        project_id=state3.project_id if project_id is None else project_id,
        revision_digest=(
            state3.head.revision_digest
            if revision_digest is None
            else revision_digest
        ),
        scope="manifest",
    )
    with pytest.raises(ProjectConflictError):
        project_read(state3, command)
    assert canonical_bytes(state3.to_data()) == before


def test_receipt_capacity_failure_has_no_partial_state(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.state as state_module

    first = _read(state3, "manifest")
    before = canonical_bytes(first.state.to_data())
    monkeypatch.setattr(state_module, "MAX_RECEIPTS", 1)

    with pytest.raises(ProjectLimitError, match="ledger is full"):
        _read(first.state, "root_instance")

    assert canonical_bytes(first.state.to_data()) == before
    assert first.state.build_index is state3.build_index
