from __future__ import annotations

from kukai.ai_protocol.authoring_benchmark_v0.schemas import (
    FINAL_BUILD_DIGEST,
    FINAL_SOURCE_DIGEST,
)


def test_fresh_host_byte_replay_recomputes_harness_conformance(
    conformance_report,
) -> None:
    assert conformance_report.status == "HARNESS_CONFORMANCE"
    assert conformance_report.final_source_digest == FINAL_SOURCE_DIGEST
    assert conformance_report.final_build_digest == FINAL_BUILD_DIGEST


def test_replay_receipt_cursor_patch_ledgers_are_exact(conformance_report) -> None:
    assert dict(conformance_report.oracle["ledger"].items()) == {
        "cursor_count": 0,
        "patch_outcome_count": 3,
        "read_receipt_count": 14,
        "revision_count": 4,
    }


def test_scripted_evidence_hashes_are_frozen(
    conformance_transcript, conformance_report,
) -> None:
    assert conformance_transcript.transcript_digest == (
        "sha256:3557c6b86185bbc629044cc0562c94223"
        "b74946c94be162181f3ce16720d203d"
    )
    assert conformance_report.report_digest == (
        "sha256:c81e1534ef3f4dae914310c9ea89def2"
        "2f01e09d2a860390d7277fde6419dbff"
    )
