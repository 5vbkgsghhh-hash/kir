"""GROUP MEMBER POSITIONS: a geometry axis that was empty for the
registry's single most expensive operation.

WHY, AS OF THE 19.08.2026 MEASUREMENT. A rehearsal (`kir/kir_plan.py`)
ran across 180 programs from the live benchmark: **4220 declared
operations unfold into 7206 elements, and 2986 of them are the content
of `create_group.members` × `placements`**. The entire frame of the
terraced tower (1822 beams, 2100 columns) is built with groups, and
`create_group`'s witness only read the COUNT of instances: `.Groups`
and `__placed`. Where those 2986 elements actually ended up — nobody
checked.

WHY THE NEW CHECK IS NOT VACUOUS, WHILE THE NEIGHBORING ONE IS ALMOST A
TAUTOLOGY. `instances` sends N placements and reads N instances. But
the position of EACH MEMBER inside a Revit copy is ITSELF DERIVED from
the group's definition: the emitter sends a single point `O0 +
delta_k` for the whole copy and says nothing about where a wall or
column will land inside it. So the expected value is derived from the
program (the definition member's position plus that copy's offset),
the actual value is read live, and an act of distinction exists —
exactly what `create_beam.level` lacked, where the level was derived
from THE SAME curve that we had sent in the first place.

THE SHAPE OF THE CHECK IS A MUTATION (discipline C5), a technique
taken from `test_witness_vacuity.py`: the witness is cut out and
replaced with a vacuum in a REAL op, and the certificate MUST refuse.
A witness that cannot be made to fail is not a witness.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_group_queue.jsonl"))

from kir import authoring                                  # noqa: E402
from kir import spec                                       # noqa: E402
from kir import translation_cert as tc                     # noqa: E402
from kir.emit_model import BarePost, WitnessCheck          # noqa: E402
from kir.tests.test_golden import PROGRAMS                 # noqa: E402

KEY = "member_positions"


def _group_op(placements=None):
    """A live, GROUNDED group op — from the golden corpus, not invented.

    Members of `create_group` must be pre-grounded (`__grounded__` selectors);
    a hand-assembled op is typedly rejected by the emitter, so the fixture is
    taken from a program that already stands as a reference.
    """
    op = None
    for candidate in PROGRAMS["native_group"]["ops"]:
        if candidate.get("op") == "create_group":
            op = dict(candidate)
            break
    assert op is not None, "в голдене native_group нет create_group"
    if placements is not None:
        op["placements"] = placements
    return op


def _emit(op):
    return authoring._emit_group(op, "2023", "kir:test")


def _plant(key: str, verdict_cs: str | None):
    """Substitute the verdict of the `key` check (or CUT it out when None)."""
    original = authoring._EMITTERS["create_group"]

    def broken(op, ver, stamp, isolation="atomic"):
        decl, create, checks, readback = original(op, ver, stamp, isolation)
        bare = isinstance(checks, BarePost)
        seq = checks.checks if bare else checks
        out = []
        for check in seq:
            if check.obligation_key != key:
                out.append(check)
                continue
            if verdict_cs is None:
                continue                      # cut out entirely
            out.append(WitnessCheck(
                obligation_key=check.obligation_key, reader_cs="",
                verdict_cs=verdict_cs, message=check.message,
                tol=None, style="plain"))
        return decl, create, (BarePost(tuple(out)) if bare else out), readback

    authoring._EMITTERS["create_group"] = broken
    return original


class TheWitnessCanBeDropped(unittest.TestCase):
    """Without mutation — proven; with mutation — must fail."""

    def test_baseline_group_is_proven(self) -> None:
        # The anchor for all mutations below. Without it they would pass for the wrong reason.
        for ver in ("2021", "2023", "2026"):
            with self.subTest(revit_version=ver):
                self.assertTrue(tc.certify_op(_group_op(), ver).proven)

    def test_cutting_the_witness_out_breaks_the_certificate(self) -> None:
        original = _plant(KEY, None)
        try:
            cert = tc.certify_op(_group_op(), "2026")
        finally:
            authoring._EMITTERS["create_group"] = original
        self.assertFalse(cert.proven, "вырезанный свидетель оставил сертификат")
        gaps = "\n".join(cert.gaps)
        self.assertIn("every member of every placement", gaps)

    def test_a_vacuous_plant_breaks_the_certificate(self) -> None:
        original = _plant(KEY, '    if (false) __post.Add("never");\n')
        try:
            cert = tc.certify_op(_group_op(), "2026")
        finally:
            authoring._EMITTERS["create_group"] = original
        self.assertFalse(cert.proven, "вакуумный саженец оставил сертификат")
        self.assertTrue(cert.vacuous, "класс вакуума не назван")
        self.assertEqual({f.obligation_key for f in cert.vacuous}, {KEY})
        self.assertEqual({f.op for f in cert.vacuous}, {"create_group"})

    def test_after_restoring_it_is_proven_again(self) -> None:
        # Otherwise the previous two could fail because the rig is broken, not
        # because of the seedling.
        self.assertTrue(tc.certify_op(_group_op(), "2026").proven)


class TheWitnessReadsWhatRevitDerives(unittest.TestCase):
    """The witness must read the copy's MEMBERS, not the argument we sent."""

    def setUp(self) -> None:
        _decl, _create, checks, self.readback = _emit(_group_op())
        seq = checks.checks if isinstance(checks, BarePost) else checks
        self.check = next(c for c in seq if c.obligation_key == KEY)
        self.cs = self.check.reader_cs + self.check.verdict_cs

    def test_it_walks_the_members_of_each_instance(self) -> None:
        # Not `__loc_*` (our argument) and not the copy's origin: specifically the members.
        self.assertIn("GetMemberIds()", self.cs)
        self.assertIn("get_BoundingBox(null)", self.cs)

    def test_the_baseline_is_the_definition_instance(self) -> None:
        # The loop starts at -1: the DEFINITION instance is itself an
        # instance, and it serves as the anchor. Taking placement #0 as the
        # anchor would mean comparing copies against one another and missing
        # it if their OWN members all drifted together.
        self.assertIn("= -1;", self.cs)
        self.assertIn("__grp_", self.cs)

    def test_the_delta_is_subtracted_not_ignored(self) -> None:
        # Conversion to the definition's coordinate system. Without
        # subtracting the offset, the check would assert that the copies
        # stand in the SAME PLACE as the definition — and would fail on every
        # correct program.
        self.assertIn("- __dx_", self.cs)
        self.assertIn("- __dy_", self.cs)
        self.assertIn("- __dz_", self.cs)

    def test_comparison_is_numeric_with_a_tolerance_not_a_string_grid(self) -> None:
        # MEASURED 14.08: equality on the grid lies at a cell boundary — the
        # witness rejected geometry that matched to 0.0000% by three metrics.
        # Hence numbers and a tolerance here, not rounding to a string.
        self.assertIn("Math.Abs(", self.cs)
        self.assertNotIn("ToString(\"F", self.cs)
        self.assertIn(str(spec.OPS["create_group"]
                          .tolerances["group_placement_mm"]), self.cs)

    def test_unreadable_bbox_is_a_refusal_not_a_skip(self) -> None:
        # Silently dropping a member would mean bearing witness over PART of
        # the subject and calling that clean — the named defect of this tree.
        self.assertIn("__gpUnread_", self.cs)
        self.assertIn("не прочитано", self.cs)

    def test_it_does_not_depend_on_revit_member_order(self) -> None:
        # `GetMemberIds()` makes no promise about order. The comparison goes
        # by NEAREST match, not by index, so the order of the return doesn't
        # matter at all. Sorting would be a second way, but its comparator is
        # a `delegate`, whose parameters the scope guard does not count as a
        # declaration: under `per_op` that's CS0103, and
        # `test_emitter_scope_contract` caught this on six versions. Hence
        # BOTH are FORBIDDEN here.
        self.assertIn("double.MaxValue", self.cs)
        self.assertNotIn("Sort(", self.cs)
        self.assertNotIn("delegate", self.cs)


class TheTolerancesProvenanceIsDeclared(unittest.TestCase):

    def test_the_number_lives_in_the_registry(self) -> None:
        # A bare number in the emitter is a "reference into the void" (a
        # create_type defect); `WitnessCheck` rejects it, and that is pinned
        # down here.
        self.assertEqual(
            spec.OPS["create_group"].tolerances["group_placement_mm"], 1000.0)

    def test_the_check_carries_the_registry_tolerance_object(self) -> None:
        _d, _c, checks, _r = _emit(_group_op())
        seq = checks.checks if isinstance(checks, BarePost) else checks
        check = next(c for c in seq if c.obligation_key == KEY)
        self.assertIsNotNone(check.tol)
        self.assertEqual(check.tol.op, "create_group")
        self.assertEqual(check.tol.key, "group_placement_mm")


class CoincidentInstancesAreCounted(unittest.TestCase):
    """The 59 duplicates across the building (measured 18.08) are derived FROM
    THE PROGRAM, not from Revit."""

    def _coincident(self, placements) -> int:
        _d, _c, _p, readback = _emit(_group_op(placements))
        line = next(l for l in readback.splitlines()
                    if "coincident_instances" in l)
        return int(line.rsplit("=", 1)[1].strip().rstrip(";"))

    def test_no_zero_delta_means_no_coincidence(self) -> None:
        self.assertEqual(self._coincident([[0, 0, 6600], [0, 0, 13200]]), 0)

    def test_a_zero_delta_coincides_with_the_definition(self) -> None:
        # The definition instance already stands at zero offset: a placement
        # with zero offset puts a SECOND group at the same point. This is
        # documented nowhere, and that is exactly how the 59 duplicates piled
        # up.
        self.assertEqual(self._coincident([[0, 0, 0], [0, 0, 6600]]), 1)

    def test_repeated_deltas_coincide_with_each_other(self) -> None:
        self.assertEqual(
            self._coincident([[0, 0, 6600], [0, 0, 6600], [0, 0, 13200]]), 1)

    def test_the_count_never_pretends_to_be_a_refusal(self) -> None:
        # A NUMBER IN THE RECEIPT, NOT A REFUSAL: the benchmark programs are
        # written exactly this way, and a refusal would break what is already
        # written. The decision is to name it, not forbid it.
        _d, _c, checks, _r = _emit(_group_op([[0, 0, 0]]))
        seq = checks.checks if isinstance(checks, BarePost) else checks
        joined = "".join(c.verdict_cs for c in seq)
        self.assertNotIn("coincident", joined)


if __name__ == "__main__":
    unittest.main()
