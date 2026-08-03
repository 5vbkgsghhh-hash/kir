"""Tests for EventLog reader."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.event_log import EventLog
from kukai.modeling.state.project_directory import ProjectStateDirectory


def _emit_n(bus: EventBus, n: int, evt_type: EventType = EventType.TASK_DISPATCHED) -> None:
    for i in range(n):
        bus.emit(EventBase(
            event_id=f"evt_{i}",
            timestamp=datetime.now(timezone.utc),
            sequence=bus.next_sequence(),
            correlation_id="corr_1",
            causation_id=None,
            event_type=evt_type,
            payload={"i": i},
        ))


class TestEventLog:
    def test_iter_all(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_n(bus, 5)

        log = EventLog(d)
        events = list(log.iter())
        assert len(events) == 5
        assert events[0].sequence == 0
        assert events[4].sequence == 4

    def test_iter_filter_by_type(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_n(bus, 3, EventType.TASK_DISPATCHED)
        _emit_n(bus, 2, EventType.ELEMENT_CREATED)

        log = EventLog(d)
        dispatched = list(log.iter(event_types={EventType.TASK_DISPATCHED}))
        assert len(dispatched) == 3
        created = list(log.iter(event_types={EventType.ELEMENT_CREATED}))
        assert len(created) == 2

    def test_iter_from_sequence(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_n(bus, 5)

        log = EventLog(d)
        events = list(log.iter(from_sequence=2))
        assert [e.sequence for e in events] == [2, 3, 4]

    def test_empty_log(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        log = EventLog(d)
        assert list(log.iter()) == []

    def test_last_event(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)
        _emit_n(bus, 3)

        log = EventLog(d)
        last = log.last_event()
        assert last is not None
        assert last.sequence == 2
