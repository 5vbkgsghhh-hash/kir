"""Sections in extraction: without them the clash detector builds only bounding boxes.

Measurement D1 on the SOB6.2 facade (v10): 2754 shells, of which exact — ZERO, because
neither the wall thickness nor the pipe diameter was present in the decompile artifacts. Pipe and
duct have been captured for a long time; what was missing was wall thickness — and it lives not on
the wall, but on its TYPE.

Names are checked against RevitAPI.xml (`/root/27B/sdk/nuget_extracted/ref/net8.0/`), not
from memory: the enum carries `WALL_ATTR_WIDTH_PARAM`, while the member
`WALL_ATTR_WIDTH` (as it is called out of habit) does NOT EXIST in the API AT ALL — emission with
it would not build on any version.

NOT VERIFIED LIVE: the measurement awaits the v12 rebuild.
"""
from __future__ import annotations

import re

import pytest

from kir.decompile.extract import build_category_batch_cs

#: The sections that must be captured. The key is the name in the `params` of the L0 row.
SECTION_PARAMS = (
    "WALL_ATTR_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
)


#: One section call: the enum member and the LABEL under which the number will land
#: in `params`. Both are captured separately — it is exactly their equality that is
#: the subject of the check.
#: 🔴 THE SHAPE OF THE CALL IS NOT THE LAW, THE LAW IS THE EQUALITY OF THE MEMBER AND THE LABEL.
#: Here stood a regex for exactly TWO arguments
#: (`__PutSectionParam(__e, BuiltInParameter.X, nameof(...), __params);`).
#: On 20.08.2026 commit `391f79f0` introduced a third argument `__typeEl` — the type was being fetched
#: 43 times per element instead of once, 6.1 million extra lookups in the document —
#: and the regex stopped finding ANYTHING: `section_calls(cs)` returned an empty
#: list, and the tests went red as a whole set. Yet not a single check
#: described the real defect: the emission was correct, the instrument was lying.
#: Also, the number of helper families became three (length, enum, reference), and
#: the law is the same for all of them.
_SECTION_CALL = re.compile(
    r"__PutSection(?:Int|Id)?Param\(\s*__e\s*,\s*(?:__typeEl\s*,\s*)?"
    r"BuiltInParameter\.(\w+)\s*,\s*"
    r"nameof\(BuiltInParameter\.(\w+)\)")


def section_calls(cs: str) -> list[tuple[str, str]]:
    """Pairs (member, label) across all section calls in the emission."""
    return [(m.group(1), m.group(2)) for m in _SECTION_CALL.finditer(cs)]


@pytest.mark.parametrize("param", SECTION_PARAMS)
def test_the_emission_asks_for_every_section_parameter(param):
    cs = build_category_batch_cs("OST_Walls")
    assert f"BuiltInParameter.{param}" in cs, param
    assert (param, param) in section_calls(cs), (
        f"{param}: нет вызова, где член и ярлык — ОДИН И ТОТ ЖЕ")


def test_no_section_call_labels_a_member_with_another_members_name():
    """WHAT IS NOW CHECKED HERE, AND WHAT BECAME IMPOSSIBLE (12.08.2026).

    Before the `nameof` fix the label was a STRING LITERAL in quotes, and the test looked for
    the spelling: `assert f'"{param}"' in cs`. The literal could diverge from the member
    silently — 38 such pairs were exactly the subject of the check.

    `nameof(BuiltInParameter.X)` takes the name FROM THE C# COMPILER: a typo in
    the label no longer compiles, and renaming the member travels together with
    it. **The discrepancy "the label is spelled wrong" became IMPOSSIBLE.** The previous
    test reported this strengthening as a loss — the instrument was tied to
    SPELLING and cannot tell a strengthening from a weakening apart.

    But there is one hole `nameof` does NOT close, and it is held here: nothing in
    the language stops writing `__PutSectionParam(__e, BuiltInParameter.A,
    nameof(BuiltInParameter.B), ...)` — both arguments are legal, the C#
    will compile, and the number will land in `params` under the WRONG name. The check
    is closed for ALL calls in the emission, not only for the eleven from
    SECTION_PARAMS: the rest (for example RBS_PIPE_OUTER_DIAMETER) have the same
    possibility.

    Do NOT "simplify" back to a literal: a literal would remove the `nameof` guarantee
    while looking like a fix to the test.
    """
    calls = section_calls(build_category_batch_cs("OST_Walls"))
    assert calls, "вызовов сечений не найдено — регулярка разошлась с эмиссией"
    mismatched = [(bip, label) for bip, label in calls if bip != label]
    assert not mismatched, (
        f"член и ярлык названы РАЗНЫМИ параметрами: {mismatched}")


def test_the_mismatch_check_is_a_check_and_not_an_ornament():
    """A FAIL control and a PASS control for the check above.

    Without this pair, a `section_calls` that has lost the ability to parse the call would return
    an empty list — and the "no discrepancies" check would become vacuously green,
    looking exactly like normal work.
    """
    good = ("__PutSectionParam(__e, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,\n"
            "                 nameof(BuiltInParameter.WALL_ATTR_WIDTH_PARAM), __params);")
    bad = ("__PutSectionParam(__e, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,\n"
           "                 nameof(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM), __params);")
    # control-PASS: identical names are read as a pair and recognized as equal
    assert section_calls(good) == [
        ("WALL_ATTR_WIDTH_PARAM", "WALL_ATTR_WIDTH_PARAM")]
    # control-FAIL: a member and a label from DIFFERENT parameters must be visible
    parsed = section_calls(bad)
    assert parsed == [("WALL_ATTR_WIDTH_PARAM", "RBS_PIPE_DIAMETER_PARAM")]
    assert [p for p in parsed if p[0] != p[1]], (
        "подменённый ярлык не отличён от верного — проверка стала украшением")


def test_the_wall_width_parameter_is_the_one_that_exists_in_the_api():
    """`WALL_ATTR_WIDTH` — a name that does not exist in the enum. The test holds the
    boundary between habit and the API: with the wrong member the C# would not build."""
    cs = build_category_batch_cs("OST_Walls")
    assert "BuiltInParameter.WALL_ATTR_WIDTH_PARAM" in cs
    assert "BuiltInParameter.WALL_ATTR_WIDTH," not in cs


def test_sections_are_read_through_the_type_falling_back_helper():
    """Thickness lives on WallType, diameter on the pipe's type. Reading them directly off the
    instance means not reading them at all, so every section goes through a
    helper that itself falls back to the type.

    The D2-A wave moved sections from the silent `__PutLengthParam` to
    `__PutSectionParam` (codex review #12): the fallback to the type stayed, but now
    every outcome has a receipt. The check for the new helper is
    `test_sections_receipts.py`; here only the fallback to the type is held.
    """
    cs = build_category_batch_cs("OST_Walls")
    # 🔴 THE SHAPE OF THE TYPE LOOKUP CHANGED ON 20.08.2026 (commit `391f79f0`: the type was fetched
    # 43 times per element), the law did not. We hold the LAW: the type is looked up and the fallback
    # to it is alive; the variable name and the call site are not the law.
    # 🔴 THE DOCUMENT IS NOT THE LAW, AND THIS ASSERT WAS PINNING IT DOWN. Before 25.08 here
    # stood `"doc.GetElement(__e.GetTypeId())" in cs`, and after reads were moved
    # to the source (`__src`), the check stayed GREEN — because the substring
    # survived in a COMMENT of the emitted C#. The matcher was reading the shape of the text, not the code.
    # There is one law here: the type IS LOOKED UP and the fallback to it is alive. Which document
    # is asked is the law of a neighboring guard (test_link_source), and pinning
    # it down here would mean holding two truths about one quantity.
    код = re.sub(r"//[^\n]*", "", cs)
    assert ".GetElement(__e.GetTypeId())" in код, "тип больше не ищется"
    assert "__typeEl.get_Parameter(__bip)" in код, "падения на тип больше нет"
    for param in SECTION_PARAMS:
        assert (param, param) in section_calls(cs), (
            f"{param} не идёт через квитанционный помощник")


def test_a_missing_parameter_is_absence_not_failure():
    """Fail-open: `__PutLengthParam` puts a number only if the parameter exists.
    An element without a section must give a record WITHOUT a number, not fail extraction —
    otherwise the very first family wall without the parameter would stop the decompile."""
    cs = build_category_batch_cs("OST_Walls")
    assert "try" in cs and "catch { }" in cs
    # 🔴 THE HELPER'S EARLY RETURN WAS REWRITTEN BY THE SAME COMMIT. The law here is
    # fail-open: a missing parameter gives a RECORD WITHOUT A NUMBER, not a failure of
    # extraction (otherwise the very first family wall without a section would stop the decompile).
    # We check the law itself, not the line: an empty parameter has its own outcome
    # (`not_applicable`/`no_value`), and the exception is caught, not propagated.
    assert "__exists ? 3 : 2" in cs, "нет различения «нет параметра» и «пуст»"
    assert "if (!__counted) __BumpSection(__name, 5)" in cs, (
        "исключение чтения больше не даёт своего исхода — fail-open потерян")


@pytest.mark.parametrize("category", ["OST_Walls", "OST_PipeCurves",
                                      "OST_DuctCurves", "OST_CableTray",
                                      "OST_StructuralColumns"])
def test_every_section_bearing_category_gets_the_same_block(category):
    """The block is common to all categories: the section is asked of every one, and
    absence is a fact about a specific element, not about the category."""
    cs = build_category_batch_cs(category)
    assert "BuiltInParameter.WALL_ATTR_WIDTH_PARAM" in cs
    assert "BuiltInParameter.RBS_PIPE_DIAMETER_PARAM" in cs
