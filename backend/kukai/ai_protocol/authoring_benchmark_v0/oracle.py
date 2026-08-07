"""Hidden terminal oracle for the tower case.

This module is invoked only after the harness has emitted a terminal signal.
It inspects the retained state independently of model statements and reports
semantic facts rather than trusting stored expected digests alone.
"""
from __future__ import annotations

from typing import Any

from kukai.design_source import canonical_bytes, materialize
from kukai.design_source.examples import make_tower_source

from .schemas import FINAL_BUILD_DIGEST, FINAL_SOURCE_DIGEST


class OracleFailure(AssertionError):
    """Terminal project semantics do not satisfy the pre-registered case."""


def _entity_semantics(build: Any) -> dict[str, bytes]:
    return {
        entity.logical_id: canonical_bytes(entity.content_data())
        for entity in build.entities
    }


def evaluate_tower54_terminal(state: Any) -> dict[str, Any]:
    """Evaluate one terminal ProjectState without using transcript claims."""

    head = state.head
    build = state.build
    initial = make_tower_source(
        n_floors=54,
        exception_floor_key="L027",
        exception_width="36000",
    )
    initial_build = materialize(initial)
    phase_a = make_tower_source(
        n_floors=60,
        width="32000",
        depth="26000",
        height="3000",
        exception_floor_key="L027",
        exception_width="36000",
    )
    phase_a_build = materialize(phase_a)

    failures: list[str] = []
    if head.source_digest != FINAL_SOURCE_DIGEST:
        failures.append("final source digest")
    if build.manifest.build_digest != FINAL_BUILD_DIGEST:
        failures.append("final build digest")
    if head.package_lock_digest != initial.package_lock_digest:
        failures.append("package lock changed")
    if tuple(item.semantic_data() for item in head.modules) != tuple(
        item.semantic_data() for item in initial.modules
    ):
        failures.append("module catalog changed")
    expected_root = {
        "floor_depth": "26000",
        "floor_height": "3000",
        "floor_module": "mod_typical_floor",
        "floor_width": "32000",
        "level_keys": tuple(f"L{index:03d}" for index in range(1, 61)),
    }
    if dict(head.root.arguments.items()) != expected_root:
        failures.append("root intent is not exact")
    if len(head.exceptions) != 1:
        failures.append("exception census")
    else:
        exception = head.exceptions[0]
        if (
            exception.exception_id != "exc_L027"
            or exception.parameter_id != "width"
            or exception.expected_value != "32000"
            or exception.value != "35000"
        ):
            failures.append("L027 exception semantics")
    if len(build.entities) != 360 or len(build.instances) != 61:
        failures.append("terminal entity/instance census")

    initial_semantics = _entity_semantics(initial_build)
    phase_a_semantics = _entity_semantics(phase_a_build)
    final_semantics = _entity_semantics(build)
    preserved_initial_ids = set(initial_semantics).issubset(final_semantics)
    if not preserved_initial_ids:
        failures.append("pre-existing logical IDs were not preserved")
    phase_a_changed_existing = {
        key for key in initial_semantics
        if initial_semantics[key] != phase_a_semantics.get(key)
    }
    phase_a_added = set(phase_a_semantics) - set(initial_semantics)
    phase_b_changed = {
        key for key in phase_a_semantics
        if phase_a_semantics[key] != final_semantics.get(key)
    }
    changed_entities = tuple(
        entity for entity in build.entities if entity.logical_id in phase_b_changed
    )
    changed_level_keys = {
        entity.properties.get("level_key") for entity in changed_entities
    }
    changed_types = sorted(entity.semantic_type for entity in changed_entities)
    if len(phase_a_changed_existing) != 270:
        failures.append("phase A changed-existing census")
    if len(phase_a_added) != 36:
        failures.append("phase A added census")
    if len(phase_b_changed) != 5:
        failures.append("phase B changed census")
    if changed_level_keys != {"L027"}:
        failures.append("phase B escaped L027")
    if changed_types != ["bim.slab", "bim.wall", "bim.wall", "bim.wall", "bim.wall"]:
        failures.append("phase B changed wrong entity types")
    if set(final_semantics) != set(phase_a_semantics):
        failures.append("phase B changed logical ID set")

    if failures:
        raise OracleFailure("; ".join(failures))
    return {
        "entity_count": len(build.entities),
        "forbidden_module_delta": False,
        "forbidden_package_delta": False,
        "instance_count": len(build.instances),
        "ledger": {
            "cursor_count": len(state.cursors),
            "patch_outcome_count": len(state.patch_outcomes),
            "read_receipt_count": len(state.read_receipts),
            "revision_count": len(state.revisions),
        },
        "phase_a_added_entities": len(phase_a_added),
        "phase_a_changed_existing_entities": len(phase_a_changed_existing),
        "phase_b_changed_entities": len(phase_b_changed),
        "phase_b_changed_level": "L027",
        "preserved_initial_logical_ids": len(initial_semantics),
        "schema": "kir-ai-authoring-benchmark-oracle-result/0",
    }


__all__ = ["OracleFailure", "evaluate_tower54_terminal"]
