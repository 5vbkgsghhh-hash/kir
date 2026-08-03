"""Round-trip certification: materialize → re-extract → check (checker v2 keystone).

THE closing of the self-certification loop (roadmap 'Checker correctness & trust',
recommendation 5): a generated/adapted SpatialModel dict is a CLAIM. Its author — the
generator, the fix-loop, or an untrusted LLM — controls every field, so re-checking the
author's own dict can never certify anything. The only verdict that means something for
the real world comes from the round-trip:

    1. materialize(model)  — write REAL Revit elements (generator/materializer.py);
    2. re-extract          — read the world back through the read-only extractor
                             (checker/extractor.py), which the author does not control;
    3. check               — run the v2 engine on the EXTRACTED model.

certify() takes the two world-touching functions as INJECTABLE callables so the seam is
unit-testable without Revit (an honest mock world vs a lying one that drops windows),
and so the live binding stays operator-gated: the default live path only works on the
single authorized device, and the agent-side harness intentionally cannot drive it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from kukai.modeling.checker.engine import run
from kukai.modeling.checker.extractor import normalize
from kukai.modeling.checker.spatial_model import CheckReport, SpatialModel
from kukai.modeling.checker.thresholds import THRESHOLDS, Thresholds


@dataclass
class RoundTripResult:
    """Outcome of one materialize→re-extract→check cycle."""
    certified: bool                 # report.passed on the RE-EXTRACTED model
    report: CheckReport             # the checker's verdict on what the WORLD contains
    extracted: dict                 # the normalized re-extraction (what was verified)
    materialize_result: dict = field(default_factory=dict)  # created ids etc.
    dict_report: CheckReport | None = None   # pre-flight verdict on the input dict


def certify(model_dict: dict,
            materialize_fn: Callable[[dict], dict],
            extract_fn: Callable[[], dict],
            *,
            thr: Thresholds = THRESHOLDS,
            preflight: bool = True) -> RoundTripResult:
    """Certify `model_dict` by building it and checking what actually exists.

    `materialize_fn(model_dict) -> dict` writes the model to the world and returns the
    write receipt (e.g. materializer.materialize bound to the authorized device).
    `extract_fn() -> raw dict` reads the world back (e.g. extractor.run_extractor_cs
    bound to the same device). Both are injected: tests pass mock worlds; the live
    binding is the operator's.

    The returned verdict is computed ONLY from the re-extracted model. The input dict's
    own check (preflight) is advisory — it exists to fail fast before touching Revit,
    never to certify."""
    dict_report: CheckReport | None = None
    if preflight:
        dict_report = run(SpatialModel.model_validate(model_dict), thr)
        if not dict_report.passed:
            # Fail fast: don't build something the checker already rejects on paper.
            return RoundTripResult(
                certified=False, report=dict_report, extracted={},
                materialize_result={}, dict_report=dict_report,
            )

    receipt = materialize_fn(model_dict) or {}
    raw = extract_fn()
    extracted = normalize(raw)
    report = run(SpatialModel.model_validate(extracted), thr)
    return RoundTripResult(
        certified=report.passed,
        report=report,
        extracted=extracted,
        materialize_result=receipt,
        dict_report=dict_report,
    )


def live_bindings(device: str, *, x_off: float | None = None, z_off: float | None = None):
    """Build (materialize_fn, extract_fn) bound to the ONE operator-authorized device.

    Kept as a separate, explicitly-named constructor so the world-touching path is a
    visible, greppable seam: nothing in this module calls it implicitly. Raises inside
    the underlying modules unless `device` is authorized. The live write must be run by
    the operator (the agent harness blocks writes to the multi-tenant Revit endpoint)."""
    from kukai.modeling.checker.extractor import run_extractor_cs
    from kukai.modeling.generator.materializer import (
        X_OFFSET_MM, Z_OFFSET_MM, materialize,
    )
    xo = X_OFFSET_MM if x_off is None else x_off
    zo = Z_OFFSET_MM if z_off is None else z_off

    def _mat(model_dict: dict) -> dict:
        return materialize(model_dict, device, x_off=xo, z_off=zo)

    def _ext() -> dict:
        return run_extractor_cs(device)

    return _mat, _ext
