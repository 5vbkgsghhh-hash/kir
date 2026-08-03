"""Tests for FamilyResolver."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.resolver.family_resolver import FamilyResolver
from kukai.modeling.schemas.resolver import (
    FamilyHint,
    FamilyResolutionStatus,
    FamilySymbolCandidate,
)


_RC_400 = FamilySymbolCandidate(
    family_symbol_id=8821, name="400 x 400mm",
    family_name="M_Concrete-Rectangular-Column",
    category="OST_StructuralColumns",
    dimensions_mm={"width": 400, "height": 400},
)
_RC_500 = FamilySymbolCandidate(
    family_symbol_id=8822, name="500 x 500mm",
    family_name="M_Concrete-Rectangular-Column",
    category="OST_StructuralColumns",
    dimensions_mm={"width": 500, "height": 500},
)
_STEEL_HEA = FamilySymbolCandidate(
    family_symbol_id=8830, name="HEA 200",
    family_name="M_Steel-Wide-Flange",
    category="OST_StructuralColumns",
    dimensions_mm={"width": 200, "height": 190},
)


@pytest.mark.asyncio
async def test_resolves_unique_by_dimensions():
    client = MockModelQueryClient(families=[_RC_400, _RC_500])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(
        category="OST_StructuralColumns",
        dimensions_mm={"width": 400, "height": 400},
    ))
    assert result.status == FamilyResolutionStatus.RESOLVED
    assert result.symbol_id == 8821


@pytest.mark.asyncio
async def test_ambiguous_when_multiple_match():
    duplicate = _RC_400.model_copy(update={"family_symbol_id": 8823, "name": "alt"})
    client = MockModelQueryClient(families=[_RC_400, duplicate])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(
        category="OST_StructuralColumns",
        dimensions_mm={"width": 400, "height": 400},
    ))
    assert result.status == FamilyResolutionStatus.AMBIGUOUS
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_not_found_empty_category():
    client = MockModelQueryClient(families=[])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(category="OST_StructuralColumns"))
    assert result.status == FamilyResolutionStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_not_found_no_dim_match_returns_neighbors_as_candidates():
    client = MockModelQueryClient(families=[_RC_400, _RC_500])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(
        category="OST_StructuralColumns",
        dimensions_mm={"width": 600, "height": 600},
    ))
    assert result.status == FamilyResolutionStatus.NOT_FOUND
    # Helpful: shows what was available so Foreman/user can pick
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_material_hint_filters():
    """material_hint='concrete' should reject Steel-Wide-Flange even at matching dimensions."""
    client = MockModelQueryClient(families=[_RC_400, _STEEL_HEA])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(
        category="OST_StructuralColumns",
        dimensions_mm={"width": 400, "height": 400},
        material_hint="concrete",
    ))
    assert result.status == FamilyResolutionStatus.RESOLVED
    assert result.symbol_id == 8821


@pytest.mark.asyncio
async def test_name_contains_filter():
    client = MockModelQueryClient(families=[_RC_400, _STEEL_HEA])
    r = FamilyResolver(client)
    result = await r.resolve(FamilyHint(
        category="OST_StructuralColumns",
        name_contains=["Steel"],
    ))
    assert result.status == FamilyResolutionStatus.RESOLVED
    assert result.symbol_id == 8830
