from __future__ import annotations

import json
from pathlib import Path

from kukai.ai_protocol.authoring_benchmark_v0.schemas import (
    FINAL_BUILD_DIGEST,
    FINAL_SOURCE_DIGEST,
    INITIAL_BUILD_DIGEST,
    INITIAL_SOURCE_DIGEST,
    PHASE_A_BUILD_DIGEST,
    PHASE_A_SOURCE_DIGEST,
)


def test_hidden_oracle_proves_terminal_census_and_identity(conformance_report) -> None:
    oracle = conformance_report.oracle
    assert oracle["entity_count"] == 360
    assert oracle["instance_count"] == 61
    assert oracle["preserved_initial_logical_ids"] == 324
    assert oracle["forbidden_module_delta"] is False
    assert oracle["forbidden_package_delta"] is False


def test_hidden_oracle_proves_phase_semantics(conformance_report) -> None:
    oracle = conformance_report.oracle
    assert oracle["phase_a_changed_existing_entities"] == 270
    assert oracle["phase_a_added_entities"] == 36
    assert oracle["phase_b_changed_entities"] == 5
    assert oracle["phase_b_changed_level"] == "L027"


def test_frozen_fixture_receipt_is_bound_to_authoritative_constants() -> None:
    path = Path(__file__).with_name("fixtures") / "tower54_expected.json"
    with path.open("r", encoding="utf-8") as stream:
        fixture = json.load(stream)
    assert fixture == {
        "case_id": "tower-reshape-54-v0",
        "final_build_digest": FINAL_BUILD_DIGEST,
        "final_entity_count": 360,
        "final_instance_count": 61,
        "final_source_digest": FINAL_SOURCE_DIGEST,
        "initial_build_digest": INITIAL_BUILD_DIGEST,
        "initial_source_digest": INITIAL_SOURCE_DIGEST,
        "phase_a_build_digest": PHASE_A_BUILD_DIGEST,
        "phase_a_source_digest": PHASE_A_SOURCE_DIGEST,
        "schema": "kir-ai-authoring-benchmark-fixture-receipt/0",
    }
