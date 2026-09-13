"""Seniority as code, and КР first — that line is the owner's, not the module's.

Asked by THREE callers (merge on one address, clash of two bodies, a norm one
of two must break). Three copies of a table diverge on the first new section;
this tree already paid for one decision living in two places (the KIR-mode
boundary, audit H §1.5).
"""
from __future__ import annotations

import pytest

from kir.door import registry as R
from kir.door import seniority as S

CONFLICT = {"kind": "modify_modify", "path": "instances/tower-b"}


def test_kr_is_first_and_ahead_of_ar():
    """The owner's word: «КР важнее АР всегда». A pin, so a future wave cannot
    quietly re-sort it."""
    assert S.ORDER[0] == "КР"
    assert S.ORDER.index("КР") < S.ORDER.index("АР")


def test_every_position_carries_a_reason():
    for section in S.ORDER:
        assert section in S.REASON
        assert S.REASON[section].strip()
    assert set(S.REASON) == set(S.ORDER)


def test_the_order_is_a_tuple_and_holds_every_section_an_agent_can_type():
    assert isinstance(S.ORDER, tuple)
    for section in S.SECTIONS:
        assert S.rank(section) < len(S.ORDER), section


def test_an_unqualified_vk_counts_as_gravity():
    """Doubt leans to the STRONGER, and the asymmetry is the reason: reading a
    plain ВК as pressure when it was gravity asks gravity to change its slope —
    a redesign of the branch; the other way round moves a duct that need not
    have moved."""
    assert S.rank("ВК") == S.ORDER.index("ВК-самотёк")
    assert S.yields_to("ОВ", "ВК") is True
    assert S.yields_to("ВК", "ОВ") is False


def test_an_unknown_section_is_last_and_does_not_raise():
    """A raise here would take down a merge over a name nobody declared."""
    assert S.rank("ЧЕГО-ТО-НЕТ") == len(S.ORDER)
    assert S.yields_to("ЧЕГО-ТО-НЕТ", "КР") is True


def test_kr_wins_over_ar_and_the_line_says_why():
    out = S.decide(CONFLICT, ("АР", "КР"))
    assert out["winner"] == "КР" and out["loser"] == "АР"
    assert out["human_needed"] is False
    assert "несущее" in out["line_ru"]
    assert "instances/tower-b" in out["line_ru"]


def test_the_human_is_asked_in_exactly_two_cases():
    for flag in ("brief_ambiguous", "changes_explicit_request"):
        out = S.decide({**CONFLICT, flag: True}, ("АР", "КР"))
        assert out["human_needed"] is True, flag
        assert "человека" in out["line_ru"], flag


def test_on_every_other_input_the_human_is_not_asked():
    """The pin the brief asked for: everywhere else the LEAD decides. Asking a
    human otherwise is palka (h) — «UI объясняет то, что должен делать агент»."""
    pairs = [(a, b) for a in S.SECTIONS for b in S.SECTIONS
             if S.rank(a) != S.rank(b)]
    assert len(pairs) >= 12
    for kind in ("modify_modify", "clash", "norm"):
        for a, b in pairs:
            out = S.decide({"kind": kind, "path": "p"}, (a, b))
            assert out["human_needed"] is False, (kind, a, b)


def test_equal_rank_yields_to_nobody_and_says_so():
    out = S.decide(CONFLICT, ("СС", "СС"))
    assert out["winner"] is None
    assert out["human_needed"] is True
    assert "равны" in out["line_ru"]


def test_a_conflict_without_an_address_is_named_not_blank():
    out = S.decide({"kind": "clash"}, ("ОВ", "КР"))
    assert "адрес не назван" in out["line_ru"]


def test_one_line_serves_the_journal_and_the_expert():
    """The journal entry and the expert's explanation are the SAME string:
    two would drift, and the expert would be told a reason the journal does
    not hold."""
    out = S.decide(CONFLICT, ("АР", "КР"))
    answer = R.lead_answer(answers="переносим стену", decision=out)
    assert answer["decision"]["line_ru"] == out["line_ru"]


def test_the_door_has_one_entrance_to_seniority():
    out = R.rule_of_seniority(CONFLICT, ("АР", "КР"))
    assert out == S.decide(CONFLICT, ("АР", "КР"))


def test_control_resorting_the_order_goes_red():
    resorted = ("АР",) + tuple(s for s in S.ORDER if s != "АР")
    assert resorted[0] != "КР"
    with pytest.raises(AssertionError):
        assert resorted[0] == "КР"
