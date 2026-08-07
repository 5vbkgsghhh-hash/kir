"""Immutable host-owned project state for the isolated AP02-K kernel."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kukai.design_source import (
    BuildResultV0,
    FrozenMap,
    SourceRevisionV0,
    canonical_bytes,
    canonical_digest,
    materialize,
)

from .contracts import (
    CursorRecordV0,
    ReadReceiptV0,
    SourcePatchResultV0,
    exact_digest,
    exact_identifier,
    frozen_object,
)
from .errors import ProjectConflictError, ProjectContractError, ProjectLimitError
from .index import ProjectBuildIndexV0
from .schemas import (
    MAX_CURSORS,
    MAX_PATCH_OUTCOMES,
    MAX_RECEIPTS,
    MAX_REVISIONS,
    PATCH_OUTCOME_SCHEMA,
    PROJECT_STATE_SCHEMA,
    SEMANTIC_PATCH_SCHEMA,
)


@dataclass(frozen=True, slots=True)
class PatchOutcomeRecordV0:
    patch_id: str
    base_revision_digest: str
    semantic_patch_digest: str
    semantic_patch_data: FrozenMap | dict[str, Any]
    target_modules: FrozenMap | dict[str, Any]
    result: SourcePatchResultV0

    def __post_init__(self) -> None:
        if type(self.result) is not SourcePatchResultV0:
            raise ProjectContractError("patch outcome result has wrong type")
        object.__setattr__(self, "patch_id", exact_identifier(
            self.patch_id, "patch outcome patch_id"))
        for name in ("base_revision_digest", "semantic_patch_digest"):
            object.__setattr__(
                self, name, exact_digest(getattr(self, name), f"patch outcome {name}"))
        semantic_data = frozen_object(
            self.semantic_patch_data, "patch outcome semantic data")
        if set(semantic_data) != {
            "base_revision_digest",
            "operations",
            "project_id",
            "receipt_refs",
            "schema",
        }:
            raise ProjectContractError(
                "patch outcome semantic data fields mismatch")
        if semantic_data["schema"] != SEMANTIC_PATCH_SCHEMA:
            raise ProjectContractError(
                "patch outcome semantic data schema mismatch")
        if (
            semantic_data["base_revision_digest"] != self.base_revision_digest
            or semantic_data["project_id"] != self.result.project_id
        ):
            raise ProjectContractError(
                "patch outcome semantic data binding mismatch")
        if canonical_digest(
            "kir.ai-semantic-patch.v0", semantic_data
        ) != self.semantic_patch_digest:
            raise ProjectContractError(
                "patch outcome semantic digest does not match its data")
        object.__setattr__(self, "semantic_patch_data", semantic_data)
        object.__setattr__(self, "target_modules", frozen_object(
            self.target_modules, "patch outcome target modules"))
        for instance_id, binding in self.target_modules.items():
            exact_identifier(instance_id, "patch outcome target instance_id")
            binding = frozen_object(
                binding, "patch outcome target module binding")
            if set(binding) != {"base_module_digest", "module_id"}:
                raise ProjectContractError(
                    "patch outcome target module binding fields mismatch")
            exact_identifier(
                binding["module_id"], "patch outcome target module_id")
            exact_digest(
                binding["base_module_digest"],
                "patch outcome target base_module_digest",
            )
        if (
            self.result.patch_id != self.patch_id
            or self.result.base_revision_digest != self.base_revision_digest
            or self.result.semantic_patch_digest != self.semantic_patch_digest
        ):
            raise ProjectContractError("patch outcome/result binding mismatch")
        expected_transition = canonical_digest("kir.ai-source-transition.v0", {
            "base_revision_digest": self.result.base_revision_digest,
            "build_digest": self.result.build_digest,
            "project_id": self.result.project_id,
            "revision_digest": self.result.revision_digest,
            "semantic_patch_digest": self.result.semantic_patch_digest,
            "source_digest": self.result.source_digest,
        })
        if self.result.transition_digest != expected_transition:
            raise ProjectContractError(
                "patch outcome transition digest does not match its bindings")

    def to_data(self) -> dict[str, Any]:
        return {
            "base_revision_digest": self.base_revision_digest,
            "patch_id": self.patch_id,
            "result": self.result.to_data(),
            "schema": PATCH_OUTCOME_SCHEMA,
            "semantic_patch_data": self.semantic_patch_data,
            "semantic_patch_digest": self.semantic_patch_digest,
            "target_modules": self.target_modules,
        }


@dataclass(frozen=True, slots=True)
class ProjectStateV0:
    project_id: str
    head: SourceRevisionV0
    build: BuildResultV0
    build_index: ProjectBuildIndexV0 = field(repr=False, compare=False)
    revisions: tuple[SourceRevisionV0, ...] | list[SourceRevisionV0] = ()
    read_receipts: tuple[ReadReceiptV0, ...] | list[ReadReceiptV0] = ()
    cursors: tuple[CursorRecordV0, ...] | list[CursorRecordV0] = ()
    patch_outcomes: tuple[PatchOutcomeRecordV0, ...] | list[PatchOutcomeRecordV0] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "state.project_id"))
        if type(self.head) is not SourceRevisionV0:
            raise ProjectContractError("state head must be exact SourceRevisionV0")
        if type(self.build) is not BuildResultV0:
            raise ProjectContractError("state build must be exact BuildResultV0")
        if type(self.build_index) is not ProjectBuildIndexV0:
            raise ProjectContractError(
                "state build_index must be exact ProjectBuildIndexV0")
        if self.head.project_id != self.project_id:
            raise ProjectContractError("state project/head mismatch")
        if self.build.build_use.source_revision_digest != self.head.revision_digest:
            raise ProjectContractError("state retained build does not bind head revision")
        if self.build.manifest.source_digest != self.head.source_digest:
            raise ProjectContractError("state retained build does not bind head source")
        if self.build_index.build_digest != self.build.manifest.build_digest:
            raise ProjectContractError(
                "state retained ProjectBuildIndex does not bind build")
        if self.build_index.entity_ids != self.build.manifest.entity_ids:
            raise ProjectContractError(
                "state retained ProjectBuildIndex does not cover build entities")

        revisions = tuple(self.revisions)
        receipts = tuple(self.read_receipts)
        cursors = tuple(self.cursors)
        outcomes = tuple(self.patch_outcomes)
        if not revisions or revisions[-1].revision_digest != self.head.revision_digest:
            raise ProjectContractError("state revision ledger does not end at head")
        if len(revisions) > MAX_REVISIONS:
            raise ProjectLimitError("revision ledger exceeds its limit")
        if len(receipts) > MAX_RECEIPTS:
            raise ProjectLimitError("read receipt ledger exceeds its limit")
        if len(cursors) > MAX_CURSORS:
            raise ProjectLimitError("cursor ledger exceeds its limit")
        if len(outcomes) > MAX_PATCH_OUTCOMES:
            raise ProjectLimitError("patch outcome ledger exceeds its limit")
        if any(type(item) is not SourceRevisionV0 for item in revisions):
            raise ProjectContractError("revision ledger has wrong child type")
        if any(item.project_id != self.project_id for item in revisions):
            raise ProjectContractError("revision ledger crosses projects")
        if any(type(item) is not ReadReceiptV0 for item in receipts):
            raise ProjectContractError("receipt ledger has wrong child type")
        if any(type(item) is not CursorRecordV0 for item in cursors):
            raise ProjectContractError("cursor ledger has wrong child type")
        if any(type(item) is not PatchOutcomeRecordV0 for item in outcomes):
            raise ProjectContractError("patch outcome ledger has wrong child type")
        if any(item.project_id != self.project_id for item in receipts):
            raise ProjectContractError("receipt ledger crosses projects")
        if any(item.project_id != self.project_id for item in cursors):
            raise ProjectContractError("cursor ledger crosses projects")
        self._require_unique(revisions, "revision_digest", "revision")
        self._require_unique(receipts, "receipt_id", "receipt")
        self._require_unique(cursors, "cursor_id", "cursor")
        self._require_unique(outcomes, "patch_id", "patch outcome")
        if len(outcomes) != len(revisions) - 1:
            raise ProjectContractError("patch outcome/revision ledger census mismatch")
        for index, outcome in enumerate(outcomes):
            before = revisions[index]
            after = revisions[index + 1]
            if (
                outcome.result.project_id != self.project_id
                or outcome.base_revision_digest != before.revision_digest
                or outcome.result.revision_digest != after.revision_digest
                or outcome.result.source_digest != after.source_digest
                or after.parent_revision_digest != before.revision_digest
            ):
                raise ProjectContractError("patch outcome/revision ledger binding mismatch")
            for binding in outcome.target_modules.values():
                module = before.module_map.get(binding["module_id"])
                if (
                    module is None
                    or module.module_digest != binding["base_module_digest"]
                ):
                    raise ProjectContractError(
                        "patch outcome target module does not bind base revision")
        if outcomes and outcomes[-1].result.build_digest != self.build.manifest.build_digest:
            raise ProjectContractError("head patch outcome/build binding mismatch")
        object.__setattr__(self, "revisions", revisions)
        object.__setattr__(self, "read_receipts", receipts)
        object.__setattr__(self, "cursors", cursors)
        object.__setattr__(self, "patch_outcomes", outcomes)

    @staticmethod
    def _require_unique(items: tuple[Any, ...], attr: str, label: str) -> None:
        values = tuple(getattr(item, attr) for item in items)
        if len(values) != len(set(values)):
            raise ProjectContractError(f"state has duplicate {label}")

    @property
    def state_digest(self) -> str:
        return canonical_digest("kir.ai-project-state.v0", self.to_data())

    @property
    def receipt_map(self) -> dict[str, ReadReceiptV0]:
        return {item.receipt_id: item for item in self.read_receipts}

    @property
    def cursor_map(self) -> dict[str, CursorRecordV0]:
        return {item.cursor_id: item for item in self.cursors}

    @property
    def outcome_map(self) -> dict[str, PatchOutcomeRecordV0]:
        return {item.patch_id: item for item in self.patch_outcomes}

    @property
    def revision_map(self) -> dict[str, SourceRevisionV0]:
        return {item.revision_digest: item for item in self.revisions}

    def to_data(self) -> dict[str, Any]:
        return {
            "build": self.build.to_data(),
            "cursors": tuple(item.to_data() for item in self.cursors),
            "head_revision_digest": self.head.revision_digest,
            "patch_outcomes": tuple(item.to_data() for item in self.patch_outcomes),
            "project_id": self.project_id,
            "read_receipts": tuple(item.to_data() for item in self.read_receipts),
            "revisions": tuple(item.to_data() for item in self.revisions),
            "schema": PROJECT_STATE_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class KernelTransitionV0:
    state: ProjectStateV0
    result: Any

    def __post_init__(self) -> None:
        if type(self.state) is not ProjectStateV0:
            raise ProjectContractError("transition state has wrong type")


def create_project_state(source: SourceRevisionV0) -> ProjectStateV0:
    if type(source) is not SourceRevisionV0:
        raise ProjectContractError("create_project_state requires exact SourceRevisionV0")
    build = materialize(source)
    return ProjectStateV0(
        project_id=source.project_id,
        head=source,
        build=build,
        build_index=ProjectBuildIndexV0(build),
        revisions=(source,),
    )


def evolve_state(
    state: ProjectStateV0,
    *,
    head: SourceRevisionV0 | None = None,
    build: BuildResultV0 | None = None,
    receipt: ReadReceiptV0 | None = None,
    cursor: CursorRecordV0 | None = None,
    outcome: PatchOutcomeRecordV0 | None = None,
) -> ProjectStateV0:
    if type(state) is not ProjectStateV0:
        raise ProjectContractError("evolve_state requires exact ProjectStateV0")
    receipts = state.read_receipts
    if receipt is not None:
        existing = state.receipt_map.get(receipt.receipt_id)
        if existing is None:
            if len(receipts) >= MAX_RECEIPTS:
                raise ProjectLimitError("read receipt ledger is full")
            receipts = (*receipts, receipt)
        elif canonical_bytes(existing.to_data()) != canonical_bytes(receipt.to_data()):
            raise ProjectConflictError("read receipt identity collision")
    cursors = state.cursors
    if cursor is not None:
        existing_cursor = state.cursor_map.get(cursor.cursor_id)
        if existing_cursor is None:
            if len(cursors) >= MAX_CURSORS:
                raise ProjectLimitError("cursor ledger is full")
            cursors = (*cursors, cursor)
        elif canonical_bytes(existing_cursor.to_data()) != canonical_bytes(cursor.to_data()):
            raise ProjectConflictError("cursor identity collision")
    new_head = state.head if head is None else head
    new_build = state.build if build is None else build
    revisions = state.revisions
    outcomes = state.patch_outcomes
    if head is not None:
        if build is None or outcome is None:
            raise ProjectContractError("head transition requires build and outcome")
        if len(revisions) >= MAX_REVISIONS or len(outcomes) >= MAX_PATCH_OUTCOMES:
            raise ProjectLimitError("project revision/outcome ledger is full")
        revisions = (*revisions, head)
        outcomes = (*outcomes, outcome)
    elif build is not None or outcome is not None:
        raise ProjectContractError("build/outcome cannot change without head")
    next_index = (
        state.build_index
        if build is None
        else ProjectBuildIndexV0(new_build)
    )
    return ProjectStateV0(
        project_id=state.project_id,
        head=new_head,
        build=new_build,
        build_index=next_index,
        revisions=revisions,
        read_receipts=receipts,
        cursors=cursors,
        patch_outcomes=outcomes,
    )


__all__ = [
    "KernelTransitionV0",
    "PatchOutcomeRecordV0",
    "ProjectStateV0",
    "create_project_state",
    "evolve_state",
]
