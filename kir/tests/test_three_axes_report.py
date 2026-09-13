"""THREE AXES OF THE RELEASE CRITERION — AND "NOT JUDGED" DOES NOT LOOK LIKE "CLEAN".

THE MEASUREMENT THAT PAID FOR THIS FILE (18.08.2026, the owner's tower
`13A-RD-AR-K2_v33`, 115,889 L0 elements). The first run in this project's
history against the criterion the owner declared on 17.08:

    axis          judged  found  SILENT   clean among judged
    GEOMETRY          4      3       2   25% (1 of 4)
    MEANING            3      3       2    0% (0 of 3)
    TOPOLOGY           2      2       7    0% (0 of 2)
    TOTAL              9      8      11

🔴 9 RULES OUT OF 20 SPOKE UP. Had the report printed one number per
axis instead of three, the topology axis on this building would have
looked like "few violations" — while SEVEN of its nine rules never
judged at all. A zero in a quantity the instrument does not compute here,
passed off as success, is a named defect of this tree, and the report by
axis would be its most expensive carrier: it is declared the RELEASE
CRITERION.

Hence the subject of these tests: not "does the report count", but
**is silence distinguishable from cleanliness** — in the numbers, in the
share, and in the text.

Run:
    venv/bin/python -m pytest kir/tests/test_three_axes_report.py -q
"""
from __future__ import annotations

import unittest

from kir import design_check as D


class TheAxisMapIsClosedOverBothRegistries(unittest.TestCase):
    """A rule with no axis would vanish from the report SILENTLY — and this cannot be noticed from the report."""

    def _known_rules(self) -> set[str]:
        from kir.checker.engine import RULE_SPECS_V2
        from kir.checker.rules import consistency
        return ({s.rule_id for s in RULE_SPECS_V2}
                | {rid for rid, _ in consistency.CONSISTENCY_REGISTRY})

    def test_every_rule_of_both_registries_has_an_axis(self):
        known = self._known_rules()
        self.assertEqual(
            sorted(known - set(D._RULE_AXIS)), [],
            "правило без оси не попадёт НИ В ОДНУ строку отчёта")
        self.assertEqual(
            sorted(set(D._RULE_AXIS) - known), [],
            "ось названа правилу, которого нет ни в одном реестре — карта стала "
            "вторым экземпляром вместо реестра под другим углом")

    def test_two_registries_are_both_covered_and_neither_is_empty(self):
        """Control against a green-by-construction: if the second registry
        were not read at all, the previous test would still pass on the
        first alone."""
        from kir.checker.engine import RULE_SPECS_V2
        from kir.checker.rules import consistency
        geom = {s.rule_id for s in RULE_SPECS_V2}
        cons = {rid for rid, _ in consistency.CONSISTENCY_REGISTRY}
        self.assertTrue(geom and cons, "реестр пуст — покрытие проверять не на чем")
        self.assertFalse(geom & cons, "реестры пересеклись: правило судится дважды")
        self.assertLessEqual(geom | cons, set(D._RULE_AXIS))

    def test_the_lint_can_actually_fail(self):
        """FAIL CONTROL built in: remove a rule from the map — the lint must scream."""
        saved = dict(D._RULE_AXIS)
        victim = sorted(self._known_rules())[0]
        try:
            D._RULE_AXIS.pop(victim)
            with self.assertRaises(AssertionError) as caught:
                D._lint_axis_map()
            self.assertIn(victim, str(caught.exception))
        finally:
            D._RULE_AXIS.clear()
            D._RULE_AXIS.update(saved)
        D._lint_axis_map()   # a restoration must be silent

    def test_every_axis_is_one_of_the_three_declared(self):
        self.assertLessEqual(set(D._RULE_AXIS.values()), set(D.AXES))
        self.assertEqual(len(D.AXES), 3)


class _Row:
    """A minimal coverage row — exactly the fields the report reads."""

    class _S:
        def __init__(self, value: str) -> None:
            self.value = value

    def __init__(self, rule_id: str, status: str, reason: str = "",
                 n_subjects: int = 0, excluded_subjects: int = 0) -> None:
        self.rule_id, self.status = rule_id, self._S(status)
        self.reason, self.n_subjects = reason, n_subjects
        self.excluded_subjects = excluded_subjects


class _Finding:
    def __init__(self, rule_id: str) -> None:
        self.rule_id = rule_id


class _Verdict:
    """A `DesignVerdict` fake, matching exactly the surface the report reads."""

    def __init__(self, rows, findings=()) -> None:
        class _Cov:
            def __init__(self, outcomes): self.outcomes = outcomes

        class _Rep:
            def __init__(self, outcomes, findings):
                self.coverage = _Cov(outcomes)
                self.blocking = list(findings)
                self.warnings, self.info = [], []

        class _Src:
            value = "parse"

        self.report = _Rep(rows, findings)
        self.building_id, self.source = "тест", _Src()


class SilenceIsNotCleanliness(unittest.TestCase):

    def test_an_axis_nobody_judged_has_NO_share_at_all(self):
        """🔴 The heart of the file. A share over an empty denominator is neither 100% nor 0%."""
        rows = [_Row(r, "not_evaluated", "предусловие не выполнено")
                for r, a in D._RULE_AXIS.items() if a == "topological"]
        report = {o.axis: o for o in D.axis_report(_Verdict(rows))}
        topo = report["topological"]
        self.assertEqual(topo.judged, ())
        self.assertIsNone(
            topo.clean_share,
            "ось, где не судил НИКТО, получила долю — значит отсутствие ответа "
            "надело костюм ответа")
        self.assertEqual(len(topo.silent), len(rows))

    def test_the_text_says_nobody_judged_and_never_prints_a_percentage_there(self):
        rows = [_Row(r, "not_evaluated", "нет входа") for r in D._RULE_AXIS]
        text = D.render_axis_report(_Verdict(rows))
        self.assertIn("не судил НИКТО", text)
        self.assertIn("ПРАВИЛ ВЫСКАЗАЛОСЬ 0 ИЗ %d" % len(rows), text)
        # THE PERCENTAGE IS LOOKED FOR IN THE TABLE'S ROWS, NOT IN THE
        # WHOLE TEXT. The first edition searched for "100%" across the
        # entire report and went red on the CORRECT explanatory line
        # «там прочерк, а не 100%» — the probe matched the LABEL, not the
        # subject (form 7). The subject is the axis row.
        table = [ln for ln in text.splitlines()
                 if any(ln.startswith(name) for name in D._AXIS_RU.values())]
        self.assertEqual(len(table), 3, "строк осей в таблице не три: %r" % table)
        for line in table:
            self.assertNotIn("%", line,
                             "ось без единого судившего правила напечатала "
                             "ПРОЦЕНТ: %r" % line)

    def test_a_silent_rule_never_lands_among_the_judged(self):
        rows = [_Row("HAB021", "evaluated", n_subjects=7),
                _Row("HAB022", "not_evaluated", "высота не прочитана")]
        geom = {o.axis: o for o in D.axis_report(_Verdict(rows))}["geometric"]
        self.assertEqual(geom.judged, ("HAB021",))
        self.assertEqual([r for r, _ in geom.silent], ["HAB022"])
        self.assertEqual(geom.subjects, 7,
                         "предметы молчавшего правила попали в счёт осмотренных")

    def test_the_reason_for_silence_is_carried_never_dropped(self):
        rows = [_Row("HAB050", "not_evaluated", "несущие стены не помечены")]
        topo = {o.axis: o for o in D.axis_report(_Verdict(rows))}["topological"]
        self.assertEqual(topo.silent, (("HAB050", "несущие стены не помечены"),))

    def test_a_silent_rule_without_a_reason_says_so_instead_of_empty(self):
        rows = [_Row("HAB050", "not_evaluated", "")]
        topo = {o.axis: o for o in D.axis_report(_Verdict(rows))}["topological"]
        self.assertEqual(topo.silent[0][1], "причина не названа")

    def test_findings_are_counted_per_axis_and_only_for_judged_rules(self):
        rows = [_Row("HAB021", "evaluated", n_subjects=3),
                _Row("HAB040", "evaluated", n_subjects=5),
                _Row("HAB020", "evaluated", n_subjects=2)]
        findings = [_Finding("HAB021"), _Finding("HAB021"), _Finding("HAB020")]
        report = {o.axis: o for o in D.axis_report(_Verdict(rows, findings))}
        self.assertEqual(report["geometric"].violated, ("HAB021",))
        self.assertEqual(report["geometric"].findings, 2)
        self.assertEqual(report["semantic"].violated, ("HAB020",))
        self.assertAlmostEqual(report["geometric"].clean_share, 0.5)

    def test_all_three_axes_appear_even_when_a_registry_is_silent(self):
        """A skipped axis would read as "no such axis", not "nothing to say"."""
        got = tuple(o.axis for o in D.axis_report(_Verdict([])))
        self.assertEqual(got, D.AXES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
