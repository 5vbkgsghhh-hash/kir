"""wave/struct gates (2026-07-17): create_beam / create_foundation.
Mirrors test_authoring.py's structure 1:1 (Ground / CommitGateInvariants /
VersionAxis / NegativeAuthoring / PBT) — same graph of invariants proven for
create_wall/create_column, applied to the two new structural ops.

Gate checklist (REGISTRY_MODULES.md / KIR_CONNECT_SPEC.md's own checklist
style, adapted):
  (a) property: PBT over well-typed beam/foundation programs
  (b) golden 6 versions — see gate_runner.py (this wave adds programs there)
      and test_golden.py (this wave adds golden .cs files)
  (d) negative: degenerate beam (p0==p1), 2D beam point (dims enforcement),
      missing symbol/level pool (not_found/ambiguous/empty), invalid
      foundation variety (KIR-T001 at validate, KIR-E004 belt-and-suspenders
      at emit), slab holes on Revit 2021 (KIR-E003, mirrors create_floor)
  (e) invariant: 1 transaction, Regenerate before postconditions, rollback-
      on-catch, stamp+witness present
  (f) witness: StructuralType == Beam/Footing checked live in post (semantic)
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_struct_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}


def _prog(ops, intent="struct-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _beam(oid="B1", **kw):
    op = {"op": "create_beam", "id": oid,
          "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000], "level": LVL}
    op.update(kw)
    return op


def _foundation_isolated(oid="F1", **kw):
    op = {"op": "create_foundation", "id": oid, "variety": "isolated",
          "xy": [3000, 3000], "level": LVL}
    op.update(kw)
    return op


def _foundation_slab(oid="F1", **kw):
    op = {"op": "create_foundation", "id": oid, "variety": "slab",
          "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "level": LVL}
    op.update(kw)
    return op


class BeamGround(unittest.TestCase):
    def test_name_resolution_pins_id(self):
        out = compile_program(_prog([_beam(symbol={"by": "name", "value": "Балка 200x400"})]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1100)", out.csharp)

    def test_sole_entry_default_when_symbol_omitted(self):
        out = compile_program(_prog([_beam()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1100)", out.csharp)

    def test_ambiguous_symbol_never_first(self):
        snap = dict(SNAPSHOT)
        snap["beam_types"] = [{"id": 1100, "name": "Балка А"}, {"id": 1102, "name": "Балка Б"}]
        out = compile_program(_prog([_beam()]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_not_found_symbol_offers_candidates(self):
        out = compile_program(_prog([_beam(symbol={"by": "name", "value": "Нет такой балки"})]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G101"][0]
        self.assertIn("Балка 200x400", d.candidates)

    def test_no_snapshot_is_typed_refusal(self):
        out = compile_program(_prog([_beam()]), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])


class BeamCommitGateInvariants(unittest.TestCase):
    """Gate (e): the emitted C# must structurally guarantee 12.5 — textual-
    order proofs over generated code, same style as CommitGateInvariants in
    test_authoring.py."""

    def _cs(self, **kw):
        out = compile_program(_prog([_beam(**kw)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_single_transaction(self):
        self.assertEqual(self._cs().count("new Transaction"), 1)

    def test_gold_overload_shape(self):
        """The exact overload gold-verified against the SDK sample
        (CreateBeamsColumnsBraces.cs PlaceBeam): NewFamilyInstance(Line,
        FamilySymbol, Level, StructuralType.Beam), with an IsActive/Activate
        guard beforehand."""
        cs = self._cs()
        self.assertIn("Line.CreateBound(", cs)
        self.assertIn("NewFamilyInstance(__ln_", cs)
        self.assertIn("StructuralType.Beam", cs)
        self.assertIn(".IsActive) { __sy_", cs)
        self.assertIn(".Activate();", cs)

    def test_commit_strictly_after_regenerate_and_checks(self):
        cs = self._cs()
        i_regen = cs.index("doc.Regenerate()")
        i_check = cs.index("__post.Count > 0")
        i_commit = cs.index("__t.Commit()")
        self.assertLess(i_regen, i_check)
        self.assertLess(i_check, i_commit)

    def test_rollback_on_catch_present(self):
        cs = self._cs()
        self.assertIn("if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();", cs)

    def test_stamped_and_witnessed(self):
        cs = self._cs()
        self.assertIn(":B1", cs)
        self.assertIn('__results["B1"]', cs)
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)

    def test_endpoint_check_is_3d(self):
        """Beam endpoints are checked in 3D (unlike wall's 2D) — the Z
        component must appear in the postcondition guard."""
        cs = self._cs(p0_mm=[0, 0, 1500], p1_mm=[4000, 0, 2500])
        self.assertIn("MM(__a.Z) - 1500", cs)
        # The postcondition normalizes a possibly reversed Revit curve into
        # __e0/__e1 before comparing both requested 3D endpoints.
        self.assertIn("MM(__e1.Z) - 2500", cs)

    def test_topology_reference_level_and_structuraltype_semantic(self):
        """Опорный уровень балки Revit ВЫВОДИТ из отметки кривой (замерено
        27.07: передан L_01 @ 0 при кривой на Z=3000 -> привязка к
        L_01ДОО1_+2.500), поэтому свидетель проверяет, что уровень ЕСТЬ, а
        какой именно — читает в результат. Общая BIP-цепочка здесь больше не
        применяется: она проверяла равенство, которого API не обещает."""
        cs = self._cs()
        self.assertIn("INSTANCE_REFERENCE_LEVEL_PARAM", cs)
        self.assertIn("нет опорного уровня (topology)", cs)
        self.assertNotIn("level binding mismatch", cs)
        self.assertIn('"reference_level_id"', cs)
        self.assertIn("StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Beam", cs)

    def test_deterministic_emit(self):
        a = compile_program(_prog([_beam()]), snapshot=SNAPSHOT).csharp
        b = compile_program(_prog([_beam()]), snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)


class BeamVersionAxis(unittest.TestCase):
    def test_compiles_all_six_versions_offline(self):
        """Offline compile (no live gate here — see gate_runner.py for the
        real :52412 6/6) across the declared version axis."""
        from kukai.ir import spec
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_prog([_beam()]), revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])


class BeamNegative(unittest.TestCase):
    CASES = [
        (_prog([_beam(p1_mm=[0, 0, 3000])]), "KIR-T002"),          # degenerate (p0==p1)
        (_prog([_beam(p0_mm=[0, 0], p1_mm=[6000, 0])]), "KIR-T001"),  # 2D point banned (dims=(3,))
        (_prog([_beam(level="Этаж 1")]), "KIR-T001"),               # bare string, not a selector
        (_prog([_beam(), {"op": "query_count", "kind": "wall", "id": "q"}]), "KIR-L002"),  # mixed
    ]

    def test_corpus(self):
        for prog, want in self.CASES:
            with self.subTest(want=want, prog=str(prog)[:70]):
                out = compile_program(prog, snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes)
                self.assertTrue(any(c.startswith(want) for c in codes),
                                f"want {want}, got {codes}")


NASTY = ["Балка \"Т-1\"", "тип\\обратный", "100%", "…", "'кавычки'", "мм"]


class BeamPBT(unittest.TestCase):
    N = 100
    SEED = 20260717

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            x0, y0, z0 = (rng.randint(-10**5, 10**5), rng.randint(-10**5, 10**5),
                          rng.randint(0, 5000))
            x1, y1, z1 = (x0 + rng.randint(100, 20000), y0 + rng.randint(-5000, 5000),
                         z0 + rng.randint(-2000, 2000))
            op = _beam(p0_mm=[x0, y0, z0], p1_mm=[x1, y1, z1])
            if rng.random() < 0.5:
                op["symbol"] = {"by": "name", "value": "Балка 200x400"}
            out = compile_program(_prog([op], intent=rng.choice(NASTY)), snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                # Success-return is the body's final action; the trailing nested
                # __KirMainFailures/__KirPad classes are wrapper-pad scaffolding.
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


# ── create_foundation ─────────────────────────────────────────────────────────

class FoundationIsolatedGround(unittest.TestCase):
    def test_name_resolution_pins_id(self):
        out = compile_program(_prog([_foundation_isolated(
            symbol={"by": "name", "value": "Фундамент 1500x1500"})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1101)", out.csharp)

    def test_sole_entry_default_when_symbol_omitted(self):
        out = compile_program(_prog([_foundation_isolated()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1101)", out.csharp)

    def test_slab_only_pool_not_speculatively_resolved(self):
        """The bug caught live during development: an isolated foundation
        must NOT be refused just because floor_types (irrelevant to this
        variety) happens to be empty in the snapshot."""
        snap = dict(SNAPSHOT)
        snap["floor_types"] = []
        out = compile_program(_prog([_foundation_isolated()]), snapshot=snap)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_no_snapshot_is_typed_refusal(self):
        out = compile_program(_prog([_foundation_isolated()]), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])


class FoundationSlabGround(unittest.TestCase):
    def test_omitted_type_resolves_sole_entry_not_doc_default(self):
        """create_foundation's "type" is NOT in ground.py's doc-default
        special-case tuple (create_wall/create_floor/create_roof/
        create_floor_by_contour only) — a foundation slab's omitted type
        resolves via the GENERIC omitted-optional rule (sole snapshot entry,
        never doc-default). GROUND_SNAPSHOT.floor_types has exactly one
        entry (id 400), so this pins that id, same as an explicit by-name
        selector would (proven by test_named_type_pins_id below) — but via
        a different resolution path (sole_entry, not name)."""
        out = compile_program(_prog([_foundation_slab()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(400)", out.csharp)
        self.assertNotIn("GetDefaultElementTypeId(ElementTypeGroup.FloorType)", out.csharp)

    def test_omitted_type_ambiguous_when_multiple_floor_types(self):
        """Proves the sole-entry claim above isn't an accident of the fixture
        having exactly one floor_type — with two, omitted type must AMBIG
        (never silently pick the first), same as pipe's system_type/pipe_type
        rule and unlike wall/floor/roof's OWN doc-default behavior."""
        snap = dict(SNAPSHOT)
        snap["floor_types"] = [{"id": 400, "name": "Монолит 200"},
                               {"id": 401, "name": "Монолит 300"}]
        out = compile_program(_prog([_foundation_slab()]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_named_type_pins_id(self):
        out = compile_program(_prog([_foundation_slab(
            type={"by": "name", "value": "Монолит 200"})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(400)", out.csharp)

    def test_isolated_only_pool_not_speculatively_resolved(self):
        """Mirror of the isolated-side bug: a slab foundation must NOT be
        refused just because foundation_symbols happens to be empty."""
        snap = dict(SNAPSHOT)
        snap["foundation_symbols"] = []
        out = compile_program(_prog([_foundation_slab()]), snapshot=snap)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])


class FoundationCommitGateInvariants(unittest.TestCase):
    def test_isolated_gold_overload_shape(self):
        out = compile_program(_prog([_foundation_isolated()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        self.assertIn("StructuralType.Footing", cs)
        self.assertIn("StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Footing", cs)
        self.assertIn(".IsActive) { __sy_", cs)

    def test_slab_structural_flag_and_bbox_postcondition(self):
        out = compile_program(_prog([_foundation_slab()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("true, null, 0.0);", cs)     # Floor.Create(..., structural=true, ...)
        self.assertIn("FLOOR_PARAM_IS_STRUCTURAL", cs)
        self.assertIn("bbox extents mismatch (geometry)", cs)

    def test_slab_holes_2022_plus_and_2021_refusal(self):
        prog = _prog([_foundation_slab(
            holes=[[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]])])
        out2026 = compile_program(prog, revit_version="2026", snapshot=SNAPSHOT)
        self.assertTrue(out2026.ok, [d.as_dict() for d in out2026.diagnostics][:3])
        self.assertIn("CurveLoop", out2026.csharp)
        out2021 = compile_program(prog, revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out2021.ok)
        self.assertIn("KIR-E003", [d.code for d in out2021.diagnostics])

    def test_slab_2021_legacy_newfloor_structural_true(self):
        out = compile_program(_prog([_foundation_slab()]), revit_version="2021", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("doc.Create.NewFloor(__ca_", out.csharp)
        self.assertIn(", true);", out.csharp)

    def test_deterministic_emit_both_varieties(self):
        for prog in (_prog([_foundation_isolated()]), _prog([_foundation_slab()])):
            a = compile_program(prog, snapshot=SNAPSHOT).csharp
            b = compile_program(prog, snapshot=SNAPSHOT).csharp
            self.assertEqual(a, b)


class FoundationNegative(unittest.TestCase):
    CASES = [
        (_prog([_foundation_isolated(variety="strip")]), "KIR-T001"),   # outside closed enum
        # xy/outline are variety-CONDITIONAL required (see struct_emit.py's
        # module docstring): non-required at the ParamSpec level (each only
        # applies to one variety), so validate()/ground.py correctly let a
        # missing one through their generic checks — emit_foundation's own
        # presence check is what catches it, as KIR-P005 (PARSE_MISSING_
        # FIELD), not a validate()-stage KIR-T001. Reused code, on-label: the
        # field genuinely IS missing, just detected one stage later than a
        # statically-required param would be.
        (_prog([{"op": "create_foundation", "id": "F1", "variety": "isolated",
                 "level": LVL}]), "KIR-P005"),                          # xy missing (isolated)
        (_prog([{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "level": LVL}]), "KIR-P005"),                          # outline missing (slab)
        (_prog([_foundation_slab(outline=[[0, 0], [10, 0]])]), "KIR-T001"),  # <3 points
    ]

    def test_corpus(self):
        for prog, want in self.CASES:
            with self.subTest(want=want, prog=str(prog)[:80]):
                out = compile_program(prog, snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes)
                self.assertTrue(any(c.startswith(want) for c in codes),
                                f"want {want}, got {codes}")

    def test_slab_holes_obey_same_relation_laws_as_floors(self):
        op = _foundation_slab(
            outline=[[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
            holes=[[[7000, 2000], [9000, 2000], [9000, 4000], [7000, 4000]]])
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_emitter_backstop_never_reached_through_normal_validate(self):
        """FOUNDATION_UNSUPPORTED_KIND (KIR-E004) is a belt-and-suspenders
        backstop inside struct_emit.py, behind authoring.validate()'s own
        enum-choices check (which always catches an out-of-enum variety
        first, as CASES[0] above proves via KIR-T001). Exercise the backstop
        directly to prove it actually refuses rather than silently doing the
        wrong thing, since normal validate() traffic never reaches it."""
        from kukai.ir import struct_emit
        from kukai.ir.diag import KirRefusal
        bad_op = {"op": "create_foundation", "id": "F1", "variety": "grillage"}
        with self.assertRaises(KirRefusal) as ctx:
            struct_emit.emit_foundation(bad_op, "2026", "kir:test")
        self.assertEqual(ctx.exception.diagnostics[0].code, "KIR-E004")


NASTY_F = ["Фундамент \"Т-1\"", "тип\\обратный", "100%", "…", "'кавычки'", "мм"]


class FoundationPBT(unittest.TestCase):
    N = 100
    SEED = 20260717

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            if rng.random() < 0.5:
                x, y = rng.randint(-10**5, 10**5), rng.randint(-10**5, 10**5)
                op = _foundation_isolated(xy=[x, y])
                if rng.random() < 0.5:
                    op["symbol"] = {"by": "name", "value": "Фундамент 1500x1500"}
            else:
                x0 = rng.randint(-50000, 50000)
                y0 = rng.randint(-50000, 50000)
                w = rng.randint(2000, 20000)
                h = rng.randint(2000, 20000)
                op = _foundation_slab(outline=[[x0, y0], [x0 + w, y0],
                                              [x0 + w, y0 + h], [x0, y0 + h]])
            out = compile_program(_prog([op], intent=rng.choice(NASTY_F)), snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                # Success-return is the body's final action; the trailing nested
                # __KirMainFailures/__KirPad classes are wrapper-pad scaffolding.
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


if __name__ == "__main__":
    unittest.main()
