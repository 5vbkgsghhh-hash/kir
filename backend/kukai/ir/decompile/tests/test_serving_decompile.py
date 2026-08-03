"""Serving-layer tests for the Wave A1 decompile/rebuild admin instruments.

Covers the stage-2 device gate, the single-run double-start refusal, status /
cancel dispatch, and the rebuild materializer-pending refusal (A3 not merged)
plus a mocked-present dry-run compile summary.  No Revit, no network: the
executor/bridge and the materializer are mocked.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_a1_serving_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
# Импортируется НА ВЕРХНЕМ УРОВНЕ намеренно: фикстура тянет kir_idempotence,
# который импортирует настоящий materialize. Импорт изнутри теста, где
# sys.modules уже подменён заглушкой, ловит ImportError на ровном месте.
from kukai.ir.decompile.tests.test_serving_idempotence import (  # noqa: E402
    _persist_decompile,
)


def _run(coro):
    return asyncio.run(coro)


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a, **k):
        return None


async def _never_bridge(method, params):  # pragma: no cover — never reached
    raise AssertionError("bridge should not be called in these tests")


class OutDirIdentity(unittest.TestCase):
    def test_lossy_stamp_names_get_full_input_digest(self):
        long_prefix = "project-" + "x" * 140
        first = serving._decompile_out_dir(long_prefix + "-A")
        second = serving._decompile_out_dir(long_prefix + "-B")
        unsafe_a = serving._decompile_out_dir("project/a")
        unsafe_b = serving._decompile_out_dir("project?a")

        self.assertNotEqual(first, second)
        self.assertNotEqual(unsafe_a, unsafe_b)
        self.assertLessEqual(len(os.path.basename(first)), 120)
        self.assertTrue(serving._decompile_out_dir("docA").endswith("/docA"))
        self.assertNotEqual(
            os.path.normpath(serving._decompile_out_dir("..")),
            os.path.normpath(os.path.join(serving._DECOMPILE_OUT_ROOT, "..")))


class DecompileGate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)

    def test_flag_off_hidden(self):
        for value in (None, "off", "shadow", "stage1"):
            if value is None:
                os.environ.pop("KUKAI_KIR_DECOMPILE", None)
            else:
                os.environ["KUKAI_KIR_DECOMPILE"] = value
            self.assertFalse(serving.revit_decompile_enabled())

    def test_stage2_wrong_device_hidden(self):
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        with mock.patch.object(serving, "_turn_device_id", return_value="x"):
            self.assertFalse(serving.revit_decompile_enabled())

    def test_stage2_admin_visible(self):
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        with mock.patch.object(serving, "_turn_device_id",
                               return_value=serving.ADMIN_DEVICE):
            self.assertTrue(serving.revit_decompile_enabled())

    def test_handler_refuses_when_gate_off(self):
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        result = _run(serving.handle_revit_decompile(
            {"action": "start", "doc_stamp": "d"}, _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "gate")


class DecompileDispatch(unittest.TestCase):
    def setUp(self):
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        serving._active_run.clear()

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        serving._active_run.clear()

    def test_start_requires_doc_stamp(self):
        result = _run(serving.handle_revit_decompile(
            {"action": "start"}, _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_bad_action_typed(self):
        result = _run(serving.handle_revit_decompile(
            {"action": "frobnicate"}, _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_double_start_is_refused(self):
        # A slow fake run keeps the single per-process task busy so the second
        # start observes it and returns the typed «run_in_progress» refusal.
        started = asyncio.Event()

        async def _slow_run(executor, *, out_dir, change_stamp, **kw):
            started.set()
            await asyncio.sleep(5)
            return serving  # unreachable value; task is cancelled in teardown

        async def _drive():
            with mock.patch(
                    "kukai.ir.decompile.pipeline.run_decompile", _slow_run):
                first = await serving.handle_revit_decompile(
                    {"action": "start", "doc_stamp": "docA"},
                    _ShimLLM(), _never_bridge)
                await started.wait()
                second = await serving.handle_revit_decompile(
                    {"action": "start", "doc_stamp": "docA"},
                    _ShimLLM(), _never_bridge)
                task = serving._active_run.get("task")
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                return first, second

        first, second = _run(_drive())
        self.assertTrue(first["ok"])
        self.assertTrue(first["started"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"], "run_in_progress")

    def test_status_reads_persisted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                from kukai.ir.decompile import pipeline as pipe
                pipe._atomic_write_json(
                    __import__("pathlib").Path(tmp) / "status.json",
                    {"stage": "curve", "done": 1, "total": 3,
                     "cancel_requested": False})
                result = _run(serving.handle_revit_decompile(
                    {"action": "status", "doc_stamp": "docA"},
                    _ShimLLM(), _never_bridge))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["stage"], "curve")

    def test_cancel_sets_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                from kukai.ir.decompile import pipeline as pipe
                import pathlib
                pipe._atomic_write_json(
                    pathlib.Path(tmp) / "status.json",
                    {"stage": "curve", "cancel_requested": False})
                result = _run(serving.handle_revit_decompile(
                    {"action": "cancel", "doc_stamp": "docA"},
                    _ShimLLM(), _never_bridge))
                self.assertTrue(result["ok"])
                self.assertTrue(pipe.read_status(tmp)["cancel_requested"])


class RebuildInstrument(unittest.TestCase):
    def setUp(self):
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_DECOMPILE", None)
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        sys.modules.pop("kukai.ir.decompile.materialize", None)

    def test_materializer_pending_when_module_absent(self):
        # Интеграционный шов A1×A3: модуль materialize ТЕПЕРЬ существует
        # (волна A3 смержена), поэтому «отсутствие» симулируется явно —
        # запись None в sys.modules заставляет import поднять ImportError
        # (прежний sys.modules.pop полагался на реальное отсутствие файла и
        # молча перестал тестировать эту ветку после мержа A3).
        with mock.patch.dict(
                sys.modules, {"kukai.ir.decompile.materialize": None}):
            result = _run(serving.handle_revit_rebuild(
                {"doc_stamp": "docA", "dry_run": True}, _ShimLLM(),
                _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "materializer_pending")

    def test_dry_run_compiles_chunks_with_mocked_materializer(self):
        # Inject a fake materialize module that returns two empty programs; the
        # compiler gates each chunk.  Also requires a persisted tree.json.
        fake = types.ModuleType("kukai.ir.decompile.materialize")

        def _leaves_to_program(leaves, mode="same_document", chunk=250):
            # The REAL A3 materializer returns a MaterializeResult whose
            # compiler-ready programs live on ``.programs`` — model that shape
            # (a bare list hid the «MaterializeResult is not iterable» seam that
            # only surfaced on the live «демо» dry-run, 2026-07-21).
            # The second program holds 25 ops (> the 20-op LLM budget): the
            # rebuild dry-run must compile materializer chunks with bulk=True,
            # else every real chunk (250 ops) is refused KIR-L001 — the seam
            # that surfaced on the live «демо» dry-run, 2026-07-21.
            return types.SimpleNamespace(programs=[
                {"ir_version": "1.0", "ops": [
                    {"op": "query_count", "id": "q0", "kind": "wall"}]},
                {"ir_version": "1.0", "ops": [
                    {"op": "query_count", "id": f"q{i}", "kind": "door"}
                    for i in range(25)]},
            ])

        fake.leaves_to_program = _leaves_to_program  # type: ignore[attr-defined]
        sys.modules["kukai.ir.decompile.materialize"] = fake

        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pathlib
            # A minimal TreeNode so iter_l1_leaves has something to walk (the
            # mocked materializer ignores the leaves anyway).
            (pathlib.Path(tmp) / "tree.json").write_text(
                json.dumps({"payload": None, "members": [], "children": []}),
                encoding="utf-8")
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))
        self.assertTrue(result["ok"], msg=result)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["chunks_total"], 2)
        self.assertEqual(result["chunks_ok"], 2)

    def test_dry_run_reuses_materializer_plan_and_reports_its_digest(self):
        fake = types.ModuleType("kukai.ir.decompile.materialize")
        retained_plan = types.SimpleNamespace(plan_digest="a" * 64)
        raw_program = {
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q0", "kind": "wall"}],
        }
        fake.leaves_to_program = (  # type: ignore[attr-defined]
            lambda leaves, **kwargs: types.SimpleNamespace(
                programs=[raw_program], plans=(retained_plan,)))
        sys.modules["kukai.ir.decompile.materialize"] = fake

        compiled = types.SimpleNamespace(
            ok=True, diagnostics=[], planned=retained_plan)
        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pathlib
            (pathlib.Path(tmp) / "tree.json").write_text(
                json.dumps({"payload": None, "members": [], "children": []}),
                encoding="utf-8")
            with (
                mock.patch.object(serving, "_decompile_out_dir",
                                  return_value=tmp),
                mock.patch("kukai.ir.compiler.compile_rebuild_chunk",
                           return_value=compiled) as compile_mock,
            ):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))

        self.assertTrue(result["ok"], result)
        self.assertIs(compile_mock.call_args.args[0], retained_plan)
        self.assertEqual(result["chunks"][0]["plan_digest"], "a" * 64)

    def test_offset_is_validated_and_forwarded_to_materializer(self):
        fake = types.ModuleType("kukai.ir.decompile.materialize")
        seen = {}

        def _leaves_to_program(leaves, **kwargs):
            seen.update(kwargs)
            return types.SimpleNamespace(programs=[])

        fake.leaves_to_program = _leaves_to_program  # type: ignore[attr-defined]
        sys.modules["kukai.ir.decompile.materialize"] = fake
        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pathlib
            (pathlib.Path(tmp) / "tree.json").write_text(
                json.dumps({"payload": None, "members": [], "children": []}),
                encoding="utf-8")
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True,
                     "offset_mm": [1250, -500.5, 0]},
                    _ShimLLM(), _never_bridge))

        self.assertTrue(result["ok"], result)
        self.assertEqual(seen["offset_mm"], (1250.0, -500.5, 0.0))
        self.assertEqual(result["offset_mm"], [1250.0, -500.5, 0.0])

    def test_rebuild_refuses_without_decompile(self):
        fake = types.ModuleType("kukai.ir.decompile.materialize")
        fake.leaves_to_program = lambda *a, **k: []  # type: ignore[attr-defined]
        sys.modules["kukai.ir.decompile.materialize"] = fake
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(serving, "_decompile_out_dir",
                                   return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA"}, _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_decompile")

    def test_atom_escrow_is_default_off(self):
        self.assertFalse(serving.atom_escrow_enabled())
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                os.environ["KUKAI_IR_ATOM_ESCROW"] = value
                self.assertTrue(serving.atom_escrow_enabled())
        os.environ["KUKAI_IR_ATOM_ESCROW"] = "off"
        self.assertFalse(serving.atom_escrow_enabled())

    def test_enabled_atom_escrow_refuses_without_geometry_evidence(self):
        os.environ["KUKAI_IR_ATOM_ESCROW"] = "on"
        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pathlib
            (pathlib.Path(tmp) / "tree.json").write_text(
                json.dumps({"payload": None, "members": [], "children": []}),
                encoding="utf-8")
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "atom_escrow_missing")

    def test_enabled_atom_escrow_reaches_dry_compile_with_pending_evidence(
            self):
        from kukai.ir.decompile.geom_extract import (
            GeometryArtifactProof,
            extract_geometry,
        )
        from kukai.ir.decompile.tests.test_geom_extract import (
            _element as geometry_element,
            _part as geometry_part,
            _payload as geometry_payload,
            _triangle_mesh,
        )
        from kukai.ir.decompile.tests.test_materialize import _atom_leaf

        os.environ["KUKAI_IR_ATOM_ESCROW"] = "on"
        atom = _atom_leaf("9901", "OST_Walls")
        geometry = extract_geometry(geometry_payload([
            geometry_element(
                "9901", "OST_Walls", [geometry_part(_triangle_mesh())]),
        ]))
        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pathlib
            root = pathlib.Path(tmp)
            root.joinpath("tree.json").write_text(json.dumps({
                "payload": atom, "members": [], "children": [],
            }), encoding="utf-8")
            root.joinpath("geometry.bundle.json").write_text(
                json.dumps(geometry.to_dict()), encoding="utf-8")
            root.joinpath("revision.proof.json").write_text(json.dumps({
                "schema_version": "document-revision/1",
                "change_stamp": "docA",
                "fingerprint": "revision-docA",
            }), encoding="utf-8")
            proof = GeometryArtifactProof.bind(
                change_stamp="docA",
                revision_fingerprint="revision-docA",
                geometry_bundle=root.joinpath(
                    "geometry.bundle.json").read_bytes(),
                leaves=[atom],
            )
            root.joinpath("geometry.proof.json").write_text(
                json.dumps(proof.to_dict()), encoding="utf-8")
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))

        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["materialize_mode"], "escrow")
        self.assertEqual(result["atoms_escrowed"], 1)
        self.assertEqual(result["atoms_skipped"], 0)
        self.assertEqual(result["chunks_total"], 1)
        self.assertEqual(
            result["escrow_evidence"][0]["acceptance_state"],
            "pending_runtime_witness",
        )

    def test_atom_escrow_loader_rejects_bundle_changed_after_proof(self):
        import json
        import pathlib
        from kukai.ir.decompile.geom_extract import (
            GeometryArtifactProof,
            GeometryPayloadError,
            extract_geometry,
        )
        from kukai.ir.decompile.tests.test_geom_extract import (
            _element as geometry_element,
            _part as geometry_part,
            _payload as geometry_payload,
            _triangle_mesh,
        )
        from kukai.ir.decompile.tests.test_materialize import _atom_leaf

        atom = _atom_leaf("9901", "OST_Walls")
        geometry = extract_geometry(geometry_payload([
            geometry_element(
                "9901", "OST_Walls", [geometry_part(_triangle_mesh())]),
        ]))
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bundle = root / "geometry.bundle.json"
            bundle.write_text(json.dumps(geometry.to_dict()), encoding="utf-8")
            root.joinpath("revision.proof.json").write_text(json.dumps({
                "schema_version": "document-revision/1",
                "change_stamp": "docA",
                "fingerprint": "revision-docA",
            }), encoding="utf-8")
            proof = GeometryArtifactProof.bind(
                change_stamp="docA",
                revision_fingerprint="revision-docA",
                geometry_bundle=bundle.read_bytes(),
                leaves=[atom],
            )
            root.joinpath("geometry.proof.json").write_text(
                json.dumps(proof.to_dict()), encoding="utf-8")
            # Still valid JSON and the same typed geometry, but no longer the
            # exact bytes that the revision-bound proof committed to.
            bundle.write_bytes(bundle.read_bytes() + b"\n")

            with self.assertRaisesRegex(GeometryPayloadError, "does not match"):
                serving._load_atom_escrow_bundle(tmp, [atom])

    # ── §18.4, хвост волны: гейт частичного чтения стоял ТОЛЬКО на A5 ──────
    #
    # Пересборка из разбора, сделанного при закрытых рабочих наборах, строит
    # ЧАСТЬ здания и молчит об этом. Отказ ровно тот же, что у A5, включая
    # именной карваут allow_partial — иначе закон заражения действует на
    # инструмент, который только МЕРЯЕТ, и не действует на тот, который ПИШЕТ.

    def _rebuild_fixture(self, tmp: str, *, worksets_closed: int = 0) -> None:
        import json
        import pathlib
        _persist_decompile(tmp, worksets_closed=worksets_closed)
        (pathlib.Path(tmp) / "tree.json").write_text(
            json.dumps({"payload": None, "members": [], "children": []}),
            encoding="utf-8")

    def _fake_materializer(self):
        fake = types.ModuleType("kukai.ir.decompile.materialize")
        fake.leaves_to_program = (  # type: ignore[attr-defined]
            lambda leaves, **kwargs: types.SimpleNamespace(programs=[]))
        sys.modules["kukai.ir.decompile.materialize"] = fake

    def test_rebuild_refuses_a_partial_read_decompile(self):
        self._fake_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            self._rebuild_fixture(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "partial_read")
        self.assertEqual(result["worksets_closed"], 2)
        self.assertTrue(result["is_partial_read"])
        self.assertIn("ворксет", result["message_ru"])

    def test_rebuild_partial_read_carveout_is_explicit_and_recorded(self):
        self._fake_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            self._rebuild_fixture(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True,
                     "allow_partial": True},
                    _ShimLLM(), _never_bridge))
        self.assertTrue(result["ok"], msg=result)
        self.assertTrue(result["allow_partial"])
        self.assertTrue(result["is_partial_read"])
        self.assertEqual(result["worksets_closed"], 2)

    def test_rebuild_rejects_non_boolean_allow_partial(self):
        self._fake_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            self._rebuild_fixture(tmp, worksets_closed=2)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True,
                     "allow_partial": "yes"},
                    _ShimLLM(), _never_bridge))
        self.assertFalse(result.get("ok", True))
        self.assertEqual(result["error"], "args")

    def test_rebuild_of_a_complete_read_stays_unmarked(self):
        self._fake_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            self._rebuild_fixture(tmp)
            with mock.patch.object(
                    serving, "_decompile_out_dir", return_value=tmp):
                result = _run(serving.handle_revit_rebuild(
                    {"doc_stamp": "docA", "dry_run": True},
                    _ShimLLM(), _never_bridge))
        self.assertTrue(result["ok"], msg=result)
        self.assertFalse(result["is_partial_read"])


class ScopeLeavesHostClosure(unittest.TestCase):
    """Пин host-замыкания A5-скоупа (живой баг #14, 2026-07-21).

    Дверь в скоупе обязана дотянуть свою стену-хост (иначе materialize
    падает fail-closed 'has no materialized host op'); хосты не считаются
    в limit_ops; чужие стены не тянутся; порядок листьев сохранён."""

    @staticmethod
    def _leaves():
        def wall(lid, name="Стена"):
            return {"kind": "op", "op_name": "create_wall", "_id": lid,
                    "level_name": "Этаж 1", "params": {"type": name}}

        def door(lid, host):
            return {"kind": "op", "op_name": "create_door", "_id": lid,
                    "level_name": "Этаж 1",
                    "params": {"host": {"ref": host}}}
        return [wall("w1"), wall("w2"), door("d1", "w1"),
                door("d2", "w1"), {"kind": "atom", "_id": "a1"}]

    def test_door_scope_pulls_host_wall_outside_cap(self):
        from kukai.ir.serving import _scope_leaves
        scoped = _scope_leaves(self._leaves(), limit_ops=2,
                               only_kinds=["create_door"])
        ids = [leaf["_id"] for leaf in scoped]
        # w2 чужая.  Атом ОСТАЁТСЯ (арх-разбор 2026-07-25 §3.6): он не
        # ребилдится, но обязан быть в знаменателе метрики.
        self.assertEqual(ids, ["w1", "d1", "d2", "a1"])

    def test_cap_counts_targets_not_hosts(self):
        from kukai.ir.serving import _scope_leaves
        scoped = _scope_leaves(self._leaves(), limit_ops=1,
                               only_kinds=["create_door"])
        ids = [leaf["_id"] for leaf in scoped]
        # Кап считает целевые опы; ни хост, ни атом в кап не входят.
        self.assertEqual(ids, ["w1", "d1", "a1"])

    @staticmethod
    def _cross_level_leaves():
        # Высокая стена на Этаже -3 хостит двери на -3/-2/-1 (живой баг #17).
        return [
            {"kind": "op", "op_name": "create_wall", "_id": "wtall",
             "level_name": "Этаж -3", "params": {"type": "ЖБ"}},
            {"kind": "op", "op_name": "create_door", "_id": "d_m3",
             "level_name": "Этаж -3", "params": {"host": {"ref": "wtall"}}},
            {"kind": "op", "op_name": "create_door", "_id": "d_m2",
             "level_name": "Этаж -2", "params": {"host": {"ref": "wtall"}}},
        ]

    def test_level_scope_pulls_cross_level_host(self):
        # Скоуп «Этаж -2» обязан втянуть стену-хост с «Этаж -3» — иначе
        # materialize падает (живой отказ паркинга -2/-1: 0/93, 0/119).
        from kukai.ir.serving import _scope_leaves
        scoped = _scope_leaves(self._cross_level_leaves(),
                               level_scope="Этаж -2")
        ids = sorted(leaf["_id"] for leaf in scoped)
        self.assertIn("wtall", ids)   # cross-level host pulled
        self.assertIn("d_m2", ids)    # the -2 door
        self.assertNotIn("d_m3", ids)  # the -3 door is out of level scope

    def test_level_scope_runs_closure_without_limit_or_kinds(self):
        # Чистый level_scope (без limit/only_kinds) ТОЖЕ запускает замыкание
        # (раньше ранний return его пропускал — этаж 20 везло со своими хостами).
        from kukai.ir.serving import _scope_leaves
        scoped = _scope_leaves(self._cross_level_leaves(),
                               level_scope="Этаж -3")
        ids = sorted(leaf["_id"] for leaf in scoped)
        self.assertEqual(ids, ["d_m3", "wtall"])  # -3 door + its host

    def test_wall_scope_pulls_nothing_extra(self):
        from kukai.ir.serving import _scope_leaves
        scoped = _scope_leaves(self._leaves(), only_kinds=["create_wall"])
        # Чужие двери не тянутся; атом остаётся — у него нет op_name, и
        # отбросить его по роду значило бы прятать неподнятое (§3.6).
        self.assertEqual([leaf["_id"] for leaf in scoped],
                         ["w1", "w2", "a1"])

    def test_atom_escrow_scope_is_stable_and_bounded_by_limit(self):
        from kukai.ir.serving import _atom_escrow_source_ids_for_scope

        leaves = [
            {"kind": "atom", "source_element_id": "20"},
            {"kind": "atom", "source_element_id": "3"},
            {"kind": "atom", "source_element_id": "100"},
        ]
        selected = _atom_escrow_source_ids_for_scope(
            leaves, whole_model=False, limit_ops=2, level_scope=None)

        self.assertEqual(selected, ("3", "20"))

    def test_only_kinds_cannot_guess_an_atom_write_scope(self):
        from kukai.ir.serving import _atom_escrow_source_ids_for_scope

        with self.assertRaisesRegex(
                serving.A5JournalError,
                "whole_model, level_scope, or limit_ops"):
            _atom_escrow_source_ids_for_scope(
                [{"kind": "atom", "source_element_id": "3"}],
                whole_model=False,
                limit_ops=None,
                level_scope=None,
            )


if __name__ == "__main__":
    unittest.main()
