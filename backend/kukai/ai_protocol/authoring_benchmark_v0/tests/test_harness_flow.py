from __future__ import annotations

from kukai.ai_protocol.authoring_benchmark_v0.schemas import (
    PHASE_A_BUILD_DIGEST,
    PHASE_A_SOURCE_DIGEST,
    REGISTRY_CANONICAL_BYTES,
    REGISTRY_DIGEST,
)
from kukai.design_source import canonical_bytes, strict_json_loads


def _matrix(transcript):
    return {
        strict_json_loads(item.request_blob)["request_id"]: (
            item,
            strict_json_loads(item.request_blob),
            strict_json_loads(item.response_blob),
        )
        for item in transcript.exchanges
    }


def test_scripted_flow_preserves_every_attempt(conformance_transcript) -> None:
    assert conformance_transcript.terminal_state == "COMPLETED"
    assert len(conformance_transcript.prompts) == 18
    assert len(conformance_transcript.model_outputs) == 18
    assert len(conformance_transcript.exchanges) == 20
    assert [item.seq for item in conformance_transcript.exchanges] == list(range(1, 21))


def test_full_registry_is_visible_and_budgeted(conformance_transcript) -> None:
    matrix = _matrix(conformance_transcript)
    exchange, _request, response = matrix["cap_1"]
    assert exchange.model_visible is True
    assert len(canonical_bytes(response["result"])) == REGISTRY_CANONICAL_BYTES
    assert response["result"]["registry_digest"] == REGISTRY_DIGEST
    assert exchange.response_bytes > REGISTRY_CANONICAL_BYTES


def test_phase_a_is_compact_and_exact(conformance_transcript) -> None:
    _exchange, request, response = _matrix(conformance_transcript)["patch_phase_a"]
    assert response["status"] == "OK"
    assert response["result"]["source_digest"] == PHASE_A_SOURCE_DIGEST
    assert response["result"]["build_digest"] == PHASE_A_BUILD_DIGEST
    assert len(request["arguments"]["operations"]) == 2
    assert len(request["arguments"]["receipt_refs"]) == 4


def test_environment_event_is_delivered_only_after_stale_output(
    conformance_transcript,
) -> None:
    matrix = _matrix(conformance_transcript)
    hidden, _, hidden_response = matrix["env_read_root_3100"]
    visible, _, visible_response = matrix["env_patch_height_3100"]
    stale, _, stale_response = matrix["patch_phase_b_stale"]
    assert hidden.seq == 13 and hidden.model_visible is False
    assert visible.seq == 14 and visible.model_visible is True
    assert stale.seq == 15 and stale_response["status"] == "CONFLICT"
    assert visible_response["status"] == hidden_response["status"] == "OK"
    assert conformance_transcript.prompts[12].visible_exchange_seqs == (12,)
    assert conformance_transcript.prompts[13].visible_exchange_seqs == (14, 15)


def test_recovery_rereads_all_owner_objects(conformance_transcript) -> None:
    matrix = _matrix(conformance_transcript)
    for name in (
        "read_root_recovery", "read_mod_building_recovery",
        "read_mod_floor_recovery", "read_exc_recovery",
    ):
        assert matrix[name][2]["read_receipt"]["authority"] == "OWNER"
    request = matrix["patch_phase_b_recovery"][1]
    assert len(request["arguments"]["receipt_refs"]) == 4
    root = request["arguments"]["operations"][0]["root"]
    assert root["arguments"]["floor_height"] == "3000"


def test_conformance_budget_receipt_is_exact(conformance_report) -> None:
    assert conformance_report.model_attempts == 18
    assert conformance_report.cumulative_request_bytes == 9724
    assert conformance_report.model_visible_response_bytes == 220493
    assert conformance_report.unique_build_entities == 0
