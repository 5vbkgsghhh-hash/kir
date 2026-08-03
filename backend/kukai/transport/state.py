"""`StateStore` — the abstract seam for shared transport state.

Two backends implement this contract identically (verified by one shared contract
test suite): `InProcessStateStore` and `RedisStateStore`. chat_ws.py talks only to
this interface, so going multi-worker is a config flip, never a rewrite.

Design notes
------------
- All methods are async (the Redis backend is async; the in-process backend is
  trivially async). chat_ws.py handlers are already async.
- Keys are opaque strings chosen by the caller (e.g. ws_id, device_id, an IP).
- TTLs guard against crashed workers leaving stale ownership/keys behind: the
  owning worker refreshes its entries on a heartbeat; if it dies, entries expire.
  The in-process backend honours TTL too (single process, but kept faithful so the
  contract test covers both).
- Counters are global (cross-worker under Redis): `incr` returns the new value so a
  cap check is atomic ("did I just cross the limit?").
- Pub/sub delivers a JSON-serialisable dict to whichever worker `subscribe`d the
  channel. Under Redis this crosses processes; in-process it is a local broker.
"""
from __future__ import annotations

import abc
from typing import Awaitable, Callable, Optional

# A subscriber handler: receives the published payload, returns when handled.
Handler = Callable[[dict], Awaitable[None]]


class StateStore(abc.ABC):
    """Backend-agnostic shared transport state. See module docstring."""

    #: human-readable backend name, surfaced on /health (IRON 10 observability)
    kind: str = "abstract"

    # ---- session keys (AES) — serializable; admin needs them cross-worker ----
    @abc.abstractmethod
    async def set_session_key(self, ws_id: str, key: bytes, ttl_s: Optional[int] = None) -> None:
        ...

    @abc.abstractmethod
    async def get_session_key(self, ws_id: str) -> Optional[bytes]:
        ...

    @abc.abstractmethod
    async def del_session_key(self, ws_id: str) -> None:
        ...

    # ---- ownership directory (routing): which worker owns a device/session ----
    @abc.abstractmethod
    async def set_owner(self, key: str, worker_id: str, ttl_s: Optional[int] = None) -> None:
        ...

    @abc.abstractmethod
    async def get_owner(self, key: str) -> Optional[str]:
        ...

    @abc.abstractmethod
    async def del_owner(self, key: str) -> None:
        ...

    # ---- global counters (caps): atomic incr returns the new value ----
    @abc.abstractmethod
    async def incr(self, counter: str, amount: int = 1) -> int:
        ...

    async def decr(self, counter: str, amount: int = 1) -> int:
        """Decrement (convenience). Never returns below 0 is NOT guaranteed — the
        caller owns the lifecycle; we clamp reads, not writes, to keep incr atomic."""
        return await self.incr(counter, -amount)

    @abc.abstractmethod
    async def get_counter(self, counter: str) -> int:
        ...

    # ---- cross-worker pub/sub: reach the worker that owns a connection ----
    @abc.abstractmethod
    async def publish(self, channel: str, payload: dict) -> int:
        """Publish `payload` to `channel`. Returns the number of receivers reached
        (0 if nobody is subscribed — the caller can treat that as 'owner is gone')."""
        ...

    @abc.abstractmethod
    async def subscribe(self, channel: str, handler: Handler) -> None:
        """Start delivering messages on `channel` to `handler` in the background.
        Idempotent per (channel) — a second subscribe replaces the handler. Runs
        until `unsubscribe`/`close`."""
        ...

    @abc.abstractmethod
    async def unsubscribe(self, channel: str) -> None:
        ...

    # ---- lifecycle / observability ----
    @abc.abstractmethod
    async def health(self) -> dict:
        """`{kind, ok, detail}` for the /health surface. Never raises."""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        ...
