"""End-to-end integration test for substrate layer.

Walks through a realistic mini-lifecycle:
- init project
- emit phase-started + 3 element-created + 1 element-failed events
- rebuild ProjectState projection via cache
- verify all counts and current phase
- assert log integrity (monotonic sequence, no gaps)
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

from kukai.modeling.cli import cmd_project_init
from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.schemas.tasks import Phase
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.event_log import EventLog
from kukai.modeling.state.project_directory import ProjectStateDirectory
from kukai.modeling.state.projection_cache import ProjectionCache
from kukai.modeling.state.projections.project_state import (
    ProjectState, ProjectStateReducer
)


def test_full_substrate_lifecycle(tmp_path: Path):
    # 1. init project
    init_result = cmd_project_init("integration_t1", tmp_path)
    project_path = Path(init_result["path"])

    pdir = ProjectStateDirectory(project_path)
    bus = EventBus(pdir)
    log = EventLog(pdir)

    # init already emitted PROJECT_CREATED at sequence 0
    assert bus.next_sequence() == 1

    # 2. emit phase started
    bus.emit(EventBase(
        event_id="phase1",
        timestamp=datetime.now(timezone.utc),
        sequence=bus.next_sequence(),
        correlation_id="phase_structure",
        causation_id=None,
        event_type=EventType.PHASE_STARTED,
        payload={"phase": "structure"},
    ))

    # 3. emit 3 ELEMENT_CREATED + 1 ELEMENT_FAILED
    for i in range(3):
        bus.emit(EventBase(
            event_id=f"ec_{i}",
            timestamp=datetime.now(timezone.utc),
            sequence=bus.next_sequence(),
            correlation_id=f"task_{i}",
            causation_id=None,
            event_type=EventType.ELEMENT_CREATED,
            payload={"element_id": 8000 + i, "task_id": f"task_{i}"},
        ))
    bus.emit(EventBase(
        event_id="ef_1",
        timestamp=datetime.now(timezone.utc),
        sequence=bus.next_sequence(),
        correlation_id="task_failed",
        causation_id=None,
        event_type=EventType.ELEMENT_FAILED,
        payload={"task_id": "task_failed", "reason": "compile_fail"},
    ))

    # 4. rebuild projection via cache
    cache = ProjectionCache(
        pdir, ProjectState, ProjectStateReducer(), name="project_state"
    )
    state = cache.load_or_rebuild(log)

    assert state.current_phase == Phase.STRUCTURE
    assert state.elements_placed == 3
    assert state.elements_failed == 1
    assert state.last_event_sequence == 5  # 0..5 inclusive = 6 events

    # 5. save projection, reload — should match
    cache.save(state)
    reloaded = cache.load()
    assert reloaded == state

    # 6. log integrity check: sequences monotonic, no duplicates, no gaps
    all_events = list(log.iter())
    sequences = [e.sequence for e in all_events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)  # no duplicates
    assert sequences == list(range(len(sequences)))  # no gaps from 0
