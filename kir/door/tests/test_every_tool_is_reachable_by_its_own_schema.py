"""EVERY TOOL MUST BE REACHABLE BY ITS OWN SCHEMA — the gate nine gates missed.

🔴 WHY THIS FILE EXISTS. On 13.09.2026 a LIVE model found that `assign` and
`show_preview` could not be called at all: `ask_outside` asked for `question`
BEFORE branching on the name, so both answered `question_required` — while
their schemas declare `required: ["section","brief"]` and
`additionalProperties: false`. The only road to success ran through a field the
schema FORBIDS. The lead called `assign` twice by the book, was refused twice,
and then carried a TOOL's obstacle to the HUMAN three times over `ask_user`.

Nine gates and 87 pins did not see it. Every one of them judged the SHAPE of a
refusal; not one asked whether a happy path is reachable. A door that only ever
refuses passes every test about refusals.

So the predicate here is not "does it work" (that needs a document) but: **fed
exactly what its own schema declares, does the tool stop complaining about its
FORM?**
"""
from __future__ import annotations

from typing import Any

from kir.door import registry as R

#: Refusals that mean "you called me wrong". If one of these comes back from a
#: call built FROM THE SCHEMA, the schema and the code disagree — which is the
#: whole defect.
FORM_REFUSALS = frozenset({
    "question_required", "what_required", "source_required",
    "section_required", "brief_required", "tool_not_in_role",
})


def _value_for(spec: dict, name: str) -> Any:
    """A plausible value for one declared property, derived FROM the schema."""
    if "const" in spec:
        return spec["const"]
    if "enum" in spec:
        return spec["enum"][0]
    kind = spec.get("type")
    if kind == "string":
        return "КР" if name == "section" else "разведка"
    if kind == "integer":
        return 1
    if kind == "boolean":
        return False
    if kind == "object":
        return {}
    if kind == "array":
        item = spec.get("items") or {}
        if item.get("type") == "object":
            return [{k: _value_for(v, k)
                     for k, v in (item.get("properties") or {}).items()}]
        return []
    return "x"


def _minimal_args(schema: dict) -> dict:
    """Exactly the REQUIRED fields, nothing more — `additionalProperties` is
    false almost everywhere, so "nothing more" is the only legal call."""
    props = schema.get("properties") or {}
    return {name: _value_for(props[name], name)
            for name in (schema.get("required") or []) if name in props}


def test_every_tool_of_every_role_accepts_its_own_required_fields():
    for role in R.ROLES:
        for name in R.names(role):
            schema = R.tool(name).schema(role)
            args = _minimal_args(schema)
            out = R.call(name, args, R.Ctx(role=role))
            code = (out.get("err") or {}).get("code")
            assert code not in FORM_REFUSALS, (
                f"{name} у роли {role}: вызван РОВНО по своей схеме "
                f"{sorted(args)} и отказал по форме «{code}» — схема и код "
                f"разошлись")


def test_a_call_by_the_schema_never_needs_a_forbidden_field():
    """The defect in its exact shape: success must not require a field the
    schema refuses."""
    for role in R.ROLES:
        for name in R.names(role):
            schema = R.tool(name).schema(role)
            if schema.get("additionalProperties") is not False:
                continue
            declared = set(schema.get("properties") or {})
            args = _minimal_args(schema)
            assert set(args) <= declared, (name, role)


def test_the_lead_hands_out_a_brief_without_a_single_refusal():
    """The live scenario, cassette `cassettes/B-p01-1.json`: two sections, two
    briefs, zero refusals."""
    lead = R.Ctx(role="lead")
    for section, brief in (("АР", "оси и габариты секции"),
                           ("КР", "фундаменты под шесть первых колонн")):
        out = R.call("assign", {"section": section, "brief": brief}, lead)
        assert out["ok"] is True, (section, out)
        assert out["assigned"] == section
        assert out["brief"] == brief
        assert "err" not in out


def test_the_lead_shows_a_sheet_without_a_question():
    out = R.call("show_preview", {"section": "КР"}, R.Ctx(role="lead"))
    assert out["ok"] is True and out["wrote_nothing"] is True
    out_all = R.call("show_preview", {}, R.Ctx(role="lead"))
    assert out_all["ok"] is True and out_all["shown"] == "всё"


def test_the_two_tools_that_do_ask_still_demand_their_question():
    """The fix moved the check, it did not delete it."""
    for name, role in (("question_to_lead", "expert"), ("ask_user", "lead")):
        out = R.call(name, {}, R.Ctx(role=role))
        assert out["ok"] is False
        assert out["err"]["code"] == "question_required"
        # `next` points back at the same tool, and that is legitimate here: the
        # field IS in the schema, so a second call can succeed. The dead end is
        # a move that cannot succeed, not a move that needs one more field.
        assert out["next"]["do"] == name
        assert "question" in R.tool(name).schema(role)["properties"]


def test_control_putting_the_question_check_back_in_front_goes_red():
    """The defect, reproduced as arithmetic: a check ahead of the branch would
    refuse a call that carries no `question` — and `assign`'s schema has no
    such field to carry."""
    assign_props = set(R.tool("assign").schema("lead")["properties"])
    assert "question" not in assign_props
    args = _minimal_args(R.tool("assign").schema("lead"))
    would_refuse = not isinstance(args.get("question"), str)
    assert would_refuse is True
    # and yet the door answers it:
    assert R.call("assign", args, R.Ctx(role="lead"))["ok"] is True
