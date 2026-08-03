"""Bridge serialization (KUKAI_BRIDGE_SERIALIZE) — one ExternalEvent op at a time.

Revit's single-threaded ExternalEvent can't run overlapping requests; concurrent turns
(rapid user messages) were colliding with "Failed to raise ExternalEvent: Pending". A
per-ws_id lock serializes bridge round-trips so they queue instead of storming.
"""
from __future__ import annotations

import asyncio

import pytest

import kukai.api.chat_ws as cw


def test_lock_is_stable_per_ws_id():
    cw._bridge_serialize_locks.pop("wsA", None)
    cw._bridge_serialize_locks.pop("wsB", None)
    a1 = cw._get_bridge_serialize_lock("wsA")
    a2 = cw._get_bridge_serialize_lock("wsA")
    b = cw._get_bridge_serialize_lock("wsB")
    assert a1 is a2, "same ws_id must reuse the same lock"
    assert a1 is not b, "different ws_id must get distinct locks"


def test_serialize_enabled_default_on(monkeypatch):
    monkeypatch.delenv("KUKAI_BRIDGE_SERIALIZE", raising=False)
    assert cw._bridge_serialize_enabled() is True     # default ON (fix is live on deploy)
    monkeypatch.setenv("KUKAI_BRIDGE_SERIALIZE", "0")
    assert cw._bridge_serialize_enabled() is False     # reversible


@pytest.mark.asyncio
async def test_lock_serializes_overlapping_ops():
    cw._bridge_serialize_locks.pop("wsX", None)
    order: list[str] = []

    async def op(tag: str) -> None:
        async with cw._get_bridge_serialize_lock("wsX"):
            order.append(f"{tag}-start")
            await asyncio.sleep(0.02)   # hold the "ExternalEvent" a beat
            order.append(f"{tag}-end")

    await asyncio.gather(op("A"), op("B"))
    # each op runs to completion before the other starts — no interleave
    assert order in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    ), order
    cw._bridge_serialize_locks.pop("wsX", None)


@pytest.mark.asyncio
async def test_different_ws_ids_run_concurrently():
    for k in ("wsC", "wsD"):
        cw._bridge_serialize_locks.pop(k, None)
    active = 0
    max_active = 0

    async def op(ws_id: str) -> None:
        nonlocal active, max_active
        async with cw._get_bridge_serialize_lock(ws_id):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(op("wsC"), op("wsD"))
    assert max_active == 2, "distinct connections must NOT serialize against each other"
    for k in ("wsC", "wsD"):
        cw._bridge_serialize_locks.pop(k, None)
