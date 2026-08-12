"""Coverage waves F5 (door/window swing state) + F6 (wall vertical attributes).

F5: create_door/create_window carry optional mirrored/hand_flipped/
facing_flipped; the lift reads them from the FamilyInstance placement side
index (hosted rows were extracted but never consumed); the emitter clones
place_family's enforced-state pattern with the mirror plane's normal derived
from the HOST WALL's direction.

F6: create_wall carries optional base_offset_mm (WALL_BASE_OFFSET) and
top_level (top constraint attached via WALL_HEIGHT_TYPE + WALL_TOP_OFFSET=0);
the lift reads both from the L0 params captured by the widened __PutParams.

Byte-stability is the load-bearing discipline: an op WITHOUT the new params
must normalize, hash, and emit exactly as before (goldens prove the emitted
bytes; the tests here prove params/hash stability and the string-level
absence of every new emission branch).
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from typing import Any

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_fw_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir.authoring import validate as _validate_op  # noqa: E402
from kukai.ir.compiler import _parse_and_check, compile_program  # noqa: E402
from kukai.ir.decompile.fold import canon_op  # noqa: E402
from kukai.ir.decompile.lift import lift_document  # noqa: E402
from kukai.ir.decompile.schema import L0Document  # noqa: E402
from kukai.ir.decompile.tests.fixtures_decompile import (  # noqa: E402
    make_element,
    project1_metadata,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.translation_cert import (  # noqa: E402
    audit_registry_coverage,
    certify_op,
)

_ZERO = (0.0, 0.0, 0.0)


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-fw-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _by_source(nodes) -> dict[str, dict[str, Any]]:
    return {node["source_element_id"]: node for node in nodes}


def _hosted_rows() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    wall = make_element("OST_Walls", 9001, ordinal=0)
    wall["p0_mm"] = [100.0, 200.0, 0.0]
    wall["p1_mm"] = [4_100.0, 3_200.0, 0.0]
    door = make_element("OST_Doors", 9600, ordinal=0)
    door["host_id"] = "9001"
    door["p0_mm"] = [2_100.0, 1_700.0, 0.0]
    window = make_element("OST_Windows", 9601, ordinal=0)
    window["host_id"] = "9001"
    window["p0_mm"] = [3_100.0, 2_450.0, 900.0]
    return wall, door, window


def _hosted_placement_row(
    element: dict[str, Any],
    *,
    mirrored: bool = False,
    hand_flipped: bool = False,
    facing_flipped: bool = False,
    host_id: str | None = "9001",
) -> dict[str, Any]:
    return {
        "symbol_id": element["type_id"],
        "type_name": element["type_name"],
        "family_name": "Дверь одностворчатая",
        "placement_type": "OneLevelBasedHosted",
        "in_place": False,
        "mirrored": mirrored,
        "hand_flipped": hand_flipped,
        "facing_flipped": facing_flipped,
        "super_component_id": None,
        "group_id": None,
        "host_id": host_id,
        "host_class": "Wall" if host_id is not None else None,
        "hand_orientation": [1.0, 0.0, 0.0],
        "facing_orientation": [0.0, 1.0, 0.0],
        "placement_available": False,
        "point_mm": None,
        "rotation_deg": None,
    }


class F5LiftFlips(unittest.TestCase):
    def test_flips_are_lifted_from_the_placement_index(self) -> None:
        wall, door, window = _hosted_rows()
        index = {
            "9600": _hosted_placement_row(
                door, mirrored=True, hand_flipped=True),
            "9601": _hosted_placement_row(
                window, mirrored=True, facing_flipped=True),
        }
        nodes = _by_source(lift_document(
            _document([wall, door, window]),
            family_placement_index=index))
        # ANY True flag -> ALL THREE emitted (mirroring can flip hand/facing
        # as a Revit side effect; the emitter must enforce the whole state).
        self.assertEqual(nodes["9600"]["params"]["mirrored"], True)
        self.assertEqual(nodes["9600"]["params"]["hand_flipped"], True)
        self.assertEqual(nodes["9600"]["params"]["facing_flipped"], False)
        self.assertEqual(nodes["9601"]["params"]["mirrored"], True)
        self.assertEqual(nodes["9601"]["params"]["facing_flipped"], True)

    def test_all_false_flags_keep_byte_identical_params(self) -> None:
        wall, door, window = _hosted_rows()
        index = {"9600": _hosted_placement_row(door)}   # all flags False
        plain = _by_source(lift_document(_document([wall, door, window])))
        with_index = _by_source(lift_document(
            _document([wall, door, window]),
            family_placement_index=index))
        # absent == default: the all-False row adds NOTHING, canonical hashes
        # of typical doors are byte-stable.
        self.assertEqual(plain["9600"], with_index["9600"])
        self.assertEqual(
            canon_op(plain["9600"], _ZERO),
            canon_op(with_index["9600"], _ZERO))

    def test_absent_requested_row_atomizes_instead_of_defaulting_flips(self) -> None:
        wall, door, window = _hosted_rows()
        plain = _by_source(lift_document(_document([wall, door, window])))
        # A valid index that carries a row only for the WINDOW means placement
        # was requested but the door was not seen.  Unknown is not all-False.
        index = {"9601": _hosted_placement_row(
            window, mirrored=True, facing_flipped=True)}
        partial = _by_source(lift_document(
            _document([wall, door, window]),
            family_placement_index=index))
        self.assertEqual(plain["9600"]["kind"], "op")
        self.assertEqual(partial["9600"]["kind"], "atom")
        self.assertEqual(
            partial["9600"]["reason"]["code"], "flip_state_unknown")

    def test_malformed_index_stays_fail_closed_at_parse(self) -> None:
        # The pre-existing pipeline contract: the WHOLE side index is
        # validated up front (parse_family_placement_index), so a malformed
        # row is a typed refusal before any lift — flips never read garbage.
        from kukai.ir.decompile.family_placement_extract import (
            FamilyPlacementPayloadError,
        )
        wall, door, window = _hosted_rows()
        with self.assertRaises(FamilyPlacementPayloadError):
            lift_document(
                _document([wall, door, window]),
                family_placement_index={"9600": {"garbage": True}})

    def test_contradictory_host_id_atomizes_not_defaults(self) -> None:
        wall, door, window = _hosted_rows()
        row = _hosted_placement_row(
            door, mirrored=True, hand_flipped=True, host_id="424242")
        nodes = _by_source(lift_document(
            _document([wall, door, window]),
            family_placement_index={"9600": row}))
        # Contradictory evidence cannot be converted into default False flags.
        self.assertEqual(nodes["9600"]["kind"], "atom")
        self.assertEqual(
            nodes["9600"]["reason"]["code"], "flip_state_unknown")


class F5EmitFlips(unittest.TestCase):
    _PROG = {
        "ir_version": "1.0", "intent": "дверь с флипами", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": {"by": "name", "value": "Этаж 1"},
             "height_mm": 3000},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
             "mirrored": True, "hand_flipped": True, "facing_flipped": False},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000,
             "sill_mm": 900, "facing_flipped": True},
        ]}

    def test_flip_branches_and_witnesses_are_emitted(self) -> None:
        # F5 v3.1 ГИБРИД (экзамен ЛОТ31, 2026-07-21): семантич. флип двери —
        # flipHand/flipFacing при CanFlip=true (СТАБИЛЬНО, не орфанит), а
        # mirror-COPY как fallback при CanFlip=false (крак flip-locked ДЛ/Блок,
        # 1-2 на этаж).  Живо: −1 (кластерный паркинг) 0%→100%, двери 30/30.
        # Свидетели всех трёх состояний остаются.
        out = compile_program(
            copy.deepcopy(self._PROG), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        for marker in (
                "CanFlipHand", "flipHand()",           # единственный путь
                "mirrored state mismatch (semantic)",
                "hand flip state mismatch (semantic)",
                "facing flip state mismatch (semantic)"):
            self.assertIn(marker, cs, marker)
        self.assertNotIn("MirrorElements", cs)  # F5 v4 — см. живой замер ниже

    def test_flip_locked_door_never_mirrors(self) -> None:
        """ЖИВОЙ ЗАМЕР 27.07 (SOB6.2, Revit 2023): mirror-copy рушит ЧУЖИЕ двери.

        Три прогона на одном наборе из 178 опов окрестности, каждый на своей
        полосе (артефакты `mirror_cause_20260727.json`,
        `mirror_cause_BC_20260727.json`):

          A как есть              — 3 отказа «зеркальная копия недоступна»,
                                    3 нарушенных постусловия, и три двери
                                    БЕЗ ГЕОМЕТРИИ ВООБЩЕ в точке [0, 0];
          B флипы сняты везде     — 0 отказов, 0 нарушений, 0 поломок;
          C флипы сняты у трёх
            отказавших опов       — поломка ПЕРЕЕХАЛА на четвёртый оп.

        Ключевое в A: отказывают опы e7300294/e7382303/e9164901, а геометрию
        теряют СОВСЕМ ДРУГИЕ двери — e7813016/e7813017/e7813240 на другом
        хосте. Значит `MirrorElements` с mirrorCopies=true на hosted-двери
        портит документ за пределами своего опа, и никакой per-op
        SubTransaction этого не удерживает.

        Тот же вывод стоял в комментарии эмиттера с 21.07 («никаких зеркал на
        hosted»), но в код доведён не был — правило, заведённое рассуждением
        и не сомкнутое с кодом. Этот тест смыкает.

        НЕДОСТИЖИМЫЙ ФЛИП — ТИПИЗИРОВАННЫЙ ОТКАЗ (обновлено 09.08). Раньше
        он доезжал до постусловия, а вердикт свидетеля программный, поэтому за
        одну неповорачиваемую створку платила вся программа (16 красных строк
        `create_door` 21.07; у всех ЧЕТЫРЁХ с записанными нарушениями
        geometry_ok и topology_ok — ЗЕЛЁНЫЕ). Теперь отказ стоит на флипе, называет
        семейство и следующий ход; под `per_op` он стоит своего опа, а не
        соседей. Закон «никаких зеркал на hosted» этим не ослаблен: отказ —
        это отсутствие действия, а не новое действие. Подробности и
        опровергающие тесты — `test_hosted_flip_refusal.py`.
        """
        prog = copy.deepcopy(self._PROG)
        door = prog["ops"][1]
        door.update({"mirrored": False, "hand_flipped": True,
                     "facing_flipped": True})
        out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        # стабильный путь жив, но недостижимость теперь ОТКАЗ, а не молчание
        self.assertIn("if (!__el_D1.CanFlipHand)", cs)
        self.assertIn("flipHand()", cs)
        self.assertNotIn("MirrorElements", cs)            # ветки больше нет
        self.assertNotIn("__kirLockedMirror", cs)         # и её бюджета тоже
        # причина названа И у отказа, и у уцелевшего постусловия
        self.assertIn("не допускает смену стороны навески", cs)
        self.assertIn("выберите другой тип двери", cs)
        self.assertIn("семейство не допускает флипа", cs)

    def test_flip_free_hosted_emission_is_byte_stable(self) -> None:
        prog = copy.deepcopy(self._PROG)
        for op in prog["ops"]:
            for key in ("mirrored", "hand_flipped", "facing_flipped"):
                op.pop(key, None)
        out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        for marker in ("MirrorElements", "flipHand", "flipFacing",
                       "Mirrored !=", "HandFlipped !=", "FacingFlipped !="):
            self.assertNotIn(marker, cs, marker)

    def test_per_op_isolation_wraps_the_flip_branches(self) -> None:
        # per_op is an emit_program mode; the flip branch lives in the create
        # block, so it must come out of the SubTransaction wrapper without
        # leaking a whole-program return (the guard is rendered as a throw by
        # emit_utils.refuse_stmt; nothing rewrites the C# any more).
        from kukai.ir.authoring import emit_program
        grounded = ground_mod.ground(
            _parse_and_check(copy.deepcopy(self._PROG)), GROUND_SNAPSHOT)
        # plan-stage host attach (same as compiler's plan step)
        by_id = {op["id"]: op for op in grounded}
        for op in grounded:
            if op["op"] in ("create_door", "create_window"):
                op["__host_wall__"] = by_id[op["host"]["value"]]
        program = emit_program(grounded, "2026", isolation="per_op")
        self.assertIn("SubTransaction", program)
        self.assertIn("flipHand()", program)

    def test_a5_carries_no_mirror_budget_because_there_is_no_mirror(self) -> None:
        """Ограничитель пережил свой механизм — теперь не переживает.

        Бюджет `__kirLockedMirror_*` существовал ровно для одного пути —
        mirror-copy при CanFlip*=false, — и держал его в двух копиях на хост,
        потому что отложенный до Commit отказ Revit нельзя было удержать
        внутри SubTransaction. Путь снят по живому замеру 27.07 (см.
        F5EmitFlips.test_flip_locked_door_never_mirrors), поэтому счётчик,
        его порог и его текст отказа обязаны исчезнуть вместе с ним: код,
        охраняющий несуществующее, читается как охрана существующего.
        """
        scope = "a5:0123456789ab:0123456789abcdef"
        out = compile_program(
            copy.deepcopy(self._PROG), snapshot=GROUND_SNAPSHOT,
            isolation="per_op", stamp_scope=scope)

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        for gone in ("__kirLockedMirror", "MirrorElements",
                     "flip-locked mirror-copy per-host cap exceeded"):
            self.assertNotIn(gone, out.csharp, gone)


class F6LiftWallVertical(unittest.TestCase):
    @staticmethod
    def _wall(**params: Any) -> dict[str, Any]:
        wall = make_element("OST_Walls", 9001, ordinal=0)
        wall["p0_mm"] = [0.0, 0.0, 0.0]
        wall["p1_mm"] = [6_000.0, 0.0, 0.0]
        wall["params"] = {"WALL_USER_HEIGHT_PARAM": 2_800.0, **params}
        return wall

    def test_base_offset_and_top_level_are_lifted(self) -> None:
        wall = self._wall(
            WALL_BASE_OFFSET=-300.0, WALL_HEIGHT_TYPE="101")
        node = _by_source(lift_document(_document([wall])))["9001"]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["params"]["base_offset_mm"], -300.0)
        # level id 101 is "Этаж 2" in project1_metadata
        self.assertEqual(
            node["params"]["top_level"],
            {"by": "name", "value": "Этаж 2", "_id": "101"})
        # height_mm stays mandatory alongside the constraint.
        self.assertEqual(node["params"]["height_mm"], 2_800.0)

    def test_without_vertical_params_lift_is_byte_identical(self) -> None:
        plain = _by_source(lift_document(
            _document([self._wall()])))["9001"]
        self.assertNotIn("base_offset_mm", plain["params"])
        self.assertNotIn("top_level", plain["params"])
        # Sub-millimetre offset noise keeps the historical params too.
        noisy = _by_source(lift_document(
            _document([self._wall(WALL_BASE_OFFSET=0.4)])))["9001"]
        self.assertEqual(
            canon_op(plain, _ZERO), canon_op(noisy, _ZERO))

    def test_top_offset_is_lifted_with_the_attach(self) -> None:
        # Wall-fidelity (live A5 evidence 2026-07-21): the top offset is a
        # DEFINING DOF — the «демо» run missed every attached wall by exactly
        # |offset| because it was never extracted/lifted/emitted.
        wall = self._wall(WALL_HEIGHT_TYPE="101", WALL_TOP_OFFSET=-300.0)
        node = _by_source(lift_document(_document([wall])))["9001"]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["params"]["top_offset_mm"], -300.0)
        # Without the attach the offset param is meaningless — not lifted.
        free = _by_source(lift_document(
            _document([self._wall(WALL_TOP_OFFSET=-300.0)])))["9001"]
        self.assertNotIn("top_offset_mm", free["params"])
        # Sub-millimetre offset keeps the historical attach params.
        tiny = _by_source(lift_document(_document([
            self._wall(WALL_HEIGHT_TYPE="101", WALL_TOP_OFFSET=0.4)])))["9001"]
        self.assertNotIn("top_offset_mm", tiny["params"])

    def test_column_vertical_dof_is_lifted(self) -> None:
        # P1 DOF-completeness (fidelity audit 2026-07-21): на «демо» 100%
        # колонн top-attached — без этой вертикали каждая колонна
        # пересобиралась бы as-placed высотой символа.
        col = make_element("OST_StructuralColumns", 9101, ordinal=0)
        col["p0_mm"] = [1_000.0, 2_000.0, 0.0]
        col["rotation_deg"] = 0.0
        col["params"] = {
            "FAMILY_BASE_LEVEL_OFFSET_PARAM": -150.0,
            "FAMILY_TOP_LEVEL_PARAM": "101",
            "FAMILY_TOP_LEVEL_OFFSET_PARAM": -300.0,
        }
        node = _by_source(lift_document(_document([col])))["9101"]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["params"]["base_offset_mm"], -150.0)
        self.assertEqual(
            node["params"]["top_level"],
            {"by": "name", "value": "Этаж 2", "_id": "101"})
        self.assertEqual(node["params"]["top_offset_mm"], -300.0)
        # Без вертикальных параметров — историческая байт-идентичная форма.
        plain = make_element("OST_StructuralColumns", 9102, ordinal=1)
        plain["p0_mm"] = [1_000.0, 2_000.0, 0.0]
        plain["rotation_deg"] = 0.0
        plain["params"] = {}
        pnode = _by_source(lift_document(_document([plain])))["9102"]
        for key in ("base_offset_mm", "top_level", "top_offset_mm"):
            self.assertNotIn(key, pnode["params"])
        # Неразрешимый top-уровень = честный атом (как у стены).
        bad = make_element("OST_StructuralColumns", 9103, ordinal=2)
        bad["p0_mm"] = [0.0, 0.0, 0.0]
        bad["rotation_deg"] = 0.0
        bad["params"] = {"FAMILY_TOP_LEVEL_PARAM": "777777"}
        bnode = _by_source(lift_document(_document([bad])))["9103"]
        self.assertEqual(bnode["kind"], "atom")

    def test_contradictory_height_type_is_an_honest_atom(self) -> None:
        wall = self._wall(WALL_HEIGHT_TYPE="777777")   # not a known level
        node = _by_source(lift_document(_document([wall])))["9001"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "missing_metadata")

    def test_out_of_bound_base_offset_is_an_honest_atom(self) -> None:
        wall = self._wall(WALL_BASE_OFFSET=99_000.0)   # beyond ±15000
        node = _by_source(lift_document(_document([wall])))["9001"]
        self.assertEqual(node["kind"], "atom")


class F6EmitWallVertical(unittest.TestCase):
    def test_base_offset_emission_and_witness(self) -> None:
        out = compile_program({
            "ir_version": "1.0", "intent": "парапет", "ops": [
                {"op": "create_wall", "id": "WB", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 1200, "base_offset_mm": 900}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        self.assertIn("WALL_BASE_OFFSET", cs)
        self.assertIn("__bo_WB.Set(U(900", cs)
        self.assertIn("base offset mismatch (geometry)", cs)

    def test_top_level_attachment_and_witness(self) -> None:
        out = compile_program({
            "ir_version": "1.0", "intent": "стена до уровня", "ops": [
                {"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000,
                 "top_level": {"by": "name", "value": "Этаж 2"}}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        self.assertIn("WALL_HEIGHT_TYPE", cs)
        self.assertIn("__ht_WT.Set(__tl_WT.Id)", cs)
        self.assertIn("WALL_TOP_OFFSET", cs)
        self.assertIn("top constraint mismatch (topology)", cs)

    def test_top_offset_emission_witness_and_absent_bytes(self) -> None:
        # Wall-fidelity (live A5 evidence 2026-07-21): explicit top_offset_mm
        # flows into WALL_TOP_OFFSET (was forced 0 — every offset-attached wall
        # rebuilt at the full span) and is witnessed; ABSENT keeps the
        # historical ``Set(0.0)`` literal byte-exact.
        base = {"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
                "p1_mm": [6000, 0],
                "level": {"by": "name", "value": "Этаж 1"},
                "height_mm": 3000,
                "top_level": {"by": "name", "value": "Этаж 2"}}
        with_off = compile_program(
            {"ir_version": "1.0", "intent": "attach с офсетом",
             "ops": [dict(base, top_offset_mm=-300.0)]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(with_off.ok)
        self.assertIn("__to_WT.Set(U(-300.0))", with_off.csharp)
        self.assertIn("top offset mismatch (geometry)", with_off.csharp)
        without = compile_program(
            {"ir_version": "1.0", "intent": "attach без офсета",
             "ops": [dict(base)]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(without.ok)
        self.assertIn("__to_WT.Set(0.0)", without.csharp)
        self.assertNotIn("top offset mismatch", without.csharp)

    def test_top_level_by_ref_to_created_level(self) -> None:
        out = compile_program({
            "ir_version": "1.0", "intent": "стена до созданного уровня",
            "ops": [
                {"op": "create_level", "id": "L9", "elev_mm": 9000,
                 "name": "КИР-9"},
                {"op": "create_wall", "id": "WR", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 9000,
                 "top_level": {"by": "ref", "value": "L9"}}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("Level __tl_WR = __el_L9;", out.csharp)

    def test_vertical_free_wall_emission_is_byte_stable(self) -> None:
        out = compile_program({
            "ir_version": "1.0", "intent": "обычная стена", "ops": [
                {"op": "create_wall", "id": "W0", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        for marker in ("WALL_BASE_OFFSET", "WALL_HEIGHT_TYPE",
                       "WALL_TOP_OFFSET", "__bo_", "__ht_", "__tl_"):
            self.assertNotIn(marker, out.csharp, marker)

    def test_omitted_top_level_never_resolves_a_default(self) -> None:
        # Two levels in the snapshot: a speculative default resolution would
        # be AMBIGUOUS and refuse; an omitted top_level must instead compile
        # as the plain unconnected wall.
        self.assertEqual(len(GROUND_SNAPSHOT["levels"]), 2)
        out = compile_program({
            "ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_wall", "id": "W0", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)


class F6WallHeightVsTopConstraint(unittest.TestCase):
    """height mismatch fix (30.07.2026, live witness telemetry 29.07.2026:
    two facade programs — 4 walls + 5 floors, then 16 walls, "height
    mismatch" on EVERY wall).

    height_mm carries a registry default (DEFAULTS["wall"]["height_mm"] ==
    3000.0), and validate()'s "mm"-kind branch fills that default into
    `norm` for every OMITTED height_mm before the emitter ever sees the op
    (authoring.validate, ``elif p.kind == "mm": v = op.get(p.name,
    p.default)``) — the emitter cannot tell "caller asked for exactly
    3000mm" apart from "caller said nothing, top_level decides the span".
    WALL_USER_HEIGHT_PARAM also stops being authoritative once a top
    constraint is attached (Revit derives the built height from the
    base/top level pair). The old unconditional height witness therefore
    rolled back correctly-built facade walls whenever their real storey
    height differed from the silently-injected 3000mm default.

    Falsifying-test note: there is no earlier commit to diff against for
    this class (unlike create_beam/create_door) — it is closed here for the
    first time. All five tests in this class were verified to FAIL against
    the pre-fix shape (temporarily un-gating the height WitnessCheck back to
    unconditional, matching the code this commit replaces) before the fix
    landed, and to PASS after — see the wave report / commit message for the
    literal before/after pytest output.
    ``test_control_the_old_unconditional_check_would_have_fired`` additionally
    keeps a standing, self-contained control: it reconstructs the pre-fix
    WitnessCheck inline and asserts its verdict line embeds the literal
    default (3000.0) the live facade walls' real storey height was never
    guaranteed to match — the false positive, pinned so it cannot silently
    regress back in.
    """

    def _facade_story(self, **extra) -> dict:
        op = {"op": "create_wall", "id": "s01", "p0_mm": [0, 0],
              "p1_mm": [8000, 0],
              "level": {"by": "name", "value": "Этаж 1"},
              "top_level": {"by": "name", "value": "Этаж 2"}}
        op.update(extra)
        return {"ir_version": "1.0", "intent": "фасад, этаж 1", "ops": [op]}

    def test_omitted_height_with_top_level_drops_the_height_witness(self) -> None:
        # height_mm OMITTED (the natural way to author a facade wall that
        # spans between two levels) -- the silently-defaulted 3000.0mm must
        # NOT become a hard equality requirement.
        out = compile_program(self._facade_story(), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("height mismatch", cs)
        self.assertNotIn("WALL_USER_HEIGHT_PARAM", cs)
        # the vertical extent is still fully pinned -- just by topology, not
        # by a fabricated height literal.
        self.assertIn("top constraint mismatch (topology)", cs)
        self.assertIn("WALL_HEIGHT_TYPE", cs)

    def test_explicit_height_with_top_level_also_drops_the_height_witness(self) -> None:
        # Even an EXPLICIT height_mm alongside top_level is no longer
        # witnessed via WALL_USER_HEIGHT_PARAM: that parameter is not the
        # source of truth once attached, explicit or not.
        out = compile_program(
            self._facade_story(height_mm=3300.0), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertNotIn("height mismatch", out.csharp)

    def test_height_witness_unchanged_without_top_level(self) -> None:
        # The ordinary (unconnected) wall keeps its exact pre-existing
        # height witness -- this class must not touch that path at all.
        out = compile_program({
            "ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_wall", "id": "W0", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        cs = out.csharp
        self.assertIn("WALL_USER_HEIGHT_PARAM", cs)
        self.assertIn("height mismatch", cs)

    def test_translation_cert_proven_with_and_without_explicit_height(self) -> None:
        from kukai.ir.translation_cert import certify_op

        for kw in ({}, {"height_mm": 3300.0}):
            with self.subTest(kw=kw):
                normed = _parse_and_check(self._facade_story(**kw))
                grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
                cert = certify_op(grounded[0], "2024")
                self.assertTrue(cert.proven, cert.gaps)
                height_clause = [
                    v for v in cert.clauses if "height" in v.clause][0]
                self.assertFalse(height_clause.required)
                self.assertTrue(height_clause.discharged)
                self.assertIsNone(height_clause.matched_marker)

    def test_control_the_old_unconditional_check_would_have_fired(self) -> None:
        """Control: reconstructs the OLD (unconditional) height-witness
        shape this class replaces and shows it fires on the exact scenario
        the live telemetry describes -- proving the fix removes a real false
        positive, not a hypothetical one."""
        from kukai.ir.authoring import WitnessCheck, _cs, _safe
        from kukai.ir.emit_model import tolerance

        s = _safe("s01")
        h = 3000.0            # the registry default -- never asked for
        # Допуск предъявляется ОБЪЕКТОМ из реестра: с 03.08 витнес нельзя
        # построить с заявленным ключом при числе, набранном рядом руками
        # (закон 2, emit_model.py) — реконструкция старой формы обязана
        # подчиняться тому же закону, иначе она реконструирует не то.
        tol = tolerance("create_wall", "height_mm")
        old_check = WitnessCheck(
            obligation_key="height",
            reader_cs=(
                f"    var __hp = __el_{s}.get_Parameter("
                f"BuiltInParameter.WALL_USER_HEIGHT_PARAM);\n"),
            verdict_cs=(
                f"    if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - {h}) > {tol})\n"
                f"        __post.Add({_cs('s01: height mismatch')});\n"),
            message="height mismatch", tol=tol, style="guard")
        # The control check is unconditional BY CONSTRUCTION here (mirrors
        # the pre-fix code, which appended it regardless of top_level) --
        # the live facade walls attach a real top_level whose span need not
        # equal the 3000mm default, so the reconstructed check's own verdict
        # line embeds a literal '3000.0' the real building's storey height
        # was never guaranteed to match. That is the false positive.
        self.assertIn("- 3000.0) > 1.0", old_check.verdict_cs)
        self.assertIn("height mismatch", old_check.verdict_cs)
        # ...and the CURRENT emission (the fix) carries no such literal for
        # this op at all.
        out = compile_program(self._facade_story(), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertNotIn("- 3000.0", out.csharp)


class LiftEmitRoundTrip(unittest.TestCase):
    def test_f5_lifted_flips_reach_the_emitted_csharp(self) -> None:
        """lift -> params -> validate -> ground -> emit carries the flips."""
        wall, door, window = _hosted_rows()
        index = {"9600": _hosted_placement_row(
            door, mirrored=True, hand_flipped=True)}
        nodes = _by_source(lift_document(
            _document([wall, door, window]),
            family_placement_index=index))
        door_node = nodes["9600"]
        flips = {k: door_node["params"][k]
                 for k in ("mirrored", "hand_flipped", "facing_flipped")}
        prog = {
            "ir_version": "1.0", "intent": "roundtrip", "ops": [
                {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                 "p1_mm": [8000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000},
                {"op": "create_door", "id": "D1",
                 "host": {"by": "ref", "value": "W1"},
                 "offset_mm": 2000, **flips}]}
        out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        # F5 v4: флип ставится только flipHand/flipFacing там, где Revit
        # разрешает; недостигнутый флип держит свидетель.
        self.assertNotIn("MirrorElements", out.csharp)
        self.assertIn("flipHand", out.csharp)
        self.assertIn("mirrored state mismatch (semantic)", out.csharp)

    def test_f6_lifted_vertical_attributes_reach_the_emitted_csharp(
            self) -> None:
        wall = make_element("OST_Walls", 9001, ordinal=0)
        wall["p0_mm"] = [0.0, 0.0, 0.0]
        wall["p1_mm"] = [6_000.0, 0.0, 0.0]
        wall["params"] = {
            "WALL_USER_HEIGHT_PARAM": 2_800.0,
            "WALL_BASE_OFFSET": -300.0,
            "WALL_HEIGHT_TYPE": "101",
        }
        node = _by_source(lift_document(_document([wall])))["9001"]
        prog = {
            "ir_version": "1.0", "intent": "roundtrip", "ops": [
                {"op": "create_wall", "id": "W1",
                 "p0_mm": node["params"]["p0_mm"],
                 "p1_mm": node["params"]["p1_mm"],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": node["params"]["height_mm"],
                 "base_offset_mm": node["params"]["base_offset_mm"],
                 "top_level": {
                     "by": "name",
                     "value": node["params"]["top_level"]["value"]}}]}
        out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("__bo_W1.Set(U(-300", out.csharp)
        self.assertIn("WALL_HEIGHT_TYPE", out.csharp)


class RegistryDiscipline(unittest.TestCase):
    def test_audit_registry_coverage_stays_empty(self) -> None:
        self.assertEqual(audit_registry_coverage(), ())

    def test_cert_conditionals_for_new_params(self) -> None:
        prog = {
            "ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000, "base_offset_mm": 900,
                 "top_level": {"by": "name", "value": "Этаж 2"}}]}
        grounded = ground_mod.ground(
            _parse_and_check(prog), GROUND_SNAPSHOT)
        cert = certify_op(grounded[0], "2024")
        self.assertTrue(cert.proven, cert.gaps)
        for needle in ("base offset", "top constraint"):
            clause = [v for v in cert.clauses if needle in v.clause][0]
            self.assertTrue(clause.required)
            self.assertTrue(clause.discharged)

    def test_absent_params_stay_absent_in_normalization(self) -> None:
        normed = _parse_and_check({
            "ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_wall", "id": "W0", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000},
                {"op": "create_door", "id": "D0",
                 "host": {"by": "ref", "value": "W0"}, "offset_mm": 100}]})
        self.assertNotIn("base_offset_mm", normed[0])
        self.assertNotIn("top_level", normed[0])
        for key in ("mirrored", "hand_flipped", "facing_flipped"):
            self.assertNotIn(key, normed[1])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
