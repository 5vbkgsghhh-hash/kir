"""ForemanToolBox — single facade for everything Foreman needs to *read*.

Foreman never reaches into ModelQueryClient or ProjectStateReducer directly.
It asks the ToolBox. This gives us one place to plug in caching, mocking,
or future telemetry without touching the orchestrator.

Per spec Section 5.2 ("Foreman tool surface"). Strictly read-only — any
mutation goes through Resolver + Subagent + ExecutionQueue.
"""
from __future__ import annotations
from typing import Callable

from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo, ModelQueryClient
from kukai.modeling.schemas.events import EventBase
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import Phase
from kukai.modeling.state.projections.project_state import ProjectState


ProjectStateProvider = Callable[[], ProjectState]
RecentEventsProvider = Callable[..., list[EventBase]]


class ForemanToolBox:
    """Read-only query surface composed for the Foreman.

    All async methods funnel through ModelQueryClient (bridge IO).
    All sync methods read in-memory projections / event log snapshots.
    """

    def __init__(
        self,
        *,
        query_client: ModelQueryClient,
        project_state_provider: ProjectStateProvider,
        recent_events_provider: RecentEventsProvider,
    ):
        self._query = query_client
        self._project_state = project_state_provider
        self._events = recent_events_provider

    # ---- Revit model reads (async, hit the bridge) ----

    async def list_families(self, category: str | None = None) -> list[FamilySymbolCandidate]:
        """Inventory of FamilySymbols currently loaded in the project.

        Optional category filter narrows to a BuiltInCategory (e.g. OST_StructuralColumns).
        """
        all_fams = await self._query.query_families(category=category)
        if category is None:
            return list(all_fams)
        return [f for f in all_fams if f.category == category]

    async def list_levels(self) -> list[LevelInfo]:
        """All Revit Levels with elevations (mm)."""
        return list(await self._query.query_levels())

    async def list_grids(self) -> list[GridInfo]:
        """All Revit Grids with axis and signed offset (mm)."""
        return list(await self._query.query_grids())

    # ---- Projection reads (sync, in-memory) ----

    def current_phase(self) -> Phase:
        return self._project_state().current_phase

    def phase_counts(self) -> tuple[int, int]:
        """Returns (elements_placed, elements_failed) cumulative across project."""
        s = self._project_state()
        return s.elements_placed, s.elements_failed

    def cost_consumed_usd(self) -> float:
        return self._project_state().cost_consumed_usd

    def user_intervention_state(self) -> tuple[bool, str | None]:
        s = self._project_state()
        return s.user_intervention_required, s.user_intervention_reason

    def recent_events(self, limit: int = 50) -> list[EventBase]:
        """Last `limit` events from history.jsonl (or test fixture)."""
        return list(self._events(limit=limit))
