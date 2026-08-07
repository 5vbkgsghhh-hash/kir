from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.project_v0 import (
    ModelQueryCommandV0,
    ProjectReadCommandV0,
    ReadReceiptV0,
    RootPutV0,
    SourcePatchCommandV0,
    create_project_state,
    model_query,
    project_read,
    source_patch,
)
from kukai.ai_protocol.project_v0.errors import ProjectContractError
from kukai.ai_protocol.project_v0.wire_v0.result_codec import (
    parse_k_coverage,
    parse_k_read_receipt,
    parse_model_query_result,
    parse_project_read_result,
    parse_source_patch_result,
)
from kukai.ai_protocol.project_v0.wire_v0 import (
    CAPABILITY_REGISTRY,
    WireCoverageV0,
    WireErrorV0,
    WireResponseV0,
    decode_response,
    encode_response,
)
from kukai.ai_protocol.project_v0.wire_v0.contracts import PROTOCOL_VERSION
from kukai.ai_protocol.project_v0.wire_v0.contracts import (
    AVAILABLE_TOOL_NAMES,
    DECLARED_TOOL_NAMES,
    MAX_RESULT_BYTES,
)
from kukai.ai_protocol.project_v0.schemas import MAX_PAGE_BYTES, MAX_PAGE_ITEMS
from kukai.ai_protocol.project_v0.wire_v0.errors import (
    WireContractError,
    WireDecodeError,
    WireEncodeError,
)
from kukai.ai_protocol.project_v0.wire_v0.registry import (
    NOT_AVAILABLE_IN_PROJECT_V0,
    PUBLISH_NOT_AVAILABLE_BEFORE_SRV1,
)
from kukai.design_source import (
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)
from kukai.design_source.examples import make_tower_source


def _manifest_result():
    state = create_project_state(make_tower_source(n_floors=3))
    command = ProjectReadCommandV0(
        state.project_id,
        state.head.revision_digest,
        "manifest",
    )
    return project_read(state, command).result


def _state3():
    return create_project_state(make_tower_source(n_floors=3))


def _read(state, scope, target_id=None):
    return project_read(state, ProjectReadCommandV0(
        state.project_id,
        state.head.revision_digest,
        scope,
        target_id,
    ))


def _query(state, scope, filters, *, limit=128):
    return model_query(state, ModelQueryCommandV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope=scope,
        filters=filters,
        limit=limit,
    ))


def _patch_result():
    state = _state3()
    read = _read(state, "root_instance")
    arguments = dict(read.state.head.root.arguments.items())
    arguments["floor_width"] = "31000"
    root = RootInstanceV0(
        read.state.head.root.instance_id,
        read.state.head.root.module_id,
        arguments,
    )
    command = SourcePatchCommandV0(
        project_id=read.state.project_id,
        base_revision_digest=read.state.head.revision_digest,
        patch_id="patch_response_codec",
        receipt_refs=(read.result.receipt.ref,),
        operations=(RootPutV0("put_root", root),),
    )
    return source_patch(read.state, command).result


def _fresh(value):
    return strict_json_loads(canonical_bytes(value))


def test_k_coverage_and_receipt_recompute_exact_derived_values() -> None:
    result = _manifest_result()

    coverage = parse_k_coverage(_fresh(result.coverage.to_data()))
    receipt = parse_k_read_receipt(_fresh(result.receipt.to_data()))

    assert coverage is not result.coverage
    assert receipt is not result.receipt
    assert canonical_bytes(coverage.to_data()) == canonical_bytes(
        result.coverage.to_data())
    assert canonical_bytes(receipt.to_data()) == canonical_bytes(
        result.receipt.to_data())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"extra": True}),
        lambda data: data.update({"schema": "wrong/0"}),
        lambda data: data.update({"receipt_id": "rr_" + "a" * 40}),
        lambda data: data.update({"receipt_digest": "sha256:" + "a" * 64}),
        lambda data: data["coverage"].update({"returned": 0}),
    ],
)
def test_k_receipt_tamper_corpus_is_refused(mutation) -> None:
    data = json.loads(canonical_bytes(_manifest_result().receipt.to_data()))
    mutation(data)

    with pytest.raises(ProjectContractError):
        parse_k_read_receipt(_fresh(data))


def test_k_coverage_requires_exact_closed_shape() -> None:
    data = json.loads(canonical_bytes(_manifest_result().coverage.to_data()))
    data["requested"] = True

    with pytest.raises(ProjectContractError):
        parse_k_coverage(_fresh(data))


def test_every_project_read_result_variant_is_semantically_admitted() -> None:
    state = _state3()
    requests = (
        ("manifest", None),
        ("module.index", None),
        ("exception.index", None),
        ("root_instance", None),
        ("module", "mod_building"),
        ("module", "mod_missing"),
        ("exception", "exc_missing"),
    )
    for scope, target_id in requests:
        transition = _read(state, scope, target_id)
        state = transition.state
        admitted = parse_project_read_result(_fresh(transition.result.to_data()))
        assert canonical_bytes(admitted.to_data()) == canonical_bytes(
            transition.result.to_data())
        assert admitted is not transition.result


def test_project_read_result_rejects_valid_receipt_from_other_scope() -> None:
    state = _state3()
    manifest = _read(state, "manifest")
    root = _read(manifest.state, "root_instance")
    data = json.loads(canonical_bytes(manifest.result.to_data()))
    data["receipt"] = json.loads(canonical_bytes(root.result.receipt.to_data()))

    with pytest.raises(ProjectContractError, match="binding mismatch"):
        parse_project_read_result(_fresh(data))


def test_query_result_variants_and_partial_page_are_semantically_admitted() -> None:
    state = _state3()
    summary = _query(state, "summary", {})
    logical_id = state.build.entities[0].logical_id
    logical = _query(
        summary.state, "logical_id", {"logical_id": logical_id})
    partial = _query(
        logical.state,
        "origin",
        {"module_id": "mod_typical_floor"},
        limit=2,
    )

    for transition in (summary, logical, partial):
        admitted = parse_model_query_result(_fresh(transition.result.to_data()))
        assert canonical_bytes(admitted.to_data()) == canonical_bytes(
            transition.result.to_data())
    assert partial.result.coverage.state == "PARTIAL"


def test_query_result_rejects_filter_item_and_receipt_binding_drift() -> None:
    result = _query(
        _state3(), "origin", {"module_id": "mod_typical_floor"}, limit=2
    ).result
    data = json.loads(canonical_bytes(result.to_data()))
    data["filters"] = {"module_id": "mod_building"}

    with pytest.raises(ProjectContractError):
        parse_model_query_result(_fresh(data))


def test_query_page_item_cap_accepts_128_and_refuses_forged_129() -> None:
    state = create_project_state(make_tower_source(n_floors=54))
    transition = _query(
        state,
        "origin",
        {"module_id": "mod_typical_floor"},
        limit=MAX_PAGE_ITEMS,
    )
    assert len(transition.result.items) == MAX_PAGE_ITEMS
    admitted = parse_model_query_result(_fresh(transition.result.to_data()))
    assert len(admitted.items) == MAX_PAGE_ITEMS

    matching = tuple(
        item for item in state.build.entities
        if item.origin.module_id == "mod_typical_floor"
    )
    data = json.loads(canonical_bytes(transition.result.to_data()))
    data["items"].append(json.loads(canonical_bytes(
        matching[MAX_PAGE_ITEMS].to_data())))
    data["coverage"]["returned"] = MAX_PAGE_ITEMS + 1
    _rebind_query_receipt(data)

    with pytest.raises(ProjectContractError, match="page cap"):
        parse_model_query_result(_fresh(data))

    envelope = json.loads(encode_response(_ok_response(
        "model.query",
        transition.result.to_data(),
        receipt=transition.result.receipt.to_data(),
        coverage=WireCoverageV0(
            transition.result.coverage.state,
            transition.result.coverage.requested,
            transition.result.coverage.evaluated,
            transition.result.coverage.returned,
        ),
    )))
    envelope["result"] = data
    envelope["read_receipt"] = data["receipt"]
    envelope["coverage"]["returned"] = MAX_PAGE_ITEMS + 1
    with pytest.raises(WireDecodeError, match="page cap"):
        decode_response(canonical_bytes(envelope))

    forged = WireResponseV0(
        request_id="request_response_1",
        tool="model.query",
        status="OK",
        coverage=WireCoverageV0(
            "PARTIAL",
            data["coverage"]["requested"],
            data["coverage"]["evaluated"],
            data["coverage"]["returned"],
        ),
        result=data,
        error=None,
        read_receipt=data["receipt"],
    )
    with pytest.raises(WireEncodeError):
        encode_response(forged)


def test_query_page_byte_cap_accepts_exact_and_refuses_plus_one() -> None:
    exact = _padded_logical_query_result(MAX_PAGE_BYTES)
    assert len(canonical_bytes(exact)) == MAX_PAGE_BYTES
    assert parse_model_query_result(_fresh(exact)).items

    too_large = _padded_logical_query_result(MAX_PAGE_BYTES + 1)
    assert len(canonical_bytes(too_large)) == MAX_PAGE_BYTES + 1
    with pytest.raises(ProjectContractError, match="page cap"):
        parse_model_query_result(_fresh(too_large))


def test_result_parser_normalizes_design_source_contract_failures() -> None:
    summary = _query(_state3(), "summary", {}).result
    data = json.loads(canonical_bytes(summary.to_data()))
    data["items"][0]["counts_by_semantic_type"]["bim.wall"] = 0
    with pytest.raises(ProjectContractError) as caught:
        parse_model_query_result(_fresh(data))
    assert type(caught.value) is ProjectContractError

    state = _state3()
    logical_id = next(
        item.logical_id for item in state.build.entities if item.dependencies)
    entity = _query(
        state, "logical_id", {"logical_id": logical_id}).result
    data = json.loads(canonical_bytes(entity.to_data()))
    dependency = data["items"][0]["dependencies"][0]
    data["items"][0]["dependencies"].append(dependency)
    with pytest.raises(ProjectContractError) as caught:
        parse_model_query_result(_fresh(data))
    assert type(caught.value) is ProjectContractError


def test_source_patch_result_recomputes_transition_digest() -> None:
    result = _patch_result()
    admitted = parse_source_patch_result(_fresh(result.to_data()))
    assert admitted is not result
    assert canonical_bytes(admitted.to_data()) == canonical_bytes(result.to_data())

    data = json.loads(canonical_bytes(result.to_data()))
    data["transition_digest"] = "sha256:" + "a" * 64
    with pytest.raises(ProjectContractError, match="transition_digest"):
        parse_source_patch_result(_fresh(data))


def _reissue_read_receipt(data, *, object_digest, result_digest):
    old = data["receipt"]
    return ReadReceiptV0(
        kind=old["kind"],
        authority=old["authority"],
        project_id=old["project_id"],
        revision_digest=old["revision_digest"],
        build_digest=old["build_digest"],
        scope=old["scope"],
        selector=old["selector"],
        present=old["present"],
        object_digest=object_digest,
        result_digest=result_digest,
        coverage=parse_k_coverage(_fresh(data["coverage"])),
        chain_digest=old["chain_digest"],
    )


def _rebind_query_receipt(data):
    old = data["receipt"]
    result_digest = canonical_digest("kir.ai-model-query-result-body.v0", {
        "build_digest": data["build_digest"],
        "chain_digest": old["chain_digest"],
        "coverage": data["coverage"],
        "filters": data["filters"],
        "items": data["items"],
        "project_id": data["project_id"],
        "revision_digest": data["revision_digest"],
        "scope": data["scope"],
    })
    receipt = _reissue_read_receipt(
        data,
        object_digest=None,
        result_digest=result_digest,
    )
    data["receipt"] = json.loads(canonical_bytes(receipt.to_data()))


def _padded_logical_query_result(target_bytes):
    state = _state3()
    logical_id = state.build.entities[0].logical_id
    result = _query(
        state, "logical_id", {"logical_id": logical_id}).result
    data = json.loads(canonical_bytes(result.to_data()))
    data["items"][0]["properties"]["wire_padding"] = ""
    for _ in range(4):
        _rebind_query_receipt(data)
        difference = target_bytes - len(canonical_bytes(data))
        padding = data["items"][0]["properties"]["wire_padding"]
        if difference == 0:
            return data
        if difference < 0 and -difference > len(padding):
            raise AssertionError("target page is smaller than its fixed payload")
        data["items"][0]["properties"]["wire_padding"] = (
            padding + "x" * difference
            if difference > 0
            else padding[:difference]
        )
    _rebind_query_receipt(data)
    assert len(canonical_bytes(data)) == target_bytes
    return data


@pytest.mark.parametrize("kind", ["module", "exception"])
def test_read_selector_cannot_be_rebound_to_a_valid_foreign_payload(kind) -> None:
    if kind == "module":
        state = _state3()
        transition = _read(state, "module", "mod_building")
        foreign = state.head.module_map["mod_typical_floor"]
        foreign_data = foreign.semantic_data()
        object_digest = foreign.module_digest
    else:
        state = create_project_state(make_tower_source(
            n_floors=3, exception_floor_key="L002"))
        original = state.head.exceptions[0]
        transition = _read(state, "exception", original.exception_id)
        foreign = SetInstanceArgumentExceptionV0(
            exception_id="exc_foreign",
            target_instance_id=original.target_instance_id,
            parameter_id=original.parameter_id,
            expected_value=original.expected_value,
            value=original.value,
        )
        foreign_data = foreign.to_data()
        object_digest = foreign.exception_digest

    data = json.loads(canonical_bytes(transition.result.to_data()))
    data["value"] = json.loads(canonical_bytes(foreign_data))
    result_digest = canonical_digest("kir.ai-project-read-result-body.v0", {
        "coverage": data["coverage"],
        "present": data["present"],
        "project_id": data["project_id"],
        "revision_digest": data["revision_digest"],
        "scope": data["scope"],
        "selector": data["selector"],
        "value": data["value"],
    })
    data["receipt"] = json.loads(canonical_bytes(_reissue_read_receipt(
        data,
        object_digest=object_digest,
        result_digest=result_digest,
    ).to_data()))

    with pytest.raises(ProjectContractError, match="selector/value identity"):
        parse_project_read_result(_fresh(data))


def test_logical_query_empty_item_census_is_typed_not_index_error() -> None:
    state = _state3()
    logical_id = state.build.entities[0].logical_id
    result = _query(
        state, "logical_id", {"logical_id": logical_id}).result
    data = json.loads(canonical_bytes(result.to_data()))
    data["items"] = []
    data["coverage"]["returned"] = 0

    with pytest.raises(ProjectContractError, match="logical_id query"):
        parse_model_query_result(_fresh(data))

    wire = _ok_response(
        "model.query",
        result.to_data(),
        receipt=result.receipt.to_data(),
        coverage=WireCoverageV0.complete(1),
    )
    envelope = json.loads(encode_response(wire))
    envelope["result"]["items"] = []
    envelope["result"]["coverage"]["returned"] = 0
    envelope["coverage"]["returned"] = 0
    with pytest.raises(WireDecodeError, match="logical_id query"):
        decode_response(canonical_bytes(envelope))


def _ok_response(tool, result, *, receipt=None, coverage=None):
    return WireResponseV0(
        request_id="request_response_1",
        tool=tool,
        status="OK",
        coverage=WireCoverageV0.complete(1) if coverage is None else coverage,
        result=result,
        error=None,
        read_receipt=receipt,
    )


def test_response_round_trip_all_four_available_tools_is_fresh() -> None:
    state = _state3()
    read = _read(state, "manifest")
    query = _query(read.state, "summary", {})
    patch = _patch_result()
    cases = (
        _ok_response("capabilities.get", CAPABILITY_REGISTRY.to_data()),
        _ok_response(
            "project.read",
            read.result.to_data(),
            receipt=read.result.receipt.to_data(),
            coverage=WireCoverageV0(
                read.result.coverage.state,
                read.result.coverage.requested,
                read.result.coverage.evaluated,
                read.result.coverage.returned,
            ),
        ),
        _ok_response(
            "model.query",
            query.result.to_data(),
            receipt=query.result.receipt.to_data(),
            coverage=WireCoverageV0(
                query.result.coverage.state,
                query.result.coverage.requested,
                query.result.coverage.evaluated,
                query.result.coverage.returned,
            ),
        ),
        _ok_response("source.patch", patch.to_data()),
    )
    for response in cases:
        payload = encode_response(response)
        first = decode_response(payload)
        second = decode_response(payload)
        assert first is not second
        assert first.result is not second.result
        assert canonical_bytes(first.to_data()) == payload
        assert canonical_bytes(second.to_data()) == payload


def test_response_decoder_rejects_outer_coverage_and_receipt_drift() -> None:
    read = _read(_state3(), "manifest").result
    response = _ok_response(
        "project.read",
        read.to_data(),
        receipt=read.receipt.to_data(),
        coverage=WireCoverageV0.complete(1),
    )
    data = json.loads(encode_response(response))
    data["coverage"]["returned"] = 0
    with pytest.raises((WireContractError, WireDecodeError)):
        decode_response(canonical_bytes(data))

    data = json.loads(encode_response(response))
    data["read_receipt"]["receipt_id"] = "rr_" + "a" * 40
    with pytest.raises((WireContractError, WireDecodeError)):
        decode_response(canonical_bytes(data))


def test_response_decoder_strict_json_and_envelope_corpus_is_typed() -> None:
    with pytest.raises(WireDecodeError):
        decode_response(b'{"x":1,"x":2}')
    with pytest.raises((WireContractError, WireDecodeError)):
        decode_response(canonical_bytes({
            "coverage": WireCoverageV0.complete(1).to_data(),
            "error": None,
            "protocol": PROTOCOL_VERSION,
            "read_receipt": None,
            "request_id": "request_1",
            "result": CAPABILITY_REGISTRY.to_data(),
            "status": "OK",
            "tool": "capabilities.get",
            "extra": True,
        }))


@pytest.mark.parametrize(
    "blob",
    [
        None,
        "{}",
        bytearray(b"{}"),
        b'{"x":1.0}',
        b'[' * 129 + b']' * 129,
    ],
)
def test_response_decoder_reuses_strict_bytes_json_boundary(blob) -> None:
    with pytest.raises(WireDecodeError):
        decode_response(blob)


def test_response_result_budget_is_checked_before_result_semantics() -> None:
    empty_size = len(canonical_bytes({"padding": ""}))
    result = {"padding": "x" * (MAX_RESULT_BYTES + 1 - empty_size)}
    assert len(canonical_bytes(result)) == MAX_RESULT_BYTES + 1
    response = {
        "coverage": WireCoverageV0.complete(1).to_data(),
        "error": None,
        "protocol": PROTOCOL_VERSION,
        "read_receipt": None,
        "request_id": "request_1",
        "result": result,
        "status": "OK",
        "tool": "capabilities.get",
    }
    with pytest.raises(WireDecodeError, match="byte limit"):
        decode_response(canonical_bytes(response))


def test_encode_response_self_admission_rejects_semantic_drift() -> None:
    invalid = WireResponseV0(
        request_id="request_1",
        tool="capabilities.get",
        status="OK",
        coverage=WireCoverageV0.complete(1),
        result={"not": "the registry"},
        error=None,
        read_receipt=None,
    )
    with pytest.raises(WireEncodeError):
        encode_response(invalid)


@pytest.mark.parametrize(
    ("status", "coverage", "error"),
    [
        (
            "CONFLICT",
            WireCoverageV0.not_evaluated(1),
            WireErrorV0("PROJECT_STATE_CONFLICT", "head changed", False, {}),
        ),
        (
            "REFUSED",
            WireCoverageV0.refused(1),
            WireErrorV0("PROJECT_CONTRACT_INVALID", "invalid", False, {}),
        ),
        (
            "FAILED",
            WireCoverageV0.not_evaluated(1),
            WireErrorV0(
                "INTERNAL_FAILURE",
                "offline fixture request failed unexpectedly",
                False,
                {},
            ),
        ),
    ],
)
def test_available_non_success_statuses_round_trip(status, coverage, error) -> None:
    response = WireResponseV0(
        request_id="request_1",
        tool="project.read",
        status=status,
        coverage=coverage,
        result=None,
        error=error,
        read_receipt=None,
    )
    assert decode_response(encode_response(response)).status == status


@pytest.mark.parametrize(
    ("tool", "code"),
    [
        ("capabilities.get", "PROJECT_STATE_CONFLICT"),
        ("capabilities.get", "PATCH_ID_CONTRADICTION"),
        ("project.read", "PATCH_ID_CONTRADICTION"),
        ("model.query", "PATCH_ID_CONTRADICTION"),
    ],
)
def test_conflict_rejects_impossible_tool_code_combinations(
    tool,
    code,
) -> None:
    response = WireResponseV0(
        request_id="request_1",
        tool=tool,
        status="CONFLICT",
        coverage=WireCoverageV0.not_evaluated(1),
        result=None,
        error=WireErrorV0(code, "conflict", False, {}),
        read_receipt=None,
    )

    with pytest.raises(WireEncodeError):
        encode_response(response)


@pytest.mark.parametrize(
    ("tool", "code"),
    [
        ("project.read", "PROJECT_STATE_CONFLICT"),
        ("model.query", "PROJECT_STATE_CONFLICT"),
        ("source.patch", "PROJECT_STATE_CONFLICT"),
        ("source.patch", "PATCH_ID_CONTRADICTION"),
    ],
)
def test_conflict_accepts_only_declared_tool_code_combinations(
    tool,
    code,
) -> None:
    response = WireResponseV0(
        request_id="request_1",
        tool=tool,
        status="CONFLICT",
        coverage=WireCoverageV0.not_evaluated(1),
        result=None,
        error=WireErrorV0(code, "conflict", False, {}),
        read_receipt=None,
    )

    admitted = decode_response(encode_response(response))
    assert admitted.tool == tool
    assert admitted.error.code == code


def test_all_unavailable_tools_have_exact_sealed_refusal() -> None:
    unavailable = tuple(
        tool for tool in DECLARED_TOOL_NAMES if tool not in AVAILABLE_TOOL_NAMES)
    for tool in unavailable:
        reason = (
            PUBLISH_NOT_AVAILABLE_BEFORE_SRV1
            if tool == "publish.prepare"
            else NOT_AVAILABLE_IN_PROJECT_V0
        )
        response = WireResponseV0(
            request_id="request_1",
            tool=tool,
            status="REFUSED",
            coverage=WireCoverageV0.refused(1),
            result=None,
            error=WireErrorV0(
                reason,
                "declared tool is unavailable in the offline project V0 fixture",
                False,
                {"tool": tool},
            ),
            read_receipt=None,
        )
        decoded = decode_response(encode_response(response))
        assert decoded.error is not response.error
        assert decoded.error.code == reason

        data = json.loads(canonical_bytes(response.to_data()))
        data["error"]["message"] += " changed"
        with pytest.raises(WireDecodeError, match="not exact"):
            decode_response(canonical_bytes(data))


def test_failed_response_cannot_leak_a_changed_message_or_details() -> None:
    response = WireResponseV0(
        request_id="request_1",
        tool="model.query",
        status="FAILED",
        coverage=WireCoverageV0.not_evaluated(1),
        result=None,
        error=WireErrorV0(
            "INTERNAL_FAILURE",
            "traceback: secret local path",
            False,
            {"exception": "RuntimeError"},
        ),
        read_receipt=None,
    )
    with pytest.raises(WireEncodeError):
        encode_response(response)
