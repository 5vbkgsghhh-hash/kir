"""FamilyResolver — picks a FamilySymbol matching Foreman's FamilyHint.

Logic (in priority order):
1. Filter loaded families by category
2. Apply material_hint substring filter on family_name (lowercased)
3. Apply name_contains substring filters on name + family_name
4. If dimensions_mm provided, exact-match keys within tolerance (1mm)
5. Verdict: RESOLVED iff exactly 1 candidate remains; AMBIGUOUS iff >1;
   NOT_FOUND iff 0 — with neighbors-by-category preserved as candidates
   for diagnostic context.
"""
from __future__ import annotations
from dataclasses import dataclass

from kukai.modeling.bridge.model_query_client import ModelQueryClient
from kukai.modeling.schemas.resolver import (
    FamilyHint,
    FamilyResolutionStatus,
    FamilySymbolCandidate,
)


_DIM_TOLERANCE_MM = 1.0


_MATERIAL_KEYWORDS: dict[str, list[str]] = {
    "concrete": ["concrete", "rc", "rebar", "бетон", "жб"],
    "steel": ["steel", "wide-flange", "hea", "heb", "hem", "ipe", "сталь"],
    "wood": ["wood", "timber", "lumber", "дерево"],
    "masonry": ["masonry", "brick", "block", "кирпич"],
}


@dataclass(frozen=True)
class FamilyResolution:
    """FamilyResolver verdict for one FamilyHint."""
    status: FamilyResolutionStatus
    symbol_id: int | None
    candidates: list[FamilySymbolCandidate]
    note: str = ""


class FamilyResolver:
    def __init__(self, query_client: ModelQueryClient):
        self._client = query_client

    async def resolve(self, hint: FamilyHint) -> FamilyResolution:
        category_pool = await self._client.query_families(category=hint.category)
        if not category_pool:
            return FamilyResolution(
                status=FamilyResolutionStatus.NOT_FOUND,
                symbol_id=None,
                candidates=[],
                note=f"no families loaded in {hint.category}",
            )

        filtered = list(category_pool)

        if hint.material_hint:
            keywords = _MATERIAL_KEYWORDS.get(hint.material_hint.lower(), [hint.material_hint.lower()])
            filtered = [c for c in filtered if any(k in c.family_name.lower() for k in keywords)]

        for needle in hint.name_contains:
            n = needle.lower()
            filtered = [c for c in filtered if n in c.name.lower() or n in c.family_name.lower()]

        if hint.dimensions_mm:
            filtered = [c for c in filtered if _dims_match(c.dimensions_mm, hint.dimensions_mm)]

        if len(filtered) == 1:
            return FamilyResolution(
                status=FamilyResolutionStatus.RESOLVED,
                symbol_id=filtered[0].family_symbol_id,
                candidates=[filtered[0]],
            )
        if len(filtered) > 1:
            return FamilyResolution(
                status=FamilyResolutionStatus.AMBIGUOUS,
                symbol_id=None,
                candidates=filtered,
                note=f"{len(filtered)} candidates match {hint}",
            )

        # No dimension-or-name match — return category pool as helpful neighbors
        return FamilyResolution(
            status=FamilyResolutionStatus.NOT_FOUND,
            symbol_id=None,
            candidates=category_pool,
            note=f"no family in {hint.category} matched dims/material/name; showing {len(category_pool)} candidates",
        )


def _dims_match(actual: dict[str, float], desired: dict[str, float]) -> bool:
    """All keys in `desired` must be present in `actual` within tolerance."""
    for k, v in desired.items():
        a = actual.get(k)
        if a is None:
            return False
        if abs(a - v) > _DIM_TOLERANCE_MM:
            return False
    return True
