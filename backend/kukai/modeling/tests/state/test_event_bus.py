"""Tests for EventBus."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.project_directory import ProjectStateDirectory


def _make_event(seq: int, evt_type: EventType = EventType.PROJECT_CREATED) -> EventBase:
    return EventBase(
        event_id=f"evt_{seq}",
        timestamp=datetime.now(timezone.utc),
        sequence=seq,
        correlation_id="corr_1",
        causation_id=None,
        event_type=evt_type,
        payload={"seq": seq},
    )


class TestEventBus:
    def test_emit_creates_jsonl_line(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)

        bus.emit(_make_event(0))

        lines = d.history_path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["sequence"] == 0
        assert parsed["event_type"] == "project.created"

    def test_emit_appends_multiple(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)

        for i in range(5):
            bus.emit(_make_event(i))

        lines = d.history_path.read_text().splitlines()
        assert len(lines) == 5

    def test_emit_rejects_non_monotonic_sequence(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus = EventBus(d)

        bus.emit(_make_event(0))
        bus.emit(_make_event(1))

        import pytest
        with pytest.raises(ValueError, match="sequence"):
            bus.emit(_make_event(0))  # going backwards
        with pytest.raises(ValueError, match="sequence"):
            bus.emit(_make_event(1))  # duplicate

    def test_next_sequence_after_existing_log(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        bus1 = EventBus(d)
        bus1.emit(_make_event(0))
        bus1.emit(_make_event(1))

        # New bus on same project — should resume sequence
        bus2 = EventBus(d)
        assert bus2.next_sequence() == 2
