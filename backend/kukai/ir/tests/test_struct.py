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
        self.assertIn("KIR-T004", [d.code for d in out.diagnostics])

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


# ── create_wall_foundation (wave/wall-foundation, 2026-08-09) ────────────────
#
# Тот же граф инвариантов (Ground / CommitGateInvariants / VersionAxis /
# Negative / PBT), плюс два, которых у прежних опов волны нет:
#
#   * ДВЕ ВЕТВИ ССЫЛКИ НА НОСИТЕЛЯ. ref внутрь программы и element_id наружу —
#     это разный C# (ветвь ref не заводит своей переменной стены вовсе), и
#     проверять одну вместо двух значит не проверять ветвление.
#   * ДОКУМЕНТНЫЙ ТИП ПО УМОЛЧАНИЮ. Пул фикстуры содержит ДВЕ записи именно
#     затем, чтобы «умолчание» нельзя было спутать с «единственный в пуле»:
#     на двух записях общее правило дало бы KIR-G102, а doc_default обязан
#     пройти.

WALL_REF = {"by": "ref", "value": "W1"}
WALL_ID = {"by": "element_id", "value": 8145901}


def _wall_op(oid="W1"):
    return {"op": "create_wall", "id": oid, "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": LVL}


def _wf(oid="WF1", wall=None, **kw):
    op = {"op": "create_wall_foundation", "id": oid,
          "wall": dict(WALL_ID) if wall is None else wall}
    op.update(kw)
    return op


class WallFoundationGround(unittest.TestCase):
    def test_named_type_pins_id(self):
        out = compile_program(
            _prog([_wf(type={"by": "name", "value": "Ленточный 900x400"})]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("__tyid_WF1 = new ElementId(1301);", out.csharp)

    def test_omitted_type_takes_the_document_default_not_the_pool(self):
        """Пропущенный тип уходит в документ, а НЕ в «единственный в пуле».

        Проверяется на пуле из ДВУХ записей: общее правило здесь отказало бы
        KIR-G102, значит зелёный результат доказывает именно ветвь
        doc_default, а не совпадение. Спросить документ можно потому, что
        ElementTypeGroup.WallFoundationType компилируется на всех шести
        версиях — замер, а не надежда (у ограждения этого члена нет вовсе).
        """
        self.assertEqual(len(SNAPSHOT["wall_foundation_types"]), 2)
        out = compile_program(_prog([_wf()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn(
            "__tyid_WF1 = doc.GetDefaultElementTypeId("
            "ElementTypeGroup.WallFoundationType);", out.csharp)
        self.assertNotIn("new ElementId(1300)", out.csharp)

    def test_missing_document_default_is_a_typed_refusal_not_a_guess(self):
        """Ветвь по умолчанию обязана иметь свой отказ: документ может не
        иметь типа ленточного фундамента вовсе, и тогда
        GetDefaultElementTypeId даёт InvalidElementId."""
        cs = compile_program(_prog([_wf()]), snapshot=SNAPSHOT).csharp
        self.assertIn("if (doc.GetElement(__tyid_WF1) as WallFoundationType "
                      "== null)", cs)
        self.assertIn("в документе нет типа по умолчанию", cs)

    def test_not_found_type_offers_candidates(self):
        out = compile_program(
            _prog([_wf(type={"by": "name", "value": "Нет такой ленты"})]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G101"][0]
        self.assertIn("Ленточный 600x300", d.candidates)

    def test_ambiguous_named_type_never_takes_the_first(self):
        snap = dict(SNAPSHOT)
        snap["wall_foundation_types"] = [
            {"id": 1300, "name": "Ленточный"}, {"id": 1301, "name": "Ленточный"}]
        out = compile_program(
            _prog([_wf(type={"by": "name", "value": "Ленточный"})]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_no_snapshot_is_typed_refusal(self):
        out = compile_program(_prog([_wf()]), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])


class WallFoundationHostBranches(unittest.TestCase):
    """Оба рода адресации носителя, каждый со своим C#."""

    def test_intra_program_ref_to_a_wall_built_by_the_same_program(self):
        """ГЛАВНЫЙ СЦЕНАРИЙ: построй стену, затем её фундамент.

        Ссылка обязана вести на ПЕРЕМЕННУЮ стены-соседа, а не на GetElement:
        у только что созданной стены нет id до коммита.
        """
        out = compile_program(
            _prog([_wall_op(), _wf(wall=WALL_REF)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        cs = out.csharp
        self.assertIn("WallFoundation.Create(doc, __tyid_WF1, __el_W1.Id);", cs)
        # Ветвь ref СВОЕЙ переменной стены не заводит — иначе она бы
        # перечитывала из документа то, чего там ещё нет.
        self.assertNotIn("Wall __hw_WF1", cs)
        # ... и её свидетель сверяется с той же переменной.
        self.assertIn("__rdw_WF1.WallId.ToString() != __el_W1.Id.ToString()", cs)

    def test_element_id_host_is_reread_and_type_checked_at_runtime(self):
        cs = compile_program(_prog([_wf(wall=WALL_ID)]), snapshot=SNAPSHOT).csharp
        self.assertIn("Wall __hw_WF1 = null;", cs)
        self.assertIn("__hw_WF1 = doc.GetElement(new ElementId(8145901)) as Wall;", cs)
        self.assertIn("WallFoundation.Create(doc, __tyid_WF1, __hw_WF1.Id);", cs)

    def test_host_declared_outside_the_create_block(self):
        """Переменная носителя объявляется в decl, а не внутри create.

        При isolation="per_op" блок создания заворачивается в собственный
        try, и объявление внутри него умирает на закрывающей скобке — ровно
        так падало ограждение живыми воротами (CS0103). Свидетель читает
        __hw_<s>, значит объявление обязано быть снаружи.
        """
        cs = compile_program(_prog([_wf(wall=WALL_ID)]), snapshot=SNAPSHOT,
                             isolation="per_op").csharp
        i_decl = cs.index("Wall __hw_WF1 = null;")
        i_try = cs.index("SubTransaction __st_WF1")
        self.assertLess(i_decl, i_try,
                        "объявление носителя попало внутрь per_op-области")


class WallFoundationWitness(unittest.TestCase):
    """Свидетель читает РЕЗУЛЬТАТ, а не вызов, — и подписывает ту ось,
    которую действительно читал."""

    def _cs(self, **kw):
        out = compile_program(_prog([_wf(**kw)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_the_element_is_reread_from_the_document(self):
        """Возвращённый Create'ом объект на веру не берётся: свидетель идёт в
        документ по id и требует, чтобы там лежал именно WallFoundation."""
        cs = self._cs()
        self.assertIn("var __rdw_WF1 = doc.GetElement(__el_WF1.Id) "
                      "as WallFoundation;", cs)
        self.assertIn("не читается из документа как WallFoundation (topology)",
                      cs)

    def test_host_topology_is_exact_equality_with_no_tolerance(self):
        cs = self._cs()
        self.assertIn("__rdw_WF1.WallId.ToString() != __hw_WF1.Id.ToString()", cs)
        self.assertIn("WallId != стены-носителя (topology)", cs)
        # Ни одного допуска: это равенство id, а не измерение. Реестр тоже
        # не должен нести чисел — иначе ссылка ушла бы в пустоту.
        from kukai.ir import spec
        self.assertEqual(spec.OPS["create_wall_foundation"].tolerances, {})

    def test_semantic_type_witness_compares_the_built_type(self):
        cs = self._cs(type={"by": "name", "value": "Ленточный 900x400"})
        self.assertIn("__rdt_WF1.GetTypeId().ToString() != __tyid_WF1.ToString()",
                      cs)
        self.assertIn("тип фундамента != запрошенного (semantic)", cs)

    def test_no_geometric_claim_is_made_anywhere(self):
        """Габарита нет ни в C#, ни в обещании — и это НАЗВАНО в post.

        Свес подошвы за стену не замерен (в сохранённых разборах ноль
        WallFoundation), поэтому любой bbox-допуск был бы выдуман. Молчать об
        этом нельзя: читатель обязан видеть, что геометрию здесь никто не
        сторожит.
        """
        cs = self._cs()
        post = cs[cs.index("// post WF1"):]
        post = post[:post.index("// witness")]
        self.assertNotIn("get_BoundingBox", post)
        self.assertNotIn("BoundingBox", post)
        from kukai.ir import spec
        self.assertIn("NOT witnessed on purpose",
                      spec.OPS["create_wall_foundation"].post)

    def test_element_id_idiom_is_the_one_safe_on_all_six(self):
        """.Value — 2024+, .IntegerValue — по 2025; универсален только
        ToString(). Свидетель сравнивает id ИМЕННО так."""
        cs = self._cs()
        self.assertNotIn(".IntegerValue", cs)
        self.assertNotIn(".WallId.Value", cs)

    def test_the_certificate_accepts_the_op_on_every_version(self):
        """Обещание и свидетель связаны сертификатом, а не соседством в
        файле: у каждой клаузулы post обязано быть своё обязательство."""
        from kukai.ir import translation_cert as cert
        from kukai.ir import ground as ground_mod, spec
        from kukai.ir.compiler import _parse_and_check
        self.assertEqual(cert.audit_registry_coverage(), ())
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_wf()])), SNAPSHOT)[0]
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                self.assertTrue(cert.certify_op(grounded, ver).proven)


class WallFoundationCommitGateInvariants(unittest.TestCase):
    def _cs(self, **kw):
        out = compile_program(_prog([_wf(**kw)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_single_transaction(self):
        self.assertEqual(self._cs().count("new Transaction"), 1)

    def test_the_measured_call_shape(self):
        """WallFoundation.Create(Document, typeId, wallId) — одна подпись на
        все шесть версий (компиляция на :52412, 09.08, 6/6)."""
        self.assertIn("WallFoundation.Create(doc, __tyid_WF1, __hw_WF1.Id);",
                      self._cs())

    def test_commit_strictly_after_regenerate_and_checks(self):
        cs = self._cs()
        self.assertLess(cs.index("doc.Regenerate()"), cs.index("__post.Count > 0"))
        self.assertLess(cs.index("__post.Count > 0"), cs.index("__t.Commit()"))

    def test_rollback_on_catch_present(self):
        self.assertIn("if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();",
                      self._cs())

    def test_stamped_and_witnessed(self):
        cs = self._cs()
        self.assertIn(":WF1", cs)
        self.assertIn('__results["WF1"]', cs)

    def test_null_create_is_a_typed_refusal(self):
        """Предполётной проверки в API НЕТ (WallAllowsWallFoundation не
        существует ни на одной версии — CS0117 6/6, это метод WallSweep), так
        что негодная стена видна только по null. Молчать про null нельзя."""
        self.assertIn("WallFoundation.Create вернул null", self._cs())

    def test_refusal_statement_has_one_owner_in_both_isolations(self):
        """emit_utils.refuse_stmt — единственный владелец фразы отказа;
        уцелевший __t.RollBack() внутри per_op-создания это KIR-E005."""
        from kukai.ir.emit_utils import program_refusal_tokens
        from kukai.ir import struct_emit, ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_wf()])), SNAPSHOT)[0]
        _d, create, _p, _r = struct_emit.emit_wall_foundation(
            grounded, "2026", "kir:test", "per_op")
        self.assertEqual(program_refusal_tokens(create), [])
        self.assertIn("throw __OpRefuse(", create)

    def test_deterministic_emit(self):
        prog = _prog([_wall_op(), _wf(wall=WALL_REF)])
        self.assertEqual(compile_program(prog, snapshot=SNAPSHOT).csharp,
                         compile_program(prog, snapshot=SNAPSHOT).csharp)


class WallFoundationVersionAxis(unittest.TestCase):
    def test_compiles_all_six_versions_offline(self):
        """Оси версий у этого опа НЕТ, и это замер: подпись
        WallFoundation.Create байт-в-байт одинакова на 2021-2026 (живые
        ворота :52412, 09.08, 24/24 включая обе изоляции). Здесь — офлайн-
        половина: эмиссия обязана состояться на каждой версии, и тело
        обязано отличаться ТОЛЬКО литералом ElementId (общий _eid)."""
        from kukai.ir import spec
        bodies = {}
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_prog([_wf()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                body = out.csharp[out.csharp.index("// create_wall_foundation"):]
                bodies[ver] = body[:body.index("doc.Regenerate()")]
        self.assertEqual(len(set(bodies.values())), 1,
                         "тело разъехалось по версиям, хотя подпись одна")


class WallFoundationNegative(unittest.TestCase):
    CASES = [
        # Носитель обязателен: без него операция бессмысленна (уровень, путь
        # и протяжённость фундамент берёт у стены).
        (_prog([{"op": "create_wall_foundation", "id": "WF1"}]), "KIR-T001"),
        # Голая строка вместо селектора.
        (_prog([_wf(wall="стена")]), "KIR-T001"),
        # by=name носителя не бывает: стена адресуется id или ссылкой.
        (_prog([_wf(wall={"by": "name", "value": "Стена"})]), "KIR-T001"),
        # Ссылка в никуда.
        (_prog([_wf(wall={"by": "ref", "value": "НЕТ"})]), "KIR-L003"),
        # Смешение чтения и записи.
        (_prog([_wf(), {"op": "query_count", "kind": "wall", "id": "q"}]),
         "KIR-L002"),
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

    def test_ref_to_a_non_wall_is_refused_before_emission(self):
        """НОСИТЕЛЬ, КОТОРЫЙ НЕ СТЕНА, — ОТКАЗ, А НЕ ПОПЫТКА.

        Внутрипрограммная ссылка типизирована: ref_kinds=(WALL,), а
        create_floor отдаёт результат рода ELEMENT. Плановая стадия видит
        расхождение и отказывает KIR-L004 ДО эмиссии — то есть неверный
        носитель невыразим, а не «отвалится в Revit».
        """
        out = compile_program(_prog([
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "level": LVL},
            _wf(wall={"by": "ref", "value": "F1"}),
        ]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-L004"][0]
        self.assertEqual(d.expected, ["wall"])
        self.assertEqual(d.got, "element")

    def test_element_id_host_that_is_not_a_wall_refuses_at_runtime(self):
        """У ветви element_id компилятор рода цели не знает — id указывает
        куда угодно. Значит проверка обязана быть в C#: `as Wall` даёт null,
        и это ТИПИЗИРОВАННЫЙ отказ с названной причиной, а не NullReference
        и не тихий пропуск."""
        cs = compile_program(_prog([_wf(wall=WALL_ID)]), snapshot=SNAPSHOT).csharp
        i_res = cs.index("__hw_WF1 = doc.GetElement(new ElementId(8145901)) as Wall;")
        guard = cs[i_res:cs.index("WallFoundation.Create", i_res)]
        self.assertIn("if (__hw_WF1 == null)", guard)
        self.assertIn("не является стеной", guard)
        self.assertIn("return __Refuse(\"WF1\"", guard)

    def test_ungrounded_type_is_a_typed_refusal_not_a_keyerror(self):
        """Эмиттер — последний рубеж: тип, не прошедший ground, обязан дать
        KIR-P005, а не голый KeyError (тот всплыл бы как KIR-P000
        «внутренняя ошибка» — fail-closed, но диагностика хуже)."""
        from kukai.ir import struct_emit
        from kukai.ir.diag import KirRefusal
        with self.assertRaises(KirRefusal) as ctx:
            struct_emit.emit_wall_foundation(
                {"op": "create_wall_foundation", "id": "WF1",
                 "wall": dict(WALL_ID)}, "2026", "kir:test")
        self.assertEqual(ctx.exception.diagnostics[0].code, "KIR-P005")


class WallFoundationPBT(unittest.TestCase):
    N = 60
    SEED = 20260809

    def test_properties(self):
        rng = random.Random(self.SEED)
        names = [r["name"] for r in SNAPSHOT["wall_foundation_types"]]
        for case in range(self.N):
            ops = []
            if rng.random() < 0.5:
                ops.append(_wall_op())
                op = _wf(wall=dict(WALL_REF))
            else:
                op = _wf(wall={"by": "element_id",
                               "value": rng.randint(1, 2 ** 31 - 1)})
            if rng.random() < 0.5:
                op["type"] = {"by": "name", "value": rng.choice(names)}
            ops.append(op)
            out = compile_program(_prog(ops, intent=rng.choice(NASTY_F)),
                                  snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


# ── wave/framing (2026-08-09): create_beam_system / create_truss ────────────

BS_RECT = {"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [8000, 6000]}}
BS_ARC = {"outer": {"shape": "poly",
                    "points_mm": [[0, 0], [9000, 0], [9000, 5000], [0, 5000]],
                    "arcs": [{"edge": 1, "bulge": 0.3}]}}


def _bs(oid="BS1", **kw):
    op = {"op": "create_beam_system", "id": oid,
          "profile": {"outer": dict(BS_RECT["outer"])}, "level": LVL}
    op.update(kw)
    return op


def _truss(oid="TR1", **kw):
    op = {"op": "create_truss", "id": oid, "p0_mm": [0, 0], "p1_mm": [12000, 0],
          "level": LVL}
    op.update(kw)
    return op


class BeamSystemContour(unittest.TestCase):
    """CONTOUR потреблён ЦЕЛИКОМ, кроме второго кольца — и это не «почти»,
    а названная граница: `BeamSystem.Create` принимает профиль ОДНИМ плоским
    IList<Curve>."""

    def test_arc_profile_lowers_to_three_literal_points(self):
        out = compile_program(_prog([_bs(profile=BS_ARC, direction_edge=0)]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        # Вся тригонометрия — в питоне: в C# уезжает Arc.Create по трём
        # ЛИТЕРАЛЬНЫМ точкам, ни одного вычисления дуги в рантайме.
        self.assertIn("__prof_BS1.Add(Arc.Create(", out.csharp)
        self.assertIn("IList<Curve> __prof_BS1 = new List<Curve>();", out.csharp)

    def test_profile_holes_are_a_typed_refusal_not_a_silent_drop(self):
        prof = {"outer": dict(BS_RECT["outer"]),
                "holes": [{"shape": "rect", "origin": [1000, 1000],
                           "size_mm": [2000, 2000]}]}
        out = compile_program(_prog([_bs(profile=prof)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E008", [d.code for d in out.diagnostics])

    def test_contour_laws_come_for_free_from_the_region_kind(self):
        """Ни одного собственного закона эскиза оп не пишет: и вырожденную
        площадь, и самопересечение ловит CONTOUR — потому что параметр
        объявлен родом `region`, а не потому, что эмиттер их проверяет.
        Отказ обязан указывать на ПОЛЕ ЭТОГО ОПА, иначе он был бы про
        чужой эскиз."""
        bowtie = {"outer": {"shape": "poly",
                            "points_mm": [[0, 0], [8000, 6000], [8000, 0],
                                          [0, 6000]]}}
        out = compile_program(_prog([_bs(profile=bowtie)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(out.diagnostics[0].field_name.startswith("profile"))
        self.assertIn(out.diagnostics[0].code, ("KIR-T002", "KIR-T004"))

    def test_self_intersection_with_real_area_is_the_contour_refusal(self):
        prof = {"outer": {"shape": "poly",
                          "points_mm": [[0, 0], [10000, 0], [0, 6000],
                                        [10000, 6000], [5000, 12000]]}}
        out = compile_program(_prog([_bs(profile=prof)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T004", [d.code for d in out.diagnostics])


class BeamSystemDirectionEdge(unittest.TestCase):
    """Направление берётся с РЕБРА, и его единственное предусловие (ребро
    обязано быть прямым) проверяется НА КОМПИЛЯЦИИ, а не исключением изнутри
    транзакции."""

    def test_arc_edge_refuses_with_the_straight_edges_as_candidates(self):
        out = compile_program(_prog([_bs(profile=BS_ARC, direction_edge=1)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-E009"][0]
        self.assertEqual(d.candidates, [0, 2, 3])

    def test_index_outside_the_profile_refuses(self):
        out = compile_program(_prog([_bs(direction_edge=9)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E009", [d.code for d in out.diagnostics])

    def test_omitted_index_names_its_choice_in_the_receipt(self):
        """Умолчание НАЗВАНО: выбранный номер уезжает в квитанцию, иначе он
        неотличим от `.FirstOrDefault()` в костюме."""
        out = compile_program(_prog([_bs()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn('__rb["direction_edge"] = 0;', out.csharp)

    def test_first_straight_edge_is_taken_when_edge_zero_is_an_arc(self):
        prof = {"outer": {"shape": "poly",
                          "points_mm": [[0, 0], [9000, 0], [9000, 5000], [0, 5000]],
                          "arcs": [{"edge": 0, "bulge": 0.25}]}}
        out = compile_program(_prog([_bs(profile=prof)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn('__rb["direction_edge"] = 1;', out.csharp)
        self.assertIn("BeamSystem.Create(doc, __prof_BS1, __lv_BS1, 1, false)",
                      out.csharp)


class BeamSystemPlacementTrap(unittest.TestCase):
    """ИЗМЕРЕННАЯ ЛОВУШКА: точечное семейство каркаса. Пул `beam_types`
    фильтрует по FamilyPlacementType, но ветвь `by: element_id` пула НЕ
    КАСАЕТСЯ — ground.py пропускает сырой id насквозь. Значит вторую половину
    входов обязан закрыть эмиттер, и закрыть ТИПИЗИРОВАННЫМ отказом."""

    def test_emitter_guards_placement_type_before_assigning_beam_type(self):
        cs = compile_program(_prog([_bs(symbol={"by": "element_id", "value": 777})]),
                             snapshot=SNAPSHOT).csharp
        guard = cs[cs.index("var __pt_BS1 ="):cs.index("BeamSystem.Create")]
        self.assertIn("FamilyPlacementType.CurveDrivenStructural", guard)
        self.assertIn("FamilyPlacementType.CurveBased", guard)
        self.assertIn('return __Refuse("BS1"', guard)
        # Отказ стоит ДО назначения типа, а не после.
        self.assertLess(cs.index("var __pt_BS1 ="), cs.index("__el_BS1.BeamType ="))

    def test_pool_still_filters_the_catalogue_half(self):
        from kukai.ir.open_model import GROUND_SNAPSHOT_CS
        self.assertIn("FamilyPlacementType.CurveDrivenStructural",
                      GROUND_SNAPSHOT_CS)


class BeamSystemWitness(unittest.TestCase):
    """Свидетель читает РЕЗУЛЬТАТ. И ровно так же важно, чего он НЕ требует."""

    def setUp(self):
        self.cs = compile_program(_prog([_bs()]), snapshot=SNAPSHOT).csharp
        self.post = self.cs[self.cs.index("// post BS1"):
                            self.cs.index("// witness BS1")]

    def test_every_check_rereads_the_element_from_the_document(self):
        self.assertEqual(self.post.count("doc.GetElement(__el_BS1.Id)"), 4)

    def test_beams_are_witnessed_as_a_result_not_as_an_authored_count(self):
        self.assertIn("GetBeamIds().Count == 0", self.post)
        # НИ ОДНОГО числа балок: раскладку выбирает Revit.
        self.assertNotIn("GetBeamIds().Count ==", self.post.replace(
            "GetBeamIds().Count == 0", ""))

    def test_direction_and_elevation_are_reported_never_demanded(self):
        self.assertNotIn(".Direction", self.post)
        self.assertNotIn(".Elevation", self.post)
        witness = self.cs[self.cs.index("// witness BS1"):]
        self.assertIn('__rb["direction"]', witness)
        self.assertIn('__rb["elevation_mm"]', witness)
        self.assertIn('__rb["layout_rule"]', witness)
        self.assertIn('__rb["beam_count"]', witness)

    def test_profile_bbox_is_compared_by_vertices_on_both_sides(self):
        # 8000x6000 прямоугольник в нуле: обе стороны считаются по вершинам.
        self.assertIn("Math.Abs(__bx1_BS1 - 8000.0) > 50.0", self.post)
        self.assertIn("Math.Abs(__by1_BS1 - 6000.0) > 50.0", self.post)

    def test_profile_is_laid_on_the_level_plane_not_on_zero(self):
        create = self.cs[self.cs.index("// create_beam_system BS1"):
                         self.cs.index("// post BS1")]
        self.assertIn("double __z_BS1 = MM(__lv_BS1.Elevation);", create)
        self.assertIn("__z_BS1)", create.split("IList<Curve>")[1])


class TrussEmission(unittest.TestCase):
    def test_sketch_plane_is_the_level_and_the_curve_lies_in_it(self):
        cs = compile_program(_prog([_truss()]), snapshot=SNAPSHOT).csharp
        self.assertIn("SketchPlane __sp_TR1 = SketchPlane.Create(doc, __lv_TR1.Id);", cs)
        # `double __z_TR1` объявлен в decl (его читает свидетель), здесь —
        # присваивание: ровно то разделение, которого требует контракт
        # области видимости при per_op.
        self.assertIn("double __z_TR1 = 0;", cs)
        self.assertIn("__z_TR1 = MM(__lv_TR1.Elevation);", cs)
        self.assertIn("Line.CreateBound(P(0, 0, __z_TR1), P(12000, 0, __z_TR1))", cs)

    def test_create_is_wrapped_because_the_api_throws_on_the_revit_edition(self):
        """Autodesk объявляет у Truss.Create InvalidOperationException «эта
        функция доступна только в Revit Structure/Architecture». Вылететь
        наружу «внутренней ошибкой» это не имеет права."""
        cs = compile_program(_prog([_truss()]), snapshot=SNAPSHOT).csharp
        block = cs[cs.index("try { __el_TR1 = Autodesk.Revit.DB.Structure.Truss.Create"):]
        self.assertIn('catch (Exception __ex_TR1)', block)
        self.assertIn('"Truss.Create: " + __ex_TR1.Message', block)

    def test_degenerate_base_line_refuses_before_emission(self):
        out = compile_program(_prog([_truss(p1_mm=[0, 0])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_sole_pool_entry_resolves_the_omitted_type(self):
        out = compile_program(_prog([_truss()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        # 1600, а не 1500: волна нагрузок заняла 1500-1504 в тот же день, и
        # id-блок фермы уехал на следующую свободную сотню при слиянии.
        self.assertIn("new ElementId(1600)", out.csharp)

    def test_two_types_refuse_rather_than_pick_the_first(self):
        snap = dict(SNAPSHOT)
        snap["truss_types"] = [{"id": 1600, "name": "Ферма А"},
                               {"id": 1601, "name": "Ферма Б"}]
        out = compile_program(_prog([_truss()]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_no_doc_default_branch_exists_because_the_api_has_none(self):
        """ElementTypeGroup.TrussType не компилируется ни на одной из шести
        версий (CS0117), поэтому ветви «тип документа по умолчанию» у фермы
        быть не должно — ни в эмиссии, ни в ground."""
        cs = compile_program(_prog([_truss()]), snapshot=SNAPSHOT).csharp
        self.assertNotIn("ElementTypeGroup.TrussType", cs)

    def test_ungrounded_type_is_a_typed_refusal_not_a_keyerror(self):
        from kukai.ir import struct_emit
        from kukai.ir.diag import KirRefusal
        with self.assertRaises(KirRefusal) as ctx:
            struct_emit.emit_truss(
                {"op": "create_truss", "id": "TR1", "p0_mm": [0, 0],
                 "p1_mm": [9000, 0],
                 "level": {"__grounded__": {"via": "id", "id": 42}}},
                "2026", "kir:test")
        self.assertEqual(ctx.exception.diagnostics[0].code, "KIR-P005")


class TrussWitness(unittest.TestCase):
    def setUp(self):
        self.cs = compile_program(_prog([_truss()]), snapshot=SNAPSHOT).csharp
        self.post = self.cs[self.cs.index("// post TR1"):
                            self.cs.index("// witness TR1")]

    def test_plan_endpoints_are_gated(self):
        self.assertIn("endpoints mismatch (geometry)", self.post)
        self.assertIn("> 5.0", self.post)

    def test_elevation_is_compared_against_the_level_plane_at_runtime(self):
        self.assertIn("__tz_TR1.Curve.GetEndPoint(0).Z) - __z_TR1", self.post)
        self.assertIn("__tz_TR1.Curve.GetEndPoint(1).Z) - __z_TR1", self.post)

    def test_members_are_witnessed_as_a_result_not_as_a_shape(self):
        self.assertIn(".Members.Count == 0", self.post)
        # Ни поясов, ни раскосов, ни панелей: их задаёт семейство фермы.
        self.assertNotIn("Curves", self.post)

    def test_reference_level_is_checked_for_existence_not_equality(self):
        """ПРЯМОЙ УРОК create_beam (замер 27.07): требование равенства
        откатывало верно построенные балки, потому что привязку выводит
        Revit. У фермы уровня в вызове нет вовсе — значит требовать тем более
        нельзя, а прочитать в квитанцию нужно."""
        chunk = self.post[self.post.index("TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM"):]
        self.assertIn("ElementId.InvalidElementId", chunk)
        self.assertNotIn("ToString() !=", chunk)
        witness = self.cs[self.cs.index("// witness TR1"):]
        self.assertIn('__rb["reference_level"]', witness)


class FramingPBT(unittest.TestCase):
    N = 40
    SEED = 20260809

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            if rng.random() < 0.5:
                w = rng.randint(500, 40000)
                h = rng.randint(500, 40000)
                op = _bs(profile={"outer": {"shape": "rect",
                                            "origin": [rng.randint(-50000, 50000),
                                                       rng.randint(-50000, 50000)],
                                            "size_mm": [w, h]}})
            else:
                x0 = rng.randint(-50000, 50000)
                op = _truss(p0_mm=[x0, x0],
                            p1_mm=[x0 + rng.randint(1000, 30000), x0])
            out = compile_program(_prog([op], intent=rng.choice(NASTY_F)),
                                  snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


if __name__ == "__main__":
    unittest.main()
