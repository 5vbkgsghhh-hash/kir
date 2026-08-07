from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from kukai.ai_protocol.authoring_benchmark_v0.contracts import (
    BenchmarkCaseV0,
    BenchmarkContractError,
    ModelOutputV0,
    PromptEventV0,
    TranscriptV0,
    WireExchangeV0,
)
from kukai.ai_protocol.authoring_benchmark_v0.schemas import MODEL_OUTPUT_SCHEMA
from kukai.ai_protocol.authoring_benchmark_v0.verifier import (
    TranscriptVerificationError,
    _fresh_replay,
    verify_transcript,
)
from kukai.design_source import canonical_bytes, strict_json_loads


def _rechain(exchanges):
    result = []
    previous = None
    for seq, item in enumerate(exchanges, 1):
        rebuilt = WireExchangeV0.create(
            seq=seq,
            actor=item.actor,
            model_visible=item.model_visible,
            provider_invocation=item.provider_invocation,
            request=item.request_blob,
            response=item.response_blob,
            before_state_digest=item.before_state_digest,
            after_state_digest=item.after_state_digest,
            previous_exchange_digest=previous,
        )
        result.append(rebuilt)
        previous = rebuilt.exchange_digest
    return tuple(result)


def _transcript(base, *, case=None, header=None, prompts=None, outputs=None, exchanges=None):
    return TranscriptV0(
        base.case if case is None else case,
        base.header if header is None else header,
        base.prompts if prompts is None else prompts,
        base.model_outputs if outputs is None else outputs,
        base.exchanges if exchanges is None else exchanges,
        base.terminal_state,
    )


def _mutate_request(base, request_id, mutation):
    exchanges = list(base.exchanges)
    outputs = list(base.model_outputs)
    for index, exchange in enumerate(exchanges):
        request = strict_json_loads(exchange.request_blob)
        if request["request_id"] != request_id:
            continue
        mutable = json.loads(canonical_bytes(request))
        mutation(mutable)
        request_blob = canonical_bytes(mutable)
        exchanges[index] = WireExchangeV0.create(
            seq=exchange.seq,
            actor=exchange.actor,
            model_visible=exchange.model_visible,
            provider_invocation=exchange.provider_invocation,
            request=request_blob,
            response=exchange.response_blob,
            before_state_digest=exchange.before_state_digest,
            after_state_digest=exchange.after_state_digest,
            previous_exchange_digest=exchange.previous_exchange_digest,
        )
        invocation = exchange.provider_invocation
        raw = canonical_bytes({
            "request_json": request_blob.decode(),
            "schema": MODEL_OUTPUT_SCHEMA,
        }).decode()
        outputs[invocation - 1] = ModelOutputV0.admit_raw(invocation, raw)
        return _transcript(
            base, outputs=tuple(outputs), exchanges=_rechain(exchanges))
    raise AssertionError("request not found")


@pytest.mark.parametrize("mode", ("remove", "reorder", "duplicate"))
def test_deleted_reordered_or_duplicated_exchange_is_rejected(
    conformance_transcript, mode,
) -> None:
    exchanges = list(conformance_transcript.exchanges)
    if mode == "remove":
        del exchanges[12]
    elif mode == "reorder":
        exchanges[12], exchanges[13] = exchanges[13], exchanges[12]
    else:
        exchanges.insert(12, exchanges[11])
    forged = _transcript(conformance_transcript, exchanges=tuple(exchanges))
    with pytest.raises(TranscriptVerificationError):
        verify_transcript(forged)


def test_response_byte_tamper_is_rejected_at_contract_boundary(
    transcript_data,
) -> None:
    transcript_data["exchanges"][0]["response_b64url"] = "e30"
    with pytest.raises(BenchmarkContractError):
        TranscriptV0.from_data(transcript_data)


def test_adapter_request_mutation_is_detected(conformance_transcript) -> None:
    outputs = list(conformance_transcript.model_outputs)
    original = outputs[0]
    request = json.loads(original.request_json)
    request["request_id"] = "adapter_changed"
    raw = canonical_bytes({
        "request_json": canonical_bytes(request).decode(),
        "schema": MODEL_OUTPUT_SCHEMA,
    }).decode()
    outputs[0] = ModelOutputV0.admit_raw(1, raw)
    forged = _transcript(conformance_transcript, outputs=tuple(outputs))
    with pytest.raises(TranscriptVerificationError, match="adapter changed"):
        verify_transcript(forged)


@pytest.mark.parametrize("kind", ("forged", "informational", "stale"))
def test_forged_informational_or_stale_receipt_is_rejected(
    conformance_transcript, kind,
) -> None:
    responses = {
        strict_json_loads(item.request_blob)["request_id"]:
        strict_json_loads(item.response_blob)
        for item in conformance_transcript.exchanges
    }

    def mutation(request):
        ref = request["arguments"]["receipt_refs"][0]
        if kind == "forged":
            ref["receipt_digest"] = "sha256:" + "0" * 64
        else:
            source = (
                responses["read_manifest_a"]["read_receipt"]
                if kind == "informational"
                else responses["read_root_a"]["read_receipt"]
            )
            ref["receipt_id"] = source["receipt_id"]
            ref["receipt_digest"] = source["receipt_digest"]

    target = "patch_phase_a" if kind != "stale" else "patch_phase_b_recovery"
    forged = _mutate_request(conformance_transcript, target, mutation)
    with pytest.raises(TranscriptVerificationError, match="OWNER reads"):
        verify_transcript(forged)


def test_same_patch_id_with_changed_semantics_is_rejected(
    conformance_transcript,
) -> None:
    def mutation(request):
        request["arguments"]["operations"][0]["root"]["arguments"][
            "floor_width"] = "33000"

    forged = _mutate_request(
        conformance_transcript, "patch_phase_a", mutation)
    with pytest.raises(TranscriptVerificationError, match="operation set"):
        verify_transcript(forged)


@pytest.mark.parametrize("field", (
    "exception_id", "target_instance_id", "parameter_id", "patch_id", "op_id",
))
def test_self_consistent_stale_identity_tamper_is_rejected(
    conformance_transcript,
    field,
) -> None:
    def mutation(request):
        operation = request["arguments"]["operations"][0]
        if field == "patch_id":
            request["arguments"]["patch_id"] = "phase_b_stale_other"
        elif field == "op_id":
            operation["op_id"] = "phase_b_stale.other"
        elif field == "exception_id":
            operation["exception"][field] = "exc_other"
        elif field == "target_instance_id":
            operation["exception"][field] = "inst_forged"
        else:
            operation["exception"][field] = "depth"

    forged = _mutate_request(
        conformance_transcript, "patch_phase_b_stale", mutation)
    with pytest.raises(TranscriptVerificationError, match="canonically exact"):
        verify_transcript(forged)


@pytest.mark.parametrize("field", (
    "provider", "model", "model_fingerprint", "inference_config",
))
def test_scripted_run_header_reattribution_is_rejected(
    conformance_transcript,
    field,
) -> None:
    value = {
        "provider": "other_provider",
        "model": "other_model",
        "model_fingerprint": "untrusted-relabel",
        "inference_config": {
            "claims_ai_benchmark_pass": False,
            "temperature": 1,
            "transport": "kir_wire(request_json:string)->raw_response_json",
        },
    }[field]
    header = replace(conformance_transcript.header, **{field: value})
    forged = _transcript(conformance_transcript, header=header)
    with pytest.raises(TranscriptVerificationError, match="scripted header"):
        verify_transcript(forged)


def test_missing_environment_causal_exchange_is_rejected(
    conformance_transcript,
) -> None:
    exchanges = [
        item for item in conformance_transcript.exchanges
        if strict_json_loads(item.request_blob)["request_id"] != "env_read_root_3100"
    ]
    forged = _transcript(
        conformance_transcript, exchanges=_rechain(exchanges))
    with pytest.raises(TranscriptVerificationError):
        verify_transcript(forged)


def test_initial_prompt_target_or_oracle_leak_is_rejected(
    conformance_transcript,
) -> None:
    prompts = list(conformance_transcript.prompts)
    prompts[0] = PromptEventV0(
        1, prompts[0].prompt_text + " inst_hidden", ())
    forged = _transcript(conformance_transcript, prompts=tuple(prompts))
    with pytest.raises(TranscriptVerificationError):
        verify_transcript(forged)


def test_transcript_from_another_fixture_is_rejected(
    conformance_transcript,
) -> None:
    original = conformance_transcript.case
    other = BenchmarkCaseV0(
        "other_fixture", original.initial_source_digest,
        original.initial_build_digest, original.expected_final_source_digest,
        original.expected_final_build_digest, original.task, original.limits,
    )
    header = replace(
        conformance_transcript.header,
        case_id=other.case_id,
        case_digest=other.case_digest,
    )
    forged = _transcript(conformance_transcript, case=other, header=header)
    with pytest.raises(TranscriptVerificationError, match="pre-registered"):
        verify_transcript(forged)


def test_hidden_direct_state_transition_fails_fresh_replay(
    conformance_transcript,
) -> None:
    first = conformance_transcript.exchanges[0]
    forged = WireExchangeV0.create(
        seq=1, actor=first.actor, model_visible=first.model_visible,
        provider_invocation=first.provider_invocation,
        request=first.request_blob, response=first.response_blob,
        before_state_digest=first.before_state_digest,
        after_state_digest="sha256:" + "f" * 64,
        previous_exchange_digest=None,
    )
    with pytest.raises(TranscriptVerificationError, match="after-state"):
        _fresh_replay(SimpleNamespace(exchanges=(forged,)))
