from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.project_v0 import (
    CoverageV0,
    CursorRecordV0,
    CursorRefV0,
    KernelTransitionV0,
    ModelQueryCommandV0,
    ModelQueryResultV0,
    ProjectReadCommandV0,
    ProjectReadResultV0,
    ProjectStateV0,
    ReadReceiptV0,
    ReceiptRefV0,
    RootPutV0,
    SourcePatchCommandV0,
)
from kukai.ai_protocol.project_v0.wire_v0 import (
    CAPABILITY_REGISTRY,
    decode_response,
)
from kukai.ai_protocol.project_v0.wire_v0.contracts import (
    AVAILABLE_TOOL_NAMES,
    DECLARED_TOOL_NAMES,
    PROTOCOL_VERSION,
)
from kukai.ai_protocol.project_v0.wire_v0.errors import (
    WireContractError,
    WireDecodeError,
    WireEncodeError,
    WireShapeError,
)
from kukai.ai_protocol.project_v0.wire_v0.contracts import (
    WireCoverageV0,
    WireResponseV0,
)
from kukai.ai_protocol.project_v0.wire_v0.session import (
    OfflineProjectWireV0,
    _CAPTURED_CODECS,
    _CAPTURED_HANDLERS,
    _SessionCodecs,
    _SessionHandlers,
    _make_offline_project_wire,
)
from kukai.ai_protocol.project_v0.wire_v0.result_codec import (
    parse_model_query_result,
    parse_project_read_result,
)
from kukai.ai_protocol.project_v0.wire_v0.wire import _make_response_encoder
from kukai.design_source import (
    RootInstanceV0,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)
from kukai.design_source.examples import make_tower_source


def _request(tool, arguments=None, *, request_id="request_1") -> bytes:
    return canonical_bytes({
        "arguments": {} if arguments is None else arguments,
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "tool": tool,
    })


def _call(host, tool, arguments=None, *, request_id="request_1"):
    return decode_response(host.handle_wire_request(_request(
        tool, arguments, request_id=request_id)))


def _state3_host():
    return OfflineProjectWireV0.from_source(make_tower_source(n_floors=3))


def _read_arguments(host, scope, target_id=None):
    return ProjectReadCommandV0(
        host.state.project_id,
        host.state.head.revision_digest,
        scope,
        target_id,
    ).to_data()


def _query_arguments(host, scope, filters, *, limit=128, cursor=None):
    return ModelQueryCommandV0(
        project_id=host.state.project_id,
        revision_digest=host.state.head.revision_digest,
        build_digest=host.state.build.manifest.build_digest,
        scope=scope,
        filters=filters,
        limit=limit,
        cursor=cursor,
    ).to_data()


def _root_patch_arguments(host, patch_id, receipt_ref, width, *, base=None):
    arguments = dict(host.state.head.root.arguments.items())
    arguments["floor_width"] = str(width)
    root = RootInstanceV0(
        host.state.head.root.instance_id,
        host.state.head.root.module_id,
        arguments,
    )
    return SourcePatchCommandV0(
        project_id=host.state.project_id,
        base_revision_digest=(
            host.state.head.revision_digest if base is None else base),
        patch_id=patch_id,
        receipt_refs=(receipt_ref,),
        operations=(RootPutV0("put_root", root),),
    ).to_data()


def test_session_capabilities_and_unavailable_are_exact_no_state_effects() -> None:
    host = _state3_host()
    initial = host.state
    digest = host.state_digest

    capabilities = _call(host, "capabilities.get")
    assert capabilities.status == "OK"
    assert canonical_bytes(capabilities.result) == canonical_bytes(
        CAPABILITY_REGISTRY.to_data())
    assert host.state is initial
    assert host.state_digest == digest

    unavailable = tuple(
        tool for tool in DECLARED_TOOL_NAMES if tool not in AVAILABLE_TOOL_NAMES)
    for index, tool in enumerate(unavailable):
        first = _call(host, tool, request_id=f"unavailable_{index}")
        second = _call(host, tool, request_id=f"unavailable_{index}")
        assert first.status == second.status == "REFUSED"
        assert first.error is not second.error
        assert canonical_bytes(first.to_data()) == canonical_bytes(second.to_data())
        assert host.state is initial
        assert host.state_digest == digest


def test_session_addressable_refusal_and_unaddressable_input_preserve_state() -> None:
    host = _state3_host()
    initial = host.state
    digest = host.state_digest
    addressable = json.loads(_request("capabilities.get"))
    addressable["protocol"] = "kir-ai/1"

    refused = decode_response(host.handle_wire_request(
        canonical_bytes(addressable)))
    assert refused.status == "REFUSED"
    assert refused.error.code == "WIRE_PROTOCOL_MISMATCH"
    assert host.state is initial
    assert host.state_digest == digest

    for blob, error_type in (
        (b'{"x":1,"x":2}', WireDecodeError),
        (canonical_bytes({"request_id": "request_1"}), WireShapeError),
    ):
        with pytest.raises(error_type):
            host.handle_wire_request(blob)
        assert host.state is initial
        assert host.state_digest == digest


@pytest.mark.parametrize(
    "mutation",
    ("nonempty_arguments", "protocol_mismatch", "extra_top_level_field"),
)
def test_addressable_malformed_unavailable_request_uses_sealed_refusal(
    mutation,
) -> None:
    host = _state3_host()
    initial = host.state
    digest = host.state_digest
    request = json.loads(_request("build.run"))
    if mutation == "nonempty_arguments":
        request["arguments"] = {"unexpected": True}
    elif mutation == "protocol_mismatch":
        request["protocol"] = "kir-ai/1"
    else:
        request["extra"] = True

    response = decode_response(host.handle_wire_request(
        canonical_bytes(request)))

    assert response.status == "REFUSED"
    assert response.tool == "build.run"
    assert response.coverage == WireCoverageV0.refused(1)
    assert response.error.code == "NOT_AVAILABLE_IN_PROJECT_V0"
    assert response.error.message == (
        "declared tool is unavailable in the offline project V0 fixture")
    assert dict(response.error.details.items()) == {"tool": "build.run"}
    assert response.error.retryable is False
    assert host.state is initial
    assert host.state_digest == digest


def test_session_read_and_query_commit_only_exact_ledgers() -> None:
    host = _state3_host()
    initial = host.state
    read = _call(host, "project.read", _read_arguments(host, "manifest"))
    assert read.status == "OK"
    assert host.state is not initial
    assert len(host.state.read_receipts) == 1
    assert len(host.state.cursors) == 0
    assert canonical_bytes(host.state.read_receipts[0].to_data()) == (
        canonical_bytes(read.read_receipt))

    after_read = host.state
    query = _call(host, "model.query", _query_arguments(host, "summary", {}))
    assert query.status == "OK"
    assert host.state is not after_read
    assert len(host.state.read_receipts) == 2
    assert len(host.state.cursors) == 0
    assert host.state.head is initial.head
    assert host.state.build is initial.build
    assert host.state.build_index is initial.build_index


def test_session_patch_replay_contradiction_conflict_and_refusal() -> None:
    host = _state3_host()
    owner = _call(
        host,
        "project.read",
        _read_arguments(host, "root_instance"),
        request_id="read_root",
    )
    receipt = host.state.read_receipts[-1]
    base = host.state.head.revision_digest
    patch = _root_patch_arguments(host, "patch_1", receipt.ref, 31000)
    applied = _call(host, "source.patch", patch, request_id="patch_apply")
    assert applied.status == "OK"
    assert applied.result["base_revision_digest"] == base
    assert len(host.state.revisions) == 2
    assert len(host.state.patch_outcomes) == 1

    applied_state = host.state
    replayed = _call(host, "source.patch", patch, request_id="patch_replay")
    assert replayed.status == "OK"
    assert host.state is applied_state
    assert canonical_bytes(replayed.result) == canonical_bytes(applied.result)

    contradiction = _root_patch_arguments(
        host,
        "patch_1",
        receipt.ref,
        32000,
        base=base,
    )
    conflict = _call(
        host, "source.patch", contradiction, request_id="patch_conflict")
    assert conflict.status == "CONFLICT"
    assert conflict.error.code == "PATCH_ID_CONTRADICTION"
    assert host.state is applied_state

    missing = ReceiptRefV0(
        "rr_" + "a" * 40,
        "sha256:" + "a" * 64,
    )
    refused_args = _root_patch_arguments(
        host,
        "patch_missing_receipt",
        missing,
        33000,
    )
    refused = _call(host, "source.patch", refused_args)
    assert refused.status == "REFUSED"
    assert refused.error.code == "OWNER_RECEIPT_REQUIRED"
    assert host.state is applied_state
    assert owner.read_receipt is not None


def test_session_trusted_verifier_binds_patch_replay_command_semantics() -> None:
    host = _state3_host()
    _call(
        host,
        "project.read",
        _read_arguments(host, "root_instance"),
        request_id="trusted_patch_owner",
    )
    receipt = host.state.read_receipts[-1]
    base = host.state.head.revision_digest
    original = _root_patch_arguments(
        host,
        "trusted_patch_replay",
        receipt.ref,
        31000,
    )
    assert _call(host, "source.patch", original).status == "OK"
    snapshot = host.state
    contradiction = _root_patch_arguments(
        host,
        "trusted_patch_replay",
        receipt.ref,
        32000,
        base=base,
    )
    calls = {"count": 0}

    def forged_patch(state, command):
        calls["count"] += 1
        prior = state.outcome_map[command.patch_id]
        return KernelTransitionV0(state, prior.result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        _CAPTURED_HANDLERS.read,
        _CAPTURED_HANDLERS.query,
        forged_patch,
    )
    forged_host = _make_offline_project_wire(
        snapshot, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        forged_host,
        "source.patch",
        contradiction,
        request_id="trusted_patch_contradiction",
    )

    assert calls["count"] == 1
    assert response.status == "CONFLICT"
    assert response.error.code == "PATCH_ID_CONTRADICTION"
    assert forged_host.state is snapshot


def test_session_trusted_verifier_rejects_false_existing_module_absence() -> None:
    state = _state3_host().state
    captured = {}

    def forged_read(snapshot, command):
        selector = {"module_id": command.target_id}
        coverage = CoverageV0("COMPLETE", 1, 1, 0)
        result_digest = canonical_digest(
            "kir.ai-project-read-result-body.v0",
            {
                "coverage": coverage.to_data(),
                "present": False,
                "project_id": command.project_id,
                "revision_digest": command.revision_digest,
                "scope": command.scope,
                "selector": selector,
                "value": None,
            },
        )
        receipt = ReadReceiptV0(
            kind="PROJECT_READ",
            authority="OWNER",
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=snapshot.build.manifest.build_digest,
            scope=command.scope,
            selector=selector,
            present=False,
            object_digest=None,
            result_digest=result_digest,
            coverage=coverage,
        )
        result = ProjectReadResultV0(
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=snapshot.build.manifest.build_digest,
            scope=command.scope,
            selector=selector,
            present=False,
            value=None,
            coverage=coverage,
            receipt=receipt,
        )
        candidate = ProjectStateV0(
            project_id=snapshot.project_id,
            head=snapshot.head,
            build=snapshot.build,
            build_index=snapshot.build_index,
            revisions=snapshot.revisions,
            read_receipts=(*snapshot.read_receipts, receipt),
            cursors=snapshot.cursors,
            patch_outcomes=snapshot.patch_outcomes,
        )
        captured["result"] = result
        return KernelTransitionV0(candidate, result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        forged_read,
        _CAPTURED_HANDLERS.query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "project.read",
        ProjectReadCommandV0(
            state.project_id,
            state.head.revision_digest,
            "module",
            "mod_building",
        ).to_data(),
        request_id="trusted_read_truth",
    )

    admitted = parse_project_read_result(strict_json_loads(canonical_bytes(
        captured["result"].to_data())))
    assert admitted.present is False
    assert admitted.receipt.authority == "OWNER"
    assert response.status == "FAILED"
    assert response.error.code == "INTERNAL_FAILURE"
    assert host.state is state


def test_session_54_floor_query_pages_without_drop_or_duplicate() -> None:
    host = OfflineProjectWireV0.from_source(make_tower_source(n_floors=54))
    cursor = None
    logical_ids = []
    while True:
        response = _call(
            host,
            "model.query",
            _query_arguments(
                host,
                "origin",
                {"module_id": "mod_typical_floor"},
                limit=37,
                cursor=cursor,
            ),
            request_id=f"page_{len(logical_ids)}",
        )
        assert response.status == "OK"
        logical_ids.extend(item["logical_id"] for item in response.result["items"])
        raw_cursor = response.result["cursor"]
        if raw_cursor is None:
            assert response.coverage.state == "COMPLETE"
            break
        assert response.coverage.state == "PARTIAL"
        cursor = CursorRefV0(
            raw_cursor["cursor_id"], raw_cursor["cursor_digest"])

    expected = tuple(
        item.logical_id for item in host.state.build.entities
        if item.origin.module_id == "mod_typical_floor")
    assert tuple(logical_ids) == expected
    assert len(logical_ids) == len(set(logical_ids)) == 270
    assert len(host.state.read_receipts) == 8
    assert len(host.state.cursors) == 7


def test_session_accepts_legitimate_k_byte_shrunk_multi_item_page(
    monkeypatch,
) -> None:
    import kukai.ai_protocol.project_v0.query as query_module

    host = OfflineProjectWireV0.from_source(
        make_tower_source(n_floors=54))
    snapshot = host.state
    arguments = _query_arguments(
        host,
        "origin",
        {"module_id": "mod_typical_floor"},
        limit=10,
    )
    monkeypatch.setattr(query_module, "MAX_PAGE_BYTES", 5_000)
    expected_command = _CAPTURED_HANDLERS.parse_query(arguments)
    expected = _CAPTURED_HANDLERS.query(snapshot, expected_command)
    assert 1 < len(expected.result.items) < expected_command.limit
    assert len(canonical_bytes(expected.result.to_data())) <= 5_000

    response = _call(
        host,
        "model.query",
        arguments,
        request_id="byte_shrunk_page",
    )

    assert response.status == "OK"
    assert len(response.result["items"]) == len(expected.result.items)
    assert canonical_bytes(host.state.to_data()) == canonical_bytes(
        expected.state.to_data())


def test_private_encoder_wraps_arbitrary_decoder_failure_without_leak() -> None:
    response = WireResponseV0(
        "request_1",
        "capabilities.get",
        "OK",
        WireCoverageV0.complete(1),
        CAPABILITY_REGISTRY.to_data(),
        None,
        None,
    )

    def explode(_payload):
        raise RuntimeError("secret decoder traceback")

    encoder = _make_response_encoder(explode)
    with pytest.raises(WireEncodeError) as caught:
        encoder(response)
    assert caught.value.code == "WIRE_RESPONSE_SELF_ADMISSION_FAILED"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("late_stage", ["encode", "decode"])
def test_session_late_codec_failure_returns_generic_failed_without_commit(
    late_stage,
) -> None:
    state = _state3_host().state
    calls = {"count": 0}

    def flaky_encoder(response):
        calls["count"] += 1
        if late_stage == "encode" and calls["count"] == 1:
            raise RuntimeError("secret encoder traceback")
        return _CAPTURED_CODECS.response_encoder(response)

    def flaky_decoder(payload):
        calls["count"] += 1
        if late_stage == "decode" and calls["count"] == 1:
            raise RuntimeError("secret decoder traceback")
        return _CAPTURED_CODECS.response_decoder(payload)

    codecs = _SessionCodecs(
        _CAPTURED_CODECS.request_decoder,
        flaky_encoder if late_stage == "encode" else (
            _CAPTURED_CODECS.response_encoder),
        flaky_decoder if late_stage == "decode" else (
            _CAPTURED_CODECS.response_decoder),
    )
    host = _make_offline_project_wire(state, codecs=codecs)
    response = decode_response(host.handle_wire_request(
        _request("capabilities.get")))

    assert response.status == "FAILED"
    assert response.error.code == "INTERNAL_FAILURE"
    assert "secret" not in canonical_bytes(response.to_data()).decode()
    assert host.state is state


def test_session_uses_captured_codecs_after_public_monkeypatch(monkeypatch) -> None:
    host = _state3_host()

    def explode(*_args, **_kwargs):
        raise RuntimeError("public codec was used")

    import kukai.ai_protocol.project_v0.wire_v0.wire as public_wire

    monkeypatch.setattr(public_wire, "decode_request", explode)
    monkeypatch.setattr(public_wire, "decode_response", explode)
    monkeypatch.setattr(public_wire, "encode_response", explode)
    payload = host.handle_wire_request(_request("capabilities.get"))
    response = _CAPTURED_CODECS.response_decoder(payload)
    assert response.status == "OK"


def test_session_reentrant_handler_fails_closed_without_state_change() -> None:
    state = _state3_host().state
    box = {}
    request = _request(
        "project.read",
        ProjectReadCommandV0(
            state.project_id,
            state.head.revision_digest,
            "root_instance",
        ).to_data(),
    )

    def reentrant_read(_state, _command):
        return box["host"].handle_wire_request(request)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        reentrant_read,
        _CAPTURED_HANDLERS.query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    box["host"] = host
    response = decode_response(host.handle_wire_request(request))
    assert response.status == "FAILED"
    assert response.error.code == "INTERNAL_FAILURE"
    assert host.state is state


def test_session_unknown_handler_exception_is_generic_and_atomic() -> None:
    state = _state3_host().state

    def explode(_state, _command):
        raise RuntimeError("sensitive local failure")

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        explode,
        _CAPTURED_HANDLERS.query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "project.read",
        ProjectReadCommandV0(
            state.project_id,
            state.head.revision_digest,
            "root_instance",
        ).to_data(),
    )
    assert response.status == "FAILED"
    assert response.error.code == "INTERNAL_FAILURE"
    assert "sensitive" not in canonical_bytes(response.to_data()).decode()
    assert host.state is state


def test_session_rejects_valid_foreign_cursor_candidate_before_commit() -> None:
    state = _state3_host().state
    captured = {}

    def forged_query(snapshot, command):
        real = _CAPTURED_HANDLERS.query(snapshot, command)
        foreign_cursor = CursorRecordV0(
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=command.build_digest,
            scope=command.scope,
            filters=command.filters,
            offset=len(real.result.items) + 7,
            limit=command.limit,
            chain_digest=real.result.receipt.chain_digest,
        )
        forged_result = ModelQueryResultV0(
            project_id=real.result.project_id,
            revision_digest=real.result.revision_digest,
            build_digest=real.result.build_digest,
            scope=real.result.scope,
            filters=real.result.filters,
            items=real.result.items,
            coverage=real.result.coverage,
            cursor=foreign_cursor.ref,
            receipt=real.result.receipt,
        )
        candidate = ProjectStateV0(
            project_id=real.state.project_id,
            head=real.state.head,
            build=real.state.build,
            build_index=real.state.build_index,
            revisions=real.state.revisions,
            read_receipts=real.state.read_receipts,
            cursors=(*snapshot.cursors, foreign_cursor),
            patch_outcomes=real.state.patch_outcomes,
        )
        captured["result"] = forged_result
        return KernelTransitionV0(candidate, forged_result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        _CAPTURED_HANDLERS.read,
        forged_query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "model.query",
        ModelQueryCommandV0(
            project_id=state.project_id,
            revision_digest=state.head.revision_digest,
            build_digest=state.build.manifest.build_digest,
            scope="origin",
            filters={"module_id": "mod_typical_floor"},
            limit=2,
        ).to_data(),
    )
    assert parse_model_query_result(strict_json_loads(canonical_bytes(
        captured["result"].to_data()))).cursor
    assert response.status == "FAILED"
    assert response.error.code == "INTERNAL_FAILURE"
    assert host.state is state


def test_session_rejects_read_receipt_with_foreign_valid_build_binding() -> None:
    state = _state3_host().state
    foreign_build = "sha256:" + "a" * 64
    captured = {}

    def forged_read(snapshot, command):
        real = _CAPTURED_HANDLERS.read(snapshot, command)
        old = real.result.receipt
        receipt = ReadReceiptV0(
            kind=old.kind,
            authority=old.authority,
            project_id=old.project_id,
            revision_digest=old.revision_digest,
            build_digest=foreign_build,
            scope=old.scope,
            selector=old.selector,
            present=old.present,
            object_digest=old.object_digest,
            result_digest=old.result_digest,
            coverage=old.coverage,
            chain_digest=old.chain_digest,
        )
        forged_result = ProjectReadResultV0(
            project_id=real.result.project_id,
            revision_digest=real.result.revision_digest,
            build_digest=foreign_build,
            scope=real.result.scope,
            selector=real.result.selector,
            present=real.result.present,
            value=real.result.value,
            coverage=real.result.coverage,
            receipt=receipt,
        )
        candidate = ProjectStateV0(
            project_id=real.state.project_id,
            head=real.state.head,
            build=real.state.build,
            build_index=real.state.build_index,
            revisions=real.state.revisions,
            read_receipts=(*snapshot.read_receipts, receipt),
            cursors=real.state.cursors,
            patch_outcomes=real.state.patch_outcomes,
        )
        captured["result"] = forged_result
        return KernelTransitionV0(candidate, forged_result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        forged_read,
        _CAPTURED_HANDLERS.query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "project.read",
        ProjectReadCommandV0(
            state.project_id,
            state.head.revision_digest,
            "root_instance",
        ).to_data(),
    )
    assert parse_project_read_result(strict_json_loads(canonical_bytes(
        captured["result"].to_data()))).build_digest == foreign_build
    assert response.status == "FAILED"
    assert host.state is state


def test_session_recomputes_chain_for_final_cursor_continuation() -> None:
    first_host = _state3_host()
    filters = {"module_id": "mod_typical_floor"}
    first = _call(
        first_host,
        "model.query",
        _query_arguments(first_host, "origin", filters, limit=10),
        request_id="first_page",
    )
    assert first.coverage.state == "PARTIAL"
    raw_cursor = first.result["cursor"]
    cursor = CursorRefV0(
        raw_cursor["cursor_id"], raw_cursor["cursor_digest"])
    state = first_host.state
    captured = {}

    def forged_final_query(snapshot, command):
        real = _CAPTURED_HANDLERS.query(snapshot, command)
        assert real.result.cursor is None
        fake_chain = "sha256:" + "a" * 64
        coverage = real.result.coverage
        result_digest = canonical_digest(
            "kir.ai-model-query-result-body.v0",
            {
                "build_digest": real.result.build_digest,
                "chain_digest": fake_chain,
                "coverage": coverage.to_data(),
                "filters": real.result.filters,
                "items": real.result.items,
                "project_id": real.result.project_id,
                "revision_digest": real.result.revision_digest,
                "scope": real.result.scope,
            },
        )
        old = real.result.receipt
        receipt = ReadReceiptV0(
            kind=old.kind,
            authority=old.authority,
            project_id=old.project_id,
            revision_digest=old.revision_digest,
            build_digest=old.build_digest,
            scope=old.scope,
            selector=old.selector,
            present=old.present,
            object_digest=old.object_digest,
            result_digest=result_digest,
            coverage=CoverageV0(
                coverage.state,
                coverage.requested,
                coverage.evaluated,
                coverage.returned,
            ),
            chain_digest=fake_chain,
        )
        forged_result = ModelQueryResultV0(
            project_id=real.result.project_id,
            revision_digest=real.result.revision_digest,
            build_digest=real.result.build_digest,
            scope=real.result.scope,
            filters=real.result.filters,
            items=real.result.items,
            coverage=coverage,
            cursor=None,
            receipt=receipt,
        )
        candidate = ProjectStateV0(
            project_id=real.state.project_id,
            head=real.state.head,
            build=real.state.build,
            build_index=real.state.build_index,
            revisions=real.state.revisions,
            read_receipts=(*snapshot.read_receipts, receipt),
            cursors=snapshot.cursors,
            patch_outcomes=real.state.patch_outcomes,
        )
        captured["result"] = forged_result
        return KernelTransitionV0(candidate, forged_result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        _CAPTURED_HANDLERS.read,
        forged_final_query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        state, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "model.query",
        _query_arguments(
            host, "origin", filters, limit=10, cursor=cursor),
        request_id="forged_final_page",
    )
    admitted = parse_model_query_result(strict_json_loads(canonical_bytes(
        captured["result"].to_data())))
    assert admitted.cursor is None
    assert admitted.receipt.chain_digest == "sha256:" + "a" * 64
    assert response.status == "FAILED"
    assert host.state is state


@pytest.mark.parametrize("forged_returned", [8, 9])
def test_session_rejects_equal_or_plus_one_forged_continuation_page(
    forged_returned,
) -> None:
    first_host = _state3_host()
    filters = {"module_id": "mod_typical_floor"}
    first = _call(
        first_host,
        "model.query",
        _query_arguments(first_host, "origin", filters, limit=10),
        request_id="exact_page_first",
    )
    raw_cursor = first.result["cursor"]
    cursor_ref = CursorRefV0(
        raw_cursor["cursor_id"], raw_cursor["cursor_digest"])
    snapshot = first_host.state
    prior = snapshot.cursor_map[cursor_ref.cursor_id]
    records = tuple(
        item.to_data() for item in snapshot.build_index.by_origin(
            module_id="mod_typical_floor").entities)

    def forged_query(state, command):
        real = _CAPTURED_HANDLERS.query(state, command)
        forged_items = records[:forged_returned]
        coverage = CoverageV0(
            "COMPLETE",
            len(state.build_index.entities),
            len(state.build_index.entities),
            forged_returned,
        )
        chain = canonical_digest("kir.ai-model-query-chain.v0", {
            "end_offset": prior.offset + forged_returned,
            "item_keys": tuple(item["logical_id"] for item in forged_items),
            "previous_chain_digest": prior.chain_digest,
            "start_offset": prior.offset,
        })
        result_digest = canonical_digest(
            "kir.ai-model-query-result-body.v0",
            {
                "build_digest": command.build_digest,
                "chain_digest": chain,
                "coverage": coverage.to_data(),
                "filters": command.filters,
                "items": forged_items,
                "project_id": command.project_id,
                "revision_digest": command.revision_digest,
                "scope": command.scope,
            },
        )
        receipt = ReadReceiptV0(
            kind="MODEL_QUERY",
            authority="INFORMATIONAL",
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=command.build_digest,
            scope=command.scope,
            selector=command.filters,
            present=None,
            object_digest=None,
            result_digest=result_digest,
            coverage=coverage,
            chain_digest=chain,
        )
        forged_result = ModelQueryResultV0(
            project_id=command.project_id,
            revision_digest=command.revision_digest,
            build_digest=command.build_digest,
            scope=command.scope,
            filters=command.filters,
            items=forged_items,
            coverage=coverage,
            cursor=None,
            receipt=receipt,
        )
        candidate = ProjectStateV0(
            project_id=state.project_id,
            head=state.head,
            build=state.build,
            build_index=state.build_index,
            revisions=state.revisions,
            read_receipts=(*state.read_receipts, receipt),
            cursors=state.cursors,
            patch_outcomes=state.patch_outcomes,
        )
        assert real.result.cursor is None
        assert parse_model_query_result(strict_json_loads(canonical_bytes(
            forged_result.to_data()))).coverage.returned == forged_returned
        return KernelTransitionV0(candidate, forged_result)

    handlers = _SessionHandlers(
        _CAPTURED_HANDLERS.parse_read,
        _CAPTURED_HANDLERS.parse_query,
        _CAPTURED_HANDLERS.parse_patch,
        _CAPTURED_HANDLERS.read,
        forged_query,
        _CAPTURED_HANDLERS.patch,
    )
    host = _make_offline_project_wire(
        snapshot, codecs=_CAPTURED_CODECS, handlers=handlers)
    response = _call(
        host,
        "model.query",
        _query_arguments(
            host, "origin", filters, limit=10, cursor=cursor_ref),
        request_id=f"forged_returned_{forged_returned}",
    )
    assert response.status == "FAILED"
    assert host.state is snapshot


@pytest.mark.parametrize(
    (
        "floors",
        "entity_count",
        "instance_count",
        "origin_count",
        "page_limit",
        "page_count",
        "cursor_count",
        "final_receipt_count",
    ),
    [
        (3, 18, 4, 15, 7, 3, 2, 10),
        (54, 324, 55, 270, 37, 8, 7, 15),
    ],
)
def test_full_bytes_only_fixture_flow_and_request_id_exclusion(
    floors,
    entity_count,
    instance_count,
    origin_count,
    page_limit,
    page_count,
    cursor_count,
    final_receipt_count,
) -> None:
    host = OfflineProjectWireV0.from_source(
        make_tower_source(n_floors=floors))
    initial_build = host.state.build.manifest.build_digest

    capabilities = _call(
        host, "capabilities.get", request_id=f"caps_{floors}")
    assert capabilities.status == "OK"
    manifest = _call(
        host,
        "project.read",
        _read_arguments(host, "manifest"),
        request_id=f"manifest_{floors}",
    )
    assert manifest.result["value"]["entity_count"] == entity_count
    assert manifest.result["value"]["instance_count"] == instance_count

    module = _call(
        host,
        "project.read",
        _read_arguments(host, "module", "mod_building"),
        request_id=f"module_{floors}",
    )
    assert module.result["present"] is True
    assert module.result["value"]["module_id"] == "mod_building"
    root = _call(
        host,
        "project.read",
        _read_arguments(host, "root_instance"),
        request_id=f"root_{floors}",
    )
    root_receipt = host.state.receipt_map[root.read_receipt["receipt_id"]]
    assert root_receipt.authority == "OWNER"

    summary = _call(
        host,
        "model.query",
        _query_arguments(host, "summary", {}),
        request_id=f"summary_{floors}",
    )
    assert summary.result["items"][0]["entity_count"] == entity_count

    cursor = None
    logical_ids = []
    pages = 0
    while True:
        page = _call(
            host,
            "model.query",
            _query_arguments(
                host,
                "origin",
                {"module_id": "mod_typical_floor"},
                limit=page_limit,
                cursor=cursor,
            ),
            request_id=f"origin_{floors}_{pages}",
        )
        pages += 1
        logical_ids.extend(
            item["logical_id"] for item in page.result["items"])
        raw_cursor = page.result["cursor"]
        if raw_cursor is None:
            break
        cursor = CursorRefV0(
            raw_cursor["cursor_id"], raw_cursor["cursor_digest"])
    assert pages == page_count
    assert len(logical_ids) == len(set(logical_ids)) == origin_count
    assert len(host.state.cursors) == cursor_count
    assert len(host.state.read_receipts) == 4 + page_count

    base = host.state.head.revision_digest
    patch_arguments = _root_patch_arguments(
        host,
        f"patch_flow_{floors}",
        root_receipt.ref,
        30000 + floors,
    )
    applied = _call(
        host,
        "source.patch",
        patch_arguments,
        request_id=f"patch_apply_{floors}",
    )
    assert applied.status == "OK"
    assert len(host.state.revisions) == 2
    assert len(host.state.patch_outcomes) == 1
    assert len(host.state.cursors) == cursor_count
    assert len(host.state.read_receipts) == 4 + page_count
    assert host.state.build.manifest.build_digest != initial_build

    patched_state = host.state
    replay = _call(
        host,
        "source.patch",
        patch_arguments,
        request_id=f"patch_replay_different_outer_id_{floors}",
    )
    assert replay.request_id != applied.request_id
    assert canonical_bytes(replay.result) == canonical_bytes(applied.result)
    assert replay.result["base_revision_digest"] == base
    assert host.state is patched_state

    reread_manifest = _call(
        host,
        "project.read",
        _read_arguments(host, "manifest"),
        request_id=f"reread_manifest_{floors}",
    )
    reread_root = _call(
        host,
        "project.read",
        _read_arguments(host, "root_instance"),
        request_id=f"reread_root_{floors}",
    )
    requery = _call(
        host,
        "model.query",
        _query_arguments(host, "summary", {}),
        request_id=f"requery_summary_{floors}",
    )
    assert reread_manifest.result["value"]["entity_count"] == entity_count
    assert reread_manifest.result["value"]["instance_count"] == instance_count
    assert reread_root.result["value"]["arguments"]["floor_width"] == str(
        30000 + floors)
    assert requery.result["items"][0]["entity_count"] == entity_count
    assert len(host.state.revisions) == 2
    assert len(host.state.patch_outcomes) == 1
    assert len(host.state.read_receipts) == final_receipt_count
    assert len(host.state.cursors) == cursor_count
