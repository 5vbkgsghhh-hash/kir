"""`RedisStateStore` — the multi-worker backend.

Redis strings (with native EX TTL) for session keys + ownership, INCRBY for global
counters, and Redis pub/sub for cross-worker delivery. The `redis` client is imported
lazily inside `connect()` so importing this module (and `kukai.transport`) never
requires `redis` to be installed — only *using* the redis backend does.

All keys are namespaced under `{prefix}:` (default `kukai`). Payloads on the wire are
JSON. Bytes session keys are stored/returned verbatim (Redis is binary-safe).
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from kukai.transport.state import Handler, StateStore


class RedisStateStore(StateStore):
    kind = "redis"

    def __init__(self, url: str = "redis://127.0.0.1:6379/0", prefix: str = "kukai", client=None) -> None:
        self._url = url
        self._prefix = prefix
        self._client = client  # injectable (e.g. fakeredis in tests); else built in connect()
        # channel -> (pubsub, reader_task)
        self._subs: dict[str, tuple[object, asyncio.Task]] = {}

    # ---- namespacing ----
    def _skey(self, ws_id: str) -> str:
        return f"{self._prefix}:skey:{ws_id}"

    def _owner(self, key: str) -> str:
        return f"{self._prefix}:owner:{key}"

    def _ctr(self, counter: str) -> str:
        return f"{self._prefix}:ctr:{counter}"

    def _ch(self, channel: str) -> str:
        return f"{self._prefix}:ch:{channel}"

    # ---- connection ----
    async def connect(self) -> "RedisStateStore":
        """Lazily create the client. Call once at startup. Returns self."""
        if self._client is None:
            import redis.asyncio as aioredis  # lazy: only needed for the redis backend

            self._client = aioredis.from_url(self._url, decode_responses=False)
        await self._client.ping()  # fail fast if the server/client is unreachable
        return self

    # ---- session keys ----
    async def set_session_key(self, ws_id: str, key: bytes, ttl_s: Optional[int] = None) -> None:
        await self._client.set(self._skey(ws_id), bytes(key), ex=ttl_s)

    async def get_session_key(self, ws_id: str) -> Optional[bytes]:
        return await self._client.get(self._skey(ws_id))

    async def del_session_key(self, ws_id: str) -> None:
        await self._client.delete(self._skey(ws_id))

    # ---- ownership ----
    async def set_owner(self, key: str, worker_id: str, ttl_s: Optional[int] = None) -> None:
        await self._client.set(self._owner(key), worker_id.encode(), ex=ttl_s)

    async def get_owner(self, key: str) -> Optional[str]:
        v = await self._client.get(self._owner(key))
        return v.decode() if v is not None else None

    async def del_owner(self, key: str) -> None:
        await self._client.delete(self._owner(key))

    # ---- counters ----
    async def incr(self, counter: str, amount: int = 1) -> int:
        return int(await self._client.incrby(self._ctr(counter), amount))

    async def get_counter(self, counter: str) -> int:
        v = await self._client.get(self._ctr(counter))
        return max(0, int(v)) if v is not None else 0

    # ---- pub/sub ----
    async def publish(self, channel: str, payload: dict) -> int:
        return int(await self._client.publish(self._ch(channel), json.dumps(payload)))

    async def subscribe(self, channel: str, handler: Handler) -> None:
        await self.unsubscribe(channel)  # idempotent
        pubsub = self._client.pubsub()
        full = self._ch(channel)
        await pubsub.subscribe(full)

        async def _reader() -> None:
            try:
                async for msg in pubsub.listen():
                    if not msg or msg.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(msg["data"])
                    except Exception:
                        continue
                    try:
                        await handler(payload)
                    except Exception:  # a bad handler must not kill the subscription
                        pass
            except asyncio.CancelledError:
                pass
            finally:
                try:
                    await pubsub.unsubscribe(full)
                    await pubsub.aclose()
                except Exception:
                    pass

        task = asyncio.ensure_future(_reader())
        self._subs[channel] = (pubsub, task)

    async def unsubscribe(self, channel: str) -> None:
        sub = self._subs.pop(channel, None)
        if sub:
            _pubsub, task = sub
            task.cancel()

    # ---- lifecycle ----
    async def health(self) -> dict:
        try:
            ok = bool(await self._client.ping()) if self._client else False
            return {"kind": self.kind, "ok": ok, "detail": {"url": self._url, "subscriptions": len(self._subs)}}
        except Exception as exc:  # never raises
            return {"kind": self.kind, "ok": False, "detail": {"error": str(exc)[:200]}}

    async def close(self) -> None:
        for channel in list(self._subs):
            await self.unsubscribe(channel)
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
