"""Identifier value types for the modeling engine.

XYZ: immutable 3D point in project-base-point coordinates (millimeters).
deterministic_task_uuid: stable UUID derived from (project_id, phase, seq).
"""
from __future__ import annotations
import hashlib
from pydantic import BaseModel, ConfigDict


class XYZ(BaseModel):
    """3D point in project base point coordinates, units = millimeters."""
    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    z: float


def deterministic_task_uuid(project_id: str, phase: str, task_seq: int) -> str:
    """Return a stable 16-char hex UUID for a task identity.

    Used for idempotency: retrying a crashed task produces the same UUID, so
    the orchestrator can detect prior completion in the event log.

    Per spec Section 3.5.
    """
    key = f"{project_id}/{phase}/{task_seq}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:16]
