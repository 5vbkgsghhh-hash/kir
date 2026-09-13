"""G2 — the expert's three tools fit 5 500 B, schemas alone 2 200 B.

Two ceilings and not one: with a single total, prose would eat the schemas or
the schemas the prose, and nobody would see it happen.
"""
from __future__ import annotations

import json

from kir.door import registry as R

EXPERT_MAX_BYTES = 5_500        # gate G2; measured on this tree: 3 659
EXPERT_SCHEMAS_MAX_BYTES = 2_200


def _schemas_bytes(role: str) -> int:
    return sum(len(json.dumps(t.schema(role), ensure_ascii=False).encode())
               for t in R.TOOLS if role in t.roles)


def test_three_tools_fit_the_ratchet():
    size = R.surface_bytes("expert")
    assert size <= EXPERT_MAX_BYTES, (
        f"поверхность эксперта {size} Б превысила {EXPERT_MAX_BYTES} Б")


def test_the_split_between_schemas_and_prose_is_named():
    schemas = _schemas_bytes("expert")
    prose = R.surface_bytes("expert") - schemas
    assert schemas <= EXPERT_SCHEMAS_MAX_BYTES, f"схемы {schemas} Б"
    # Prose is allowed to be the larger half — that is the whole finding of
    # S's run: a weak model needs the words, not the JSON.
    assert prose > 0


def test_the_lead_surface_is_bounded_too():
    size = R.surface_bytes("lead")
    assert size <= R.LEAD_SURFACE_MAX_BYTES, f"поверхность лида {size} Б"


def test_control_a_fourth_tool_goes_red():
    """Adding a tool to a role must break either this gate or G4 — and the
    arithmetic here shows it breaks this one too, so neither can be dodged."""
    extra = 1_900  # a modest fourth tool: schema + prose
    assert R.surface_bytes("expert") + extra * 2 > EXPERT_MAX_BYTES
