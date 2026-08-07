"""Strict client contract for emitted-artifact compile receipts."""
from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from kukai.compile_client import ArtifactCompileResult, CompileClient
from kukai.ir.compile_receipt import CompileReceipt
from kukai.ir.compiler import compile_program
from kukai.ir.emitted_artifact import EmittedArtifact
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


PROGRAM = {
    "ir_version": "1.0",
    "intent": "strict compile client receipt",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "name", "value": "Этаж 1"},
    }],
}


def _compile_artifact(
    *,
    revit_version: str = "2026",
    wall_length: int = 6000,
) -> EmittedArtifact:
    program = copy.deepcopy(PROGRAM)
    program["ops"][0]["p1_mm"] = [wall_length, 0]
    output = compile_program(
        program,
        revit_version=revit_version,
        snapshot=GROUND_SNAPSHOT,
    )
    assert output.ok, [item.as_dict() for item in output.diagnostics]
    assert output.emitted is not None
    return output.emitted


@pytest.fixture(scope="module")
def artifact() -> EmittedArtifact:
    return _compile_artifact()


def _success_payload(receipt: CompileReceipt) -> dict[str, Any]:
    return {
        "schema": "kir-compile-response/1",
        "success": True,
        "errors": [],
        "receipt": receipt.to_dict(),
    }


def _failure_payload() -> dict[str, Any]:
    return {
        "schema": "kir-compile-response/1",
        "success": False,
        "errors": [{
            "code": "CS0246",
            "message": "The type 'Missing' could not be found",
            "line": 17,
            "column": 9,
        }],
        "receipt": None,
    }


def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> CompileClient:
    client = CompileClient(base_url="http://compile.invalid")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
async def test_success_posts_exact_request_and_returns_bound_receipt(
    artifact: EmittedArtifact,
) -> None:
    expected = CompileReceipt.expected_for(artifact)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/compile-receipt/v1"
        assert json.loads(request.content) == {
            "schema": "kir-compile-request/1",
            "source": artifact.source,
            "artifact": expected.artifact.to_dict(),
            "compile_unit": expected.compile_unit.to_dict(),
            "target": expected.target.to_dict(),
        }
        return httpx.Response(200, json=_success_payload(expected))

    client = _mock_client(handler)
    try:
        result = await client.check_artifact(artifact)

        assert isinstance(result, ArtifactCompileResult)
        assert result.success is True
        assert result.errors == ()
        assert result.receipt == expected
        assert client.available is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_compile_failure_is_available_typed_failure(
    artifact: EmittedArtifact,
) -> None:
    client = _mock_client(
        lambda _request: httpx.Response(200, json=_failure_payload()))
    try:
        result = await client.check_artifact(artifact)

        assert isinstance(result, ArtifactCompileResult)
        assert result.success is False
        assert result.receipt is None
        assert len(result.errors) == 1
        assert result.errors[0].code == "CS0246"
        assert result.errors[0].line == 17
        assert client.available is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.errors[0].code = "CS0000"  # type: ignore[misc]
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unavailable", "non_200"])
async def test_unavailable_or_non_200_fails_closed(
    artifact: EmittedArtifact,
    mode: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "unavailable":
            raise httpx.ConnectError("compile service is down", request=request)
        return httpx.Response(503, json={"status": "not-ready"})

    client = _mock_client(handler)
    client._available = True
    try:
        assert await client.check_artifact(artifact) is None
        assert client.available is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_string_false_is_not_coerced_to_success_state(
    artifact: EmittedArtifact,
) -> None:
    payload = _failure_payload()
    payload["success"] = "false"
    client = _mock_client(
        lambda _request: httpx.Response(200, json=payload))
    try:
        assert await client.check_artifact(artifact) is None
        assert client.available is False
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"extra": True}),
        lambda payload: payload.pop("receipt"),
        lambda payload: payload["errors"][0].update({"extra": "field"}),
        lambda payload: payload["errors"][0].pop("column"),
        lambda payload: payload["errors"][0].update({"line": True}),
        lambda payload: payload["errors"].clear(),
    ],
    ids=[
        "response-extra",
        "response-missing",
        "error-extra",
        "error-missing",
        "bool-is-not-integer",
        "failure-needs-diagnostic",
    ],
)
async def test_extra_missing_or_wrongly_typed_fields_fail_closed(
    artifact: EmittedArtifact,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    payload = _failure_payload()
    mutate(payload)
    client = _mock_client(
        lambda _request: httpx.Response(200, json=payload))
    try:
        assert await client.check_artifact(artifact) is None
        assert client.available is False
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forgery",
    ["receipt_digest", "other_body", "other_profile", "source_hash"],
)
async def test_forged_receipt_body_profile_or_hash_fails_closed(
    artifact: EmittedArtifact,
    forgery: str,
) -> None:
    expected = CompileReceipt.expected_for(artifact)
    if forgery == "other_body":
        forged = CompileReceipt.expected_for(_compile_artifact(
            wall_length=7000))
        receipt_payload = forged.to_dict()
    elif forgery == "other_profile":
        forged = CompileReceipt.expected_for(_compile_artifact(
            revit_version="2025"))
        receipt_payload = forged.to_dict()
    else:
        receipt_payload = copy.deepcopy(expected.to_dict())
        if forgery == "receipt_digest":
            receipt_payload["receipt_digest"] = "0" * 64
        else:
            receipt_payload["compile_unit"]["source_sha256"] = "0" * 64

    payload = _success_payload(expected)
    payload["receipt"] = receipt_payload
    client = _mock_client(
        lambda _request: httpx.Response(200, json=payload))
    try:
        assert await client.check_artifact(artifact) is None
        assert client.available is False
    finally:
        await client.close()
