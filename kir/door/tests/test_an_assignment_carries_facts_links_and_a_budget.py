"""An assignment carries a fact SHEET, neighbour ADDRESSES and a BUDGET.

Every number here is from the M5 measurement (ДОК-M14): the winning cell built
P01 on the FIRST attempt with 940 characters, 2 help calls, 13 792 tokens and
76.44 s; the pathological cell burned 13 help calls, 151 311 tokens and 382.58 s
and built nothing.
"""
from __future__ import annotations

import json

import pytest

from kir.door import registry as R


def _assign_schema() -> dict:
    return R.tool("assign").schema("lead")


def test_the_fact_sheet_is_an_object_not_a_list_of_strings():
    """A sheet of NAMES makes an expert refuse before Revit: offline a
    type/symbol/system slot grounds only as `{"by": "element_id"}` — 21 of 35
    such slots take nothing else."""
    facts = _assign_schema()["properties"]["facts"]
    assert facts["type"] == "object"
    assert "element_id" in facts["description"]


def test_the_sheet_schema_is_the_one_S_measured():
    assert R.FACTS_SCHEMA == "kir-rq7-document-facts/2"


def test_neighbours_travel_as_addresses_never_as_program_text():
    """A neighbour may be rewritten after the brief goes out: the text would go
    stale silently, the address does not."""
    links = _assign_schema()["properties"]["links"]
    item = links["items"]
    assert item["properties"]["by"]["const"] == "pack"
    assert set(item["required"]) == {"by", "link", "output"}
    assert item["additionalProperties"] is False


def test_an_address_matches_what_project_pack_produces():
    from kir.project_pack import pack_ref

    made = pack_ref("АР", "S1")
    item = _assign_schema()["properties"]["links"]["items"]
    assert set(made) == set(item["properties"])
    assert made["by"] == item["properties"]["by"]["const"]


def test_the_budget_is_the_five_numbers_of_the_measurement():
    b = R.budget()
    assert b == {"prompt_chars": 1_000, "help_calls": 4,
                 "build_attempts": 3, "tokens": 20_000, "seconds": 120}
    # each ceiling is at least the winner and at most twice it
    assert b["prompt_chars"] >= 940
    assert b["help_calls"] >= 2 and b["help_calls"] <= 4
    assert b["tokens"] >= 13_792
    assert b["seconds"] >= 77


def test_the_budget_cuts_the_measured_funnel():
    """The pathological cell: 13 help calls, 151 311 tokens, 382.58 s. Each
    ceiling must be below it, or the budget is decoration."""
    b = R.budget()
    assert b["help_calls"] < 13
    assert b["tokens"] * 7 < 151_311
    assert b["seconds"] < 382


def test_an_exhausted_budget_asks_the_lead_and_is_never_silence():
    for kind in ("help_calls", "build_attempts", "tokens", "seconds"):
        out = R.exhausted(kind, detail="create_wall")
        assert out["asked"] == "lead"
        assert out["waiting"] is True
        assert out["question"].strip()
        assert out["budget_exhausted"] == kind


def test_an_unknown_budget_name_is_refused_loudly():
    with pytest.raises(ValueError):
        R.exhausted("выдумка")


def test_the_lead_answer_has_its_three_load_bearing_fields():
    answer = R.lead_answer(answers="строй по типу 274477",
                           facts_added={"wall_types": {"Наружная 250": 274477}},
                           decision={"line_ru": "АР уступает КР"},
                           budget_left={"tokens": 6000})
    assert answer["schema"] == R.LEAD_ANSWER_SCHEMA == "kir-door-lead-answer/1"
    assert answer["facts_added"]["wall_types"]["Наружная 250"] == 274477
    assert answer["decision"]["line_ru"]
    assert answer["budget_left"]["tokens"] == 6000


def test_a_lead_answer_that_says_nothing_is_refused():
    with pytest.raises(ValueError):
        R.lead_answer(answers="   ")


def test_the_lead_answer_defaults_the_budget_rather_than_omitting_it():
    """An expert that does not know its remainder spends it on reconnaissance
    — measured: 13 help calls on a task that never built."""
    assert R.lead_answer(answers="да")["budget_left"] == R.budget()


def test_the_lead_surface_still_fits_its_ratchet_after_the_growth():
    """🔴 THE SURFACE GREW AND THE NUMBER IS NAMED: 2 626 -> 3 096 B, +470 B,
    bought by the fact-sheet form and the neighbour addresses — the two things
    that stop `KIR-G103`. Ceiling 4 730 B is untouched."""
    size = R.surface_bytes("lead")
    assert size <= R.LEAD_SURFACE_MAX_BYTES
    assert size > 2_626, "лист фактов и адреса исчезли из поручения"
    blob = json.dumps(R.projection("mcp", "lead"), ensure_ascii=False)
    assert "element_id" in blob and "pack" in blob
