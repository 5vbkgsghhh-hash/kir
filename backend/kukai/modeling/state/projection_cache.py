"""ProjectionCache — persists projection state with watermark for incremental rebuild.

Per spec Section 9.2: 'last_event_sequence' is the projection's watermark.
Reading projection: load cached state (if exists), then apply only events
with sequence > watermark.
"""
from __future__ import annotations
from typing import Generic, TypeVar

from pydantic import BaseModel

from kukai.modeling.state.event_log import EventLog
from kukai.modeling.state.project_directory import ProjectStateDirectory
from kukai.modeling.state.projections.base import Projection, Reducer


T = TypeVar("T", bound=BaseModel)


class ProjectionCache(Generic[T]):
    """Disk-cached projection with incremental rebuild from event log."""

    def __init__(
        self,
        project_dir: ProjectStateDirectory,
        state_type: type[T],
        reducer: Reducer[T],
        name: str,
    ):
        self._project_dir = project_dir
        self._state_type = state_type
        self._reducer = reducer
        self._name = name
        self._projection = Projection(state_type, reducer)

    def _cache_path(self):
        return self._project_dir.projection_path(self._name)

    def load(self) -> T | None:
        """Load cached projection from disk; return None if not present."""
        path = self._cache_path()
        if not path.exists():
            return None
        return self._state_type.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, state: T) -> None:
        """Persist projection to disk."""
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def load_or_rebuild(self, log: EventLog) -> T:
        """Return current projection state.

        If a cached state exists, use it as the starting point for incremental
        rebuild. Otherwise rebuild from scratch.
        """
        cached = self.load()
        return self._projection.rebuild(log, from_state=cached)
