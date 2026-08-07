from __future__ import annotations

import pytest

from kukai.ai_protocol.authoring_benchmark_v0.case_tower54 import tower54_case
from kukai.ai_protocol.authoring_benchmark_v0.contracts import (
    BenchmarkContractError,
    BenchmarkReportV0,
    BenchmarkSuiteReportV0,
    ModelOutputV0,
    TranscriptV0,
    WireExchangeV0,
    b64url_decode,
    b64url_encode,
    sha256_bytes,
)
from kukai.ai_protocol.authoring_benchmark_v0.schemas import (
    CASE_SCHEMA,
    MODEL_OUTPUT_SCHEMA,
    PROMPT_EVENT_SCHEMA,
    REPORT_SCHEMA,
    RUN_HEADER_SCHEMA,
    SUITE_REPORT_SCHEMA,
    TRANSCRIPT_SCHEMA,
    WIRE_EXCHANGE_SCHEMA,
)
from kukai.design_source import canonical_bytes


def test_all_eight_evidence_schemas_are_closed_and_unique() -> None:
    names = (
        CASE_SCHEMA, RUN_HEADER_SCHEMA, PROMPT_EVENT_SCHEMA,
        MODEL_OUTPUT_SCHEMA, WIRE_EXCHANGE_SCHEMA, TRANSCRIPT_SCHEMA,
        REPORT_SCHEMA, SUITE_REPORT_SCHEMA,
    )
    assert len(names) == len(set(names)) == 8
    assert all(name.startswith("kir-ai-authoring-benchmark-") for name in names)


def test_case_round_trip_and_digest_are_exact() -> None:
    case = tower54_case()
    rebuilt = type(case).from_data(case.to_data())
    assert canonical_bytes(rebuilt.to_data()) == canonical_bytes(case.to_data())
    assert rebuilt.case_digest == case.case_digest


def test_raw_model_output_is_preserved_before_adaptation() -> None:
    request = '{"arguments":{},"protocol":"kir-ai/0","request_id":"r","tool":"capabilities.get"}'
    raw = canonical_bytes({
        "request_json": request,
        "schema": MODEL_OUTPUT_SCHEMA,
    }).decode()
    output = ModelOutputV0.admit_raw(1, raw)
    assert output.raw_output_json == raw
    assert output.request_json == request
    assert output.raw_output_sha256 == sha256_bytes(raw.encode())
    assert ModelOutputV0.from_data(output.to_data()) == output


@pytest.mark.parametrize("raw", (
    '{}',
    '{"request_json":"{}","schema":"wrong/0"}',
    '{"extra":1,"request_json":"{}","schema":"kir-ai-authoring-benchmark-model-output/0"}',
))
def test_raw_model_output_rejects_open_or_wrong_shapes(raw: str) -> None:
    with pytest.raises(BenchmarkContractError):
        ModelOutputV0.admit_raw(1, raw)


def test_base64url_is_canonical_unpadded() -> None:
    blob = b"exact bytes"
    encoded = b64url_encode(blob)
    assert "=" not in encoded
    assert b64url_decode(encoded) == blob
    with pytest.raises(BenchmarkContractError):
        b64url_decode(encoded + "=")


def test_wire_exchange_binds_hashes_lengths_and_chain() -> None:
    digest = "sha256:" + "0" * 64
    exchange = WireExchangeV0.create(
        seq=1, actor="MODEL", model_visible=True, provider_invocation=1,
        request=b"{}", response=b"{}", before_state_digest=digest,
        after_state_digest=digest, previous_exchange_digest=None,
    )
    rebuilt = WireExchangeV0.from_data(exchange.to_data())
    assert rebuilt.request_blob == b"{}"
    assert rebuilt.response_blob == b"{}"
    data = exchange.to_data()
    data["request_bytes"] += 1
    with pytest.raises(BenchmarkContractError):
        WireExchangeV0.from_data(data)


def test_transcript_and_reports_round_trip_exactly(
    conformance_transcript, conformance_report,
) -> None:
    transcript = TranscriptV0.from_data(conformance_transcript.to_data())
    report = BenchmarkReportV0.from_data(conformance_report.to_data())
    suite = BenchmarkSuiteReportV0((report,))
    assert transcript.transcript_digest == conformance_transcript.transcript_digest
    assert BenchmarkSuiteReportV0.from_data(suite.to_data()) == suite


def test_ai_benchmark_pass_is_not_an_admitted_harness_status(
    conformance_report,
) -> None:
    values = dict(conformance_report.__dict__) if hasattr(conformance_report, "__dict__") else None
    assert values is None  # slots prevent an open mutable status bag
    with pytest.raises(BenchmarkContractError):
        BenchmarkReportV0(
            conformance_report.run_id,
            conformance_report.transcript_digest,
            "AI_BENCHMARK_PASS",
            conformance_report.final_state_digest,
            conformance_report.final_source_digest,
            conformance_report.final_build_digest,
            conformance_report.model_attempts,
            conformance_report.cumulative_request_bytes,
            conformance_report.model_visible_response_bytes,
            conformance_report.unique_build_entities,
            conformance_report.oracle,
        )
