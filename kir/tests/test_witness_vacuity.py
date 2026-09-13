"""VACUOUS WITNESS: a check that CANNOT fail is not a check.

THE DEFECT THIS FILE GREW OUT OF (audit of 09.08.2026).  The wall witness was
replaced with

    if (false) __post.Add("never");

and ``certify_op(wall, "2026").proven`` stayed ``True``.  The cause was
two-layered, and both layers were checking THE SAME THING:

  * ``emit_model.WitnessCheck`` requires the PRESENCE of ``__post.Add`` in the verdict;
  * ``translation_cert.certify_op`` requires the PRESENCE of the obligation key.

Neither one looked at the CONDITION under which this line stands.  "A line
exists that is capable of adding a violation" was taken for "the check is
capable of detecting the violation" — and this discharged the certificate's
obligation.

THE SHAPE OF THE CHECK IS A MUTATION, not an assertion (discipline C5 of this
repository): every vacuum class is IMPLANTED into a witness of a REAL op, and
the certificate MUST refuse with a typed, op-bound diagnostic.

AN HONEST BOUNDARY, PINNED MECHANICALLY.  Reachability is undecidable, and
``NotDetected`` below is NOT a task list — it is a presented limit: shapes of
vacuum that the instrument does NOT SEE and about which it must stay silent
rather than lie.  The class of defect this house fights is an instrument that
covers PART of the range and passes itself off as complete; so the limits
here are tested on equal footing with the findings.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_vacuity_queue.jsonl"))

from kir import authoring                                  # noqa: E402
from kir import translation_cert as tc                     # noqa: E402
from kir import spec                                       # noqa: E402
from kir.authoring import _SOLO_PROGRAMS                   # noqa: E402
from kir.emit_model import BarePost, WitnessCheck          # noqa: E402
from kir.tests.test_emitter_scope_contract import VERSIONS  # noqa: E402
from kir.tests.test_tolerance_provenance import (          # noqa: E402
    _full_instances,
    WRITE_OPS,
)

WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
        "p1_mm": [6000, 0], "height_mm": 3000.0,
        "level": {"__grounded__": {"id": 42, "name": "L1",
                                   "via": "element_id"}},
        "type": {"__grounded__": {"id": 901, "name": "T",
                                  "via": "element_id"}}}


def _grounded(op_name: str) -> dict:
    """A real grounded op from the corpus — not a hand-invented dict."""

    for name, op, _ver in _full_instances():
        if name == op_name:
            return op
    raise AssertionError(f"корпус не строит {op_name}")


#: (form name, verdict C#, expected vacuum class).  Each row is a SEEDLING:
#: it is inserted in place of a real verdict of a live witness.
PLANTS: tuple[tuple[str, str, str], ...] = (
    ("if (false)",
     '    if (false) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (0 == 1)",
     '    if (0 == 1) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (1 > 2)",
     '    if (1 > 2) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (!true)",
     '    if (!true) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (false && live)",
     '    if (false && __el_W1 == null) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (false || 1 > 2)",
     '    if (false || 1 > 2) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if ((false))",
     '    if ((false)) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("while (false)",
     '    while (false) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("for (;false;)",
     '    for (int __i = 0; false; __i++) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("else of if (true)",
     '    if (true) { } else { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("nested under if (false)",
     '    if (false) { if (__el_W1 == null) { __post.Add("never"); } }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("self-comparison !=",
     '    if (__el_W1 != __el_W1) __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("self-comparison <",
     '    if (__el_W1.Id < __el_W1.Id) __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("self-comparison through a tolerance",
     '    if (Math.Abs(MM(__el_W1.Width) - MM(__el_W1.Width)) > 5.0)\n'
     '        __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("unreachable after return",
     '    return;\n    __post.Add("never");\n',
     tc.VACUITY_UNREACHABLE),
    ("unreachable after throw inside a LIVE guard",
     '    if (__el_W1 == null) { throw new Exception();'
     ' __post.Add("never"); }\n',
     tc.VACUITY_UNREACHABLE),
    ("unreachable after continue in a loop",
     '    foreach (var __x in __els) { continue; __post.Add("never"); }\n',
     tc.VACUITY_UNREACHABLE),
)

#: Shapes that the instrument PROVABLY does not see.  Each one is a vacuum,
#: and each is pinned here as a LIMIT: if one day it becomes a finding, the
#: test fails and the boundary is rewritten EXPLICITLY, not silently.
NOT_DETECTED: tuple[tuple[str, str], ...] = (
    ("константа в переменной (нет распространения констант)",
     '    bool __never = false;\n    if (__never) __post.Add("never");\n'),
    ("пустая коллекция (число итераций из текста не выводится)",
     '    foreach (var __x in __definitelyEmpty) __post.Add("never");\n'),
    ("недостижимость через данные (null уже исключён выше)",
     '    if (__el_W1 == null) __post.Add("never");\n'),
    ("допуск шире любого расхождения — живое число, не вакуум",
     '    if (Math.Abs(MM(__a) - MM(__b)) > 1e30) __post.Add("never");\n'),
)


def _plant(op_name: str, key: str, verdict_cs: str):
    """Replace witness verdict ``key`` of op ``op_name`` with the seedling."""

    original = authoring._EMITTERS[op_name]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
                continue
            out.append(WitnessCheck(
                obligation_key=check.obligation_key,
                reader_cs="",
                verdict_cs=verdict_cs,
                message=check.message,
                tol=None,
                style="plain"))
        return decl, create, (BarePost(tuple(out)) if bare else out), readback

    authoring._EMITTERS[op_name] = broken
    return original


class MutationPlantsMustBeRefused(unittest.TestCase):
    """Every vacuum class implanted into a live witness drops the certificate."""

    def test_baseline_wall_is_proven(self) -> None:
        # The anchor of the whole mutation: without the seedling, the wall is
        # proven. Otherwise the tests below would pass for the wrong reason.
        self.assertTrue(tc.certify_op(WALL, "2026").proven)

    def test_every_plant_is_refused_with_a_typed_named_diagnostic(self) -> None:
        for label, verdict_cs, expected_kind in PLANTS:
            with self.subTest(plant=label):
                original = _plant("create_wall", "endpoints", verdict_cs)
                try:
                    cert = tc.certify_op(WALL, "2026")
                finally:
                    authoring._EMITTERS["create_wall"] = original

                self.assertFalse(
                    cert.proven,
                    f"саженец {label!r} оставил сертификат доказанным")
                self.assertTrue(cert.vacuous, f"{label}: находки нет")
                kinds = {f.kind for f in cert.vacuous}
                self.assertIn(expected_kind, kinds, f"{label}: класс {kinds}")
                for finding in cert.vacuous:
                    self.assertEqual(finding.op, "create_wall")
                    self.assertEqual(finding.obligation_key, "endpoints")
                    self.assertIn(finding.kind, tc.VACUITY_KINDS)
                # The obligation must become NOT discharged: the certificate
                # names the CLAUSE, not just a line of C#.
                gaps = "\n".join(cert.gaps)
                self.assertIn("LocationCurve endpoints", gaps)
                self.assertIn("VACUOUS", gaps)

    def test_the_plant_is_refused_in_a_second_op_too(self) -> None:
        # Not a property of create_wall: the same seedling is in the pipe.
        pipe = _grounded("create_pipe")
        self.assertTrue(tc.certify_op(pipe, "2026").proven)
        original = _plant("create_pipe", "endpoints",
                          '    if (false) __post.Add("never");\n')
        try:
            cert = tc.certify_op(pipe, "2026")
        finally:
            authoring._EMITTERS["create_pipe"] = original
        self.assertFalse(cert.proven)
        self.assertEqual({f.op for f in cert.vacuous}, {"create_pipe"})
        self.assertEqual({f.obligation_key for f in cert.vacuous}, {"endpoints"})

    def test_assert_refined_raises_the_specific_typed_error(self) -> None:
        original = _plant("create_wall", "endpoints",
                          '    if (false) __post.Add("never");\n')
        try:
            cert = tc.certify_op(WALL, "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        # "There is no check" and "there is a check and it cannot fire" are
        # different defects and must come under different names.
        with self.assertRaises(tc.VacuousWitnessError):
            tc.assert_refined(cert)
        # ...while still being caught by the old handlers.
        self.assertTrue(issubclass(tc.VacuousWitnessError,
                                   tc.UnprovenRefinementError))

    def test_a_missing_check_still_raises_the_general_error(self) -> None:
        # We did not weaken what existed: deleting the witness is still a
        # refusal, and NOT a vacuous one (that is a different defect class).
        original = authoring._EMITTERS["create_wall"]

        def broken(op, ver, stamp, isolation="atomic"):
            d, c, p, r = original(op, ver, stamp, isolation)
            return d, c, [x for x in p if x.obligation_key != "endpoints"], r

        authoring._EMITTERS["create_wall"] = broken
        try:
            cert = tc.certify_op(WALL, "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        self.assertFalse(cert.proven)
        self.assertEqual(cert.vacuous, ())
        with self.assertRaises(tc.UnprovenRefinementError) as ctx:
            tc.assert_refined(cert)
        self.assertNotIsInstance(ctx.exception, tc.VacuousWitnessError)

    def test_plants_removed_the_wall_is_proven_again(self) -> None:
        # The seedlings are removed — the certificate is THE SAME as before the whole wave.
        self.assertTrue(tc.certify_op(WALL, "2026").proven)
        self.assertEqual(tc.certify_op(WALL, "2026").vacuous, ())


class TheDetectorItself(unittest.TestCase):
    """Guard the guard: without it, the whole suite above could pass by running idle."""

    def test_it_recognises_the_archetype(self) -> None:
        findings, partial = tc.analyze_witness_cs(
            'if (false) __post.Add("");')
        self.assertFalse(partial)
        self.assertEqual([f[0] for f in findings], [tc.VACUITY_CONSTANT_FALSE])

    def test_it_stays_silent_on_a_live_witness(self) -> None:
        live = (
            'var __lc = __el_W1.Location as LocationCurve;\n'
            'if (__lc == null) __post.Add("");\n'
            'else\n'
            '{\n'
            '    var __c = __lc.Curve;\n'
            '    if (Math.Abs(MM(__c.GetEndPoint(0).X) - 0) > 1.0)\n'
            '        __post.Add("");\n'
            '}\n')
        findings, partial = tc.analyze_witness_cs(live)
        self.assertEqual(findings, ())
        self.assertFalse(partial)

    def test_a_live_verdict_beside_a_dead_one_is_still_reported(self) -> None:
        # The rule is deliberately strict: a finding is EVERY dead
        # `__post.Add`, not only "all of them are dead" — otherwise gutting
        # just one of the witness's two branches would pass silently.
        mixed = ('if (__lc == null) __post.Add("");\n'
                 'if (false) __post.Add("");\n')
        findings, _ = tc.analyze_witness_cs(mixed)
        self.assertEqual(len(findings), 1)

    def test_the_named_limits_are_really_limits(self) -> None:
        for label, code in NOT_DETECTED:
            with self.subTest(limit=label):
                findings, _ = tc.analyze_witness_cs(code)
                self.assertEqual(
                    findings, (),
                    f"{label}: прибор внезапно ЭТО видит — граница в "
                    "docstring translation_cert устарела, перепишите её ЯВНО")

    def test_an_always_true_guard_is_not_a_vacuity_finding(self) -> None:
        # An always-true guard is a different defect: it fails ALWAYS and
        # LOUDLY, that is, it does not belong to the "silently wrong" class.
        findings, _ = tc.analyze_witness_cs('if (true) __post.Add("");')
        self.assertEqual(findings, ())

    def test_a_fragment_that_is_not_self_contained_is_flagged_partial(self) -> None:
        findings, partial = tc.analyze_witness_cs(
            'if (false) __post.Add(""); }\nprivate class X { }')
        self.assertTrue(partial)
        # ...and yet it is parsed: incompleteness does not mean blindness.
        self.assertEqual([f[0] for f in findings], [tc.VACUITY_CONSTANT_FALSE])

    def test_constant_folding_corners(self) -> None:
        for expr, expected in (
                ("false", False), ("true", True), ("!false", True),
                ("0 == 1", False), ("1 != 1", False), ("2 <= 1", False),
                ("1.0 > 2.0", False), ("(false)", False),
                ("false && __x", False), ("__x && false", False),
                ("true || __x", True), ("false || false", False),
                ("__x == __x", True), ("__x != __x", False),
                ("Math.Abs(MM(__a) - MM(__a)) > 5.0", False),
                ("__a == __b", None), ("__a > 5.0", None),
                ("__lc == null", None), ("", None)):
            with self.subTest(expr=expr):
                self.assertEqual(tc._const_bool(expr)[0], expected)


class TheWholeCorpusIsClean(unittest.TestCase):
    """Ratchet: not a single registered op emits a dead verdict."""

    def test_no_registered_op_emits_a_dead_verdict(self) -> None:
        offenders = set()
        for name, op, ver in _full_instances():
            for finding in tc.certify_op(op, ver).vacuous:
                offenders.add(
                    f"{name}.{finding.obligation_key} [{finding.kind}] "
                    f"{finding.guard}")
        self.assertEqual(
            sorted(offenders), [],
            "эти свидетели не могут сработать:\n  " + "\n  ".join(sorted(offenders)))

    def test_only_whole_program_templates_are_read_in_pieces(self) -> None:
        # Exactly those texts are not self-contained in their brackets that
        # have their own template of the WHOLE program (method body + class
        # declarations, the frame supplied by wrap_user_code), that is,
        # exactly `spec.SOLO_OPS`. The appearance of a third such text is a
        # fact that must be noticed, and since 10.08.2026 the set is checked
        # against the REGISTRY, not against a single name: the site arrived
        # as a second occupant, and a hard-coded literal would have declared
        # correct behavior a regression.
        partial = {name for name, op, ver in _full_instances()
                   if tc.certify_op(op, ver).vacuity_partial}
        self.assertEqual(partial, set(spec.SOLO_OPS))

        # ...and "piecewise" here still means WHOLE: every verdict of the
        # template is reached by the walk. Incomplete parsing is a risk, not
        # a fact; here it was measured and came out zero — for BOTH templates.
        for name in sorted(spec.SOLO_OPS):
            with self.subTest(op=name):
                solo = next(op for got, op, _v in _full_instances()
                            if got == name)
                reached, present = tc.witness_site_census(
                    tc._code(_SOLO_PROGRAMS[name](solo, "2026")))
                self.assertGreater(present, 0)
                self.assertEqual(reached, present)

    def test_the_walk_reaches_every_verdict_site_in_the_corpus(self) -> None:
        # WITHOUT THIS, "zero findings" and "the walk silently missed it" are
        # indistinguishable — exactly the substitution this file is about. We
        # count the `__post.Add` calls reached by the walk against those
        # present in the text.
        missed = []
        reached = total = 0
        for name, op, ver in _full_instances():
            emitter = authoring._EMITTERS.get(name)
            if emitter is None:      # solo op: its own template of the whole program
                continue
            _d, _c, post, _r = emitter(op, ver, "kir:census")
            checks = list(post.checks) if isinstance(post, BarePost) else list(post)
            for check in checks:
                got, want = tc.witness_site_census(tc._code(check.render()))
                reached += got
                total += want
                if got != want:
                    missed.append(f"{name}.{check.obligation_key}: {got}/{want}")
        self.assertGreater(total, 0, "корпус не дал ни одного вердикта")
        self.assertEqual(
            sorted(missed), [],
            "обход не дошёл до этих вердиктов — «чисто» было бы ложью:\n  "
            + "\n  ".join(sorted(missed)))

    def test_every_write_op_is_actually_exercised(self) -> None:
        # An empty corpus would make the lever above green for nothing.
        seen = {name for name, _op, _ver in _full_instances()}
        self.assertEqual(sorted(set(WRITE_OPS) - seen), [])
        self.assertGreaterEqual(len(VERSIONS), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
