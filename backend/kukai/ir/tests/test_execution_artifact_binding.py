"""Exact final-C# authority for the regular KIR write lane."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from kukai.ir import acceptance_journal as journal_module
from kukai.ir.acceptance_evidence import (
    EXECUTION_ARTIFACT_CAPABILITY_KEY,
    EXECUTION_ARTIFACT_DIGEST_KEY,
    REGULAR_WRITE_EXECUTION_LANE,
    ExecutionArtifactBinding,
    ExecutionArtifactBindingError,
)
from kukai.ir.acceptance_journal import (
    ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
    LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
    AcceptanceJournal,
    AcceptanceJournalError,
)
from kukai.ir.tests.test_acceptance_journal import _parts
from kukai.ir.outcome import program_not_started
from kukai.llm.revit_execution_pipeline import (
    RevitExecutionPipeline,
    wrap_user_code,
)
from tests.test_revit_execution_pipeline import FakeTransport, make_deps


SOURCE = "var x = 1;\nreturn x;"


def _binding(
    source: str = SOURCE,
    *,
    revit_version: str = "2026",
    execution_lane: str = REGULAR_WRITE_EXECUTION_LANE,
    tool: str = "revit_ir",
    op: str = "write",
) -> ExecutionArtifactBinding:
    return ExecutionArtifactBinding.from_source(
        source,
        run_id="a" * 32,
        revit_version=revit_version,
        plan_digest="b" * 64,
        ground_digest="c" * 64,
        ground_context_digest="d" * 64,
        execution_lane=execution_lane,
        tool=tool,
        op=op,
    )


def test_binding_addresses_utf8_bytes_and_all_dispatch_identity_fields():
    source = "return \"стена\";"
    binding = _binding(source)
    assert binding.source_byte_length == len(source.encode("utf-8"))
    assert binding.source_sha256 == hashlib.sha256(
        source.encode("utf-8")).hexdigest()
    assert ExecutionArtifactBinding.from_dict(binding.to_dict()) == binding

    mutations = (
        {"source": source + " "},
        {"run_id": "e" * 32},
        {"revit_version": "2025"},
        {"plan_digest": "e" * 64},
        {"ground_digest": "e" * 64},
        {"ground_context_digest": "e" * 64},
        {"execution_lane": "another_lane"},
        {"tool": "another_tool"},
        {"op": "another_op"},
    )
    base = dict(
        source=source,
        run_id=binding.run_id,
        revit_version=binding.revit_version,
        plan_digest=binding.plan_digest,
        ground_digest=binding.ground_digest,
        ground_context_digest=binding.ground_context_digest,
        execution_lane=binding.execution_lane,
        tool=binding.tool,
        op=binding.op,
    )
    for mutation in mutations:
        with pytest.raises(ExecutionArtifactBindingError):
            binding.require_exact(**{**base, **mutation})
    with pytest.raises(ExecutionArtifactBindingError, match="UTF-8"):
        _binding("return \"\ud800\";")


def _bind_journal(journal, registration, evidence, source="wrapped final C#"):
    binding = ExecutionArtifactBinding.from_source(
        source,
        run_id=registration.run_id,
        revit_version=registration.revit_version,
        plan_digest=registration.plan_digest,
        ground_digest=registration.ground_digest,
        ground_context_digest=registration.ground_context_digest,
        execution_lane=REGULAR_WRITE_EXECUTION_LANE,
        tool="revit_ir",
        op="write",
    )
    journal.bind_execution_artifact(binding)
    evidence = replace(
        evidence,
        execution_artifact_binding_digest=binding.binding_digest,
    )
    return binding, evidence


def test_bound_crash_state_reopens_and_can_finalize_exact_evidence(tmp_path: Path):
    registration, evidence, outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    binding, evidence = _bind_journal(journal, registration, evidence)

    reopened = AcceptanceJournal.open(journal.path)
    assert reopened.state.artifact_bound
    assert not reopened.state.finalized
    assert reopened.state.artifact_binding == binding
    reopened.finalize(outcome, evidence=evidence)

    final = AcceptanceJournal.open(journal.path)
    assert final.state.finalized
    assert final.state.final_payload is not None
    assert final.state.final_payload[
        "execution_artifact_binding_digest"] == binding.binding_digest


def test_started_outcome_without_binding_is_refused(tmp_path: Path):
    registration, evidence, outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    with pytest.raises(AcceptanceJournalError, match="missing.*binding"):
        journal.finalize(outcome, evidence=evidence)


def test_even_pre_effect_terminal_cannot_skip_the_required_binding_phase(
    tmp_path: Path,
):
    registration, _evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    with pytest.raises(AcceptanceJournalError, match="missing.*binding"):
        journal.finalize(program_not_started(), evidence=None)


def test_replay_rejects_a_forged_terminal_that_skipped_binding(tmp_path: Path):
    registration, _evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    prepared = json.loads(journal.path.read_text(encoding="utf-8"))
    terminal = {
        "outcome": program_not_started().to_dict(),
        "evidence": None,
        "evidence_digest": None,
        "execution_artifact_binding_digest": None,
    }
    body = {
        "schema_version": ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
        "seq": 1,
        "event": "finalized",
        "run_id": registration.run_id,
        "time_ns": 2,
        "prev_checksum": prepared["checksum"],
        "registration_digest": registration.registration_digest,
        "terminal": terminal,
    }
    checksum = journal_module._checksum(prepared["checksum"], body)
    with journal.path.open("ab") as sink:
        sink.write(journal_module._canonical({
            **body, "checksum": checksum}) + b"\n")
    with pytest.raises(AcceptanceJournalError, match="missing.*binding"):
        AcceptanceJournal.open(journal.path)


def test_duplicate_and_out_of_order_binding_are_refused(tmp_path: Path):
    registration, evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    binding, _evidence = _bind_journal(journal, registration, evidence)
    with pytest.raises(AcceptanceJournalError, match="one artifact binding"):
        journal.bind_execution_artifact(binding)

    rows = journal.path.read_text(encoding="utf-8").splitlines()
    journal.path.write_text("\n".join(reversed(rows)) + "\n", encoding="utf-8")
    with pytest.raises(AcceptanceJournalError):
        AcceptanceJournal.open(journal.path)


def test_replay_rejects_a_checksum_valid_duplicate_binding(tmp_path: Path):
    registration, evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    _bind_journal(journal, registration, evidence)
    rows = [json.loads(row) for row in journal.path.read_text(
        encoding="utf-8").splitlines()]
    duplicate = {
        key: value for key, value in rows[1].items() if key != "checksum"}
    duplicate["seq"] = 2
    duplicate["time_ns"] = 3
    duplicate["prev_checksum"] = rows[1]["checksum"]
    checksum = journal_module._checksum(rows[1]["checksum"], duplicate)
    with journal.path.open("ab") as sink:
        sink.write(journal_module._canonical({
            **duplicate, "checksum": checksum}) + b"\n")
    with pytest.raises(AcceptanceJournalError, match="one artifact binding"):
        AcceptanceJournal.open(journal.path)


def test_tampered_and_torn_binding_rows_fail_closed(tmp_path: Path):
    registration, evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    _bind_journal(journal, registration, evidence)
    rows = [json.loads(row) for row in journal.path.read_text(
        encoding="utf-8").splitlines()]
    rows[1]["binding"]["source_sha256"] = "f" * 64
    binding_body = {
        key: value for key, value in rows[1].items() if key != "checksum"}
    rows[1]["checksum"] = journal_module._checksum(
        rows[0]["checksum"], binding_body)
    journal.path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AcceptanceJournalError, match="binding digest"):
        AcceptanceJournal.open(journal.path)

    other_root = tmp_path / "torn"
    other = AcceptanceJournal.create(other_root, registration)
    _bind_journal(other, registration, evidence)
    with other.path.open("ab") as sink:
        sink.write(b'{"event":"final')
    with pytest.raises(AcceptanceJournalError, match="torn tail"):
        AcceptanceJournal.open(other.path)


def test_live_journal_rejects_mutated_registration_before_bind_or_finalize(
    tmp_path: Path,
):
    registration, evidence, outcome = _parts()
    before_bind = AcceptanceJournal.create(tmp_path / "before", registration)
    before_bind.state.registration_payload["plan_digest"] = "f" * 64
    with pytest.raises(AcceptanceJournalError, match="in-memory.*durable"):
        before_bind.bind_execution_artifact(
            ExecutionArtifactBinding.from_source(
                "wrapped",
                run_id=registration.run_id,
                revit_version=registration.revit_version,
                plan_digest="f" * 64,
                ground_digest=registration.ground_digest,
                ground_context_digest=registration.ground_context_digest,
                execution_lane=REGULAR_WRITE_EXECUTION_LANE,
                tool="revit_ir",
                op="write",
            )
        )
    assert len(before_bind.path.read_text(encoding="utf-8").splitlines()) == 1

    before_final = AcceptanceJournal.create(tmp_path / "final", registration)
    binding, evidence = _bind_journal(
        before_final, registration, evidence)
    before_final.state.registration_payload["ground_digest"] = "f" * 64
    with pytest.raises(AcceptanceJournalError, match="in-memory.*durable"):
        before_final.finalize(outcome, evidence=evidence)
    assert binding == before_final.state.artifact_binding
    assert len(before_final.path.read_text(encoding="utf-8").splitlines()) == 2


def test_terminal_refuses_outcome_that_contradicts_bound_acceptance(tmp_path: Path):
    from kukai.ir.outcome import AcceptanceState, ProgramOutcome

    registration, evidence, outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    _binding_value, evidence = _bind_journal(
        journal, registration, evidence)
    contradictory = ProgramOutcome(
        outcome.execution,
        outcome.witness,
        AcceptanceState.REJECTED,
    )
    with pytest.raises(AcceptanceJournalError, match="contradicts"):
        journal.finalize(contradictory, evidence=evidence)
    assert len(journal.path.read_text(encoding="utf-8").splitlines()) == 2


def test_legacy_v1_is_archive_readable_but_never_new_write_authority(
    tmp_path: Path,
):
    run_id = "e" * 32
    registration = {
        "schema_version": "kir-acceptance-registration/1",
        "run_id": run_id,
        "plan_digest": "f" * 64,
    }
    registration_digest = journal_module._digest(registration)
    body = {
        "schema_version": LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
        "seq": 0,
        "event": "prepared",
        "run_id": run_id,
        "time_ns": 1,
        "prev_checksum": journal_module._ZERO_CHECKSUM,
        "registration_digest": registration_digest,
        "registration": registration,
    }
    checksum = journal_module._checksum(journal_module._ZERO_CHECKSUM, body)
    terminal_body = {
        "schema_version": LEGACY_ACCEPTANCE_JOURNAL_SCHEMA_VERSION,
        "seq": 1,
        "event": "finalized",
        "run_id": run_id,
        "time_ns": 2,
        "prev_checksum": checksum,
        "registration_digest": registration_digest,
        "terminal": {
            "outcome": program_not_started().to_dict(),
            "evidence": None,
            "evidence_digest": None,
        },
    }
    terminal_checksum = journal_module._checksum(checksum, terminal_body)
    path = tmp_path / f"{run_id}.jsonl"
    path.write_bytes(
        journal_module._canonical({**body, "checksum": checksum}) + b"\n"
        + journal_module._canonical({
            **terminal_body, "checksum": terminal_checksum}) + b"\n"
    )

    legacy = AcceptanceJournal.open(path)
    assert legacy.state.legacy_unbound
    assert legacy.state.finalized
    assert not legacy.state.artifact_bound
    with pytest.raises(AcceptanceJournalError, match="archive-only"):
        legacy.bind_execution_artifact(_binding())


def _pipeline(binding, *, revit_version="2026", lane=None,
              tool="revit_ir", op="write"):
    transport = FakeTransport(results=[{"ok": True}])
    deps, transport, _compile = make_deps(
        transport=transport, revit_version=revit_version)
    pipe = RevitExecutionPipeline(deps)
    return pipe, transport, dict(
        tool=tool,
        op=op,
        args={},
        timeout_ms=60_000,
        execution_artifact_binding=binding,
        execution_lane=lane,
    )


@pytest.mark.asyncio
async def test_pipeline_sends_exact_bound_wrapped_bytes():
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    pipe, transport, kwargs = _pipeline(
        binding, lane=REGULAR_WRITE_EXECUTION_LANE)
    record = await pipe.run_declarative(SOURCE, **kwargs)
    assert record.ok
    assert transport.calls[0][1]["code"] == wrapped
    assert transport.calls[0][1][
        EXECUTION_ARTIFACT_CAPABILITY_KEY] is binding
    assert transport.calls[0][1][
        EXECUTION_ARTIFACT_DIGEST_KEY] == binding.binding_digest
    assert record.execution_artifact_binding_digest == binding.binding_digest


def test_bridge_boundary_rechecks_exact_bytes_version_and_private_capability():
    from kukai.api.bridge_protocol import (
        _validate_execution_artifact_transport,
    )

    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    assert _validate_execution_artifact_transport(
        "execute", params, revit_version="2026",
        encrypted_session_available=True) is binding

    attacks = (
        {"code": wrapped + " "},
        {EXECUTION_ARTIFACT_DIGEST_KEY: "f" * 64},
        {EXECUTION_ARTIFACT_CAPABILITY_KEY: binding.to_dict()},
        {"_pipeline_prepared": False},
    )
    for attack in attacks:
        with pytest.raises(ExecutionArtifactBindingError):
            _validate_execution_artifact_transport(
                "execute", {**params, **attack}, revit_version="2026",
                encrypted_session_available=True)
    with pytest.raises(ExecutionArtifactBindingError):
        _validate_execution_artifact_transport(
            "execute", params, revit_version="2025",
            encrypted_session_available=True)
    with pytest.raises(ExecutionArtifactBindingError):
        _validate_execution_artifact_transport(
            "execute", params, revit_version="2026",
            encrypted_session_available=False)


def test_direct_bridge_route_derives_stable_operation_from_bound_run():
    from kukai.api.bridge_protocol import _operation_context

    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "timeout_ms": 30_000,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    first = _operation_context("execute", params)[1]
    second = _operation_context(
        "execute", {**params, "timeout_ms": 5_000})[1]
    assert first is not None and second is not None
    assert first == second
    assert first.turn_id == binding.run_id


def test_operation_identity_hashes_portable_binding_digest_not_capability_repr():
    from kukai.operations.protocol import canonical_payload_hash

    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    base = {
        "code": wrapped,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    with_capability = {
        **base,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
    }
    assert canonical_payload_hash("execute", with_capability) == (
        canonical_payload_hash("execute", base))
    assert canonical_payload_hash("execute", {
        **base, EXECUTION_ARTIFACT_DIGEST_KEY: "f" * 64,
    }) != canonical_payload_hash("execute", base)


@pytest.mark.asyncio
async def test_concurrent_bound_dispatch_has_exactly_one_bridge_send(monkeypatch):
    from kukai.api import bridge_protocol as bridge
    from kukai.api.ws_registry import _session_contexts, _session_keys
    from kukai.operations.store import InMemoryOperationStore
    from kukai.security.encryption import SessionEncryption

    ws_id = "execution-artifact-concurrency"
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "timeout_ms": 30_000,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    store = InMemoryOperationStore()
    monkeypatch.setattr(bridge, "_operation_store", lambda: store)
    monkeypatch.setitem(_session_keys, ws_id, SessionEncryption.generate_key())
    monkeypatch.setitem(_session_contexts, ws_id, {"revit_version": "2026"})
    requests: list[dict] = []
    first_entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_send(_ws, frame):
        if frame.get("type") != "bridge_request":
            return
        requests.append(frame)
        first_entered.set()
        await release.wait()
        entry = bridge._pending_bridge_requests.get(frame["id"])
        if entry is not None and not entry[1].done():
            entry[1].set_result({"success": True, "result": {"ok": True}})

    monkeypatch.setattr(bridge, "_send_json", fake_send)
    first = asyncio.create_task(
        bridge._bridge_callback(object(), ws_id, "execute", dict(params)))
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    second = asyncio.create_task(
        bridge._bridge_callback(object(), ws_id, "execute", dict(params)))
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(first, second)
    assert len(requests) == 1

    _session_keys.pop(ws_id, None)
    _session_contexts.pop(ws_id, None)


@pytest.mark.asyncio
async def test_claimed_send_failure_becomes_unknown_and_never_redispatches(
    monkeypatch,
):
    from kukai.api import bridge_protocol as bridge
    from kukai.api.ws_registry import _session_contexts, _session_keys
    from kukai.operations.protocol import OperationOutcome, OperationPhase
    from kukai.operations.store import InMemoryOperationStore
    from kukai.security.encryption import SessionEncryption

    ws_id = "execution-artifact-send-failure"
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "timeout_ms": 30_000,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    store = InMemoryOperationStore()
    monkeypatch.setattr(bridge, "_operation_store", lambda: store)
    monkeypatch.setitem(_session_keys, ws_id, SessionEncryption.generate_key())
    monkeypatch.setitem(_session_contexts, ws_id, {"revit_version": "2026"})
    sends = 0

    async def broken_send(_ws, frame):
        nonlocal sends
        if frame.get("type") == "bridge_request":
            sends += 1
            raise ConnectionError("ambiguous websocket send")

    monkeypatch.setattr(bridge, "_send_json", broken_send)
    first = await bridge._bridge_callback(
        object(), ws_id, "execute", dict(params))
    identity = bridge._operation_context("execute", params)[1]
    assert identity is not None
    state = await store.get(identity.operation_id)
    assert first["state"] == OperationOutcome.RUNNING_UNKNOWN.value
    assert state is not None
    assert state.phase is OperationPhase.RUNNING_UNKNOWN
    assert state.attempt_id

    second = await bridge._bridge_callback(
        object(), ws_id, "execute", dict(params))
    assert second["state"] == OperationOutcome.RUNNING_UNKNOWN.value
    assert sends == 1
    _session_keys.pop(ws_id, None)
    _session_contexts.pop(ws_id, None)


@pytest.mark.asyncio
async def test_cancel_during_claimed_send_is_unknown_cleans_waiter_and_never_replays(
    monkeypatch,
):
    from kukai.api import bridge_protocol as bridge
    from kukai.api.ws_registry import _session_contexts, _session_keys
    from kukai.operations.protocol import OperationOutcome, OperationPhase
    from kukai.operations.store import InMemoryOperationStore
    from kukai.security.encryption import SessionEncryption

    ws_id = "execution-artifact-send-cancel"
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "timeout_ms": 30_000,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    store = InMemoryOperationStore()
    monkeypatch.setattr(bridge, "_operation_store", lambda: store)
    monkeypatch.setitem(_session_keys, ws_id, SessionEncryption.generate_key())
    monkeypatch.setitem(_session_contexts, ws_id, {"revit_version": "2026"})
    send_entered = asyncio.Event()
    sends = 0
    request_id = ""

    async def blocked_send(_ws, frame):
        nonlocal sends, request_id
        if frame.get("type") == "bridge_request":
            sends += 1
            request_id = frame["id"]
            send_entered.set()
            await asyncio.Future()

    monkeypatch.setattr(bridge, "_send_json", blocked_send)
    task = asyncio.create_task(
        bridge._bridge_callback(object(), ws_id, "execute", dict(params)))
    await asyncio.wait_for(send_entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    identity = bridge._operation_context("execute", params)[1]
    assert identity is not None
    state = await store.get(identity.operation_id)
    assert state is not None
    assert state.phase is OperationPhase.RUNNING_UNKNOWN
    assert state.outcome == OperationOutcome.RUNNING_UNKNOWN.value
    assert request_id not in bridge._pending_bridge_requests
    assert request_id not in bridge._pending_bridge_operations

    replay = await bridge._bridge_callback(
        object(), ws_id, "execute", dict(params))
    assert replay["state"] == OperationOutcome.RUNNING_UNKNOWN.value
    assert sends == 1
    _session_keys.pop(ws_id, None)
    _session_contexts.pop(ws_id, None)


@pytest.mark.asyncio
async def test_dispatch_claim_is_attempt_bound_and_crash_state_is_not_reclaimable():
    from kukai.operations.protocol import OperationIdentity, OperationPhase
    from kukai.operations.store import (
        InMemoryOperationStore,
        OperationRecord,
    )

    identity = OperationIdentity.for_payload(
        turn_id="crash-run",
        tool_call_id="call",
        tool_name="revit_ir",
        method="execute",
        params={"code": "return 1;"},
    )
    store = InMemoryOperationStore()
    await store.create(OperationRecord(
        identity=identity,
        method="execute",
        phase=OperationPhase.PERSISTED_SERVER,
    ))
    claimed = await store.claim_dispatch(
        identity.operation_id, attempt_id="attempt-one")
    assert claimed is not None
    assert claimed.phase is OperationPhase.DISPATCH_CLAIMED
    assert claimed.attempt_id == "attempt-one"
    assert await store.claim_dispatch(
        identity.operation_id, attempt_id="attempt-two") is None

    invalid = InMemoryOperationStore()
    await invalid.create(OperationRecord(
        identity=identity,
        method="execute",
        phase=OperationPhase.PERSISTED_SERVER,
    ))
    with pytest.raises(ValueError):
        await invalid.claim_dispatch(identity.operation_id, attempt_id="")


@pytest.mark.asyncio
async def test_store_without_atomic_claim_fails_closed_before_bridge_send(
    monkeypatch,
):
    from kukai.api import bridge_protocol as bridge
    from kukai.api.ws_registry import _session_contexts, _session_keys
    from kukai.operations.store import InMemoryOperationStore
    from kukai.security.encryption import SessionEncryption

    class LegacyStoreAdapter:
        """Shape of a pre-claim custom store implementation."""

        def __init__(self):
            self.inner = InMemoryOperationStore()

        async def create(self, record):
            return await self.inner.create(record)

        async def transition(self, *args, **kwargs):
            return await self.inner.transition(*args, **kwargs)

        async def get(self, operation_id):
            return await self.inner.get(operation_id)

    ws_id = "execution-artifact-old-store"
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    params = {
        "code": wrapped,
        "_pipeline_prepared": True,
        EXECUTION_ARTIFACT_CAPABILITY_KEY: binding,
        EXECUTION_ARTIFACT_DIGEST_KEY: binding.binding_digest,
    }
    monkeypatch.setattr(bridge, "_operation_store", LegacyStoreAdapter)
    monkeypatch.setitem(_session_keys, ws_id, SessionEncryption.generate_key())
    monkeypatch.setitem(_session_contexts, ws_id, {"revit_version": "2026"})
    sends = []

    async def fake_send(_ws, frame):
        sends.append(frame)

    monkeypatch.setattr(bridge, "_send_json", fake_send)
    result = await bridge._bridge_callback(
        object(), ws_id, "execute", params)
    assert result["error"] is True
    assert result["err"]["code"] == "internal.unhandled"
    assert sends == []
    _session_keys.pop(ws_id, None)
    _session_contexts.pop(ws_id, None)


@pytest.mark.asyncio
async def test_database_store_claim_roundtrips_operation_and_attempt_identity():
    from kukai.operations.protocol import OperationIdentity, OperationPhase
    from kukai.operations.store import DatabaseOperationStore, OperationRecord

    identity = OperationIdentity.for_payload(
        turn_id="db-run",
        tool_call_id="call",
        tool_name="revit_ir",
        method="execute",
        params={"code": "return 1;"},
    )
    row = OperationRecord(
        identity=identity,
        method="execute",
        phase=OperationPhase.DISPATCH_CLAIMED,
        attempt_id="attempt-db",
    ).as_dict()

    class FakeDatabase:
        seen = None

        async def claim_operation_dispatch(self, operation_id, *, attempt_id):
            self.seen = (operation_id, attempt_id)
            return row

    database = FakeDatabase()
    claimed = await DatabaseOperationStore(database).claim_dispatch(
        identity.operation_id, attempt_id="attempt-db")
    assert database.seen == (identity.operation_id, "attempt-db")
    assert claimed is not None
    assert claimed.identity == identity
    assert claimed.phase is OperationPhase.DISPATCH_CLAIMED
    assert claimed.attempt_id == "attempt-db"


@pytest.mark.asyncio
async def test_pipeline_rechecks_binding_after_compile_immediately_before_send():
    wrapped = wrap_user_code(SOURCE)
    binding = _binding(wrapped)
    pipe, transport, kwargs = _pipeline(
        binding, lane=REGULAR_WRITE_EXECUTION_LANE)
    with mock.patch.object(
        ExecutionArtifactBinding,
        "require_exact",
        side_effect=[
            None,
            ExecutionArtifactBindingError("wrapper drift after compile"),
        ],
    ):
        record = await pipe.run_declarative(SOURCE, **kwargs)
    assert not record.ok
    assert record.n_compile_checks == 1
    assert record.n_bridge_roundtrips == 0
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("binding_mutation", "dispatch_mutation"), [
    ("unbound", {}),
    ("source", {}),
    ("version", {}),
    (None, {"lane": "another_lane"}),
    (None, {"tool": "another_tool"}),
    (None, {"op": "another_op"}),
])
async def test_pipeline_refuses_artifact_or_dispatch_swaps_before_effect(
    binding_mutation, dispatch_mutation,
):
    wrapped = wrap_user_code(SOURCE)
    if binding_mutation == "unbound":
        binding = None
    elif binding_mutation == "source":
        binding = _binding(wrapped + " ")
    elif binding_mutation == "version":
        binding = _binding(wrapped, revit_version="2025")
    else:
        binding = _binding(wrapped)
    lane = dispatch_mutation.get("lane", REGULAR_WRITE_EXECUTION_LANE)
    tool = dispatch_mutation.get("tool", "revit_ir")
    op = dispatch_mutation.get("op", "write")
    pipe, transport, kwargs = _pipeline(
        binding, lane=lane, tool=tool, op=op)
    record = await pipe.run_declarative(SOURCE, **kwargs)
    assert not record.ok
    assert record.state == "blocked"
    assert record.attempts == 0
    assert record.n_compile_checks == 0
    assert record.n_bridge_roundtrips == 0
    assert transport.calls == []
    assert record.err_code == "kir.precondition_unmet"


@pytest.mark.asyncio
async def test_an_unnamed_unbound_dispatch_refuses_before_effect():
    """Закрытый список отказывает В РАНТАЙМЕ, а не только в обходе пакета.

    До 11.08.2026 отправка без полосы и без связывания уходила в Revit молча:
    охрана возвращала None, потому что отвечала на «не подменили ли
    связывание», а не на «должна ли была эта отправка быть связанной».
    Теперь незнакомая пара (tool, op) — типизированный отказ ДО эффекта.
    """
    pipe, transport, kwargs = _pipeline(
        None, lane=None, tool="revit_ir", op="op_nobody_named")
    record = await pipe.run_declarative(SOURCE, **kwargs)
    result = record.to_tool_result()
    assert result.get("execution_artifact_refused_pre_effect") is True
    assert "op_nobody_named" in result.get("message", "")
    # ЭФФЕКТА НЕ БЫЛО: до транспорта дело не дошло.
    assert transport.calls == []


@pytest.mark.asyncio
async def test_a_named_unbound_dispatch_still_goes_through():
    """Обратная сторона того же замка: названный маршрут не сломан.

    Иначе закрытие списка читалось бы как «связывай всё», и первая же
    честная правка сняла бы его целиком.
    """
    pipe, transport, kwargs = _pipeline(
        None, lane=None, tool="revit_ir", op="ground_snapshot")
    record = await pipe.run_declarative(SOURCE, **kwargs)
    result = record.to_tool_result()
    assert not result.get("execution_artifact_refused_pre_effect")
    assert transport.calls, "названная несвязанная отправка не доехала"
