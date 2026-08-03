"""Tests for ProjectionCache."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.schemas.tasks import Phase
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.event_log import EventLog
from kukai.modeling.state.project_directory import ProjectStateDirectory
from kukai.modeling.state.projection_cache import ProjectionCache
from kukai.modeling.state.projections.project_state import (
    ProjectState, ProjectStateReducer
)


def _emit_phase_started(bus: EventBus, phase: str) -> None:
    bus.emit(EventBase(
        event_id=f"e_{phase}",
        timestamp=datetime.now(timezone.utc),
        sequence=bus.next_sequence(),
        correlation_id="c",
        causation_id=None,
        event_type=EventType.PHASE_STARTED,
        payload={"phase": phase},
    ))


class TestProjectionCache:
    def test_saves_and_loads(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_phase_started(bus, "structure")

        cache = ProjectionCache(d, ProjectState, ProjectStateReducer(), name="project_state")
        state = cache.load_or_rebuild(EventLog(d))
        assert state.current_phase == Phase.STRUCTURE

        # Save explicitly
        cache.save(state)

        # Load again — should come from cache, not rebuild
        state2 = cache.load()
        assert state2 is not None
        assert state2.current_phase == Phase.STRUCTURE

    def test_incremental_rebuild_uses_cached_watermark(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_phase_started(bus, "structure")

        cache = ProjectionCache(d, ProjectState, ProjectStateReducer(), name="project_state")
        state1 = cache.load_or_rebuild(EventLog(d))
        cache.save(state1)

        # Add another event
        _emit_phase_started(bus, "architecture")

        # Should incrementally rebuild from cached watermark
        state2 = cache.load_or_rebuild(EventLog(d))
        assert state2.current_phase == Phase.ARCHITECTURE

    def test_load_returns_none_if_no_cache(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        cache = ProjectionCache(d, ProjectState, ProjectStateReducer(), name="project_state")
        assert cache.load() is None
