"""Isolated transport-neutral AP02-K project kernel.

Importing this package does not register tools or make them reachable from the
AP-01 wire surface.
"""
from .contracts import (
    CoverageV0,
    CursorRecordV0,
    CursorRefV0,
    ExceptionPutV0,
    ExceptionRemoveV0,
    ModelQueryCommandV0,
    ModelQueryResultV0,
    ModulePutV0,
    ProjectReadCommandV0,
    ProjectReadResultV0,
    ReadReceiptV0,
    ReceiptRefV0,
    RootPutV0,
    SourcePatchCommandV0,
    SourcePatchResultV0,
)
from .errors import (
    CursorAuthorityError,
    PatchContradictionError,
    ProjectApplyError,
    ProjectConflictError,
    ProjectContractError,
    ProjectKernelError,
    ProjectLimitError,
    ProjectQueryError,
    ReceiptAuthorityError,
)
from .source_codec import (
    parse_exception,
    parse_model_query_command,
    parse_module,
    parse_project_read_command,
    parse_root,
    parse_source_patch_command,
)
from .query import model_query
from .reads import project_read
from .patches import source_patch
from .index import ProjectBuildIndexV0
from .state import (
    KernelTransitionV0,
    PatchOutcomeRecordV0,
    ProjectStateV0,
    create_project_state,
)


__all__ = [
    "CoverageV0",
    "CursorAuthorityError",
    "CursorRecordV0",
    "CursorRefV0",
    "ExceptionPutV0",
    "ExceptionRemoveV0",
    "KernelTransitionV0",
    "ModelQueryCommandV0",
    "ModelQueryResultV0",
    "ModulePutV0",
    "PatchOutcomeRecordV0",
    "PatchContradictionError",
    "ProjectApplyError",
    "ProjectBuildIndexV0",
    "ProjectConflictError",
    "ProjectContractError",
    "ProjectKernelError",
    "ProjectLimitError",
    "ProjectQueryError",
    "ProjectReadCommandV0",
    "ProjectReadResultV0",
    "ProjectStateV0",
    "ReadReceiptV0",
    "ReceiptAuthorityError",
    "ReceiptRefV0",
    "RootPutV0",
    "SourcePatchCommandV0",
    "SourcePatchResultV0",
    "create_project_state",
    "model_query",
    "parse_exception",
    "parse_model_query_command",
    "parse_module",
    "parse_project_read_command",
    "parse_root",
    "parse_source_patch_command",
    "project_read",
    "source_patch",
]
