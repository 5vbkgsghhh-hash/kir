"""Scripted mocks for compile and bridge clients.

Used by gate/queue tests to avoid spinning up the real services or Revit.
Each mock supports either a default-success behavior OR a scripted response
list consumed in order.
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

from kukai.modeling.bridge.model_query_client import (
    ElementGeometry, GridInfo, LevelInfo,
)
from kukai.modeling.schemas.execution import CompileError, CompileResult

if TYPE_CHECKING:
    from kukai.modeling.bridge.mock_revit_session import MockRevitSession


class MockCompileClient:
    """Mock for HttpCompileClient. Records all .compile() calls."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self._responses = responses or []
        self._idx = 0
        self.calls: list[str] = []

    async def compile(self, csharp_code: str, revit_version: str = "2026") -> CompileResult:
        self.calls.append(csharp_code)
        if self._idx < len(self._responses):
            data = self._responses[self._idx]
            self._idx += 1
        else:
            data = {"success": True, "assembly_id": f"mock_asm_{len(self.calls)}"}

        # Accept legacy `error` string OR new `errors` list for ergonomic mocks.
        errors_data = data.get("errors")
        if errors_data is None and data.get("error"):
            errors_data = [{"code": "MOCK", "message": data["error"], "line": 0, "column": 0}]
        errors_data = errors_data or []

        return CompileResult(
            success=bool(data.get("success", True)),
            code=csharp_code if data.get("success", True) else None,
            assembly_id=data.get("assembly_id"),
            errors=[CompileError.model_validate(e) for e in errors_data],
        )

    async def health(self) -> bool:
        return True


class MockBridgeClient:
    """Mock for WebSocketBridgeClient.

    Two modes: scripted (legacy, via `responses`) or session-backed (Phase 3,
    via `revit_session`). When a session is supplied, execute_code delegates.
    """

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        revit_session: "MockRevitSession | None" = None,
    ):
        self._responses = responses or []
        self._idx = 0
        self._revit_session = revit_session
        self.calls: list[dict[str, Any]] = []

    # Wave 6C — Fix A#3: BridgeBriefForwarder Protocol implementation.
    # These methods replace the legacy duck-typed back-channel in
    # ExecutionQueue.submit (getattr chain through gate privates).
    # Real WebSocketBridgeClient deliberately does NOT implement this
    # protocol — real Revit knows the current task from its own state.
    def forward_brief(
        self,
        task_brief: Any,
        plan_task_id: str | None = None,
    ) -> None:
        """Forward the brief into the wrapped MockRevitSession's current-
        task register so the passive recorder synthesizes placements
        from resolver-supplied data. No-op when no session wraps this
        mock (legacy scripted-response mode)."""
        if self._revit_session is not None:
            self._revit_session.set_current_task(
                task_brief=task_brief, plan_task_id=plan_task_id,
            )

    def clear_brief(self) -> None:
        """Clear the wrapped MockRevitSession's current-task register
        after dispatch completes. No-op when no session is wrapped."""
        if self._revit_session is not None:
            self._revit_session.clear_current_task()

    async def list_sessions(self) -> list[str]:
        return ["mock_session"]

    async def execute_code(
        self,
        session_id: str,
        csharp_code: str,
        expected_count: int = 1,
        *,
        task_brief: Any = None,
        plan_task_id: str | None = None,
    ) -> dict[str, Any]:
        """Round 1A — `task_brief` + `plan_task_id` are optional pass-through.

        The real WebSocketBridgeClient.execute_code only takes (session_id,
        csharp_code, expected_count); these kwargs are mock-only and let
        the runner forward TaskBrief data into MockRevitSession's
        passive-recorder synthesis without changing the real bridge
        signature. If a runner already calls
        `session.set_current_task(...)` before each dispatch, these
        kwargs are unnecessary — the session's current_task register
        wins-or-defaults via the explicit kwargs path inside execute_code.

        Wave 6C (Fix A#3): ExecutionQueue now drives the current-task
        register via `forward_brief` / `clear_brief` on this client
        (BridgeBriefForwarder Protocol) — these kwargs remain for callers
        that prefer the per-call style.
        """
        self.calls.append({
            "session_id": session_id,
            "code": csharp_code,
            "expected_count": expected_count,
            "task_brief_task_id": getattr(task_brief, "task_id", None),
            "plan_task_id": plan_task_id,
        })
        if self._revit_session is not None:
            return self._revit_session.execute_code(
                csharp_code, expected_count=expected_count,
                task_brief=task_brief, plan_task_id=plan_task_id,
            )
        if self._idx < len(self._responses):
            data = self._responses[self._idx]
            self._idx += 1
            return data
        # Default success: create `expected_count` elements at IDs 9000+
        return {
            "success": True,
            "element_ids": list(range(9000 + len(self.calls) * 100,
                                      9000 + len(self.calls) * 100 + expected_count)),
            "duration_ms": 50,
            "error": None,
        }


class MockModelQueryClient:
    """Static-data mock for ModelQueryClient.

    Used by Resolver tests to avoid spinning up bridge or Revit.

    When `levels` or `grids` is ``None`` (i.e. the caller didn't care),
    sensible defaults are seeded so the mock represents a minimally
    realistic project (1 level + 2 grids). Passing an empty list (``[]``)
    is honored verbatim, for tests that want a deliberately empty model.
    `families` defaults to empty either way — families are intent-specific
    and callers always seed them when they matter.
    """

    _DEFAULT_LEVELS = (
        LevelInfo(level_id=1, name="L1", elevation_mm=0.0),
    )
    _DEFAULT_GRIDS = (
        GridInfo(grid_id=1, name="A", axis="vertical", position_mm=0.0),
        GridInfo(grid_id=2, name="1", axis="horizontal", position_mm=0.0),
    )

    def __init__(
        self,
        families: list | None = None,
        levels: list | None = None,
        grids: list | None = None,
        parameter_info: dict[int, dict[str, tuple[str, str]]] | None = None,
        element_properties: dict[int, dict[str, str]] | None = None,
        element_geometries: dict[int, "ElementGeometry"] | None = None,
    ):
        self._families = list(families) if families is not None else []
        self._levels = list(levels) if levels is not None else list(self._DEFAULT_LEVELS)
        self._grids = list(grids) if grids is not None else list(self._DEFAULT_GRIDS)
        self._parameter_info = parameter_info or {}
        self._element_properties = element_properties or {}
        self._element_geometries = dict(element_geometries) if element_geometries else {}
        self.calls: list[str] = []

    async def query_families(self, category: str | None = None):
        self.calls.append(f"query_families(category={category!r})")
        if category is None:
            return list(self._families)
        return [f for f in self._families if f.category == category]

    async def query_levels(self):
        self.calls.append("query_levels()")
        return list(self._levels)

    async def query_grids(self):
        self.calls.append("query_grids()")
        return list(self._grids)

    async def query_parameter_info(self, family_symbol_id: int):
        self.calls.append(f"query_parameter_info({family_symbol_id})")
        return dict(self._parameter_info.get(family_symbol_id, {}))

    async def query_element_properties(self, element_id: int) -> dict[str, str]:
        self.calls.append(f"query_element_properties({element_id})")
        return dict(self._element_properties.get(element_id, {}))

    async def query_element_geometry(self, element_id: int) -> ElementGeometry:
        self.calls.append(f"query_element_geometry({element_id})")
        if element_id in self._element_geometries:
            return self._element_geometries[element_id]
        # Synthetic fallback: 400x400x3000 box at origin, no host.
        return ElementGeometry(
            element_id=element_id,
            bounding_box_min_mm=(-200.0, -200.0, 0.0),
            bounding_box_max_mm=(200.0, 200.0, 3000.0),
            centroid_mm=(0.0, 0.0, 1500.0),
            host_element_id=None,
            level_id=1,
        )

    def seed_geometry(self, geom: ElementGeometry) -> None:
        """Pre-load a geometry record under geom.element_id."""
        self._element_geometries[geom.element_id] = geom
