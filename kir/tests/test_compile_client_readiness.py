"""Fail-closed readiness contract for the real six-version compile gate."""

from __future__ import annotations

import httpx
import pytest

from kir import compile_client
from kir.compile_client import CompileClient


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


def test_one_unreadable_entry_rejects_the_whole_narrowing(monkeypatch, caplog) -> None:
    """🔴 F-369: A TYPO MUST NOT SILENTLY NARROW THE REQUIRED SET.

    The neighboring test `test_resolve_required_versions_is_fail_closed`
    checked only a string that was ENTIRELY invalid (`""`, `"foo,99"`,
    `","`, `"20255"`) — and it was green, because the mixed case was not in
    its list. Yet before 30.08.2026 the mixed case was exactly the hole:
    `"2025,2O26"` (a Latin O instead of a zero) produced `{2025}`, meaning
    the compilation gate demanded ONE version where the operator had
    written two, and stayed silent about it. The resolver's docstring and
    the originating commit `e9316b21` promised fail-closed; the body did
    fail-open.

    THREE assertions are checked, and they are different:
      1. an unparsed entry drops the ENTIRE narrowing to the full matrix;
      2. an EMPTY entry (a trailing comma) does NOT drop the narrowing —
         this matches C#'s `StringSplitOptions.RemoveEmptyEntries`, and a
         fix along the lines of "any non-version drops the parse" would
         break a legitimate setting;
      3. the unparsed entry SPEAKS: the journal carries a warning NAMING
         the entry itself. A silent fallback to the full matrix would be
         correct in count and mute — and a state indistinguishable from
         "the operator meant it that way" is exactly the defect this fix
         was made for.
    """
    resolve = compile_client._resolve_required_revit_versions
    full = frozenset(_ALL)

    # 1. An unparsed entry next to a parsed one -> the FULL matrix, not the
    # remainder.
    for raw, unreadable in (("2025,2O26", "2O26"),   # a Latin O instead of a zero
                            ("2025,202", "202"),     # three-digit
                            ("2026,мусор", "мусор"),  # not a number at all
                            ("2025, ,20255", "20255")):
        caplog.clear()
        with caplog.at_level("WARNING", logger=compile_client.__name__):
            monkeypatch.setenv("KUKAI_COMPILE_REQUIRED_VERSIONS", raw)
            assert resolve() == full, (
                f"{raw!r}: непонятая позиция {unreadable!r} молча сузила "
                f"обязательный набор — это и есть fail-open")
        assert any(unreadable in rec.getMessage() for rec in caplog.records), (
            f"{raw!r}: набор сужен верно, но {unreadable!r} нигде не назван — "
            f"непонятое обязано звучать")

    # 2. An empty entry is NOT garbage: it matches C#'s RemoveEmptyEntries.
    for raw in ("2025,2026,", "2025,,2026", " 2025 , 2026 ,"):
        caplog.clear()
        with caplog.at_level("WARNING", logger=compile_client.__name__):
            monkeypatch.setenv("KUKAI_COMPILE_REQUIRED_VERSIONS", raw)
            assert resolve() == frozenset({"2025", "2026"}), (
                f"{raw!r}: висячая/пустая запятая уронила ЗАКОННОЕ сужение")
        assert not caplog.records, (
            f"{raw!r}: законная настройка не должна ничего кричать")
