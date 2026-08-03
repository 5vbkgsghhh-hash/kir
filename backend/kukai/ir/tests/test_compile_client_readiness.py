"""Fail-closed readiness contract for the real six-version compile gate."""

from __future__ import annotations

import httpx
import pytest

from kukai import compile_client
from kukai.compile_client import CompileClient


_ALL = ["2021", "2022", "2023", "2024", "2025", "2026"]


def _client(response: httpx.Response) -> CompileClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        return response

    client = CompileClient(base_url="http://compile.invalid")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
async def test_health_accepts_only_complete_six_version_matrix() -> None:
    client = _client(httpx.Response(200, json={
        "status": "ready",
        "versions": _ALL,
        "requiredVersions": _ALL,
        "missingVersions": [],
    }))
    try:
        assert await client.health() is True
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={
            "status": "degraded",
            "versions": ["2025", "2026"],
            "requiredVersions": _ALL,
            "missingVersions": ["2021", "2022", "2023", "2024"],
        }),
        # Even a buggy/stale service returning 200 cannot claim 6/6 with a
        # partial matrix.
        httpx.Response(200, json={
            "status": "ready",
            "versions": ["2025", "2026"],
            "requiredVersions": _ALL,
            "missingVersions": [],
        }),
        httpx.Response(200, json={
            "status": "ready",
            "versions": _ALL + ["2026"],
            "requiredVersions": _ALL,
            "missingVersions": [],
        }),
    ],
)
async def test_health_refuses_missing_reference_sets(
    response: httpx.Response,
) -> None:
    client = _client(response)
    try:
        assert await client.health() is False
    finally:
        await client.close()


def test_resolve_required_versions_is_fail_closed(monkeypatch) -> None:
    """C# gate and this Python check read the SAME env var; empty/garbage must
    fall back to the full matrix (never an empty 'require nothing' set = never
    fail-open)."""
    resolve = compile_client._resolve_required_revit_versions
    monkeypatch.delenv("KUKAI_COMPILE_REQUIRED_VERSIONS", raising=False)
    assert resolve() == frozenset(_ALL)
    monkeypatch.setenv("KUKAI_COMPILE_REQUIRED_VERSIONS", "2025,2026")
    assert resolve() == frozenset({"2025", "2026"})
    monkeypatch.setenv("KUKAI_COMPILE_REQUIRED_VERSIONS", "2026, 2025 ,2025")
    assert resolve() == frozenset({"2025", "2026"})  # trims + dedups
    for bad in ("", "   ", "foo,99", ",", "20255"):
        monkeypatch.setenv("KUKAI_COMPILE_REQUIRED_VERSIONS", bad)
        assert resolve() == frozenset(_ALL), (
            f"garbage {bad!r} must fall back to the full matrix, not fail-open")


@pytest.mark.asyncio
async def test_health_follows_configured_override(monkeypatch) -> None:
    """With an explicit override, health() accepts the reduced set the service
    reports — and still rejects a service reporting a DIFFERENT set (no drift
    between the C# gate and this check)."""
    monkeypatch.setattr(
        compile_client, "_REQUIRED_REVIT_VERSIONS", frozenset({"2025", "2026"}))
    accepted = _client(httpx.Response(200, json={
        "status": "ready",
        "versions": ["2025", "2026"],
        "requiredVersions": ["2025", "2026"],
        "missingVersions": [],
    }))
    try:
        assert await accepted.health() is True
    finally:
        await accepted.close()
    # Drift guard: override says {2025,2026} but service reports the full 6 -> reject.
    mismatched = _client(httpx.Response(200, json={
        "status": "ready",
        "versions": _ALL,
        "requiredVersions": _ALL,
        "missingVersions": [],
    }))
    try:
        assert await mismatched.health() is False
    finally:
        await mismatched.close()
