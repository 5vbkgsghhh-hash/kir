"""Unit tests for BridgeModelQueryClient — parsing the live exec-channel results
into framework pydantic types, with a fake exec_fn (no live Revit).

The C# axis CONVENTION (critic B-2) is verified live on Муза, not here; these
tests cover the Python parsing/coercion contract that rides on it.
"""
import pytest

from kukai.modeling.bridge.bridge_model_query_client import BridgeModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.schemas.resolver import FamilySymbolCandidate

pytestmark = pytest.mark.asyncio


def _client(canned: dict):
    """canned maps a substring-of-the-C#-code -> the (already-unwrapped) result."""
    async def exec_fn(code: str, timeout_ms: int):
        for key, val in canned.items():
            if key in code:
                return val
        return []
    return BridgeModelQueryClient(exec_fn, revit_version="2026")


async def test_query_levels_parses_string_ids():
    c = _client({"OfClass(typeof(Level))": [
        {"level_id": "9124", "name": "L1", "elevation_mm": 0.0},
        {"level_id": "452074", "name": "L2", "elevation_mm": 3150.0},
    ]})
    assert await c.query_levels() == [
        LevelInfo(level_id=9124, name="L1", elevation_mm=0.0),
        LevelInfo(level_id=452074, name="L2", elevation_mm=3150.0),
    ]


async def test_query_families_coerces_and_skips_malformed():
    c = _client({"FamilySymbol": [
        {"family_symbol_id": "100", "name": "C-300", "family_name": "Concrete", "category": "Стены"},
        {"name": "broken — no id"},  # missing id -> skipped, not crash
    ]})
    fams = await c.query_families("OST_StructuralColumns")
    assert fams == [FamilySymbolCandidate(
        family_symbol_id=100, name="C-300", family_name="Concrete", category="Стены")]


async def test_query_grids_passthrough_axis():
    c = _client({"OfClass(typeof(Grid))": [
        {"grid_id": "451200", "name": "А", "axis": "vertical", "position_mm": 43589.8},
        {"grid_id": "538581", "name": "1", "axis": "horizontal", "position_mm": 36493.0},
    ]})
    grids = await c.query_grids()
    assert grids[0] == GridInfo(grid_id=451200, name="А", axis="vertical", position_mm=43589.8)
    assert grids[1].axis == "horizontal" and grids[1].grid_id == 538581


async def test_bridge_error_dict_raises():
    c = _client({"OfClass(typeof(Level))": {"error": True, "message": "device offline"}})
    with pytest.raises(RuntimeError, match="device offline"):
        await c.query_levels()


async def test_element_properties_coerced_to_str():
    c = _client({"GetElement": {"FamilySymbolId": "486336", "Mark": "K1", "Height": 3000}})
    props = await c.query_element_properties(99)
    assert props["FamilySymbolId"] == "486336"
    assert props["Mark"] == "K1"
    assert props["Height"] == "3000"          # int value coerced to str
    assert all(isinstance(v, str) for v in props.values())


async def test_element_geometry_parses_and_defaults():
    c = _client({"GetElement": {
        "min": [0.0, 0.0, 0.0], "max": [300.0, 300.0, 4000.0],
        "centroid": [150.0, 150.0, 2000.0], "level_id": "9124",
    }})
    g = await c.query_element_geometry(555692)
    assert g.element_id == 555692
    assert g.centroid_mm == (150.0, 150.0, 2000.0)
    assert g.level_id == 9124
    assert g.host_element_id is None          # absent -> None


async def test_parameter_info_degrades_to_empty():
    assert await _client({}).query_parameter_info(1) == {}


async def test_eid_literal_is_version_aware():
    assert BridgeModelQueryClient(None, revit_version="2026")._eid(5) == "5L"   # long for 2024+
    assert BridgeModelQueryClient(None, revit_version="2022")._eid(5) == "5"    # int for <=2023
