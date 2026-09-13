"""wave/site (2026-08-09): create_topography / create_building_pad /
create_site_subregion.

WHY THIS WAVE. The site family was ENTIRELY empty — zero operations out of
five API entry points. The building stood in a void: "put the house on the terrain", the most
ordinary phrase a client can say, was expressed by nothing at all, and "site" and "subregion" did not
even have a name in the language.

The structure mirrors test_arch.py 1:1 (RegistryShape / VersionAxis / Ground /
Negative / Witness / CommitGateInvariants) — the same graph of invariants
already proven for create_ceiling/create_railing.

THE VERSION AXIS AND EVERY API MEMBER ARE MEASURED BY COMPILATION ON :52412 (09.08.2026, six
reference builds), not taken from memory and not from `data/revit_api_db.json` —
the measurement table is in the header of ops_site.py. Only the conclusions that
are checked by the code below are repeated here:

  * `TopographySurface.Create` and `GetPoints` — 6/6, and this is the STRONGEST
    witness of the wave: the element gives back exactly the points it was given;
  * the `Toposolid` class does not exist before 2024 (CS0246 on 2021/2022/2023), so
    variety="toposolid" below produces a typed refusal, KIR-E003, that NAMES
    the next move, rather than a silent fallback to a surface (that is an element of a DIFFERENT
    category);
  * `Toposolid.GetPoints()` does not exist on ANY version (CS1061 wherever
    the type itself exists), so point-by-point reading of the mass goes through
    `GetSlabShapeEditor()`, and the confident predicate is the bounding box;
  * `SiteSubRegion` is NOT an `Element` (CS0029/CS1061 on all six): it has neither
    `.Id` nor `get_Parameter`. The subregion's element is its `.TopographySurface`,
    and that is exactly what gets stamped, read into the receipt, and witnessed.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_site_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: Five survey points: four corners and one in the middle. No pair
#: coincides in plan and none are collinear — that is, the cloud is legal under
#: all three laws of geom.validate_points_xyz.
PTS = [[0, 0, 0], [24000, 0, 800], [24000, 18000, 1500],
       [0, 18000, 400], [12000, 9000, 1100]]

RECT_REGION = {"outer": {"shape": "rect", "origin": [2000, 2000],
                         "size_mm": [12000, 9000]}}


def _prog(ops, intent="site-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _surface(oid="T1", **kw):
    op = {"op": "create_topography", "id": oid, "variety": "surface",
          "points_mm": PTS}
    op.update(kw)
    return op


def _toposolid(oid="T1", **kw):
    op = {"op": "create_topography", "id": oid, "variety": "toposolid",
          "points_mm": PTS, "level": LVL}
    op.update(kw)
    return op


def _pad(oid="P1", **kw):
    op = {"op": "create_building_pad", "id": oid, "contour": RECT_REGION,
          "level": LVL}
    op.update(kw)
    return op


def _subregion(oid="R1", **kw):
    op = {"op": "create_site_subregion", "id": oid, "contour": RECT_REGION}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _cs(op, ver="2026"):
    out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
    assert out.ok, _codes(out)
    return out.csharp


# ── registry ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    OPS = ("create_topography", "create_building_pad",
           "create_site_subregion")

    def test_all_three_ops_are_registered_as_writers(self):
        for name in self.OPS:
            with self.subTest(op=name):
                self.assertIn(name, spec.OPS)
                self.assertTrue(spec.OPS[name].writes_model)
                self.assertEqual(spec.OPS[name].family, "authoring")

    def test_the_type_pools_are_their_own(self):
        """The mass is NOT grounded against floor_types; the pad is grounded against its own pool.

        A foreign pool would give a PLAUSIBLE but wrong type, and a type substitution
        is indistinguishable from success from the outside — exactly what §18.1 forbids."""
        topo = {p: pool for p, pool, _ in spec.OPS["create_topography"].grounded}
        pad = {p: pool for p, pool, _ in
               spec.OPS["create_building_pad"].grounded}
        self.assertEqual(topo["type"], "toposolid_types")
        self.assertEqual(pad["type"], "building_pad_types")

    def test_the_subregion_grounds_nothing(self):
        """The subregion has neither a level nor a type — neither is in the API signature either.

        A pool of topography surfaces does not exist in the snapshot, so `host`
        is addressed by id or by reference; introducing a pool for `by:name` would mean
        promising resolution by name where the surface's name is not
        its address (the same seam as in create_railing.host)."""
        self.assertEqual(spec.OPS["create_site_subregion"].grounded, ())

    def test_the_terrain_point_is_three_dimensional(self):
        """A flat kind would silently zero the terrain into a plane: the surface
        has no level at all, and the elevation lives in the Z of each point."""
        kinds = {p.name: p.kind for p in spec.OPS["create_topography"].params}
        self.assertEqual(kinds["points_mm"], "pts_xyz")

    def test_variety_is_required_and_has_no_default(self):
        """Substituting the variety on the author's behalf means choosing for them an element
        of a DIFFERENT category."""
        variety = next(p for p in spec.OPS["create_topography"].params
                       if p.name == "variety")
        self.assertTrue(variety.required)
        self.assertIsNone(variety.default)
        self.assertEqual(set(variety.choices), {"surface", "toposolid"})


# ── the version axis ───────────────────────────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_the_surface_builds_on_every_shipped_version(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_surface()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("TopographySurface.Create(doc,", out.csharp)

    def test_the_toposolid_refuses_below_2024_and_names_the_next_move(self):
        """A refusal, not a substitution. Silently falling back to a surface is not allowed: it has
        a DIFFERENT category (OST_Topography versus OST_Toposolid), a different
        binding, and a different witness — that is, it would be a different element
        passed off as the one requested."""
        for ver in ("2021", "2022", "2023"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_toposolid()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-E003", _codes(out))
                text = " ".join(d.message_ru or "" for d in out.diagnostics)
                self.assertIn("surface", text,
                              "отказ обязан НАЗВАТЬ следующий ход")

    def test_the_toposolid_builds_on_2024_and_later(self):
        for ver in ("2024", "2025", "2026"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_toposolid()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("Toposolid.Create(doc,", out.csharp)

    def test_pad_and_subregion_build_on_every_shipped_version(self):
        for ver in spec.REVIT_VERSIONS:
            for op in (_pad(), _subregion()):
                with self.subTest(version=ver, op=op["op"]):
                    out = compile_program(_prog([op]), revit_version=ver,
                                          snapshot=SNAPSHOT)
                    self.assertTrue(out.ok, _codes(out))

    def test_the_host_probe_names_toposolid_only_where_it_exists(self):
        """AN EMISSION BRANCH, NOT DECORATION: on 2021-2023 a mention of `Toposolid`
        in the candidate counter would be a CS0246, meaning the pad would stop
        compiling on half the fleet."""
        for ver in ("2021", "2022", "2023"):
            with self.subTest(version=ver):
                self.assertNotIn("Toposolid", _cs(_pad(), ver))
        for ver in ("2024", "2025", "2026"):
            with self.subTest(version=ver):
                self.assertIn("typeof(Toposolid)", _cs(_pad(), ver))


# ── grounding ────────────────────────────────────────────────────────────────

class Ground(unittest.TestCase):

    def test_the_surface_gets_no_level_and_no_type(self):
        """TopographySurface.Create has NO level in its signature at all. The general
        "sole entry in the pool" rule would give the surface a tie to a
        story that it cannot possibly have, and the witness would start checking
        something made up."""
        cs = _cs(_surface())
        self.assertNotIn("Level __lv_", cs)
        self.assertNotIn("__ty_", cs)

    def test_the_toposolid_resolves_the_sole_pool_type(self):
        # 1700, not 1300: block 1300-1301 was taken by the strip footing, and
        # the pad's ids moved to the next free hundred during the merge on 09.08.
        cs = _cs(_toposolid())
        self.assertIn("ToposolidType __ty_T1 = doc.GetElement("
                      "new ElementId(1700))", cs)

    def test_the_pad_never_substitutes_a_document_default_type(self):
        """The pad DOES have a default type in the API
        (ElementTypeGroup.BuildingPadType, 6/6 — measured), and it is deliberately
        NOT used: a "default pad" on someone else's building is almost
        never the right one, and a type substitution is indistinguishable from success from the outside. The
        doc_default branch in the emitter's first draft was DEAD (ground hands out
        `in_emit=default` to four ops, and the pad is not among them) — this test
        keeps the decision explicit so the dead branch does not come back."""
        cs = _cs(_pad())
        self.assertNotIn("GetDefaultElementTypeId", cs)
        self.assertIn("BuildingPadType __ty_P1 = doc.GetElement("
                      "new ElementId(1701))", cs)

    def test_an_ambiguous_pad_type_is_a_typed_question_not_a_guess(self):
        snap = dict(SNAPSHOT)
        snap["building_pad_types"] = [{"id": 1701, "name": "Площадка 200"},
                                      {"id": 1702, "name": "Площадка 400"}]
        out = compile_program(_prog([_pad()]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))


# ── typed refusals ────────────────────────────────────────────────────

class Negative(unittest.TestCase):

    def test_a_toposolid_without_a_level_is_a_typed_refusal(self):
        """The mass's level is required by the signature of Toposolid.Create itself. The fixture's
        level pool carries TWO levels, so the general "sole entry in the
        pool" rule does not fire here and the question reaches the author."""
        op = _toposolid()
        op.pop("level")
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))

    def test_two_points_over_one_plan_spot_are_refused(self):
        """At one point of the plan, terrain has exactly ONE elevation. Accepting both would mean
        letting Revit silently choose one — that is, building the wrong terrain,
        and from the outside this is indistinguishable from success."""
        pts = PTS + [[24000, 0, 5000]]      # the same plan position as point 1
        out = compile_program(_prog([_surface(points_mm=pts)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T004", _codes(out))

    def test_a_third_point_does_not_hide_behind_an_overwritten_neighbour(self):
        """🔴 A GRID CELL HELD ONE INDEX, AND THE SECOND POINT ERASED THE FIRST.

        Points 0 and 1 fall into the same cell and are legal (0.127 mm at a tolerance of
        0.1), so point 1 was written over the place of point 0. Point 2
        diverges from point 1 by 0.120 mm and also passes — while against the FORGOTTEN
        point 0 it sits at 0.01 mm, with a difference in elevation of 0 and 2000 mm.
        Both elevations were accepted, and Revit silently picked one.
        """
        pts = [[0, 0, 0], [0.09, 0.09, 1000], [0.01, 0, 2000],
               [100000, 0, 0], [0, 100000, 0]]
        out = compile_program(_prog([_surface(points_mm=pts)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok, "две отметки в одном плане ПРИНЯТЫ")
        self.assertIn("KIR-T004", _codes(out))

    def test_a_collinear_point_cloud_is_refused(self):
        """A diagonal chain of points: the bounding frame has both dimensions
        non-zero, and yet there will still be no surface. An instrument that sees
        only axis-aligned degeneracy is more dangerous than none at all."""
        pts = [[0, 0, 0], [1000, 1000, 100], [2000, 2000, 200],
               [3000, 3000, 300]]
        out = compile_program(_prog([_surface(points_mm=pts)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T004", _codes(out))

    def test_a_flat_two_dimensional_point_is_refused(self):
        """This is exactly why a separate kind was introduced: [x,y] would zero out the
        ground elevation, and terrain at a zero elevation is a DIFFERENT terrain."""
        out = compile_program(
            _prog([_surface(points_mm=[[0, 0], [1000, 0], [0, 1000]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", _codes(out))

    def test_fewer_than_three_points_is_refused(self):
        out = compile_program(
            _prog([_surface(points_mm=[[0, 0, 0], [1000, 0, 0]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_an_unknown_variety_never_reaches_the_emitter(self):
        out = compile_program(_prog([_surface(variety="mountain")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── witnesses: we read the RESULT, not the call ──────────────────────────────────

class Witness(unittest.TestCase):

    def test_the_surface_rereads_its_own_points(self):
        """The STRONGEST witness of the wave: what is compared is not "we called
        Create" but the set of points given back by the BUILT element."""
        cs = _cs(_surface())
        self.assertIn("__el_T1.GetPoints()", cs)
        self.assertIn("DistanceTo", cs)
        self.assertIn("описанных точек рельефа нет в GetPoints() (geometry)", cs)

    def test_the_point_witness_can_actually_fail(self):
        """A check that cannot fail is worse than no check at all.
        Here the failure is expressed explicitly: a counter of points not found and a verdict
        based on it."""
        cs = _cs(_surface())
        self.assertIn("if (__miss_T1 > 0)", cs)
        self.assertIn("__post.Add", cs.split("if (__miss_T1 > 0)")[1][:400])

    def test_the_toposolid_reads_vertices_and_reports_unreadability(self):
        """For the mass, GetPoints() DOES NOT EXIST, so points are read from the
        shape editor. Whether it can be read for a mass built FROM POINTS is a
        fact about LIVE Revit, unverifiable offline; so an inaccessible editor
        here is not a verdict but a number in the receipt: "we could not read it" must not
        look like "it matched"."""
        cs = _cs(_toposolid())
        self.assertIn("GetSlabShapeEditor()", cs)
        self.assertIn("SlabShapeVertices", cs)
        self.assertIn('__rb["slab_shape_vertices"] = __vcnt_T1;', cs)
        self.assertIn("if (__vcnt_T1 > 0)", cs)

    def test_the_pad_rereads_its_boundary_not_its_bounding_box(self):
        """The bounding box of the pad's SOLID includes its thickness and its cut into the terrain;
        what is read is the boundary itself — that is, exactly the sketch that was passed in."""
        cs = _cs(_pad())
        self.assertIn("__el_P1.GetBoundary()", cs)
        self.assertIn("Tessellate()", cs)
        self.assertIn("boundary bbox mismatch (geometry)", cs)

    def test_the_pad_reads_the_host_revit_chose_itself(self):
        """A genuine read of the result, not an echo of the argument: we did not
        pass a host — BuildingPad.Create has none in its signature at all."""
        cs = _cs(_pad())
        self.assertIn("AssociatedTopographySurfaceId", cs)
        self.assertIn("площадка не привязана к топоповерхности (topology)", cs)

    def test_a_pad_with_no_host_refuses_before_creating_anything(self):
        """A typed refusal WITH A NAMED NEXT MOVE, instead of an
        InvalidOperationException that the pipeline would record as "something broke on
        our end". The check is NECESSARY, not sufficient, and it stands
        BEFORE the call."""
        cs = _cs(_pad())
        probe = cs.index("__hosts_P1 =")
        self.assertLess(probe, cs.index("BuildingPad.Create"))
        self.assertIn("create_topography", cs)

    def test_the_subregion_witnesses_a_boolean_it_never_wrote(self):
        cs = _cs(_subregion())
        self.assertIn("__el_R1.IsSiteSubRegion", cs)
        self.assertIn("не помечена как подобласть (semantic)", cs)

    def test_the_subregion_owns_the_surface_not_the_wrapper(self):
        """SiteSubRegion is NOT an Element (CS0029/CS1061 on all six): it has
        neither `.Id` nor `get_Parameter`. The stamp and the receipt must stand on
        its TopographySurface, otherwise ownership is lost — A5 checks it exactly
        against the receipt."""
        cs = _cs(_subregion())
        self.assertIn("__el_R1 = __sr_R1.TopographySurface;", cs)
        self.assertNotIn("__sr_R1.Id", cs)
        self.assertIn('__rb["id"] = __el_R1.Id.ToString();', cs)

    def test_the_subregion_checks_the_named_host_only_when_named(self):
        with_host = _cs(_subregion(host={"by": "element_id", "value": 7777}))
        self.assertIn("принадлежит не запрошенной топоповерхности", with_host)
        without = _cs(_subregion())
        self.assertIn("не принадлежит ни одной топоповерхности", without)
        self.assertNotIn("принадлежит не запрошенной", without)

    def test_every_verdict_signs_the_axis_it_read(self):
        """The witness signs the axis it actually read: points and
        boundary — (geometry), bindings — (topology), the subregion flag —
        (semantic)."""
        for op, expected in ((_surface(), "(geometry)"),
                             (_pad(), "(topology)"),
                             (_subregion(), "(semantic)")):
            with self.subTest(op=op["op"], axis=expected):
                self.assertIn(expected, _cs(op))


# ── house invariants ──────────────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def test_no_emitter_hand_types_the_refusal_statement(self):
        """`emit_utils.refuse_stmt` is the SOLE owner of the refusal text.
        A hand-typed refusal in per_op would roll back already-committed
        neighbors."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "site_emit.py").read_text(encoding="utf-8")
        self.assertNotIn("__t.RollBack(); return __Refuse(", src)

    def test_per_op_isolation_never_carries_whole_program_refusals(self):
        for op in (_surface(), _toposolid(), _pad(), _subregion()):
            with self.subTest(op=op["op"], variety=op.get("variety")):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT, isolation="per_op")
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("throw __OpRefuse(", out.csharp)

    def test_the_registry_tolerances_are_the_ones_emitted(self):
        """The number lives in the registry, not in the emitted C# (the law of provenance)."""
        self.assertEqual(spec.OPS["create_topography"].tolerances,
                         {"point_mm": 1.0, "bbox_mm": 50.0})
        cs = _cs(_surface())
        self.assertIn("<= U(1.0)", cs)
        self.assertIn("> 50.0", cs)

    def test_the_reverse_direction_is_declared_a_capture_gap(self):
        """A promise of a lift that does not exist rots silently — the manifest
        exists precisely so that this does not happen."""
        from kir.reverse_contract import REVERSE_CONTRACTS
        for name in ("create_topography", "create_building_pad",
                     "create_site_subregion"):
            with self.subTest(op=name):
                self.assertFalse(
                    REVERSE_CONTRACTS[name].direct_same_op_lift)

    def test_the_translation_certificate_proves_every_branch(self):
        """The certificate is taken from EVERY branch, not from one: a branch
        the corpus does not build is certified only in the negative."""
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_program
        for op, ver in ((_surface(), "2021"), (_surface(), "2026"),
                        (_toposolid(), "2026"), (_pad(), "2021"),
                        (_pad(), "2026"), (_subregion(), "2026"),
                        (_subregion(host={"by": "element_id", "value": 7777}),
                         "2026")):
            with self.subTest(op=op["op"], variety=op.get("variety"), ver=ver):
                grounded = ground_mod.ground(_parse_and_check(_prog([op])),
                                             SNAPSHOT)
                cert = certify_program(grounded, ver)
                self.assertTrue(cert.proven, cert.gaps)


if __name__ == "__main__":
    unittest.main()
