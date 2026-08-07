"""Pre-registered AP03 tower reshape case and model-visible bootstrap."""
from __future__ import annotations

from kukai.design_source import SourceRevisionV0, canonical_bytes
from kukai.design_source.examples import make_tower_source

from .contracts import BenchmarkCaseV0, RunHeaderV0
from .schemas import (
    CASE_ID,
    FINAL_BUILD_DIGEST,
    FINAL_SOURCE_DIGEST,
    INITIAL_BUILD_DIGEST,
    INITIAL_SOURCE_DIGEST,
    MAX_CUMULATIVE_REQUEST_BYTES,
    MAX_MODEL_ATTEMPTS,
    MAX_MODEL_VISIBLE_RESPONSE_BYTES,
    MAX_UNIQUE_BUILD_ENTITIES,
    HARNESS_VERSION,
    REGISTRY_DIGEST,
)


def initial_source() -> SourceRevisionV0:
    """Return a fresh exact fixture; it is the sole host bootstrap input."""

    source = make_tower_source(
        n_floors=54,
        exception_floor_key="L027",
        exception_width="36000",
    )
    if source.source_digest != INITIAL_SOURCE_DIGEST:
        raise RuntimeError("AP03 initial fixture source digest drifted")
    return source


def tower54_case() -> BenchmarkCaseV0:
    return BenchmarkCaseV0(
        case_id=CASE_ID,
        initial_source_digest=INITIAL_SOURCE_DIGEST,
        initial_build_digest=INITIAL_BUILD_DIGEST,
        expected_final_source_digest=FINAL_SOURCE_DIGEST,
        expected_final_build_digest=FINAL_BUILD_DIGEST,
        task={
            "environment_conflict": {
                "field": "floor_height",
                "injected_value": "3100",
                "required_final_value": "3000",
            },
            "phase_a": {
                "depth": "26000",
                "height": "3000",
                "level_keys": tuple(f"L{index:03d}" for index in range(1, 61)),
                "preserve_exception_floor": "L027",
                "preserve_exception_width": "36000",
                "width": "32000",
            },
            "phase_b": {
                "exception_floor": "L027",
                "exception_width": "35000",
            },
            "prohibited": (
                "module mutation",
                "package lock mutation",
                "full BuildGraph retrieval",
            ),
        },
        limits={
            "max_cumulative_request_bytes": MAX_CUMULATIVE_REQUEST_BYTES,
            "max_model_attempts": MAX_MODEL_ATTEMPTS,
            "max_model_visible_response_bytes": MAX_MODEL_VISIBLE_RESPONSE_BYTES,
            "max_unique_build_entities": MAX_UNIQUE_BUILD_ENTITIES,
        },
    )


def scripted_run_header() -> RunHeaderV0:
    """Return the exact non-provider header admitted for scripted conformance."""

    case = tower54_case()
    return RunHeaderV0(
        run_id="scripted_tower54_001",
        case_id=case.case_id,
        case_digest=case.case_digest,
        harness_version=HARNESS_VERSION,
        provider="scripted",
        model="scripted_tower54_v0",
        model_fingerprint="deterministic-harness-client-only",
        inference_config={
            "claims_ai_benchmark_pass": False,
            "temperature": 0,
            "transport": "kir_wire(request_json:string)->raw_response_json",
        },
        registry_digest=REGISTRY_DIGEST,
    )


def initial_prompt() -> str:
    """Exact model-visible task bootstrap; no target instance or oracle digest."""

    source = initial_source()
    payload = {
        "bootstrap": {
            "project_id": source.project_id,
            "revision_digest": source.revision_digest,
        },
        "instructions": (
            "Use only kir_wire. Send complete four-field kir-ai/0 requests. "
            "Inspect owner objects before patching. Preserve modules and package "
            "lock. Complete phase A, then change only L027 local width to 35000. "
            "A concurrent exact wire event may occur; on conflict reread current "
            "owner objects and restore the requested final intent."
        ),
        "task": tower54_case().task,
    }
    return canonical_bytes(payload).decode("utf-8")


__all__ = [
    "initial_prompt", "initial_source", "scripted_run_header", "tower54_case",
]
