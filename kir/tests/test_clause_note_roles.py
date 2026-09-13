"""THE ROLE OF THE `_CLAUSE_NOTES` RECORD — AND WHY THERE IS NO SINGLE CHECK
FOR THE WHOLE TABLE.

THE 22.08.2026 MEASUREMENT THAT STARTED ALL OF THIS. The table of
non-witnessable clauses has 26 records for 18 ops. For FIVE of them the
marker never occurred in any clause of `OpSpec.post` of its own op:

    create_building_pad      "boundary vertex multiset"
    create_site_subregion    "boundary vertex multiset"
    create_ceiling           "contour bbox when a ring carries a spline"
    create_floor_by_contour  "contour bbox when a ring carries a spline"
    create_stairs            «недобор подступенков»

As an audit exclusion they did not work — there was nothing to exclude —
while models kept being presented as before: `named_absences` returns the
string without asking whether the clause is alive. THE SILENCE WAS
TWO-SIDED.

🔴 THE MAIN THING THE ANALYSIS FOUND: THIS IS NOT FIVE STALE MARKERS, BUT
THREE DIFFERENT ROLES. Verified by history (`git log -S` across every
`ops_*.py`, where `post` actually lives): not one of the three lines EVER
stood in `post` — in any commit. That is, the marker was not "reworded":
from birth it addressed not a clause but something else, and the table held
three different subjects under one name.

    RELEASE   the clause EXISTS, there is no obligation and none is owed  -> exactly 1
    ABSENCE   the clause DOES NOT EXIST: the op deliberately promises nothing -> exactly 0
    CAVEAT    the obligation EXISTS and is alive; its BOUNDARY is named    -> 0 + a key

Three correct answers to one question — that is exactly why there could be
no single guard role: any one unified check would accuse two-thirds of the
table.

WHAT THIS FILE HOLDS:

    L1  a census of roles by name (not by number: a number does not say WHAT
        changed);
    L2  the `_NON_WITNESSABLE_CLAUSES` projection cannot drift apart from
        the literal;
    L3  only a RELEASE extinguishes a clause — by mutation;
    L4  a FAIL CONTROL for each of the seven refusals of `audit_clause_notes`;
    L5  the finding REACHES a live consumer (`audit_registry_coverage`);
    L6  the role reaches the MODEL, and a caveat is no longer called
        «не смотрели»;
    L7  a check against the subject: `audit_clause_axis_credit` + a frozen
        baseline + a FAIL control.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_roles_queue.jsonl"))

from kir import spec                                       # noqa: E402
from kir import translation_cert as tc                     # noqa: E402


class _PostOverride:
    """A proxy `OpSpec` with a substituted `post` — everything else is
    delegated to the real one.

    The `OpSpec` itself cannot be substituted: it is frozen+slots, and a
    full copy would carry the test away from its subject. The proxy changes
    EXACTLY the value the mutation is about.
    """

    def __init__(self, real, post: str) -> None:
        self._real = real
        self.post = post

    def __getattr__(self, name):                                # noqa: D105
        return getattr(self._real, name)


def _with_post(op: str, post: str):
    return mock.patch.dict(spec.OPS, {op: _PostOverride(spec.OPS[op], post)})


def _with_notes(op: str, notes: tuple):
    return mock.patch.dict(tc._CLAUSE_NOTES, {op: notes})


class TheRoleCensus(unittest.TestCase):
    """L1. By name, not by number."""

    #: Five records, analyzed on 22.08.2026 — each with its OWN outcome.
    #: The list is named so that a regression is visible by subject, not by
    #: counter: «стало четыре» does not say which record moved, or where.
    MEASURED = {
        # There IS NO clause AND THERE SHOULD NOT BE ONE: `GetBoundary()` is
        # not measured, and a vertex witness on an unsettled representation
        # risks a FALSE RED. Neighbors from wave 84f54b69 got a witness,
        # these two did not, deliberately.
        ("create_building_pad", "boundary vertex multiset"): tc.NOTE_ABSENCE,
        ("create_site_subregion", "boundary vertex multiset"): tc.NOTE_ABSENCE,
        # The `bbox` obligation IS ALIVE and does discharge; its BOUNDARY is
        # named — the gate `unless_kind_in=("contour","spline")`, introduced
        # by the same commit, 96f53f07, as the record itself.
        ("create_ceiling", "contour bbox when a ring carries a spline"): tc.NOTE_CAVEAT,
        ("create_floor_by_contour", "contour bbox when a ring carries a spline"): tc.NOTE_CAVEAT,
        # The `vertical_extent` obligation IS ALIVE; the guard is
        # one-sided, and the record names exactly that one-sidedness.
        ("create_stairs", "недобор подступенков"): tc.NOTE_CAVEAT,
    }

    def test_the_five_are_not_exemptions(self) -> None:
        for (op, marker), role in sorted(self.MEASURED.items()):
            with self.subTest(op=op, marker=marker):
                got = [r for m, _w, r, _k in tc._CLAUSE_NOTES[op] if m == marker]
                self.assertEqual(got, [role])

    def test_a_caveat_names_a_key_and_the_others_do_not(self) -> None:
        for op, notes in sorted(tc._CLAUSE_NOTES.items()):
            for marker, _why, role, key in notes:
                with self.subTest(op=op, marker=marker):
                    self.assertIn(role, tc.NOTE_ROLES)
                    if role == tc.NOTE_CAVEAT:
                        self.assertTrue(key, "оговорка без ключа не проверяема")
                    else:
                        self.assertIsNone(key)

    def test_the_dead_markers_stay_dead_on_purpose(self) -> None:
        """Not one of the five markers is obligated to land in a clause.

        This is an assertion, not an observation: if tomorrow `post` starts
        to contain such a line, the role must change, and
        `audit_clause_notes` will say so (see L4). What is pinned here is
        the 22.08.2026 MEASUREMENT as such.
        """
        for (op, marker), _role in sorted(self.MEASURED.items()):
            with self.subTest(op=op, marker=marker):
                post = (spec.OPS[op].post or "").lower()
                self.assertNotIn(marker.lower(), post)


class TheProjectionCannotDriftFromTheLiteral(unittest.TestCase):
    """L2. There is ONE carrier, everything else is a view onto it."""

    def test_projection_is_the_literal_with_the_role_folded_into_why(self) -> None:
        expected = {op: tuple((m, tc._absence_why_ru(w, r, k))
                              for m, w, r, k in notes)
                    for op, notes in tc._CLAUSE_NOTES.items()}
        self.assertEqual(tc._NON_WITNESSABLE_CLAUSES, expected)

    def test_the_raw_reason_survives_inside_the_labelled_one(self) -> None:
        """The label ADDS, it does not replace: the reason is the entire
        value of the record."""
        for op, notes in tc._CLAUSE_NOTES.items():
            labelled = dict(tc._NON_WITNESSABLE_CLAUSES[op])
            for marker, why, _r, _k in notes:
                with self.subTest(op=op, marker=marker):
                    self.assertIn(why, labelled[marker])

    def test_exempt_markers_are_exactly_the_exempt_role(self) -> None:
        for op, notes in tc._CLAUSE_NOTES.items():
            with self.subTest(op=op):
                self.assertEqual(
                    tc._EXEMPT_MARKERS[op],
                    tuple(m for m, _w, r, _k in notes if r == tc.NOTE_EXEMPT))


class OnlyAnExemptionSilencesAClause(unittest.TestCase):
    """L3. BY MUTATION, not by reading.

    Before 22.08, the role had no effect at all on the outcome of
    `audit_registry_coverage`: ANY record whose text happened to land in the
    clause extinguished it. What is checked is that the very same string, in
    the role of a RELEASE, extinguishes it, while in the role of an ABSENCE,
    it does not.
    """

    OP = "create_room"
    MARKER = "placed after"

    def test_as_an_exemption_the_clause_is_silenced(self) -> None:
        self.assertEqual(tc.audit_registry_coverage(), ())

    def test_as_an_absence_the_same_string_stops_silencing(self) -> None:
        why = "control-FAIL: та же строка в другой роли"
        with _with_notes(self.OP, (tc._absence(self.MARKER, why),)):
            with mock.patch.dict(
                    tc._EXEMPT_MARKERS, {self.OP: ()}):
                problems = tc.audit_registry_coverage()
        self.assertTrue(
            any(self.OP in p and "not witnessed" in p for p in problems),
            f"клауза обязана снова потребовать обязательства: {problems}")


class AuditClauseNotesControlFail(unittest.TestCase):
    """L4. Seven refusals — seven mutations. A guard without a FAIL control
    is not a guard."""

    def _problems(self, op, notes, post=None):
        ctx = _with_notes(op, notes)
        if post is None:
            with ctx:
                return tc.audit_clause_notes()
        with ctx, _with_post(op, post):
            return tc.audit_clause_notes()

    def test_the_live_tree_is_clean(self) -> None:
        self.assertEqual(tc.audit_clause_notes(), ())

    def test_dead_exemption_marker(self) -> None:
        got = self._problems(
            "create_room",
            (tc._exempt("no such clause anywhere", "control-FAIL, мёртвый маркер"),))
        self.assertTrue(any("DEAD exemption marker" in p for p in got), got)

    def test_ambiguous_exemption_marker(self) -> None:
        """The other half of the substring's weakness: the marker
        extinguishes its NEIGHBOR too."""
        got = self._problems(
            "create_room",
            (tc._exempt("room", "control-FAIL, маркер перестал различать"),),
            post="room exists (materialize); room is placed after (topology)")
        self.assertTrue(any("AMBIGUOUS exemption marker" in p for p in got), got)

    def test_a_named_absence_that_became_a_promise(self) -> None:
        got = self._problems(
            "create_building_pad",
            (tc._absence("boundary vertex multiset", "control-FAIL"),),
            post=(spec.OPS["create_building_pad"].post
                  + "; boundary vertex multiset == contour (geometry)"))
        self.assertTrue(any("is now PROMISED" in p for p in got), got)

    def test_a_caveat_that_matches_a_clause(self) -> None:
        got = self._problems(
            "create_stairs",
            (tc._caveat("vertical_extent", "недобор подступенков", "control-FAIL"),),
            post=spec.OPS["create_stairs"].post + "; недобор подступенков (geometry)")
        self.assertTrue(any("does not exempt a clause" in p for p in got), got)

    def test_a_caveat_whose_obligation_key_is_gone(self) -> None:
        got = self._problems(
            "create_stairs",
            (tc._caveat("no_such_key", "недобор подступенков", "control-FAIL"),))
        self.assertTrue(any("does not exist" in p for p in got), got)

    def test_an_unknown_role(self) -> None:
        got = self._problems(
            "create_room", (("placed after", "control-FAIL", "vibes", None),))
        self.assertTrue(any("unknown role" in p for p in got), got)

    def test_a_note_for_an_op_outside_the_registry(self) -> None:
        with mock.patch.dict(
                tc._CLAUSE_NOTES,
                {"create_hovercraft": (tc._exempt("x", "control-FAIL"),)}):
            got = tc.audit_clause_notes()
        self.assertTrue(any("outside the registry" in p for p in got), got)


class TheFindingReachesItsConsumer(unittest.TestCase):
    """L5. A finding with no reader is exactly the class of defect that was
    found.

    `audit_registry_coverage` already reads `op_contract.py`. What is
    checked is that a refusal from the role table reaches there, rather
    than staying inside a separate function that nobody calls.
    """

    def test_a_dead_marker_shows_up_in_the_registry_audit(self) -> None:
        with _with_notes(
                "create_room",
                (tc._exempt("no such clause anywhere", "control-FAIL"),)):
            problems = tc.audit_registry_coverage()
        self.assertTrue(
            any("DEAD exemption marker" in p for p in problems),
            f"находка не доехала до живого потребителя: {problems}")

    def test_op_contract_kernel_carries_it_too(self) -> None:
        from kir import op_contract
        self.assertEqual(op_contract.audit_contract_kernel(), ())
        with _with_notes(
                "create_room",
                (tc._exempt("no such clause anywhere", "control-FAIL"),)):
            problems = op_contract.audit_contract_kernel()
        self.assertTrue(any("DEAD exemption marker" in p for p in problems),
                        problems)


class TheRoleReachesTheModel(unittest.TestCase):
    """L6. «Сюда никто не смотрел» is a LIE when said about a caveat."""

    def test_a_caveat_is_not_reported_as_unlooked_at(self) -> None:
        rows = tc.named_absences(["create_stairs"])["create_stairs"]
        why = dict(rows)["недобор подступенков"]
        self.assertIn("свидетель ЕСТЬ", why)
        self.assertIn("vertical_extent", why,
                      "оговорка обязана НАЗЫВАТЬ обязательство, чью границу "
                      "описывает, иначе читатель не может её проверить")
        self.assertNotIn("никто не смотрел", why)

    def test_an_absence_still_says_nobody_looked(self) -> None:
        rows = tc.named_absences(["create_building_pad"])["create_building_pad"]
        why = dict(rows)["boundary vertex multiset"]
        self.assertIn("никто не смотрел", why)

    def test_an_exemption_says_promised_without_a_witness(self) -> None:
        rows = tc.named_absences(["create_wall_sweep"])["create_wall_sweep"]
        why = dict(rows)["named weaker guarantee"]
        self.assertIn("свидетеля нет", why)

    def test_the_shape_the_readers_unpack_is_unchanged(self) -> None:
        """Other readers unpack a PAIR. The role has no right to change
        it."""
        for op, rows in (tc.named_absences(sorted(tc._CLAUSE_NOTES)) or {}).items():
            for row in rows:
                with self.subTest(op=op):
                    clause, why = row
                    self.assertTrue(clause.strip())
                    self.assertTrue(len(why.strip()) > 20)


class ClauseAxisCredit(unittest.TestCase):
    """L7. A CHECK AGAINST THE SUBJECT, the cheap half.

    Measured 22.08.2026: 332 clauses pass invariant 3, and 194 of them
    (58.4%) share a word with TWO or more obligations — the audit does not
    know which of them discharges the clause. The axis in parentheses is a
    carrier that 205 clauses already have, and checking against it costs
    zero edits elsewhere.
    """

    #: 🔴 LIVE DISCREPANCIES, FROZEN BY NAME. Growth is forbidden: a new
    #: line means a new clause credited to someone else's axis. Shrinking
    #: is allowed and required, but the test must NOTICE the shrinkage and
    #: demand the baseline be updated: a silent «стало меньше» hides WHAT
    #: exactly was fixed.
    #:
    #: TWO CLASSES LIVE HERE, AND THEY ARE FIXED DIFFERENTLY:
    #:   * `create_dimension` / `create_angular_dimension` — the semantic
    #:     axis DOES NOT EXIST AT ALL (only materialize/topology/geometry
    #:     obligations), yet the clause «every ref visible in in_view
    #:     (semantic, VIEW-BINDING LAW)» is promised. This is a HOLE: a
    #:     promise with no obligation;
    #:   * `create_text` — the axis is declared (`at`/`width`), but credit
    #:     went to a neighbor. This is a MISCREDIT, not a hole.
    #:
    #: 🔴 A DECREASE WAS RECORDED THE SAME DAY, 22.08.2026: `move_elements`
    #: ×2 LEFT. The reason is not in this file: the move gained two
    #: ripple-circle obligations (`hosted_inserts`, `locked_dimensions`,
    #: both `(topology)`), and clauses that used to be credited to a
    #: neighbor's axis via `connectors` now discharge against their own.
    #: That is, the miscredit was cleared by fixing the SUBJECT, not by
    #: editing the instrument — this is exactly how this baseline is
    #: supposed to shrink.
    #:
    #: 🔴 AN INCREASE WAS RECORDED ON 07.09.2026, AND THIS IS NOT A
    #: CONCESSION BUT TWO NEW HOLES. The provenance is ONE commit,
    #: `878947f` («Снимок волны foundation (Codex, 05–06.09) + первый
    #: пакет исправлений по независимому аудиту 06.09», package D-1: a
    #: type-ownership marker and read-only reuse). Before it,
    #: `create_type.post` NAMED NO AXES AT ALL — not a single parenthesis
    #: — and the instrument was silent not because the credit was correct,
    #: but because there was nothing to judge. The commit placed the
    #: parentheses DELIBERATELY and exposed at once:
    #:
    #:   * `create_type (semantic)` — «named width/depth parameters must
    #:     have observed Double storage and Length dimension before
    #:     writing...»: the clause was introduced by THE SAME commit, the
    #:     op HAS NO semantic obligation AT ALL, credit went to
    #:     `width`/`depth` `(parameter)`;
    #:   * `create_type (geometry)` — «width_mm/depth_mm held on
    #:     param_width_name/param_depth_name at pre-commit re-read...»:
    #:     the clause's text is older (`8eda450`), the `(geometry)`
    #:     parenthesis was hung on by `878947f`, the op HAS NO geometric
    #:     obligation AT ALL, the same credit applies.
    #:
    #: BOTH ARE THE HARD CLASS (a hole, like with `create_dimension`), not
    #: a miscredit: `create_type` has declared exactly `materialize` +
    #: three `(parameter)`. The pin does NOT replace a fix: alongside it
    #: stands `test_the_create_type_hole_is_the_hard_class_too`, which
    #: will turn red on the day the obligation is introduced, and will
    #: force the baseline to SHRINK, naming the op that was fixed.
    #:
    #: 🔴 WHY NOT «RENAME THE PARENTHESIS TO `(parameter)`»: `parameter`
    #: and `identity` ARE NOT IN `tc._CLAUSE_AXIS_WORDS`, and such an edit
    #: would take both clauses out from under the instrument entirely.
    #: That would hide the hole rather than close it, and the baseline
    #: would "shrink" without a single fix to the subject.
    BASELINE = (
        ("create_angular_dimension", "semantic"),
        ("create_dimension", "semantic"),
        ("create_text", "geometry"),
        ("create_type", "geometry"),
        ("create_type", "semantic"),
    )

    def test_the_baseline_holds(self) -> None:
        got = tuple(sorted((op, axis)
                           for op, axis, _c, _k in tc.audit_clause_axis_credit()))
        self.assertEqual(
            got, self.BASELINE,
            "клаузы, зачтённые обязательству ЧУЖОЙ оси, изменились. Прибавка — "
            "новый дефект; убыль — победа, которую надо ЗАПИСАТЬ, обновив "
            "базу вместе с именем починенного опа.\n"
            + "\n".join(f"  {o} [{a}] {c[:70]!r} -> {k}"
                        for o, a, c, k in tc.audit_clause_axis_credit()))

    def test_the_dimension_hole_is_the_hard_class(self) -> None:
        """A hole, not a miscredit: neither op has a semantic axis AT
        ALL."""
        table = tc._ensure_table()
        for op in ("create_dimension", "create_angular_dimension"):
            with self.subTest(op=op):
                kinds = {o.kind for o in table[op].obligations}
                self.assertNotIn(
                    tc.KIND_SEMANTIC, kinds,
                    "если семантическое обязательство завели — это ПОБЕДА, и "
                    "её надо записать здесь и в BASELINE, а не оставить тест "
                    "зелёным по старой причине")
                self.assertIn("every ref visible in in_view",
                              spec.OPS[op].post)

    def test_the_create_type_hole_is_the_hard_class_too(self) -> None:
        """THE ANCHOR FOR THE `878947f` INCREASE: `create_type` HAS NO
        FOREIGN AXES AT ALL.

        Without this test, the two baseline lines would just be frozen red.
        Here the pin is tied to the SUBJECT: as soon as the op gains a
        semantic or a geometric obligation, the test will turn red and
        demand the line be struck from `BASELINE` along with the name of
        the fix — exactly the win the baseline is obligated to NOTICE.
        """
        table = tc._ensure_table()
        kinds = {o.kind for o in table["create_type"].obligations}
        self.assertEqual(kinds, {tc.KIND_MATERIALIZE, tc.KIND_PARAMETER},
                         "состав осей `create_type` сменился — обнови BASELINE")
        for clause in ("named width/depth parameters must have observed Double "
                       "storage and Length",
                       "width_mm/depth_mm held on param_width_name/"
                       "param_depth_name at pre-commit re-read"):
            with self.subTest(clause=clause[:40]):
                self.assertIn(clause, spec.OPS["create_type"].post,
                              "клаузу переписали — перемерь ось и провенанс")

    def test_control_fail_a_clause_credited_to_the_wrong_axis(self) -> None:
        """FAIL CONTROL: the instrument must SEE a new axis substitution."""
        op = "create_room"
        before = len(tc.audit_clause_axis_credit())
        # `room` is present in the topology obligation's clause; the axis
        # is declared as geometric — so the credit will go to a foreign
        # axis.
        with _with_post(op, spec.OPS[op].post + "; room outline area (geometry)"):
            after = tc.audit_clause_axis_credit()
        self.assertEqual(len(after), before + 1, after)
        self.assertTrue(any(o == op and a == tc.KIND_GEOMETRY
                            for o, a, _c, _k in after), after)

    def test_the_probe_is_selective_not_blanket(self) -> None:
        """THE OTHER HALF OF THE CONTROL: the instrument must STAY SILENT
        about a correct credit.

        The mutation above proved the finding is reachable. That alone is
        not enough: an instrument that flags everything indiscriminately
        would reach it too. What is checked here is the reverse — of 78 ops
        in the registry it names only a HANDFUL, and `create_wall` (7,845
        operations on a real building, clauses on all three axes) is not
        among them.

        🔴 THE NUMBER CHANGED 4 -> 3 ON THE SAME DAY, and this is a WIN, not
        a relaxation: `move_elements` left once the move gained
        ripple-circle obligations. The number is kept RIGHT NEXT TO
        `BASELINE`, where the decrease is itemized by name; together the
        two prevent swapping "fixed" for "stopped looking".

        🔴 THE NUMBER 3 -> 4 (07.09.2026, provenance `878947f`) is the
        OPPOSITE case: `create_type` arrived, for which package D-1 placed
        axis parentheses without introducing obligations. The increase is
        itemized by name at `BASELINE` and tied to the subject by the test
        `test_the_create_type_hole_is_the_hard_class_too`. Selectivity was
        not hurt by this: 4 named ops out of 78 in the registry.
        """
        named = {op for op, _a, _c, _k in tc.audit_clause_axis_credit()}
        self.assertNotIn("create_wall", named)
        self.assertEqual(len(named), len({op for op, _a in self.BASELINE}),
                         sorted(named))
        self.assertLess(len(named), len(spec.OPS) // 4,
                        "прибор, называющий четверть реестра, не различает")


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()
