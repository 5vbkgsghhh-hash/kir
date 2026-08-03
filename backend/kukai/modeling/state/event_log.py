"""EventLog — read-only access to the event log for replay and queries."""
from __future__ import annotations
import json
from typing import Iterator

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.state.project_directory import ProjectStateDirectory


class EventLog:
    """Read-only event log access. Streams from disk; no in-memory buffer."""

    def __init__(self, project_dir: ProjectStateDirectory):
        self._project_dir = project_dir

    def iter(
        self,
        from_sequence: int = 0,
        event_types: set[EventType] | None = None,
    ) -> Iterator[EventBase]:
        """Yield events from the log in sequence order.

        Args:
            from_sequence: skip events with sequence < this
            event_types: only yield events matching one of these types
        """
        path = self._project_dir.history_path
        if not path.exists():
            return

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = EventBase.model_validate_json(line)
                if event.sequence < from_sequence:
                    continue
                if event_types is not None and event.event_type not in event_types:
                    continue
                yield event

    def last_event(self) -> EventBase | None:
        """Return the highest-sequence event, or None if empty."""
        last = None
        for event in self.iter():
            last = event
        return last
