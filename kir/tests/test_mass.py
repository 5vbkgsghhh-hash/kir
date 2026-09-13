"""wave/mass (2026-08-10): create_face_wall — the sole door from a
conceptual mass into real BIM.

WHY THIS WAVE AND WHY IT HAS ONE OPERATION, NOT EIGHT. The census called
the "freeform shapes and masses" family nearly blind (2 out of 12) and
left a hypothesis of six mass shapes, `DividedSurface`, and `DividedPath`.
Measurement by compiling against six reference assemblies (live :52412,
08.10) refuted the hypothesis: ALL SIX shapes live only on
`doc.FamilyCreate`, and this accessor is documented verbatim and
identically on 2021 and 2026 — "thrown when the current document is
project document." KIR writes into a project document, so the six
factories are unreachable BY THE DOOR, not by a condition inside the call.
The full measurement table is in the header of `ops_mass.py`; only the
conclusions checked by the code below are repeated here.

THE CLASS `FamilyDocumentBoundary` IS THE CENTERPIECE OF THIS FILE. It
holds not an operation's behavior but the BOUNDARY the whole chapter
stands on: no registry emitter has the right to call `doc.FamilyCreate`.
A fix adding a mass shape "like all the others" looks like an expansion of
capability and throws every time on live Revit — that is, it is exactly
the kind of defect the offline Roslyn gate CANNOT see (the call compiles
6/6). The only place it can be caught before a live run is here.
"""
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_mass_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.ops_mass import FACE_WALL_LOCATION_LINES           # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_face_wall"
HOST_ID = {"by": "element_id", "value": 900001}
BRICK = {"by": "name", "value": "Кирпич 250"}


def _fw(oid="FW1", **kw):
    op = {"op": OP, "id": oid, "host": HOST_ID,
          "face_normal": [0.6, 0.0, 0.8], "location_line": "core_exterior",
          "type": BRICK}
    op.update(kw)
    return op


def _emit(ops, ver="2026", isolation="atomic", snapshot=SNAPSHOT):
    return compile_program({"ir_version": "1.0", "intent": "mass-test",
                            "ops": ops},
                           revit_version=ver, snapshot=snapshot,
                           isolation=isolation)


def _cs(ops=None, **kw):
    out = _emit(ops or [_fw()], **kw)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


class RegistryShape(unittest.TestCase):
    def test_the_op_is_a_registered_writing_create(self):
        self.assertIn(OP, spec.OPS)
        o = spec.OPS[OP]
        self.assertTrue(o.writes_model)
        self.assertEqual(o.effect.value, "create")

    def test_it_grounds_the_same_wall_type_pool_as_create_wall(self):
        """THE POOL IS SHARED WITH `create_wall`, AND THIS IS A DECISION,
        NOT A COINCIDENCE.

        The type class is the same (`WallType`), so a second pool over the
        same elements would mean two answers to one question. Whether a
        SPECIFIC type is fit for a face-based wall is decided not by the
        pool but by Revit itself — in the preflight below.
        """
        pools = {p: pool for p, pool, _ in spec.OPS[OP].grounded}
        self.assertEqual(pools, {"type": "wall_types"})
        wall_pools = {p: pool for p, pool, _ in spec.OPS["create_wall"].grounded}
        self.assertEqual(pools["type"], wall_pools["type"])

    def test_it_declares_no_tolerance(self):
        """NOT A SINGLE TOLERANCE — A CONSEQUENCE, NOT A GAP.

        The wave's only numeric comparison (the face's position) compares
        against the sum of `WallType.Width` and
        `doc.Application.VertexTolerance` — Revit reports BOTH values
        itself, and both depend on the operation's geometry, so by
        construction they cannot be a registry constant. The lock is there
        because the reverse fix — writing a number in here — looks like an
        improvement while actually being a "bound authored by reasoning."
        """
        self.assertEqual(spec.OPS[OP].tolerances, {})
        self.assertNotIn("±", spec.OPS[OP].post)

    def test_location_line_is_closed_mandatory_and_undefaulted(self):
        """A CALL ARGUMENT, NOT AN OPTIONAL FIELD: substituting it on the
        author's behalf would mean silently deciding which side of the
        face the body stands on."""
        p = {x.name: x for x in spec.OPS[OP].params}["location_line"]
        self.assertEqual(set(p.choices), set(FACE_WALL_LOCATION_LINES))
        self.assertTrue(p.required)
        self.assertIsNone(p.default)

    def test_the_six_location_lines_are_spelled_like_create_wall(self):
        """ONE CONCEPT — ONE SPELLING. Two different words for the same
        thing within one registry would make the author guess whether they
        are the same. `create_wall` exhibits three of the six (the
        narrowing is explained by the ELEVATOR), but EVERY one of its
        words must be found here.
        """
        from kir.ops_authoring import WALL_LOCATION_LINE_ORDINALS
        self.assertEqual(set(FACE_WALL_LOCATION_LINES),
                         set(WALL_LOCATION_LINE_ORDINALS))
        wall = {x.name: x for x in spec.OPS["create_wall"].params}["location_line"]
        for word in wall.choices:
            with self.subTest(word=word):
                self.assertIn(word, FACE_WALL_LOCATION_LINES)

    def test_face_normal_is_a_direction_kind_not_a_point(self):
        """🔴 THE CHECK WAS REWRITTEN ON 21.08.2026, AND THIS IS A
        STRENGTHENING, NOT A FIX TO GO GREEN.

        This used to read `assertEqual(p.kind, "pt_xyz")` with the
        docstring: "kind `pt_xyz`, BUT NOT MILLIMETERS… must be NAMED, not
        implied." The argument was entirely correct, but the distinction
        was named by PROSE — a comment in `authoring_validation` (and
        `assertIn("DIRECTION", …)` was the one guarding it).

        Prose does not protect. While `face_normal` was a point,
        `decompile.program_source._shift` subtracted the local frame's
        origin from it: [-1, 0, 0] turned into [-1001, -500, 0], and no
        check failed — three numbers remain three numbers. Now the
        distinction is named by the KIND (`dir_xyz`), and it holds both
        questions at once: addressability from the axes, and the frame
        shift.

        So what is compared is the KIND and ITS CONSEQUENCES, not whether
        a word appears in a comment: the word can be rewritten, the
        consequence cannot.
        """
        from kir.decompile.program_source import MM_KINDS
        from kir.relate import addressable_params

        p = {x.name: x for x in spec.OPS[OP].params}["face_normal"]
        self.assertEqual(p.kind, "dir_xyz")
        self.assertTrue(p.required)
        # NOT MILLIMETERS — now this is a fact about the kind, not a promise in prose.
        self.assertNotIn("dir_xyz", MM_KINDS)
        # AND NOT A POSITION: an address from the axes resolves into model
        # millimeters, while millimeters in a direction field are a
        # different quantity.
        self.assertNotIn("face_normal", addressable_params(OP))

    def test_it_claims_element_not_geometry(self):
        """A REAL ELEMENT, NOT "GEOMETRY": a face-based wall has a type,
        layers, and an area in the schedule — everything a DirectShape
        lacks by construction. This is the entire point of the wave, and
        it is declared in the cell."""
        cap = spec.OPS[OP].capability
        self.assertIn(("create", "element"), cap)
        self.assertNotIn(("create", "geometry"), cap)
        self.assertNotIn(("create", "geometry"),
                         spec.OPS[OP].capability)


# 🔴 `_validation_source()` USED TO LIVE HERE — a helper that read the
# SOURCE TEXT of `authoring_validation` to confirm that the comment
# contained the word "DIRECTION." Removed on 21.08.2026 together with its
# only consumer.
#
# It was itself proof that prose does not protect: the word in the comment
# stood there, was correct — and the whole time `_shift` was subtracting
# the local frame's origin from the direction. Now the distinction is
# carried by the KIND (`dir_xyz`), and the test compares its CONSEQUENCES.
# There is nothing left, and no reason, to check comments any more.


class FamilyDocumentBoundary(unittest.TestCase):
    """THE BOUNDARY THE ENTIRE MASS CHAPTER STANDS ON.

    `Document.FamilyCreate` is documented verbatim and identically across
    all six RevitAPI.xml files (read individually, not just the two
    extremes): *"Thrown when the current document is project document."*
    All six mass-shape factories live ONLY on it (`doc.Create.NewExtrusionForm`
    and the other five — CS1061 on all six), so in a project document they
    throw GUARANTEED.

    And here is why this class is needed: such a call COMPILES 6/6. The
    Roslyn gate will let it through, the gate stays green, and live Revit
    will refuse every time. Offline, this boundary is visible in exactly
    one place — here.
    """

    _FORBIDDEN = (
        "FamilyCreate",
        "NewExtrusionForm", "NewRevolveForms", "NewSweptBlendForm",
        "NewLoftForm", "NewFormByThickenSingleSurface", "NewFormByCap",
        "FreeFormElement.Create",
    )

    def test_no_registry_emitter_ever_calls_the_family_only_door(self):
        import kir.authoring as authoring
        sources = []
        for mod in (authoring,):
            with open(mod.__file__, encoding="utf-8") as fh:
                sources.append(fh.read())
        for name in ("mass_emit", "solid_emit", "shape_emit"):
            mod = __import__(f"kir.{name}", fromlist=["x"])
            with open(mod.__file__, encoding="utf-8") as fh:
                sources.append(fh.read())
        blob = "\n".join(sources)
        # Mentions as strings inside COMMENTS are legitimate and needed —
        # they are exactly what explains to the next reader why these
        # calls are absent. What we search for is a CALL: a name
        # immediately followed by an opening parenthesis.
        for member in self._FORBIDDEN:
            with self.subTest(member=member):
                self.assertIsNone(
                    re.search(re.escape(member) + r"\s*\(", blob),
                    f"{member} — вызов из семейного документа; KIR пишет в "
                    f"ПРОЕКТНЫЙ, и Revit бросит на нём всегда")

    def test_the_taken_op_is_the_documented_inverse(self):
        """`FaceWall.Create` was chosen not "because it was left over" but
        because it alone has a throw condition that is the EXACT INVERSE
        of the shapes' refusal: "document is not a project document." The
        reason must stand in text a human reads, not only in the head of
        the wave's author."""
        import kir.ops_mass as m
        self.assertIn("document is not a project document", " ".join(m.__doc__.split()))
        self.assertIn("thrown when the current document is project document",
                      m.__doc__.lower())


class NamedAbsence(unittest.TestCase):
    """THE SECOND-MOST-IMPORTANT CLASS: what the witness does NOT assert.

    In the bodies wave, the witness compares the volume against a closed
    shape computed at compile time. HERE THERE IS NO SUCH QUANTITY, and
    there cannot be — the shape is set by a face belonging to a foreign
    element. The temptation to add "wall area == face area" is strong and
    looks like a strengthening; whether Revit covers the face completely
    is not stated in any of the six RevitAPI.xml files, so such a check
    would reject correct work. Named out loud and locked.
    """

    def test_the_absence_is_stated_in_post(self):
        post = spec.OPS[OP].post
        self.assertIn("NAMED ABSENCE", post)
        self.assertIn("area equality", post)

    def test_the_clause_is_registered_as_non_witnessable(self):
        from kir.translation_cert import _NON_WITNESSABLE_CLAUSES
        markers = _NON_WITNESSABLE_CLAUSES[OP]
        self.assertEqual(len(markers), 1)
        marker, why = markers[0]
        self.assertIn(marker, spec.OPS[OP].post.lower())
        self.assertIn("documented nowhere", why)

    def test_the_registry_audit_is_clean(self):
        from kir.translation_cert import audit_registry_coverage
        self.assertEqual(audit_registry_coverage(), ())

    def test_the_raw_pair_rides_the_receipt_not_the_verdict(self):
        """BOTH NUMBERS ARE IN THE RECEIPT AND NEITHER IS IN THE VERDICT —
        so the first live run will MEASURE the remainder, not merely
        estimate it."""
        cs = _cs()
        # Both numbers are in the receipt block (`__results`), and NEITHER
        # enters any verdict (`__post.Add`): the verdict asserts, the
        # receipt observes, and mixing them would mean asserting a
        # quantity nobody measured.
        self.assertIn('__rb["named_face_area_mm2"]', cs)
        self.assertIn('__rb["built_face_area_mm2"]', cs)
        import re as _re
        for verdict in _re.findall(r"__post\.Add\((.*?)\);", cs, _re.S):
            with self.subTest(verdict=verdict[:60]):
                self.assertNotIn("area_mm2", verdict)
                self.assertNotIn("__farea_", verdict)
                self.assertNotIn("__warea_", verdict)


class VersionAxis(unittest.TestCase):
    def test_six_versions_receive_the_same_csharp(self):
        """THERE IS NO VERSION AXIS — AND THIS IS AN ASSERTION, NOT AN
        OMISSION. Every member the emitter names has been measured 6/6, so
        there must be no divergence anywhere. The test catches a future
        fix that quietly introduces a version branch where the API does
        not require one."""
        texts = {}
        for ver in spec.REVIT_VERSIONS:
            out = _emit([_fw()], ver=ver)
            self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
            texts[ver] = out.csharp
        self.assertEqual(len(set(texts.values())), 1)


class Ground(unittest.TestCase):
    def test_named_type_is_resolved_by_name(self):
        cs = _cs()
        self.assertIn("100", cs)          # pool id for "Brick 250"

    def test_an_ambiguous_pool_refuses_instead_of_picking(self):
        """The wall pool in the snapshot has TWO types. An omitted `type`
        must produce a typed question with candidates, not
        `.FirstOrDefault()`: the 08.02 live paired measurement on Snowdon
        showed the cost of the choice — the C# leverage silently took 1
        door type out of 62 and built it."""
        op = _fw()
        op.pop("type")
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_an_existing_mass_by_element_id_is_legal(self):
        """THE MAIN SCENARIO: a face-based wall is built on a mass that IS
        ALREADY STANDING. Requiring `ref` would mean forbidding it."""
        self.assertTrue(_emit([_fw()]).ok)

    def test_a_mass_placed_by_the_same_program_is_legal_too(self):
        placed = {"op": "place_family", "id": "M1",
                  "symbol": {"by": "family_type", "category": "OST_Furniture",
                             "family_name": "Стол офисный",
                             "type_name": "Стол 1200"},
                  "xyz": [1000, 2000, 0],
                  "level": {"by": "name", "value": "Этаж 1"}}
        out = _emit([placed, _fw(oid="FW2", host={"by": "ref", "value": "M1"})])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


class Negative(unittest.TestCase):
    def test_face_normal_is_mandatory(self):
        op = _fw()
        op.pop("face_normal")
        self.assertFalse(_emit([op]).ok)

    def test_a_zero_vector_is_refused_at_parse_time(self):
        """EXACT ZERO IS DEGENERACY BY DEFINITION, not a threshold. The
        refusal sits at decompile time precisely because this is equality,
        not a comparison against a number."""
        out = _emit([_fw(face_normal=[0, 0, 0])])
        self.assertFalse(out.ok)
        self.assertTrue(any("нулевой вектор" in (d.message_ru or "")
                            for d in out.diagnostics))

    def test_a_near_zero_vector_is_left_to_revit(self):
        """AND THE EXACT OPPOSITE: a "nearly zero" vector is NOT touched by
        the compiler. Only Revit knows where this boundary runs, and it
        answers with its own `XYZ.IsZeroLength()` at runtime. Assigning a
        threshold here would mean introducing a number nobody measured,
        next to a number Revit reports itself."""
        out = _emit([_fw(face_normal=[1e-12, 0, 0])])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("IsZeroLength", out.csharp)

    def test_location_line_is_mandatory(self):
        op = _fw()
        op.pop("location_line")
        self.assertFalse(_emit([op]).ok)

    def test_an_unknown_location_line_refuses(self):
        self.assertFalse(_emit([_fw(location_line="по_потолку")]).ok)

    def test_host_is_mandatory(self):
        op = _fw()
        op.pop("host")
        self.assertFalse(_emit([op]).ok)


class Emission(unittest.TestCase):
    def test_both_revit_preflights_stand_before_the_call(self):
        """BOTH PREFLIGHTS RUN BEFORE THE EFFECT. There is nothing left to
        ask after the call: the refusal would arrive as an exception and
        land in the receipt as `internal`, that is, "something broke on
        our end" instead of "Revit does not accept this type/face."""
        cs = _cs()
        call = cs.index("FaceWall.Create(")
        for guard in ("IsWallTypeValidForFaceWall",
                      "IsValidFaceReferenceForFaceWall"):
            with self.subTest(guard=guard):
                self.assertIn(guard, cs)
                self.assertLess(cs.index(guard), call)

    def test_the_face_walk_is_facerefs_and_not_a_second_one(self):
        """FACE SELECTION — BY FOREIGN CODE, UNDER OUR OWN LAW. The
        traversal helpers come from `faceref`; a second selection next to
        it would mean two places where the cardinality law could be
        weakened separately."""
        cs = _cs()
        self.assertIn("__faceWalk_", cs)
        self.assertIn("__faceKeep_", cs)
        self.assertIn("GetSymbolGeometry()", cs)
        # A trap that cost the annotations wave a live refusal:
        # `GetInstanceGeometry` is documented as a COPY whose references
        # are unfit for creating new elements. It must not come back here.
        self.assertNotIn("GetInstanceGeometry", cs)

    def test_cardinality_decides_and_the_refusal_names_the_count(self):
        cs = _cs()
        self.assertIn("отвечает не одна грань, а", cs)
        self.assertIn(".Count.ToString()", cs)

    def test_the_refusal_speaks_this_ops_vocabulary_not_the_selectors(self):
        """A REFUSAL THAT SENDS THE AUTHOR TO EDIT A FIELD THAT DOES NOT
        EXIST IS WORSE THAN NO REFUSAL AT ALL.

        `faceref`'s own text refers to `predicate.side` and
        `predicate.normal` — the vocabulary of the SELECTOR'S SECOND
        STAGE. This operation has no such fields at all: the direction
        arrives as an ordinary parameter, `face_normal`, exactly like the
        side in `create_slab_edge`. The helper therefore takes the NEXT
        STEP in the caller's own words, rather than being rewritten by
        string substitution over the emitted C# (substitution is a
        forbidden technique, KIR-E005).
        """
        cs = _cs()
        self.assertNotIn("predicate.side", cs)
        self.assertNotIn("predicate.normal", cs)
        self.assertIn("face_normal", cs)
        # And Revit's own rule is named in the refusal, not left to guesswork.
        self.assertIn("наклонной грани массы", cs)

    def test_the_shared_helper_keeps_its_old_text_by_default(self):
        """EXTENDING THE HELPER HAS NO RIGHT TO SHIFT THOSE WHO ALREADY
        CALLED IT. The default must produce VERBATIM the previous text —
        otherwise one wave would silently rewrite the diagnostics of its
        neighbor."""
        import inspect
        from kir import faceref
        src = inspect.getsource(faceref.resolve_cs)
        self.assertIn("либо назови сторону (predicate.side)", src)
        self.assertIn("рядом с predicate.side (или наоборот)", src)

    def test_the_op_never_reads_coordinates_off_the_instance_face(self):
        """THE ONE PLACE WHERE THIS WAVE COULD HAVE LIED QUIETLY.

        The carrier is `FamilyInstance`, and its body's face lives in
        SYMBOL coordinates. Area is invariant under a rigid transform, so
        reading it off this reference is legitimate; ANY coordinate
        (Origin, FaceNormal) read off it would mean a third coordinate
        system inside the witness — the same kind of error as an assigned
        tolerance, only quieter.
        """
        cs = _cs()
        used = set(re.findall(r"__mf_[A-Za-z0-9_]*\.([A-Za-z_]+)", cs))
        self.assertEqual(used, {"Area"}, f"с грани массы прочитано лишнее: {used}")

    def test_the_documented_null_return_is_guarded(self):
        cs = _cs()
        self.assertIn("создание вернуло null", cs)

    def test_the_location_line_reaches_the_call(self):
        for word, member in FACE_WALL_LOCATION_LINES.items():
            with self.subTest(word=word):
                cs = _cs([_fw(location_line=word)])
                self.assertIn(f"WallLocationLine.{member}", cs)


class Witness(unittest.TestCase):
    def test_the_geometry_witness_reads_the_built_wall(self):
        """WHAT IS READ IS THE BUILT WALL, NOT OUR OWN CALL: its exterior
        faces are queried, and among them there must be EXACTLY ONE that
        is co-directional with the named mass face."""
        cs = _cs()
        self.assertIn("HostObjectUtils.GetSideFaces(__el_", cs)
        self.assertIn("ShellLayerType.Exterior", cs)
        self.assertIn("__wfn_", cs)

    def test_the_normal_test_invents_no_tolerance(self):
        """Parallelism is decided by Revit's OWN NATIVE test, co-direction
        by the sign of the dot product. Not a single number of our own."""
        cs = _cs()
        self.assertIn("CrossProduct", cs)
        self.assertIn("IsZeroLength()", cs)
        self.assertIn("DotProduct", cs)

    def test_the_position_bound_is_revits_own_two_numbers(self):
        cs = _cs()
        self.assertIn("__ty_FW1.Width", cs)
        self.assertIn("doc.Application.VertexTolerance", cs)
        self.assertIn("get_BoundingBox(null)", cs)

    def test_the_vacuity_floor_reads_the_SOLID_not_a_parameter(self):
        """§18.3: THE WITNESS SIGNS THE AXIS IT ACTUALLY READ.

        The first version of this wave read `HOST_AREA_COMPUTED` here and
        still signed it (geometry) — that is, it certified an axis it
        never looked at. This was caught by the house's own guard, not by
        a human, and caught in the least obvious spot: a parameter WHOSE
        NAME IS ABOUT AREA looks more convincingly like geometry than many
        genuine reads. The lock is here so that the reverse fix ("just
        take the ready-made parameter, it's already computed") does not
        slip through silently.
        """
        cs = _cs()
        self.assertNotIn("HOST_AREA_COMPUTED", cs)
        self.assertIn("__warea_FW1 = __wp_FW1.Area;", cs)
        i = cs.index("площадь наружной грани построенного тела")
        self.assertIn("__warea_FW1", cs[max(0, i - 200):i])

    def test_every_verdict_signs_the_axis_it_reads(self):
        """The witness signs the axis it actually read: type — (topology),
        geometry — (geometry). A check that reads a dimension and signs
        (topology) certifies something nobody looked at."""
        cs = _cs()
        for phrase, axis in (
                ("тип построенной стены по грани", "topology"),
                ("наружных граней построенной стены", "geometry"),
                ("лежит вне габарита носителя", "geometry"),
                ("площадь наружной грани построенного тела", "geometry")):
            with self.subTest(phrase=phrase):
                i = cs.index(phrase)
                self.assertIn(axis, cs[i:i + 400])


class CommitGateInvariants(unittest.TestCase):
    def test_per_op_isolation_uses_the_op_local_refusal(self):
        """Under `per_op`, a refusal must be OP-LOCAL. A surviving
        `__t.RollBack()` inside a wrapped create would mean that one
        operation's refusal rolls back neighbors that are already
        committed — a defect closed on 07.28 and guarded by KIR-E005."""
        cs = _cs(isolation="per_op")
        self.assertIn("__OpRefuse", cs)

    def test_the_created_element_is_stamped(self):
        self.assertIn("__el_FW1", _cs())

    def test_names_read_by_the_witness_are_declared_outside_create(self):
        """THE SCOPE CONTRACT: under `per_op`, create and post land in
        DIFFERENT scopes, and a name declared inside create is invisible
        to the witness (CS0103). The Roslyn gate catches this, but only
        across all six versions at once — here it is cheaper."""
        out = _emit([_fw()], isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        # Initializers DIFFER by type (`null` for references, `0.0` for
        # numbers, `0` for a counter, `false` for a flag), so what is
        # checked is the DECLARATION itself: a name followed by an
        # assignment, not a specific initial value.
        import re as _re
        for name in ("__wfn_FW1", "__inbb_FW1", "__ty_FW1", "__hsrc_FW1",
                     "__warea_FW1", "__farea_FW1", "__wwid_FW1", "__wtol_FW1"):
            with self.subTest(name=name):
                decl_head = out.csharp.split("// create_face_wall")[0]
                self.assertRegex(decl_head, r"\b" + name + r" = [^;]+;")


class ReverseAndCensus(unittest.TestCase):
    def test_the_reverse_gap_carries_a_date_and_a_deadline(self):
        """A CAPTURE GAP WITHOUT A DEADLINE IS "SOMEDAY," NOT A DECISION.
        Importing `reverse_contract` would fail on its own, but the check
        stands here so the next reader sees WHY it is capture_gap
        specifically, and not lifter_gap: the read brings neither a
        carrier nor a face normal."""
        from kir.reverse_contract import (
            REVERSE_CONTRACTS, ReverseMode, ReverseGuarantee)
        rc = REVERSE_CONTRACTS[OP]
        self.assertIs(rc.mode, ReverseMode.CAPTURE_GAP)
        self.assertIs(rc.guarantee, ReverseGuarantee.NONE)
        self.assertEqual(rc.decided_on, "2026-08-10")
        self.assertEqual(rc.due, "2026-09-09")

    def test_the_census_key_is_exact_and_single(self):
        """The category is known EXACTLY and there is exactly one: it is
        set by the call itself, not by the type selector. No pair is
        needed here — the operation has no choice between categories in
        any field."""
        from kir.acceptance import _category_of_op
        self.assertEqual(_category_of_op({"op": OP}), ("OST_Walls",))

    def test_clash_declares_the_blind_spot_with_a_reason(self):
        """The body is real, there is no envelope, and the reason is
        NAMED: a wall's envelope is built from `LocationCurve`, and
        `FaceWall` is not a `Wall` (measured, CS0029 on all six) and has no
        `LocationCurve` at all.

        THE BLIND SPOT IS ASKED OF THE ONE WHO HOLDS IT (fix of
        11.08.2026). This used to read
        `assertIsNone(category_of({"op": OP}))` — an assertion about the
        BODY, read through an answer about the CATEGORY. These are two
        different quantities: `category_of` answers "where the result
        lands in Revit," `OP_NO_BODY` answers "can we build an envelope."
        A face-based wall IS a wall (`OST_Walls`) and has no envelope;
        exactly this is written one line above in
        `test_the_census_key_is_exact_and_single`, which requires
        `("OST_Walls",)` — that is, the file was asserting both halves at
        once and contradicting itself while one of them stayed silent.

        Of the registry's 69 ops, this is the ONLY ONE where the answers
        diverge, and hence the only one on which substituting one quantity
        for the other is noticeable. The lock on 1-of-69 stands in
        `test_clash_in_the_receipt`.
        """
        from kir.clash_bundle import OP_NO_BODY, category_of, op_categories
        self.assertIn(OP, OP_NO_BODY)
        self.assertIn("LocationCurve", OP_NO_BODY[OP])
        # There is no body — and this is asserted by the one who knows about bodies.
        self.assertNotIn(OP, __import__(
            "kir.clash_bundle", fromlist=["x"]).body_making_ops())
        # The category, meanwhile, IS KNOWN, and knowing it does not cancel the absence of a body.
        self.assertEqual(category_of({"op": OP}), "OST_Walls")
        self.assertEqual(op_categories(OP), ("OST_Walls",))


if __name__ == "__main__":
    unittest.main()
