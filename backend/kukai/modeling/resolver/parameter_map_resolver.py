"""ParameterMapResolver — symbol -> semantic-name -> (Revit param, scope).

Per spec Section 5.3. Each family symbol exposes Revit parameters under
varying names ('b' vs 'Width' vs Cyrillic). Resolver provides a canonical
map: semantic_name -> (actual_param_name, scope) so Subagent doesn't guess.
"""
from __future__ import annotations

from kukai.modeling.bridge.model_query_client import ModelQueryClient
from kukai.modeling.schemas.resolver import ParameterScope


class ParameterMapResolver:
    def __init__(self, query_client: ModelQueryClient):
        self._client = query_client

    async def resolve(
        self, family_symbol_id: int
    ) -> dict[str, tuple[str, ParameterScope]]:
        raw = await self._client.query_parameter_info(family_symbol_id)
        result: dict[str, tuple[str, ParameterScope]] = {}
        for semantic_name, (actual_name, scope_str) in raw.items():
            try:
                scope = ParameterScope(scope_str)
            except ValueError as e:
                raise ValueError(
                    f"unknown ParameterScope {scope_str!r} for "
                    f"semantic={semantic_name!r} on symbol {family_symbol_id}"
                ) from e
            result[semantic_name] = (actual_name, scope)
        return result
