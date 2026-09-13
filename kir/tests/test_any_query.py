"""Any-Query acceptance test (SPEC §14.2, operator directive 2026-07-16).

The product invariant: for ANY request the system returns exactly one of
(a) a structurally-correct answer, (b) a typed refusal WITH a tail route.
Out-of-coverage kinds (MEP internals, worksharing, exotics — the §10
anti-scope) must produce 100% typed handoffs, zero exceptions, zero silent
degradations, and each must land in the rejection telemetry
(contract /root/kukai-cube/KIR_QUEUE_CONTRACT.md — schema v1, RAW kinds).
"""
import json
import os
import tempfile
import unittest

# A process-unique directory keeps the suite hermetic across users, parallel
# workers and stale files from a killed prior run.  A fixed /tmp filename made
# the test fail before exercising KIR whenever another user owned that file.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="kir-anyquery-test-")
_QUEUE = os.path.join(_TEST_DIR.name, "rejections.jsonl")
os.environ["KIR_REJECTIONS_PATH"] = _QUEUE

from kir.compiler import compile_program  # noqa: E402

# Views that EXITED the anti-scope on 27.07. Work is carried out by
# discipline section, each with its own owner, so the kind registry grew
# from 21 to 51 — the structural/HVAC/plumbing/electrical disciplines were
# represented in it by a single line per section. Moving one here is
# legitimate under exactly one condition: the kind can now be answered
# HONESTLY, that is, it has a collector giving a correct count. Below are
# the ones for which that collector has appeared; they are checked
# positively (`test_newly_covered_kinds_answer_instead_of_handing_off`),
# so that the list does not turn into a way to quietly carry kinds out
# from under the invariant.
NEWLY_COVERED_KINDS = [
    "conduit", "sprinkler", "curtain_panel", "area", "space",
    "railing", "ramp", "furniture",
    # The group_by wave (28.07): exited the anti-scope in 0a16e8f5
    # ("sections in the tables", 21->51 kinds), but were not entered into
    # this list at the time — the registration itself in KINDS was not
    # checked by a test. Confirmed by history: `git show
    # 440a8afe:.../registry_base.py` does not know them,
    # `git show 0a16e8f5:.../registry_base.py` does know them (0 -> 1
    # KindSpec each). Live refusals carrying these same words sit in
    # data/telemetry/kir_rejections.jsonl (UNSUPPORTED_KIND before
    # 27.07 19:03).
    "structural_framing",    # «Каркас несущий»
    "mechanical_equipment",  # «Мех. оборудование»
    "plumbing_fixture",      # «Сантехника»
    "specialty_equipment",   # «Спец. оборудование» / «Специальное оборудование»
    "generic_model",         # «Обобщённые модели»
]

OUT_OF_COVERAGE_KINDS = [
    # anti-scope / not-yet-covered, every one must hand off — never guess:
    "mep_system", "fitting",
    "workset", "revision", "schedule", "schedule_field", "topography",
    "toposolid", "mass", "mullion", "rebar",
    "point_cloud", "rvt_link", "keynote", "filled_region",
    "zone", "parking",
    "design_option", "phase", "material_asset", "other",
    # The 9th kind from the live decompile of 27.07 («Опоры»,
    # data/telemetry/kir_rejections.jsonl, query_id 30614d9c185ec17c) is
    # LEFT here deliberately, not guessed at: there are several live
    # candidates (OST_RailingSupport, by coincidence in the same batch as
    # «Перила», OST_BridgeBearings, structural connection anchors) and not
    # one of them is confirmed by a live check — this wave is not allowed
    # to touch Revit (see the commit), and a silently wrong count is worse
    # than a typed refusal. The next live pass should ask the
    # operator/query context, rather than substitute a guess.
    "Опоры",
    # nonsense / adversarial (must stay RAW in telemetry — they ARE the signal):
    "unicorn", "стена", "wall​", "OST_ImportInstances",
]

#: 🔴 MOVED HERE FROM THE ADVERSARIAL SET ON 15.08.2026, AND THIS IS NOT A
#: WEAKENING OF THE INVARIANT.
#:
#: `"Wall "` and `"WALL"` used to stand above as proof that "the compiler
#: does not guess". The merge brought in a KIND-NAME RESOLUTION LADDER
#: (`compiler._check_kind`, `_canon_kind`, `_kind_canon_index`), and it
#: made a deliberate decision: a single match within a CLOSED set is the
#: same name, typed differently, not a choice between two. On a collision
#: it REFUSES (the index holds a list, not the first name), and the
#: refusal names the neighbor.
#:
#: So these two are no longer "out of scope": they ARE in scope, just
#: written differently. The anti-scope invariant is untouched — the
#: adversarial cases that must refuse stayed above, and among them is
#: `"wall​"` with zero width: `\s` does not strip it, the ladder does not
#: fold it in, the refusal stands.
#:
#: 🔴 A NAMED DEBT THIS TEST DOES NOT CLOSE. The ladder fires SILENTLY:
#: `_check_kind` returns the corrected name and puts nothing into the
#: receipt. By this tree's own law, "a choice the caller cannot see is a
#: `.FirstOrDefault()` with a good reputation" (the same argument by which
#: `ground` MUST print `grounding_report`). What is written here is that
#: the correction HAPPENS; whether it is VISIBLE to the author is not
#: checked, because there is no channel for it yet. It closes together
#: with the channel, not with a separate test.
RESOLVED_BY_THE_NAME_LADDER = ["Wall ", "WALL"]


class AnyQueryInvariant(unittest.TestCase):
    # THE ENVIRONMENT IS PINNED PER TEST, NOT ONCE AT IMPORT (12.08.2026).
    #
    # The tests below read and write EXACTLY `_QUEUE` (lines 72/118/126),
    # but the key was only ever set on line 20, at module import.
    # `test_shadow.py:17` assigns that same key DIRECTLY (the other ~80
    # modules do `setdefault`, which does nothing on an occupied key), and
    # pytest imports ALL modules at collection, before the first test.
    # So whichever module was imported last wins, and that depends on the
    # order of the arguments:
    #
    #   pytest test_any_query.py test_shadow.py   -> shadow wins, the module is blind
    #   pytest test_shadow.py test_any_query.py   -> its own wins, everything green
    #
    # Hence "passes alone, fails in the suite": the value was asserted at
    # import and read in the tests, and nothing forced the two to agree.
    # The cure is not restoring the constant, but having each test set up
    # the state it needs itself and return what it OBSERVED.
    def setUp(self):
        self._previous_queue = os.environ.get("KIR_REJECTIONS_PATH")
        os.environ["KIR_REJECTIONS_PATH"] = _QUEUE

    def tearDown(self):
        if self._previous_queue is None:
            os.environ.pop("KIR_REJECTIONS_PATH", None)
        else:
            os.environ["KIR_REJECTIONS_PATH"] = self._previous_queue

    def test_out_of_coverage_is_typed_handoff(self):
        if os.path.exists(_QUEUE):
            os.remove(_QUEUE)
        for kind in OUT_OF_COVERAGE_KINDS:
            with self.subTest(kind=kind):
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"anyq-{kind!r}")
                self.assertFalse(out.ok, f"{kind!r} must not silently compile")
                self.assertIsNone(out.csharp)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes, "panic is forbidden")
                self.assertIn("KIR-G001", codes, f"{kind!r}: want typed unsupported-kind")
                self.assertIsNotNone(out.handoff, f"{kind!r}: refusal must carry a route")
                self.assertEqual(out.handoff["route"], "recipe-path")

    def test_a_spelling_variant_resolves_and_does_not_hand_off(self):
        """A spelling variant of the same kind IS RESOLVED, not shipped off to a recipe.

        A control on both sides, otherwise the assertion is degenerate: the
        spelling variant MUST COMPILE, while adversarial junk from
        `OUT_OF_COVERAGE_KINDS` must NOT. Both ends in one test, so that
        "green because we accept everything" does not look like "green
        because we discriminate"."""
        for kind in RESOLVED_BY_THE_NAME_LADDER:
            with self.subTest(kind=kind):
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"ladder-{kind!r}")
                self.assertTrue(
                    out.ok,
                    f"{kind!r}: одно совпадение в закрытом множестве — то же "
                    f"имя; диагностики: {[d.code for d in out.diagnostics]}")
                self.assertNotIn("KIR-G001", [d.code for d in out.diagnostics])

        # THE OTHER END: the ladder is not omnivorous. Zero matches — a refusal.
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "kind": "unicorn"}],
        }, query_id="ladder-negative")
        self.assertFalse(out.ok, "лестница приняла бессмыслицу — она всеядна")
        self.assertIn("KIR-G001", [d.code for d in out.diagnostics])

    def test_newly_covered_kinds_answer_instead_of_handing_off(self):
        """A kind that exited the anti-scope MUST ANSWER, not stay silent.

        Otherwise, moving a kind from `OUT_OF_COVERAGE_KINDS` to
        `NEWLY_COVERED_KINDS` would be a way to remove it from under the
        invariant while doing nothing: the refusal test would stop seeing
        it, and an answer test would never appear. Here is that second
        end: every moved kind compiles into C# and collects ITS OWN
        category — not "just anything".
        """
        from kir import spec
        for kind in NEWLY_COVERED_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(kind, spec.KINDS, f"{kind!r} нет в реестре видов")
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"covered-{kind!r}")
                self.assertTrue(
                    out.ok, f"{kind!r}: {[d.code for d in out.diagnostics]}")
                self.assertIsNotNone(out.csharp)
                collector = spec.KINDS[kind].collector_cs
                self.assertIn(collector, out.csharp,
                              f"{kind!r}: собран не свой коллектор")
                self.assertTrue(
                    spec.KINDS[kind].discipline,
                    f"{kind!r}: вид без раздела")

    def test_telemetry_contract_v1(self):
        if os.path.exists(_QUEUE):
            os.remove(_QUEUE)
        compile_program({"ir_version": "1.0", "intent": "x",
                         "ops": [{"op": "query_count", "kind": "OST_ImportInstances"}]},
                        query_id="join-key-1")
        compile_program({"ir_version": "1.0",
                         "ops": [{"op": "query_inspect", "target": {"by": "vibe", "value": 1}}]},
                        query_id="join-key-2")
        with open(_QUEUE, encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        self.assertEqual(len(recs), 2)
        r0, r1 = recs
        self.assertEqual(r0["v"], 1)
        self.assertEqual(r0["source"], "kir")
        self.assertEqual(r0["reject_code"], "UNSUPPORTED_KIND")
        self.assertEqual(r0["kind_requested"], "OST_ImportInstances")   # RAW, unnormalized
        self.assertEqual(r0["op_requested"], "count")
        self.assertEqual(r0["query_id"], "join-key-1")
        self.assertIn("×", r0["cell"])
        self.assertEqual(r1["reject_code"], "SLOT_RESOLUTION_FAILED")
        self.assertEqual(r1["query_id"], "join-key-2")

    def test_queue_failure_is_fail_open(self):
        # WE RESTORE WHAT WAS OBSERVED, NOT WHAT WAS REMEMBERED (12.08.2026).
        # This used to read `= _QUEUE` — this module's own constant, set by
        # it on line 20 at import.  But `test_shadow.py:17` also assigns
        # that same key DIRECTLY (not `setdefault`, like the other ~80
        # modules), and pytest imports everything at collection, before
        # the first test — so by the time this runs, a FOREIGN path sits
        # here.  `finally` was restoring its own, the environment guard
        # caught the substitution in teardown, and in the suite this read
        # as an `ERROR` on exactly this test, even though the file is
        # green on its own.  The value was ASSERTED on line 20 and READ
        # here; nothing forced the two to agree.  The minimal
        # reproduction is two files:
        #   pytest kir/tests/test_any_query.py kir/tests/test_shadow.py
        previous = os.environ.get("KIR_REJECTIONS_PATH")
        os.environ["KIR_REJECTIONS_PATH"] = "/proc/definitely/not/writable/q.jsonl"
        try:
            out = compile_program({"ir_version": "1.0",
                                   "ops": [{"op": "query_count", "kind": "unicorn"}]})
            self.assertFalse(out.ok)           # refusal still typed
            self.assertIsNotNone(out.handoff)  # route still present
        finally:
            if previous is None:
                os.environ.pop("KIR_REJECTIONS_PATH", None)
            else:
                os.environ["KIR_REJECTIONS_PATH"] = previous


if __name__ == "__main__":
    unittest.main()
