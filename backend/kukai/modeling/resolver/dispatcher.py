"""Resolver dispatcher — composes the four sub-resolvers into one entry point.

Per spec Section 5.3 + role-play audit. Foreman calls Resolver.resolve(intent)
and receives a fully-resolved ResolverOutput ready for Subagent dispatch.
"""
from __future__ import annotations

from kukai.modeling.bridge.model_query_client import ModelQueryClient
from kukai.modeling.resolver.family_resolver import FamilyResolver
from kukai.modeling.resolver.geometry_resolver import GeometryResolver
from kukai.modeling.resolver.parameter_map_resolver import ParameterMapResolver
from kukai.modeling.resolver.version_selector import VersionSelector
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.resolver import (
    FamilyResolutionStatus,
    ResolverIntent,
    ResolverOutput,
)


class Resolver:
    """Composes Family/Geometry/ParameterMap/Version resolution."""

    def __init__(self, query_client: ModelQueryClient):
        self._family = FamilyResolver(query_client)
        self._geometry = GeometryResolver(query_client)
        self._params = ParameterMapResolver(query_client)

    async def resolve(self, intent: ResolverIntent) -> ResolverOutput:
        notes: list[str] = []

        # 1. Validate version
        version_info = VersionSelector(intent.revit_version).info()
        notes.append(f"version: {intent.revit_version} ({version_info.dotnet}, EID={version_info.element_id_property})")

        # 2. Resolve family
        fam_result = await self._family.resolve(intent.family_hint)
        if fam_result.note:
            notes.append(fam_result.note)

        # 3. Resolve geometry
        if intent.explicit_point is not None:
            point = intent.explicit_point
            if intent.grid_intersection is not None:
                level_id = await self._geometry.lookup_level_id(intent.grid_intersection.level_name)
                if level_id is None:
                    raise KeyError(f"level {intent.grid_intersection.level_name!r} not found")
            elif intent.top_level_name is not None:
                # Fallback: use top_level_name to anchor level when no grid_intersection
                level_id = await self._geometry.lookup_level_id(intent.top_level_name)
                if level_id is None:
                    raise KeyError(f"level {intent.top_level_name!r} not found")
            else:
                raise ValueError("ResolverIntent with explicit_point must provide grid_intersection.level_name or top_level_name")
        elif intent.grid_intersection is not None:
            geo = await self._geometry.resolve_grid_intersection(intent.grid_intersection)
            point = geo.point
            level_id = geo.level_id
        else:
            raise ValueError("ResolverIntent requires either grid_intersection or explicit_point")

        # 4. Resolve top level
        top_level_id: int | None = None
        if intent.top_level_name is not None:
            top_level_id = await self._geometry.lookup_level_id(intent.top_level_name)
            if top_level_id is None:
                notes.append(f"top_level {intent.top_level_name!r} not found; top_level_id omitted")

        # 5. Resolve parameter map (only if family resolved)
        parameter_map: dict = {}
        if fam_result.status == FamilyResolutionStatus.RESOLVED and fam_result.symbol_id is not None:
            parameter_map = await self._params.resolve(fam_result.symbol_id)

        return ResolverOutput(
            family_resolution=fam_result.status,
            family_symbol_id=fam_result.symbol_id,
            candidate_symbols=fam_result.candidates,
            parameter_map=parameter_map,
            placement_point=point,
            level_id=level_id,
            top_level_id=top_level_id,
            revit_version=intent.revit_version,
            notes=notes,
        )
