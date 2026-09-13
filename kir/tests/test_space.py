"""wave/space (2026-08-10): create_space — the HVAC space (OST_MEPSpaces).

WHY THIS WAVE IS A MEASUREMENT OVER THE CORPUS, NOT A WISH. As of 10.08, over
76 saved decompiles (`backend/data/decompile/*/L0.jsonl`, the
`category_status` and `document.census` records):

    decompiles where extraction looked at OST_MEPSpaces at all      44 of 76
    decompiles with a nonzero space count                             6
    buildings                                                         2
      Snowdon Towers Sample Electrical (snowdon_elec_v1)             80
      Snowdon Towers Sample Plumbing      (plumb_v1..v4)             43
      Snowdon Towers Sample Architectural (plumb_v5)                 46
                                                                  ----
                                                                   169

    CORRECTION 11.08 TO THIS SAME WAVE'S MEASUREMENT: this used to read
    "126 / 2 buildings". The `snowdon_plumb_v5` directory carries in its L0
    header `doc_name: "Snowdon Towers Sample Architectural"` — a THIRD
    document, not a fifth plumbing revision. The directory name had been
    taken for the document name; the document is named only by `doc_name`.
    for all six: expected_count == extracted_count, state=complete

That is, READING spaces has been able to, and has always been able to, while
the lifter has not: `lift.py`'s candidate table knows "OST_Rooms" and does
not know "OST_MEPSpaces", so all 126 elements were falling into "the op does
not exist" atoms. That was true; with this wave it stopped being true.

THE API WAS TAKEN FROM THE ASSEMBLIES, NOT FROM THE DOCUMENTATION. Two
independent instruments, 10.08: reflection over six `RevitAPI.dll`
assemblies (`data/api_surface/api_signatures_*.json`), and a live
compilation on :52412 run SEPARATELY for each version.

    doc.Create.NewSpace(Level, UV)        -> Space               6/6
    doc.Create.NewSpace(Level, Phase, UV) -> Space               6/6
    doc.Create.NewSpace(Phase)            -> Space               6/6
    the parameterless overload does NOT EXIST                CS1501, 0/6
    the return type is proven by CS0029 ("Cannot implicitly convert type
        'Autodesk.Revit.DB.Mechanical.Space' to 'int'") on all six
    Space.Location/.Area/.Volume/.Number/.Name/.LevelId/.Level   6/6
    SpatialElement.GetBoundarySegments(...)                      6/6
    BuiltInCategory.OST_MEPSpaces                                6/6
    Space.Unplace()                                      CS1061, 0/6
        even though Room.Unplace() exists                        6/6

Structure mirrors test_room.py (Registry / VersionAxis / Signature /
TwoBadOutcomes / Witnesses / Acceptance / Reverse / PBT).
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_space_queue.jsonl"))

from kir import authoring, spec                             # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.registry_base import IdentityCardinality           # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_space"
LVL = {"by": "element_id", "value": 42}
LVL_BY_NAME = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}


def _prog(ops, intent="space-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _space(oid="SP1", **kw):
    op = {"op": OP, "id": oid, "xy": [4000, 3000], "level": LVL}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _checks(ver="2024", op=None):
    """The op's witnesses as OBJECTS — not as text, so as not to measure
    prose."""
    from kir import ground as ground_mod
    from kir.authoring import _EMITTERS
    from kir.compiler import _parse_and_check
    grounded = ground_mod.ground(
        _parse_and_check(_prog([op or _space()])), SNAPSHOT)
    _d, create, checks, readback = _EMITTERS[OP](
        dict(grounded[0]), ver, "kir:test")
    return create, checks, readback


# ── registry ───────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_op_is_registered(self):
        self.assertIn(OP, spec.OPS)

    def test_it_declares_itself_a_writer(self):
        self.assertTrue(spec.OPS[OP].writes_model)
        self.assertEqual(spec.OPS[OP].family, "authoring")

    def test_it_lives_in_the_room_family_module(self):
        """Space is kin to the separator (both are SpatialElement, both
        concern the volume boundary), while ops_authoring.py, where
        create_room lives, is the busiest file in the registry, one that
        every wave writes to at once."""
        from kir import ops_room
        self.assertIn(OP, [op.name for op in ops_room.OPS])

    def test_the_result_is_one_identity_and_it_is_referenceable(self):
        """Unlike the separator (MANY identities): NewSpace returns exactly
        one Space, so the next op is entitled to reference it."""
        result = spec.OPS[OP].result
        self.assertIs(result.identity_cardinality, IdentityCardinality.ONE)
        self.assertEqual(result.identity_field, "id")
        self.assertTrue(result.referenceable)

    def test_it_grounds_only_the_level(self):
        self.assertEqual(
            {p: pool for p, pool, _ in spec.OPS[OP].grounded},
            {"level": "levels"})


# ── signature: narrow ON PURPOSE, and the compiler holds it there ───────────

class SignatureIsDeliberatelyNarrow(unittest.TestCase):
    """v1 — exactly a point and a level. Every absence is paid for by a
    measurement."""

    def test_the_op_takes_exactly_xy_and_level(self):
        self.assertEqual({p.name for p in spec.OPS[OP].params},
                         {"xy", "level"})

    def test_a_name_is_refused_by_the_compiler_not_merely_ignored(self):
        """MEASUREMENT 04.08 (live Revit 2026), recorded in the create_room
        emitter: the `Room.Name` setter stores ONLY the name, while the
        getter returns "the name AND the number" (`"KIR_GAP_ROOM_1 1"`),
        which is why the witness was rolling back EVERY correctly built
        room.

        Whether `Space` behaves the same way cannot be settled offline —
        but reflection over six assemblies narrows the question: `Name` is
        declared EXACTLY ONCE, on `SpatialElement`, and neither Room nor
        Space overrides it. That is, the concatenation is a property of the
        SAME member. The stakes are asymmetric: an error in this direction
        destroys a CORRECT build, while the absence of a parameter destroys
        nothing."""
        out = compile_program(_prog([_space(name="Венткамера")]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_a_number_is_refused_the_same_way(self):
        out = compile_program(_prog([_space(number="1")]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_a_type_is_refused_because_the_api_has_no_type_argument(self):
        """`NewSpace` has no type argument at all, and for all 169 spaces
        in the corpus `type_id`/`type_name` are empty. A type pool would
        promise something the API does not deliver."""
        out = compile_program(
            _prog([_space(type={"by": "name", "value": "Пространство"})]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_the_point_is_two_dimensional(self):
        """Z on a spatial element sets the LEVEL: `SpatialElement.Location`
        is documented as "Z ... not changeable"."""
        out = compile_program(_prog([_space(xy=[1000, 2000, 3000])]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_level_is_mandatory(self):
        op = {"op": OP, "id": "SP1", "xy": [4000, 3000]}
        out = compile_program(_prog([op]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))


# ── version axis: it does NOT exist, and this is a measurement ──────────────

class VersionAxis(unittest.TestCase):

    def test_it_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_space()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("doc.Create.NewSpace(", out.csharp)

    def test_the_emitted_csharp_is_byte_identical_across_the_six(self):
        """THERE IS NO VERSION AXIS — and this is a verifiable claim, not a
        hope. Three NewSpace overloads exist on all six versions with
        identical signatures (measured 10.08), so the emitter does not
        branch. A branch that appears here without a measured DIFFERENCE is
        code unreachable on any target; this test will be the first to see
        it."""
        texts = {ver: compile_program(_prog([_space()]), revit_version=ver,
                                      snapshot=SNAPSHOT).csharp
                 for ver in spec.REVIT_VERSIONS}
        self.assertEqual(len(set(texts.values())), 1,
                         "эмиссия разошлась по версиям: %s"
                         % sorted(texts))

    def test_it_never_reads_a_member_absent_on_some_version(self):
        """`ElementId.IntegerValue` was removed in 2026, and
        `Category.BuiltInCategory` only appeared in 2023 — neither one
        should be in the emission, nor should `Space.Unplace()`, which does
        not exist on ANY version (CS1061)."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = compile_program(_prog([_space()]), revit_version=ver,
                                     snapshot=SNAPSHOT).csharp
                self.assertNotIn("IntegerValue", cs)
                self.assertNotIn(".BuiltInCategory", cs)
                self.assertNotIn("Unplace", cs)


# ── TWO BAD OUTCOMES THAT MUST NOT BE CONFUSED ───────────────────────────────

class TwoBadOutcomesAreNotOne(unittest.TestCase):
    """'Not placed' and 'not closed' are cured differently, and that is why
    the compiler answers them differently too. `create_room` does NOT
    distinguish between them: an unplaced room falls, in its code, into the
    check `__loc == null || …` with the message "room placement mismatch
    (geometry)", meaning it reads as "missed the point"."""

    def test_an_unplaced_space_is_a_typed_refusal_in_the_create_block(self):
        create, _checks_, _rb = _checks()
        self.assertIn("Location as LocationPoint) == null", create)
        self.assertIn("НЕ РАЗМЕЩЕНО", create)

    def test_the_unplaced_refusal_names_a_cause_and_a_next_move(self):
        """A silent rollback is indistinguishable from a genuine breakage:
        the reason must live in the text, not in the author's head."""
        create, _c, _rb = _checks()
        self.assertIn("не попала ни в одну область", create)
        self.assertIn("проверьте xy и level", create)

    def test_no_witness_ever_signs_an_unplaced_space_green(self):
        """The refusal sits IN THE CREATION BLOCK, i.e. before the
        postconditions: an unplaced space never even reaches the witness."""
        out = compile_program(_prog([_space()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        code = out.csharp
        self.assertLess(code.find("НЕ РАЗМЕЩЕНО"), code.find("// post SP1"))

    def test_an_unenclosed_space_is_a_postcondition_violation_not_a_refusal(self):
        """The operation did exactly what was asked — the space stands at
        the given point on the given level. What failed to match is the
        PROMISE, and the MODEL is at fault, not the call. The same fork and
        the same answer as in create_room."""
        _create, checks, _rb = _checks()
        keys = {c.obligation_key for c in checks}
        self.assertIn("area", keys)
        self.assertIn("boundary", keys)
        create, _c, _rb2 = _checks()
        self.assertNotIn("не замкнуто", create)


# ── witnesses ─────────────────────────────────────────────────────────────────

class WitnessesReadTheResult(unittest.TestCase):

    def setUp(self):
        self.create, self.checks, self.readback = _checks()
        self.by_key = {c.obligation_key: c for c in self.checks}

    def test_every_promise_clause_has_an_obligation(self):
        # THROUGH THE ACCESSOR, NOT BY THE BARE NAME. `REFINEMENT` is a
        # module-level dictionary, EMPTY until the first `_ensure_table()`:
        # on a fresh interpreter `REFINEMENT["create_wall"]` raises a
        # KeyError. The previous edition read the name directly and passed
        # or failed depending on whether someone had already called
        # `certify_op` — and test order here is SHUFFLED on purpose
        # (pytest-randomly). Measured 11.08, an audit of the class "a value
        # is asserted in one place and read in another".
        from kir import translation_cert as tc
        ref = tc._ensure_table()[OP]
        self.assertEqual(
            len([c for c in spec.OPS[OP].post.split(";") if c.strip()]),
            len(ref.obligations))

    def test_the_certificate_proves_the_op_on_every_version(self):
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_space()])), SNAPSHOT)
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cert = certify_op(dict(grounded[0]), ver)
                self.assertTrue(cert.proven, cert.gaps)
                self.assertEqual(cert.vacuous, ())

    def test_cutting_any_witness_makes_the_certificate_fall(self):
        """LAW L6: the strong form of honesty is not words but MUTATION.
        The audit checks prose against common words and therefore misses a
        substitution; cutting out a live witness must make `proven` fail."""
        from kir import ground as ground_mod, room_emit
        from kir.authoring import _EMITTERS
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_space()])), SNAPSHOT)
        original = room_emit.emit_space
        try:
            for cut in ("level_binding", "location", "area", "boundary"):
                with self.subTest(cut=cut):
                    def mutated(op, ver, stamp, isolation="atomic", _c=cut):
                        d, c, checks, r = original(op, ver, stamp, isolation)
                        return d, c, [k for k in checks
                                      if k.obligation_key != _c], r
                    _EMITTERS[OP] = mutated
                    cert = certify_op(dict(grounded[0]), "2024")
                    self.assertFalse(cert.proven,
                                     "вырезан свидетель %s, а сертификат всё "
                                     "ещё доказан" % cut)
        finally:
            from kir import authoring
            _EMITTERS[OP] = authoring._emit_space

    def test_the_topology_axis_is_discharged_by_reading_boundaries(self):
        """YOU MUST SIGN THE AXIS YOU ACTUALLY READ. Area answers "how
        much", the boundary loops answer "bounded by what"; a "(topology)"
        label under a reading of area would be certifying a relationship
        that nobody read."""
        boundary = self.by_key["boundary"]
        self.assertIn("(topology)", boundary.message)
        self.assertIn("GetBoundarySegments",
                      boundary.reader_cs + boundary.verdict_cs)

    def test_the_area_witness_signs_geometry_and_reads_area(self):
        area = self.by_key["area"]
        self.assertIn("(geometry)", area.message)
        self.assertIn(".Area", area.verdict_cs)
        self.assertNotIn("(topology)", area.verdict_cs)

    def test_the_location_witness_reads_a_revit_computed_property(self):
        """§18.3: a check labeled "(geometry)" whose reader consists ONLY
        of `get_Parameter(...)` does not read out the geometry at all.
        Here what is read is `Location`, which Revit itself computes."""
        location = self.by_key["location"]
        self.assertIn("(geometry)", location.message)
        self.assertIn("Location as LocationPoint", location.reader_cs)
        self.assertNotIn("get_Parameter", location.reader_cs)

    def test_no_witness_reads_back_a_parameter_this_op_wrote(self):
        """The op writes NOT A SINGLE parameter, so there is nothing to read
        back either: a witness that confirms its own setter is the chief
        recurring defect of this code."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn("get_Parameter", witness)

    def test_the_volume_is_reported_but_never_witnessed(self):
        """`Space.Volume` exists 6/6, but its value depends on a document
        SETTING (volume computation), not on the built element. In the
        receipt it is honest; as a guarantee it would be a lie."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn(".Volume", witness)
        self.assertIn(".Volume", self.readback)

    def test_the_category_is_not_witnessed_and_that_is_a_decision(self):
        """`NewSpace` returns a `Space` (the type is proven by CS0029 on all
        six), and the correspondence between class and category is an
        invariant of Revit itself. A check that cannot fail to match is
        `plate_z_doubling` in different clothes. The category is checked
        against the CENSUS by ACCEPTANCE, i.e. by an independent judge."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn("OST_MEPSpaces", witness)
        self.assertEqual(spec.op_result_categories({"op": OP}),
                         ("OST_MEPSpaces",))

    def test_the_receipt_never_offers_the_name_as_comparable(self):
        """For Room, `Space.Name` was measured to be a CONCATENATION of the
        name with the number, which is why the key is called
        `name_and_number`: useful to a human, unusable for verification."""
        self.assertIn("name_and_number", self.readback)
        self.assertNotIn('__rb["name"]', self.readback)

    def test_the_tolerance_comes_from_the_registry(self):
        """THE TOLERANCE IN THE CHECK IS NOT A NUMBER, BUT A NUMBER WITH ITS
        OWN PROVENANCE.

        Here stood `assertEqual(location.tol, 5.0)`, and it failed with
        `Tolerance(op='create_space', key='location_mm', value=5.0) != 5.0`.
        The type was introduced on purpose: it carries `op`/`key` and
        remembers every string it has ever rendered itself as. Comparing it
        to a bare number means throwing away exactly what it exists for —
        so we check BOTH halves: the value against the registry, and the
        provenance against this op.
        """
        registry_tol = spec.OPS[OP].tolerances["location_mm"]
        self.assertEqual(registry_tol, 5.0)
        _c, checks, _rb = _checks()
        location = {c.obligation_key: c for c in checks}["location"]
        self.assertEqual(location.tol.value, registry_tol,
                         "допуск проверки разошёлся с реестром")
        self.assertEqual((location.tol.op, location.tol.key),
                         (OP, "location_mm"),
                         "допуск не помнит, чей он — происхождение потеряно")


# ── the seam of transaction and scopes ───────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def setUp(self):
        self.code = compile_program(_prog([_space()]), revit_version="2024",
                                    snapshot=SNAPSHOT).csharp

    def test_one_transaction(self):
        self.assertEqual(self.code.count("new Transaction(doc"), 1)

    def test_regenerate_precedes_postconditions(self):
        self.assertLess(self.code.find("doc.Regenerate();"),
                        self.code.find("// post SP1"))

    def test_the_creation_is_stamped(self):
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", self.code)

    def test_a_null_result_is_a_refusal_not_a_success(self):
        self.assertIn("NewSpace вернул null", self.code)

    def test_it_survives_per_op_isolation(self):
        """A live rake from the enclosures wave: a variable declared inside
        create is not visible to the witness in per_op (CS0103 across all
        six runs)."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(
                    _prog([_space("SP1"), _space("SP2", xy=[9000, 9000])]),
                    revit_version=ver, snapshot=SNAPSHOT, bulk=True,
                    isolation="per_op")
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_walls_before_a_space_force_a_regenerate(self):
        """The v0 rule of create_room has been extended to the space:
        NewSpace resolves the enclosing area AT THE MOMENT OF CREATION, so a
        space created right after its own walls would read Area == 0 and
        would roll back a CORRECT program."""
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL_BY_NAME},
            _space("SP1", level=LVL_BY_NAME),
        ]), revit_version="2024", snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        # THE THIRD COPY OF THE SAME LINE, AND THE THIRD ONE OUT OF DATE.
        # Here what was searched for was `"finalize wall enclosures"`, in
        # `test_regen_before_spatial` — `"doc.Regenerate();  // finalize"`,
        # while the emitter writes a third variant. Ask the emitter
        # (`authoring.SPATIAL_REGEN_CS`), do not retell it.
        regen = out.csharp.find(authoring.SPATIAL_REGEN_CS)
        self.assertGreater(regen, 0)
        self.assertLess(regen, out.csharp.find("// create_space"))


# ── acceptance ────────────────────────────────────────────────────────────────

class AcceptanceKnowsTheOp(unittest.TestCase):
    """An op whose category acceptance does not know REJECTS an honest build
    (`category_shortfall`). The blindness must be a measurement, not
    caution — here the measurement exists: 169 spaces in the corpus were
    read by extraction SPECIFICALLY as OST_MEPSpaces, `expected ==
    extracted`, `state: complete`."""

    def test_the_result_category_is_named_exactly(self):
        self.assertEqual(spec.op_result_categories({"op": OP}),
                         ("OST_MEPSpaces",))

    def test_the_op_is_not_blind_and_not_element_free(self):
        from kir import acceptance
        self.assertNotIn(OP, acceptance._OPS_BLIND)
        self.assertNotIn(OP, acceptance._OPS_WITHOUT_ELEMENTS)

    def test_the_expectation_is_one_exact_row_at_the_resolved_level(self):
        from kir.acceptance import Certainty, derive_expectation
        program = _prog([_space("SP1", level=LVL_BY_NAME),
                         _space("SP2", xy=[9000, 9000], level=LVL_BY_NAME)])
        self.assertTrue(compile_program(program, revit_version="2024",
                                        snapshot=SNAPSHOT, bulk=True).ok)
        rows = [r for r in derive_expectation(program).rows
                if r.categories == ("OST_MEPSpaces",)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].count, 2)
        self.assertEqual(rows[0].level, SNAPSHOT["levels"][0]["name"])
        self.assertIs(rows[0].certainty, Certainty.EXACT)

    def test_the_level_is_taken_from_the_selector_by_construction(self):
        """The level goes straight INTO THE CALL ITSELF, `NewSpace(Level,
        UV)`, i.e. it is equal to the resolved selector by construction, not
        by coincidence."""
        from kir import acceptance
        self.assertIn(OP, acceptance._LEVEL_FROM_PARAM)


# ── the reverse pass and the live-run debt ───────────────────────────────────

class ReverseAndDebt(unittest.TestCase):

    def test_the_reverse_contract_names_the_lifter_not_the_capture(self):
        """LIFTER_GAP, not CAPTURE_GAP: a "capture gap" would send the next
        person to fix reading that already works (44 of 76 decompiles looked
        at the category, 6 found elements, all with state=complete)."""
        from kir.reverse_contract import (
            REVERSE_CONTRACTS, ReverseGuarantee, ReverseMode)
        contract = REVERSE_CONTRACTS[OP]
        self.assertIs(contract.mode, ReverseMode.LIFTER_GAP)
        self.assertIs(contract.guarantee, ReverseGuarantee.NONE)
        self.assertIn("L0:OST_MEPSpaces", contract.sources)

    def test_the_op_is_named_in_the_unproven_ledger(self):
        """The witness corpus was closed on 04.08, the op was introduced on
        10.08 — there are no live rows BY CONSTRUCTION. The silent set must
        remain empty: the models must never say that an unverified op has
        been verified."""
        from kir.tool_doc import UNPROVEN
        self.assertIn(OP, UNPROVEN)
        self.assertTrue(UNPROVEN.reason(OP).strip())


# ── property ──────────────────────────────────────────────────────────────────

class SpacePBT(unittest.TestCase):

    def test_well_typed_spaces_always_compile_on_every_version(self):
        import random
        rng = random.Random(20260810)
        for i in range(12):
            xy = [rng.randint(-50_000, 50_000), rng.randint(-50_000, 50_000)]
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(i=i, version=ver):
                    out = compile_program(_prog([_space(xy=xy)]),
                                          revit_version=ver,
                                          snapshot=SNAPSHOT)
                    self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()