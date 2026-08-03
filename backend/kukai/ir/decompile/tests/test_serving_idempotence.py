"""Serving-layer tests for the Wave A5 idempotence admin instrument.

Covers the stage-2 device gate, the no-decompile refusal, and a dry-run that
loads persisted tree/passport artifacts and compile-gates the Δ-programs — all
with the bridge mocked (the dry-run path never touches the bridge, so the mock
asserts it is never called).  Mirrors ``test_serving_decompile`` style.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_a5_serving_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.contracts import RevisionProof  # noqa: E402
from kukai.ir.open_model import (  # noqa: E402
    OpenModelProfile,
    required_grounding_pools,
)
import kir_idempotence as K  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a, **k):
        return None


class _LeaseStore:
    def __init__(self):
        self.owner = None

    async def acquire_a5_document_lease(
            self, fingerprint_digest, owner_token, run_id, ttl_seconds):
        if self.owner is not None:
            return False
        self.owner = owner_token
        return True

    async def renew_a5_document_lease(
            self, fingerprint_digest, owner_token, ttl_seconds):
        return self.owner == owner_token

    async def release_a5_document_lease(
            self, fingerprint_digest, owner_token):
        if self.owner != owner_token:
            return False
        self.owner = None
        return True


async def _never_bridge(method, params):  # pragma: no cover — must not be called
    raise AssertionError("bridge must not be called on the dry-run/gate path")


async def _revision_after_chunk():
    return "revision-with-a5-elements"


def _exact_open_model_profile(
    fingerprint: serving.DocumentFingerprint,
    *,
    include_wall_bindings: bool = True,
) -> OpenModelProfile:
    snapshot = {
        pool_name: [] for pool_name in required_grounding_pools()
    }
    if include_wall_bindings:
        snapshot["levels"] = [{
            "id": 100,
            "name": "Этаж 1",
            "unique_id": "level-100",
            "version_guid": "0" * 32,
            "class_name": "Autodesk.Revit.DB.Level",
            "category": "OST_Levels",
        }]
        snapshot["wall_types"] = [{
            "id": 5001,
            "name": "Стена 200",
            "unique_id": "wall-type-5001",
            "version_guid": "1" * 32,
            "class_name": "Autodesk.Revit.DB.WallType",
            "category": "OST_Walls",
        }]
    for pool_name in required_grounding_pools():
        snapshot[pool_name + "__total"] = len(snapshot[pool_name])
    snapshot.update({
        "__document_fingerprint": fingerprint.compiler_guard(),
        "__revit_version": "2026",
        "__revit_build": "test-build",
    })
    profile = OpenModelProfile.from_ground_snapshot(
        snapshot,
        revision_proof=RevisionProof("docA", "revision-docA"),
    )
    if not profile.authoritative:  # pragma: no cover - fixture invariant
        raise AssertionError("synthetic open-model profile is not exact")
    return profile


def _persist_decompile(
    tmp: str,
    *,
    partial_category: str | None = None,
    profile_fingerprint: serving.DocumentFingerprint | None = None,
    worksets_closed: int = 0,
) -> None:
    """Write a minimal tree.json + passport.json A5 can load and re-lift."""
    # One wall op-leaf so materialize produces a compilable Δ-program.
    from kukai.ir.decompile.schema import (
        CategoryState, CategoryStatus, GeometryKind, L0Document, L0Element,
        LevelInfo, ProjectInfo)
    from kukai.ir.decompile.extract import EXTRACT_CATEGORIES
    from kukai.ir.decompile.lift import lift_document
    from kukai.ir.decompile.fold import fold_document

    lvl = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
    proj = ProjectInfo(name="Проект", address="а", building_type_hint=None)
    wall = L0Element(
        element_id="9001", category="OST_Walls", category_ru="Стены",
        type_id="5001", type_name="Стена 200", level_id="100",
        level_name="Этаж 1", geom_kind=GeometryKind.CURVE,
        p0_mm=[0.0, 0.0, 0.0], p1_mm=[6000.0, 0.0, 0.0], rotation_deg=None,
        bbox_min_mm=None, bbox_max_mm=None, host_id=None,
        params={"WALL_USER_HEIGHT_PARAM": 2800.0})
    doc = L0Document(
        doc_name="Проект — КОПИЯ", revit_version="2026", units="mm",
        change_stamp="docA", levels=(lvl,), grids=(), rooms=(),
        project_info=proj, elements=(wall,))
    l1 = lift_document(doc)
    tree = fold_document(doc, l1)
    (pathlib.Path(tmp) / "tree.json").write_text(
        json.dumps(tree), encoding="utf-8")
    # The REAL passport does NOT persist the L0 datum block — the authoritative
    # metadata source is the frozen L0.jsonl header record ``{"document": {...}}``
    # (the live «демо» A5 dry-run refused `no_metadata` because the fixture used
    # to fake an ``l0_metadata`` passport key that production never writes).
    (pathlib.Path(tmp) / "passport.json").write_text(
        json.dumps({"doc_name": "Проект — КОПИЯ", "revit_version": "2026"}),
        encoding="utf-8")
    header_document: dict = {
        "doc_name": "Проект — КОПИЯ", "revit_version": "2026",
        "units": "mm", "change_stamp": "docA",
        "levels": [lvl.to_dict()], "grids": [], "rooms": [],
        "project_info": proj.to_dict()}
    if worksets_closed:
        # §18.4: разбор, сделанный при закрытых рабочих наборах, несёт пометку
        # в ЗАГОЛОВКЕ L0 — именно оттуда её берёт гейт A5.
        header_document.update({
            "worksharing": True,
            "worksets": [
                {"id": index, "name": f"Набор {index}",
                 "open": index >= worksets_closed}
                for index in range(worksets_closed + 1)
            ],
            "worksets_closed": worksets_closed,
        })
    rows = [json.dumps({
            "record": "header", "schema_version": "1.0",
            "document": header_document})]
    for category in EXTRACT_CATEGORIES:
        is_partial = category == partial_category
        status = CategoryStatus(
            category=category,
            state=(CategoryState.PARTIAL if is_partial
                   else CategoryState.COMPLETE),
            extracted_count=0,
            expected_count=None if is_partial else 0,
            error="synthetic timeout" if is_partial else None,
        )
        rows.append(json.dumps({
            "record": "category_status", "status": status.to_dict()}))
    rows.append(json.dumps({
        "record": "footer", "stream_complete": True,
        "element_count": 0, "link_count": 0,
        "category_count": len(EXTRACT_CATEGORIES),
    }))
    (pathlib.Path(tmp) / "L0.jsonl").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8")
    (pathlib.Path(tmp) / "revision.proof.json").write_text(
        json.dumps({
            "schema_version": "document-revision/1",
            "change_stamp": "docA",
            "fingerprint": "revision-docA",
        }), encoding="utf-8")
    if profile_fingerprint is not None:
        profile = _exact_open_model_profile(profile_fingerprint)
        (pathlib.Path(tmp) / "open_model.profile.json").write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )


class IdempotenceGate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)

    def test_refuses_when_gate_off(self):
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        result = _run(serving.handle_revit_idempotence(
            {"doc_stamp": "docA", "dry_run": True}, _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "gate")


class IdempotenceDispatch(unittest.TestCase):
    def setUp(self):
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        os.environ.pop("KUKAI_A5_CONFIRM_TOKEN", None)
        serving._active_a5_runs.clear()

    def test_requires_doc_stamp(self):
        result = _run(serving.handle_revit_idempotence(
            {"dry_run": True}, _ShimLLM(), _never_bridge))
        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "args")

    def test_refuses_without_decompile(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))
        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "no_decompile")

    def test_enabled_atom_escrow_requires_persisted_geometry_bundle(self):
        os.environ["KUKAI_IR_ATOM_ESCROW"] = "true"
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))

        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "atom_escrow_missing")

    def test_atom_escrow_refuses_ambiguous_only_kinds_scope(self):
        os.environ["KUKAI_IR_ATOM_ESCROW"] = "true"
        result = _run(serving.handle_revit_idempotence(
            {"doc_stamp": "docA", "dry_run": True,
             "only_kinds": ["create_wall"]},
            _ShimLLM(), _never_bridge))

        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "atom_escrow_scope_required")

    def test_dry_run_loads_artifacts_and_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))
        # Dry run: compiled every Δ-chunk, never touched the bridge.
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result.get("error"), msg=result)
        self.assertIsNone(result["multiset_match"])
        self.assertFalse(result["comparison_performed"])
        self.assertEqual(result["datums_skipped"], 0)

    def test_a5_refuses_persisted_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, partial_category="OST_Roofs")
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "snapshot_non_authoritative")
        self.assertEqual(result["partial_categories"], ["OST_Roofs"])

    def test_a5_refuses_partial_read_snapshot(self):
        # §18.4: закрытые рабочие наборы ⇒ загруженные листья описывают ЧАСТЬ
        # модели. Отказ типизированный и объясняет, что делать оператору.
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "partial_read")
        self.assertEqual(result["worksets_closed"], 2)
        self.assertIn("ворксет", result["message_ru"])

    def test_a5_partial_read_carveout_is_explicit_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True, "allow_partial": True},
                    _ShimLLM(), _never_bridge))

        self.assertIsNone(result.get("error"), msg=result)
        self.assertTrue(result["allow_partial"])
        self.assertTrue(result["is_partial_read"])
        self.assertEqual(result["worksets_closed"], 2)

    def test_a5_rejects_non_boolean_allow_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True, "allow_partial": "yes"},
                    _ShimLLM(), _never_bridge))
        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "args")

    def test_a5_legacy_decompile_without_workset_fields_still_runs(self):
        # Осознанная миграция: у старых разборов полей нет — «нет данных» не
        # превращается в отказ, иначе поправка ретроактивно ломает архив.
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            header = json.loads(
                (pathlib.Path(tmp) / "L0.jsonl").read_text(
                    encoding="utf-8").splitlines()[0])
            self.assertNotIn("worksharing", header["document"])
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))
        self.assertIsNone(result.get("error"), msg=result)
        self.assertFalse(result["is_partial_read"])

    def test_a5_refuses_l0_without_committed_coverage_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            l0_path = pathlib.Path(tmp) / "L0.jsonl"
            rows = l0_path.read_text(encoding="utf-8").splitlines()
            l0_path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": True,
                     "whole_model": True},
                    _ShimLLM(), _never_bridge))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "snapshot_non_authoritative")
        self.assertIn("coverage_error", result)

    def test_rejects_non_boolean_modes_before_loading_artifacts(self):
        for field, value in (("dry_run", "false"), ("keep", "false"),
                             ("whole_model", 1)):
            with self.subTest(field=field, value=value):
                args = {"doc_stamp": "docA", "dry_run": True,
                        "whole_model": True}
                args[field] = value
                result = _run(serving.handle_revit_idempotence(
                    args, _ShimLLM(), _never_bridge))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "args")

    def test_rejects_missing_or_malformed_scope(self):
        cases = (
            {"doc_stamp": "docA", "dry_run": True},
            {"doc_stamp": "docA", "dry_run": True, "level_scope": ""},
            {"doc_stamp": "docA", "dry_run": True,
             "only_kinds": "create_wall"},
            {"doc_stamp": "docA", "dry_run": True, "limit_ops": 0},
        )
        for args in cases:
            with self.subTest(args=args):
                result = _run(serving.handle_revit_idempotence(
                    args, _ShimLLM(), _never_bridge))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "args")

    def test_run_scoped_sweep_never_uses_global_kir_prefix(self):
        code = serving._orphan_sweep_cs(
            "kir:a5:0123456789ab:0123456789abcdef:", delete=False)
        self.assertIn("kir:a5:0123456789ab:0123456789abcdef:", code)
        self.assertIn('"preview", true', code)
        self.assertIn(f'"{serving._A5_SWEEP_SCHEMA_VERSION}"', code)
        self.assertNotIn("Take(500)", code)
        self.assertNotIn('StartsWith("kir:")', code)

    # task #69: cancellation-as-a-feature for REGULAR (non-A5) programs.
    # `authoring._program_stamp` writes `kir:<hash8>:<oid>` for every plain
    # chat/`/admin/kir/run` program (`authoring.py::_program_stamp`,
    # `program_hash` = 8 hex chars of a content sha1). Before this change the
    # sweep grammar only accepted the A5 run form, so that stamp could never
    # be cleaned up through this route — the disproving case below failed on
    # unpatched code with ValueError("invalid A5 run stamp prefix").
    def test_plain_program_hash_prefix_is_now_accepted(self):
        code = serving._orphan_sweep_cs("kir:1a2b3c4d:", delete=False)
        self.assertIn("kir:1a2b3c4d:", code)
        self.assertIn('"preview", true', code)

    def test_plain_program_hash_prefix_delete_mode_is_accepted(self):
        code = serving._orphan_sweep_cs("kir:1a2b3c4d:", delete=True)
        self.assertIn("kir:1a2b3c4d:", code)
        self.assertIn('"preview", false', code)

    def test_a5_run_prefix_still_accepted_after_grammar_widened(self):
        # Negative control (regression guard): widening the grammar must not
        # narrow or break the pre-existing A5 form.
        code = serving._orphan_sweep_cs(
            "kir:a5:0123456789ab:0123456789abcdef:", delete=False)
        self.assertIn("kir:a5:0123456789ab:0123456789abcdef:", code)

    def test_open_global_kir_prefix_is_still_rejected(self):
        # Negative control: an unqualified "kir:" must never be accepted —
        # that would mean "delete everything KIR ever built in this
        # document", which is deliberately out of scope (see docstring of
        # ``_orphan_sweep_cs``).
        with self.assertRaises(ValueError) as ctx:
            serving._orphan_sweep_cs("kir:", delete=False)
        msg = str(ctx.exception)
        self.assertIn("kir:a5:", msg)
        self.assertIn("kir:<8 hex", msg)

    def test_garbage_prefix_is_still_rejected(self):
        # Negative control: neither grammar, must stay a typed refusal.
        with self.assertRaises(ValueError):
            serving._orphan_sweep_cs("not-a-stamp-prefix", delete=False)

    def test_malformed_program_hash_prefix_variants_are_rejected(self):
        # Negative controls on the new grammar's edges: wrong digit count,
        # missing trailing colon, uppercase hex — none of these are the
        # exact 8-lowercase-hex form `authoring.program_hash` emits.
        for bad in (
            "kir:1a2b3c4",       # 7 hex digits
            "kir:1a2b3c4dd:",    # 9 hex digits
            "kir:1A2B3C4D:",     # uppercase
            "kir:1a2b3c4d",      # missing trailing colon
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    serving._orphan_sweep_cs(bad, delete=False)

    def test_sweep_csharp_bytes_are_pinned_to_the_wire_version(self):
        prefix = "kir:a5:0123456789ab:0123456789abcdef:"
        expected_by_version = {
            "a5-stamp-sweep/2": (
                "cb43c856801fe88c80586dfada32242713dc6579f6ec91f29a78fe9c9c4a09e9",
                "ed9d8fe07d10c3e323e12dfe75b42c6f71b0497c772f810dee7b36a9d46c1cee",
                "102877a203b867b2745634f9f838796c7df5eaf63d0f21b15eb196dfbeac7b36",
                "b58c60468e6f681583c2764f04fd1eae295c4ca6b5db2c69a97355141a7c509d",
            ),
            # v3 (task #69, lead's decision): + a separate
            # WhereElementIsElementType()/ALL_MODEL_TYPE_COMMENTS census
            # (types_found/types_found_ids/types_found_names) — types are
            # found and reported, never deleted. Roslyn-checked live across
            # all 6 Revit versions for both preview/delete and guarded/
            # unguarded variants (kukai/ir/gate_runner.py does not cover this
            # generator; verified separately via kukai.compile_client).
            "a5-stamp-sweep/3": (
                "78191a18db688c72be86db19316035522076fb8087ac7657b01e205f51805204",
                "13b5095d312258f5bb4afb9caf06ae66e4d89c886b360ff26b8797a88675cfeb",
                "7c80c0951544baf5a1e7e2f7efc7e646088bc81124367746adb2122d8441b5df",
                "60c0090996e854504f82f3e70897d25a60e15e6189be7f8f8659c96197c59628",
            ),
        }
        fingerprint = serving.DocumentFingerprint(
            "Model A5 Copy", "C:/copy.rvt", "uid-a5")
        hashes = tuple(
            hashlib.sha256(serving._orphan_sweep_cs(
                prefix, delete=delete,
                document_fingerprint=(fingerprint if guarded else None),
            ).encode("utf-8")).hexdigest()
            for guarded in (False, True)
            for delete in (False, True))
        self.assertIn(
            serving._A5_SWEEP_SCHEMA_VERSION, expected_by_version,
            "generated sweep C# changed: bump its wire schema version")
        self.assertEqual(
            hashes, expected_by_version[serving._A5_SWEEP_SCHEMA_VERSION],
            "generated sweep C# changed without a wire schema version bump")

    def test_run_scoped_sweep_is_bound_to_probed_document(self):
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", r"C:\\copy.rvt", "uid-a5")
        code = serving._orphan_sweep_cs(
            "kir:a5:0123456789ab:0123456789abcdef:", delete=True,
            document_fingerprint=fingerprint)

        # Once before census and once inside the deletion transaction.
        self.assertGreaterEqual(code.count("document_mismatch"), 2)
        self.assertIn(fingerprint.digest, code)
        self.assertIn("__t.RollBack(); return", code)

    def test_live_single_flight_refuses_second_run_for_same_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            self.assertTrue(serving._claim_a5_document("docA"))
            try:
                with mock.patch.object(
                        serving, "_decompile_out_dir", return_value=tmp):
                    result = _run(serving.handle_revit_idempotence(
                        {"doc_stamp": "docA", "dry_run": False,
                         "whole_model": True},
                        _ShimLLM(), _never_bridge))
            finally:
                serving._release_a5_document("docA")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "run_in_progress")

    def test_durable_fingerprint_lease_refuses_another_worker(self):
        os.environ["KUKAI_A5_CONFIRM_TOKEN"] = "RUN-A5-OK"
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        store = _LeaseStore()
        store.owner = "another-worker"
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, profile_fingerprint=fingerprint)
            with (mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp),
                  mock.patch.object(
                      serving, "_probe_document_fingerprint",
                      new=mock.AsyncMock(return_value=fingerprint))):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": False,
                     "whole_model": True, "confirm_token": "RUN-A5-OK"},
                    _ShimLLM(), _never_bridge, lease_store=store))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "run_in_progress")

    def test_live_snapshot_revision_mismatch_is_fail_closed(self):
        os.environ["KUKAI_A5_CONFIRM_TOKEN"] = "RUN-A5-OK"
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, profile_fingerprint=fingerprint)
            with (mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp),
                  mock.patch.object(
                      serving, "_probe_document_fingerprint",
                      new=mock.AsyncMock(return_value=fingerprint)),
                  mock.patch.object(
                      serving, "_probe_a5_document_revision",
                      new=mock.AsyncMock(return_value="different-revision"))):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": False,
                     "whole_model": True, "confirm_token": "RUN-A5-OK"},
                    _ShimLLM(), _never_bridge,
                    lease_store=_LeaseStore()))
            journal_dir = pathlib.Path(tmp) / "a5_runs"
            journal_created = journal_dir.exists()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "recovery_unavailable")
        self.assertFalse(journal_created)

    def test_open_model_preflight_refuses_before_compile_lease_or_effect(self):
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        stamp_scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        source_profile = _exact_open_model_profile(
            fingerprint, include_wall_bindings=False)
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()
        program = {
            "ir_version": "1.0",
            "program_id": "a" * 64,
            "ops": [{
                "op": "create_wall",
                "id": "W1",
                "level": {"by": "element_id", "value": 100},
                "type": {"by": "element_id", "value": 5001},
            }],
        }

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp, profile_fingerprint=fingerprint)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": hashlib.sha256(
                        b"docA").hexdigest(),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            before = journal.path.read_bytes()
            with (mock.patch(
                    "kukai.ir.compiler.compile_rebuild_chunk") as compile_mock,
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock()) as bridge_mock):
                rebuild, *_rest = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope,
                    stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint,
                    journal=journal,
                    lease=lease,
                    revision_runner=_revision_after_chunk,
                    open_model_profile=source_profile,
                )
                result = _run(rebuild(program))
            after = journal.path.read_bytes()

        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(result["error"], "open_model_preflight")
        self.assertEqual(
            {issue["code"] for issue in result["preflight"]["issues"]},
            {"pinned_element_missing"},
        )
        compile_mock.assert_not_called()
        lease.ensure_held.assert_not_awaited()
        bridge_mock.assert_not_awaited()
        self.assertEqual(after, before)
        self.assertFalse(journal.state.pending_effects)

    def test_rebuild_receipt_is_fsynced_before_runner_returns(self):
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        stamp_scope, stamp_prefix = serving._a5_stamp_scope(
            "docA", serving.RunId("0123456789abcdef"))
        bridge_result = {
            "ok": True,
            "result": {"wall": {"id": "7001"}, "ok": True},
        }
        compiled = mock.Mock(ok=True, csharp="compiled-csharp", diagnostics=[])

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            run_id = serving.RunId("0123456789abcdef")
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": (
                        "d1f11d6786f10c18cf161379e7c5b806ef9df64901f54afc72f89c5a68b3b36c"),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            lease = mock.Mock()
            lease.ensure_held = mock.AsyncMock()
            with (mock.patch(
                    "kukai.ir.compiler.compile_rebuild_chunk",
                    return_value=compiled) as compile_mock,
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock(return_value=bridge_result))):
                rebuild, _read, _delete, _preview, _sweep = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope,
                    stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint,
                    journal=journal, lease=lease,
                    revision_runner=_revision_after_chunk,
                    open_model_profile=_exact_open_model_profile(fingerprint))
                result = _run(rebuild({
                    "ir_version": "1.0",
                    "program_id": "a" * 64,
                    "ops": [{
                        "op": "create_wall",
                        "id": "W1",
                        "level": {"by": "element_id", "value": 100},
                        "type": {"by": "element_id", "value": 5001},
                    }],
                }))

            rows = [json.loads(line) for line in journal.path.read_text(
                encoding="utf-8").splitlines()]

        self.assertTrue(result["ok"])
        self.assertEqual(
            [row["event"] for row in rows],
            ["transition", "transition", "effect_started", "effect_finished"])
        self.assertEqual(rows[-1]["receipt"]["element_ids"], ["7001"])
        self.assertEqual(
            compile_mock.call_args.kwargs["expected_document"],
            fingerprint.compiler_guard())
        self.assertEqual(
            [
                proof.element_id
                for proof in compile_mock.call_args.kwargs[
                    "expected_identities"]
            ],
            [100, 5001],
        )

    def test_timeout_after_commit_stays_pending_for_reconciliation(self):
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        stamp_scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        compiled = mock.Mock(ok=True, csharp="compiled-csharp", diagnostics=[])
        committed_ids: set[str] = set()
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()

        async def _timeout_after_commit(*_args):
            committed_ids.add("7001")
            return {"ok": False, "state": "timeout_unconfirmed",
                    "message": "response lost after dispatch"}

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": (
                        "d1f11d6786f10c18cf161379e7c5b806ef9df64901f54afc72f89c5a68b3b36c"),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            with (mock.patch(
                    "kukai.ir.compiler.compile_rebuild_chunk",
                    return_value=compiled),
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock(side_effect=_timeout_after_commit))):
                rebuild, *_rest = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope, stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint,
                    journal=journal, lease=lease,
                    revision_runner=_revision_after_chunk)
                result = _run(rebuild({
                    "program_id": "a" * 64, "ops": []}))

            reopened = serving.A5Journal.open(journal.path)

        self.assertFalse(result["ok"])
        self.assertEqual(committed_ids, {"7001"})
        self.assertEqual(set(reopened.state.pending_effects),
                         {"rebuild:000000"})
        self.assertFalse(reopened.state.effect_receipts)

    def test_restart_reconciles_commit_whose_response_was_lost(self):
        """F11: unknown post-commit outcome is swept before rebuild replay."""

        class _ProcessKilled(BaseException):
            pass

        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        stamp_scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        compiled = mock.Mock(ok=True, csharp="compiled-csharp", diagnostics=[])
        model_ids: set[str] = set()
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()

        def _stamp_payload(*, delete: bool) -> dict:
            # ONE builder for this wire shape (task #69) — see
            # serving.build_sweep_payload's docstring for why hand-typing it
            # per call site is the exact disease this replaces.
            found = sorted(model_ids)
            deleted = list(found) if delete else []
            if delete:
                model_ids.clear()
            remaining = sorted(model_ids)
            return serving.build_sweep_payload(
                prefix=stamp_prefix, found_ids=found, deleted_ids=deleted,
                remaining_ids=remaining, preview=not delete,
                commit_status="Committed" if delete else "NotStarted",
                wrap_result=True)

        async def _lost_after_commit(*_args):
            model_ids.add("7001")  # Revit committed; transport never replied.
            raise _ProcessKilled()

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": (
                        "d1f11d6786f10c18cf161379e7c5b806ef9df64901f54afc72f89c5a68b3b36c"),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            with (mock.patch(
                    "kukai.ir.compiler.compile_rebuild_chunk",
                    return_value=compiled),
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock(side_effect=_lost_after_commit))):
                rebuild, *_rest = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope, stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint,
                    journal=journal, lease=lease,
                    revision_runner=_revision_after_chunk)
                with self.assertRaises(_ProcessKilled):
                    _run(rebuild({
                        "program_id": "a" * 64, "ops": []}))

            # A fresh process knows only disk journal + live stamped census.
            restarted = serving.A5Journal.open(journal.path)
            self.assertEqual(
                restarted.state.phase, serving.A5Phase.SNAPSHOT_VERIFIED)
            self.assertEqual(set(restarted.state.pending_effects),
                             {"rebuild:000000"})
            self.assertEqual(model_ids, {"7001"})

            async def _restarted_bridge(
                    _llm, _callback, _code, action, _timeout):
                if action == "idempotence_sweep_preview":
                    return _stamp_payload(delete=False)
                if action == "idempotence_sweep":
                    return _stamp_payload(delete=True)
                if action == "idempotence_rebuild":
                    model_ids.add("7002")
                    return {"ok": True,
                            "result": {"wall": {"id": "7002"}}}
                raise AssertionError(action)

            async def _post_rebuild_revision():
                return "revision-with-a5-elements"

            with (mock.patch(
                    "kukai.ir.compiler.compile_rebuild_chunk",
                    return_value=compiled),
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock(side_effect=_restarted_bridge))):
                (rebuild, _read, _delete,
                 preview, sweep) = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope, stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint,
                    journal=restarted, lease=lease,
                    revision_runner=_post_rebuild_revision)
                recovery = serving._A5Recovery(
                    restarted, lease, stamp_prefix=stamp_prefix,
                    preview_runner=preview, sweep_runner=sweep,
                    revision_runner=_post_rebuild_revision)
                _run(recovery.recover_pending_effects())
                self.assertFalse(restarted.state.pending_effects)
                self.assertFalse(model_ids)  # orphan was reconciled first
                replay_size = restarted.path.stat().st_size
                _run(recovery.recover_pending_effects())
                self.assertEqual(restarted.path.stat().st_size, replay_size)
                _run(recovery.prepare_rebuild_plan(["a" * 64]))
                envelope = _run(rebuild({
                    "program_id": "a" * 64, "ops": []}))
                self.assertTrue(envelope["ok"])
                _run(recovery.after_rebuilt(["7002"]))

            self.assertEqual(model_ids, {"7002"})
            self.assertEqual(restarted.state.phase, serving.A5Phase.RECONCILED)
            reopened = serving.A5Journal.open(restarted.path)
            self.assertEqual(reopened.state.phase, serving.A5Phase.RECONCILED)
            self.assertFalse(reopened.state.pending_effects)

    def test_restart_after_fsynced_chunk_resumes_confirmed_prefix(self):
        """A clean kill between chunks preserves progress, not duplicates it."""

        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        _scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()
        first_program = "a" * 64
        second_program = "b" * 64

        async def _preview():
            # ONE builder for this wire shape (task #69) — see
            # serving.build_sweep_payload's docstring.
            return serving.build_sweep_payload(
                prefix=stamp_prefix, found_ids=["7001"],
                remaining_ids=["7001"], wrap_result=True)

        async def _no_sweep():
            raise AssertionError("confirmed prefix must not be swept")

        async def _revision():
            return "revision-after-first-chunk"

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": hashlib.sha256(b"docA").hexdigest(),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            receipt = serving.CommitReceipt(
                run_id=run_id,
                operation="rebuild",
                element_ids=("7001",),
                bridge_error=False,
                commit_confirmed=True,
                commit_status="Committed",
                program_id=first_program,
                document_revision="revision-after-first-chunk",
            )
            journal.start_effect("rebuild:000000", {
                "kind": "rebuild", "program_id": first_program})
            journal.finish_effect(
                "rebuild:000000", receipt.to_dict())
            restarted = serving.A5Journal.open(journal.path)
            recovery = serving._A5Recovery(
                restarted, lease,
                stamp_prefix=stamp_prefix,
                preview_runner=_preview,
                sweep_runner=_no_sweep,
                revision_runner=_revision,
            )
            before = restarted.path.read_bytes()
            _run(recovery.recover_pending_effects())
            confirmed = _run(recovery.prepare_rebuild_plan(
                [first_program, second_program]))

            self.assertEqual(
                confirmed, {first_program: ("7001",)})
            self.assertEqual(recovery.resume_created_ids, ("7001",))
            self.assertEqual(recovery.expected_document_revision,
                             "revision-after-first-chunk")
            self.assertEqual(restarted.state.rebuild_epoch, 0)
            self.assertEqual(restarted.path.read_bytes(), before)

    def test_zero_created_escrow_refusal_can_complete_durably(self):
        """An isolated atom rollback is a closed 0%-coverage outcome."""

        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        _scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        program_id = "a" * 64
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()

        async def _preview():
            return serving.build_sweep_payload(
                prefix=stamp_prefix, found_ids=[], remaining_ids=[],
                wrap_result=True)

        async def _no_sweep():
            raise AssertionError("empty run needs no recovery sweep")

        async def _revision():
            return "revision-docA"

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": hashlib.sha256(b"docA").hexdigest(),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            refusal = serving.CommitReceipt(
                run_id=run_id,
                operation="rebuild",
                element_ids=(),
                bridge_error=True,
                commit_confirmed=False,
                commit_status="RolledBack",
                program_id=program_id,
            )
            journal.start_effect("rebuild:000000", {
                "kind": "rebuild", "program_id": program_id})
            journal.finish_effect("rebuild:000000", {
                **refusal.to_dict(),
                "outcome": "refused_without_commit",
            })
            recovery = serving._A5Recovery(
                journal, lease, stamp_prefix=stamp_prefix,
                preview_runner=_preview, sweep_runner=_no_sweep,
                revision_runner=_revision)

            confirmed = _run(recovery.prepare_rebuild_plan([program_id]))
            self.assertEqual(confirmed, {program_id: ()})
            _run(recovery.after_rebuilt([]))
            report = {
                "doc_stamp": "docA",
                "delta_mm": list(K.DELTA_MM),
                "comparison_performed": True,
                "multiset_match": True,
                "expected_hash": "e",
                "actual_hash": "e",
                "total_expected": 0,
                "total_actual": 0,
                "total_matched": 0,
                "total_extra": 0,
                "raw_precision_pct": None,
                "raw_recall_pct": None,
                "adjusted_precision_pct": None,
                "adjusted_recall_pct": None,
                "per_kind": [],
                "discrepancies": [],
                "datums_skipped": 0,
                "atoms_excluded": 0,
                "atoms_escrowed": 1,
                "atoms_form_accepted": 0,
                "atoms_form_rejected": 0,
                "atoms_form_inconclusive": 1,
                "form_expectations": [{"source_id": "9999"}],
                "form_acceptance": [{
                    "state": "inconclusive",
                    "evidence_digest": "c" * 64,
                }],
                "form_read_error": "",
                "non_datum_total": 1,
                "comparable_coverage_pct": 0.0,
                "canon_version": "fidelity-canon/1",
            }
            _run(recovery.after_compared(report))
            _run(recovery.before_cleanup([], retain=False))
            _run(recovery.after_cleanup(
                [], retain=False, cleanup_ok=True,
                cleanup_detail="nothing to clean up"))

            self.assertEqual(journal.state.phase, serving.A5Phase.COMPLETED)

    def test_recovery_adapter_persists_all_confirmed_phases(self):
        fingerprint = serving.DocumentFingerprint(
            "Проект — КОПИЯ A5", "", "uid-a5")
        run_id = serving.RunId("0123456789abcdef")
        _stamp_scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        live_ids = {"7001"}
        revision = {"value": "revision-with-a5-elements"}
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()

        async def _preview():
            # ONE builder for this wire shape (task #69) — see
            # serving.build_sweep_payload's docstring.
            ids = sorted(live_ids)
            return serving.build_sweep_payload(
                prefix=stamp_prefix, found_ids=ids, remaining_ids=ids,
                wrap_result=True)

        async def _unexpected_sweep():
            raise AssertionError("normal exact-id cleanup needs no recovery sweep")

        async def _revision():
            return revision["value"]

        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": (
                        "d1f11d6786f10c18cf161379e7c5b806ef9df64901f54afc72f89c5a68b3b36c"),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            rebuild_receipt = serving.CommitReceipt(
                run_id=run_id, operation="rebuild", element_ids=("7001",),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed",
                program_id="a" * 64,
                document_revision="revision-with-a5-elements")
            journal.start_effect("rebuild:000000", {
                "kind": "rebuild", "program_id": "a" * 64})
            journal.finish_effect(
                "rebuild:000000", rebuild_receipt.to_dict())
            recovery = serving._A5Recovery(
                journal, lease, stamp_prefix=stamp_prefix,
                preview_runner=_preview, sweep_runner=_unexpected_sweep,
                revision_runner=_revision)

            _run(recovery.prepare_rebuild_plan(["a" * 64]))
            _run(recovery.after_rebuilt(["7001"]))
            _run(recovery.after_compared({
                "comparison_performed": True, "multiset_match": True,
                "total_expected": 1, "total_actual": 1,
                "total_matched": 1, "total_extra": 0,
                "raw_precision_pct": 100.0, "raw_recall_pct": 100.0,
                "adjusted_precision_pct": 100.0,
                "adjusted_recall_pct": 100.0,
                "atoms_excluded": 0, "non_datum_total": 1,
                "comparable_coverage_pct": 100.0,
                "canon_version": "fidelity-canon/1",
            }))
            _run(recovery.before_cleanup(["7001"], retain=False))
            delete_receipt = serving.CommitReceipt(
                run_id=run_id, operation="delete", element_ids=("7001",),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed")
            journal.start_effect("delete:000000", {"kind": "delete"})
            journal.finish_effect("delete:000000", delete_receipt.to_dict())
            live_ids.clear()
            revision["value"] = "revision-docA"
            _run(recovery.after_cleanup(
                ["7001"], retain=False, cleanup_ok=True,
                cleanup_detail="deleted 1/1"))

            reopened = serving.A5Journal.open(journal.path)
            transitions = [
                json.loads(line)["phase"]
                for line in journal.path.read_text(
                    encoding="utf-8").splitlines()
                if json.loads(line)["event"] == "transition"
            ]

        self.assertEqual(reopened.state.phase, serving.A5Phase.COMPLETED)
        self.assertEqual(transitions, [phase.value for phase in serving.A5Phase])

    def test_cleanup_failure_is_top_level_failure_and_not_dashboard_success(self):
        report = K.IdempotenceReport(
            doc_stamp="docA", delta_mm=K.DELTA_MM, multiset_match=True,
            expected_hash="e", actual_hash="e", total_expected=1,
            total_matched=1, raw_exact_pct=100.0,
            adjusted_exact_pct=100.0, per_kind=(), discrepancies=(),
            datums_skipped=0, created_ids=("7001",), cleanup_ok=False,
            cleanup_detail="delete witness missing", dry_run=False)
        os.environ["KUKAI_A5_CONFIRM_TOKEN"] = "RUN-A5-OK"
        serving._last_idempotence.clear()

        with tempfile.TemporaryDirectory() as tmp:
            profile_fingerprint = serving.DocumentFingerprint(
                "Проект", "", "project-uid")
            _persist_decompile(
                tmp, profile_fingerprint=profile_fingerprint)
            with (mock.patch.object(serving, "_decompile_out_dir",
                                    return_value=tmp),
                  mock.patch.object(
                      serving, "_probe_document_fingerprint",
                      new=mock.AsyncMock(return_value=profile_fingerprint)),
                  mock.patch.object(
                      serving, "_probe_a5_document_revision",
                      new=mock.AsyncMock(return_value="revision-docA")),
                  mock.patch.object(serving, "_a5_runners",
                                    return_value=(object(), object(), object(),
                                                  object(), object())),
                  mock.patch.object(K, "run_idempotence",
                                    new=mock.AsyncMock(return_value=report))):
                result = _run(serving.handle_revit_idempotence(
                    {"doc_stamp": "docA", "dry_run": False,
                     "whole_model": True, "confirm_token": "RUN-A5-OK"},
                    _ShimLLM(), _never_bridge,
                    lease_store=_LeaseStore()))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "cleanup_failed")
        self.assertFalse(serving._last_idempotence)


if __name__ == "__main__":
    unittest.main()


class A5RequestHashDeltaTests(unittest.TestCase):
    """Δ входит в тождество запроса: разное смещение — разные прогоны."""

    def _hash(self, delta, *, scope_digest="c" * 64):
        from kukai.ir.contracts import RevisionProof
        from kukai.ir.serving import _a5_request_hash
        return _a5_request_hash(
            doc_stamp="s",
            revision=RevisionProof(change_stamp="c", fingerprint="f"),
            keep_delta=True, whole_model=True,
            limit_ops=None, only_kinds=None, level_scope=None,
            revit_version="2026", scope_digest=scope_digest,
            delta_mm=delta)

    def test_different_offsets_are_different_requests(self):
        self.assertNotEqual(self._hash((100000.0, 0.0, 0.0)),
                            self._hash((200000.0, 0.0, 0.0)))

    def test_default_offset_keeps_the_historical_digest(self):
        from kir_idempotence import DELTA_MM
        self.assertEqual(self._hash(None), self._hash(DELTA_MM))

    def test_scoped_l1_content_is_request_identity(self):
        self.assertNotEqual(
            self._hash(None, scope_digest="c" * 64),
            self._hash(None, scope_digest="d" * 64),
        )

    def _atom_hash(self, *, digest="a" * 64, source_ids=("3", "20")):
        from kukai.ir.serving import _a5_request_hash
        return _a5_request_hash(
            doc_stamp="s",
            revision=RevisionProof(change_stamp="c", fingerprint="f"),
            keep_delta=True, whole_model=False,
            limit_ops=2, only_kinds=None, level_scope=None,
            revit_version="2026", scope_digest="c" * 64,
            atom_escrow=True,
            geometry_bundle_digest=digest,
            atom_escrow_source_ids=source_ids,
        )

    def test_atom_geometry_and_exact_scope_are_request_identity(self):
        baseline = self._atom_hash()
        self.assertNotEqual(baseline, self._atom_hash(digest="b" * 64))
        self.assertNotEqual(
            baseline, self._atom_hash(source_ids=("3", "21")))

    def test_atom_request_refuses_missing_or_unstable_identity(self):
        from kukai.ir.serving import _a5_request_hash

        with self.assertRaisesRegex(
                serving.A5JournalError, "geometry bundle identity"):
            _a5_request_hash(
                doc_stamp="s",
                revision=RevisionProof(change_stamp="c", fingerprint="f"),
                keep_delta=True, whole_model=False,
                limit_ops=2, only_kinds=None, level_scope=None,
                revit_version="2026", scope_digest="c" * 64,
                atom_escrow=True,
                atom_escrow_source_ids=("3", "20"),
            )
        with self.assertRaisesRegex(
                serving.A5JournalError, "sorted and unique"):
            self._atom_hash(source_ids=("20", "3"))
        with self.assertRaisesRegex(
                serving.A5JournalError, "require atom escrow"):
            _a5_request_hash(
                doc_stamp="s",
                revision=RevisionProof(change_stamp="c", fingerprint="f"),
                keep_delta=True, whole_model=True,
                limit_ops=None, only_kinds=None, level_scope=None,
                revit_version="2026", scope_digest="c" * 64,
                atom_escrow=False,
                atom_escrow_source_ids=(),
            )
