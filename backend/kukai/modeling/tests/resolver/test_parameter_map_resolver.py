"""Tests for ParameterMapResolver."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.resolver.parameter_map_resolver import ParameterMapResolver
from kukai.modeling.schemas.resolver import ParameterScope


@pytest.mark.asyncio
async def test_returns_empty_when_symbol_unknown():
    client = MockModelQueryClient()
    r = ParameterMapResolver(client)
    out = await r.resolve(8821)
    assert out == {}


@pytest.mark.asyncio
async def test_maps_scope_strings_to_enum():
    client = MockModelQueryClient(parameter_info={
        8821: {
            "width": ("b", "instance"),
            "mark": ("ALL_MODEL_MARK", "built_in"),
            "shared_x": ("KUKI_X", "shared"),
            "type_x": ("TY", "type"),
        },
    })
    r = ParameterMapResolver(client)
    out = await r.resolve(8821)
    assert out["width"] == ("b", ParameterScope.INSTANCE)
    assert out["mark"] == ("ALL_MODEL_MARK", ParameterScope.BUILT_IN)
    assert out["shared_x"] == ("KUKI_X", ParameterScope.SHARED)
    assert out["type_x"] == ("TY", ParameterScope.TYPE)


@pytest.mark.asyncio
async def test_unknown_scope_raises():
    client = MockModelQueryClient(parameter_info={
        8821: {"x": ("X", "bogus_scope")},
    })
    r = ParameterMapResolver(client)
    with pytest.raises(ValueError, match="bogus_scope"):
        await r.resolve(8821)
