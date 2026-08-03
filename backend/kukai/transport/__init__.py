"""Transport-state seam (IRON 8 — Immortal Session / topology under the invariant).

Makes KUKAI multi-worker-ready by abstracting the SHARED, serializable transport
state behind one interface (`StateStore`) with two interchangeable backends:

- `InProcessStateStore` (default): plain dicts + an in-process pub/sub broker.
  Behaviour-identical to the historical single-worker `chat_ws.py` module dicts.
- `RedisStateStore`: Redis strings/INCR + Redis pub/sub. Coherent across workers
  and machines — fixes the per-worker sharding (admin "75% wrong worker", 4×
  under-counted caps, split session keys) once you run `--workers N`.

NOT carried here (kept process-local in chat_ws.py, because they are live objects
that cannot be serialized): the WebSocket registry and the pending-bridge Futures.
This store carries only the *directory* (which worker owns a device/session),
serializable session keys, global counters, and the pub/sub used to reach the
owning worker.

Switching is configuration: `KUKAI_STATE_BACKEND=inprocess` (default) | `redis`.
"""
from __future__ import annotations

from kukai.transport.state import StateStore
from kukai.transport.factory import get_state_store, init_state_store, make_state_store

__all__ = ["StateStore", "get_state_store", "init_state_store", "make_state_store"]
