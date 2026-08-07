"""Immutable command, receipt, cursor, and result values for AP02-K."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal, TypeAlias

from kukai.design_source import (
    CanonicalError,
    FrozenMap,
    ModuleV0,
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)

from .errors import ProjectContractError, ProjectLimitError
from .schemas import (
    COVERAGE_SCHEMA,
    CURSOR_RECORD_SCHEMA,
    CURSOR_REF_SCHEMA,
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
    MAX_ARGUMENT_BYTES,
    MAX_PAGE_ITEMS,
    MAX_PATCH_OPS,
    MAX_RECEIPT_REFS,
    MODEL_QUERY_COMMAND_SCHEMA,
    MODEL_QUERY_RESULT_SCHEMA,
    MODEL_QUERY_SCOPES,
    MODULE_PUT_SCHEMA,
    ORIGIN_FILTER_FIELDS,
    PROJECT_READ_COMMAND_SCHEMA,
    PROJECT_READ_RESULT_SCHEMA,
    PROJECT_READ_SCOPES,
    READ_RECEIPT_SCHEMA,
    RECEIPT_REF_SCHEMA,
    ROOT_PUT_SCHEMA,
    SOURCE_PATCH_COMMAND_SCHEMA,
    SOURCE_PATCH_RESULT_SCHEMA,
)


_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def exact_identifier(value: Any, path: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ProjectContractError(f"{path} must be an exact V0 identifier")
    return value


def exact_digest(value: Any, path: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProjectContractError(
            f"{path} must be exact lowercase sha256:<64 hex>")
    return value


def exact_int(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProjectContractError(
            f"{path} must be an exact integer in [{minimum}, {maximum}]")
    return value


def frozen_value(value: Any, path: str, *, max_bytes: int | None = None) -> Any:
    try:
        payload = canonical_bytes(value)
        if max_bytes is not None and len(payload) > max_bytes:
            raise ProjectLimitError(f"{path} exceeds {max_bytes} canonical bytes")
        return strict_json_loads(payload)
    except ProjectLimitError:
        raise
    except (CanonicalError, TypeError, ValueError, RecursionError) as exc:
        raise ProjectContractError(f"{path} is not canonical: {exc}") from exc


def frozen_object(value: Any, path: str, *, max_bytes: int | None = None) -> FrozenMap:
    admitted = frozen_value(value, path, max_bytes=max_bytes)
    if type(admitted) is not FrozenMap:
        raise ProjectContractError(f"{path} must be an exact object")
    return admitted


@dataclass(frozen=True, slots=True)
class CoverageV0:
    state: Literal["COMPLETE", "PARTIAL"]
    requested: int
    evaluated: int
    returned: int

    def __post_init__(self) -> None:
        if self.state not in {"COMPLETE", "PARTIAL"}:
            raise ProjectContractError("coverage.state is unsupported")
        for name in ("requested", "evaluated", "returned"):
            exact_int(getattr(self, name), f"coverage.{name}", minimum=0,
                      maximum=1_000_000_000)
        if self.evaluated > self.requested or self.returned > self.evaluated:
            raise ProjectContractError("coverage census is inconsistent")

    def to_data(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "requested": self.requested,
            "returned": self.returned,
            "schema": COVERAGE_SCHEMA,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class ReceiptRefV0:
    receipt_id: str
    receipt_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", exact_identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "receipt_digest",
            exact_digest(self.receipt_digest, "receipt_digest"),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "schema": RECEIPT_REF_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class CursorRefV0:
    cursor_id: str
    cursor_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "cursor_id", exact_identifier(self.cursor_id, "cursor_id"))
        object.__setattr__(
            self, "cursor_digest", exact_digest(self.cursor_digest, "cursor_digest"))

    def to_data(self) -> dict[str, Any]:
        return {
            "cursor_digest": self.cursor_digest,
            "cursor_id": self.cursor_id,
            "schema": CURSOR_REF_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class ReadReceiptV0:
    kind: Literal["PROJECT_READ", "MODEL_QUERY"]
    authority: Literal["OWNER", "INFORMATIONAL"]
    project_id: str
    revision_digest: str
    build_digest: str
    scope: str
    selector: FrozenMap | dict[str, Any]
    present: bool | None
    object_digest: str | None
    result_digest: str
    coverage: CoverageV0
    chain_digest: str | None = None
    _receipt_id: str = field(init=False, repr=False, compare=False)
    _receipt_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in {"PROJECT_READ", "MODEL_QUERY"}:
            raise ProjectContractError("receipt.kind is unsupported")
        if self.authority not in {"OWNER", "INFORMATIONAL"}:
            raise ProjectContractError("receipt.authority is unsupported")
        if type(self.coverage) is not CoverageV0:
            raise ProjectContractError("receipt.coverage must be exact CoverageV0")
        if type(self.present) not in {bool, type(None)}:
            raise ProjectContractError("receipt.present must be bool or null")
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "receipt.project_id"))
        for name in ("revision_digest", "build_digest", "result_digest"):
            object.__setattr__(
                self, name, exact_digest(getattr(self, name), f"receipt.{name}"))
        if self.object_digest is not None:
            object.__setattr__(
                self, "object_digest",
                exact_digest(self.object_digest, "receipt.object_digest"),
            )
        if self.chain_digest is not None:
            object.__setattr__(
                self, "chain_digest",
                exact_digest(self.chain_digest, "receipt.chain_digest"),
            )
        if type(self.scope) is not str or not self.scope:
            raise ProjectContractError("receipt.scope must be exact non-empty text")
        selector = frozen_object(self.selector, "receipt.selector")
        object.__setattr__(self, "selector", selector)
        identity = canonical_digest("kir.ai-project-read-receipt-id.v0", self.body_data())
        object.__setattr__(self, "_receipt_id", f"rr_{identity[7:47]}")
        object.__setattr__(
            self,
            "_receipt_digest",
            canonical_digest(
                "kir.ai-project-read-receipt.v0",
                {**self.body_data(), "receipt_id": self.receipt_id},
            ),
        )

    @property
    def receipt_id(self) -> str:
        return self._receipt_id

    @property
    def receipt_digest(self) -> str:
        return self._receipt_digest

    @property
    def ref(self) -> ReceiptRefV0:
        return ReceiptRefV0(self.receipt_id, self.receipt_digest)

    def body_data(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "build_digest": self.build_digest,
            "chain_digest": self.chain_digest,
            "coverage": self.coverage.to_data(),
            "kind": self.kind,
            "object_digest": self.object_digest,
            "present": self.present,
            "project_id": self.project_id,
            "result_digest": self.result_digest,
            "revision_digest": self.revision_digest,
            "schema": READ_RECEIPT_SCHEMA,
            "scope": self.scope,
            "selector": self.selector,
        }

    def to_data(self) -> dict[str, Any]:
        return {
            **self.body_data(),
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
        }


@dataclass(frozen=True, slots=True)
class CursorRecordV0:
    project_id: str
    revision_digest: str
    build_digest: str
    scope: str
    filters: FrozenMap | dict[str, Any]
    offset: int
    limit: int
    chain_digest: str
    _cursor_id: str = field(init=False, repr=False, compare=False)
    _cursor_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "cursor.project_id"))
        for name in ("revision_digest", "build_digest", "chain_digest"):
            object.__setattr__(
                self, name, exact_digest(getattr(self, name), f"cursor.{name}"))
        if self.scope not in MODEL_QUERY_SCOPES:
            raise ProjectContractError("cursor.scope is unsupported")
        object.__setattr__(self, "filters", frozen_object(
            self.filters, "cursor.filters"))
        exact_int(self.offset, "cursor.offset", minimum=0, maximum=1_000_000_000)
        exact_int(self.limit, "cursor.limit", minimum=1, maximum=MAX_PAGE_ITEMS)
        identity = canonical_digest("kir.ai-model-query-cursor-id.v0", self.body_data())
        object.__setattr__(self, "_cursor_id", f"cur_{identity[7:47]}")
        object.__setattr__(
            self,
            "_cursor_digest",
            canonical_digest(
                "kir.ai-model-query-cursor.v0",
                {**self.body_data(), "cursor_id": self.cursor_id},
            ),
        )

    @property
    def cursor_id(self) -> str:
        return self._cursor_id

    @property
    def cursor_digest(self) -> str:
        return self._cursor_digest

    @property
    def ref(self) -> CursorRefV0:
        return CursorRefV0(self.cursor_id, self.cursor_digest)

    def body_data(self) -> dict[str, Any]:
        return {
            "build_digest": self.build_digest,
            "chain_digest": self.chain_digest,
            "filters": self.filters,
            "limit": self.limit,
            "offset": self.offset,
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
            "schema": CURSOR_RECORD_SCHEMA,
            "scope": self.scope,
        }

    def to_data(self) -> dict[str, Any]:
        return {
            **self.body_data(),
            "cursor_digest": self.cursor_digest,
            "cursor_id": self.cursor_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectReadCommandV0:
    project_id: str
    revision_digest: str
    scope: str
    target_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "project.read.project_id"))
        object.__setattr__(self, "revision_digest", exact_digest(
            self.revision_digest, "project.read.revision_digest"))
        if self.scope not in PROJECT_READ_SCOPES:
            raise ProjectContractError("project.read.scope is unsupported")
        requires_target = self.scope in {"module", "exception"}
        if requires_target != (self.target_id is not None):
            raise ProjectContractError("project.read target does not match scope")
        if self.target_id is not None:
            object.__setattr__(self, "target_id", exact_identifier(
                self.target_id, "project.read.target_id"))

    def to_data(self) -> dict[str, Any]:
        data = {
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
            "schema": PROJECT_READ_COMMAND_SCHEMA,
            "scope": self.scope,
        }
        if self.scope == "module":
            data["module_id"] = self.target_id
        elif self.scope == "exception":
            data["exception_id"] = self.target_id
        return data


@dataclass(frozen=True, slots=True)
class ModelQueryCommandV0:
    project_id: str
    revision_digest: str
    build_digest: str
    scope: str
    filters: FrozenMap | dict[str, Any]
    limit: int
    cursor: CursorRefV0 | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "model.query.project_id"))
        for name in ("revision_digest", "build_digest"):
            object.__setattr__(
                self, name, exact_digest(getattr(self, name), f"model.query.{name}"))
        if self.scope not in MODEL_QUERY_SCOPES:
            raise ProjectContractError("model.query.scope is unsupported")
        exact_int(self.limit, "model.query.limit", minimum=1, maximum=MAX_PAGE_ITEMS)
        if self.cursor is not None and type(self.cursor) is not CursorRefV0:
            raise ProjectContractError("model.query.cursor must be exact CursorRefV0")
        filters = frozen_object(self.filters, "model.query.filters")
        if self.scope == "summary" and len(filters) != 0:
            raise ProjectContractError("summary query requires empty filters")
        if self.scope == "logical_id":
            if tuple(filters) != ("logical_id",):
                raise ProjectContractError("logical_id query requires only logical_id")
            exact_identifier(filters["logical_id"], "model.query.logical_id")
        if self.scope == "origin":
            if not filters or not set(filters).issubset(ORIGIN_FILTER_FIELDS):
                raise ProjectContractError("origin query filters are not exact")
            for name, value in filters.items():
                exact_identifier(value, f"model.query.filters.{name}")
        object.__setattr__(self, "filters", filters)

    def binding_data(self) -> dict[str, Any]:
        return {
            "build_digest": self.build_digest,
            "filters": self.filters,
            "limit": self.limit,
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
            "scope": self.scope,
        }

    def to_data(self) -> dict[str, Any]:
        return {
            **self.binding_data(),
            "cursor": None if self.cursor is None else self.cursor.to_data(),
            "schema": MODEL_QUERY_COMMAND_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class ModulePutV0:
    op_id: str
    module: ModuleV0

    def __post_init__(self) -> None:
        object.__setattr__(self, "op_id", exact_identifier(self.op_id, "op_id"))
        if type(self.module) is not ModuleV0:
            raise ProjectContractError("module.put requires exact ModuleV0")

    @property
    def target_key(self) -> tuple[str, str]:
        return ("module", self.module.module_id)

    def to_data(self) -> dict[str, Any]:
        return {
            "module": self.module.semantic_data(),
            "op_id": self.op_id,
            "schema": MODULE_PUT_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class RootPutV0:
    op_id: str
    root: RootInstanceV0

    def __post_init__(self) -> None:
        object.__setattr__(self, "op_id", exact_identifier(self.op_id, "op_id"))
        if type(self.root) is not RootInstanceV0:
            raise ProjectContractError("root.put requires exact RootInstanceV0")

    @property
    def target_key(self) -> tuple[str, str]:
        return ("root", "root_instance")

    def to_data(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "root": self.root.to_data(), "schema": ROOT_PUT_SCHEMA}


@dataclass(frozen=True, slots=True)
class ExceptionPutV0:
    op_id: str
    exception: SetInstanceArgumentExceptionV0

    def __post_init__(self) -> None:
        object.__setattr__(self, "op_id", exact_identifier(self.op_id, "op_id"))
        if type(self.exception) is not SetInstanceArgumentExceptionV0:
            raise ProjectContractError("exception.put requires exact exception V0")

    @property
    def target_key(self) -> tuple[str, str]:
        return ("exception", self.exception.exception_id)

    def to_data(self) -> dict[str, Any]:
        return {
            "exception": self.exception.to_data(),
            "op_id": self.op_id,
            "schema": EXCEPTION_PUT_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class ExceptionRemoveV0:
    op_id: str
    exception_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "op_id", exact_identifier(self.op_id, "op_id"))
        object.__setattr__(self, "exception_id", exact_identifier(
            self.exception_id, "exception_id"))

    @property
    def target_key(self) -> tuple[str, str]:
        return ("exception", self.exception_id)

    def to_data(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "op_id": self.op_id,
            "schema": EXCEPTION_REMOVE_SCHEMA,
        }


PatchOperationV0: TypeAlias = (
    ModulePutV0 | RootPutV0 | ExceptionPutV0 | ExceptionRemoveV0
)


@dataclass(frozen=True, slots=True)
class SourcePatchCommandV0:
    project_id: str
    base_revision_digest: str
    patch_id: str
    receipt_refs: tuple[ReceiptRefV0, ...] | list[ReceiptRefV0]
    operations: tuple[PatchOperationV0, ...] | list[PatchOperationV0]

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "source.patch.project_id"))
        object.__setattr__(self, "base_revision_digest", exact_digest(
            self.base_revision_digest, "source.patch.base_revision_digest"))
        object.__setattr__(self, "patch_id", exact_identifier(
            self.patch_id, "source.patch.patch_id"))
        refs = tuple(self.receipt_refs)
        if not refs or len(refs) > MAX_RECEIPT_REFS:
            raise ProjectContractError("source.patch receipt_refs census is invalid")
        if any(type(item) is not ReceiptRefV0 for item in refs):
            raise ProjectContractError("source.patch receipt_refs have wrong type")
        refs = tuple(sorted(refs, key=lambda item: item.receipt_id))
        if len({item.receipt_id for item in refs}) != len(refs):
            raise ProjectContractError("source.patch has duplicate receipt_id")
        operations = tuple(self.operations)
        if not operations or len(operations) > MAX_PATCH_OPS:
            raise ProjectContractError("source.patch operations census is invalid")
        allowed = {ModulePutV0, RootPutV0, ExceptionPutV0, ExceptionRemoveV0}
        if any(type(item) not in allowed for item in operations):
            raise ProjectContractError("source.patch has unsupported operation")
        if len({item.op_id for item in operations}) != len(operations):
            raise ProjectContractError("source.patch has duplicate op_id")
        object.__setattr__(self, "receipt_refs", refs)
        object.__setattr__(self, "operations", operations)
        if len(canonical_bytes(self.arguments_data())) > MAX_ARGUMENT_BYTES:
            raise ProjectLimitError("source.patch arguments exceed 1MB")

    def arguments_data(self) -> dict[str, Any]:
        return {
            "base_revision_digest": self.base_revision_digest,
            "operations": tuple(item.to_data() for item in self.operations),
            "patch_id": self.patch_id,
            "project_id": self.project_id,
            "receipt_refs": tuple(item.to_data() for item in self.receipt_refs),
            "schema": SOURCE_PATCH_COMMAND_SCHEMA,
        }

    def to_data(self) -> dict[str, Any]:
        return self.arguments_data()


@dataclass(frozen=True, slots=True)
class ProjectReadResultV0:
    project_id: str
    revision_digest: str
    build_digest: str
    scope: str
    selector: FrozenMap | dict[str, Any]
    present: bool | None
    value: Any
    coverage: CoverageV0
    receipt: ReadReceiptV0
    cursor: None = None

    def __post_init__(self) -> None:
        if type(self.coverage) is not CoverageV0 or type(self.receipt) is not ReadReceiptV0:
            raise ProjectContractError("project.read result has wrong child type")
        object.__setattr__(self, "selector", frozen_object(
            self.selector, "project.read result selector"))
        object.__setattr__(self, "value", frozen_value(
            self.value, "project.read result value"))

    def to_data(self) -> dict[str, Any]:
        return {
            "build_digest": self.build_digest,
            "coverage": self.coverage.to_data(),
            "cursor": None,
            "present": self.present,
            "project_id": self.project_id,
            "receipt": self.receipt.to_data(),
            "revision_digest": self.revision_digest,
            "schema": PROJECT_READ_RESULT_SCHEMA,
            "scope": self.scope,
            "selector": self.selector,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ModelQueryResultV0:
    project_id: str
    revision_digest: str
    build_digest: str
    scope: str
    filters: FrozenMap | dict[str, Any]
    items: tuple[Any, ...] | list[Any]
    coverage: CoverageV0
    cursor: CursorRefV0 | None
    receipt: ReadReceiptV0

    def __post_init__(self) -> None:
        if type(self.coverage) is not CoverageV0 or type(self.receipt) is not ReadReceiptV0:
            raise ProjectContractError("model.query result has wrong child type")
        if self.cursor is not None and type(self.cursor) is not CursorRefV0:
            raise ProjectContractError("model.query result cursor has wrong type")
        if (self.coverage.state == "COMPLETE") != (self.cursor is None):
            raise ProjectContractError("query coverage/cursor invariant failed")
        object.__setattr__(self, "filters", frozen_object(
            self.filters, "model.query result filters"))
        object.__setattr__(self, "items", tuple(
            frozen_value(item, "model.query result item") for item in self.items))

    def to_data(self) -> dict[str, Any]:
        return {
            "build_digest": self.build_digest,
            "coverage": self.coverage.to_data(),
            "cursor": None if self.cursor is None else self.cursor.to_data(),
            "filters": self.filters,
            "items": self.items,
            "project_id": self.project_id,
            "receipt": self.receipt.to_data(),
            "revision_digest": self.revision_digest,
            "schema": MODEL_QUERY_RESULT_SCHEMA,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class SourcePatchResultV0:
    patch_id: str
    semantic_patch_digest: str
    transition_digest: str
    project_id: str
    base_revision_digest: str
    revision_digest: str
    source_digest: str
    build_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_id", exact_identifier(self.patch_id, "patch_id"))
        object.__setattr__(self, "project_id", exact_identifier(
            self.project_id, "project_id"))
        for name in (
            "semantic_patch_digest",
            "transition_digest",
            "base_revision_digest",
            "revision_digest",
            "source_digest",
            "build_digest",
        ):
            object.__setattr__(self, name, exact_digest(getattr(self, name), name))

    def to_data(self) -> dict[str, Any]:
        return {
            "base_revision_digest": self.base_revision_digest,
            "build_digest": self.build_digest,
            "patch_id": self.patch_id,
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
            "schema": SOURCE_PATCH_RESULT_SCHEMA,
            "semantic_patch_digest": self.semantic_patch_digest,
            "source_digest": self.source_digest,
            "transition_digest": self.transition_digest,
        }


__all__ = [
    "CoverageV0",
    "CursorRecordV0",
    "CursorRefV0",
    "ExceptionPutV0",
    "ExceptionRemoveV0",
    "ModelQueryCommandV0",
    "ModelQueryResultV0",
    "ModulePutV0",
    "PatchOperationV0",
    "ProjectReadCommandV0",
    "ProjectReadResultV0",
    "ReadReceiptV0",
    "ReceiptRefV0",
    "RootPutV0",
    "SourcePatchCommandV0",
    "SourcePatchResultV0",
    "exact_digest",
    "exact_identifier",
    "exact_int",
    "frozen_object",
    "frozen_value",
]
