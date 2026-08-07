"""Current-head project.read implementation for AP02-K."""
from __future__ import annotations

from typing import Any

from kukai.design_source import canonical_bytes, canonical_digest, root_digest

from .contracts import (
    CoverageV0,
    ProjectReadCommandV0,
    ProjectReadResultV0,
)
from .errors import ProjectConflictError, ProjectContractError, ProjectLimitError
from .receipts import clone_receipt, issue_read_receipt
from .schemas import MAX_RESULT_BYTES
from .state import KernelTransitionV0, ProjectStateV0, evolve_state


def _manifest_view(state: ProjectStateV0) -> dict[str, Any]:
    head = state.head
    manifest = state.build.manifest
    return {
        "build_digest": manifest.build_digest,
        "entity_count": manifest.entity_count,
        "exception_count": len(head.exceptions),
        "instance_count": manifest.instance_count,
        "module_count": len(head.modules),
        "package_lock_digest": head.package_lock_digest,
        "project_id": state.project_id,
        "revision_digest": head.revision_digest,
        "root_instance_id": head.root.instance_id,
        "root_module_id": head.root.module_id,
        "schema": "kir-ai-project-manifest-view/0",
        "source_digest": head.source_digest,
    }


def _read_value(
    state: ProjectStateV0,
    command: ProjectReadCommandV0,
) -> tuple[dict[str, Any], bool | None, Any, int, int, str | None, str]:
    head = state.head
    if command.scope == "manifest":
        value = _manifest_view(state)
        return {}, True, value, 1, 1, None, "INFORMATIONAL"
    if command.scope == "module.index":
        value = tuple({
            "module_digest": item.module_digest,
            "module_id": item.module_id,
            "schema": "kir-ai-module-index-entry/0",
        } for item in head.modules)
        return {}, None, value, len(value), len(value), None, "INFORMATIONAL"
    if command.scope == "exception.index":
        value = tuple({
            "exception_digest": item.exception_digest,
            "exception_id": item.exception_id,
            "schema": "kir-ai-exception-index-entry/0",
            "target_instance_id": item.target_instance_id,
        } for item in head.exceptions)
        return {}, None, value, len(value), len(value), None, "INFORMATIONAL"
    if command.scope == "root_instance":
        value = head.root.to_data()
        return {}, True, value, 1, 1, root_digest(head.root), "OWNER"
    if command.scope == "module":
        selector = {"module_id": command.target_id}
        module = head.module_map.get(command.target_id)
        if module is None:
            return selector, False, None, 1, 0, None, "OWNER"
        return (
            selector,
            True,
            module.semantic_data(),
            1,
            1,
            module.module_digest,
            "OWNER",
        )
    if command.scope == "exception":
        selector = {"exception_id": command.target_id}
        exception = head.exception_map.get(command.target_id)
        if exception is None:
            return selector, False, None, 1, 0, None, "OWNER"
        return (
            selector,
            True,
            exception.to_data(),
            1,
            1,
            exception.exception_digest,
            "OWNER",
        )
    raise ProjectContractError("project.read scope escaped command admission")


def project_read(
    state: ProjectStateV0,
    command: ProjectReadCommandV0,
) -> KernelTransitionV0:
    if type(state) is not ProjectStateV0:
        raise ProjectContractError("project_read requires exact ProjectStateV0")
    if type(command) is not ProjectReadCommandV0:
        raise ProjectContractError("project_read requires exact ProjectReadCommandV0")
    if command.project_id != state.project_id:
        raise ProjectConflictError("project.read crosses project authority")
    if command.revision_digest != state.head.revision_digest:
        raise ProjectConflictError("project.read is current-head-only")

    selector, present, value, requested, returned, object_digest, authority = (
        _read_value(state, command)
    )
    coverage = CoverageV0("COMPLETE", requested, requested, returned)
    result_digest = canonical_digest("kir.ai-project-read-result-body.v0", {
        "coverage": coverage.to_data(),
        "present": present,
        "project_id": state.project_id,
        "revision_digest": state.head.revision_digest,
        "scope": command.scope,
        "selector": selector,
        "value": value,
    })
    receipt = issue_read_receipt(
        kind="PROJECT_READ",
        authority=authority,
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope=command.scope,
        selector=selector,
        present=present,
        object_digest=object_digest,
        result_digest=result_digest,
        coverage=coverage,
    )
    next_state = evolve_state(state, receipt=receipt)
    result = ProjectReadResultV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope=command.scope,
        selector=selector,
        present=present,
        value=value,
        coverage=CoverageV0("COMPLETE", requested, requested, returned),
        receipt=clone_receipt(receipt),
    )
    if len(canonical_bytes(result.to_data())) > MAX_RESULT_BYTES:
        raise ProjectLimitError("project.read result exceeds 2MB")
    return KernelTransitionV0(next_state, result)


__all__ = ["project_read"]
