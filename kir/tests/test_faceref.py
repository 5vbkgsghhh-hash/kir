"""SELECTOR STAGE TWO: the program NAMES a face (`kir/faceref.py`).

What is proven here, by section:

  FlagOffIsAbsentTests        a flag turned off is INDISTINGUISHABLE from the form's absence
  GrammarTests                the form and its refusals — each names ITS OWN cause
  NoSilentPickTests           zero and "several" are refusals, not a choice
  CoherenceWithFrozenDialectTests   a nested `by=ref` is visible to ALL traversals
  WitnessTests                the witness reads the RESULT and is not vacuous
  InstrumentTests             the flag is VISIBLE to the instrument (otherwise it sits in storage)

WHAT IS NOT HERE, AND WHY. A live Revit. The "no candidate" and "several
candidates" refusals are RUNTIME ones: C# inside Revit accepts them, and offline what is checked is
exactly what is checkable offline — that the refusal is EMITTED, typed, tied
to the op, and rendered in the form of its own isolation. Asserting here that they fired
would mean signing an axis nobody has read.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import faceref                                  # noqa: E402
from kir.compiler import compile_program                 # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAP   # noqa: E402




IN_VIEW = {"by": "element_id", "value": 900}
REF_W1 = {"by": "ref", "value": "W1"}
REF_W2 = {"by": "ref", "value": "W2"}
PINNED = {"by": "element_id", "value": 12345}


def wall(oid="W1", **kw):
    op = {"op": "create_wall", "id": oid, "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(kw)
    return op


def face(of, **pred):
    return {"by": "face", "of": of, "predicate": pred}


def dim(refs, oid="D1"):
    return {"op": "create_dimension", "id": oid, "in_view": IN_VIEW,
            "refs": refs, "line_at": [3000, 500]}


def prog(ops):
    return {"ir_version": "1.0", "intent": "face-test", "ops": ops}


def build(ops, ver="2023", isolation="atomic"):
    return compile_program(prog(ops), revit_version=ver, snapshot=SNAP,
                           bulk=True, isolation=isolation)


class _FlagOn:
    """The operator flag is ON for the duration of the test — and removed afterward, whatever the outcome."""

    def __enter__(self):
        self._old = os.environ.get(faceref.FACE_REF_FLAG)
        os.environ[faceref.FACE_REF_FLAG] = "1"
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop(faceref.FACE_REF_FLAG, None)
        else:
            os.environ[faceref.FACE_REF_FLAG] = self._old
        return False


TWO_WALLS = [wall("W1"), wall("W2", p0_mm=[0, 4000], p1_mm=[6000, 4000])]
NAMED = TWO_WALLS + [dim([face(REF_W1, side="exterior"),
                          face(REF_W2, side="exterior")])]
PLAIN = TWO_WALLS + [dim([REF_W1, REF_W2])]


class FlagOffIsAbsentTests(unittest.TestCase):
    """LAW: what is absent stays absent.

    The flag is OFF by default, and while off it must be indistinguishable from the
    form not existing at all — otherwise «off» means «on just a little»."""

    def test_flag_is_off_by_default(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        self.assertFalse(faceref.face_ref_enabled())

    def test_program_without_faces_is_byte_identical(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        off = build(PLAIN)
        with _FlagOn():
            on = build(PLAIN)
        self.assertTrue(off.ok and on.ok)
        # BYTE FOR BYTE, not "equivalent": any difference in the text is a difference
        # in program_digest, that is, a different program under the same signature.
        self.assertEqual(off.csharp, on.csharp)

    def test_named_face_refused_while_flag_is_off(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        out = build(NAMED)
        self.assertFalse(out.ok)
        codes = {d.code for d in out.diagnostics}
        self.assertIn("KIR-G002", codes)
        # The refusal must NAME the flag: "form not accepted" without the gate's name
        # sends you off to read the source.
        self.assertTrue(any(faceref.FACE_REF_FLAG in d.message_ru
                            for d in out.diagnostics))

    def test_helpers_absent_from_emission_without_named_face(self):
        with _FlagOn():
            out = build(PLAIN)
        self.assertTrue(out.ok)
        for token in ("__faceWalk_", "__faceKeep_", "__fbWant_"):
            self.assertNotIn(token, out.csharp)

    def test_decode_schema_is_byte_identical_while_flag_is_off(self):
        # A fail-closed bounded-decode schema: as long as the variant is not in it,
        # the model physically cannot produce a face selector.
        import json
        from kir import schema_gen, spec

        def rendered() -> str:
            return json.dumps(schema_gen._op_schema(
                spec.OPS["create_dimension"]), sort_keys=True)

        os.environ.pop(faceref.FACE_REF_FLAG, None)
        off = rendered()
        with _FlagOn():
            on = rendered()
        self.assertNotIn(faceref.BY_FACE, off)
        self.assertIn(faceref.BY_FACE, on)
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        self.assertEqual(off, rendered())


class GrammarTests(unittest.TestCase):
    """The second stage's form and its refusals. Each refusal names ITS OWN cause."""

    def _refuse(self, refs):
        with _FlagOn():
            out = build(TWO_WALLS + [dim(refs)])
        self.assertFalse(out.ok, "форма должна была быть отвергнута")
        return " | ".join(d.message_ru for d in out.diagnostics)

    def test_accepts_the_whole_form(self):
        with _FlagOn():
            out = build(NAMED)
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_of_carries_a_whole_selector_not_a_bare_op_id(self):
        # This is the file's central decision: `of` is a SELECTOR, not a string.
        msg = self._refuse([{"by": "face", "of": "W1",
                             "predicate": {"side": "exterior"}}, REF_W2])
        self.assertIn(".of", msg)

    def test_unknown_key_in_selector(self):
        msg = self._refuse([{"by": "face", "of": REF_W1,
                             "predicate": {"side": "exterior"},
                             "index": 0}, REF_W2])
        self.assertIn("index", msg)

    def test_predicate_is_required(self):
        msg = self._refuse([{"by": "face", "of": REF_W1}, REF_W2])
        self.assertIn("predicate", msg)

    def test_empty_predicate_is_refused(self):
        # A description that EVERY face satisfies is not a face's name.
        msg = self._refuse([face(REF_W1), REF_W2])
        self.assertIn("predicate", msg)

    def test_unknown_predicate_key(self):
        msg = self._refuse([face(REF_W1, largest=True), REF_W2])
        self.assertIn("largest", msg)

    def test_side_is_a_closed_enum_named_by_revit(self):
        msg = self._refuse([face(REF_W1, side="outside"), REF_W2])
        for name in faceref.SIDES:
            self.assertIn(name, msg)

    def test_normal_must_be_three_numbers(self):
        for bad in ([0, 0], [0, 0, "z"], "up", [0, 0, True]):
            with self.subTest(bad=bad):
                msg = self._refuse([face(REF_W1, normal=bad), REF_W2])
                self.assertIn("normal", msg)

    def test_two_identical_face_selectors_are_a_zero_size_dimension(self):
        msg = self._refuse([face(REF_W1, side="exterior"),
                            face(REF_W1, side="exterior")])
        self.assertIn("повтор", msg.lower())

    def test_two_different_faces_of_one_element_are_legal(self):
        # The identity key includes the PREDICATE, otherwise two different faces of one
        # wall would read as a duplicate — and a meaningful count would be rejected.
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face(REF_W1, side="exterior"),
                              face(REF_W1, side="interior")])])
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_carrier_is_a_named_list_not_the_param_kind(self):
        # `move_elements.targets` is the same `refs_w` kind, but "move a face"
        # means nothing. The form is allowed by name, not by kind.
        with _FlagOn():
            out = build([wall("W1"),
                         {"op": "move_elements", "id": "M1",
                          "targets": [face(REF_W1, side="exterior")],
                          "delta_mm": [100, 0, 0]}])
        self.assertFalse(out.ok)
        self.assertTrue(any("create_dimension.refs" in d.message_ru
                            for d in out.diagnostics),
                        [d.message_ru for d in out.diagnostics])


class NoSilentPickTests(unittest.TestCase):
    """LAW: the description FILTERS, the CARDINALITY decides. Zero and "several" are refusals.

    A live measurement of 02.08 (Snowdon, a paired trial): the C# arm took `.FirstOrDefault()`
    — 1 door type out of 62 — and built SILENTLY. These tests hold both boundaries."""

    def _cs(self, isolation="atomic"):
        with _FlagOn():
            out = build(NAMED, isolation=isolation)
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
        return out.csharp

    def test_no_candidate_is_a_typed_op_bound_refusal(self):
        cs = self._cs()
        self.assertIn("Count == 0", cs)
        self.assertIn("нет грани, отвечающей описанию", cs)
        # The refusal repeats the DESCRIPTION: "face not found" without it sends
        # the author off to reread their own program.
        self.assertIn("сторона «exterior»", cs)

    def test_ambiguity_is_a_refusal_that_names_the_count(self):
        cs = self._cs()
        self.assertIn("Count > 1", cs)
        self.assertIn("Count.ToString()", cs)
        self.assertIn("Компилятор НЕ выбирает за автора", cs)
        # A NAMED NEXT MOVE, not just a diagnosis.
        self.assertIn("СЛЕДУЮЩИЙ ХОД", cs)

    def test_both_refusals_render_in_the_form_their_isolation_needs(self):
        # The refusal has ONE owner (`emit_utils.refuse_stmt`). Typed by
        # hand, it would roll back neighbors in `per_op` — a defect closed on 28.07.
        atomic = self._cs("atomic")
        per_op = self._cs("per_op")
        self.assertIn("__t.RollBack(); return __Refuse(", atomic)
        self.assertNotIn("throw __OpRefuse(", atomic)
        self.assertIn("throw __OpRefuse(", per_op)

    def test_the_walk_counts_and_never_stops_at_the_first_hit(self):
        # An early exit would turn "there are two of them" into "took the first one": `Solid.Faces`'s
        # order is NOT documented, so "the first matching one" is a number with no
        # meaning. The set's cardinality does not depend on iteration order.
        cs = self._cs()
        walk = cs[cs.index("void __faceWalk_"):]
        walk = walk[:walk.index("void __faceKeep_")] if "void __faceKeep_" in walk else walk
        self.assertNotIn("FirstOrDefault", cs)
        self.assertNotIn("break;", walk)

    def test_no_invented_tolerance_anywhere_in_the_emitted_comparison(self):
        # Parallelism — with Revit's OWN native test. Not a single number of our own.
        cs = self._cs()
        self.assertIn("IsZeroLength()", cs)
        self.assertIn("CrossProduct", cs)
        walk = cs[cs.index("void __faceKeep_"):cs.index("void __faceWalk_")]
        for invented in ("1e-", "0.0001", "0.001", "Math.Abs("):
            self.assertNotIn(invented, walk)

    def test_symbol_geometry_not_instance_geometry(self):
        # The annotation branch's trap (`9c5c7492`): `GetInstanceGeometry()`
        # compiles 6/6 and refuses LIVE — it is a documented COPY,
        # whose references are unusable for creating elements.
        cs = self._cs()
        self.assertIn("GetSymbolGeometry()", cs)
        self.assertNotIn("GetInstanceGeometry", cs)
        # The coordinates are returned to the model via the instance transform.
        self.assertIn(".Multiply(__fwGi.Transform)", cs)


class CoherenceWithFrozenDialectTests(unittest.TestCase):
    """A nested `{"by": "ref"}` must be visible to ALL reference traversals.

    This is exactly why `of` carries a whole selector instead of a bare op id. The generic
    traversals (`design_check._ref_targets`, `course._mark_cross_phase`) descend
    into any nested dict; the compiler's graph traversal is NOT generic, and it had
    to be taught. Both sides are checked here."""

    FACE_SEL = face(REF_W1, side="exterior")

    def test_generic_ref_walk_finds_the_nested_ref(self):
        from kir.design_check import _ref_targets
        self.assertEqual(_ref_targets(self.FACE_SEL), ["W1"])
        self.assertIn("W1", _ref_targets(dim([self.FACE_SEL, REF_W2])))

    def test_dag_sees_the_edge_dangling_ref_is_refused(self):
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face({"by": "ref", "value": "NOPE"},
                                   side="exterior"), REF_W1])])
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", {d.code for d in out.diagnostics})

    def test_dag_sees_the_edge_forward_ref_is_refused(self):
        # A FORWARD reference: the producing op stands LATER. Without a graph edge this
        # would pass silently, and the C# would reference a variable not yet declared.
        with _FlagOn():
            out = build([dim([face(REF_W1, side="exterior"), PINNED]),
                         wall("W1")])
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", {d.code for d in out.diagnostics})

    def test_bundle_contract_refuses_a_cross_program_face_ref(self):
        # The same law as for stage 1, and WITHOUT A SINGLE CHANGE to
        # `design_check`: a neighboring program in the batch is a separate transaction, and by
        # the time it runs, the id no longer exists. A bare string in `of` would have
        # passed silently here — and a dangling reference would have ridden into execution.
        from kir.design_check import _merge_bundle, BundleContractError
        with self.assertRaises(BundleContractError) as caught:
            _merge_bundle([[wall("W1")], [dim([self.FACE_SEL, PINNED])]])
        self.assertIn("W1", str(caught.exception))

    def test_inner_ref_is_normalised_like_a_grade_one_selector(self):
        # Stage 1 trims whitespace around the id; an untrimmed stage 2 would give
        # KIR-L003 on a reference that points correctly.
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face({"by": "ref", "value": "  W1  "},
                                   side="exterior"),
                              face({"by": "ref", "value": "W1"},
                                   side="interior")])])
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_selection_closure_keeps_the_producing_op(self):
        from kir.live.transfer import refs_of
        edges = refs_of(dim([self.FACE_SEL, REF_W2]))
        self.assertIn(("refs[0].of", "W1"), edges)
        self.assertIn(("refs[1]", "W2"), edges)

    def test_ground_never_sees_the_second_grade(self):
        # `refs` is not part of `ospec.grounded` — the second stage lives entirely in
        # the strip of write targets that ground never looks into. If that stops
        # being true, the test will fail here, not live.
        from kir import spec
        grounded = {p for p, _pool, _req in spec.OPS["create_dimension"].grounded}
        self.assertNotIn("refs", grounded)


class WitnessTests(unittest.TestCase):
    """What the witness CAN and CANNOT say about a named face."""

    def test_named_face_adds_a_check_that_reads_the_result(self):
        with _FlagOn():
            out = build(NAMED)
        cs = out.csharp
        # What is read is the BUILT size, not that the call took place.
        self.assertIn("__el_D1.References", cs)
        self.assertIn("ConvertToStableRepresentation(doc)", cs)
        self.assertIn("named face is not among the built dimension References", cs)

    def test_the_check_is_absent_when_it_would_be_vacuous(self):
        # A check that cannot fail is worse than no check. Without a
        # named face, the list of expected signatures would be EMPTY, and the check
        # would always be green — so it simply does not exist.
        with _FlagOn():
            out = build(PLAIN)
        self.assertNotIn("named face is not among", out.csharp)
        self.assertNotIn("__fbWant_", out.csharp)

    def test_unreadable_signature_fails_the_witness_not_passes_it(self):
        # `catch` CLEARS THE FLAG, rather than swallowing it: a swallowed
        # read would have made the check unfailable.
        with _FlagOn():
            cs = build(NAMED).csharp
        self.assertIn("catch { __fbOk_D1 = false; }", cs)
        self.assertIn("!__fbRead_D1 ||", cs)

    def test_owner_level_witness_alone_cannot_speak_about_a_face(self):
        # The neighboring check reads `Reference.ElementId` — the OWNER of
        # the reference. It stays equally green no matter which face of the
        # same element the dimension attaches to; that is exactly why the
        # named face needs one of its own.
        with _FlagOn():
            named = build(NAMED).csharp
            plain = build(PLAIN).csharp
        for cs in (named, plain):
            self.assertIn("References do not match requested refs", cs)


class InstrumentTests(unittest.TestCase):
    """The flag the instrument cannot see sits in the store BY CONSTRUCTION."""

    def test_flag_name_constant_matches_the_literal_in_the_gate(self):
        # The owner's inventory looks for flags by a TEXT regex; a call
        # through a constant it will not see. That is why the name is
        # written twice, and it is this test — not a convention — that keeps
        # the two copies from drifting apart. The call form changed on
        # 02.09.2026 (`os.getenv` -> the `env.get` door, see
        # `kir/faceref.py`), the pair stays the same.
        import inspect
        src = inspect.getsource(faceref.face_ref_enabled)
        self.assertIn(f'env.get("{faceref.FACE_REF_FLAG}"', src)

    def test_gate_is_a_zero_arg_bool_predicate(self):
        # The second half of the same regex: `def имя() -> bool:`.
        import inspect
        sig = inspect.signature(faceref.face_ref_enabled)
        self.assertEqual(len(sig.parameters), 0)
        # `from __future__ import annotations` -> the annotation arrives as
        # a STRING, and the instrument's regex reads exactly that.
        self.assertIn(sig.return_annotation, (bool, "bool"))


if __name__ == "__main__":
    unittest.main()
