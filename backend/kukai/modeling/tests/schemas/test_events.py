"""Tests for event schema base and enum."""
from __future__ import annotations
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.events import EventType, EventBase


class TestEventType:
    def test_all_required_types_present(self):
        # Lifecycle
        assert EventType.PROJECT_CREATED.value == "project.created"
        assert EventType.BRIEF_INGESTED.value == "brief.ingested"
        # Phases
        assert EventType.PHASE_STARTED.value == "phase.started"
        assert EventType.PHASE_COMPLETED.value == "phase.completed"
        # Tasks
        assert EventType.TASK_DISPATCHED.value == "task.dispatched"
        assert EventType.ELEMENT_CREATED.value == "element.created"
        assert EventType.ELEMENT_FAILED.value == "element.failed"
        # QC
        assert EventType.GATE_EVALUATED.value == "gate.evaluated"
        # System
        assert EventType.SYSTEM_PAUSE.value == "system.pause"


class TestEventBase:
    def test_creates_with_required_fields(self):
        e = EventBase(
            event_id="abc123",
            timestamp=datetime.now(timezone.utc),
            sequence=0,
            correlation_id="corr_1",
            causation_id=None,
            event_type=EventType.PROJECT_CREATED,
            payload={"project_id": "proj_1"},
        )
        assert e.event_id == "abc123"
        assert e.sequence == 0
        assert e.payload == {"project_id": "proj_1"}

    def test_rejects_missing_required(self):
        with pytest.raises(ValidationError):
            EventBase(event_id="abc")  # type: ignore

    def test_serializes_to_json(self):
        e = EventBase(
            event_id="abc123",
            timestamp=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            sequence=0,
            correlation_id="corr_1",
            causation_id=None,
            event_type=EventType.PROJECT_CREATED,
            payload={"k": "v"},
        )
        json_str = e.model_dump_json()
        assert '"event_id":"abc123"' in json_str
        assert '"event_type":"project.created"' in json_str

    def test_roundtrip_json(self):
        original = EventBase(
            event_id="abc123",
            timestamp=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            sequence=5,
            correlation_id="corr_1",
            causation_id="parent_evt",
            event_type=EventType.TASK_DISPATCHED,
            payload={"task_id": "t_1"},
        )
        json_str = original.model_dump_json()
        parsed = EventBase.model_validate_json(json_str)
        assert parsed == original
