from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kukai.ai_protocol.contracts import (
    CAPABILITIES_TOOL,
    COVERAGE_SCHEMA,
    MAX_WIRE_BYTES,
    CoverageV0,
    ProtocolContractV0,
    ProtocolErrorV0,
    ReadReceiptV0,
    ToolRequestV0,
    ToolResponseV0,
)
from kukai.ai_protocol.errors import ProtocolContractError
from kukai.ai_protocol.registry import CAPABILITY_REGISTRY
from kukai.design_source.canonical import canonical_bytes


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _error() -> ProtocolErrorV0:
    return ProtocolErrorV0("BROKEN", "The operation failed.")


def _receipt(
    *,
    request_id: str = "request_1",
    tool: str = CAPABILITIES_TOOL,
    coverage: CoverageV0 | None = None,
) -> ReadReceiptV0:
    return ReadReceiptV0(
        request_id=request_id,
        tool=tool,
        project_id="project_1",
        revision_digest=DIGEST_A,
        request_digest=DIGEST_B,
        result_digests=(DIGEST_A,),
        coverage=CoverageV0.complete() if coverage is None else coverage,
        schema_registry_digest=CAPABILITY_REGISTRY.registry_digest,
    )


def test_request_identifier_accepts_64_and_refuses_65_characters() -> None:
    admitted = "A" + "a" * 63
    refused = admitted + "a"

    assert ToolRequestV0(admitted, CAPABILITIES_TOOL, {}).request_id == admitted
    with pytest.raises(ProtocolContractError):
        ToolRequestV0(refused, CAPABILITIES_TOOL, {})


@pytest.mark.parametrize("value", [True, False, -1, 1_000_000_001])
def test_coverage_refuses_non_exact_or_out_of_range_counts(value: object) -> None:
    with pytest.raises(ProtocolContractError):
        CoverageV0("UNKNOWN", value, 0)  # type: ignore[arg-type]


def test_coverage_enforces_accounting_and_deep_immutability() -> None:
    omitted = ["z", "a"]
    coverage = CoverageV0("PARTIAL", 3, 1, omitted=omitted)
    omitted.append("later")

    assert coverage.omitted == ("a", "z")
    with pytest.raises(FrozenInstanceError):
        coverage.state = "UNKNOWN"  # type: ignore[misc]
    with pytest.raises(ProtocolContractError):
        CoverageV0("UNKNOWN", 1, 2)
    with pytest.raises(ProtocolContractError):
        CoverageV0("COMPLETE", 2, 1)
    with pytest.raises(ProtocolContractError):
        CoverageV0("COMPLETE", 1, 1, failed=("gap",))
    with pytest.raises(ProtocolContractError):
        CoverageV0("NOT_EVALUATED", 1, 1)
    with pytest.raises(ProtocolContractError):
        CoverageV0("REFUSED", 1, 1)
    with pytest.raises(ProtocolContractError):
        CoverageV0("PARTIAL", 1, 0, omitted=("same", "same"))


def test_coverage_has_exact_canonical_byte_boundary() -> None:
    limit = 1_000_000
    items = [f"{index:04d}" + "x" * 4_092 for index in range(243)]

    def data(values: list[str]) -> dict:
        return {
            "schema": COVERAGE_SCHEMA,
            "state": "PARTIAL",
            "requested": {"items": 1},
            "evaluated": {"items": 0},
            "omitted": tuple(values),
            "failed": (),
        }

    probe = [*items, "9999"]
    remaining = limit - len(canonical_bytes(data(probe)))
    exact = [*items, "9999" + "x" * remaining]
    assert len(canonical_bytes(data(exact))) == limit
    admitted = CoverageV0("PARTIAL", 1, 0, omitted=exact)
    assert len(canonical_bytes(admitted.to_data())) == limit

    over = [*items, "9999" + "x" * (remaining + 1)]
    with pytest.raises(ProtocolContractError, match="canonical byte limit"):
        CoverageV0("PARTIAL", 1, 0, omitted=over)


def test_wire_budget_matches_strict_json_input_budget() -> None:
    assert MAX_WIRE_BYTES == 4_000_000


def test_protocol_error_copies_details_and_enforces_exact_scalars() -> None:
    details = {"nested": {"value": 1}}
    error = ProtocolErrorV0("TOOL_UNAVAILABLE", "Unavailable.", details=details)
    details["nested"]["value"] = 2

    assert error.details["nested"]["value"] == 1
    with pytest.raises(TypeError):
        error.details["new"] = 1  # type: ignore[index]
    with pytest.raises(ProtocolContractError):
        ProtocolErrorV0("lowercase", "bad")
    with pytest.raises(ProtocolContractError):
        ProtocolErrorV0("A" * 129, "bad")
    with pytest.raises(ProtocolContractError):
        ProtocolErrorV0("BROKEN", "bad", retryable=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "arguments",
    [
        {"authority": "model"},
        {"nested": {"Principal-ID": "model"}},
        {"nested": {"principalId": "model"}},
        {"nested": [{"APPROVAL": True}]},
        {"authentication": {"token": "model"}},
        {"requestAuthorization": "model"},
    ],
)
def test_model_payload_cannot_supply_identity_or_authority(arguments) -> None:
    with pytest.raises(ProtocolContractError, match="model payload cannot set"):
        ToolRequestV0("request_1", CAPABILITIES_TOOL, arguments)


def test_every_ap01_request_requires_exact_empty_arguments() -> None:
    with pytest.raises(ProtocolContractError, match="exact empty object"):
        ToolRequestV0("request_1", CAPABILITIES_TOOL, {"query": "anything"})


def test_response_status_coverage_matrix_has_valid_representatives() -> None:
    ok = ToolResponseV0(
        "request_1",
        CAPABILITIES_TOOL,
        "OK",
        CoverageV0.complete(),
        CAPABILITY_REGISTRY.to_data(),
        None,
    )
    refused = ToolResponseV0(
        "request_2",
        "project.read",
        "REFUSED",
        CoverageV0.refused("NOT_AVAILABLE_IN_AP01"),
        None,
        ProtocolErrorV0("TOOL_UNAVAILABLE", "Unavailable."),
    )
    failed = ToolResponseV0(
        "request_3",
        CAPABILITIES_TOOL,
        "FAILED",
        CoverageV0("NOT_EVALUATED", 1, 0),
        None,
        _error(),
    )

    assert (ok.status, refused.status, failed.status) == (
        "OK", "REFUSED", "FAILED")


@pytest.mark.parametrize("coverage", [CoverageV0.complete(), CoverageV0.refused("x")])
def test_failed_excludes_complete_and_refused_coverage(
    coverage: CoverageV0,
) -> None:
    with pytest.raises(ProtocolContractError, match="FAILED requires"):
        ToolResponseV0(
            "request_1",
            CAPABILITIES_TOOL,
            "FAILED",
            coverage,
            None,
            _error(),
        )


def test_refused_requires_refused_coverage_error_and_null_result() -> None:
    with pytest.raises(ProtocolContractError):
        ToolResponseV0(
            "request_1",
            "project.read",
            "REFUSED",
            CoverageV0("NOT_EVALUATED", 1, 0),
            None,
            _error(),
        )
    with pytest.raises(ProtocolContractError):
        ToolResponseV0(
            "request_1",
            "project.read",
            "REFUSED",
            CoverageV0.refused("reason"),
            {},
            _error(),
        )


def test_capability_ok_requires_exact_complete_single_item_coverage() -> None:
    for coverage in (
        CoverageV0("PARTIAL", 1, 0),
        CoverageV0.complete(2),
    ):
        with pytest.raises(ProtocolContractError, match="COMPLETE 1-of-1"):
            ToolResponseV0(
                "request_1",
                CAPABILITIES_TOOL,
                "OK",
                coverage,
                CAPABILITY_REGISTRY.to_data(),
                None,
            )


def test_unavailable_tool_cannot_return_ok() -> None:
    with pytest.raises(ProtocolContractError, match="unavailable"):
        ToolResponseV0(
            "request_1",
            "project.read",
            "OK",
            CoverageV0.complete(),
            {},
            None,
        )


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (_receipt(request_id="other"), "request_id"),
        (_receipt(tool="project.read"), "tool"),
        (_receipt(coverage=CoverageV0.complete(2)), "coverage"),
    ],
)
def test_read_receipt_is_bound_to_enclosing_response(
    receipt: ReadReceiptV0,
    message: str,
) -> None:
    with pytest.raises(ProtocolContractError, match=message):
        ToolResponseV0(
            "request_1",
            CAPABILITIES_TOOL,
            "OK",
            CoverageV0.complete(),
            CAPABILITY_REGISTRY.to_data(),
            None,
            receipt,
        )


def test_capability_discovery_cannot_programmatically_issue_read_receipt() -> None:
    with pytest.raises(ProtocolContractError, match="cannot carry"):
        ToolResponseV0(
            "request_1",
            CAPABILITIES_TOOL,
            "OK",
            CoverageV0.complete(),
            CAPABILITY_REGISTRY.to_data(),
            None,
            _receipt(),
        )


@pytest.mark.parametrize("mutate_receipt_child", [False, True])
def test_receipt_coverage_binding_refuses_digest_subclass_with_lying_equality(
    mutate_receipt_child: bool,
) -> None:
    class LyingDigest(str):
        def __eq__(self, _other):
            return True

        def __ne__(self, _other):
            return False

    coverage = CoverageV0.complete()
    receipt = _receipt()
    target = receipt.coverage if mutate_receipt_child else coverage
    object.__setattr__(target, "_coverage_digest", LyingDigest(DIGEST_A))

    with pytest.raises(ProtocolContractError, match="exact digest text"):
        ToolResponseV0(
            "request_1",
            CAPABILITIES_TOOL,
            "OK",
            coverage,
            CAPABILITY_REGISTRY.to_data(),
            None,
            receipt,
        )


def test_read_receipt_requires_nonempty_unique_exact_digests() -> None:
    values = dict(
        request_id="request_1",
        tool=CAPABILITIES_TOOL,
        project_id="project_1",
        revision_digest=DIGEST_A,
        request_digest=DIGEST_B,
        coverage=CoverageV0.complete(),
        schema_registry_digest=CAPABILITY_REGISTRY.registry_digest,
    )
    with pytest.raises(ProtocolContractError):
        ReadReceiptV0(result_digests=(), **values)
    with pytest.raises(ProtocolContractError):
        ReadReceiptV0(result_digests=(DIGEST_A, DIGEST_A), **values)
    with pytest.raises(ProtocolContractError):
        ReadReceiptV0(result_digests=("SHA256:" + "A" * 64,), **values)


def test_protocol_contract_marker_is_sealed_to_implementation_modules() -> None:
    with pytest.raises(TypeError, match="sealed"):

        class ExternalProtocolContract(ProtocolContractV0):
            pass
