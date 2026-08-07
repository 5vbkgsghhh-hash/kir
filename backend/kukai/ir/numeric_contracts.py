"""Shared numeric limits that define the KIR value domain.

These are frontend contracts, not emitter implementation details. Keeping
them below validation, grounding and domain helpers prevents those stages
from importing one another merely to share a number.
"""
from __future__ import annotations


# Static coordinate sanity bound (audit F12): Revit's workable model extent is
# approximately 16 km from the origin. Values outside it are treated as a
# unit/garbage error before any transaction.
MODEL_COORD_LIMIT_MM = 16_000_000.0

