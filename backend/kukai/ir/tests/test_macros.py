"""Macro layer + DAG + modify family gates (a)(d): deterministic expansion,
caps, ref-DAG discipline, destructive policy-gate."""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import macros  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _prog(ops, **env):
    p = {"ir_version": "1.0", "intent": "macro-test", "ops": ops}
    p.update(env)
    return p


STACK = {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
         "name_prefix": "Этаж",
         "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0], "height_mm": 2800}]}


class StackMacro(unittest.TestCase):
    def test_expansion_shape_and_determinism(self):
        flat1 = macros.expand([STACK])
        flat2 = macros.expand([STACK])
        self.assertEqual(flat1, flat2, "expansion must be deterministic")
        levels = [o for o in flat1 if o["op"] == "create_level"]
        walls = [o for o in flat1 if o["op"] == "create_wall"]
        self.assertEqual(len(levels), 3)
        self.assertEqual(len(walls), 3)
        self.assertEqual(levels[1]["elev_mm"], 3000)
        self.assertEqual(levels[2]["name"], "Этаж 3")
        self.assertEqual(walls[0]["level"], {"by": "ref", "value": "sec_L1"})

    def test_full_compile_no_snapshot_needed(self):
        """Stack references only its own created levels + doc-default wall
        type is in-emit — the program grounds without any census snapshot."""
        out = compile_program(_prog([STACK]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertEqual(out.csharp.count("= Level.Create(doc"), 3)
        self.assertEqual(out.csharp.count("= Wall.Create(doc"), 3)
        self.assertEqual(out.csharp.count("new Transaction"), 1)

    def test_pipe_z_shift_per_storey(self):
        st = dict(STACK)
        st["floor"] = [{"op": "create_pipe", "id": "P",
                        "p0_mm": [0, 0, 2700], "p1_mm": [3000, 0, 2700]}]
        flat = macros.expand([st])
        pipes = [o for o in flat if o["op"] == "create_pipe"]
        self.assertEqual(pipes[0]["p0_mm"][2], 2700)
        self.assertEqual(pipes[2]["p0_mm"][2], 2700 + 2 * 3000)

    def test_pipe_z_shift_includes_nonzero_base_elevation(self):
        st = dict(STACK)
        st["base_elev_mm"] = 12000
        st["floor"] = [{"op": "create_pipe", "id": "P",
                        "p0_mm": [0, 0, 2700], "p1_mm": [3000, 0, 2700]}]
        flat = macros.expand([st])
        pipes = [o for o in flat if o["op"] == "create_pipe"]
        self.assertEqual(pipes[0]["p0_mm"][2], 14700)
        self.assertEqual(pipes[2]["p0_mm"][2], 20700)

    def test_grid_inside_stack_refused(self):
        st = dict(STACK)
        st["floor"] = [{"op": "create_grid", "id": "G",
                        "p0_mm": [0, 0], "p1_mm": [0, 5000]}]
        out = compile_program(_prog([st]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_caps(self):
        st = dict(STACK)
        st["levels"] = 41
        out = compile_program(_prog([st]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_expansion_budget_checked_before_copying_floor(self):
        st = dict(STACK)
        st["levels"] = 40
        st["floor"] = [dict(STACK["floor"][0], id=f"W{i}") for i in range(7)]
        out = compile_program(_prog([st]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_nonfinite_and_unknown_macro_fields_refused_at_macro_stage(self):
        for change in ({"h_mm": float("nan")}, {"base_elev_mm": float("inf")},
                       {"surprise": True}, {"id": 7}):
            with self.subTest(change=change):
                st = dict(STACK)
                st.update(change)
                out = compile_program(_prog([st]))
                self.assertFalse(out.ok)
                self.assertIn("KIR-M001", [d.code for d in out.diagnostics])


class GridArrayMacro(unittest.TestCase):
    def test_expansion(self):
        flat = macros.expand([{"op": "grid_array", "id": "net", "nx": 3, "ny": 2,
                               "dx_mm": 6000, "dy_mm": 4500}])
        self.assertEqual(len(flat), 5)
        names = [o["name"] for o in flat]
        self.assertEqual(names, ["1", "2", "3", "А1", "А2"])
        out = compile_program(_prog(list(flat)))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_compiles_via_macro_in_program(self):
        out = compile_program(_prog([{"op": "grid_array", "id": "net",
                                      "nx": 2, "ny": 2}]))
        self.assertTrue(out.ok)
        self.assertEqual(out.csharp.count("= Grid.Create(doc"), 4)


#: Сужение с ИЗЛОМОМ: hw падает 8000->4000 на первой половине и 4000->1000 на
#: второй, то есть с разной крутизной. Равномерное сужение дало бы на шаге 1
#: 6250, а не 6000 — именно этим кусочный трек и отличается от stack.transform.
SERIES = {"op": "series", "id": "leg", "count": 4,
          "track": {"hw": [[0, 8000], [2, 4000], [4, 1000]],
                    "z": [[0, 0], [4, 12000]]},
          "items": [{"op": "create_beam", "id": "sw",
                     "p0_mm": ["-$hw", "-$hw", "$z"],
                     "p1_mm": ["-$hw@next", "-$hw@next", "$z@next"],
                     "level": {"by": "ref", "value": "L0"}}]}


def _series(**change):
    s = dict(SERIES)
    s.update(change)
    return s


class SeriesMacro(unittest.TestCase):
    def test_expansion_shape_and_determinism(self):
        flat1 = macros.expand([SERIES])
        flat2 = macros.expand([SERIES])
        self.assertEqual(flat1, flat2, "expansion must be deterministic")
        self.assertEqual(len(flat1), 4)
        self.assertEqual([o["id"] for o in flat1],
                         ["leg_0_sw", "leg_1_sw", "leg_2_sw", "leg_3_sw"])
        # series is orthogonal to stack: it never mints a level
        self.assertEqual([o for o in flat1 if o["op"] == "create_level"], [])

    def test_track_is_piecewise_not_one_straight_line(self):
        flat = macros.expand([SERIES])
        got = [o["p0_mm"][0] for o in flat]
        self.assertEqual(got, [-8000.0, -6000.0, -4000.0, -2500.0])
        # a single straight 8000->1000 line would have put step 1 at -6250
        self.assertNotEqual(got[1], -6250.0)

    def test_next_chains_segments_end_to_start(self):
        """N повторов сшивают N сегментов по N+1 станциям: конец k == начало k+1."""
        flat = macros.expand([SERIES])
        for k in range(len(flat) - 1):
            with self.subTest(k=k):
                self.assertEqual(flat[k]["p1_mm"], flat[k + 1]["p0_mm"])
        self.assertEqual(flat[-1]["p1_mm"], [-1000.0, -1000.0, 12000.0])

    def test_sign_mirrors_one_track_into_four_legs(self):
        s = _series(items=[
            {"op": "create_beam", "id": "sw", "p0_mm": ["-$hw", "-$hw", "$z"],
             "p1_mm": ["-$hw@next", "-$hw@next", "$z@next"]},
            {"op": "create_beam", "id": "se", "p0_mm": ["$hw", "-$hw", "$z"],
             "p1_mm": ["$hw@next", "-$hw@next", "$z@next"]},
            {"op": "create_beam", "id": "ne", "p0_mm": ["$hw", "$hw", "$z"],
             "p1_mm": ["$hw@next", "$hw@next", "$z@next"]},
            {"op": "create_beam", "id": "nw", "p0_mm": ["-$hw", "$hw", "$z"],
             "p1_mm": ["-$hw@next", "$hw@next", "$z@next"]}])
        flat = macros.expand([s])
        self.assertEqual(len(flat), 16)
        first4 = flat[:4]
        self.assertEqual([o["p0_mm"] for o in first4],
                         [[-8000.0, -8000.0, 0.0], [8000.0, -8000.0, 0.0],
                          [8000.0, 8000.0, 0.0], [-8000.0, 8000.0, 0.0]])

    def test_full_compile_walls_no_snapshot_needed(self):
        """Переменная высота/длина рёбер — компилируется как обычный плоский IR.

        Уровень объявлен ОТДЕЛЬНЫМ опом и берётся по ref: series, в отличие от
        stack, уровней не создаёт, и это видно прямо в форме программы."""
        out = compile_program(_prog([
            {"op": "create_level", "id": "L0", "elev_mm": 0},
            {"op": "series", "id": "fin", "count": 3,
             "track": {"x": [[0, 0], [2, 10000]], "y": [[0, 3000], [2, 9000]]},
             "items": [{"op": "create_wall", "id": "w", "p0_mm": ["$x", 0],
                        "p1_mm": ["$x", "$y"], "height_mm": 3000,
                        "level": {"by": "ref", "value": "L0"}}]}]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertEqual(out.csharp.count("= Wall.Create(doc"), 3)
        self.assertEqual(out.csharp.count("= Level.Create(doc"), 1)
        self.assertEqual(out.csharp.count("new Transaction"), 1)

    def test_variable_pitch_grids_the_thing_grid_array_cannot_do(self):
        out = compile_program(_prog([{
            "op": "series", "id": "ax", "count": 3,
            "track": {"x": [[0, 0], [1, 6000], [2, 15000]]},
            "items": [{"op": "create_grid", "id": "g", "p0_mm": ["$x", -1000],
                       "p1_mm": ["$x", 20000]}]}]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertEqual(out.csharp.count("= Grid.Create(doc"), 3)
        flat = macros.expand([{
            "op": "series", "id": "ax", "count": 3,
            "track": {"x": [[0, 0], [1, 6000], [2, 15000]]},
            "items": [{"op": "create_grid", "id": "g", "p0_mm": ["$x", -1000],
                       "p1_mm": ["$x", 20000]}]}])
        self.assertEqual([o["p0_mm"][0] for o in flat], [0.0, 6000.0, 15000.0])

    def test_refusals_each_with_its_own_reason(self):
        cases = {
            "один узел": {"track": {"hw": [[0, 8000]],
                                    "z": [[0, 0], [4, 12000]]}},
            "узлы не по возрастанию": {"track": {"hw": [[0, 8000], [4, 4000], [2, 1000]],
                                                 "z": [[0, 0], [4, 12000]]}},
            "равные индексы узлов": {"track": {"hw": [[0, 8000], [2, 4000], [2, 1000]],
                                               "z": [[0, 0], [4, 12000]]}},
            "значение nan": {"track": {"hw": [[0, float("nan")], [4, 1000]],
                                       "z": [[0, 0], [4, 12000]]}},
            "значение inf": {"track": {"hw": [[0, 8000], [4, float("inf")]],
                                       "z": [[0, 0], [4, 12000]]}},
            "индекс nan": {"track": {"hw": [[float("nan"), 8000], [4, 1000]],
                                     "z": [[0, 0], [4, 12000]]}},
            "count не целое": {"count": 4.5},
            "count за пределом": {"count": macros.MAX_SERIES_COUNT + 1},
            "count ноль": {"count": 0},
            "items пустой": {"items": []},
            "неизвестное поле": {"surprise": True},
            "id не строка": {"id": 7},
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                out = compile_program(_prog([_series(**change)]))
                self.assertFalse(out.ok, name)
                self.assertIn("KIR-M001", [d.code for d in out.diagnostics], name)

    def test_unknown_parameter_reference_refused(self):
        out = compile_program(_prog([_series(items=[
            {"op": "create_beam", "id": "b", "p0_mm": ["-$hwd", 0, "$z"],
             "p1_mm": [0, 0, "$z@next"]}])]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-M001"][0]
        self.assertIn("hwd", d.message_ru)

    def test_malformed_reference_is_a_typo_not_a_literal(self):
        """'$hw@nxt' не должно уехать текстом в числовое поле."""
        for bad in ("$hw@nxt", "$hw+1", "$2hw", "-$", "$hw@next@next"):
            with self.subTest(ref=bad):
                out = compile_program(_prog([_series(items=[
                    {"op": "create_beam", "id": "b", "p0_mm": [bad, 0, "$z"],
                     "p1_mm": [0, 0, "$z@next"]}])]))
                self.assertFalse(out.ok, bad)
                self.assertIn("KIR-M001", [d.code for d in out.diagnostics], bad)

    def test_declared_but_unused_track_parameter_refused(self):
        out = compile_program(_prog([_series(
            track={"hw": [[0, 8000], [4, 1000]], "z": [[0, 0], [4, 12000]],
                   "unused": [[0, 1], [4, 2]]})]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-M001"][0]
        self.assertIn("unused", d.message_ru)

    def test_track_must_cover_every_index_it_is_read_at(self):
        # hw читается на 0..4 (есть @next), а покрывает только 0..3
        out = compile_program(_prog([_series(
            track={"hw": [[0, 8000], [3, 1000]], "z": [[0, 0], [4, 12000]]})]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-M001"][0]
        self.assertIn("hw", d.message_ru)
        # без @next хватило бы 0..3 — проверяю, что предел зависит от @next
        ok = compile_program(_prog([{
            "op": "series", "id": "s", "count": 4,
            "track": {"hw": [[0, 8000], [3, 1000]]},
            "items": [{"op": "create_column", "id": "c", "xy": ["$hw", 0],
                       "height_mm": 3000, "level": {"by": "ref", "value": "L0"}}]},
        ]))
        self.assertNotIn("KIR-M001", [d.code for d in ok.diagnostics])

    def test_track_starting_after_zero_refused(self):
        out = compile_program(_prog([_series(
            track={"hw": [[1, 8000], [4, 1000]], "z": [[0, 0], [4, 12000]]})]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_expansion_cap_counts_items_times_count(self):
        # 40 x 6 = 240 > MAX_SERIES_OPS(200), хотя ни count, ни items не за пределом
        items = [dict(SERIES["items"][0], id=f"b{i}") for i in range(6)]
        out = compile_program(_prog([_series(count=40, items=items)]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-M001"][0]
        self.assertIn(str(macros.MAX_SERIES_OPS), d.message_ru)

    def test_cap_is_below_the_program_wide_budget(self):
        """Один series не может выбрать весь бюджет программы."""
        self.assertLess(macros.MAX_SERIES_OPS, macros.MAX_EXPANDED_OPS)

    def test_non_series_able_op_refused(self):
        out = compile_program(_prog([_series(items=[
            {"op": "create_door", "id": "d", "xy": ["$hw", 0],
             "host": {"by": "ref", "value": "W1"}}])]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_nested_macro_refused(self):
        out = compile_program(_prog([_series(items=[
            {"op": "stack", "id": "inner", "levels": 2, "floor": []}])]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-M001"][0]
        self.assertIn("12.3", d.message_ru)

    def test_duplicate_item_id_refused(self):
        out = compile_program(_prog([_series(items=[
            dict(SERIES["items"][0]), dict(SERIES["items"][0])])]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-M001", [d.code for d in out.diagnostics])

    def test_reference_cannot_forge_op_or_id(self):
        """op/id не участвуют в подстановке — иначе имя опа собиралось бы из числа."""
        flat = macros.expand([_series(items=[
            {"op": "create_beam", "id": "$hw", "p0_mm": ["-$hw", 0, "$z"],
             "p1_mm": [0, 0, "$z@next"]}])])
        self.assertEqual(flat[0]["id"], "leg_0_$hw")
        self.assertEqual(flat[0]["op"], "create_beam")

    def test_existing_macros_untouched_by_the_new_one(self):
        """Регрессия: stack и grid_array разворачиваются побайтово как прежде."""
        self.assertEqual(len(macros.expand([STACK])), 6)
        self.assertEqual(len(macros.expand([{"op": "grid_array", "id": "n",
                                             "nx": 3, "ny": 2}])), 5)


class DagDiscipline(unittest.TestCase):
    def test_forward_ref_refused(self):
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_level", "id": "L1", "elev_mm": 0},
        ]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", [d.code for d in out.diagnostics])

    def test_ref_wrong_kind_refused(self):
        out = compile_program(_prog([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0], "p1_mm": [0, 5000]},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "ref", "value": "G1"}},
        ]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-L004", [d.code for d in out.diagnostics])

    def test_level_ref_topology_check_uses_variable(self):
        out = compile_program(_prog([
            {"op": "create_level", "id": "L1", "elev_mm": 3000, "name": "Тест"},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "ref", "value": "L1"}},
        ]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("__el_L1.Id.ToString()", out.csharp)


class ModifyFamily(unittest.TestCase):
    def test_set_param_str_and_mm(self):
        out = compile_program(_prog([
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 5555},
             "param": "Комментарии", "value": "проверено KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 5555},
             "param": "Смещение снизу", "value": {"value": 250, "unit": "mm"}},
        ]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("GetParameters", cs)
        self.assertIn(".Count != 1", cs)
        self.assertIn("IsReadOnly", cs)
        self.assertIn("U(250.0)", cs)
        self.assertIn("re-read", cs)         # postcondition present

    def test_bare_number_value_banned(self):
        out = compile_program(_prog([
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 5555},
             "param": "Смещение", "value": 250}]))
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T001"][0]
        self.assertEqual(d.suggested_replacement, {"value": 250, "unit": "mm"})

    def test_delete_needs_allow_destructive(self):
        ops = [{"op": "delete", "id": "D1",
                "target": {"by": "element_id", "value": 5555}}]
        out = compile_program(_prog(ops))
        self.assertFalse(out.ok)
        self.assertIn("KIR-D001", [d.code for d in out.diagnostics])
        out2 = compile_program(_prog(ops, allow_destructive=True))
        self.assertTrue(out2.ok, [d.as_dict() for d in out2.diagnostics][:3])
        self.assertIn("doc.Delete", out2.csharp)
        self.assertIn("элемент всё ещё существует", out2.csharp)

    def test_authoring_and_modify_mix_in_one_txn(self):
        out = compile_program(_prog([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
        ]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertEqual(out.csharp.count("new Transaction"), 1)

    def test_query_still_exclusive(self):
        out = compile_program(_prog([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "query_count", "id": "q", "kind": "wall"},
        ]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
