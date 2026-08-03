"""Tests for Projection base class."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.event_log import EventLog
from kukai.modeling.state.project_directory import ProjectStateDirectory
from kukai.modeling.state.projections.base import Projection, Reducer


class _CountingState(BaseModel):
    """Test projection: counts events by type."""
    last_event_sequence: int = -1
    counts: dict[str, int] = {}


class _CountingReducer:
    """Reducer that counts events by type."""

    def apply(self, state: _CountingState, event: EventBase) -> _CountingState:
        new_counts = dict(state.counts)
        key = event.event_type.value
        new_counts[key] = new_counts.get(key, 0) + 1
        return _CountingState(
            last_event_sequence=event.sequence,
            counts=new_counts,
        )


class TestProjection:
    def test_rebuilds_from_empty(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        log = EventLog(d)
        proj = Projection(_CountingState, _CountingReducer())

        state = proj.rebuild(log)
        assert state.last_event_sequence == -1
        assert state.counts == {}

    def test_rebuilds_from_log(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        for i in range(3):
            bus.emit(EventBase(
                event_id=f"e{i}",
                timestamp=datetime.now(timezone.utc),
                sequence=bus.next_sequence(),
                correlation_id="c1",
                causation_id=None,
                event_type=EventType.TASK_DISPATCHED,
                payload={},
            ))
        bus.emit(EventBase(
            event_id="e3",
            timestamp=datetime.now(timezone.utc),
            sequence=bus.next_sequence(),
            correlation_id="c1",
            causation_id=None,
            event_type=EventType.ELEMENT_CREATED,
            payload={},
        ))

        log = EventLog(d)
        proj = Projection(_CountingState, _CountingReducer())
        state = proj.rebuild(log)

        assert state.last_event_sequence == 3
        assert state.counts["task.dispatched"] == 3
        assert state.counts["element.created"] == 1

    def test_incremental_rebuild_from_state(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        for i in range(3):
            bus.emit(EventBase(
                event_id=f"e{i}",
                timestamp=datetime.now(timezone.utc),
                sequence=bus.next_sequence(),
                correlation_id="c1",
                causation_id=None,
                event_type=EventType.TASK_DISPATCHED,
                payload={},
            ))

        log = EventLog(d)
        proj = Projection(_CountingState, _CountingReducer())
        partial_state = proj.rebuild(log)  # gets all 3

        # Add 2 more events
        for i in range(2):
            bus.emit(EventBase(
                event_id=f"f{i}",
                timestamp=datetime.now(timezone.utc),
                sequence=bus.next_sequence(),
                correlation_id="c1",
                causation_id=None,
                event_type=EventType.ELEMENT_CREATED,
                payload={},
            ))

        updated = proj.rebuild(log, from_state=partial_state)
        assert updated.last_event_sequence == 4
        assert updated.counts["task.dispatched"] == 3
        assert updated.counts["element.created"] == 2


# --- ProjectState tests ---

from kukai.modeling.schemas.tasks import Phase
from kukai.modeling.state.projections.project_state import (
    ProjectState, ProjectStateReducer
)


class TestProjectStateProjection:
    def test_initial_state(self):
        s = ProjectState()
        assert s.current_phase == Phase.SETUP
        assert s.elements_placed == 0
        assert s.elements_failed == 0
        assert s.last_event_sequence == -1
        assert s.cost_consumed_usd == 0.0
        assert s.user_intervention_required is False

    def test_phase_started_advances(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        bus.emit(EventBase(
            event_id="e0",
            timestamp=datetime.now(timezone.utc),
            sequence=bus.next_sequence(),
            correlation_id="c",
            causation_id=None,
            event_type=EventType.PHASE_STARTED,
            payload={"phase": "structure"},
        ))

        proj = Projection(ProjectState, ProjectStateReducer())
        state = proj.rebuild(EventLog(d))
        assert state.current_phase == Phase.STRUCTURE

    def test_element_created_increments_placed(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        for i in range(3):
            bus.emit(EventBase(
                event_id=f"e{i}",
                timestamp=datetime.now(timezone.utc),
                sequence=bus.next_sequence(),
                correlation_id="c",
                causation_id=None,
                event_type=EventType.ELEMENT_CREATED,
                payload={"element_id": 8000 + i},
            ))

        proj = Projection(ProjectState, ProjectStateReducer())
        state = proj.rebuild(EventLog(d))
        assert state.elements_placed == 3

    def test_element_failed_increments_failed(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        bus.emit(EventBase(
            event_id="e0",
            timestamp=datetime.now(timezone.utc),
            sequence=bus.next_sequence(),
            correlation_id="c",
            causation_id=None,
            event_type=EventType.ELEMENT_FAILED,
            payload={"task_id": "t1"},
        ))

        proj = Projection(ProjectState, ProjectStateReducer())
        state = proj.rebuild(EventLog(d))
        assert state.elements_failed == 1
