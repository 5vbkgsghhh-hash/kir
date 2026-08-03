"""WebSocketBridgeClient — Python wrapper for KUKAI Revit Bridge access.

For MVP1 / spike phase: uses the spike HTTP loopback endpoints
(/api/spike/sessions, /api/spike/execute) added by the spike-builder.
These endpoints route through chat_ws's existing _bridge_callback pipeline,
so we're not bypassing the bridge architecture — we're using the same
single-thread execution path with a simpler programmatic surface.

Future Plan: replace with raw WebSocket client when bridge protocol
exposes a public message contract beyond the spike endpoints.

Concurrency (Wave 6C — Fix A+B#3): every `execute_code` call is serialized
through an instance-level `asyncio.Lock` so concurrent dispatchers / repair
loops / sampling do not interleave WebSocket frames into the
single-threaded Revit API. Two concurrent execute_code coroutines on the
same client queue in submission order rather than racing. Read-only
operations like `list_sessions` stay lock-free — they don't touch the
Revit transaction model.
"""
from __future__ import annotations
import asyncio
import time
from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING
import httpx

if TYPE_CHECKING:
    from kukai.modeling.schemas.tasks import TaskBrief


@runtime_checkable
class BridgeBriefForwarder(Protocol):
    """Optional capability for bridge clients that need to know which task
    is currently dispatching.

    The only known implementer is `MockBridgeClient` — when it wraps a
    `MockRevitSession`, the session's passive recorder needs the TaskBrief
    + plan_task_id to synthesize placements (no real Revit to inspect).

    The real `WebSocketBridgeClient` does NOT implement this protocol:
    real Revit knows what was just executed by inspecting its own document
    state, so there is nothing to forward. Callers (e.g. ExecutionQueue)
    detect implementers via `isinstance(client, BridgeBriefForwarder)` and
    no-op otherwise.

    Wave 6C — Fix A#3: replaces the legacy duck-typed
    `getattr(getattr(self._execute, "_client", None), "_revit_session",
    None)` chain in execution/queue.py — a back-channel that reached
    through gate privates and broke encapsulation. The Protocol exposes
    the same capability with a typed surface.
    """

    def forward_brief(
        self,
        task_brief: "TaskBrief | None",
        plan_task_id: str | None = None,
    ) -> None: ...

    def clear_brief(self) -> None: ...


class WebSocketBridgeClient:
    """HTTP-over-loopback wrapper around the bridge execution pipeline.

    Despite the class name, communication uses the spike HTTP endpoints
    (which internally drive the WebSocket bridge). This is a stable surface
    for testing without requiring a live WebSocket connection.

    Wave 6C (Fix A+B#3): execute_code is serialized by an internal
    asyncio.Lock. This honors Revit's single-threaded API contract — even
    if multiple dispatchers / repair-loop attempts / sampling siblings call
    concurrently on the same client, only one execute_code body runs at a
    time. The ExecutionQueue's own lock guards queue-level ordering;
    this client-level lock guards transport-level ordering when multiple
    queues or out-of-band callers share one client instance.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:52411",
        timeout_seconds: float = 600.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        # Wave 6B (Fix B#4): expose .calls so ForemanBudgetGuard._count can
        # observe per-phase invocations and trip the execute cap in production.
        # Mirrors MockBridgeClient.calls contract — append on entry to each
        # external-work method, before any await.
        self.calls: list[dict[str, Any]] = []
        # Wave 6C (Fix A+B#3): per-client execute_code serializer. Defer
        # construction to first await — asyncio.Lock() requires a running
        # event loop on some Python versions, but the canonical pattern is
        # to construct lazily inside the first coroutine.
        self._exec_lock: asyncio.Lock | None = None

    def _get_exec_lock(self) -> asyncio.Lock:
        """Lazily instantiate the execute_code serializer the first time
        it's needed. Subsequent calls return the same lock instance."""
        if self._exec_lock is None:
            self._exec_lock = asyncio.Lock()
        return self._exec_lock

    def _client(self) -> httpx.AsyncClient:
        kwargs = {"base_url": self._base_url, "timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def list_sessions(self) -> list[str]:
        """Return active bridge session IDs."""
        # Wave 6B (Fix B#4): record on entry; session-listing storms count
        # toward the execute cap.
        self.calls.append({
            "method": "list_sessions",
            "args_summary": "",
            "ts": time.monotonic(),
        })
        async with self._client() as c:
            resp = await c.get("/api/spike/sessions")
            resp.raise_for_status()
        return list(resp.json().get("sessions", []))

    async def execute_code(
        self,
        session_id: str,
        csharp_code: str,
        expected_count: int = 1,
    ) -> dict[str, Any]:
        """Submit C# to the bridge for compile-and-execute.

        Returns a dict with keys: success (bool), element_ids (list[int]),
        error (str | None), duration_ms (int).

        Wave 6C (Fix A+B#3): the entire request/response is wrapped in
        `self._get_exec_lock()` so concurrent execute_code calls on the
        same client serialize. Revit's API is single-threaded and the
        spike endpoint already serializes server-side, but client-side
        serialization is the cheap defense against accidentally interleaved
        retries / concurrent dispatchers.
        """
        async with self._get_exec_lock():
            # Wave 6B (Fix B#4): record BEFORE network I/O so BudgetGuard
            # counts the attempt even if the bridge later raises mid-flight.
            # Inside the lock so .calls ordering matches actual execution
            # order under contention.
            self.calls.append({
                "method": "execute_code",
                "args_summary": (
                    f"session={session_id} expected={expected_count} "
                    f"code_len={len(csharp_code)}"
                ),
                "ts": time.monotonic(),
            })
            async with self._client() as c:
                resp = await c.post(
                    "/api/spike/execute",
                    json={
                        "session_id": session_id,
                        "code": csharp_code,
                        "expected_count": expected_count,
                    },
                )
                resp.raise_for_status()
            return resp.json()
