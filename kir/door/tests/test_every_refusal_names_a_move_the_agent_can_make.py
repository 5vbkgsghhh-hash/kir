"""G8 — a refusal names a move the agent CAN make.

Measured 13.09.2026: of three refusals that reached a model that day, **3 of
3** named a move it could not make — `revit_ir` absent from the palette
(`kukai/llm/client.py:3404-3408`), the environment variable
`KUKAI_KIR_TOOL=stage2` (`kir/serving.py:294`), and silence. The law makes
the third impossible and the other two unspellable.
"""
from __future__ import annotations

import re

from kir.door import registry as R
from kir.door.build import kir_build
from kir.door.read import kir_read

#: Names an agent cannot act on. Every one of these actually reached a model
#: through some door of this tree.
FORBIDDEN_IN_REFUSALS = ("KUKAI_KIR_TOOL", "KIR_MCP_WRITE", "KIR_MCP_PENDING_DIR",
                         "KUKAI_ADMIN_DEVICES", "KIR_TOOL")

_VARIABLE = re.compile(r"\b[A-Z][A-Z0-9_]{3,}=")

ALL_TOOL_NAMES = frozenset(t.name for t in R.TOOLS)


def _refusals_the_door_actually_produces() -> list[dict]:
    """Driven, not declared: a list of codes in a dataclass proves nothing
    about what a caller receives."""
    from kir.sandbox import SandboxPolicy

    expert = R.Ctx(role="expert")
    lead = R.Ctx(role="lead")
    out = [
        kir_build({}, expert),                                      # source_required
        kir_build({"source": "   "}, expert),                       # source_required
        kir_build({"source": "program = []"}, expert,
                  policy=SandboxPolicy(filesystem_isolation=False)),  # weak_sandbox
        kir_build({"source": "program = [нет_такого()]"}, expert),  # author_failed
        kir_build({"source": 'program = [create_level(id="L1", elev_mm=0, name="Э")]'},
                  expert),                                          # no_executor
        kir_read({}, expert),                                       # what_required
        kir_read({"what": "help"}, expert),                         # unknown_op
        kir_read({"what": "help", "op": "invented"}, expert),       # unknown_op
        kir_read({"what": "level_plan"}, expert),                   # no_level_plan_op
        kir_read({"what": "building"}, expert),                     # no_snapshot
        kir_read({"what": "выдумка"}, expert),                      # what_required
        R.call("kir_build", {"source": "x"}, lead),                 # tool_not_in_role
        R.call("assign", {"section": "СС", "brief": "b"}, lead),    # section_required
        R.call("assign", {"section": "КР"}, lead),                  # brief_required
        R.call("question_to_lead", {}, expert),                     # question_required
    ]
    return [r for r in out if r.get("ok") is False]


def test_the_door_really_produces_refusals_to_judge():
    assert len(_refusals_the_door_actually_produces()) >= 12


def test_every_refusal_has_a_next():
    for r in _refusals_the_door_actually_produces():
        assert isinstance(r.get("next"), dict), r["err"]["code"]
        assert r["next"].get("do"), r["err"]["code"]


def test_every_next_is_a_registry_tool_name():
    for r in _refusals_the_door_actually_produces():
        assert r["next"]["do"] in ALL_TOOL_NAMES, (r["err"]["code"], r["next"])


def test_no_refusal_text_contains_an_environment_variable():
    for r in _refusals_the_door_actually_produces():
        message = r["err"]["message_ru"]
        for name in FORBIDDEN_IN_REFUSALS:
            assert name not in message, (r["err"]["code"], name)
        assert not _VARIABLE.search(message), (r["err"]["code"], message)


def test_every_refusal_says_nothing_was_written():
    for r in _refusals_the_door_actually_produces():
        assert r.get("wrote_nothing") is True, r["err"]["code"]


def test_control_a_next_naming_a_variable_goes_red():
    bad = R.Refusal("gate", "недоступно: задай KUKAI_KIR_TOOL=stage2",
                    next="kir_read").as_dict()
    message = bad["err"]["message_ru"]
    assert any(n in message for n in FORBIDDEN_IN_REFUSALS)
    assert _VARIABLE.search(message)
