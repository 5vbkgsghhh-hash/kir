"""The Will organ — IRON 3, the Evaluator.

KUKAI's deterministic value function over every write's change-set. The
Evaluator answers "did the action do the right thing?" with a verdict
(``pass | partial | fail | unverifiable``) computed PURELY from the action's
args and the bridge's read-back witnesses, plus opt-in read-only probes.

**The one iron rule of this organ (VISION.md I3): it NEVER calls an LLM.**
Every check here is a pure computation or a deterministic read-only probe.
``kukai.agents.error_interpreter`` is LLM-backed and is *constitutionally
excluded* from this package (its home is the W4 repair-reroute lane).

v1 runs in SHADOW: ``kukai.will.shadow.shadow_evaluate`` observes and records a
verdict per write (joined to the turn's telemetry by ``query_id``) and changes
nothing the model can see — no gating, no result mutation, no bridge change at
the default level. See ``plans/020-evaluator-v1.md``.
"""
from __future__ import annotations

from kukai.will.evaluator import (
    Check,
    EvalReport,
    derive_checks,
    evaluate_structural,
)

__all__ = [
    "Check",
    "EvalReport",
    "derive_checks",
    "evaluate_structural",
]
