"""wave/placement (2026-08-11): place_family by PLACEMENT KIND.

THE TRIGGER IS MEASURED FROM THE CORPUS, NOT CHOSEN. `tools/coverage_matrix.py`
across the whole decompilation corpus — 11 DISTINCT documents (76 catalogs
are catalogs, not buildings) — ranks atom causes by TWO numbers at once, and
the riser's refusal "place_family only places point-based
(OneLevelBased/OneLevelBasedHosted)" ranks like this:

    'WorkPlaneBased'    483 el. across 7 of 11 documents
    'TwoLevelsBased'   9392 el. across 4 documents
    'ViewBased'         999 el. across 3 documents   ← NOT taken
    'CurveBasedDetail'  862 el. across 3 documents   ← NOT taken

Seven documents out of eleven is the widest spread across buildings among
all effective-gap rows in the corpus, and by the coverage map's own logic a
wide spread means OUR rule itself is wrong, not that one project is
peculiar.

API TAKEN FROM THE ASSEMBLIES (11.08, reflection over six `RevitAPI.dll`
files plus live compilation on :52412, a separate run per version):

    NewFamilyInstance(XYZ, FamilySymbol, XYZ refDir, Element,
                      StructuralType)                              6/6
    NewFamilyInstance(Reference, XYZ, XYZ, FamilySymbol)           6/6
    FamilyPlacementType — all 10 members                           6/6
    FamilyInstance.HandOrientation / FacingOrientation / Host      6/6
    FAMILY_TOP_LEVEL_PARAM / FAMILY_*_LEVEL_OFFSET_PARAM           6/6

A REFLECTION-READING TRAP, MEASURED ALONG THE WAY: the overload
`(XYZ, FamilySymbol, Level, StructuralType)` is declared on
`Creation.Document` in 2021-2023 and on `Creation.ItemFactoryBase` in
2024-2026. It did NOT DISAPPEAR — it moved along the inheritance chain, and
a dump of DECLARED members shows this as missing on three versions. The same
trap as `SpatialElement.Name`: you must query the chain, not the class.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_placement_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "place_family"
LVL = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}


def _prog(ops, intent="placement-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _codes(out):
    return [d.code for d in out.diagnostics]


def _wall(oid="W1"):
    return {"op": "create_wall", "id": oid, "p0_mm": [0, 0],
            "p1_mm": [8000, 0], "level": LVL}


def _work_plane(**kw):
    op = {"op": OP, "id": "P1", "xyz": [4000, 0, 1200], "level": LVL,
          "host": {"by": "ref", "value": "W1"}, "ref_dir": [1, 0, 0]}
    op.update(kw)
    return [_wall(), op]


def _two_levels(**kw):
    op = {"op": OP, "id": "P1", "xyz": [1000, 2000, 0], "level": LVL,
          "top_level": {"by": "ref", "value": "LT"}}
    op.update(kw)
    return [{"op": "create_level", "id": "LT", "elev_mm": 6000,
             "name": "КИР-В"}, op]


def _checks_of(ops):
    from kir import ground as ground_mod
    from kir.authoring import _EMITTERS
    from kir.compiler import _parse_and_check
    grounded = ground_mod.ground(_parse_and_check(_prog(ops)), SNAPSHOT)
    node = [g for g in grounded if g["op"] == OP][0]
    return _EMITTERS[OP](dict(node), "2026", "kir:test")


# ── registry ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_new_operands_exist(self):
        names = {p.name for p in spec.OPS[OP].params}
        self.assertIn("ref_dir", names)
        self.assertIn("top_level", names)
        self.assertIn("base_offset_mm", names)
        self.assertIn("top_offset_mm", names)

    def test_none_of_them_carries_a_default(self):
        """MEASURED 29.07: `height_mm` carried a default of 3000,
        `_validate_op` substituted it BEFORE the emitter, and the witness
        was rolling back EVERY correctly built facade wall — "asked for
        exactly 3000" and "said nothing" became indistinguishable. A missing
        key must stay missing: otherwise the byte parity of 18,700 demo
        instances would also shift."""
        by_name = {p.name: p for p in spec.OPS[OP].params}
        for name in ("ref_dir", "top_level", "base_offset_mm",
                     "top_offset_mm"):
            with self.subTest(param=name):
                self.assertIsNone(by_name[name].default)

    def test_the_offset_tolerances_are_named_in_the_registry(self):
        """A bare literal in a comparison is exactly the kind of boundary
        the `bounds_audit` census only finds by eye. The numbers are the
        same as for create_wall and create_column: one promise about one
        value."""
        tol = dict(spec.OPS[OP].tolerances)
        self.assertEqual(tol["base_offset_mm"], 1.0)
        self.assertEqual(tol["top_offset_mm"], 1.0)
        self.assertEqual(tol["base_offset_mm"],
                         dict(spec.OPS["create_column"].tolerances)
                         ["base_offset_mm"])

    def test_the_top_level_is_grounded_by_the_levels_pool(self):
        self.assertIn(("top_level", "levels", False), spec.OPS[OP].grounded)

    def test_a_direction_is_not_addressable_by_grid(self):
        """RELATE resolves an address into MODEL MILLIMETERS, and
        millimeters in a direction field are not "roughly that way" but a
        different quantity.

        🔴 THE TEST WAS REWRITTEN 21.08.2026 FROM MECHANISM TO PROPERTY, and
        it was rewritten because the mechanism CHANGED FOR THE BETTER. A
        check against `assertIn((OP, "ref_dir"), ADDRESS_EXCLUDED)` used to
        stand here — a check on a handwritten exception. The exception no
        longer exists: the parameter's kind is `dir_xyz`, and
        non-addressability is DERIVED from the kind
        (`addressable_params` only looks at point-like kinds). The knowledge
        moved from a list into a type.

        Checking the list after that would mean turning red on the fix.
        So what is checked is the PROPERTY ITSELF, and it is now stronger:
        the kind now governs not one question but both — the address from
        the axes, and the shift into the local frame in
        `decompile.program_source._shift`, which before this wave turned
        [-1, 0, 0] into [-1001, -500, 0].
        """
        from kir.relate import addressable_params
        self.assertNotIn("ref_dir", addressable_params(OP))
        self.assertEqual(
            "dir_xyz",
            next(p.kind for p in spec.OPS[OP].params if p.name == "ref_dir"))


# ── disproving: before this wave both programs FAILED ───────────────

class TheRefutingPrograms(unittest.TestCase):
    """These two compile ONLY after the wave. On HEAD before it, both gave
    KIR-P003 "unknown field" — that is, the engineer could not even ask,
    rather than getting a bad result."""

    def test_a_work_plane_placement_compiles(self):
        out = compile_program(_prog(_work_plane()), revit_version="2024",
                              snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("FamilyPlacementType.WorkPlaneBased", out.csharp)

    def test_a_two_levels_placement_compiles(self):
        out = compile_program(_prog(_two_levels(base_offset_mm=100,
                                                top_offset_mm=-250)),
                              revit_version="2024", snapshot=SNAPSHOT,
                              bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("FAMILY_TOP_LEVEL_PARAM", out.csharp)


# ── byte parity: the point-based path must not shift ─────────────────────────

class TheFrozenPathDoesNotMove(unittest.TestCase):

    def test_a_program_without_the_new_operands_is_byte_identical(self):
        """The point-based path is frozen by the parity corpus (18,700 demo
        instances). The addition must be EMPTY when the operand is not
        named."""
        import io
        import pathlib
        from kir.tests.test_golden import GOLDEN_DIR, PROGRAMS
        for name in ("full_house_v1", "place_family_point_and_curve"):
            with self.subTest(golden=name):
                prog = {k: v for k, v in PROGRAMS[name].items()
                        if not k.startswith("__")}
                out = compile_program(prog, revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                path = pathlib.Path(GOLDEN_DIR) / ("%s.golden.cs" % name)
                self.assertEqual(
                    io.open(str(path), encoding="utf-8").read(), out.csharp,
                    "%s: точечный путь сдвинулся" % name)


# ── version axis: it does not exist ──────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_both_branches_build_on_all_six(self):
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels())):
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(branch=label, version=ver):
                    out = compile_program(_prog(ops), revit_version=ver,
                                          snapshot=SNAPSHOT, bulk=True)
                    self.assertTrue(out.ok, _codes(out)[:3])

    def test_the_emission_does_not_branch_by_version(self):
        """The three `NewFamilyInstance` overloads live on all six versions
        with identical signatures (measured 11.08), so there should be no
        version branch here — it would be code unreachable on any target."""
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels())):
            texts = {ver: compile_program(_prog(ops), revit_version=ver,
                                          snapshot=SNAPSHOT,
                                          bulk=True).csharp
                     for ver in spec.REVIT_VERSIONS}
            with self.subTest(branch=label):
                self.assertEqual(len(set(texts.values())), 1)


# ── refusals: each names its cause ─────────────────────────────────────────

class RefusalsNameTheCause(unittest.TestCase):

    def test_a_direction_with_a_curve_is_refused_not_swallowed(self):
        """Silently swallowing an operand is worse than refusing: the
        by-host-reference overload has no orientation reference at all, and
        accepting `ref_dir` would mean building something other than what
        was asked and reporting it as success."""
        out = compile_program(_prog([
            _wall(),
            {"op": OP, "id": "P1", "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
             "host": {"by": "ref", "value": "W1"}, "ref_dir": [1, 0, 0]},
        ]), revit_version="2024", snapshot=SNAPSHOT, bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))

    def test_a_work_plane_placement_without_a_host_is_refused(self):
        out = compile_program(_prog([
            {"op": OP, "id": "P1", "xyz": [1, 2, 0], "level": LVL,
             "ref_dir": [1, 0, 0]}]), revit_version="2024",
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(_codes(out))

    def test_the_placement_type_guard_names_the_actual_kind(self):
        """`CanFlip*=false` taught us: the placement kind is a FACT ABOUT THE
        FAMILY, and Revit will not rearrange it. So a typed REFUSAL (its own
        op sits under per_op), not a postcondition violation (that would
        cost the whole program), and the text carries the actual kind — the
        author has something to fix."""
        _d, create, _c, _r = _checks_of(_work_plane())
        self.assertIn("FamilyPlacementType.WorkPlaneBased", create)
        self.assertIn("FamilyPlacementType.ToString()", create)

    def test_a_zero_length_direction_is_refused(self):
        _d, create, _c, _r = _checks_of(_work_plane())
        self.assertIn("IsZeroLength()", create)

    def test_work_plane_never_swallows_point_or_two_level_operands(self):
        """`ref_dir` selects a different Revit overload.  Even an explicit
        neutral value is author intent and must not disappear at that branch's
        early return."""
        cases = {
            "rotation_deg": 0.0,
            "mirrored": False,
            "hand_flipped": False,
            "facing_flipped": False,
            "top_level": LVL,
            "base_offset_mm": 0.0,
            "top_offset_mm": 0.0,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                out = compile_program(
                    _prog(_work_plane(**{field: value})),
                    revit_version="2024", snapshot=SNAPSHOT, bulk=True)
                self.assertFalse(out.ok)
                refusals = [d for d in out.diagnostics
                            if d.code == "KIR-P007"
                            and d.field_name == field]
                self.assertEqual(len(refusals), 1, out.diagnostics)
                self.assertIn("ref_dir", refusals[0].message_ru)
                self.assertIn("не будет молча", refusals[0].message_ru)

    def test_trusted_emitter_call_has_the_same_fail_closed_boundary(self):
        """The validator is the public boundary, but a trusted pre-grounded
        caller must not be able to reintroduce the old silent-ignore path."""
        from kir.authoring import _emit_place_work_plane
        from kir.diag import KirRefusal

        fields = {
            "rotation_deg": 15.0,
            "mirrored": True,
            "hand_flipped": True,
            "facing_flipped": False,
            "top_level": LVL,
            "base_offset_mm": 100.0,
            "top_offset_mm": -100.0,
        }
        op = _work_plane(**fields)[-1]
        with self.assertRaises(KirRefusal) as caught:
            _emit_place_work_plane(op, "2024", "kir:test")
        self.assertEqual(
            set(fields),
            {d.field_name for d in caught.exception.diagnostics})
        self.assertTrue(all(d.code == "KIR-P007"
                            for d in caught.exception.diagnostics))


# ── witnesses ───────────────────────────────────────────────────────────────

class WitnessesReadTheResult(unittest.TestCase):

    def test_each_branch_carries_its_own_keys(self):
        _d, _c, wp, _r = _checks_of(_work_plane())
        self.assertIn("reference_direction",
                      {k.obligation_key for k in wp})
        _d, _c, tl, _r = _checks_of(_two_levels(base_offset_mm=100,
                                                top_offset_mm=-250))
        keys = {k.obligation_key for k in tl}
        self.assertIn("top_level_binding", keys)
        self.assertIn("base_offset", keys)
        self.assertIn("top_offset", keys)

    def test_an_absent_operand_leaves_no_witness_behind(self):
        """A conditional obligation is discharged by the ABSENCE of its own
        witness: an extra witness would declare proven something nobody
        asked for."""
        _d, _c, checks, _r = _checks_of([
            {"op": OP, "id": "P1", "xyz": [1, 2, 0], "level": LVL}])
        keys = {k.obligation_key for k in checks}
        for absent in ("reference_direction", "top_level_binding",
                       "base_offset", "top_offset"):
            self.assertNotIn(absent, keys)

    def test_the_direction_witness_reads_a_revit_computed_vector(self):
        """§18.3: a check labeled "(geometry)" whose reader consists SOLELY
        of `get_Parameter(...)` does not discharge geometry. What is read
        here is `HandOrientation` — a vector Revit itself computes."""
        _d, _c, checks, _r = _checks_of(_work_plane())
        wit = {k.obligation_key: k for k in checks}["reference_direction"]
        self.assertIn("(geometry)", wit.message)
        self.assertIn("HandOrientation", wit.reader_cs)
        self.assertNotIn("get_Parameter", wit.reader_cs)

    def test_the_offsets_sign_semantic_because_that_is_what_they_read(self):
        """The reader is exactly `get_Parameter(...)`, i.e. a parameter we
        ourselves wrote. Labeling it as geometry would mean requesting an
        exception in `_ALLOWED_PARAMETER_GEOMETRY` for a claim no one
        measured. Semantics is what it ACTUALLY proves."""
        _d, _c, checks, _r = _checks_of(_two_levels(base_offset_mm=100))
        wit = {k.obligation_key: k for k in checks}["base_offset"]
        self.assertIn("(semantic)", wit.message)
        self.assertNotIn("(geometry)", wit.message)

    def test_every_setter_of_this_wave_is_read_back(self):
        """A setter with no witness is this code's chief recurring defect:
        it passes every test and proves nothing."""
        _d, create, checks, _r = _checks_of(
            _two_levels(base_offset_mm=100, top_offset_mm=-250))
        witness = "".join(c.reader_cs + c.verdict_cs for c in checks)
        for bip in ("FAMILY_TOP_LEVEL_PARAM",
                    "FAMILY_BASE_LEVEL_OFFSET_PARAM",
                    "FAMILY_TOP_LEVEL_OFFSET_PARAM"):
            with self.subTest(bip=bip):
                self.assertIn(bip, create)
                self.assertIn(bip, witness)

    def test_the_certificate_proves_both_branches_on_every_version(self):
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_op
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels(base_offset_mm=100,
                                                      top_offset_mm=-250))):
            grounded = ground_mod.ground(_parse_and_check(_prog(ops)),
                                         SNAPSHOT)
            node = [g for g in grounded if g["op"] == OP][0]
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(branch=label, version=ver):
                    cert = certify_op(dict(node), ver)
                    self.assertTrue(cert.proven, cert.gaps)
                    self.assertEqual(cert.vacuous, ())

    def test_cutting_any_new_witness_makes_the_certificate_fall(self):
        """LAW L6. And the oracle only makes sense on a GREEN baseline: a
        mutation whose original certificate is already red "passes" for
        nothing — that is exactly what happened on this wave's first run."""
        from kir import authoring, ground as ground_mod
        from kir.authoring import _EMITTERS
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_op
        cases = {
            "reference_direction": _work_plane(),
            "top_level_binding": _two_levels(base_offset_mm=100),
            "base_offset": _two_levels(base_offset_mm=100),
        }
        original = authoring._emit_place
        try:
            for cut, ops in cases.items():
                grounded = ground_mod.ground(_parse_and_check(_prog(ops)),
                                             SNAPSHOT)
                node = [g for g in grounded if g["op"] == OP][0]
                with self.subTest(cut=cut):
                    self.assertTrue(certify_op(dict(node), "2026").proven,
                                    "база мутации обязана быть зелёной")

                    def mutated(op, ver, stamp, isolation="atomic", _c=cut):
                        d, c, checks, r = original(op, ver, stamp, isolation)
                        return d, c, [k for k in checks
                                      if k.obligation_key != _c], r
                    _EMITTERS[OP] = mutated
                    self.assertFalse(certify_op(dict(node), "2026").proven,
                                     "вырезан свидетель %s, а сертификат "
                                     "всё ещё доказан" % cut)
                    _EMITTERS[OP] = original
        finally:
            _EMITTERS[OP] = original


# ── the honest remainder ─────────────────────────────────────────────────────

class TheReverseHalfStaysClosed(unittest.TestCase):
    """The wave extends the FORWARD path. There is nothing to raise such an
    instance back with, and this is recorded in the code, not left as a
    finding for the next measurement."""

    def test_l0_carries_one_level_and_no_work_plane_reference(self):
        from kir.decompile.schema import L0Element
        fields = set(L0Element.__dataclass_fields__)
        self.assertIn("level_id", fields)
        self.assertNotIn("top_level_id", fields)
        for name in fields:
            self.assertNotIn("work_plane", name)
            self.assertNotIn("sketch_plane", name)

    def test_the_view_owned_kinds_are_deliberately_not_taken(self):
        """`ViewBased` (999 el./3 docs) and `CurveBasedDetail` (862/3) run
        into the same wall as size, tag, and text: `L0Element` carries no
        owning view, and NOT ONE KIR op creates a View — `_annot_view_res`
        refuses `in_view: ref` on exactly this premise. Taking them would
        mean changing the LANGUAGE, not the registry."""
        from kir.decompile.schema import L0Element
        fields = set(L0Element.__dataclass_fields__)
        self.assertNotIn("owner_view_id", fields)
        self.assertNotIn("view_id", fields)


if __name__ == "__main__":
    unittest.main()
