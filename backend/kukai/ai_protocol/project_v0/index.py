"""Frozen AP02-owned derived index over one retained complete BuildResult."""
from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import ClassVar

from kukai.design_source import BuildEntityV0, BuildResultV0, FrozenMap
from kukai.design_source.canonical import identifier
from kukai.design_source.errors import QueryError


@dataclass(frozen=True, slots=True)
class ProjectBuildSummaryV0:
    schema: ClassVar[str] = "kir-build-summary/0"

    build_digest: str
    entity_count: int
    counts_by_semantic_type: FrozenMap[str, int]


@dataclass(frozen=True, slots=True)
class ProjectBuildQueryResultV0:
    build_digest: str
    entities: tuple[BuildEntityV0, ...]
    requested: int
    evaluated: int
    returned: int
    coverage: str = "COMPLETE"


@dataclass(frozen=True, slots=True)
class ProjectBuildIndexV0:
    """Deeply immutable lookup value derived from one exact retained build."""

    build: InitVar[BuildResultV0]
    build_digest: str = field(init=False)
    entity_ids: tuple[str, ...] = field(init=False)
    entities: tuple[BuildEntityV0, ...] = field(init=False, repr=False)
    _by_id: FrozenMap[str, BuildEntityV0] = field(init=False, repr=False)
    _counts_by_semantic_type: FrozenMap[str, int] = field(
        init=False, repr=False)

    def __post_init__(self, build: BuildResultV0) -> None:
        if type(build) is not BuildResultV0:
            raise QueryError(
                "ProjectBuildIndex requires an exact BuildResultV0")
        entities = tuple(build.entities)
        counts: dict[str, int] = {}
        for entity in entities:
            counts[entity.semantic_type] = counts.get(entity.semantic_type, 0) + 1
        object.__setattr__(self, "build_digest", build.manifest.build_digest)
        object.__setattr__(self, "entity_ids", build.manifest.entity_ids)
        object.__setattr__(self, "entities", entities)
        object.__setattr__(
            self,
            "_by_id",
            FrozenMap({item.logical_id: item for item in entities}),
        )
        object.__setattr__(
            self, "_counts_by_semantic_type", FrozenMap(counts))

    def summary(self) -> ProjectBuildSummaryV0:
        return ProjectBuildSummaryV0(
            build_digest=self.build_digest,
            entity_count=len(self.entities),
            counts_by_semantic_type=self._counts_by_semantic_type,
        )

    def by_logical_id(self, logical_id: str) -> BuildEntityV0:
        identifier(logical_id, "logical_id")
        try:
            return self._by_id[logical_id]
        except KeyError as exc:
            raise QueryError(
                f"unknown BuildGraph logical_id {logical_id!r}") from exc

    def by_origin(
        self,
        *,
        module_id: str | None = None,
        instance_id: str | None = None,
        call_id: str | None = None,
        slot_id: str | None = None,
        occurrence_key: str | None = None,
    ) -> ProjectBuildQueryResultV0:
        filters = {
            key: value for key, value in {
                "call_id": call_id,
                "instance_id": instance_id,
                "module_id": module_id,
                "occurrence_key": occurrence_key,
                "slot_id": slot_id,
            }.items() if value is not None
        }
        if not filters:
            raise QueryError("origin query requires at least one indexed filter")
        for key, value in filters.items():
            identifier(value, key)
        matches = tuple(
            entity for entity in self.entities
            if all(
                getattr(entity.origin, key) == value
                for key, value in filters.items()
            )
        )
        return ProjectBuildQueryResultV0(
            build_digest=self.build_digest,
            entities=matches,
            requested=len(self.entities),
            evaluated=len(self.entities),
            returned=len(matches),
        )


__all__ = [
    "ProjectBuildIndexV0",
    "ProjectBuildQueryResultV0",
    "ProjectBuildSummaryV0",
]
