"""D6: category upper-bound coverage reports enforced group contracts.

AT_LEAST remains a lawful lower-bound expectation. This does not add an
invented upper bound or claim geometric/level checks that were not available.
"""
from dataclasses import replace

from kir.acceptance import (
    Certainty, Expectation, ExpectedRow, MismatchCode,
    check_acceptance, derive_expectation,
)
from kir.compiler import plan_program
from kir.tests.test_golden import PROGRAMS


def row(category, certainty=Certainty.EXACT, count=1):
    return ExpectedRow((category,), None, count, certainty, (category,))


def expectation(*rows, derived=(), upper_valid=True):
    return Expectation(tuple(rows), tuple(derived), (), upper_valid, len(rows))


def test_real_hosted_railing_can_pass_a_lower_bound_without_an_upper_claim():
    program = PROGRAMS["arch_railing_hosted"]
    assert plan_program(program)
    expected = derive_expectation(program)
    assert expected.upper_bounds_valid and expected.rows[0].certainty is Certainty.AT_LEAST
    category = expected.rows[0].categories[0]
    verdict = check_acceptance(expected, {}, {(category, ""): 1_000_000})
    assert verdict.accepted  # overshoot is not prohibited by AT_LEAST
    assert verdict.checked_groups == 1
    assert verdict.upper_bounds_checked is False
    assert verdict.upper_bound_coverage == "none"
    assert verdict.to_dict()["upper_bound_groups"] == []
    assert "верхние границы не проверялись" in verdict.summary_ru()


def test_exact_group_rejects_overshoot_and_names_its_actual_scope():
    verdict = check_acceptance(expectation(row("OST_Walls")), {}, {("OST_Walls", ""): 2})
    assert not verdict.accepted
    assert MismatchCode.CATEGORY_OVERSHOOT in {m.code for m in verdict.mismatches}
    assert verdict.upper_bounds_checked
    assert verdict.upper_bound_coverage == "full"
    assert verdict.upper_bound_groups == (("OST_Walls",),)


def test_mixed_scope_does_not_turn_partial_upper_coverage_into_full():
    expected = expectation(row("OST_Walls"), row("OST_StairsRailing", Certainty.AT_LEAST))
    verdict = check_acceptance(expected, {}, {("OST_Walls", ""): 1, ("OST_StairsRailing", ""): 100})
    assert verdict.accepted and verdict.checked_groups == 2
    assert not verdict.upper_bounds_checked
    assert verdict.upper_bound_coverage == "partial"
    assert verdict.to_dict()["upper_bound_groups"] == [["OST_Walls"]]
    assert "только для 1 из 2 групп" in verdict.summary_ru()
    wrong = check_acceptance(expected, {}, {("OST_Walls", ""): 2, ("OST_StairsRailing", ""): 100})
    assert not wrong.accepted


def test_derived_category_loses_only_its_upper_bound():
    expected = expectation(row("OST_Walls"), row("OST_StairsRailing"), derived=("OST_StairsRailing",))
    verdict = check_acceptance(expected, {}, {("OST_Walls", ""): 1, ("OST_StairsRailing", ""): 100})
    assert verdict.accepted and verdict.upper_bound_coverage == "partial"
    assert verdict.upper_bound_groups == (("OST_Walls",),)


def test_globally_ineligible_upper_bounds_never_claim_local_coverage():
    verdict = check_acceptance(expectation(row("OST_Walls"), upper_valid=False), {}, {("OST_Walls", ""): 100})
    assert verdict.accepted and not verdict.upper_bounds_checked
    assert verdict.upper_bound_coverage == "none"


def test_unknown_and_zero_only_groups_do_not_vacuously_check_an_upper_bound():
    for expected in (expectation(), expectation(row("OST_Walls", Certainty.UNKNOWN)),
                     expectation(row("OST_Walls", count=0))):
        verdict = check_acceptance(expected, {}, {})
        assert not verdict.accepted and verdict.vacuous
        assert not verdict.upper_bounds_checked and verdict.upper_bound_coverage == "none"


def test_overlapping_categories_report_one_merged_upper_bound_scope():
    wall_or_floor = ExpectedRow(("OST_Walls", "OST_Floors"), None, 1, Certainty.EXACT, ("either",))
    expected = expectation(row("OST_Walls"), wall_or_floor)
    verdict = check_acceptance(expected, {}, {("OST_Walls", ""): 2})
    assert verdict.accepted and verdict.checked_groups == 1
    assert verdict.upper_bound_groups == (("OST_Floors", "OST_Walls"),)
    weaker = replace(expected, rows=(expected.rows[0], replace(wall_or_floor, certainty=Certainty.AT_LEAST)))
    other = check_acceptance(weaker, {}, {("OST_Walls", ""): 1_000})
    assert other.accepted and not other.upper_bounds_checked


def test_no_group_checked_when_mutation_invalidates_net_lower_bounds():
    expected = derive_expectation({"allow_destructive": True, "ops": [
        {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "element_id", "value": 1}},
        {"op": "delete", "id": "D", "target": {"by": "element_id", "value": 2}},
    ]})
    assert not expected.lower_bounds_valid
    verdict = check_acceptance(expected, {}, {})
    assert verdict.checked_groups == 0 and not verdict.upper_bounds_checked
    assert verdict.upper_bound_coverage == "none"
