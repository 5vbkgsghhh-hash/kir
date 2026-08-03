"""Backend selection + process singleton for the transport state store.

Config (read via env, consistent with the other KUKAI_AGENT_* flags; promote to
`Settings`/`FeatureFlags` later per the flag-governance rule):
  - `KUKAI_STATE_BACKEND` = `inprocess` (default) | `redis`
  - `KUKAI_REDIS_URL`     = `redis://127.0.0.1:6379/0` (only for the redis backend)

Lifecycle:
  - `await init_state_store()` once at startup (main.py lifespan) — connects redis.
  - `get_state_store()` anywhere (chat_ws.py) — returns the singleton.
  - `await get_state_store().close()` at shutdown.

The in-process backend works with NO init call (lazy), so existing single-worker
deploys keep working untouched. The redis backend REQUIRES init (async connect); if
config asks for redis but init was skipped, `get_state_store` falls back to in-process
and logs a loud warning rather than silently mis-routing.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from kukai.transport.local_store import InProcessStateStore
from kukai.transport.state import StateStore

logger = logging.getLogger(__name__)

_store: Optional[StateStore] = None


def _configured_backend() -> str:
    return os.getenv("KUKAI_STATE_BACKEND", "inprocess").strip().lower()


def _redis_url() -> str:
    return os.getenv("KUKAI_REDIS_URL", "redis://127.0.0.1:6379/0")


def make_state_store(backend: Optional[str] = None, url: Optional[str] = None) -> StateStore:
    """Construct (but do not connect) the configured backend."""
    backend = (backend or _configured_backend()).strip().lower()
    if backend in ("redis", "redis_store"):
        from kukai.transport.redis_store import RedisStateStore  # lazy: imports redis only here

        return RedisStateStore(url=url or _redis_url())
    return InProcessStateStore()


async def init_state_store(backend: Optional[str] = None, url: Optional[str] = None) -> StateStore:
    """Create + connect the store and install it as the process singleton."""
    global _store
    store = make_state_store(backend, url)
    connect = getattr(store, "connect", None)
    if connect is not None:
        await connect()
    _store = store
    logger.info("transport state store initialised: backend=%s", store.kind)
    return _store


def get_state_store() -> StateStore:
    """Return the process singleton, lazily defaulting to in-process."""
    global _store
    if _store is None:
        if _configured_backend() in ("redis", "redis_store"):
            logger.warning(
                "KUKAI_STATE_BACKEND=redis but init_state_store() was not called — "
                "falling back to in-process (NOT multi-worker-safe). Wire init_state_store() "
                "into main.py lifespan before running --workers N."
            )
        _store = InProcessStateStore()
    return _store


def reset_state_store() -> None:
    """Drop the singleton (test helper)."""
    global _store
    _store = None
