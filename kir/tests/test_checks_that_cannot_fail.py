"""CHECKS THAT COULD NOT HAVE FIRED — ONE KIND OF DEFECT, FOUR CASES.

Each of the four 07.08 fixes closes a line that READ AS a check without
being one. What they share is not a topic but a form: the code signed an
axis that no one read, and the signature was impossible to tell apart from
a measurement.

  A. `authoring_validation.validate` — an `if/elif p.kind == ...` chain
     without a tail. `ParamSpec.kind` is an OPEN string (there is no closed
     enumeration, `spec._lint_registry` knows nothing about kinds), so a
     typo in a new kind failed nowhere: the parameter was checked by NOT A
     SINGLE branch and, worse, did not end up in `norm` — it traveled on as
     if the author had not written it. Only `schema_gen`
     (`unknown param kind`) caught this, meaning a FOREIGN pass, and only
     if someone generated a schema.

  B. `acceptance.Verdict.accepted` — used to be a FIELD, and
     `check_acceptance` put `not mismatches` into it. With zero groups
     checked, there are no discrepancies by construction, so the verdict
     declared success without having checked anything.

  C. `serving` —
     `guarded_out.planned.plan_digest != out.planned.plan_digest` after
     re-lowering with identity proofs. The proofs do not enter the digest
     at all, both lowerings come from the same `compile_input` — the
     comparison was identically false.

  D. `serving._witness_for_success` — the triple of axes is green across
     the board on success, with the justification "the gate proved all
     postconditions before Commit." The argument is true exactly to the
     extent that postconditions per axis are DECLARED, and about that it
     is silent: 11 ops out of 64 have no obligations on geometry, 15 on
     topology, 25 on semantics.

Every test below WOULD HAVE FAILED on the code before the fix — that is
precisely their point. Wherever the old condition can be written out as a
number, it is spelled out VERBATIM, so the reader sees exactly what is
caught, rather than taking it on faith.
"""
from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_spine_honesty_queue.jsonl"))

from kir import authoring_validation as AV  # noqa: E402
from kir import serving as S  # noqa: E402
from kir import spec  # noqa: E402
from kir.acceptance import (  # noqa: E402
    VERDICT_MEASURED,
    VERDICT_MISMATCHED,
    VERDICT_NOTHING_TO_CHECK,
    Certainty,
    ExpectedRow,
    Expectation,
    Verdict,
    check_acceptance,
)
from kir.midend import PlannedProgram  # noqa: E402


def _write_ops() -> tuple[str, ...]:
    return tuple(name for name, op in spec.OPS.items()
                 if op.family in spec.WRITE_FAMILIES)


def _expectation(rows) -> Expectation:
    return Expectation(rows=tuple(rows), derived_categories=(), blind_ops=(),
                       upper_bounds_valid=True, op_count=len(tuple(rows)),
                       notes=())


def _row(count: int, certainty: Certainty) -> ExpectedRow:
    return ExpectedRow(categories=("OST_Walls",), level="L1", count=count,
                       certainty=certainty, op_ids=("w",), why="")


# ═════════════════════════════════════════════════════════════════════════
# A. A TYPO IN `kind` IS NO LONGER SILENCE
# ═════════════════════════════════════════════════════════════════════════

class ATypoInAParamKindIsNoticed(unittest.TestCase):

    def test_an_unknown_kind_raises_instead_of_dropping_the_parameter(self):
        """REFUTATION. Before the fix, this call returned `norm` WITHOUT
        the parameter and WITHOUT a single diagnostic: the `if/elif` chain
        had no tail, a value with an unrecognized kind simply touched no
        branch at all. So a typo in the registry turned a required
        parameter into a missing one — silently."""
        op_spec = spec.OPS["create_wall"]
        original = op_spec.params
        typo = dataclasses.replace(original[0], kind="pt_xzy")  # pt_xyz
        object.__setattr__(op_spec, "params", (typo,) + tuple(original[1:]))
        try:
            with self.assertRaises(AssertionError) as caught:
                AV.validate({"op": "create_wall", "id": "W1"},
                            "create_wall", 0, "W1", [])
            message = str(caught.exception)
            self.assertIn("pt_xzy", message)
            self.assertIn(typo.name, message)
            # The diagnostic must NAME the way out: a list for the foreign
            # kinds.
            self.assertIn("_KINDS_VALIDATED_ELSEWHERE", message)
        finally:
            object.__setattr__(op_spec, "params", original)

    def test_every_writing_op_of_the_registry_still_validates(self):
        """THE LOCK MUST NOT REFUSE A CORRECT PROGRAM. The loop's first
        branch carries a second conjunct
        (`p.name not in ("p0_mm", "p1_mm")`): the segment's endpoints are
        parsed BEFORE the loop, as a whole, because the "length ~0" law
        looks at both points at once. A naive `else` would misfire on 32
        such parameters across 16 ops — exactly the kind of thing that
        costs more than a missed finding."""
        for name in _write_ops():
            op_spec = spec.OPS[name]
            for payload in ({}, {p.name: None for p in op_spec.params}):
                op = dict(payload, op=name, id="X1")
                with self.subTest(op=name, payload=sorted(payload)):
                    AV.validate(op, name, 0, "X1", [])

    def test_the_kind_vocabulary_is_closed_and_matches_the_registry(self):
        """REFUTATION OF THE THIRD CASE. `schema_gen` referred to
        "registry lint keeps kinds closed" — to a guarantee that did not
        exist: `_lint_registry` knew about capability cells, effects, and
        pools, and knew nothing about `ParamSpec.kind`. Now the dictionary
        is closed, and the test holds it in BOTH DIRECTIONS: an extra name
        in the set is just as much a lie as a missing one, because a set
        that anything can be appended to closes nothing."""
        in_use = {p.kind for op in spec.OPS.values() for p in op.params}
        self.assertEqual(spec.PARAM_KINDS, in_use)
        # 🔴 THE SECOND RATCHET ON THE NUMBER OF KINDS, AND IT HAD STOOD
        # RED SINCE 20.08 TOGETHER WITH THE FIRST (`test_program_source`):
        # the surface and boolean waves started their own kinds and looked
        # into neither of the two. The substantive review was done on
        # 21.08 in the first one — it lists what is millimeters inside
        # each new kind and what is dimensionless. Here the number simply
        # must match the registry, and it is held by TWO independent
        # guards deliberately: one about printing the reverse pass, the
        # other about the dictionary's closedness.
        #
        # 37 -> 38 (21.08.2026): kind `dir_xyz` — a DIRECTION, separated
        # from a point. The substantive review lies in the first guard
        # (`test_program_source`), and it found more there than one new
        # kind: three OLD kinds carried millimeters past `MM_KINDS`, and
        # the most frequent of them (`arc` on a wall, the direct reverse
        # pass) had its arc center not following the unit frame.
        #
        # 🔴 THE LESSON OF THIS NUMBER, NOT THE NUMBER ITSELF. Both guards
        # had been red TOGETHER since 20.08 and were only read just now —
        # not because they were silent, but because their files did not
        # collect: a solo op without a sample dropped the collection of
        # three neighboring files. Red for a known reason hides the next
        # one, and here it hid four levels in a row.
        #
        # 38 -> 39 (23.08.2026): kind `wall_layers` — the WALL'S LAYER
        # STACK, a list of layers with thickness, function, and material.
        # The substantive review lies in the first guard and in
        # `MM_KINDS_REFUSED`; it found a SECOND hole, a foreign one
        # (`member_ops`) — meaning it was worth repeating across the whole
        # list.
        # ── 39 -> 41 (13.09.2026) ─────────────────────────────────────
        # Два вида, каждый сверен ПО ИМЕНИ с реестром, а не вспомнен:
        #   `identity`   — волна N-2, `{unique_id, version_guid}` как база правки
        #   `enum_list`  — `query_level_plan.include`, выбор из `choices` самого
        #                  параметра (у `fields` словарь прибит к LIST_FIELDS)
        # 39 + 2 = 41, без остатка.
        #
        # 🔴 ЧТО ЭТОТ КРАСНЫЙ СТОИЛ. `identity` приехал ещё в N-2, и вместе с
        # ним остались красными ЧЕТЫРЕ счётных пина словаря видов: этот,
        # `test_program_source` (список миллиметровых), `test_sdk` (образец
        # вида) и состояние канона. Ни один не попал в наборы, которые я гонял
        # по предмету правки, — и это ровно тот класс, что уже записан у меня:
        # «сравнивай ИМЕНА красных, а не число». Здесь он обошёлся в четыре
        # пина, найденные только тогда, когда следующий вид приехал в дерево.
        self.assertEqual(len(spec.PARAM_KINDS), 41)

    def test_a_typo_is_refused_at_registry_import_as_well(self):
        """THREE LOCKS, THREE DIFFERENT REASONS TO FAIL. The registry does
        not import with an unnamed kind; the schema does not build; the
        program does not parse. Here the first — the earliest of the
        three — is checked."""
        op_spec = spec.OPS["create_wall"]
        original = op_spec.params
        typo = dataclasses.replace(original[0], kind="pt_xzy")
        object.__setattr__(op_spec, "params", (typo,) + tuple(original[1:]))
        try:
            with self.assertRaises(AssertionError) as caught:
                spec._lint_registry()
            self.assertIn("pt_xzy", str(caught.exception))
            self.assertIn("PARAM_KINDS", str(caught.exception))
        finally:
            object.__setattr__(op_spec, "params", original)
        # The registry must be clean again — otherwise the test would
        # poison its neighbors.
        spec._lint_registry()

    def test_the_allowlist_holds_only_kinds_no_write_op_can_carry(self):
        """The list of foreign kinds is a census, not a store. Every key
        must be a real registry kind AND not sit on any writing op:
        otherwise it would swallow the typo instead of showing it."""
        in_use = {p.kind for op in spec.OPS.values() for p in op.params}
        on_writes = {p.kind for name in _write_ops()
                     for p in spec.OPS[name].params}
        self.assertTrue(AV._KINDS_VALIDATED_ELSEWHERE)
        for kind, where in AV._KINDS_VALIDATED_ELSEWHERE.items():
            with self.subTest(kind=kind):
                self.assertIn(kind, in_use)
                self.assertNotIn(kind, on_writes)
                # The location of the parse is named, not implied.
                self.assertIn("compiler", where)


# ═════════════════════════════════════════════════════════════════════════
# B. AN EMPTY CHECK IS NOT SUCCESS
# ═════════════════════════════════════════════════════════════════════════

class AnEmptyCheckIsNotAPass(unittest.TestCase):

    def test_an_expectation_with_nothing_to_check_is_not_accepted(self):
        """REFUTATION. The UNKNOWN/0 row is skipped by `check_acceptance`,
        zero groups checked, zero discrepancies — and the former
        `accepted=not mismatches` gave TRUE. Acceptance declared success
        without having looked at anything."""
        verdict = check_acceptance(
            _expectation([_row(0, Certainty.UNKNOWN)]), {}, {})
        self.assertEqual(verdict.checked_groups, 0)
        self.assertEqual(verdict.mismatches, ())
        # The former formula, spelled out VERBATIM: it really was true.
        self.assertTrue(not verdict.mismatches)
        self.assertFalse(verdict.accepted)
        self.assertTrue(verdict.vacuous)
        self.assertEqual(verdict.reason, VERDICT_NOTHING_TO_CHECK)

    def test_a_measured_match_is_still_accepted(self):
        """GREEN DID NOT BECOME RED. The fix must move exactly one case —
        the zero check — and must not touch genuine convergence."""
        verdict = check_acceptance(
            _expectation([_row(1, Certainty.EXACT)]), {},
            {("OST_Walls", "L1"): 1})
        self.assertEqual(verdict.checked_groups, 1)
        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.reason, VERDICT_MEASURED)

    def test_a_finding_is_distinguishable_from_an_emptiness(self):
        """Both give `accepted=False`, and these are DIFFERENT facts: the
        first is fixed by building, the second by waiting. A bare boolean
        merged them."""
        missed = check_acceptance(
            _expectation([_row(1, Certainty.EXACT)]), {},
            {("OST_Walls", "L1"): 0})
        empty = check_acceptance(
            _expectation([_row(0, Certainty.UNKNOWN)]), {}, {})
        self.assertFalse(missed.accepted)
        self.assertFalse(empty.accepted)
        self.assertEqual(missed.reason, VERDICT_MISMATCHED)
        self.assertEqual(empty.reason, VERDICT_NOTHING_TO_CHECK)
        self.assertNotEqual(missed.reason, empty.reason)
        self.assertIn("reason", missed.to_dict())

    def test_the_lying_verdict_can_no_longer_be_constructed(self):
        """`accepted` is no longer A FIELD. As long as it was a field, any
        caller could write true into it with zero groups checked; now
        there is no such name among the fields, and there is nothing left
        to lie with."""
        names = {f.name for f in dataclasses.fields(Verdict)}
        self.assertNotIn("accepted", names)
        self.assertIn("checked_groups", names)


# ═════════════════════════════════════════════════════════════════════════
# C. THE PLAN DIGEST DOES NOT SEE IDENTITY PROOFS
# ═════════════════════════════════════════════════════════════════════════

class ThePlanDigestCannotSeeIdentityProofs(unittest.TestCase):

    def test_the_digest_binds_no_identity_and_the_deleted_check_knew_nothing(self):
        """THE REASON FOR REMOVAL, PINNED DOWN BY THE TEST. The removed
        condition compared the `plan_digest` of two lowerings that
        differed ONLY by identity proofs. The digest binds not a single
        proof, so the two sides were always equal.

        The test also guards the reverse: if proofs are ever folded into
        the digest, it will fail — and that will be the signal that the
        removed check can (and must) be brought back, this time for
        real."""
        bound = set(PlannedProgram.__dataclass_fields__)
        self.assertNotIn("expected_identities", bound)
        self.assertNotIn("identity_proofs", bound)
        for field_name in bound:
            self.assertNotIn("identit", field_name.lower())

    def test_the_surviving_arms_are_the_ones_that_can_fire(self):
        """What remains in place of what was removed: `guarded_out is None`
        (contradictory proofs for one element_id) and `not guarded_out.ok`
        (the re-lowering failed to compile). Both are about the outcome of
        the SECOND compilation, that is, about what could actually go
        wrong.

        A CHECKED-OUT LINE BROKE FROM AN HONEST FIX (11.08.2026). Here
        stood `assertIn("if guarded_out is None or not guarded_out.ok:")` —
        the WRITING of the condition in full, as one line. The acceptance
        wave appended two genuine arms to that same condition
        (`grounded is None` and a mismatch of `ground_digest` against the
        registered one), the condition moved to five lines, and the test
        turned red even though the guarding had become STRICTER. The
        irony is named aloud: an instrument that hunts for checks
        incapable of firing was itself tied to the spelling instead of the
        property.

        Now what is read is STRUCTURE, not text: `ast` finds the condition
        branching on `guarded_out`, and the arms are compared by form. A
        comment, a line break, and renaming a local variable no longer
        decide anything; bringing back the dead comparison does decide.

        THE BOUNDARY OF THIS TEST, named because it equals the power of
        `ast`, not the power of a run. This is NOT a behavioral check:
        `_handle_revit_ir_inner` is the boundary of a live write, it
        cannot be executed without the bridge, an acceptance session, and
        a model snapshot, and faking all three would only prove the
        fake's own operation. So the test guards exactly two things: that
        the removed digest comparison has not come back, and that the
        remaining arms are about the outcome of the SECOND compilation.
        That they actually refuse is proven not by this test but by the
        write acceptance tests.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(
            inspect.getsource(S._handle_revit_ir_inner)))
        guards = [node for node in ast.walk(tree)
                  if isinstance(node, ast.If)
                  and "guarded_out" in ast.dump(node.test)]
        self.assertTrue(guards, "условие, ветвящееся по guarded_out, исчезло")

        arms: list[str] = []
        for node in guards:
            test = node.test
            arms.extend(
                ast.dump(value) for value in
                (test.values if isinstance(test, ast.BoolOp) else [test]))

        def has(fragment: str) -> bool:
            return any(fragment in arm for arm in arms)

        # Arm 1: the proofs are contradictory — there was no second
        # compilation at all.
        self.assertTrue(
            has("Compare") and has("'guarded_out'") and has("Is("),
            "плечо `guarded_out is None` не найдено среди условий")
        # Arm 2: the re-lowering with guards failed to compile.
        self.assertTrue(
            has("attr='ok'"), "плечо `not guarded_out.ok` не найдено")

        # THE DEAD COMPARISON HAS NOT COME BACK. `plan_digest` binds not a
        # single identity proof, so the comparison of the two lowerings'
        # digests was identically true and could never have fired.
        for arm in arms:
            self.assertNotIn("attr='plan_digest'", arm,
                             "мёртвое сравнение отпечатков вернулось в код")
            self.assertNotIn("attr='planned'", arm,
                             "мёртвое сравнение отпечатков вернулось в код")


# ═════════════════════════════════════════════════════════════════════════
# D. A GREEN AXIS MUST BE MEASURED
# ═════════════════════════════════════════════════════════════════════════

class AGreenAxisMustHaveBeenMeasured(unittest.TestCase):

    def test_an_op_that_promised_nothing_on_an_axis_says_so(self):
        """REFUTATION. `set_param` declares NOT A SINGLE obligation on
        geometry, topology, or semantics (`translation_cert.REFINEMENT`),
        yet a successful write still returned a fully green triple. Now a
        list of axes no one promised to measure travels alongside the
        triple."""
        witness = S._witness_for_success("write", {}, ("set_param",))
        self.assertEqual(
            witness["unwitnessed_axes"],
            {"geometry": ["set_param"], "semantic": ["set_param"],
             "topology": ["set_param"]})
        # The triple is NOT redefined: the field is additive, not a
        # replacement.
        self.assertTrue(witness["geometry_ok"])
        self.assertTrue(witness["semantic_ok"])
        self.assertTrue(witness["topology_ok"])

    def test_a_fully_obligated_op_reports_nothing_unwitnessed(self):
        """The flip side: `create_wall` declares all three axes, and the
        list is empty. An instrument that always shouts is no better than
        a silent one."""
        witness = S._witness_for_success("write", {}, ("create_wall",))
        self.assertEqual(witness["unwitnessed_axes"], {})

    def test_nothing_to_judge_is_none_and_none_is_not_green(self):
        """A TRISTATE, by the same law as `Judged.proven`. An empty program
        and an op outside the obligations table give `None` — "nothing to
        say" — rather than an empty list, which would read as "everything
        is declared"."""
        self.assertIsNone(S._unwitnessed_axes(()))
        self.assertIsNone(S._unwitnessed_axes(("not_a_real_op",)))
        self.assertIsNone(
            S._witness_for_success("write", {})["unwitnessed_axes"])

    def test_a_mixed_program_names_which_op_promised_nothing(self):
        """REFUTATION OF A SELF-REVIEW FIX. While the answer was a LIST OF
        AXES, this pair gave `["geometry","semantic","topology"]` — byte
        for byte the same as one bare `set_param`. Two different worlds
        under one answer: "nothing was checked" and "one of the two
        operations promised nothing." Now the culprit is named, and the
        cases are distinguishable."""
        self.assertEqual(S._unwitnessed_axes(("create_wall",)), {})
        mixed = S._unwitnessed_axes(("create_wall", "set_param"))
        self.assertEqual(sorted(mixed), ["geometry", "semantic", "topology"])
        for axis in mixed:
            with self.subTest(axis=axis):
                # `create_wall` declared all three and must NOT be named.
                self.assertEqual(mixed[axis], ["set_param"])
        # MERGING TWO PROGRAMS HERE IS NOT A DEFECT, AND THIS IS VERIFIED
        # BY MEASUREMENT. `(create_wall, set_param)` and `(set_param,)`
        # give the SAME dictionary, and that is how it must be: the same
        # op is at fault, so the unearned claims are the same too. What
        # distinguishes the cases is not the length of the answer but the
        # NAMES: `create_wall` is never named, and this shows that its
        # green is earned.
        #
        # Here stood `assertNotEqual(mixed, bare)` — a requirement I had
        # not thought through: it declared as a defect exactly the
        # behavior that is correct. The measurement removed it before it
        # shipped as a red test.
        self.assertEqual(S._unwitnessed_axes(("set_param",)), mixed)
        self.assertNotIn("create_wall", str(mixed))

    def test_the_three_booleans_are_byte_identical_to_the_old_formula(self):
        """THE NEW FIELD REDEFINED NOTHING. The old layout is spelled out
        here VERBATIM and checked against the new one on every set of
        violations."""
        corpus = (
            [],
            ["bad thing (geometry)"],
            ["bad thing (topology)"],
            ["bad thing"],
            ["a (geometry)", "b (topology)", "c"],
            ["a (geometry)", "b (geometry)"],
        )
        for vio in corpus:
            with self.subTest(violations=vio):
                old = {
                    "geometry_ok": not any("(geometry)" in x for x in vio),
                    "topology_ok": not any("(topology)" in x for x in vio),
                    "semantic_ok": not any(
                        "(geometry)" not in x and "(topology)" not in x
                        for x in vio),
                }
                self.assertEqual(S._axes_from_violations(vio), old)

    def test_both_witness_paths_split_the_axes_identically(self):
        """D1: the layout lived as TWO VERBATIM COPIES in two functions.
        Copies diverge silently, so now there is one — and both paths must
        give the same triple on the same violations."""
        vio = ["a (geometry)", "b (topology)", "c"]
        success = S._witness_for_success(
            "write", {"postcondition_violations": vio}, ("create_wall",))
        failure = S._derive_witness(
            False, "write", {"code": "KIR-X004", "violations": vio})
        for axis in ("geometry_ok", "topology_ok", "semantic_ok"):
            with self.subTest(axis=axis):
                self.assertEqual(success[axis], failure[axis])

    def test_a_query_carries_no_axis_claim_at_all(self):
        """A query has neither a witness nor obligations — and no field
        either: an empty list there would read as a claim."""
        self.assertEqual(S._witness_for_success("query", {}), {"read_only": True})
        self.assertNotIn(
            "unwitnessed_axes",
            S._witness_for_success("query", {}, ("create_wall",)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
