"""AN L6 ORACLE WITH THREE STATES, not silence on two of them.

THE TRIGGER — THIS SAME ORACLE'S OWN MISTAKE (11.08.2026). A territory
sweep reported: "the oracle skipped seven ops," and named the reasons.
ALL THREE REASONS WERE WRONG, and each is exactly the class of defect the
sweep was hunting:

  * "three graph ops carry a legacy string post" — NO. All three declare
    `witness_source="model"` and return `BarePost`, whose witnesses live
    in `.checks`. The probe asked `isinstance(post, (list, tuple))`, got
    False, and CALLED this "legacy string" — an assertion about a cause,
    read off a type;
  * "`create_stairs` has no entry in the emitter table" — true, but the
    conclusion "uncheckable" is NOT: `certify_op` parses solo ops
    through a separate branch (`spec.SOLO_OPS`) and returns
    `proven=True` on 5 clauses;
  * "three load ops refuse by construction" — true on 2024+, but the
    probe tried ONLY one version. On 2021-2023 they emit and are
    certified `proven=True`.

The upshot: there was NO architectural work there at all, only a report
in which "not checked," "uncheckable," and "not reached" all read the
same way — as silence. This file exists so that such a report never
happens again.

THREE STATES, AND EACH ONE IS PRINTED:

  VERIFIED      — the baseline is green, and cutting out EVERY witness
                  drops `proven` (or makes the post unconstructable,
                  which is stronger).
  UNCHECKABLE   — the op is structurally outside the mutation, and the
                  CAUSE IS NAMED AS A STRING that the test itself
                  prints, not one the reader has to infer.
  NOT_REACHED   — the corpus builds no program with this op at all.
                  This is NOT "healthy": it is an absence of evidence,
                  and it must be visible separately from the other two.

THE BASELINE LAW. A mutation whose original certificate is ALREADY red
"passes" for free: the cut changes nothing, and the report is green.
That is how this oracle lied to the 11.08 placements wave. So the green
baseline is checked BEFORE every cut, and its absence is a separate
state, not a silent skip.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_l6_states_queue.jsonl"))

from kir import ground as ground_mod, spec                  # noqa: E402
from kir import translation_cert as tc                      # noqa: E402
from kir.authoring import _EMITTERS, _SOLO_PROGRAMS         # noqa: E402
from kir.compiler import _parse_and_check                   # noqa: E402
from kir.emit_model import BarePost                         # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAP      # noqa: E402
from kir.tests.test_emitter_scope_contract import (         # noqa: E402
    PROGRAMS as SCOPE)
from kir.tests.test_golden import PROGRAMS as GOLDEN        # noqa: E402

VERIFIED = "verified"
UNCHECKABLE = "structurally-uncheckable"
NOT_REACHED = "not-reached"

#: Ops for which mutation is UNREACHABLE by design, and why. The reason goes
#: into the report VERBATIM: "not testable" without a reason is indistinguishable
#: from "forgot to test".
#:
#: The list is CLOSED by the test below: an op that lands here without a
#: string fails the run, and an op with a string that in fact does mutate
#: fails it too — otherwise the record would outlive its own truth, as has
#: already happened twice in tool_doc.
_UNCHECKABLE_REASONS: dict[str, str] = {
    # EMPTY, AND THIS IS THE RESULT, NOT A STUB.
    #
    # On 08.11 this held `create_stairs` with the reason "solo op: the post
    # renders as ONE string, there is no separate handle for a witness".
    # The reason was HONEST and WRONG: the handle exists, it's just not
    # where it was looked for. The assumption was that the seam was
    # `_LIVE_STUB` of the standing test; checking the code showed that
    # `_LIVE_STUB` treats an EMPTY post, while the standing test excludes
    # solo ops by a list. The real seam is `authoring._SOLO_PROGRAMS`: a
    # solo op is discharged by a MARKER in the program text, so cutting the
    # witness = removing the lines carrying its markers (`_solo_survivors`
    # below).
    #
    # Measurement after the fix: for both solo ops EVERY required
    # obligation is caught by the slice. The one "survivor" is
    # `create_stairs.spiral_path` on a STRAIGHT flight, where it is
    # `required=False`; on a spiral it is required and is caught. This is
    # the correct behavior of a conditional obligation, not a hole.
    #
    # AN HONEST CAVEAT ABOUT THE STRENGTH OF THIS SLICE: a solo op is
    # discharged by SUBSTRING SEARCH, so "cut the witness" and "cut what
    # the certificate searches for" are one and the same act. The slice
    # proves that the obligation is tied to specific text, but NOT that
    # this text is executable — the model path supplies that key. The
    # difference is named here so that "verified" for a solo op and for a
    # model op are not read as equally strong.
}


def _grounded_corpus():
    """{op: (node, program name)} across both corpora."""
    out: dict[str, tuple[dict, str]] = {}
    for corpus in (SCOPE, GOLDEN):
        for pname, prog in corpus.items():
            body = {k: v for k, v in prog.items() if not k.startswith("__")}
            try:
                grounded = ground_mod.ground(_parse_and_check(body), SNAP)
            except Exception:
                continue
            for node in grounded:
                name = node.get("op")
                if name in spec.OPS and name not in out:
                    out[name] = (dict(node), pname)
    return out


def _checks_of(post):
    """Witnesses, WHATEVER the envelope is.

    `BarePost` is neither a list nor a string; the 08.11 traversal probe
    mistook it for a "legacy string post" and declared three graph ops
    untestable. The envelope is unpacked HERE, in one place, and only here."""
    if isinstance(post, BarePost):
        return list(post.checks)
    if isinstance(post, (list, tuple)):
        return list(post)
    return None


def _emittable_version(name, node):
    """The first version on which the op EMITS, and the reason if none.

    An op with a version axis (free loads were dropped by Autodesk after
    2023) is fully testable on "its own" version, and on a foreign one
    responds with a typed refusal — and these are DIFFERENT facts that
    must read differently."""
    refusals = []
    for ver in spec.REVIT_VERSIONS:
        try:
            post = _EMITTERS[name](dict(node), ver, "kir:l6")[2]
        except Exception as exc:
            refusals.append("%s:%s" % (ver, type(exc).__name__))
            continue
        if _checks_of(post):
            return ver, None
    return None, ("оп не эмитирует свидетелей ни на одной из шести версий "
                  "(%s)" % ", ".join(refusals))


def classify():
    """{op: (state, detail)} — exactly three states, each with a reason."""
    corpus = _grounded_corpus()
    verdicts: dict[str, tuple[str, str]] = {}
    for name, op_spec in sorted(spec.OPS.items()):
        if op_spec.family not in spec.WRITE_FAMILIES:
            continue
        if name in _UNCHECKABLE_REASONS:
            verdicts[name] = (UNCHECKABLE, _UNCHECKABLE_REASONS[name])
            continue
        if name not in corpus:
            verdicts[name] = (
                NOT_REACHED,
                "ни одна программа корпуса (scope + golden) не строит этот оп")
            continue
        node, pname = corpus[name]
        if name in spec.SOLO_OPS:
            # Solo op: the handle is not in _EMITTERS but in _SOLO_PROGRAMS.
            try:
                base = tc.certify_op(dict(node), "2026")
            except Exception as exc:
                verdicts[name] = (UNCHECKABLE,
                                  "certify_op падает: %s: %s"
                                  % (type(exc).__name__, str(exc)[:70]))
                continue
            if not base.proven:
                verdicts[name] = (
                    UNCHECKABLE,
                    "базовая линия НЕ зелена (%s) — мутации на ней "
                    "бессмысленны" % ("; ".join(base.gaps)[:90]))
                continue
            verdicts[name] = (
                VERIFIED,
                "2026: %d обязательств (сольный шов, разряд по "
                "маркеру), программа %s"
                % (len(_solo_obligations(name, node)), pname))
            continue
        if name not in _EMITTERS:
            verdicts[name] = (
                UNCHECKABLE,
                "нет записи в _EMITTERS и нет строки в _UNCHECKABLE_REASONS — "
                "состояние не названо")
            continue
        ver, why = _emittable_version(name, node)
        if ver is None:
            verdicts[name] = (UNCHECKABLE, why)
            continue
        try:
            base = tc.certify_op(dict(node), ver)
        except Exception as exc:
            verdicts[name] = (UNCHECKABLE,
                              "certify_op падает на %s: %s: %s"
                              % (ver, type(exc).__name__, str(exc)[:70]))
            continue
        if not base.proven:
            verdicts[name] = (
                UNCHECKABLE,
                "базовая линия НЕ зелена на %s (%s) — мутации на ней "
                "бессмысленны: срез ничего не меняет"
                % (ver, "; ".join(base.gaps)[:90]))
            continue
        keys = [c.obligation_key
                for c in _checks_of(_EMITTERS[name](dict(node), ver,
                                                    "kir:l6")[2])
                if c.obligation_key]
        verdicts[name] = (VERIFIED,
                          "%s: %d свидетелей, программа %s"
                          % (ver, len(keys), pname))
    return verdicts


def _solo_obligations(name, node):
    """Solo-op obligations that are REQUIRED for this program.

    A conditional obligation whose operand is not named is discharged by
    the ABSENCE of a witness — there is nothing to cut there, and counting
    that as a survivor would mean blaming correct behavior."""
    tc._ensure_table()
    out = []
    for o in tc.REFINEMENT[name].obligations:
        if not o.witness_markers:
            continue
        if o.conditional and o.param is not None and o.param not in node:
            continue
        out.append(o)
    return out


def _solo_survivors(name, node, ver):
    """Solo-op obligations whose slice did NOT fail the certificate.

    Slice = removal from the rendered program of all lines carrying this
    obligation's markers. ALL markers, not just the first: the level tie
    has two of them (`STAIRS_BASE_LEVEL_PARAM`/`..._TOP_...`), and slicing
    only one left the second in place — the first attempt on 08.11
    reported exactly such a false survivor."""
    original = _SOLO_PROGRAMS[name]
    out = []
    try:
        for o in _solo_obligations(name, node):
            def stripped(op, v, _ms=o.witness_markers, _o=original):
                text = _o(op, v)
                return "\n".join(
                    ln for ln in text.splitlines()
                    if not any(m in ln for m in _ms))
            _SOLO_PROGRAMS[name] = stripped
            try:
                if tc.certify_op(dict(node), ver).proven:
                    out.append(o.key or o.kind)
            except Exception:
                pass
            _SOLO_PROGRAMS[name] = original
    finally:
        _SOLO_PROGRAMS[name] = original
    return out


def _survivors(name, node, ver, keys):
    """Keys whose removal did NOT fail the certificate."""
    original = _EMITTERS[name]
    out = []
    try:
        for cut in keys:
            def mutated(op, v, stamp, isolation="atomic", _o=original, _c=cut):
                d, c, post, r = _o(op, v, stamp, isolation)
                kept = [k for k in _checks_of(post) if k.obligation_key != _c]
                return d, c, kept, r
            _EMITTERS[name] = mutated
            try:
                if tc.certify_op(dict(node), ver).proven:
                    out.append(cut)
            except Exception:
                # An empty post is UNCONSTRUCTIBLE (render_post rejects it) —
                # for an op with a single witness the slice raises an
                # exception, and this is a DETECTION stronger than a failed
                # certificate.
                pass
            _EMITTERS[name] = original
    finally:
        _EMITTERS[name] = original
    return out


class TheOracleDistinguishesThreeStates(unittest.TestCase):

    def test_no_write_op_is_silently_unclassified(self):
        verdicts = classify()
        writing = {n for n, o in spec.OPS.items()
                   if o.family in spec.WRITE_FAMILIES}
        self.assertEqual(set(verdicts), writing)
        for name, (state, detail) in sorted(verdicts.items()):
            with self.subTest(op=name):
                self.assertIn(state, (VERIFIED, UNCHECKABLE, NOT_REACHED))
                self.assertTrue(detail.strip(),
                                "%s: состояние без причины" % name)

    def test_every_uncheckable_op_names_a_printable_reason(self):
        """"Not testable" without a reason is indistinguishable from
        "forgot". The reason must be a STRING that the test prints, not
        something the reader is left to infer."""
        for name, (state, detail) in sorted(classify().items()):
            if state != UNCHECKABLE:
                continue
            with self.subTest(op=name):
                self.assertGreater(
                    len(detail), 40,
                    "%s: причина слишком коротка, чтобы что-то объяснить"
                    % name)
                self.assertNotIn("состояние не названо", detail,
                                 "%s: оп вне мутации и вне журнала причин"
                                 % name)

    def test_the_reason_ledger_has_not_outlived_its_truth(self):
        """A "not testable" record must fail once an op HAS BECOME testable
        — otherwise it will outlive its own truth, as has already happened
        twice in tool_doc."""
        corpus = _grounded_corpus()
        for name in sorted(_UNCHECKABLE_REASONS):
            with self.subTest(op=name):
                self.assertIn(name, spec.OPS)
                if name in _EMITTERS and name in corpus:
                    ver, _why = _emittable_version(name, corpus[name][0])
                    self.assertIsNone(
                        ver,
                        "%s теперь эмитирует свидетелей на %s — запись в "
                        "_UNCHECKABLE_REASONS устарела" % (name, ver))

    def test_every_verified_op_loses_proven_when_a_witness_is_cut(self):
        """LAW L6 on a GREEN base. Slicing each witness must fail
        `proven`; a survivor is a witness the certificate does not
        require."""
        from kir.tests.test_tolerance_provenance import (
            _UNPROMISED_WITNESSES)
        corpus = _grounded_corpus()
        for name, (state, detail) in sorted(classify().items()):
            if state != VERIFIED:
                continue
            ver = detail.split(":")[0]
            node = corpus[name][0]
            if name in spec.SOLO_OPS:
                with self.subTest(op=name, version=ver, seam="solo"):
                    self.assertEqual(
                        _solo_survivors(name, node, ver), [],
                        "%s: обязательство пережило вырезание своих "
                        "маркеров" % name)
                continue
            keys = [c.obligation_key
                    for c in _checks_of(_EMITTERS[name](dict(node), ver,
                                                        "kir:l6")[2])
                    if c.obligation_key]
            with self.subTest(op=name, version=ver):
                unexplained = [k for k in _survivors(name, node, ver, keys)
                               if (name, k) not in _UNPROMISED_WITNESSES]
                self.assertEqual(
                    unexplained, [],
                    "%s: свидетели пережили вырезание и не названы в "
                    "_UNPROMISED_WITNESSES: %s" % (name, unexplained))

    def test_the_solo_ops_are_verified_through_their_own_seam(self):
        """The assumption that "the seam is `_LIVE_STUB`" was WRONG: that
        stub treats an EMPTY post, while the standing test excludes solo
        ops by a list. The real seam is `_SOLO_PROGRAMS`."""
        verdicts = classify()
        for name in sorted(spec.SOLO_OPS):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))
                self.assertIn("сольный шов", verdicts[name][1])

    def test_the_graph_ops_are_verified_not_skipped(self):
        """Ops with a "one op → many elements" leverage: for these the
        cost of an invisible defect is highest. The 08.11 probe declared
        them untestable by mistaking `BarePost` for a string; this test
        holds the opposite."""
        verdicts = classify()
        for name in ("create_pipe_system", "route_pipe_system",
                     "route_duct_system"):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))

    def test_version_gated_ops_are_verified_on_a_version_that_emits(self):
        """"Deliberately refuses on 2024+" and "not verified" are
        different facts. The oracle must search for a version on which the
        op IS EXPRESSIBLE."""
        verdicts = classify()
        for name in ("create_point_load", "create_line_load",
                     "create_area_load"):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))


if __name__ == "__main__":
    for _n, (_s, _d) in sorted(classify().items()):
        print("%-14s %-28s %s" % (_s, _n, _d))
