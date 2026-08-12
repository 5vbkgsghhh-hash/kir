"""Family-A completion gates (a)(d)(e): floor version divergence, hosted
window/door topology-at-compile-time, room ordering rule, symbol pools."""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _prog(ops, **env):
    p = {"ir_version": "1.0", "intent": "family-a", "ops": ops}
    p.update(env)
    return p


OUTLINE = [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]
HOLE = [[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]
LVL = {"by": "name", "value": "Этаж 1"}


class FloorVersionAxis(unittest.TestCase):
    def test_2022_plus_uses_floor_create(self):
        out = compile_program(_prog([{"op": "create_floor", "id": "F1",
                                      "outline": OUTLINE, "holes": [HOLE],
                                      "level": LVL}]),
                              revit_version="2022", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("Floor.Create(doc, __loops_F1", out.csharp)
        self.assertIn("__hl_F1_0", out.csharp)          # hole loop present

    def test_2021_uses_newfloor(self):
        out = compile_program(_prog([{"op": "create_floor", "id": "F1",
                                      "outline": OUTLINE, "level": LVL}]),
                              revit_version="2021", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("doc.Create.NewFloor(__ca_F1", out.csharp)
        self.assertNotIn("Floor.Create(doc, __loops", out.csharp)

    def test_2021_holes_typed_refusal(self):
        out = compile_program(_prog([{"op": "create_floor", "id": "F1",
                                      "outline": OUTLINE, "holes": [HOLE],
                                      "level": LVL}]),
                              revit_version="2021", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", [d.code for d in out.diagnostics])

    def test_degenerate_outline_refused(self):
        out = compile_program(_prog([{"op": "create_floor", "id": "F1",
                                      "outline": [[0, 0], [10, 0], [10, 10]],
                                      "level": LVL}]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


class HostedTopology(unittest.TestCase):
    WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
            "level": LVL}

    def test_window_position_computed_at_compile(self):
        out = compile_program(_prog([
            self.WALL,
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000, "sill_mm": 900},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("U(2000.0)", cs)                       # px literal along host
        self.assertIn("__el_Win1.Host", cs)                   # topology postcondition
        self.assertIn("host mismatch (topology)", cs)
        self.assertIn("Elevation + U(900.0)", cs)             # sill on host level
        # 28.07 regression pin: the new element_id runtime-host branch must
        # never leak into the ref path's emission.
        self.assertNotIn("__hw_", cs)
        self.assertNotIn(".Evaluate(", cs)

    def test_offset_beyond_wall_end_unexpressible(self):
        out = compile_program(_prog([
            self.WALL,
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 6500},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T002"][0]
        self.assertEqual(d.field_name, "offset_mm")
        self.assertIn("6000", str(d.expected))

    def test_host_by_unsupported_selector_still_refused(self):
        """28.07: host в v1 сузилось до ref|element_id (было — только ref).
        Любой ТРЕТИЙ вид селектора остаётся отказом — правило сужено, не
        снято."""
        out = compile_program(_prog([
            {"op": "create_door", "id": "D1",
             "host": {"by": "name", "value": "Стена 1"}, "offset_mm": 1000},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])
        # No longer the OLD "host в v1 — только ref" message (that message is
        # now reserved for ops OTHER than door/window — set_curtain_panel's
        # host, place_family's curve host — where ref really is still the
        # only legal form).
        self.assertNotIn(
            "только ref на create_wall",
            " ".join(d.message_ru for d in out.diagnostics))

    def test_host_wrong_kind(self):
        out = compile_program(_prog([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0], "p1_mm": [0, 5000]},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "G1"}, "offset_mm": 100},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L004", [d.code for d in out.diagnostics])


class HostByElementId(unittest.TestCase):
    """28.07 (audit's most frequent external scenario): «поставь окно в МОЮ
    стену» — v1 could only host a door/window on a wall the SAME program
    created (ref). host now also accepts a pinned element_id — an existing
    wall the program never touches.

    compiler.py's plan stage (не трогаем — грязный чужой файл) attaches
    ``__host_wall__`` by looking ``host.value`` up in ``byid``, a table keyed
    by op-id STRINGS; an element_id is an int, so the lookup is empty BY
    CONSTRUCTION and ``__host_wall__`` is simply never attached — no
    compiler.py change needed, and the compile-time "offset beyond wall end"
    law (KIR-T002) silently does not fire for this branch. The law is not
    dropped — it moves to RUNTIME: the emitter reads the host's live
    LocationCurve and measures it there (see
    test_offset_vs_length_check_moves_to_runtime).
    """

    HOST_ID = 8145901   # opaque: host is target_w, never snapshot-resolved

    def test_door_host_by_element_id_compiles_with_runtime_frame(self):
        out = compile_program(_prog([
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": self.HOST_ID},
             "offset_mm": 1000, "sill_mm": -100},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        # host resolved LIVE (doc.GetElement + cast), not a same-program
        # __el_<ref> variable — the actual Revit API shape confirmed by
        # binary reflection over RevitAPI.dll (Curve.Evaluate(double,bool),
        # Curve.Length, LocationCurve.Curve — stable across all 6 versions).
        self.assertIn("__hw_D1", cs)
        self.assertIn("as LocationCurve", cs)
        self.assertIn(".Evaluate(", cs)
        self.assertIn("true)", cs)          # normalized parameter, not raw
        # sill still comes from the host's OWN level — same formula as ref.
        self.assertIn("Elevation + U(-100.0)", cs)
        # topology postcondition present, same shape as the ref path.
        self.assertIn("__el_D1.Host", cs)
        self.assertIn("host mismatch (topology)", cs)
        # scope contract: the computed point/host var must be readable from
        # the per_op-wrapped post block, i.e. NOT declared only inside the
        # per-op create try-scope.
        per_op_cs = compile_program(_prog([
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": self.HOST_ID},
             "offset_mm": 1000},
        ]), snapshot=GROUND_SNAPSHOT, isolation="per_op").csharp
        self.assertIn(".Evaluate(", per_op_cs)

    def test_window_host_by_element_id_compiles(self):
        out = compile_program(_prog([
            {"op": "create_window", "id": "Win1",
             "host": {"by": "element_id", "value": self.HOST_ID},
             "offset_mm": 2000, "sill_mm": 900},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn(".Evaluate(", cs)
        self.assertIn("Elevation + U(900.0)", cs)

    def test_stale_host_is_a_typed_refusal_not_an_npe(self):
        """The host cast (`as Wall`) and the LocationCurve cast both carry a
        typed null-guard — a stale id (deleted/wrong-category since
        grounding) is a refuse_stmt, never a live NullReferenceException."""
        out = compile_program(_prog([
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": self.HOST_ID},
             "offset_mm": 1000},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("== null", cs)
        self.assertIn("не найдена", cs)

    def test_offset_vs_length_check_moves_to_runtime(self):
        """Compile-time cannot know the real wall's length for an
        element_id host (byid never matches an int), so an offset the
        compile-time ref-path WOULD refuse outright (see
        test_offset_beyond_wall_end_unexpressible: 6500mm > a 6000mm host)
        is NOT refused here at plan time — it becomes a runtime length-vs-
        offset guard emitted as C#, never a KIR-T002."""
        out = compile_program(_prog([
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": self.HOST_ID},
             "offset_mm": 99_000},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertNotIn("KIR-T002", [d.code for d in out.diagnostics])
        self.assertIn("Length", out.csharp)
        self.assertIn("U(99000.0)", out.csharp)


class RoomOrderingRule(unittest.TestCase):
    def test_regenerate_before_room_after_walls(self):
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": LVL},
            {"op": "create_room", "id": "R1", "xy": [3000, 1000], "level": LVL,
             "name": "Кухня"},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        i_wall = cs.index("= Wall.Create(doc")
        i_regen = cs.index("finalize wall enclosures")
        i_room = cs.index("NewRoom")
        self.assertLess(i_wall, i_regen)
        self.assertLess(i_regen, i_room)

    def test_no_spurious_regen_without_walls(self):
        out = compile_program(_prog([
            {"op": "create_room", "id": "R1", "xy": [3000, 1000], "level": LVL},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertNotIn("finalize wall enclosures", out.csharp)

    def test_room_witness_rejects_unplaced_or_unenclosed_room(self):
        out = compile_program(_prog([
            {"op": "create_room", "id": "R1", "xy": [3000, 1000],
             "level": LVL, "name": "Кухня"},
        ]), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("room placement mismatch (geometry)", out.csharp)
        self.assertIn("room is not enclosed (semantic)", out.csharp)
        # ИМЯ СВЕРЯЕТСЯ ПАРАМЕТРОМ, А НЕ `Room.Name` — и это утверждение
        # двустороннее нарочно. Замер 04.08 («Проект1», Revit 2026): сеттер
        # `Room.Name` кладёт только имя, а геттер склеивает его с НОМЕРОМ
        # помещения, поэтому постусловие на геттере не выполнялось НИКОГДА и
        # живая матрица откатывала ИСПРАВНЫЕ помещения (`f570aee2`). Эмиттер
        # починили в тот же день, а это утверждение осталось на старой форме и
        # держало набор красным пять дней. Вторая половина — храповик: если
        # `Room.Name` вернётся в свидетеля, тест обязан упасть здесь, а не на
        # живой модели пользователя.
        self.assertIn('__rnm_R1.AsString() != "Кухня"', out.csharp)
        self.assertNotIn('__el_R1.Name != "Кухня"', out.csharp)


class SymbolsAndPlacement(unittest.TestCase):
    def test_column_category_pools(self):
        for cat, sym_id in (("structural", 500), ("architectural", 501)):
            out = compile_program(_prog([{"op": "create_column", "id": "C1",
                                          "xy": [3000, 3000], "level": LVL,
                                          "category": cat}]),
                                  snapshot=GROUND_SNAPSHOT)
            self.assertTrue(out.ok, (cat, [d.as_dict() for d in out.diagnostics][:2]))
            self.assertIn(f"new ElementId({sym_id})", out.csharp)
        st = compile_program(_prog([{"op": "create_column", "id": "C1",
                                     "xy": [0, 0], "level": LVL}]),
                             snapshot=GROUND_SNAPSHOT).csharp
        self.assertIn("StructuralType.Column", st)     # default category

    def test_place_family_full_checks(self):
        out = compile_program(_prog([{"op": "place_family", "id": "T1",
                                      "xyz": [1000, 2000, 0], "level": LVL}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("IsActive", cs)                   # symbol activation
        self.assertIn("FAMILY_BASE_LEVEL_PARAM", cs)    # level chain topology
        self.assertIn("location mismatch (geometry)", cs)

    def test_full_house_program(self):
        """Every family-A op in one program — the v1-complete smoke."""
        out = compile_program(_prog([
            {"op": "create_level", "id": "L1", "elev_mm": 0, "name": "КИР-1"},
            {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000], "p1_mm": [0, 7000]},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000},
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_column", "id": "C1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2700], "level": {"by": "ref", "value": "L1"}},
            {"op": "create_room", "id": "R1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}, "name": "Зал"},
            {"op": "place_family", "id": "T1", "xyz": [2000, 2000, 0],
             "level": {"by": "ref", "value": "L1"}},
        ], intent="полный дом v1"), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        self.assertEqual(cs.count("{"), cs.count("}"))
        for oid in ("L1", "G1", "W1", "Win1", "D1", "F1", "C1", "P1", "R1", "T1"):
            self.assertIn(f'__results["{oid}"]', cs)


if __name__ == "__main__":
    unittest.main()
