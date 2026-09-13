"""G4 — four tools at most, and the lead sees no op name anywhere.

Owner's word: the starting model is a MANAGER and must not know 83 ops. That
is not a preference about prompts — it is what S measured: a lead with the
section map at 591 characters handed out exactly one brief, while the same
model given the language looped.
"""
from __future__ import annotations

import json

from kir.door import registry as R


def test_no_role_exceeds_four_tools():
    for role in R.ROLES:
        assert len(R.names(role)) <= R.MAX_TOOLS_PER_ROLE, role


def test_the_lead_has_no_build_door():
    assert "kir_build" not in R.names("lead")
    assert R.names("lead") == ("kir_read", "assign", "show_preview", "ask_user")
    assert R.names("expert") == ("kir_build", "kir_read", "question_to_lead")


def test_the_lead_sees_no_op_name_anywhere():
    """Checked against the WHOLE registry of 83 names, not one example: a
    single sample would pass the day someone writes `create_beam` into a
    description."""
    from kir import spec

    blob = json.dumps(R.projection("mcp", "lead"), ensure_ascii=False)
    leaked = sorted(op for op in spec.OPS if op in blob)
    assert leaked == [], f"имена операций у лида: {leaked}"


def test_the_expert_cannot_speak_to_the_human():
    assert "ask_user" not in R.names("expert")
    assert "question_to_lead" not in R.names("lead")


def test_a_name_outside_the_role_is_refused_by_naming_what_is_inside():
    ctx = R.Ctx(role="lead")
    out = R.call("kir_build", {"source": "x"}, ctx)
    assert out["ok"] is False
    assert out["err"]["code"] == "tool_not_in_role"
    assert "kir_read" in out["err"]["message_ru"]
    assert out["next"]["do"] in R.names("lead")


def test_control_projecting_build_to_the_lead_goes_red():
    from kir import spec

    faked = R.projection("mcp", "lead") + [
        {"name": "kir_build", "description": "create_wall(...)",
         "input_schema": {}}]
    blob = json.dumps(faked, ensure_ascii=False)
    assert any(op in blob for op in spec.OPS)
    assert len(faked) > R.MAX_TOOLS_PER_ROLE
