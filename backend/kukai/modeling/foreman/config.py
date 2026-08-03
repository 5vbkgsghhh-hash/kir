"""Foreman sub-configs (Wave 5 R1).

Group the ~9 optional Foreman.__init__ kwargs into four typed, frozen
pydantic sub-configs so callers configure one capability at a time and
cross-field invariants are enforced at construction.

Mapping (legacy kwarg → sub-config field):

  judge, compile_client_for_repair, reflect_llm   → ForemanRepair
  toolbox, mock_revit_session                     → ForemanVerifiers
  sampling_n, roslyn_check_fn                     → ForemanSampling
  pro_subagent                                    → ForemanRouting

Cross-sub-config rules (e.g. "sampling > 1 requires a Judge") are still
enforced by Foreman's own __init__ — pydantic sub-configs only see their
own fields. The Foreman raises a clear ValueError before any work runs.
"""
from __future__ import annotations
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kukai.modeling.bridge.mock_revit_session import MockRevitSession
from kukai.modeling.foreman.repair_loop import (
    CompileClientProto, JudgeProto, ReflectLLMProto,
)
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.subagent.structural import StructuralSubagent


class ForemanRepair(BaseModel):
    """Reflexion repair-loop wiring (Phase 2 Task 3).

    All three fields go together. Configuring repair partially is a
    silent bug today — the dispatcher checks all-or-nothing at runtime
    and skips the loop if any field is None. We promote that to a
    construction-time validation error.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    judge: JudgeProto = Field(...)
    compile_client_for_repair: CompileClientProto = Field(...)
    reflect_llm: ReflectLLMProto = Field(...)


class ForemanVerifiers(BaseModel):
    """Multi-verifier review wiring (Phase 3 Task 2).

    `toolbox` is required for multi-verifier mode (grids/level lookups).
    `mock_revit_session` is optional — when present, geometry verifier
    runs collision checks against placed elements; otherwise only the
    grid-bounds + level-binding + zero-length checks apply.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    toolbox: ForemanToolBox = Field(...)
    mock_revit_session: MockRevitSession | None = None


class ForemanSampling(BaseModel):
    """Self-consistency sampling wiring (Phase 3 Task 3).

    `n` is the number of CodeProposal candidates the SampledStructural
    Subagent generates per dispatch. `roslyn_check_fn` is an optional
    short-circuit screen that runs before the judge — keeps the LLM
    judge cost off the budget when Roslyn already rejects a candidate.

    NOTE: Cross-config "sampling > 1 requires a Judge" is enforced by
    Foreman.__init__ (sub-configs only see their own fields).
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    n: int = Field(..., ge=1)
    roslyn_check_fn: Callable | None = None


class ForemanRouting(BaseModel):
    """Cascade Flash↔Pro routing wiring (Phase 4 Task 2).

    Optional Pro-tier subagent. When configured, `select_tier` may route
    complex tasks to it; absent, the dispatcher uses `self._subagent`
    for every task.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    pro_subagent: StructuralSubagent | None = None
