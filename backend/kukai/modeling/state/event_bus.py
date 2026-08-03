"""EventBus — append-only writer for the event log.

Per spec Section 9.1. Writes use append mode + fsync after each line for
atomicity on Windows NTFS (events <4KB are atomic at OS level).
"""
from __future__ import annotations
import json
import threading
from pathlib import Path

from kukai.modeling.schemas.events import EventBase
from kukai.modeling.state.project_directory import ProjectStateDirectory


class EventBus:
    """Append-only writer with monotonic sequence enforcement."""

    def __init__(self, project_dir: ProjectStateDirectory):
        self._project_dir = project_dir
        self._lock = threading.Lock()
        self._last_seq = self._scan_last_sequence()

    def _scan_last_sequence(self) -> int:
        """Return the highest sequence in the existing log, or -1 if empty."""
        path = self._project_dir.history_path
        if not path.exists():
            return -1
        last = -1
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                seq = json.loads(line)["sequence"]
                if seq > last:
                    last = seq
        return last

    def next_sequence(self) -> int:
        """Return the next sequence number that would be valid for emit()."""
        with self._lock:
            return self._last_seq + 1

    def emit(self, event: EventBase) -> None:
        """Append event to the log. Sequence must be > all prior events."""
        with self._lock:
            if event.sequence <= self._last_seq:
                raise ValueError(
                    f"event.sequence={event.sequence} not greater than "
                    f"last_sequence={self._last_seq}"
                )
            line = event.model_dump_json()
            path = self._project_dir.history_path
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                import os
                os.fsync(f.fileno())
            self._last_seq = event.sequence
