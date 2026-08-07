"""Host-ledger issuance and dereference of AP02-K read receipts."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from kukai.design_source import canonical_bytes

from .contracts import (
    CoverageV0,
    ReadReceiptV0,
    ReceiptRefV0,
    frozen_object,
)
from .errors import ProjectContractError, ReceiptAuthorityError
from .state import ProjectStateV0


def issue_read_receipt(
    *,
    kind: str,
    authority: str,
    project_id: str,
    revision_digest: str,
    build_digest: str,
    scope: str,
    selector: dict[str, Any],
    present: bool | None,
    object_digest: str | None,
    result_digest: str,
    coverage: CoverageV0,
    chain_digest: str | None = None,
) -> ReadReceiptV0:
    return ReadReceiptV0(
        kind=kind,
        authority=authority,
        project_id=project_id,
        revision_digest=revision_digest,
        build_digest=build_digest,
        scope=scope,
        selector=selector,
        present=present,
        object_digest=object_digest,
        result_digest=result_digest,
        coverage=coverage,
        chain_digest=chain_digest,
    )


def clone_receipt(receipt: ReadReceiptV0) -> ReadReceiptV0:
    if type(receipt) is not ReadReceiptV0:
        raise ProjectContractError("clone_receipt requires exact ReadReceiptV0")
    return issue_read_receipt(
        kind=receipt.kind,
        authority=receipt.authority,
        project_id=receipt.project_id,
        revision_digest=receipt.revision_digest,
        build_digest=receipt.build_digest,
        scope=receipt.scope,
        selector=dict(receipt.selector.items()),
        present=receipt.present,
        object_digest=receipt.object_digest,
        result_digest=receipt.result_digest,
        coverage=CoverageV0(
            receipt.coverage.state,
            receipt.coverage.requested,
            receipt.coverage.evaluated,
            receipt.coverage.returned,
        ),
        chain_digest=receipt.chain_digest,
    )


def resolve_receipt_refs(
    state: ProjectStateV0,
    refs: Iterable[ReceiptRefV0],
) -> tuple[ReadReceiptV0, ...]:
    if type(state) is not ProjectStateV0:
        raise ProjectContractError("receipt resolution requires exact ProjectStateV0")
    ledger = state.receipt_map
    resolved = []
    for ref in tuple(refs):
        if type(ref) is not ReceiptRefV0:
            raise ProjectContractError("receipt reference has wrong type")
        receipt = ledger.get(ref.receipt_id)
        if receipt is None:
            raise ReceiptAuthorityError(
                f"receipt {ref.receipt_id!r} is not in the host ledger")
        if receipt.receipt_digest != ref.receipt_digest:
            raise ReceiptAuthorityError("receipt digest does not match host ledger")
        resolved.append(receipt)
    return tuple(resolved)


def require_owner_receipt(
    receipts: Iterable[ReadReceiptV0],
    *,
    project_id: str,
    revision_digest: str,
    build_digest: str,
    scope: str,
    selector: dict[str, Any],
    present: bool,
    object_digest: str | None,
) -> ReadReceiptV0:
    expected_selector = frozen_object(selector, "owner receipt selector")
    matches = []
    for receipt in tuple(receipts):
        if (
            receipt.kind == "PROJECT_READ"
            and receipt.authority == "OWNER"
            and receipt.project_id == project_id
            and receipt.revision_digest == revision_digest
            and receipt.build_digest == build_digest
            and receipt.scope == scope
            and canonical_bytes(receipt.selector)
            == canonical_bytes(expected_selector)
            and receipt.present is present
            and receipt.object_digest == object_digest
            and receipt.coverage.state == "COMPLETE"
        ):
            matches.append(receipt)
    if len(matches) != 1:
        raise ReceiptAuthorityError(
            f"exact owner receipt required for {scope} {dict(expected_selector)!r}")
    return matches[0]


__all__ = [
    "clone_receipt",
    "issue_read_receipt",
    "require_owner_receipt",
    "resolve_receipt_refs",
]
