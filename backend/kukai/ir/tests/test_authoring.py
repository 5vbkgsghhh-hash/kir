"""Authoring family gates (a)(d)(e): ground resolution, PBT over well-typed
programs, negative corpus, and the transaction/commit-gate invariants
(SPEC 12.5 — commit strictly after in-txn postcondition checks; rollback on
every guard; zero-trace on failure)."""
import hashlib
import os
import random
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import authoring, ground, spec  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.contracts import ElementIdentityProof  # noqa: E402
from kukai.ir.schema_gen import program_schema  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402


def _prog(ops, intent="test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _wall(oid="W1", **kw):
    op = {"op": "create_wall", "id": oid, "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(kw)
    return op


class Ground(unittest.TestCase):
    def test_name_resolution_pins_id(self):
        out = compile_program(_prog([_wall()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(42)", out.csharp)

    def test_internal_a5_stamp_scope_is_run_owned(self):
        scope = "a5:0123456789ab:0123456789abcdef"
        out = compile_program(
            _prog([_wall()]), snapshot=SNAPSHOT, stamp_scope=scope)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(f"kir:{scope}:", out.csharp)
        self.assertIn("A5 stamp parameter missing", out.csharp)
        self.assertIn("A5 stamp parameter is read-only", out.csharp)
        self.assertIn("A5 stamp readback mismatch", out.csharp)
        self.assertIn("A5 stamp write failed", out.csharp)

        legacy = compile_program(_prog([_wall()]), snapshot=SNAPSHOT)
        self.assertTrue(legacy.ok)
        self.assertNotIn("kir:a5:", legacy.csharp)
        self.assertNotIn("A5 stamp write failed", legacy.csharp)

    def test_internal_document_fingerprint_guard_precedes_first_write(self):
        fingerprint = {
            "title": 'Проект "A5"',
            "path_name": r"C:\\models\\copy.rvt",
            "project_uid": "uid-123",
        }
        out = compile_program(
            _prog([_wall()]), snapshot=SNAPSHOT,
            expected_document=fingerprint)

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("active document fingerprint changed", out.csharp)
        self.assertIn(r'Проект \"A5\"', out.csharp)
        self.assertLess(
            out.csharp.index("active document fingerprint changed"),
            out.csharp.index("Wall.Create"))
        # Public/default emission stays byte-compatible and unbound.
        legacy = compile_program(_prog([_wall()]), snapshot=SNAPSHOT)
        self.assertNotIn("active document fingerprint changed", legacy.csharp)

    def test_internal_element_identity_guard_is_in_transaction_and_versioned(
            self):
        proof = ElementIdentityProof(
            element_id=42,
            unique_id="level-42",
            version_guid="0" * 32,
        )
        out = compile_program(
            _prog([_wall()]),
            snapshot=SNAPSHOT,
            expected_identities=(proof,),
        )

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(authoring.MODEL_BINDING_GUARD_VERSION, out.csharp)
        self.assertIn("level-42", out.csharp)
        self.assertIn("VersionGuid.ToString(\"N\")", out.csharp)
        self.assertLess(
            out.csharp.index(authoring.MODEL_BINDING_GUARD_VERSION),
            out.csharp.index("Wall.Create"),
        )
        self.assertIn(
            "__t.RollBack(); return __Refuse(\"$program\", "
            "\"open model binding changed",
            out.csharp,
        )
        legacy = compile_program(_prog([_wall()]), snapshot=SNAPSHOT)
        self.assertNotIn(authoring.MODEL_BINDING_GUARD_VERSION, legacy.csharp)

    def test_model_binding_guard_bytes_require_version_bump(self):
        proof = ElementIdentityProof(
            element_id=42,
            unique_id="level-42",
            version_guid="0" * 32,
        )
        # Хешируются ФРАГМЕНТЫ СТРАЖА, а не вся программа. Раньше бралась
        # программа целиком, и любая правка общего футера — например, сбор
        # текста ошибки Revit для откатов 27.07 — требовала «поднять версию
        # провода», хотя сам страж не менялся. Такой бамп был бы ложью о
        # совместимости; проверка теперь пиннит ровно то, что заявляет, а
        # остальные байты закрыты голденами и байт-парити.
        expected_by_version = {
            "kir-model-binding-guard/1": {
                version: (
                    "a5c8f21331ffcb0e0b811e19a02882b9094aa68a721941749"
                    "f8e269ab56488a3"
                )
                for version in spec.REVIT_VERSIONS
            },
        }
        self.assertIn(
            authoring.MODEL_BINDING_GUARD_VERSION,
            expected_by_version,
            "generated guard changed: bump MODEL_BINDING_GUARD_VERSION",
        )
        expected = expected_by_version[
            authoring.MODEL_BINDING_GUARD_VERSION]
        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                guard = (
                    authoring._document_binding_guard(
                        {"title": "KIR guard COPY", "path_name": "",
                         "project_uid": "kir-guard-project"},
                        rollback="__t.RollBack(); ")
                    + authoring._element_identity_guard(
                        (proof,), version, rollback="__t.RollBack(); "))
                self.assertEqual(
                    hashlib.sha256(guard.encode("utf-8")).hexdigest(),
                    expected[version],
                    "generated guard changed without a wire version bump",
                )

    def test_not_found_offers_candidates(self):
        out = compile_program(_prog([_wall(level={"by": "name", "value": "Этаж 99"})]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G101"][0]
        self.assertIn("Этаж 1", d.candidates)

    def test_family_selector_requires_exact_category_family_and_type(self):
        snap = dict(SNAPSHOT)
        snap["family_symbols"] = [
            {"id": 800, "name": "Тип X", "category": "OST_Furniture",
             "family_name": "Семейство A", "type_name": "Тип X"},
            {"id": 801, "name": "Тип X", "category": "OST_GenericModel",
             "family_name": "Семейство B", "type_name": "Тип X"},
        ]
        op = {
            "op": "place_family", "id": "PF1", "xyz": [0, 0, 0],
            "level": {"by": "element_id", "value": 42},
            "symbol": {
                "by": "family_type", "category": "OST_GenericModel",
                "family_name": "Семейство B", "type_name": "Тип X",
            },
        }

        out = compile_program(_prog([op]), snapshot=snap)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("new ElementId(801)", out.csharp)
        wrong_case = dict(op)
        wrong_case["symbol"] = dict(op["symbol"], family_name="семейство B")
        refused = compile_program(_prog([wrong_case]), snapshot=snap)
        self.assertFalse(refused.ok)
        self.assertIn("KIR-G101", [item.code for item in refused.diagnostics])

    def test_ambiguous_default_refused_never_first(self):
        """Two wall types + by=default level? No — pipe default rule: two system
        types must AMBIG, never silently the first (the v0 disease)."""
        snap = dict(SNAPSHOT)
        snap["piping_system_types"] = [{"id": 300, "name": "ХВС"},
                                       {"id": 301, "name": "ГВС"}]
        out = compile_program(_prog([{
            "op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
            "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
        }]), snapshot=snap)
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertIn("KIR-G102", codes)
        # fix/g102-disambiguate: the default-branch AMBIGUOUS also surfaces
        # {id, name} candidates now, same as the by=name branch below —
        # omitted-param default resolution hits the identical several-
        # matches-never-first rule (_resolve_one's by=="default" tail).
        d = [x for x in out.diagnostics if x.code == "KIR-G102"][0]
        self.assertEqual(d.candidates,
                         [{"id": 300, "name": "ХВС"}, {"id": 301, "name": "ГВС"}])

    def _duct(self, oid="D1", **kw):
        # create_duct grounds `duct_type` against the duct_types pool — the
        # exact MEP-type-duplication case the fix targets ("несколько типов
        # воздуховодов называются «По умолчанию»", live-test finding).
        op = {"op": "create_duct", "id": oid,
              "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
              "level": {"by": "element_id", "value": 42}}
        op.update(kw)
        return op

    def test_ambiguous_by_name_offers_element_id_candidates(self):
        """fix/g102-disambiguate (2026-07-17): the live-test finding this
        closes — several types sharing one name (e.g. multiple duct/cable-
        tray types called "По умолчанию", routine in real MEP projects) used
        to refuse KIR-G102 with only NAMES as candidates, giving the caller
        no way to disambiguate short of already knowing an element_id. The
        ids were sitting in the snapshot pool the whole time; ground.py just
        discarded them when building the diagnostic. Now candidates carries
        {id, name} pairs, so the resolution pattern is: on AMBIGUOUS, pick
        one candidate's id and re-issue with {"by": "element_id", "value": id}
        instead of retrying the same ambiguous name."""
        snap = dict(SNAPSHOT)
        snap["duct_types"] = [{"id": 1000, "name": "По умолчанию"},
                              {"id": 1001, "name": "По умолчанию"},
                              {"id": 1002, "name": "Прямоугольный 300x200"}]
        out = compile_program(_prog([
            self._duct(duct_type={"by": "name", "value": "По умолчанию"})
        ]), snapshot=snap)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G102"][0]
        self.assertEqual(d.candidates,
                         [{"id": 1000, "name": "По умолчанию"},
                          {"id": 1001, "name": "По умолчанию"}])
        # exactly the two ambiguous entries, the unrelated third name absent
        self.assertEqual(len(d.candidates), 2)
        # each candidate is directly usable as a fresh element_id selector —
        # this is the resolution path the fix exists to enable.
        for c in d.candidates:
            retry = compile_program(_prog([
                self._duct(duct_type={"by": "element_id", "value": c["id"]})
            ]), snapshot=snap)
            self.assertTrue(retry.ok, [x.as_dict() for x in retry.diagnostics][:2])
            self.assertIn(f"new ElementId({c['id']})", retry.csharp)

    def test_multiple_case_insensitive_name_matches_are_ambiguous(self):
        snap = dict(SNAPSHOT)
        snap["wall_types"] = [
            {"id": 201, "name": "BASIC WALL"},
            {"id": 202, "name": "Basic Wall"},
        ]
        out = compile_program(
            _prog([_wall(type={"by": "name", "value": "basic wall"})]),
            snapshot=snap)

        self.assertFalse(out.ok)
        diag = next(item for item in out.diagnostics
                    if item.field_name == "type")
        self.assertEqual(diag.code, "KIR-G102")
        self.assertEqual(
            [row["id"] for row in diag.candidates], [201, 202])

    @staticmethod
    def _parameterized_duct_snapshot():
        snap = dict(SNAPSHOT)
        snap["duct_types"] = [
            {"id": 1000, "name": "По умолчанию",
             "params": {"Диаметр": 100, "Форма": "Круглая"}},
            {"id": 1001, "name": "По умолчанию",
             "params": {"Диаметр": 200, "Форма": "Прямоугольная"}},
            {"id": 1002, "name": "По умолчанию",
             "params": {"Диаметр": 200, "Форма": "Круглая"}},
        ]
        return snap

    def test_disambiguate_by_narrows_to_one_in_same_ground_round_trip(self):
        selector = {
            "by": "name",
            "value": "По умолчанию",
            "disambiguate_by": {"param": "Диаметр", "value": 100},
        }
        out = compile_program(
            _prog([self._duct(duct_type=selector)]),
            snapshot=self._parameterized_duct_snapshot())
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1000)", out.csharp)

    def test_disambiguate_by_narrows_to_zero_still_refuses_ambiguous(self):
        selector = {
            "by": "name",
            "value": "По умолчанию",
            "disambiguate_by": {"param": "Диаметр", "value": 999},
        }
        out = compile_program(
            _prog([self._duct(duct_type=selector)]),
            snapshot=self._parameterized_duct_snapshot())
        self.assertFalse(out.ok)
        diag = next(d for d in out.diagnostics if d.code == "KIR-G102")
        self.assertEqual(
            diag.candidates,
            [{"id": 1000, "name": "По умолчанию"},
             {"id": 1001, "name": "По умолчанию"},
             {"id": 1002, "name": "По умолчанию"}])

    def test_disambiguate_by_leaves_multiple_still_refuses_ambiguous(self):
        selector = {
            "by": "name",
            "value": "По умолчанию",
            "disambiguate_by": {"param": "Диаметр", "value": 200},
        }
        out = compile_program(
            _prog([self._duct(duct_type=selector)]),
            snapshot=self._parameterized_duct_snapshot())
        self.assertFalse(out.ok)
        diag = next(d for d in out.diagnostics if d.code == "KIR-G102")
        self.assertEqual(
            diag.candidates,
            [{"id": 1001, "name": "По умолчанию"},
             {"id": 1002, "name": "По умолчанию"}])

    def test_disambiguate_by_absent_preserves_existing_ambiguity(self):
        out = compile_program(
            _prog([self._duct(
                duct_type={"by": "name", "value": "По умолчанию"})]),
            snapshot=self._parameterized_duct_snapshot())
        self.assertFalse(out.ok)
        diag = next(d for d in out.diagnostics if d.code == "KIR-G102")
        self.assertEqual(
            diag.candidates,
            [{"id": 1000, "name": "По умолчанию"},
             {"id": 1001, "name": "По умолчанию"},
             {"id": 1002, "name": "По умолчанию"}])

    def test_explicit_wall_default_disambiguator_is_not_silently_ignored(self):
        snap = dict(SNAPSHOT)
        snap["wall_types"] = [
            {"id": 2000, "name": "Тип A",
             "params": {"Толщина": {"display": "100 мм"}}},
            {"id": 2001, "name": "Тип B",
             "params": {"Толщина": {"display": "200 мм"}}},
        ]
        out = compile_program(_prog([_wall(type={
            "by": "default",
            "disambiguate_by": {"param": "Толщина", "value": "200 мм"},
        })]), snapshot=snap)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(2001)", out.csharp)
        self.assertNotIn("GetDefaultElementTypeId", out.csharp)

    def test_unambiguous_by_name_unaffected_by_candidates_shape_change(self):
        """0-regressions guard: a name that resolves to exactly ONE pool entry
        must keep working exactly as before the fix — no AMBIGUOUS at all,
        regardless of how many OTHER differently-named entries share the
        pool (the fix only changes the SHAPE of candidates on an already-
        ambiguous refusal; it must never introduce new ambiguity)."""
        snap = dict(SNAPSHOT)
        snap["duct_types"] = [{"id": 1000, "name": "По умолчанию"},
                              {"id": 1001, "name": "По умолчанию"},
                              {"id": 1002, "name": "Прямоугольный 300x200"}]
        out = compile_program(_prog([
            self._duct(duct_type={"by": "name", "value": "Прямоугольный 300x200"})
        ]), snapshot=snap)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("new ElementId(1002)", out.csharp)

    def test_unambiguous_name_still_must_satisfy_disambiguate_by(self):
        snap = dict(SNAPSHOT)
        snap["duct_types"] = [{
            "id": 1002,
            "name": "Прямоугольный 300x200",
            "params": {"Диаметр": 200},
        }]
        out = compile_program(_prog([
            self._duct(duct_type={
                "by": "name",
                "value": "Прямоугольный 300x200",
                "disambiguate_by": {"param": "Диаметр", "value": 100},
            })
        ]), snapshot=snap)
        self.assertFalse(out.ok)
        diag = next(d for d in out.diagnostics if d.code == "KIR-G102")
        self.assertEqual(diag.candidates, [{
            "id": 1002, "name": "Прямоугольный 300x200",
        }])

    def test_no_snapshot_is_typed_refusal(self):
        out = compile_program(_prog([_wall()]), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_all_failures_reported_at_once(self):
        out = compile_program(_prog([
            _wall(level={"by": "name", "value": "Нет такого"}),
            _wall(oid="W2", type={"by": "name", "value": "Тоже нет"}),
        ]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertGreaterEqual(len(out.diagnostics), 2)

    def test_malformed_bridge_snapshot_is_typed_not_compiler_panic(self):
        malformed = [
            {"levels": ["not-a-row"]},
            {"levels": [{"id": "42", "name": "Этаж 1"}]},
            {"levels": [{"id": 1 << 63, "name": "Этаж 1"}]},
            {"levels": [{"id": 42, "name": 123}]},
            {"levels": "not-a-pool"},
        ]
        for snapshot in malformed:
            with self.subTest(snapshot=snapshot):
                out = compile_program(_prog([_wall()]), snapshot=snapshot)
                self.assertFalse(out.ok)
                codes = [d.code for d in out.diagnostics]
                self.assertIn("KIR-G106", codes)
                self.assertNotIn("KIR-P000", codes)

    def test_duplicate_snapshot_ids_are_rejected(self):
        snapshot = {"levels": [
            {"id": 42, "name": "Этаж 1"},
            {"id": 42, "name": "Этаж другой"},
        ]}
        out = compile_program(_prog([_wall()]), snapshot=snapshot)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G106", [d.code for d in out.diagnostics])


class CommitGateInvariants(unittest.TestCase):
    """Gate (e) for authoring: the emitted C# must structurally guarantee
    12.5 — these are textual-order proofs over generated code."""

    def _cs(self):
        out = compile_program(_prog([
            _wall(),
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
            {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
             "p1_mm": [0, 9000], "name": "А"},
        ], intent="стена+труба+ось"), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_single_transaction(self):
        self.assertEqual(self._cs().count("new Transaction"), 1)

    def test_commit_strictly_after_regenerate_and_checks(self):
        cs = self._cs()
        i_regen = cs.index("doc.Regenerate()")
        i_check = cs.index("__post.Count > 0")
        i_commit = cs.index("__t.Commit()")
        self.assertLess(i_regen, i_check)
        self.assertLess(i_check, i_commit)
        self.assertEqual(cs.count("__t.Commit()"), 1)

    def test_transaction_statuses_are_not_ignored(self):
        cs = self._cs()
        self.assertIn("var __startStatus = __t.Start()", cs)
        self.assertIn("__startStatus != TransactionStatus.Started", cs)
        self.assertIn("var __commitStatus = __t.Commit()", cs)
        self.assertIn("__commitStatus != TransactionStatus.Committed", cs)
        self.assertLess(cs.index("__commitStatus != TransactionStatus.Committed"),
                        cs.index('__results["ok"] = true'))

    def test_stairs_checks_inner_transaction_statuses(self):
        out = compile_program(_prog([{
            "op": "create_stairs", "id": "S1",
            "p0_mm": [0, 0], "p1_mm": [5000, 0],
            "base_level": {"by": "element_id", "value": 42},
            "top_level": {"by": "element_id", "value": 43},
            "width_mm": 1200,
        }]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("__startStatus != TransactionStatus.Started", out.csharp)
        self.assertIn("__commitStatus != TransactionStatus.Committed", out.csharp)
        self.assertIn("__ess.Cancel()", out.csharp)
        self.assertIn("stairs run width mismatch (geometry)", out.csharp)
        self.assertIn("stairs run width unreadable (geometry)", out.csharp)

    def test_rollback_on_catch_present(self):
        cs = self._cs()
        self.assertIn("catch", cs)
        self.assertIn("if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();", cs)
        self.assertIn("throw;", cs)

    def test_every_op_stamped_and_witnessed(self):
        cs = self._cs()
        for oid in ("W1", "P1", "G1"):
            self.assertIn(f":{oid}", cs)                      # stamp suffix
            self.assertIn(f'__results["{oid}"]', cs)          # witness readback
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
        self.assertIn('__rb["stamp"] = __stampParam.AsString()', cs)
        self.assertNotIn('__rb["stamp"] = "kir:', cs)

    def test_topology_checks_day_one(self):
        cs = self._cs()
        self.assertIn("WALL_BASE_CONSTRAINT", cs)
        self.assertIn("RBS_START_LEVEL_PARAM", cs)
        self.assertIn("topology", cs)

    def test_endpoint_witness_is_direction_independent(self):
        cs = self._cs()
        self.assertIn("double __da =", cs)
        self.assertIn("double __db =", cs)
        self.assertIn("var __e0 = __da <= __db ? __a : __b", cs)

    def test_grid_witness_accepts_reversed_curve_endpoints(self):
        cs = self._cs()
        grid_post = cs[cs.index("// post G1"):cs.index("// witness W1")]
        self.assertIn("var __e0 = __da <= __db ? __a : __b", grid_post)
        self.assertIn("MM(__e1.Y) - 9000", grid_post)
        grid_witness = cs[cs.index("// witness G1"):]
        self.assertIn("var __gc2 = __el_G1.Curve", grid_witness)
        self.assertIn('__rb["start_mm"]', grid_witness)

    def test_column_category_is_witnessed_semantically(self):
        out = compile_program(_prog([{
            "op": "create_column", "id": "C1", "xy": [1000, 2000],
            "level": {"by": "element_id", "value": 42},
            "category": "architectural",
        }]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("__el_C1.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.NonStructural",
                      out.csharp)

    def test_rotated_column_normalizes_grounds_and_emits_checked_rotation(self):
        raw = {
            "op": "create_column", "id": "C_ROT",
            "xy": [1_000, 2_000],
            "level": {"by": "element_id", "value": 42},
            "category": "structural",
            "rotation_deg": 37.5,
        }
        diagnostics = []
        normalized = authoring.validate(
            raw, "create_column", 0, "C_ROT", diagnostics)
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rotation_deg"], 37.5)
        grounded = ground.ground([normalized], SNAPSHOT)

        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                cs = authoring.emit_program(grounded, version)
                self.assertIn(
                    "Line.CreateUnbound(P(1000, 2000, 0), XYZ.BasisZ)", cs)
                self.assertIn("ElementTransformUtils.RotateElement", cs)
                self.assertIn("37.5 * Math.PI / 180.0", cs)
                self.assertIn("Math.Atan2(", cs)
                self.assertIn("Math.PI / 1800.0", cs)
                self.assertIn('__rb["rotation_deg"]', cs)
                self.assertLess(
                    cs.index("NewFamilyInstance"),
                    cs.index("ElementTransformUtils.RotateElement"),
                )

    def test_column_rotation_default_is_implicit_and_bad_angles_refuse(self):
        rotation_spec = next(
            param for param in spec.OPS["create_column"].params
            if param.name == "rotation_deg")
        self.assertEqual(rotation_spec.kind, "deg")
        self.assertFalse(rotation_spec.required)
        self.assertEqual(rotation_spec.default, 0.0)
        column_schema = next(
            item
            for item in program_schema()["properties"]["ops"]["items"]["oneOf"]
            if item.get("properties", {}).get("op", {}).get("const")
            == "create_column"
        )
        self.assertEqual(
            column_schema["properties"]["rotation_deg"],
            {"type": "number", "default": 0.0},
        )

        without_rotation = compile_program(_prog([{
            "op": "create_column", "id": "C1", "xy": [1_000, 2_000],
            "level": {"by": "element_id", "value": 42},
        }]), snapshot=SNAPSHOT)
        self.assertTrue(without_rotation.ok)
        self.assertNotIn(
            "ElementTransformUtils.RotateElement", without_rotation.csharp)

        for bad in (True, float("nan"), float("inf"), "90"):
            with self.subTest(rotation_deg=bad):
                out = compile_program(_prog([{
                    "op": "create_column", "id": "C1",
                    "xy": [1_000, 2_000],
                    "level": {"by": "element_id", "value": 42},
                    "rotation_deg": bad,
                }]), snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn(
                    "KIR-T001", [item.code for item in out.diagnostics])

    def test_place_family_state_order_postchecks_and_schema(self):
        # XOR-консистентная комбинация (M = H XOR F), при которой v2-эмиттер
        # держит ВСЕ блоки: mirror (facing=T), flipHand, flipFacing.
        raw = {
            "op": "place_family", "id": "PF_ROT",
            "xyz": [1_000, 2_000, 3_000],
            "level": {"by": "element_id", "value": 42},
            "symbol": {
                "by": "family_type",
                "category": "OST_Furniture",
                "family_name": "Стол офисный",
                "type_name": "Стол 1200",
            },
            "rotation_deg": 37.5,
            "mirrored": False,
            "hand_flipped": True,
            "facing_flipped": True,
        }
        diagnostics = []
        normalized = authoring.validate(
            raw, "place_family", 0, "PF_ROT", diagnostics)
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rotation_deg"], 37.5)
        self.assertFalse(normalized["mirrored"])
        grounded = ground.ground([normalized], SNAPSHOT)

        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                cs = authoring.emit_program(grounded, version)
                ordered = [
                    "NewFamilyInstance", "RotateElement", "MirrorElements",
                    ".flipHand()", ".flipFacing()",
                ]
                positions = [cs.index(item) for item in ordered]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("Plane.CreateByNormalAndOrigin", cs)
                self.assertIn("false);", cs)  # mirrorCopies=false, in-place
                self.assertIn("CanFlipHand", cs)
                self.assertIn("CanFlipFacing", cs)
                self.assertIn("rotation mismatch", cs)
                self.assertIn("mirrored state mismatch", cs)
                self.assertIn("hand flip state mismatch", cs)
                self.assertIn("facing flip state mismatch", cs)
                self.assertIn('__rb["rotation_deg"]', cs)
                self.assertIn('__rb["mirrored"]', cs)

        place_spec = spec.OPS["place_family"]
        defaults = {param.name: param.default for param in place_spec.params}
        self.assertEqual(defaults["rotation_deg"], 0.0)
        self.assertIs(defaults["mirrored"], False)
        self.assertIs(defaults["hand_flipped"], False)
        self.assertIs(defaults["facing_flipped"], False)
        place_schema = next(
            item
            for item in program_schema()["properties"]["ops"]["items"]["oneOf"]
            if item.get("properties", {}).get("op", {}).get("const")
            == "place_family"
        )
        family_variants = place_schema["properties"]["symbol"]["oneOf"]
        self.assertTrue(any(
            variant.get("properties", {}).get("by", {}).get("const")
            == "family_type"
            for variant in family_variants
        ))

    def test_mirrored_state_must_equal_flip_xor(self):
        raw = {
            "op": "place_family", "id": "PF_BAD",
            "xyz": [1_000, 2_000, 3_000],
            "level": {"by": "element_id", "value": 42},
            "mirrored": True,
            "hand_flipped": False,
            "facing_flipped": False,
        }
        diagnostics = []
        authoring.validate(raw, "place_family", 0, "PF_BAD", diagnostics)
        self.assertEqual(
            [(item.code, item.field_name) for item in diagnostics],
            [("KIR-T002", "mirrored")],
        )

    def test_floor_structural_and_hosted_xyz_are_witnessed(self):
        out = compile_program(_prog([
            _wall(),
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "level": {"by": "element_id", "value": 42}, "structural": True},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"},
             "offset_mm": 2000, "sill_mm": 900},
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("FLOOR_PARAM_IS_STRUCTURAL", out.csharp)
        self.assertIn("structural flag mismatch (semantic)", out.csharp)
        self.assertIn("no LocationPoint (geometry)", out.csharp)
        self.assertIn("location/sill mismatch (geometry)", out.csharp)
        self.assertIn("__hl_Win1.Elevation + U(900.0)", out.csharp)

    def test_floor_empty_holes_list_accepted_as_no_holes(self):
        # Regression (live «демо» rebuild dry-run 2026-07-21): the A3
        # materializer emits holes=[] for hole-free floors; an empty list means
        # "no holes" (identical to omitting it) and must compile, not be refused
        # KIR-T001 «список контуров (каждый 3..32 точек)».
        out = compile_program(_prog([
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "level": {"by": "element_id", "value": 42}, "holes": []},
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertNotIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_floor_falsey_non_list_holes_are_refused(self):
        for invalid in (False, 0, "", {}):
            with self.subTest(invalid=invalid):
                out = compile_program(_prog([
                    {"op": "create_floor", "id": "F1",
                     "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                     "level": {"by": "element_id", "value": 42},
                     "holes": invalid},
                ]), snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_stale_guards_rollback(self):
        cs = self._cs()
        self.assertGreaterEqual(cs.count("__t.RollBack(); return __Refuse("), 4)

    def test_deterministic_emit(self):
        p = _prog([_wall()], intent="determinism")
        a = compile_program(p, snapshot=SNAPSHOT).csharp
        b = compile_program(p, snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)


# ── Curve-IR (P4-B): create_wall learns the arc ─────────────────────────────
import math as _math  # noqa: E402


def _quarter_arc(radius=325.0):
    """A 90° fillet Arc dict (canonical shape) with its matching endpoints."""
    arc = {"curve_type": "Arc", "center_mm": [0.0, 0.0, 0.0],
           "radius_mm": radius, "x_axis": [1.0, 0.0, 0.0],
           "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.0,
           "end_angle_rad": _math.pi / 2.0}
    return arc, [radius, 0.0], [0.0, radius]


class PlaceFamilyLevelRelativeZ(unittest.TestCase):
    """Пин Z-фикса 2026-07-21 (замена байт-паритета для full_house-корпуса).

    Живое доказательство: NewFamilyInstance(point, symbol, level) трактует z
    точки как офсет НАД уровнем — абсолютный z в точке давал double-count
    (exp 71100 → act 142200 на этаже 20 демо-модели).  Контракт: точка
    создания получает z−Elevation, а свидетель и ось поворота остаются в
    АБСОЛЮТНЫХ координатах (честная сверка итогового LocationPoint)."""

    def _emit(self):
        raw = {"op": "place_family", "id": "PF_Z", "xyz": [1000, 2000, 3000],
               "level": {"by": "element_id", "value": 42},
               "symbol": {"by": "family_type", "category": "OST_Furniture",
                          "family_name": "Стол офисный",
                          "type_name": "Стол 1200"},
               "rotation_deg": 37.5}
        diagnostics = []
        normalized = authoring.validate(
            raw, "place_family", 0, "PF_Z", diagnostics)
        self.assertEqual(diagnostics, [])
        return authoring.emit_program(ground.ground([normalized], SNAPSHOT),
                                      "2026")

    def test_creation_point_is_level_relative(self):
        cs = self._emit()
        self.assertIn(
            "XYZ __pfp_PF_Z = new XYZ(U(1000), U(2000), "
            "U(3000) - __lv_PF_Z.Elevation);", cs)
        self.assertIn(
            "NewFamilyInstance(__pfp_PF_Z, __sy_PF_Z, __lv_PF_Z", cs)
        self.assertNotIn("NewFamilyInstance(P(1000, 2000, 3000)", cs)

    def test_witness_and_rotation_axis_stay_absolute(self):
        cs = self._emit()
        self.assertIn("Math.Abs(MM(__loc.Point.Z) - 3000)", cs)
        self.assertIn(
            "Line.CreateUnbound(P(1000, 2000, 3000), XYZ.BasisZ)", cs)


class ExoticFlipStates(unittest.TestCase):
    """XOR-модель флипов place_family (живые пробы 2026-07-21, демо).

    Mirrored у Revit ПРОИЗВОДЕН (= Hand XOR Facing).  Наблюдения:

    * plane (-sinθ,cosθ) + rotate(θ):  (M=T, H=F, F=T), свидетель прошёл —
      единственное проверенное действие для facing=T (работает и при
      CanFlipFacing=false).
    * ортогональная plane (cosθ,sinθ):  Mirrored читается F (канонизация в
      поворот+facing-флип) — «выбор плоскости по чётности» опровергнут.
    * flipHand сдвигает чтение __loc.Rotation на 180° (GT_C) → при hand=T
      действие поворота пре-компенсируется (+180), свидетель остаётся на
      лифтованном rotation_deg; для (M=T,H=T,F=F) зеркала НЕТ вовсе
      (у двери ДГ 900x2100 этот рецепт живьём дал точное состояние, P6)."""

    def _emit(self, hand, facing, rot=180.0):
        raw = {"op": "place_family", "id": "PF_M", "xyz": [1000, 2000, 0],
               "level": {"by": "element_id", "value": 42},
               "symbol": {"by": "family_type", "category": "OST_Furniture",
                          "family_name": "Стол офисный",
                          "type_name": "Стол 1200"},
               "rotation_deg": rot, "mirrored": hand != facing,
               "hand_flipped": hand, "facing_flipped": facing}
        diagnostics = []
        normalized = authoring.validate(
            raw, "place_family", 0, "PF_M", diagnostics)
        self.assertEqual(diagnostics, [])
        return authoring.emit_program(ground.ground([normalized], SNAPSHOT),
                                      "2026")

    def test_hand_only_state_uses_flip_not_mirror(self):
        cs = self._emit(hand=True, facing=False, rot=180.0)
        self.assertNotIn("MirrorElements", cs)
        self.assertIn("flipHand", cs)
        # пре-компенсация: θ=180, hand=T → действие 0 → строки поворота нет,
        # свидетель сверяет лифтованные 180.
        self.assertNotIn("RotateElement", cs)
        self.assertIn("mirrored state mismatch (semantic)", cs)

    def test_hand_precompensation_rotates_theta_plus_180(self):
        cs = self._emit(hand=True, facing=False, rot=90.0)
        self.assertIn("__axis_PF_M, 270.0 * Math.PI / 180.0", cs)
        # свидетель остаётся на лифтованном значении
        self.assertIn("__wantRot_PF_M = 90.0 * Math.PI / 180.0", cs)

    def test_facing_state_keeps_proven_mirror_plane(self):
        cs = self._emit(hand=False, facing=True, rot=180.0)
        self.assertIn("new XYZ(-Math.Sin(__mirrorAngle_PF_M), "
                      "Math.Cos(__mirrorAngle_PF_M), 0)", cs)
        self.assertIn("__axis_PF_M, 180.0 * Math.PI / 180.0", cs)

    def test_mirror_guard_is_facing_state_not_mirrored(self):
        # (F,T,T)×11 живьём: гард по Mirrored для цели M=F не срабатывал
        # (свежий инстанс уже M=F) → зеркало пропускалось → flipFacing
        # упирался в CanFlipFacing=false.  Гард — по наблюдаемому эффекту.
        for hand in (False, True):
            with self.subTest(hand=hand):
                cs = self._emit(hand=hand, facing=True, rot=90.0)
                # action-гард зеркала — по FacingFlipped, не по Mirrored
                idx = cs.index("MirrorElements")
                pre = cs[:idx]
                self.assertIn("if (__el_PF_M.FacingFlipped != true)", pre)
                self.assertNotIn("if (__el_PF_M.Mirrored != false)\n{", pre)
        # чётная пара (T,T): зеркало + flipHand с пре-ротацией 270
        cs = self._emit(hand=True, facing=True, rot=90.0)
        self.assertIn("__axis_PF_M, 270.0 * Math.PI / 180.0", cs)
        self.assertIn("MirrorElements", cs)


class ArcWall(unittest.TestCase):
    def _arc_wall(self, arc, p0, p1, oid="WA"):
        return {"op": "create_wall", "id": oid, "p0_mm": p0, "p1_mm": p1,
                "level": {"by": "name", "value": "Этаж 1"}, "arc": arc}

    def test_straight_wall_is_byte_stable_without_arc(self):
        # The pre-existing straight-wall emission must not move at all.
        out = compile_program(_prog([_wall()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("Line.CreateBound(P(", out.csharp)
        self.assertNotIn("Arc.Create(", out.csharp)

    def test_arc_wall_emits_arc_create(self):
        arc, p0, p1 = _quarter_arc()
        out = compile_program(
            _prog([self._arc_wall(arc, p0, p1)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        seg = out.csharp[out.csharp.index("create_wall WA"):]
        # Якорь СМЫСЛОВОЙ, а не позиционный: кривая — АРГУМЕНТ Wall.Create,
        # поэтому смотрим ровно в этот вызов, от имени до его точки с запятой.
        # Было `seg[:600]`, и проверка умерла от того, что выше добавилось
        # несколько строк резолва уровня (31.07). Тот же класс, что задача
        # #64: проверка, привязанная к смещению в тексте, слепнет от правки
        # соседнего кода.
        create_stmt = seg[seg.index("Wall.Create"):]
        create_stmt = create_stmt[:create_stmt.index(";") + 1]
        self.assertIn("Arc.Create(P(", create_stmt)
        self.assertNotIn(
            "Line.CreateBound(P(", seg[:seg.index("Wall.Create") + 200])

    def test_arc_wall_has_arc_postcondition(self):
        arc, p0, p1 = _quarter_arc()
        cs = compile_program(
            _prog([self._arc_wall(arc, p0, p1)]), snapshot=SNAPSHOT).csharp
        self.assertIn("arc requested but wall is not an Arc", cs)
        self.assertIn("arc center/radius mismatch", cs)

    def test_arc_endpoints_must_match_p0_p1(self):
        arc, _p0, p1 = _quarter_arc()
        out = compile_program(
            _prog([self._arc_wall(arc, [9999.0, 0.0], p1)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any(d.field_name == "arc" for d in out.diagnostics))

    def test_arc_endpoints_agree_ignoring_capture_z(self):
        # p0_mm/p1_mm are 2D (pt_xy); a real captured arc carries its absolute
        # elevation z. Endpoint agreement is a PLAN-plane check, so a faithful
        # LOT31-style arc at z=15000 must still be accepted (regression: the
        # 3D _dist compared the arc's z against a 2D endpoint's implicit 0).
        arc = {"curve_type": "Arc", "center_mm": [25600.0, 37550.0, 15000.0],
               "radius_mm": 325.0, "x_axis": [1.0, 0.0, 0.0],
               "y_axis": [0.0, -1.0, 0.0], "start_angle_rad": _math.pi,
               "end_angle_rad": 3.0 * _math.pi / 2.0}
        out = compile_program(
            _prog([self._arc_wall(arc, [25275.0, 37550.0], [25600.0, 37875.0])]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("Arc.Create(P(", out.csharp)

    def test_invalid_arc_is_refused(self):
        arc, p0, p1 = _quarter_arc()
        arc["radius_mm"] = 0.0
        out = compile_program(
            _prog([self._arc_wall(arc, p0, p1)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_arc_wall_deterministic_emit(self):
        arc, p0, p1 = _quarter_arc()
        p = _prog([self._arc_wall(arc, p0, p1)], intent="arc-determinism")
        a = compile_program(p, snapshot=SNAPSHOT).csharp
        b = compile_program(p, snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)

    def test_arc_wall_per_version_emit(self):
        # The arc branch must emit on every supported Revit version, not just
        # 2026 (Arc.Create/Wall.Create are stable 2021-2026).
        arc, p0, p1 = _quarter_arc()
        p = _prog([self._arc_wall(arc, p0, p1)])
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(p, revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(
                    out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertIn("Arc.Create(P(", out.csharp)

    def test_arc_schema_is_optional_on_create_wall(self):
        from kukai.ir.schema_gen import program_schema
        text = repr(program_schema())
        # the arc property exists in the schema but is never required
        self.assertIn("start_angle_rad", text)


class VersionAxis(unittest.TestCase):
    def test_int64_id_diverges_per_version(self):
        big = {"id": 5_000_000_000, "name": "Этаж 1"}
        snap = dict(SNAPSHOT)
        snap["levels"] = [big]
        p = _prog([_wall(level={"by": "name", "value": "Этаж 1"})])
        out26 = compile_program(p, revit_version="2026", snapshot=snap)
        self.assertTrue(out26.ok)
        self.assertIn("new ElementId(5000000000L)", out26.csharp)
        out21 = compile_program(p, revit_version="2021", snapshot=snap)
        self.assertFalse(out21.ok)
        self.assertIn("KIR-E002", [d.code for d in out21.diagnostics])


class NegativeAuthoring(unittest.TestCase):
    CASES = [
        (_prog([_wall(p1_mm=[0, 0])]), "KIR-T002"),                    # degenerate
        (_prog([_wall(height_mm=0)]), "KIR-T002"),
        (_prog([_wall(height_mm=10**9)]), "KIR-T002"),
        (_prog([_wall(level="Этаж 1")]), "KIR-T001"),                  # bare string, not a selector
        (_prog([{"op": "create_pipe", "id": "P", "p0_mm": [0, 0],      # pipe needs 3D pts
                 "p1_mm": [1000, 0], "level": {"by": "element_id", "value": 42}}]), "KIR-T001"),
        (_prog([{"op": "create_grid", "id": "G", "p0_mm": [0, 0],
                 "p1_mm": [0, 5000], "name": ""}]), "KIR-T001"),
        (_prog([_wall(), {"op": "query_count", "kind": "wall", "id": "q"}]), "KIR-L002"),  # mixed
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


NASTY = ["Стена \"Т-1\"", "тип\\обратный", "100%", "…", "'кавычки'", "мм"]


class AuthoringPBT(unittest.TestCase):
    N = 150
    SEED = 20260716

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            ops = []
            for j in range(rng.randint(1, 6)):
                kind = rng.choice(["wall", "pipe", "grid"])
                oid = f"op{j}"
                x0, y0 = rng.randint(-10**5, 10**5), rng.randint(-10**5, 10**5)
                x1, y1 = x0 + rng.randint(100, 20000), y0 + rng.randint(100, 20000)
                if kind == "wall":
                    ops.append({"op": "create_wall", "id": oid,
                                "p0_mm": [x0, y0], "p1_mm": [x1, y1],
                                "level": rng.choice([
                                    {"by": "name", "value": "Этаж 1"},
                                    {"by": "element_id", "value": 43}]),
                                "height_mm": rng.randint(100, 10000),
                                **({"type": {"by": "name", "value": "ЖБ 200"}}
                                   if rng.random() < 0.5 else {})})
                elif kind == "pipe":
                    ops.append({"op": "create_pipe", "id": oid,
                                "p0_mm": [x0, y0, rng.randint(0, 3000)],
                                "p1_mm": [x1, y1, rng.randint(0, 3000)],
                                "level": {"by": "element_id", "value": 42},
                                **({"diameter_mm": rng.randint(10, 300)}
                                   if rng.random() < 0.5 else {})})
                else:
                    ops.append({"op": "create_grid", "id": oid,
                                "p0_mm": [x0, y0], "p1_mm": [x1, y1],
                                **({"name": rng.choice(NASTY)}
                                   if rng.random() < 0.5 else {})})
            out = compile_program(_prog(ops, intent=rng.choice(NASTY)),
                                  snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                code_only = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cs)
                code_only = re.sub(r'//[^\n]*', '', code_only)
                self.assertNotIn("doc.Delete", code_only)
                self.assertNotIn("IntegerValue", cs)
                # Success-return is the body's final action; the trailing nested
                # __KirMainFailures/__KirPad classes are wrapper-pad scaffolding.
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


class QueryTypes(unittest.TestCase):
    """fix/g102-disambiguate (2026-07-17): query_types — the G102-AMBIGUOUS
    enumeration companion. "What types/families of X exist" as a standalone
    read, independent of any by=name selector attempt — the caller can ask
    up front (before an AMBIGUOUS refusal) or after one (the refusal's own
    candidates already carry {id, name} now, ground.py fix same commit)."""

    def test_emits_correct_collector_per_pool(self):
        out = compile_program({"ir_version": "1.0", "intent": "типы воздуховодов",
                               "ops": [{"op": "query_types", "id": "q1",
                                        "pool": "duct_types"}]})
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        cs = out.csharp
        self.assertIn("Autodesk.Revit.DB.Mechanical.DuctType", cs)
        self.assertIn('__row["id"] = __e.Id.ToString();', cs)
        self.assertIn('__row["name"] = __NameOf(__e);', cs)
        self.assertIn('__r["pool"] = "duct_types";', cs)

    def test_no_snapshot_required(self):
        """query family invariant (compiler.py's own docstring: 'No ground
        round-trip'): query_types must compile WITHOUT a snapshot, exactly
        like query_count/list/inspect — it reads the live document via its
        own FilteredElementCollector at execute time, not a pre-fetched
        census. Passing snapshot=None (the default) must still succeed."""
        out = compile_program({"ir_version": "1.0",
                               "ops": [{"op": "query_types", "id": "q1",
                                        "pool": "wall_types"}]}, snapshot=None)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_category_symbol_pools_use_family_symbol_plus_category(self):
        out = compile_program({"ir_version": "1.0",
                               "ops": [{"op": "query_types", "id": "q1",
                                        "pool": "column_symbols_structural"}]})
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("OfClass(typeof(FamilySymbol))", out.csharp)
        self.assertIn("OST_StructuralColumns", out.csharp)

    def test_universal_family_pool_exposes_canonical_identity(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_types", "id": "q1", "pool": "family_symbols"}
        ]})
        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("OfClass(typeof(FamilySymbol))", out.csharp)
        self.assertNotIn("OST_Furniture", out.csharp)
        self.assertIn('__row["category"]', out.csharp)
        self.assertIn('__row["family_name"]', out.csharp)
        self.assertIn('__row["type_name"]', out.csharp)

    def test_family_pool_says_whether_a_symbol_holds_a_point(self):
        """Каталог обязан отдавать `FamilyPlacementType`.

        Замер живьём 04.08 («Проект1», 320 типоразмеров): 279 ViewBased,
        20 OneLevelBased, 16 OneLevelBasedHosted, 4 TwoLevelsBased. Без
        этого поля выбрать типоразмер под `place_family` НЕЛЬЗЯ: ни имя, ни
        категория не отвечают на вопрос «держит ли он точку». Живая проба
        (транзакция откачена) в одной точке (200000,290000,0):

            407  «50 x 150 мм»          -> LocationPoint (0,0,0) — точка
                                          ПРОИГНОРИРОВАНА (MullionType)
            5290 «С остеклением»        -> LocationPoint == null
            4275 «Строительный прицеп»  -> ровно запрошенная точка
            132630 «Опора»              -> ровно запрошенная точка

        Матрица 04.08 взяла №0 = 407 и получила честный
        `KIR-X004: PF: location mismatch (geometry)`."""
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_types", "id": "q1", "pool": "family_symbols"}
        ]})
        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn('__row["placement"]', out.csharp)
        self.assertIn("FamilyPlacementType", out.csharp)
        self.assertNotIn("IntegerValue", out.csharp)

    def test_unknown_pool_is_typed_refusal_not_panic(self):
        out = compile_program({"ir_version": "1.0",
                               "ops": [{"op": "query_types", "id": "q1",
                                        "pool": "not_a_pool"}]})
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertNotIn("KIR-P000", codes, "panic is forbidden")
        self.assertIn("KIR-T003", codes)
        d = [x for x in out.diagnostics if x.code == "KIR-T003"][0]
        self.assertIn("wall_types", d.expected)   # closed enum surfaced

    def test_missing_pool_is_typed_refusal(self):
        out = compile_program({"ir_version": "1.0",
                               "ops": [{"op": "query_types", "id": "q1"}]})
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_mixed_with_write_family_refused(self):
        """Query family stays exclusive (compiler.py's plan-stage rule,
        KIR-L002) — query_types is a query op like query_count/list/inspect,
        so it must trip the same mixed-family refusal as they already do."""
        out = compile_program(_prog([
            _wall(), {"op": "query_types", "id": "q1", "pool": "wall_types"}
        ]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_all_sixteen_pools_compile_offline(self):
        """Every pool in the closed enum must actually emit — a stale/typo'd
        entry in the choices tuple vs. _TYPE_POOL_COLLECTOR_CS would KeyError
        at emit time (an internal bug, not a refusal); this proves the two
        tables stay in lockstep (16 pools — the type subset serving.py's
        _SNAPSHOT_CS collects live, see ops_authoring.py's OpSpec comment)."""
        pools = spec.OPS["query_types"].params[0].choices
        self.assertEqual(len(pools), 16)
        for pool in pools:
            with self.subTest(pool=pool):
                out = compile_program({"ir_version": "1.0",
                                       "ops": [{"op": "query_types", "id": "q1",
                                                "pool": pool}]})
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertIn(f'__r["pool"] = "{pool}"', out.csharp)

    def test_structural_type_pools_use_domain_categories(self):
        expected = {"beam_types": "OST_StructuralFraming",
                    "foundation_symbols": "OST_StructuralFoundation"}
        for pool, category in expected.items():
            with self.subTest(pool=pool):
                out = compile_program({"ir_version": "1.0", "ops": [
                    {"op": "query_types", "id": "q1", "pool": pool}]})
                self.assertTrue(out.ok)
                self.assertIn(category, out.csharp)


def _grounded_wall(oid, x0, y0, x1, y1):
    """A PRE-GROUNDED create_wall member (the shape the component-library bridge
    produces): level/type carry the {"__grounded__": ...} marker directly."""
    return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0], "p1_mm": [x1, y1],
            "level": {"__grounded__": {"id": 42, "name": None,
                                       "via": "element_id"}},
            "height_mm": 3000.0,
            "type": {"__grounded__": {"id": None, "name": None,
                                      "via": "doc_default",
                                      "in_emit": "__doc_default__"}}}


class NativeGroup(unittest.TestCase):
    """feat/native-groups: the create_group forward op (NewGroup/PlaceGroup)."""

    def _group_prog(self, *, name=None, placements=((0, 0, 6600), (0, 0, 13200))):
        op = {"op": "create_group", "id": "GRP1",
              "members": [_grounded_wall("W1", 30000, 23000, 36000, 23000),
                          _grounded_wall("W2", 36000, 23000, 36000, 27000)],
              "placements": [list(p) for p in placements]}
        if name is not None:
            op["name"] = name
        return _prog([op], intent="типовой этаж как группа")

    def test_group_compiles_offline_and_emits_native_api(self):
        out = compile_program(self._group_prog(name="Типовой этаж"),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        cs = out.csharp
        # the native Revit group API, fully-qualified (Group collides with
        # System.Text.RegularExpressions.Group under the compile wrapper).
        self.assertIn("doc.Create.NewGroup(", cs)
        self.assertIn("doc.Create.PlaceGroup(", cs)
        self.assertIn("Autodesk.Revit.DB.Group ", cs)
        self.assertIn("Autodesk.Revit.DB.GroupType ", cs)
        self.assertNotRegex(cs, r"(?<![.\w])Group\s+__grp_")  # never bare Group

    def test_placement_math_reads_live_origin_and_adds_delta(self):
        # The invariant: PlaceGroup aligns the group ORIGIN to its location, and
        # O0 is read LIVE (never assumed 0); occurrence k is placed at
        # O0 + delta_k.  Assert the emission does exactly that.
        out = compile_program(self._group_prog(), snapshot=SNAPSHOT)
        cs = out.csharp
        self.assertIn(".Location as LocationPoint", cs)   # read O0
        self.assertIn("__o0_GRP1 = __lp0_GRP1.Point", cs)
        # deltas are the ABSOLUTE-origin differences (0,0,6600)/(0,0,13200),
        # added to the live origin — never a fixed absolute point.
        self.assertIn("__o0_GRP1.Z + U(6600.0)", cs)
        self.assertIn("__o0_GRP1.Z + U(13200.0)", cs)

    def test_fail_closed_guards_present(self):
        # NewGroup null, missing GroupType, missing origin, and each PlaceGroup
        # null all roll back (fail-closed -> caller keeps N loose elements).
        cs = compile_program(self._group_prog(), snapshot=SNAPSHOT).csharp
        self.assertIn("NewGroup вернул null", cs)
        self.assertIn("PlaceGroup вернул null", cs)
        # every guard rolls the transaction back before refusing.
        self.assertGreaterEqual(cs.count("__t.RollBack(); return __Refuse("), 3)

    def test_definition_only_group_is_legal(self):
        # occurrence 0 IS the members, so an EMPTY placements list is valid.
        out = compile_program(self._group_prog(placements=()), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("doc.Create.NewGroup(", out.csharp)

    def test_name_rename_only_when_given(self):
        with_name = compile_program(
            self._group_prog(name="Секция"), snapshot=SNAPSHOT).csharp
        self.assertIn("__gt_GRP1.Name = ", with_name)
        without = compile_program(
            self._group_prog(name=None), snapshot=SNAPSHOT).csharp
        self.assertNotIn("__gt_GRP1.Name = ", without)

    def test_determinism(self):
        p = self._group_prog(name="Секция")
        a = compile_program(p, snapshot=SNAPSHOT).csharp
        b = compile_program(p, snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)

    def test_rejects_query_member(self):
        # a member must be an authoring op, never a query op.
        out = compile_program(_prog([{
            "op": "create_group", "id": "G",
            "members": [{"op": "query_count", "id": "q", "kind": "wall"}],
            "placements": []}]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_rejects_nested_group(self):
        out = compile_program(_prog([{
            "op": "create_group", "id": "G",
            "members": [{"op": "create_group", "id": "inner",
                         "members": [_grounded_wall("W", 0, 0, 1000, 0)],
                         "placements": []}],
            "placements": []}]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_rejects_bad_placements(self):
        out = compile_program(_prog([{
            "op": "create_group", "id": "G",
            "members": [_grounded_wall("W", 0, 0, 6000, 0)],
            "placements": [[0]]}]), snapshot=SNAPSHOT)  # 1-D point
        self.assertFalse(out.ok)

    def test_rejects_duplicate_member_ids(self):
        out = compile_program(_prog([{
            "op": "create_group", "id": "G",
            "members": [_grounded_wall("W", 0, 0, 6000, 0),
                        _grounded_wall("W", 0, 4000, 6000, 4000)],
            "placements": []}]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_group_in_program_schema(self):
        sch = program_schema()
        # create_group must be a decodable op in the program schema (no
        # unknown-param-kind crash on member_ops/placements).
        self.assertIn("create_group", str(sch))


class RoomNameIsNotTheNameProperty(unittest.TestCase):
    """`Room.Name` НЕ отдаёт то, что в него положили — замер живьём 04.08.

    Живая проба на «Проект1» (Revit 2026, ru-RU, транзакция откачена):

        rm.Name = "KIR_GAP_ROOM_1";
        rm.Name                                   -> "KIR_GAP_ROOM_1 1"
        rm.Name == "KIR_GAP_ROOM_1"               -> False
        ROOM_NAME.AsString()                      -> "KIR_GAP_ROOM_1"
        ROOM_NAME.AsString() == "KIR_GAP_ROOM_1"  -> True

    Геттер `Room.Name` склеивает ИМЯ и НОМЕР («KIR_GAP_ROOM_1» + " " + "1"),
    а сеттер кладёт только имя.  Постусловие, сверяющее геттер с запрошенным
    именем, поэтому нарушается ВСЕГДА — и живая матрица 04.08 честно
    откатывала ИСПРАВНУЮ постройку с `KIR-X004: RM: name mismatch`.

    Это ложный КРАСНЫЙ: свидетель мерил не то, чем оп писал.  Читать имя
    обязан `BuiltInParameter.ROOM_NAME` — тот же параметр, в который пишет
    сеттер."""

    def _room_cs(self, name="Зал"):
        op = {"op": "create_room", "id": "RM", "xy": [2000, 1500],
              "level": {"by": "name", "value": "Этаж 1"}, "name": name}
        diagnostics = []
        normalized = authoring.validate(op, "create_room", 0, "RM", diagnostics)
        self.assertEqual(diagnostics, [])
        return authoring.emit_program(ground.ground([normalized], SNAPSHOT),
                                      "2026")

    def test_name_postcondition_reads_room_name_parameter(self):
        cs = self._room_cs()
        self.assertIn("BuiltInParameter.ROOM_NAME", cs)

    def test_name_postcondition_never_compares_the_name_property(self):
        # Ровно та строка, которая откатывала исправное помещение.
        cs = self._room_cs()
        self.assertNotIn('__el_RM.Name != "Зал"', cs)

    def test_readback_reports_the_requested_name_not_name_plus_number(self):
        # Квитанция обязана называть ИМЯ. `.Name` вернул бы «Зал 1» и увёл
        # бы читателя от того, что программа на самом деле поставила.
        cs = self._room_cs()
        self.assertNotIn('__rb["name"] = __el_RM.Name;', cs)

    def test_room_without_a_name_emits_no_name_postcondition(self):
        op = {"op": "create_room", "id": "RM", "xy": [2000, 1500],
              "level": {"by": "name", "value": "Этаж 1"}}
        diagnostics = []
        normalized = authoring.validate(op, "create_room", 0, "RM", diagnostics)
        self.assertEqual(diagnostics, [])
        cs = authoring.emit_program(ground.ground([normalized], SNAPSHOT),
                                    "2026")
        self.assertNotIn("RM: name mismatch", cs)


if __name__ == "__main__":
    unittest.main()
