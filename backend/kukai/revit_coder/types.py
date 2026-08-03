"""Types for revit_coder module — strict dataclasses, no any-typed dicts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Optional


@dataclass
class ModelContext:
    """Minimum context Gemini passes about the Revit model state.

    All fields optional. Backend auto-fills from get_model_info() when missing.
    Pass only what affects WHICH API to use (e.g. revit_version) or
    WHICH elements to operate on (e.g. selected_element_ids).
    """
    revit_version: Optional[str] = None         # "2024" | "2025" | "2026"
    active_view_id: Optional[int] = None
    active_view_type: Optional[str] = None      # "FloorPlan" | "Section" | "ThreeD"
    project_units: Optional[str] = None         # "Millimeters" | "Feet"
    selected_element_ids: Optional[list[int]] = None
    document_title: Optional[str] = None

    def to_dict(self) -> dict:
        """Compact dict — None fields omitted, for prompt injection."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RevitCoderResult:
    """Output of revit-coder generation call."""
    code: str
    finish_reason: Literal["stop", "length", "error"]
    latency_ms: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    node_used: Optional[str] = None             # "kaggle-1" | "kaggle-2" | None on error


class RevitCoderError(Exception):
    """Raised when revit-coder is unavailable (Kaggle 503, network, auth, etc).

    In Phase 1: NO fallback to Gemini-as-coder. User sees error directly.
    """
    pass


__all__ = ["ModelContext", "RevitCoderResult", "RevitCoderError"]
