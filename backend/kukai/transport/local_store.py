"""`InProcessStateStore` — the default backend (single worker).

Plain dicts + a local asyncio pub/sub broker. Behaviour-identical to the historical
module-level dicts in chat_ws.py, but behind the `StateStore` seam so the Redis
backend can replace it by config with zero call-site changes. TTLs are honoured
(lazy expiry on read) so the shared contract test exercises both backends equally.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from kukai.transport.state import Handler, StateStore


class InProcessStateStore(StateStore):
    kind = "inprocess"

    def __init__(self) -> None:
        # value -> (payload, expiry_monotonic | None)
        self._keys: dict[str, tuple[bytes, Optional[float]]] = {}
        self._owners: dict[str, tuple[str, Optional[float]]] = {}
        self._counters: dict[str, int] = {}
        # channel -> (queue, drain_task, handler)
        self._subs: dict[str, tuple[asyncio.Queue, asyncio.Task, Handler]] = {}
        self._closed = False

    # ---- internal: lazy TTL ----
    @staticmethod
    def _live(entry, now: float):
        if entry is None:
            return None
        value, exp = entry
        if exp is not None and exp <= now:
            return None
        return value

    @staticmethod
    def _exp(ttl_s: Optional[int]) -> Optional[float]:
        return (time.monotonic() + ttl_s) if ttl_s else None

    # ---- session keys ----
    async def set_session_key(self, ws_id: str, key: bytes, ttl_s: Optional[int] = None) -> None:
        self._keys[ws_id] = (bytes(key), self._exp(ttl_s))

    async def get_session_key(self, ws_id: str) -> Optional[bytes]:
        v = self._live(self._keys.get(ws_id), time.monotonic())
        if v is None:
            self._keys.pop(ws_id, None)
        return v

    async def del_session_key(self, ws_id: str) -> None:
        self._keys.pop(ws_id, None)

    # ---- ownership ----
    async def set_owner(self, key: str, worker_id: str, ttl_s: Optional[int] = None) -> None:
        self._owners[key] = (worker_id, self._exp(ttl_s))

    async def get_owner(self, key: str) -> Optional[str]:
        v = self._live(self._owners.get(key), time.monotonic())
        if v is None:
            self._owners.pop(key, None)
        return v

    async def del_owner(self, key: str) -> None:
        self._owners.pop(key, None)

    # ---- counters ----
    async def incr(self, counter: str, amount: int = 1) -> int:
        self._counters[counter] = self._counters.get(counter, 0) + amount
        return self._counters[counter]

    async def get_counter(self, counter: str) -> int:
        return max(0, self._counters.get(counter, 0))

    # ---- pub/sub (local broker) ----
    async def publish(self, channel: str, payload: dict) -> int:
        sub = self._subs.get(channel)
        if not sub:
            return 0
        queue, _task, _handler = sub
        queue.put_nowait(dict(payload))
        return 1

    async def subscribe(self, channel: str, handler: Handler) -> None:
        await self.unsubscribe(channel)  # idempotent: replace any prior handler
        queue: asyncio.Queue = asyncio.Queue()

        async def _drain() -> None:
            while True:
                payload = await queue.get()
                try:
                    await handler(payload)
                except Exception:  # a bad handler must not kill the subscription
                    pass

        task = asyncio.ensure_future(_drain())
        self._subs[channel] = (queue, task, handler)

    async def unsubscribe(self, channel: str) -> None:
        sub = self._subs.pop(channel, None)
        if sub:
            _queue, task, _handler = sub
            task.cancel()

    # ---- lifecycle ----
    async def health(self) -> dict:
        return {
            "kind": self.kind,
            "ok": not self._closed,
            "detail": {
                "keys": len(self._keys),
                "owners": len(self._owners),
                "counters": len(self._counters),
                "subscriptions": len(self._subs),
            },
        }

    async def close(self) -> None:
        self._closed = True
        for channel in list(self._subs):
            await self.unsubscribe(channel)
        self._keys.clear()
        self._owners.clear()
        self._counters.clear()
