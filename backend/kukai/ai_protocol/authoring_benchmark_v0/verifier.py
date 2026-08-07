"""Fresh-host byte replay and independent AP03 report construction."""
from __future__ import annotations

from typing import Any

from kukai.ai_protocol.project_v0.wire_v0 import OfflineProjectWireV0
from kukai.design_source import FrozenMap, canonical_bytes, strict_json_loads

from .case_tower54 import (
    initial_prompt,
    initial_source,
    scripted_run_header,
    tower54_case,
)
from .contracts import (
    BenchmarkContractError,
    BenchmarkReportV0,
    TranscriptV0,
    WireExchangeV0,
)
from .harness import _budget_state, _prompt_for_visible
from .oracle import OracleFailure, evaluate_tower54_terminal
from .schemas import (
    FINAL_BUILD_DIGEST,
    FINAL_SOURCE_DIGEST,
    MAX_CUMULATIVE_REQUEST_BYTES,
    MAX_MODEL_ATTEMPTS,
    MAX_MODEL_VISIBLE_RESPONSE_BYTES,
    MAX_UNIQUE_BUILD_ENTITIES,
    PHASE_A_BUILD_DIGEST,
    PHASE_A_SOURCE_DIGEST,
    PROTOCOL_VERSION,
    REGISTRY_CANONICAL_BYTES,
    REGISTRY_DIGEST,
)


class TranscriptVerificationError(AssertionError):
    """A transcript is incomplete, forged, over-budget, or non-replayable."""


def _fail(message: str) -> None:
    raise TranscriptVerificationError(message)


def _decode(blob: bytes, path: str) -> FrozenMap:
    try:
        value = strict_json_loads(blob)
    except Exception as exc:
        raise TranscriptVerificationError(f"{path} is not strict JSON") from exc
    if type(value) is not FrozenMap:
        _fail(f"{path} must be an object")
    return value


def _exact_known_case(transcript: TranscriptV0) -> None:
    expected = tower54_case()
    if canonical_bytes(transcript.case.to_data()) != canonical_bytes(expected.to_data()):
        _fail("case is not the pre-registered tower fixture")
    header = transcript.header
    expected_header = scripted_run_header()
    if canonical_bytes(header.to_data()) != canonical_bytes(
        expected_header.to_data()
    ):
        _fail("run header is not the exact pre-registered scripted header")
    if transcript.terminal_state != "COMPLETED":
        _fail("only a complete transcript can claim harness conformance")


def _exact_chain(transcript: TranscriptV0) -> None:
    previous: str | None = None
    for expected_seq, exchange in enumerate(transcript.exchanges, 1):
        if exchange.seq != expected_seq:
            _fail("wire exchange sequence is not continuous")
        if exchange.previous_exchange_digest != previous:
            _fail("wire exchange hash chain is broken")
        previous = exchange.exchange_digest


def _expected_visible(
    model_exchanges: dict[int, WireExchangeV0],
    exchanges: tuple[WireExchangeV0, ...],
    invocation: int,
) -> tuple[WireExchangeV0, ...]:
    if invocation == 1:
        return ()
    lower = 0 if invocation == 2 else model_exchanges[invocation - 2].seq
    upper = model_exchanges[invocation - 1].seq
    return tuple(
        item for item in exchanges
        if lower < item.seq <= upper and item.model_visible
    )


def _exact_prompts_and_outputs(transcript: TranscriptV0) -> None:
    model_exchanges = {
        item.provider_invocation: item
        for item in transcript.exchanges if item.actor == "MODEL"
    }
    invocation_count = len(transcript.model_outputs)
    expected_invocations = tuple(range(1, invocation_count + 1))
    if tuple(item.invocation for item in transcript.prompts) != expected_invocations:
        _fail("prompt invocation ledger is incomplete or reordered")
    if tuple(item.invocation for item in transcript.model_outputs) != expected_invocations:
        _fail("raw model output ledger is incomplete or reordered")
    if tuple(sorted(model_exchanges)) != expected_invocations:
        _fail("model wire invocation ledger is incomplete")

    for prompt in transcript.prompts:
        expected = _expected_visible(
            model_exchanges, transcript.exchanges, prompt.invocation)
        if prompt.visible_exchange_seqs != tuple(item.seq for item in expected):
            _fail("prompt visibility ledger is not causally exact")
        expected_text = (
            initial_prompt()
            if prompt.invocation == 1
            else _prompt_for_visible(expected)
        )
        if prompt.prompt_text != expected_text:
            _fail("stored prompt differs from exact visible wire evidence")

    first_prompt = transcript.prompts[0].prompt_text
    if (
        "inst_" in first_prompt
        or FINAL_SOURCE_DIGEST in first_prompt
        or FINAL_BUILD_DIGEST in first_prompt
    ):
        _fail("initial prompt leaks target identity or oracle digest")

    outputs = {item.invocation: item for item in transcript.model_outputs}
    for invocation, exchange in model_exchanges.items():
        output = outputs[invocation]
        if output.request_json.encode("utf-8") != exchange.request_blob:
            _fail("adapter changed model request bytes")


def _request_response_matrix(transcript: TranscriptV0) -> None:
    expected = (
        ("MODEL", "cap_1", "capabilities.get", True),
        ("MODEL", "read_manifest_a", "project.read", True),
        ("MODEL", "read_exc_index_a", "project.read", True),
        ("MODEL", "read_root_a", "project.read", True),
        ("MODEL", "read_mod_building_a", "project.read", True),
        ("MODEL", "read_mod_floor_a", "project.read", True),
        ("MODEL", "read_exc_a", "project.read", True),
        ("MODEL", "patch_phase_a", "source.patch", True),
        ("MODEL", "read_root_b", "project.read", True),
        ("MODEL", "read_mod_building_b", "project.read", True),
        ("MODEL", "read_mod_floor_b", "project.read", True),
        ("MODEL", "read_exc_b", "project.read", True),
        ("ENVIRONMENT", "env_read_root_3100", "project.read", False),
        ("ENVIRONMENT", "env_patch_height_3100", "source.patch", True),
        ("MODEL", "patch_phase_b_stale", "source.patch", True),
        ("MODEL", "read_root_recovery", "project.read", True),
        ("MODEL", "read_mod_building_recovery", "project.read", True),
        ("MODEL", "read_mod_floor_recovery", "project.read", True),
        ("MODEL", "read_exc_recovery", "project.read", True),
        ("MODEL", "patch_phase_b_recovery", "source.patch", True),
    )
    if len(transcript.exchanges) != len(expected):
        _fail("wire exchange census differs from pre-registered flow")
    decoded: dict[str, tuple[FrozenMap, FrozenMap, WireExchangeV0]] = {}
    for exchange, (actor, request_id, tool, visible) in zip(
        transcript.exchanges, expected, strict=True,
    ):
        request = _decode(exchange.request_blob, f"request {exchange.seq}")
        response = _decode(exchange.response_blob, f"response {exchange.seq}")
        if set(request) != {"arguments", "protocol", "request_id", "tool"}:
            _fail("wire request envelope is not exact")
        if (
            request["protocol"] != PROTOCOL_VERSION
            or request["request_id"] != request_id
            or request["tool"] != tool
            or exchange.actor != actor
            or exchange.model_visible is not visible
            or response.get("request_id") != request_id
            or response.get("tool") != tool
        ):
            _fail("wire matrix or actor schedule differs from pre-registration")
        decoded[request_id] = (request, response, exchange)

    cap_result = decoded["cap_1"][1]["result"]
    if (
        len(canonical_bytes(cap_result)) != REGISTRY_CANONICAL_BYTES
        or cap_result.get("registry_digest") != REGISTRY_DIGEST
    ):
        _fail("full exact capability registry was not shown to the model")

    phase_a = decoded["patch_phase_a"][1]
    if (
        phase_a.get("status") != "OK"
        or phase_a["result"].get("source_digest") != PHASE_A_SOURCE_DIGEST
        or phase_a["result"].get("build_digest") != PHASE_A_BUILD_DIGEST
    ):
        _fail("phase A did not reach the pre-registered compact build")

    def expected_refs(read_ids: tuple[str, ...]) -> set[tuple[str, str]]:
        return {
            (
                decoded[read_id][1]["read_receipt"]["receipt_id"],
                decoded[read_id][1]["read_receipt"]["receipt_digest"],
            )
            for read_id in read_ids
        }

    def actual_refs(patch_id: str) -> set[tuple[str, str]]:
        refs = decoded[patch_id][0]["arguments"]["receipt_refs"]
        if type(refs) is not tuple:
            _fail(f"{patch_id} receipt refs are not an array")
        return {(item["receipt_id"], item["receipt_digest"]) for item in refs}

    owner_sets = {
        "patch_phase_a": (
            "read_root_a", "read_exc_a", "read_mod_building_a",
            "read_mod_floor_a",
        ),
        "patch_phase_b_stale": (
            "read_root_b", "read_exc_b", "read_mod_building_b",
            "read_mod_floor_b",
        ),
        "patch_phase_b_recovery": (
            "read_root_recovery", "read_exc_recovery",
            "read_mod_building_recovery", "read_mod_floor_recovery",
        ),
    }
    for patch_id, read_ids in owner_sets.items():
        if actual_refs(patch_id) != expected_refs(read_ids):
            _fail(f"{patch_id} does not bind its exact fresh OWNER reads")

    def expected_ref_records(read_ids: tuple[str, ...]) -> tuple[dict[str, str], ...]:
        records = tuple({
            "receipt_digest": decoded[read_id][1]["read_receipt"][
                "receipt_digest"],
            "receipt_id": decoded[read_id][1]["read_receipt"]["receipt_id"],
            "schema": "kir-ai-project-read-receipt-ref/0",
        } for read_id in read_ids)
        return tuple(sorted(records, key=lambda item: item["receipt_id"]))

    expected_root_arguments = {
        "floor_depth": "26000",
        "floor_height": "3000",
        "floor_module": "mod_typical_floor",
        "floor_width": "32000",
        "level_keys": tuple(f"L{index:03d}" for index in range(1, 61)),
    }

    def exact_root_exception_patch(
        patch_id: str,
        *,
        exception_width: str,
    ) -> None:
        arguments = decoded[patch_id][0]["arguments"]
        operations = arguments["operations"]
        if (
            type(operations) is not tuple
            or len(operations) != 2
            or tuple(item.get("schema") for item in operations)
            != ("kir-ai-root-put/0", "kir-ai-exception-put/0")
            or dict(operations[0]["root"]["arguments"].items())
            != expected_root_arguments
        ):
            _fail(f"{patch_id} root/exception operation set is not exact")
        exception = operations[1]["exception"]
        if (
            exception.get("exception_id") != "exc_L027"
            or exception.get("parameter_id") != "width"
            or exception.get("expected_value") != "32000"
            or exception.get("value") != exception_width
        ):
            _fail(f"{patch_id} exception intent is not exact")

    exact_root_exception_patch("patch_phase_a", exception_width="36000")
    exact_root_exception_patch("patch_phase_b_recovery", exception_width="35000")

    stale_arguments = decoded["patch_phase_b_stale"][0]["arguments"]
    stale_operations = stale_arguments["operations"]
    if (
        type(stale_operations) is not tuple
        or len(stale_operations) != 1
        or stale_operations[0].get("schema") != "kir-ai-exception-put/0"
        or stale_operations[0]["exception"].get("expected_value") != "32000"
        or stale_operations[0]["exception"].get("value") != "35000"
        or stale_arguments.get("base_revision_digest")
        != phase_a["result"]["revision_digest"]
    ):
        _fail("stale phase B model intent is not exact")
    stale_exception = dict(
        decoded["read_exc_b"][1]["result"]["value"].items())
    stale_exception["expected_value"] = "32000"
    stale_exception["value"] = "35000"
    expected_stale_request = {
        "arguments": {
            "base_revision_digest": phase_a["result"]["revision_digest"],
            "operations": ({
                "exception": stale_exception,
                "op_id": "phase_b_stale.exception",
                "schema": "kir-ai-exception-put/0",
            },),
            "patch_id": "phase_b_stale",
            "project_id": phase_a["result"]["project_id"],
            "receipt_refs": expected_ref_records(owner_sets[
                "patch_phase_b_stale"]),
            "schema": "kir-ai-source-patch-command/0",
        },
        "protocol": PROTOCOL_VERSION,
        "request_id": "patch_phase_b_stale",
        "tool": "source.patch",
    }
    if canonical_bytes(decoded["patch_phase_b_stale"][0]) != canonical_bytes(
        expected_stale_request
    ):
        _fail("stale phase B command is not canonically exact")

    stale = decoded["patch_phase_b_stale"][1]
    if (
        stale.get("status") != "CONFLICT"
        or stale.get("error", FrozenMap()).get("code") != "PROJECT_STATE_CONFLICT"
        or decoded["patch_phase_b_stale"][2].before_state_digest
        != decoded["patch_phase_b_stale"][2].after_state_digest
    ):
        _fail("stale model attempt was not preserved as an exact no-commit conflict")

    env_read_request, env_read_response, _ = decoded["env_read_root_3100"]
    env_patch_request, env_patch_response, _ = decoded["env_patch_height_3100"]
    env_operations = env_patch_request["arguments"]["operations"]
    if type(env_operations) is not tuple or len(env_operations) != 1:
        _fail("environment patch is not the exact root-only intervention")
    env_root = env_operations[0]
    if (
        env_root.get("schema") != "kir-ai-root-put/0"
        or env_root["root"]["arguments"].get("floor_height") != "3100"
        or env_patch_request["arguments"].get("base_revision_digest")
        != env_read_request["arguments"].get("revision_digest")
        or env_patch_response.get("status") != "OK"
    ):
        _fail("environment intervention semantics are not exact")
    refs = env_patch_request["arguments"]["receipt_refs"]
    owner = env_read_response["read_receipt"]
    if (
        type(refs) is not tuple or len(refs) != 1
        or refs[0].get("receipt_id") != owner.get("receipt_id")
        or refs[0].get("receipt_digest") != owner.get("receipt_digest")
    ):
        _fail("environment patch does not use its traced owner read")

    final = decoded["patch_phase_b_recovery"][1]
    if (
        final.get("status") != "OK"
        or final["result"].get("source_digest") != FINAL_SOURCE_DIGEST
        or final["result"].get("build_digest") != FINAL_BUILD_DIGEST
    ):
        _fail("recovery did not reach the exact final compact build")
    if (
        decoded["patch_phase_b_recovery"][0]["arguments"].get(
            "base_revision_digest")
        != env_patch_response["result"]["revision_digest"]
    ):
        _fail("recovery patch does not bind the observable environment head")

    for patch_id in (
        "patch_phase_a", "patch_phase_b_stale", "patch_phase_b_recovery",
    ):
        request = decoded[patch_id][0]
        refs = request["arguments"]["receipt_refs"]
        if type(refs) is not tuple or len(refs) != 4:
            _fail(f"{patch_id} lacks the four required owner receipts")


def _budgets(transcript: TranscriptV0) -> tuple[int, int, int, int]:
    budget = _budget_state(list(transcript.exchanges))
    attempts, request_bytes, response_bytes, entities = budget
    if attempts > MAX_MODEL_ATTEMPTS:
        _fail("model attempt budget exceeded")
    if request_bytes > MAX_CUMULATIVE_REQUEST_BYTES:
        _fail("cumulative model request budget exceeded")
    if response_bytes > MAX_MODEL_VISIBLE_RESPONSE_BYTES:
        _fail("cumulative model-visible raw response budget exceeded")
    if entities > MAX_UNIQUE_BUILD_ENTITIES:
        _fail("DISQUALIFIED_CONTEXT_BYPASS: unique BuildEntity budget exceeded")
    return budget


def _fresh_replay(transcript: TranscriptV0) -> OfflineProjectWireV0:
    host = OfflineProjectWireV0.from_source(initial_source())
    for exchange in transcript.exchanges:
        if host.state_digest != exchange.before_state_digest:
            _fail("fresh replay before-state digest mismatch")
        try:
            response = host.handle_wire_request(exchange.request_blob)
        except Exception as exc:
            raise TranscriptVerificationError(
                "fresh replay rejected a stored request") from exc
        if response != exchange.response_blob:
            _fail("fresh replay response is not byte-identical")
        if host.state_digest != exchange.after_state_digest:
            _fail("fresh replay after-state digest mismatch")
    return host


def verify_transcript(transcript: TranscriptV0) -> BenchmarkReportV0:
    """Recompute conformance on a new host; never trust a stored report."""

    if type(transcript) is not TranscriptV0:
        raise BenchmarkContractError("verify_transcript requires exact TranscriptV0")
    _exact_known_case(transcript)
    _exact_chain(transcript)
    _exact_prompts_and_outputs(transcript)
    _request_response_matrix(transcript)
    budget = _budgets(transcript)
    host = _fresh_replay(transcript)

    # Terminal was structurally proven above; only now may the hidden oracle
    # inspect the replay host's state object.
    try:
        oracle = evaluate_tower54_terminal(host.state)
    except OracleFailure as exc:
        raise TranscriptVerificationError(f"terminal oracle failed: {exc}") from exc
    expected_ledger = {
        "cursor_count": 0,
        "patch_outcome_count": 3,
        "read_receipt_count": 14,
        "revision_count": 4,
    }
    if dict(oracle["ledger"].items()) != expected_ledger:
        _fail("fresh replay receipt/cursor/patch ledgers are not exact")
    attempts, request_bytes, response_bytes, entities = budget
    return BenchmarkReportV0(
        run_id=transcript.header.run_id,
        transcript_digest=transcript.transcript_digest,
        status="HARNESS_CONFORMANCE",
        final_state_digest=host.state_digest,
        final_source_digest=host.state.head.source_digest,
        final_build_digest=host.state.build.manifest.build_digest,
        model_attempts=attempts,
        cumulative_request_bytes=request_bytes,
        model_visible_response_bytes=response_bytes,
        unique_build_entities=entities,
        oracle=oracle,
    )


def verify_transcript_data(value: Any) -> BenchmarkReportV0:
    """Strictly admit serialized evidence before fresh replay."""

    try:
        transcript = TranscriptV0.from_data(value)
    except BenchmarkContractError:
        raise
    return verify_transcript(transcript)


__all__ = [
    "TranscriptVerificationError", "verify_transcript", "verify_transcript_data",
]
