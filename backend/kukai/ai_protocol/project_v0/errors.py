"""Typed failures for the isolated AP02-K project kernel."""
from __future__ import annotations

from typing import Any


class ProjectKernelError(ValueError):
    """Base class for deterministic, caller-safe AP02-K refusals."""

    code = "PROJECT_KERNEL_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = {} if details is None else dict(details)


class ProjectContractError(ProjectKernelError):
    code = "PROJECT_CONTRACT_INVALID"


class ProjectConflictError(ProjectKernelError):
    code = "PROJECT_STATE_CONFLICT"


class PatchContradictionError(ProjectKernelError):
    code = "PATCH_ID_CONTRADICTION"


class ReceiptAuthorityError(ProjectKernelError):
    code = "OWNER_RECEIPT_REQUIRED"


class CursorAuthorityError(ProjectKernelError):
    code = "CURSOR_AUTHORITY_INVALID"


class ProjectLimitError(ProjectKernelError):
    code = "PROJECT_LIMIT_EXCEEDED"


class ProjectApplyError(ProjectKernelError):
    code = "SOURCE_PATCH_REFUSED"


class ProjectQueryError(ProjectKernelError):
    code = "MODEL_QUERY_INVALID"


__all__ = [
    "CursorAuthorityError",
    "PatchContradictionError",
    "ProjectApplyError",
    "ProjectConflictError",
    "ProjectContractError",
    "ProjectKernelError",
    "ProjectLimitError",
    "ProjectQueryError",
    "ReceiptAuthorityError",
]
