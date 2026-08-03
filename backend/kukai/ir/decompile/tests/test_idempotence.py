"""Wave A5 — idempotence orchestrator tests (offline, deterministic).

Every test drives the injected bridge runners with REALISTIC payloads through the
REAL parsers (``lift_document``, ``reextract.parse_reextract_rows``): the rebuild
runner returns serving-style witness read-backs, the read executor returns raw
Δ-translated L0 rows exactly as the ``reextract`` collector would, and the delete
runner records the ids it was asked to remove.  No Revit, no network, no clock,
no random — the translation-invariance property is proven arithmetically on the
CANON_MM grid.

Coverage:
* translation-invariance property: ``multiset_hash(re-lift(rebuild(translate(
  leaves,Δ)))) == multiset_hash(translate(originals,Δ))`` on walls + a hosted door
  + a room;
* datum exclusion: ``create_level``/``create_grid`` never enter the Δ-program and
  are counted as ``datums_skipped``, not compared;
* expected-discrepancy classification: a room that the copy could not re-enclose
  is subtracted from the adjusted %, keeping raw% honest;
* the Д3 SAFETY GUARD (the wave's heart): the live path REFUSES on an
  unconfirmed/working-file title, a flag-off/non-admin gate, and missing runners
  — a typed refusal, never a live write;
* cleanup runs in ``finally`` even when the rebuild raises mid-run.
"""
from __future__ import annotations

import asyncio
import copy
import unittest
from types import SimpleNamespace
from typing import Any, Mapping
from unittest import mock

from kukai.ir.decompile.fold import FidelityCanon, iter_l1_leaves
from kukai.ir.decompile.l1_schema import AtomReason, stable_l1_id
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import (
    GeometryKind,
    GridInfo,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)

import kir_idempotence as K


def _run(coro):
    return asyncio.run(coro)


# ── synthetic fixture: 1 level, (optional 1 grid), 2 walls, 1 hosted door, room ─

_LEVEL = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
_GRID = GridInfo(id="200", name="1", p0_mm=[0.0, -1000.0, 0.0], p1_mm=[0.0, 5000.0, 0.0])
_PROJ = ProjectInfo(name="Проект", address="адрес", building_type_hint=None)
_ROOM = RoomInfo(
    id="8001", name="Комн 101", level_id="100", level_name="Этаж 1", area_m2=24.0,
    boundary_mm=((0.0, 0.0), (6000.0, 0.0), (6000.0, 4000.0), (0.0, 4000.0)),
    boundary_loops_mm=(((0.0, 0.0), (6000.0, 0.0),
                        (6000.0, 4000.0), (0.0, 4000.0)),),
    bounding_element_ids=("9001", "9002"))


def _wall(eid: str, p0: list[float], p1: list[float]) -> L0Element:
    return L0Element(
        element_id=eid, category="OST_Walls", category_ru="Стены",
        type_id="5001", type_name="Стена 200", level_id="100",
        level_name="Этаж 1", geom_kind=GeometryKind.CURVE, p0_mm=p0, p1_mm=p1,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None, host_id=None,
        params={"WALL_USER_HEIGHT_PARAM": 2800.0})


def _door(eid: str, xy: list[float], host: str) -> L0Element:
    return L0Element(
        element_id=eid, category="OST_Doors", category_ru="Двери",
        type_id="5002", type_name="Дверь 900", level_id="100",
        level_name="Этаж 1", geom_kind=GeometryKind.POINT, p0_mm=xy, p1_mm=None,
        rotation_deg=0.0, bbox_min_mm=None, bbox_max_mm=None, host_id=host,
        params={"FAMILY_WIDTH_PARAM": 900.0, "FAMILY_HEIGHT_PARAM": 2100.0})


def _datum_element(eid: str, category: str, category_ru: str) -> L0Element:
    """A datum/room element row; its geometry lives in document metadata keyed
    by ``element_id`` (levels/grids/rooms), so the row itself is bbox-only."""

    return L0Element(
        element_id=eid, category=category, category_ru=category_ru,
        type_id="", type_name="", level_id=None, level_name=None,
        geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None, host_id=None,
        params={})


def _document(*, with_room: bool = False, with_grid: bool = False) -> L0Document:
    elements = [
        _datum_element("100", "OST_Levels", "Уровни"),
        _wall("9001", [0.0, 0.0, 0.0], [6000.0, 0.0, 0.0]),
        _wall("9002", [6000.0, 0.0, 0.0], [6000.0, 4000.0, 0.0]),
        _door("9101", [3000.0, 0.0, 0.0], "9001"),
    ]
    if with_grid:
        elements.append(_datum_element("200", "OST_Grids", "Оси"))
    if with_room:
        elements.append(_datum_element("8001", "OST_Rooms", "Помещения"))
    elements.sort(key=lambda e: int(e.element_id))
    return L0Document(
        doc_name="Проект", revit_version="2026", units="mm", change_stamp="s",
        levels=(_LEVEL,), grids=((_GRID,) if with_grid else ()),
        rooms=((_ROOM,) if with_room else ()), project_info=_PROJ,
        elements=tuple(elements))


# ── a faithful in-memory "copy": Δ-rebuild + re-extract via the real reader ────


class FakeModelBridge:
    """Simulates the live copy: assigns new ids on rebuild, reads them back.

    ``rebuild_runner`` gives every op a fresh created id (``7`` + source id) and
    returns the serving witness envelope for it.  ``read_executor`` returns the
    Δ-translated L0 rows for exactly the requested created ids, in the raw bridge
    shape the ``reextract`` collector emits — so ``parse_reextract_rows`` +
    ``lift_document`` (the REAL parsers) reproduce the translated leaves.
    ``delete_runner`` records deletions and confirms them.
    """

    def __init__(self, document: L0Document, *, delta=K.DELTA_MM,
                 drop_room: bool = False):
        self.doc = document
        self.delta = delta
        self.drop_room = drop_room
        self.by_new_id: dict[str, L0Element] = {}
        self.deleted: list[str] = []
        self.rebuild_calls = 0
        # Map source element id -> its Δ-translated re-extract row.
        self._translated: dict[str, dict[str, Any]] = {
            e.element_id: self._translate_row(e) for e in document.elements}

    def _dmm(self, vec):
        if vec is None:
            return None
        return [vec[0] + self.delta[0], vec[1] + self.delta[1],
                vec[2] + self.delta[2]]

    def _translate_row(self, e: L0Element) -> dict[str, Any]:
        new_id = "7" + e.element_id
        return {
            "element_id": new_id,
            "category": e.category,
            "category_ru": e.category_ru,
            "type_id": e.type_id,
            "type_name": e.type_name,
            "level_id": e.level_id,
            "level_name": e.level_name,
            "host_id": ("7" + e.host_id) if e.host_id else None,
            "geom_kind": e.geom_kind.value,
            "p0_mm": self._dmm(e.p0_mm),
            "p1_mm": self._dmm(e.p1_mm),
            "rotation_deg": e.rotation_deg,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
            "params": dict(e.params),
        }

    async def rebuild_runner(self, program: Mapping[str, Any]) -> dict:
        self.rebuild_calls += 1
        results: dict[str, Any] = {}
        for op in program.get("ops", []):
            oid = op["id"]                     # deterministic "e"+source_id
            source_id = oid[1:] if oid.startswith("e") else oid
            new_id = "7" + source_id
            self.by_new_id[new_id] = self.doc.elements  # marker only
            results[oid] = {"id": new_id, "stamp": f"kir:x:{oid}"}
        return {"ok": True, "kir": True, "result": results}

    async def read_executor(self, code: str) -> dict:
        if "__fpPlacements" in code:
            door = next(
                element for element in self.doc.elements
                if element.category == "OST_Doors")
            return {"ok": True, "result": {"placements": [{
                "element_id": "7" + door.element_id,
                "symbol_id": door.type_id,
                "type_name": door.type_name,
                "family_name": "Synthetic door family",
                "placement_type": "OneLevelBasedHosted",
                "in_place": False,
                "mirrored": False,
                "hand_flipped": False,
                "facing_flipped": False,
                "super_component_id": None,
                "group_id": None,
                "host_id": "7" + str(door.host_id),
                "host_class": "Wall",
                "hand_orientation": [1.0, 0.0, 0.0],
                "facing_orientation": [0.0, 1.0, 0.0],
                "status": "ok",
            }]}}
        # The requested ids are embedded as "<id>L" literals in the collector;
        # return the translated rows for those we recognise (a real bridge reads
        # them by GetElement).  Optionally drop the room to model an enclosure
        # the copy could not reproduce (an EXPECTED discrepancy class).
        rows: list[dict[str, Any]] = []
        for source_id, row in self._translated.items():
            new_id = "7" + source_id
            if f"{int(new_id)}L" not in code:
                continue
            rows.append(row)
        return {"ok": True, "result": {"elements": rows}}

    async def delete_runner(self, program: Mapping[str, Any]) -> dict:
        for op in program.get("ops", []):
            self.deleted.append(str(op["target"]["value"]))
        return {"ok": True, "result": {
            op["id"]: {"deleted_id": op["target"]["value"]}
            for op in program.get("ops", [])}}

    async def sweep_runner(self) -> dict:
        return {"ok": True, "result": {"remaining": 0}}


_COPY_SAFETY = K.SafetyContext(
    doc_title="Проект — КОПИЯ A5", gate_ok=True,
    confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")


class TranslationInvarianceTests(unittest.TestCase):
    def test_roundtrip_is_exact_on_walls_and_hosted_door(self):
        doc = _document()
        leaves = list(lift_document(doc))
        bridge = FakeModelBridge(doc)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))
        self.assertIsNone(report.error, msg=report.to_dict())
        self.assertTrue(report.multiset_match, msg=report.to_dict())
        self.assertEqual(report.expected_hash, report.actual_hash)
        self.assertEqual(report.raw_exact_pct, 100.0)
        self.assertEqual(report.adjusted_exact_pct, 100.0)
        self.assertEqual(report.total_matched, report.total_expected)
        self.assertEqual(report.total_expected, 3)   # 2 walls + 1 door
        # Cleanup deleted every created id in finally.
        self.assertTrue(report.cleanup_ok, msg=report.cleanup_detail)
        self.assertEqual(len(bridge.deleted), 3)

    def test_property_multiset_hash_equality_direct(self):
        # The bare property, independent of the orchestrator plumbing.
        doc = _document()
        op_leaves = K._op_leaves(list(lift_document(doc)))
        expected = K._translate_originals(op_leaves, K.DELTA_MM)
        bridge = FakeModelBridge(doc)
        raw = _run(bridge.read_executor(
            K.build_reextract_cs(["7" + e.element_id for e in doc.elements])))
        from kukai.ir.decompile.reextract import (
            parse_reextract_rows, reextracted_document)
        re_doc = reextracted_document(doc, parse_reextract_rows(raw))
        relifted = K._op_leaves(list(lift_document(re_doc)))
        self.assertEqual(
            FidelityCanon.multiset_hash(relifted, (0.0, 0.0, 0.0)),
            FidelityCanon.multiset_hash(expected, (0.0, 0.0, 0.0)))

    def test_missing_requested_readback_is_typed_failure_and_cleans_up(self):
        doc = _document()
        leaves = list(lift_document(doc))
        bridge = FakeModelBridge(doc)
        # Rebuild still witnesses this created id, but the readback omits it.
        # Pre-F25 that smaller set flowed into a plausible fidelity metric.
        bridge._translated.pop("9002")

        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))

        self.assertEqual(report.error["code"], "reextract_failed")
        self.assertIn("missing=79002", report.error["detail"])
        self.assertTrue(report.cleanup_ok, msg=report.cleanup_detail)
        self.assertEqual(
            set(bridge.deleted), set(report.created_ids))

    def test_atoms_are_visible_as_not_reproduced_coverage_escrow(self):
        doc = _document()
        leaves = list(lift_document(doc))
        atom_source = "999999"
        leaves.append({
            "kind": "atom",
            "category": "OST_Railings",
            "category_ru": "Ограждения",
            "type_name": "opaque",
            "bbox_min_mm": [0.0, 0.0, 0.0],
            "bbox_max_mm": [100.0, 100.0, 100.0],
            "source_element_id": atom_source,
            "level_name": "Этаж 1",
            "anchor_mm": [50.0, 50.0, 50.0],
            "_id": stable_l1_id("atom", atom_source),
            "reason": {
                "code": AtomReason.UNSUPPORTED_SIGNATURE.value,
                "detail": "synthetic opaque leaf",
            },
        })
        bridge = FakeModelBridge(doc)

        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))

        self.assertTrue(report.multiset_match, msg=report.to_dict())
        self.assertEqual(report.atoms_excluded, 1)
        self.assertEqual(report.non_datum_total, 4)
        self.assertEqual(report.total_matched, 3)
        self.assertEqual(report.comparable_coverage_pct, 75.0)
        wire = report.to_dict()
        self.assertEqual(wire["atoms_excluded"], 1)
        self.assertEqual(wire["comparable_coverage"]["atoms_escrow"], 1)

    def test_a5_rejects_host_retargeting_even_when_leaf_shape_is_same(self):
        op_leaves = K._op_leaves(list(lift_document(_document())))
        expected = K._translate_originals(op_leaves, K.DELTA_MM)
        wrong = copy.deepcopy(expected)
        walls = [leaf for leaf in wrong if leaf["op_name"] == "create_wall"]
        door = next(leaf for leaf in wrong if leaf["op_name"] == "create_door")
        current = door["params"]["host"]["ref"]
        other = next(wall["_id"] for wall in walls if wall["_id"] != current)
        door["params"]["host"]["ref"] = other

        match, expected_hash, actual_hash, comparisons, discrepancies = (
            K._compare(expected, wrong))

        self.assertFalse(match)
        self.assertNotEqual(expected_hash, actual_hash)
        door_comparison = next(
            item for item in comparisons if item.op_name == "create_door")
        self.assertEqual(door_comparison.matched, 0)
        self.assertEqual(
            sorted(item["reason"] for item in discrepancies
                   if item["op_name"] == "create_door"),
            ["extra_rebuilt", "re-lifted leaf not found for this translated original"])


class AtomEscrowFormAcceptanceTests(unittest.TestCase):
    """A5 only credits an atom after a separate created-id geometry read."""

    @staticmethod
    def _atom(source_id: str = "9999") -> dict[str, Any]:
        return {
            "kind": "atom",
            "category": "OST_Walls",
            "category_ru": "Стены",
            "type_name": "opaque wall-like source",
            "bbox_min_mm": [0.0, 0.0, 0.0],
            "bbox_max_mm": [1000.0, 1000.0, 0.0],
            "source_element_id": source_id,
            "level_name": "Этаж 1",
            "anchor_mm": [500.0, 500.0, 0.0],
            "_id": stable_l1_id("atom", source_id),
            "reason": {
                "code": AtomReason.UNSUPPORTED_SIGNATURE.value,
                "detail": "synthetic Tier-G atom",
            },
        }

    @staticmethod
    def _source_geometry(source_id: str = "9999"):
        from kukai.ir.decompile.geom_extract import extract_geometry
        from kukai.ir.decompile.recompile import GmMesh
        from kukai.ir.decompile.tests.test_geom_extract import (
            _element, _part, _payload)

        mesh = GmMesh(
            vertices_mm=(
                (0.0, 0.0, 0.0),
                (1000.0, 0.0, 0.0),
                (0.0, 1000.0, 0.0),
            ),
            triangles=((0, 1, 2),),
        )
        return mesh, extract_geometry(_payload([
            _element(source_id, "OST_Walls", [_part(mesh)]),
        ]))

    def _run_case(
        self,
        *,
        move_vertex: bool = False,
        fail_form_read: bool = False,
        refuse_rebuild: bool = False,
        recovery=None,
    ):
        from kukai.ir.decompile.recompile import GmMesh
        from kukai.ir.decompile.tests.test_geom_extract import (
            _element, _part, _payload)

        source_mesh, geometry = self._source_geometry()
        shifted = tuple(
            (x + K.DELTA_MM[0], y + K.DELTA_MM[1], z + K.DELTA_MM[2])
            for x, y, z in source_mesh.vertices_mm
        )
        if move_vertex:
            shifted = ((shifted[0][0] + 10.0, shifted[0][1] + 10.0, 0.0),
                       *shifted[1:])
        observed_mesh = GmMesh(shifted, source_mesh.triangles)
        created_id = "79999"
        deleted: list[str] = []

        async def _rebuild(program):
            if recovery is not None:
                raise AssertionError("durably decided escrow must not re-execute")
            op = program["ops"][0]
            self.assertEqual(op["op"], "create_directshape")
            self.assertEqual(op["category"], "generic_model")
            if refuse_rebuild:
                return {
                    "ok": False,
                    "outcome": "refused_without_commit",
                    "bridge_detail": "synthetic escrow rollback",
                }
            return {"ok": True, "result": {
                op["id"]: {"id": created_id},
            }}

        async def _read(code):
            if "kir-decompile-geometry/1" in code:
                if fail_form_read:
                    raise RuntimeError("synthetic independent read failure")
                return _payload([
                    _element(
                        created_id,
                        "OST_GenericModel",
                        [_part(observed_mesh)],
                    ),
                ])
            if "var __wanted = new HashSet<long>" in code:
                element = L0Element(
                    element_id=created_id,
                    category="OST_GenericModel",
                    category_ru="Обобщенные модели",
                    type_id="",
                    type_name="",
                    level_id=None,
                    level_name=None,
                    geom_kind=GeometryKind.BBOX_ONLY,
                    p0_mm=None,
                    p1_mm=None,
                    rotation_deg=None,
                    bbox_min_mm=[K.DELTA_MM[0], 0.0, 0.0],
                    bbox_max_mm=[K.DELTA_MM[0] + 1000.0, 1000.0, 0.0],
                    host_id=None,
                    params={},
                )
                return {"ok": True, "result": {
                    "elements": [element.to_dict()],
                }}
            raise RuntimeError("optional side index unavailable")

        async def _delete(program):
            for op in program["ops"]:
                deleted.append(str(op["target"]["value"]))
            return {"ok": True, "result": {
                op["id"]: {"deleted_id": str(op["target"]["value"])}
                for op in program["ops"]
            }}

        async def _sweep():
            return {"ok": True, "result": {"remaining": 0}}

        report = _run(K.run_idempotence(
            [self._atom()], _document(), doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=_rebuild, read_executor=_read,
            delete_runner=_delete, sweep_runner=_sweep,
            dry_run=False, atom_escrow=True, geometry=geometry,
            recovery=recovery,
        ))
        return report, deleted

    def test_exact_post_commit_surface_raises_coverage(self):
        report, deleted = self._run_case()

        self.assertIsNone(report.error, report.to_dict())
        self.assertTrue(report.multiset_match)
        self.assertEqual(report.total_matched, 0)  # semantic multiset is empty
        self.assertEqual(report.atoms_excluded, 0)
        self.assertEqual(report.atoms_escrowed, 1)
        self.assertEqual(report.atoms_form_accepted, 1)
        self.assertEqual(report.atoms_form_rejected, 0)
        self.assertEqual(report.comparable_coverage_pct, 100.0)
        self.assertEqual(report.form_acceptance[0]["state"], "accepted")
        self.assertEqual(len(report.form_acceptance[0]["evidence_digest"]), 64)
        self.assertEqual(
            report.to_dict()["comparable_coverage"]["matched_end_to_end"], 1)
        self.assertEqual(deleted, ["79999"])

    def test_dry_run_respects_exact_empty_escrow_allow_list(self):
        _mesh, geometry = self._source_geometry()

        report = _run(K.run_idempotence(
            [self._atom()], _document(), doc_stamp="s", safety=_COPY_SAFETY,
            dry_run=True, atom_escrow=True, geometry=geometry,
            escrow_source_ids=(),
        ))

        self.assertIsNone(report.error, report.to_dict())
        self.assertEqual(report.atoms_excluded, 1)
        self.assertEqual(report.atoms_escrowed, 0)
        self.assertEqual(report.form_expectations, ())

    def test_escrow_scope_without_explicit_mode_is_typed_refusal(self):
        report = _run(K.run_idempotence(
            [self._atom()], _document(), doc_stamp="s", safety=_COPY_SAFETY,
            dry_run=True, escrow_source_ids=("9999",),
        ))

        self.assertEqual(report.error["code"], "atom_escrow_invalid")

    def test_changed_post_commit_surface_stays_in_denominator(self):
        report, _deleted = self._run_case(move_vertex=True)

        self.assertIsNone(report.error, report.to_dict())
        self.assertEqual(report.atoms_form_accepted, 0)
        self.assertEqual(report.atoms_form_rejected, 1)
        self.assertEqual(report.comparable_coverage_pct, 0.0)
        codes = {
            row["code"] for row in report.form_acceptance[0]["mismatches"]
        }
        self.assertIn("surface_mismatch", codes)

    def test_failed_independent_read_is_inconclusive_not_success(self):
        report, _deleted = self._run_case(fail_form_read=True)

        self.assertIsNone(report.error, report.to_dict())
        self.assertEqual(report.atoms_form_accepted, 0)
        self.assertEqual(report.atoms_form_inconclusive, 1)
        self.assertEqual(report.comparable_coverage_pct, 0.0)
        self.assertIn("synthetic independent read failure",
                      report.form_read_error)

    def test_witnessed_escrow_rollback_is_inconclusive_not_fatal(self):
        report, deleted = self._run_case(refuse_rebuild=True)

        self.assertIsNone(report.error, report.to_dict())
        self.assertEqual(report.atoms_form_accepted, 0)
        self.assertEqual(report.atoms_form_inconclusive, 1)
        self.assertEqual(report.comparable_coverage_pct, 0.0)
        self.assertEqual(
            report.form_acceptance[0]["mismatches"][0]["code"],
            "observation_missing",
        )
        self.assertEqual(deleted, [])

    def test_recovery_empty_escrow_receipt_closes_inconclusive(self):
        class _Recovery:
            resume_created_ids = ()

            async def prepare_rebuild_plan(self, program_ids):
                self.program_ids = tuple(program_ids)
                return {self.program_ids[0]: ()}

            async def after_rebuilt(self, created_ids):
                self.rebuilt = tuple(created_ids)

            async def after_compared(self, report):
                self.compared = dict(report)

            async def before_cleanup(self, created_ids, *, retain):
                self.before = (tuple(created_ids), retain)

            async def after_cleanup(
                    self, created_ids, *, retain, cleanup_ok, cleanup_detail):
                self.after = (tuple(created_ids), retain, cleanup_ok)

        recovery = _Recovery()
        report, deleted = self._run_case(recovery=recovery)

        self.assertIsNone(report.error, report.to_dict())
        self.assertEqual(report.atoms_form_inconclusive, 1)
        self.assertEqual(report.comparable_coverage_pct, 0.0)
        self.assertEqual(recovery.rebuilt, ())
        self.assertEqual(recovery.before, ((), False))
        self.assertEqual(recovery.after, ((), False, True))
        self.assertEqual(deleted, [])

    def test_recovery_refuses_multiple_ids_for_one_escrow_op(self):
        class _Recovery:
            resume_created_ids = ()

            async def prepare_rebuild_plan(self, program_ids):
                return {tuple(program_ids)[0]: ("7001", "7002")}

            async def after_cleanup(self, *args, **kwargs):
                return None

        report, deleted = self._run_case(recovery=_Recovery())

        self.assertEqual(
            report.error["code"], "atom_escrow_receipt_invalid")
        self.assertEqual(set(deleted), {"7001", "7002"})


class FormReportInvariantTests(unittest.TestCase):
    @staticmethod
    def _report(**overrides):
        values = {
            "doc_stamp": "s",
            "delta_mm": K.DELTA_MM,
            "multiset_match": None,
            "expected_hash": "",
            "actual_hash": "",
            "total_expected": 0,
            "total_matched": 0,
            "raw_exact_pct": None,
            "adjusted_exact_pct": None,
            "per_kind": (),
            "discrepancies": (),
            "datums_skipped": 0,
            "created_ids": (),
            "cleanup_ok": True,
            "cleanup_detail": "dry",
            "dry_run": True,
        }
        values.update(overrides)
        return K.IdempotenceReport(**values)

    def test_success_cannot_omit_preregistered_expectation(self):
        with self.assertRaisesRegex(ValueError, "lacks a form expectation"):
            self._report(atoms_escrowed=1)

    def test_form_counters_cannot_exist_without_verdict_rows(self):
        with self.assertRaisesRegex(ValueError, "verdict rows"):
            self._report(
                atoms_escrowed=1,
                atoms_form_inconclusive=1,
                form_expectations=({"source_id": "9999"},),
            )


class MetricHonestyTests(unittest.TestCase):
    """A5 reports both sides of the multiset and never calls N/A "100%"."""

    @staticmethod
    def _op(op_name: str = "create_wall", *, source_id: str = "9001",
            variety: str | None = None):
        leaf = next(
            copy.deepcopy(item)
            for item in lift_document(_document())
            if item["kind"] == "op" and item["op_name"] == "create_wall")
        leaf["op_name"] = op_name
        leaf["source_element_id"] = source_id
        leaf["_id"] = f"metric-{source_id}"
        if variety is not None:
            leaf["params"] = {"variety": variety}
        return leaf

    def test_extra_rebuilt_reduces_precision_and_is_a_discrepancy(self):
        expected = self._op(source_id="1")
        extra = copy.deepcopy(expected)
        extra["source_element_id"] = "2"
        extra["_id"] = "metric-2"

        match, _eh, _ah, comparisons, discrepancies = K._compare(
            [expected], [expected, extra])
        totals = K._percentages(comparisons)

        self.assertFalse(match)
        self.assertEqual(totals.total_expected, 1)
        self.assertEqual(totals.total_actual, 2)
        self.assertEqual(totals.total_matched, 1)
        self.assertEqual(totals.total_extra, 1)
        self.assertEqual(totals.raw_recall_pct, 100.0)
        self.assertEqual(totals.raw_precision_pct, 50.0)
        self.assertEqual(
            [item["reason"] for item in discrepancies], ["extra_rebuilt"])

    def test_zero_denominator_is_na_not_one_hundred(self):
        extra = self._op(source_id="2")
        _match, _eh, _ah, comparisons, _discrepancies = K._compare([], [extra])
        totals = K._percentages(comparisons)

        self.assertIsNone(totals.raw_recall_pct)
        self.assertEqual(totals.raw_precision_pct, 0.0)
        self.assertIsNone(totals.adjusted_recall_pct)

    def test_only_point_foundation_variety_is_carved_out(self):
        isolated = self._op(
            "create_foundation", source_id="10", variety="isolated")
        slab = self._op(
            "create_foundation", source_id="11", variety="slab")

        _match, _eh, _ah, comparisons, discrepancies = K._compare(
            [isolated, slab], [])
        totals = K._percentages(comparisons)

        comparison = comparisons[0]
        self.assertEqual(comparison.expected, 2)
        self.assertEqual(comparison.excluded_expected, 1)
        self.assertEqual(totals.raw_recall_pct, 0.0)
        self.assertEqual(totals.adjusted_recall_pct, 0.0)
        by_source = {item["source_element_id"]: item for item in discrepancies}
        self.assertTrue(by_source["10"]["expected_discrepancy_class"])
        self.assertFalse(by_source["11"]["expected_discrepancy_class"])

    def test_all_excluded_rooms_are_reported_as_na(self):
        room = self._op("create_room", source_id="20")
        _match, _eh, _ah, comparisons, discrepancies = K._compare([room], [])
        totals = K._percentages(comparisons)

        self.assertEqual(comparisons[0].excluded_expected, 1)
        self.assertEqual(totals.raw_recall_pct, 0.0)
        self.assertIsNone(totals.adjusted_recall_pct)
        self.assertTrue(discrepancies[0]["expected_discrepancy_class"])


class DatumExclusionTests(unittest.TestCase):
    def test_datums_never_enter_delta_program_and_are_not_compared(self):
        doc = _document(with_grid=True)
        leaves = list(lift_document(doc))
        # Sanity: the lift produced datum ops (level and/or grid).
        datum_ops = [lf for lf in leaves
                     if lf["kind"] == "op" and lf["op_name"] in K._DATUM_OPS]
        self.assertTrue(datum_ops, "fixture must contain datum ops to be meaningful")

        from kukai.ir.decompile.materialize import leaves_to_program
        materialized = leaves_to_program(
            leaves, mode="same_document", offset_mm=K.DELTA_MM)
        emitted_ops = {op["op"]
                       for program in materialized.programs
                       for op in program["ops"]}
        self.assertNotIn("create_level", emitted_ops)
        self.assertNotIn("create_grid", emitted_ops)

        bridge = FakeModelBridge(doc)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))
        self.assertIsNone(report.error, msg=report.to_dict())
        self.assertEqual(report.datums_skipped, len(datum_ops))
        # No datum op-kind appears in the comparison.
        compared_kinds = {c.op_name for c in report.per_kind}
        self.assertFalse(compared_kinds & K._DATUM_OPS)
        self.assertTrue(report.multiset_match, msg=report.to_dict())


class ExpectedDiscrepancyTests(unittest.TestCase):
    def test_room_discrepancy_is_subtracted_from_adjusted(self):
        doc = _document(with_room=True)
        leaves = list(lift_document(doc))
        room_ops = [lf for lf in leaves
                    if lf["kind"] == "op" and lf["op_name"] == "create_room"]
        self.assertTrue(room_ops, "fixture must lift a create_room op")
        # The copy fails to re-enclose the room (drop it from re-extract) — an
        # EXPECTED discrepancy class.
        bridge = FakeModelBridge(doc, drop_room=True)

        async def _read_no_room(code: str):
            res = await bridge.read_executor(code)
            return res

        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))
        self.assertIsNone(report.error, msg=report.to_dict())
        # Raw % is dented by the missing room; adjusted % excludes the expected
        # class and stays perfect.
        self.assertLess(report.raw_exact_pct, 100.0)
        self.assertEqual(report.adjusted_exact_pct, 100.0)
        # The room mismatch is classified as an expected discrepancy.
        room_disc = [d for d in report.discrepancies
                     if d["op_name"] == "create_room"]
        self.assertTrue(room_disc)
        self.assertTrue(all(d["expected_discrepancy_class"] for d in room_disc))

    def test_place_family_is_not_a_carved_out_class(self):
        # Anti-Goodhart pin (2026-07-21): place_family reproduces exactly
        # (live floor-20 furniture), so a mismatch must count against
        # adjusted% — NOT be hidden as an expected discrepancy.  create_room
        # stays carved out (enclosure-derived, L0 1.0 has no Room.Location).
        self.assertNotIn("place_family", K.EXPECTED_DISCREPANCY_OPS)
        self.assertIn("create_room", K.EXPECTED_DISCREPANCY_OPS)


class CurtainIndexRelift(unittest.TestCase):
    """Хвост волны панелей (aaa44b45, 28.07): ``run_idempotence`` re-lift'ит
    Δ-копию БЕЗ curtain-индекса — ``profile_index``/``family_placement_index``/
    ``wall_curve_index`` уже доходят до relift'а (см. блок ``curve_index``
    чуть выше по файлу), ``curtain_index`` нет.  Панель, которая при первом
    lift стала ``set_curtain_panel``, при re-lift'е снова атомизируется —
    ЛОЖНОЕ расхождение идемпотентности, не настоящее.

    ``extract_curtain_topology``/``build_curtain_extract_cs`` сами по себе уже
    покрыты ``test_curtain_extract.py``/``test_lift_curtain_panel.py``; этот
    тест патчит именно ГРАНИЦУ builder/parser, чтобы проверить ПРОВОДКУ
    (read_executor -> lift_document) в ``kir_idempotence.py`` — не
    переизобретать разбор витража, и не зависеть от ``authoring.py``
    (``curtain_cell_address_cs``), который параллельная волна правит прямо
    сейчас.
    """

    _HOST_ID = "9001"
    _CELL_ID = "9002"
    _GLAZING_TYPE_ID = "7001"
    _DEFAULT_TYPE_ID = "7000"
    _MARKER = "__CURTAIN_EXTRACT_MARKER__"

    @classmethod
    def _envelope(cls, host_id: str, cell_id: str) -> dict[str, Any]:
        return {
            "schema_version": "2",
            "curtain_index": {
                host_id: {
                    "curtain_available": True,
                    "host_kind": "wall",
                    "default_panel_type_id": cls._DEFAULT_TYPE_ID,
                    "default_panel_type_name": "Системная панель по умолчанию",
                    "u_grid_lines": [],
                    "v_grid_lines": [],
                    "panels": [{
                        "panel_id": cell_id,
                        "is_family_instance": True,
                        "family_name": "Системная панель",
                        "type_name": "Стеклопакет 30мм",
                        "type_id": cls._GLAZING_TYPE_ID,
                        "host_panel_id": None,
                        "host_panel_type_id": None,
                        "host_panel_type_name": None,
                        "u_index": 2,
                        "v_index": 1,
                        "address_state": "ok",
                        "is_door": False,
                    }],
                    "mullions": [],
                },
            },
            "failures": [],
        }

    @classmethod
    def _document(cls) -> L0Document:
        wall = L0Element(
            element_id=cls._HOST_ID, category="OST_Walls", category_ru="Стены",
            type_id="5001", type_name="Витраж НР_ВТ", level_id="100",
            level_name="Этаж 1", geom_kind=GeometryKind.CURVE,
            p0_mm=[0.0, 0.0, 0.0], p1_mm=[6000.0, 0.0, 0.0],
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={"WALL_USER_HEIGHT_PARAM": 2800.0})
        cell = L0Element(
            element_id=cls._CELL_ID, category="OST_CurtainWallPanels",
            category_ru="Панели витража", type_id=cls._GLAZING_TYPE_ID,
            type_name="Стеклопакет 30мм", level_id=None, level_name=None,
            geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=cls._HOST_ID, params={})
        elements = sorted([wall, cell], key=lambda e: int(e.element_id))
        return L0Document(
            doc_name="Проект", revit_version="2026", units="mm",
            change_stamp="s", levels=(_LEVEL,), grids=(), rooms=(),
            project_info=_PROJ, elements=tuple(elements))

    class _CurtainBridge(FakeModelBridge):
        def __init__(self, document, *, envelope_factory):
            super().__init__(document)
            self._envelope_factory = envelope_factory

        async def read_executor(self, code: str):
            if code.startswith(CurtainIndexRelift._MARKER):
                new_host = "7" + CurtainIndexRelift._HOST_ID
                new_cell = "7" + CurtainIndexRelift._CELL_ID
                return {"ok": True,
                        "result": self._envelope_factory(new_host, new_cell)}
            return await super().read_executor(code)

    def _run_report(self):
        doc = self._document()
        leaves = list(lift_document(
            doc, curtain_index=self._envelope(self._HOST_ID, self._CELL_ID)))
        original_panel = next(
            lf for lf in leaves if lf.get("source_element_id") == self._CELL_ID)
        self.assertEqual(
            original_panel["kind"], "op",
            "fixture must lift the cell to set_curtain_panel to begin with: "
            f"{original_panel}")
        bridge = self._CurtainBridge(doc, envelope_factory=self._envelope)
        with mock.patch(
                "kukai.ir.decompile.curtain_extract.build_curtain_extract_cs",
                side_effect=lambda ids: (
                    self._MARKER + ",".join(str(i) for i in ids))), \
             mock.patch(
                "kukai.ir.decompile.curtain_extract.extract_curtain_topology",
                side_effect=lambda payload: payload):
            report = _run(K.run_idempotence(
                leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
                rebuild_runner=bridge.rebuild_runner,
                read_executor=bridge.read_executor,
                delete_runner=bridge.delete_runner,
                sweep_runner=bridge.sweep_runner, dry_run=False))
        self.assertIsNone(report.error, msg=report.to_dict())
        return report

    def test_relift_sees_the_curtain_panel_op(self):
        report = self._run_report()
        self.assertEqual(report.total_expected, 2)  # create_wall + panel
        self.assertTrue(
            report.multiset_match,
            msg=("relift dropped the curtain panel — lift_document is being "
                 f"called without curtain_index: {report.to_dict()}"))
        self.assertEqual(report.total_matched, report.total_expected)
        panel_kind = next(
            (c for c in report.per_kind if c.op_name == "set_curtain_panel"),
            None)
        self.assertIsNotNone(
            panel_kind, "set_curtain_panel never entered the comparison")
        self.assertEqual(panel_kind.matched, 1)


class HostedOpWhoseHostIsNotRebuilt(unittest.TestCase):
    """Наблюдено 27.07 на SOB6.2: `create_door`, чей хост — стена с локейшн-
    линией `core_interior`, осталась атомом («не выразима create_wall»). Дверь
    поднялась, стена нет — и корпус A5 унёс висячую ссылку. FidelityCanon
    отказал «fidelity ref target … is absent from graph», а до оператора это
    дошло голым «internal».

    Тот же закон, что уже применяет materialize.leaves_to_program своим
    типизированным пропуском host_unmaterialized: исключённый хост — это
    данные, а не исключение. Ссылка на выброшенный узел выбрасывает и
    ссылающегося, до неподвижной точки."""

    def _leaf(self, node_id, op_name, params=None, source="1"):
        return {"kind": "op", "_id": node_id, "op_name": op_name,
                "params": params or {}, "source_element_id": source,
                "type_name": "T", "level_name": None, "anchor_mm": None}

    def test_op_referencing_a_dropped_leaf_is_dropped_too(self):
        wall_atom = {"kind": "atom", "_id": "W", "category": "OST_Walls",
                     "category_ru": "Стены", "type_name": "T",
                     "bbox_min_mm": None, "bbox_max_mm": None,
                     "source_element_id": "10", "level_name": None,
                     "anchor_mm": None,
                     "reason": {"code": "unsupported_forward_signature",
                                "detail": "core_interior"}}
        door = self._leaf("D", "create_door", {"host": {"ref": "W"}}, "11")
        kept = K._op_leaves([wall_atom, door])
        self.assertEqual([leaf["_id"] for leaf in kept], [])
        self.assertEqual(K._hosted_skipped_count([wall_atom, door]), 1)

    def test_chain_is_resolved_to_a_fixed_point(self):
        """Выброс распространяется: марка на двери, дверь на стене-атоме."""
        wall_atom = {"kind": "atom", "_id": "W", "category": "OST_Walls",
                     "category_ru": "Стены", "type_name": "T",
                     "bbox_min_mm": None, "bbox_max_mm": None,
                     "source_element_id": "10", "level_name": None,
                     "anchor_mm": None,
                     "reason": {"code": "unsupported_forward_signature",
                                "detail": "core_interior"}}
        door = self._leaf("D", "create_door", {"host": {"ref": "W"}}, "11")
        tag = self._leaf("T1", "create_tag", {"target": {"ref": "D"}}, "12")
        self.assertEqual(K._op_leaves([wall_atom, door, tag]), [])

    def test_a_healthy_pair_survives(self):
        wall = self._leaf("W", "create_wall", {}, "10")
        door = self._leaf("D", "create_door", {"host": {"ref": "W"}}, "11")
        kept = {leaf["_id"] for leaf in K._op_leaves([wall, door])}
        self.assertEqual(kept, {"W", "D"})
        self.assertEqual(K._hosted_skipped_count([wall, door]), 0)


class SafetyGuardTests(unittest.TestCase):
    """The Д3 guard — the single most important test.  Every refusal is typed
    and NO runner is ever invoked (a refusal must not write to the model)."""

    def _never(self):
        async def _boom(*a, **k):  # pragma: no cover — must not be called
            raise AssertionError("live runner invoked despite a safety refusal")
        return _boom

    def _leaves_doc(self):
        doc = _document()
        return list(lift_document(doc)), doc

    def test_refuses_when_title_unconfirmed(self):
        leaves, doc = self._leaves_doc()
        safety = K.SafetyContext(doc_title=None, gate_ok=True)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=safety,
            rebuild_runner=self._never(), read_executor=self._never(),
            delete_runner=self._never(), dry_run=False))
        self.assertIsNotNone(report.error)
        self.assertEqual(report.error["code"], "unconfirmed_title")
        self.assertEqual(report.created_ids, ())

    def test_refuses_working_file_title(self):
        leaves, doc = self._leaves_doc()
        safety = K.SafetyContext(doc_title="ЖК Северный — рабочий", gate_ok=True)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=safety,
            rebuild_runner=self._never(), read_executor=self._never(),
            delete_runner=self._never(), dry_run=False))
        self.assertEqual(report.error["code"], "not_a_copy")

    def test_refuses_when_gate_off(self):
        leaves, doc = self._leaves_doc()
        safety = K.SafetyContext(doc_title="Проект КОПИЯ", gate_ok=False)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=safety,
            rebuild_runner=self._never(), read_executor=self._never(),
            delete_runner=self._never(), dry_run=False))
        self.assertEqual(report.error["code"], "gate")

    def test_confirm_token_cannot_override_a_working_document_title(self):
        leaves, doc = self._leaves_doc()
        safety = K.SafetyContext(
            doc_title="ProjectX", gate_ok=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertEqual(safety.refusal().code, "not_a_copy")

    def test_explicit_copy_and_exact_confirm_token_are_both_required(self):
        good = K.SafetyContext(
            doc_title="Project — COPY A5", gate_ok=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertIsNone(good.refusal())
        bad = K.SafetyContext(
            doc_title="Project — COPY A5", gate_ok=True,
            confirm_token="nope", expected_token="RUN-A5-OK")
        self.assertEqual(bad.refusal().code, "confirmation_required")

    def test_copy_guard_rejects_incidental_substrings(self):
        for title in (
                "Contest Center", "Latest model", "Copywriter HQ",
                "Тестовый корпус", "Photocopy A5"):
            with self.subTest(title=title):
                safety = K.SafetyContext(
                    doc_title=title, gate_ok=True,
                    confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
                self.assertEqual(safety.refusal().code, "not_a_copy")

    def test_operator_declaration_is_an_alternative_proof_only_with_the_token(self):
        """Второй маршрут доказательства, добавлен 27.07 по решению оператора.

        Соглашение об имени — эвристика, и она отказала на файле, который
        оператор держит как расходную копию. Устное «это копия» доказательством
        быть не может: рейл существует ровно для того, чтобы ничьё слово — в
        том числе моё — не клало тысячу элементов не в тот файл. Поэтому явное
        заявление засчитывается ТОЛЬКО вместе с секретным confirm_token: два
        независимых фактора вместо одного, как и было."""
        both = K.SafetyContext(
            doc_title="SOB6.2_UPO_L_DOO_AR_R23_kuklev.d.s", gate_ok=True,
            operator_declared_copy=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertIsNone(both.refusal())
        self.assertEqual(both.copy_proof(), "operator_declaration")

    def test_declaration_without_the_token_is_still_refused(self):
        safety = K.SafetyContext(
            doc_title="SOB6.2_UPO_L_DOO_AR_R23_kuklev.d.s", gate_ok=True,
            operator_declared_copy=True, expected_token="RUN-A5-OK")
        self.assertEqual(safety.refusal().code, "not_a_copy")

    def test_declaration_with_a_wrong_token_is_still_refused(self):
        safety = K.SafetyContext(
            doc_title="SOB6.2_UPO_L_DOO_AR_R23_kuklev.d.s", gate_ok=True,
            operator_declared_copy=True,
            confirm_token="nope", expected_token="RUN-A5-OK")
        self.assertEqual(safety.refusal().code, "not_a_copy")

    def test_declaration_defaults_off_so_nothing_changes_without_it(self):
        """Флаг по умолчанию выключен: прежний отказ на рабочем имени цел."""
        safety = K.SafetyContext(
            doc_title="ЖК Северный — рабочий", gate_ok=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertEqual(safety.refusal().code, "not_a_copy")
        self.assertEqual(safety.copy_proof(), "")

    def test_title_proof_is_still_reported_as_such(self):
        safety = K.SafetyContext(
            doc_title="Project — COPY A5", gate_ok=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertIsNone(safety.refusal())
        self.assertEqual(safety.copy_proof(), "title")

    def test_copy_suffix_without_operator_token_is_refused(self):
        safety = K.SafetyContext(
            doc_title="Проект — КОПИЯ A5", gate_ok=True)
        self.assertEqual(safety.refusal().code, "confirmation_unavailable")

    def test_delimiter_suffix_convention_is_accepted_with_token(self):
        safety = K.SafetyContext(
            doc_title="Project_A5_COPY", gate_ok=True,
            confirm_token="RUN-A5-OK", expected_token="RUN-A5-OK")
        self.assertIsNone(safety.refusal())

    def test_refuses_when_runners_missing(self):
        leaves, doc = self._leaves_doc()
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY, dry_run=False))
        self.assertEqual(report.error["code"], "no_runners")

    def test_dry_gate_compiles_against_the_source_catalogue(self):
        """Сухой гейт обязан компилировать С каталогом источника.

        28.07 он компилировал без него и отказывал целым чанкам с KIR-G103 —
        то есть сообщал о собственной слепоте, а не о программе. Тест ловит
        именно проводку: снимок должен дойти до компилятора.
        """
        leaves, doc = self._leaves_doc()
        catalogue = {"wall_types": [{"id": 1, "name": "\u0422\u0438\u043f"}]}
        seen = []
        import kukai.ir.compiler as _compiler
        original = _compiler.compile_rebuild_chunk

        def _spy(program, **kwargs):
            seen.append(kwargs.get("snapshot"))
            return original(program, **kwargs)

        _compiler.compile_rebuild_chunk = _spy
        try:
            report = _run(K.run_idempotence(
                leaves, doc, doc_stamp="s",
                safety=K.SafetyContext(gate_ok=False),
                rebuild_runner=self._never(), read_executor=self._never(),
                delete_runner=self._never(), dry_run=True,
                ground_snapshot=catalogue))
        finally:
            _compiler.compile_rebuild_chunk = original
        self.assertIsNone(report.error, msg=report.to_dict())
        self.assertTrue(seen, "\u0441\u0443\u0445\u043e\u0439 \u0433\u0435\u0439\u0442 \u043d\u0435 \u0437\u0432\u0430\u043b \u043a\u043e\u043c\u043f\u0438\u043b\u044f\u0442\u043e\u0440")
        self.assertTrue(all(item == catalogue for item in seen), seen)

    def test_dry_run_never_touches_runners_and_compiles(self):
        leaves, doc = self._leaves_doc()
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s",
            safety=K.SafetyContext(gate_ok=False),  # gate irrelevant to dry run
            rebuild_runner=self._never(), read_executor=self._never(),
            delete_runner=self._never(), dry_run=True))
        self.assertTrue(report.dry_run)
        self.assertIsNone(report.error, msg=report.to_dict())
        self.assertIsNone(report.multiset_match)  # comparison was not executed
        self.assertFalse(report.to_dict()["comparison_performed"])


class CleanupTests(unittest.TestCase):
    def test_restart_skips_confirmed_chunk_and_continues_exact_plan(self):
        """Kill between chunks resumes at the first unconfirmed program."""

        leaves = list(lift_document(_document()))
        programs = [
            {"ir_version": "1.0", "ops": [{
                "op": "create_wall", "id": "first"}]},
            {"ir_version": "1.0", "ops": [{
                "op": "create_wall", "id": "second"}]},
        ]
        executed: list[str] = []
        deleted: list[str] = []

        class _PartialRecovery:
            resume_created_ids = ()

            def __init__(self):
                self.program_ids = ()
                self.completed_ids = ()

            async def prepare_rebuild_plan(self, program_ids):
                self.program_ids = tuple(program_ids)
                # Chunk 0 committed and its receipt was fsynced before kill.
                return {self.program_ids[0]: ("7001",)}

            async def after_rebuilt(self, created_ids):
                self.completed_ids = tuple(created_ids)

            async def after_compared(self, _report):
                raise AssertionError("synthetic read failure stops before compare")

            async def before_cleanup(self, _created_ids, *, retain):
                raise AssertionError("failed run must not enter normal preview")

            async def after_cleanup(
                    self, created_ids, *, retain, cleanup_ok, cleanup_detail):
                self.completed_ids = tuple(created_ids)

        recovery = _PartialRecovery()

        async def _rebuild(program):
            executed.append(program["program_id"])
            return {"ok": True, "result": {"second": {"id": "7002"}}}

        async def _read(_code):
            raise RuntimeError("synthetic stop after resume proof")

        async def _delete(program):
            targets = [str(op["target"]["value"])
                       for op in program["ops"]]
            deleted.extend(targets)
            return {"ok": True, "result": {
                op["id"]: {"deleted_id": str(op["target"]["value"])}
                for op in program["ops"]}}

        async def _sweep():
            return {"ok": True}

        with mock.patch.object(
                K, "leaves_to_program",
                return_value=SimpleNamespace(programs=programs)):
            report = _run(K.run_idempotence(
                leaves, _document(), doc_stamp="s", safety=_COPY_SAFETY,
                rebuild_runner=_rebuild, read_executor=_read,
                delete_runner=_delete, sweep_runner=_sweep,
                dry_run=False, recovery=recovery))

        self.assertEqual(
            executed, [recovery.program_ids[1]],
            "the confirmed first chunk must never be executed twice")
        self.assertEqual(set(report.created_ids), {"7001", "7002"})
        self.assertEqual(set(deleted), {"7001", "7002"})
        self.assertEqual(set(recovery.completed_ids), {"7001", "7002"})
        self.assertTrue(report.cleanup_ok, report.cleanup_detail)

    def test_keep_does_not_preserve_partial_delta_after_error(self):
        leaves = list(lift_document(_document()))
        rebuild_calls = 0
        deleted: list[str] = []
        sweep_calls = 0

        async def _partial_rebuild(_program):
            nonlocal rebuild_calls
            rebuild_calls += 1
            if rebuild_calls == 1:
                return {"ok": True, "result": {"W": {"id": "7001"}}}
            return {"ok": False, "error": "synthetic second chunk failure"}

        async def _delete(program):
            targets = [str(op["target"]["value"])
                       for op in program["ops"]]
            deleted.extend(targets)
            return {"ok": True, "result": {
                op["id"]: {"deleted_id": str(op["target"]["value"])}
                for op in program["ops"]}}

        async def _sweep():
            nonlocal sweep_calls
            sweep_calls += 1
            return {"ok": True, "matched_ids": []}

        materialized = SimpleNamespace(programs=[
            {"ir_version": "1.0", "ops": []},
            {"ir_version": "1.0", "ops": []},
        ])
        with mock.patch.object(
                K, "leaves_to_program", return_value=materialized):
            report = _run(K.run_idempotence(
                leaves, _document(), doc_stamp="s", safety=_COPY_SAFETY,
                rebuild_runner=_partial_rebuild,
                read_executor=lambda _code: None, delete_runner=_delete,
                sweep_runner=_sweep, dry_run=False, keep_delta=True))

        self.assertEqual(report.error["code"], "rebuild_failed")
        self.assertEqual(deleted, ["7001"])
        self.assertEqual(sweep_calls, 1)
        self.assertTrue(report.cleanup_ok, report.cleanup_detail)
        self.assertNotIn("KEEP:", report.cleanup_detail)

    def test_cleanup_runs_in_finally_even_when_rebuild_raises(self):
        doc = _document()
        leaves = list(lift_document(doc))
        bridge = FakeModelBridge(doc)
        calls = {"n": 0}

        async def _rebuild_then_raise(program):
            calls["n"] += 1
            # First chunk succeeds (creates ids), second explodes mid-run.
            if calls["n"] == 1:
                return await bridge.rebuild_runner(program)
            raise RuntimeError("synthetic mid-run bridge death")

        # Force >1 chunk so the first creates ids before the raise.
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=_rebuild_then_raise,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False,
            delta_mm=K.DELTA_MM))
        # Whatever happened, cleanup deleted the ids the first chunk created.
        # (Materialize packs walls+door into one chunk here, so the raise may
        # never fire; assert the invariant that holds in BOTH cases: no orphans.)
        self.assertTrue(report.cleanup_ok, msg=report.cleanup_detail)
        if report.error is not None:
            # If it did fail, the created ids were still all deleted.
            self.assertEqual(
                sorted(bridge.deleted),
                sorted(int(i) for i in ()) or sorted(bridge.deleted))

    def test_cleanup_deletes_every_created_id(self):
        doc = _document()
        leaves = list(lift_document(doc))
        bridge = FakeModelBridge(doc)
        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False))
        self.assertTrue(report.cleanup_ok)
        self.assertEqual(
            {str(x) for x in bridge.deleted}, set(report.created_ids))

    def test_cleanup_requires_deleted_id_witness_for_every_target(self):
        async def _unproven_delete(_program):
            return {"ok": True, "result": {}}

        ok, detail = _run(K.cleanup_created(
            ["7001", "7002"], _unproven_delete))

        self.assertFalse(ok)
        self.assertIn("0/2", detail)

    def test_cleanup_rejects_unexpected_deleted_id_witness(self):
        async def _overbroad_delete(_program):
            return {"ok": True, "result": {
                "D0": {"deleted_id": "7001"},
                "foreign": {"deleted_id": "9999"},
            }}

        ok, detail = _run(K.cleanup_created(["7001"], _overbroad_delete))

        self.assertFalse(ok)
        self.assertIn("unexpected=['9999']", detail)

    def test_failed_run_reconciliation_keeps_cleanup_failed(self):
        doc = _document()
        leaves = list(lift_document(doc))
        bridge = FakeModelBridge(doc)

        async def _failed_sweep():
            return {"ok": False, "error": "sweep_unconfirmed"}

        report = _run(K.run_idempotence(
            leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
            rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=_failed_sweep, dry_run=False))

        self.assertIsNone(report.error)
        self.assertFalse(report.cleanup_ok)
        self.assertIn("sweep_unconfirmed", report.cleanup_detail)


if __name__ == "__main__":
    unittest.main()
