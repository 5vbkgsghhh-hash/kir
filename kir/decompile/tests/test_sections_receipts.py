"""Fail-open receipts for sections — codex review #12.

Before this wave, `null`, `HasValue=false`, a foreign `StorageType`, and an exception inside
`__PutLengthParam` all collapsed into ONE missing key. A measurement on v13
shows what this costs: width is missing for 992 walls out of 1189, and 197 of the omissions
EXACTLY match curtain-wall hosts (`curtain.index.json`:
`curtain_available=True` for exactly 197, intersection with the omissions — 197, the difference
in both directions — 0). The match is perfect, and it is still not proof: the code
could not tell "the curtain-wall type has no such parameter" apart from "the parameter
exists but could not be read." A receipt distinguishes this by construction.

The census law here is literal: the sum of the six counters for EVERY parameter
must equal the number of elements of the category that were polled.

**Not verified live:** the wiring is proven offline (emission → page →
aggregate → `category_status` → law). Exactly which of the six outcomes a live
Revit gives for a curtain wall — measurement v14.

    venv/bin/pytest kir/decompile/tests/test_sections_receipts.py -q
"""
from __future__ import annotations

import re

import asyncio
import json
import pathlib

import pytest

from kir.decompile.extract import (
    SECTION_PARAM_NAMES,
    ExtractionProtocolError,
    _parse_page,
    _Scope,
    build_category_batch_cs,
)
from kir.decompile.schema import (
    SECTION_RECEIPT_OUTCOMES,
    CategoryState,
    CategoryStatus,
    L0SchemaError,
    SectionReceipt,
)
from kir.decompile.snapshot_io import open_snapshot, snapshot_file_exists
from kir.decompile.tests.fixtures_decompile import make_element

LIVE_V13 = (pathlib.Path(__file__).resolve().parents[4]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v13")


# ── emission ────────────────────────────────────────────────────────────────

def test_the_emission_counts_every_outcome_of_a_section_read():
    """The six outcomes must be DIFFERENT branches of the generated C#.

    What is checked is not text for text's sake: every line below is an outcome that
    used to be indistinguishable from the other five.
    """
    cs = build_category_batch_cs("OST_Walls")
    assert "__PutSectionParam" in cs, "квитанционного чтения сечений нет"
    assert "__sectionReceipts" in cs
    # instance_hit / type_hit — different slots, because thickness lives on the type,
    # and "read from the type" is a different fact than "read from the instance."
    assert "__fromType ? 1 : 0" in cs
    # not_applicable (the parameter does not exist at all) versus no_value (it exists, empty).
    assert "__exists ? 3 : 2" in cs
    assert "__p.StorageType != StorageType.Double" in cs
    assert "if (!__counted) __BumpSection(__name, 5)" in cs
    for name in SECTION_RECEIPT_OUTCOMES:
        assert f'"{name}"' in cs, name


def _calls_of(cs: str, helper: str) -> list[str]:
    """Chunks of text from the helper call to the end of its arguments.

    We look AT THE ARGUMENTS, not at the exact shape of the call: the three families of
    helpers have different signatures and are entitled to change, while the law — "the parameter's
    name traveled through the receipt" — is one.
    """
    out = []
    start = 0
    while True:
        i = cs.find(helper + "(", start)
        if i < 0:
            return out
        out.append(cs[i:i + 260])
        start = i + 1


@pytest.mark.parametrize("param", SECTION_PARAM_NAMES)
def test_every_section_parameter_goes_through_the_receipt_helper(param):
    """Not a single section parameter may be left on the silent
    `__PutLengthParam`: one forgotten line would bring back an indistinguishable omission."""
    cs = build_category_batch_cs("OST_Walls")
    # 🔴 THIS TEST WAS PINNING DOWN THE SIGNATURE, WHILE ITS LAW IS SOMETHING ELSE (20.08.2026).
    # It used to be: `f"{helper}(__e, BuiltInParameter.{param}"` — that is, the check was for the
    # EXACT text of a call with two arguments. Commit `00ee35f5` at 11:12 introduced a
    # third argument (`__typeEl`, so the type would be fetched once instead of forty-
    # three times), and the test went red in ALL sixteen cases at once — and was not
    # noticed, because the `decompile/tests` suite runs behind a lock and was not
    # run that day. A test that pins down the SHAPE OF THE CALL breaks on every
    # honest signature edit and thereby stops guarding its own law.
    #
    # There is exactly one law here: a section parameter must go through the RECEIPT-BEARING
    # helper (any of the three families — length, enum, reference) and must NOT
    # be left on the silent `__PutLengthParam`, which does not distinguish an omission from
    # a read refusal. The argument name and their count are not the law.
    helpers = ("__PutSectionParam", "__PutSectionIntParam",
               "__PutSectionIdParam")
    assert any(f"BuiltInParameter.{param}" in chunk
               for helper in helpers
               for chunk in _calls_of(cs, helper)), (
        f"{param} не идёт ни через один квитанционный помощник")
    assert f"__PutLengthParam(__e, BuiltInParameter.{param}" not in cs


def test_sections_are_still_read_through_the_type():
    """Thickness lives on `WallType`, diameter on the pipe's type. A receipt must not
    cancel the fallback to the type, otherwise it would neatly count zeros."""
    cs = build_category_batch_cs("OST_Walls")
    # 🔴 THE SHAPE OF THE TYPE LOOKUP CHANGED ON 20.08.2026, THE LAW DID NOT.
    # It used to be `var __type = doc.GetElement(__e.GetTypeId());` inside the reader;
    # commit `391f79f0` moved this OUTWARD (`__typeEl`), because the type was fetched
    # 43 times per element — 6.1 million extra lookups in the document. The test was pinning
    # down the line and so went red from an honest optimization.
    # The law: the fallback to the TYPE must be preserved — thickness lives on `WallType`,
    # diameter on the pipe's type, and without this a receipt would neatly count zeros.
    # 🔴 THE DOCUMENT IS NOT THE LAW, AND THIS ASSERT WAS PINNING IT DOWN. Before 25.08 here
    # stood `"doc.GetElement(__e.GetTypeId())" in cs`, and after reads were moved
    # to the source (`__src`), the check stayed GREEN — because the substring
    # survived in a COMMENT of the emitted C#. The matcher was reading the shape of the text, not the code.
    # There is one law here: the type IS LOOKED UP and the fallback to it is alive. Which document
    # is asked is the law of a neighboring guard (test_link_source), and pinning
    # it down here would mean holding two truths about one quantity.
    код = re.sub(r"//[^\n]*", "", cs)
    assert ".GetElement(__e.GetTypeId())" in код, "тип больше не ищется вовсе"
    assert "__typeEl.get_Parameter(__bip)" in код, "падения на тип больше нет"


def test_the_page_returns_its_receipts():
    cs = build_category_batch_cs("OST_PipeCurves")
    assert '{"section_receipts", __receipts}' in cs
    assert ".OrderBy(" in cs, "порядок квитанций обязан быть детерминированным"


# ── the page ───────────────────────────────────────────────────────────────

def _receipt_rows(count: int, *, slot: str = "instance_hit",
                  names=SECTION_PARAM_NAMES) -> list[dict]:
    rows = []
    for name in names:
        row = {"parameter": name}
        for outcome in SECTION_RECEIPT_OUTCOMES:
            row[outcome] = count if outcome == slot else 0
        rows.append(row)
    return rows


def _page(elements: list[dict], receipts) -> dict:
    return {"elements": elements, "has_more": False, "next_cursor": None,
            "section_receipts": receipts}


def _element(eid: str, category: str) -> dict:
    """A row in exactly the shape the bridge returns (the common fake of wave A)."""
    row = make_element(category, int(eid))
    row["level_id"] = None
    row["level_name"] = None
    return row


def test_a_page_without_receipts_is_refused():
    """A bridge that did not send receipts for a requested read is exactly the
    silent failure that receipts were introduced to prevent."""
    page = {"elements": [_element("1", "OST_Walls")], "has_more": False,
            "next_cursor": None}
    with pytest.raises(ExtractionProtocolError, match="section_receipts"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_page_whose_receipts_do_not_add_up_is_refused():
    """The census law: the sum of the six counters = the number polled."""
    page = _page([_element("1", "OST_Walls")], _receipt_rows(2))
    with pytest.raises(ExtractionProtocolError, match="не сходится"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_page_missing_one_parameter_row_is_refused():
    """A missing parameter row would mean it stopped being asked for —
    and "no section" would again become indistinguishable from "we did not ask"."""
    page = _page([_element("1", "OST_Walls")],
                 _receipt_rows(1, names=SECTION_PARAM_NAMES[:-1]))
    with pytest.raises(ExtractionProtocolError, match="параметр"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_good_page_carries_its_receipts_through():
    page = _page([_element("1", "OST_Walls")], _receipt_rows(1, slot="type_hit"))
    elements, has_more, cursor, receipts, _routes = _parse_page(
        page, category="OST_Walls", scope=_Scope("__all__", 1),
        after_element_id=None)
    assert len(elements) == 1 and has_more is False and cursor is None
    by_name = {r.parameter: r for r in receipts}
    assert by_name["WALL_ATTR_WIDTH_PARAM"].type_hit == 1
    assert by_name["WALL_ATTR_WIDTH_PARAM"].total() == 1


def test_an_empty_page_carries_no_receipt_rows():
    """A zero page polled no one — and must not assert the opposite."""
    elements, _, _, receipts, _routes = _parse_page(
        _page([], []), category="OST_Walls", scope=_Scope("__all__", 0),
        after_element_id=None)
    assert elements == () and receipts == ()


# ── the receipt as a type ──────────────────────────────────────────────────────

def test_the_six_outcomes_are_the_ones_the_review_asked_for():
    assert SECTION_RECEIPT_OUTCOMES == (
        "instance_hit", "type_hit", "not_applicable", "no_value",
        "wrong_storage", "exception")


def test_a_status_whose_receipts_contradict_its_count_is_a_schema_error():
    """The census law lives in the TYPE, not in the calling code: otherwise the very
    first new write path would bypass it."""
    good = CategoryStatus(
        category="OST_Walls", state=CategoryState.COMPLETE,
        extracted_count=3, expected_count=3,
        section_receipts=(SectionReceipt("WALL_ATTR_WIDTH_PARAM",
                                         instance_hit=1, type_hit=2),))
    assert good.section_receipts[0].total() == 3
    with pytest.raises(L0SchemaError, match="не сходится"):
        CategoryStatus(category="OST_Walls", state=CategoryState.COMPLETE,
                       extracted_count=3, expected_count=3,
                       section_receipts=(SectionReceipt(
                           "WALL_ATTR_WIDTH_PARAM", instance_hit=1),))


def test_an_older_stream_says_receipts_are_absent_instead_of_zero():
    """L0 written before this wave must say "no receipts," not
    show six zeros: a zero is an assertion it never made."""
    row = {"category": "OST_Walls", "state": "complete", "extracted_count": 2,
           "expected_count": 2, "error": None}
    assert CategoryStatus.from_dict(row).section_receipts is None
    with_receipts = CategoryStatus.from_dict({
        **row, "section_receipts": _receipt_rows(2)})
    assert len(with_receipts.section_receipts) == len(SECTION_PARAM_NAMES)


def test_receipts_survive_the_json_round_trip():
    status = CategoryStatus(
        category="OST_PipeCurves", state=CategoryState.COMPLETE,
        extracted_count=1, expected_count=1,
        section_receipts=tuple(
            SectionReceipt(name, not_applicable=1) for name in SECTION_PARAM_NAMES))
    back = CategoryStatus.from_dict(json.loads(json.dumps(status.to_dict())))
    assert back == status


# ── v13: the hypothesis "197 omissions = curtain-wall hosts", by the numbers ──────────────

@pytest.mark.skipif(not snapshot_file_exists(LIVE_V13 / "L0.jsonl"),
                    reason="живой декомпайл только на прод-боксе")
def test_v13_wall_width_gaps_coincide_exactly_with_curtain_hosts():
    """By the numbers, not by eye: 1189 walls, width present for 992, 197 omissions; curtain-wall
    hosts number exactly 197; intersection 197, the difference in BOTH directions 0.

    The match is perfect — and it is still a CORRELATION. A receipt turns it
    into a per-element diagnosis (`not_applicable` versus `no_value`/`exception`), but
    the diagnosis itself will only come with the live v14 run: in v13 there are no receipts yet.
    """
    walls = {}
    for line in open_snapshot(LIVE_V13 / "L0.jsonl", "rt", encoding="utf-8"):
        line = line.strip()
        if not line or '"OST_Walls"' not in line:
            continue
        row = json.loads(line)
        if row.get("record") != "element":
            continue
        el = row["element"]
        if el.get("category") == "OST_Walls":
            walls[str(el["element_id"])] = el
    no_width = {k for k, v in walls.items()
                if "WALL_ATTR_WIDTH_PARAM" not in (v.get("params") or {})}
    with open_snapshot(LIVE_V13 / "curtain.index.json", "rt",
                       encoding="utf-8") as handle:
        index = json.load(handle)["curtain_index"]
    curtain = {k for k, v in index.items() if v.get("curtain_available")}
    assert (len(walls), len(no_width), len(curtain)) == (1189, 197, 197)
    assert no_width == curtain, "гипотеза «пропуск ширины = витраж» опровергнута"


@pytest.mark.skipif(not snapshot_file_exists(LIVE_V13 / "L0.jsonl"),
                    reason="живой декомпайл только на прод-боксе")
def test_v13_predates_the_receipts_and_says_so():
    """v13 was written BEFORE this wave: `category_status` in it carries no receipts,
    and the reader must see `None`, not a silent zero."""
    for line in open_snapshot(LIVE_V13 / "L0.jsonl", "rt", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("record") == "category_status":
            assert CategoryStatus.from_dict(row["status"]).section_receipts is None
            return
    pytest.fail("в v13 нет ни одной строки category_status")
