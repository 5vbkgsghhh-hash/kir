"""Gate (d): negative fuzzing — malformed IR must yield typed diagnostics,
never an exception, never emitted C# (SPEC 12.6d)."""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import MAX_OPS_PER_PROGRAM, compile_program  # noqa: E402


def _p(ops, **envelope):
    prog = {"ir_version": "1.0", "ops": ops}
    prog.update(envelope)
    return prog


class NegativeCorpus(unittest.TestCase):
    CASES = [
        # (program, expected diagnostic code prefix)
        (None, "KIR-P"),
        ([], "KIR-P"),
        ("wall", "KIR-P"),
        ({}, "KIR-P"),
        ({"ir_version": "1.0"}, "KIR-P"),
        ({"ir_version": "2.0", "ops": [{"op": "query_count", "kind": "wall"}]}, "KIR-P004"),
        (_p([]), "KIR-P"),
        (_p([{"op": "make_coffee"}]), "KIR-P002"),
        (_p([{"op": "query_count"}]), "KIR-G001"),                        # kind missing
        (_p([{"op": "query_count", "kind": 42}]), "KIR-G001"),
        (_p([{"op": "query_count", "kind": "wall", "extra": 1}]), "KIR-P003"),
        (_p([{"op": "query_count", "id": 7, "kind": "wall"}]), "KIR-T001"),
        (_p([{"op": "query_count", "id": "", "kind": "wall"}]), "KIR-T002"),
        (_p([{"op": "query_count", "kind": "wall", "where": "level=1"}]), "KIR-T001"),
        (_p([{"op": "query_count", "kind": "wall", "where": {"colour": "red"}}]), "KIR-P003"),
        (_p([{"op": "query_count", "kind": "wall", "where": {"level_name": 5}}]), "KIR-T001"),
        (_p([{"op": "query_list", "kind": "door", "limit": 0}]), "KIR-T002"),
        (_p([{"op": "query_list", "kind": "door", "limit": 10**9}]), "KIR-T002"),
        (_p([{"op": "query_list", "kind": "door", "limit": True}]), "KIR-T001"),
        (_p([{"op": "query_list", "kind": "door", "fields": []}]), "KIR-T001"),
        (_p([{"op": "query_list", "kind": "door", "fields": ["password"]}]), "KIR-T001"),
        (_p([{"op": "query_list", "kind": "door", "fields": ["id", "id"]}]), "KIR-T002"),
        (_p([{"op": "query_inspect"}]), "KIR-G002"),
        (_p([{"op": "query_inspect", "target": {"by": "vibe", "value": 1}}]), "KIR-G002"),
        (_p([{"op": "query_inspect", "target": {"by": "element_id", "value": -5}}]), "KIR-T001"),
        (_p([{"op": "query_inspect", "target": {"by": "name", "value": ""}}]), "KIR-T001"),
        (_p([{"op": "query_inspect", "target": {"by": "name", "value": "Стена"}}]), "KIR-G001"),  # kind missing
        (_p([{"op": "query_count", "kind": "wall", "id": "a"},
             {"op": "query_count", "kind": "door", "id": "a"}]), "KIR-P"),  # dup id
        (_p([{"op": "query_count", "kind": "wall"}], junk_field=1), "KIR-P003"),
        (_p([{"op": "query_count", "kind": "wall"}], intent=42), "KIR-T001"),
        (_p([{"op": "query_count", "kind": "wall"}], intent="x" * 2001), "KIR-T002"),
        (_p([{"op": "query_count", "kind": "wall"}], allow_destructive="yes"), "KIR-T001"),
        # ГРАНИЦА БЕРЁТСЯ У АВТОРИТЕТА. Здесь стоял литерал 21 — «на один
        # больше бюджета», верный, пока бюджет был 20. Владелец поднял его до
        # 100 (15.08), и негативный случай перестал быть негативным: программа
        # компилируется, а корпус, который обязан ловить отказ, ловил тишину.
        (_p([{"op": "query_count", "kind": "wall"}] * (MAX_OPS_PER_PROGRAM + 1)),
         "KIR-L001"),
        (_p([{"op": "create_level", "id": "L1"}]), "KIR-P005"),
        # unicode / injection attempts must be refused or safely escaped, never crash
        (_p([{"op": "query_count", "kind": 'wall"); doc.Delete(', }]), "KIR-G001"),
        (_p([{"op": "query_list", "kind": "wall",
              "where": {"name_contains": '"); System.IO.File.Delete("C:'}}]), None),  # valid shape: must COMPILE-ok w/ escaping
    ]

    def test_corpus(self):
        for prog, want in self.CASES:
            with self.subTest(prog=str(prog)[:80]):
                out = compile_program(prog)     # must never raise
                if want is None:
                    self.assertTrue(out.ok)
                    # injection string must arrive escaped, not as live C#
                    self.assertNotIn('File.Delete("C:', out.csharp.replace('\\"', ''))
                else:
                    self.assertFalse(out.ok)
                    self.assertIsNone(out.csharp)
                    self.assertTrue(out.diagnostics)
                    codes = [d.code for d in out.diagnostics]
                    self.assertTrue(any(c.startswith(want) for c in codes),
                                    f"want {want}, got {codes}")
                    self.assertNotIn("KIR-P000", codes)   # P000 = compiler panic

    def test_distinct_ids_never_alias_in_emitted_csharp(self):
        out = compile_program(_p([
            {"op": "query_count", "id": "a-b", "kind": "wall"},
            {"op": "query_count", "id": "a_b", "kind": "door"},
            {"op": "query_count", "id": "KIRX_612d62", "kind": "floor"},
        ]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("var __c_KIRX_612d62", out.csharp)
        self.assertIn("var __c_a_b", out.csharp)
        self.assertIn("var __c_KIRX_4b4952585f363132643632", out.csharp)

    def test_catalog_selector_ref_is_typed_refusal_not_emitter_panic(self):
        out = compile_program(_p([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [1000, 0], "level": {"by": "ref", "value": "L1"},
             "type": {"by": "ref", "value": "L1"}},
        ]), snapshot={})
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])
        self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])

    def test_dimension_dangling_ref_is_caught_by_generic_dag_walk(self):
        out = compile_program(_p([{
            "op": "create_dimension", "id": "D1",
            "in_view": {"by": "element_id", "value": 10},
            "refs": [{"by": "ref", "value": "missing"},
                     {"by": "element_id", "value": 20}],
            "line_at": [0, 0],
        }]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", [d.code for d in out.diagnostics])

    def test_dimension_ref_count_matches_schema_cap(self):
        out = compile_program(_p([{
            "op": "create_dimension", "id": "D1",
            "in_view": {"by": "element_id", "value": 10},
            "refs": [{"by": "element_id", "value": i} for i in range(1, 18)],
            "line_at": [0, 0],
        }]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_default_selector_cannot_hide_ignored_value(self):
        out = compile_program(_p([{
            "op": "create_wall", "id": "W1", "p0_mm": [0, 0],
            "p1_mm": [1000, 0],
            "level": {"by": "element_id", "value": 42},
            "type": {"by": "default", "value": "ignored"},
        }]), snapshot={})
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_xy_and_footprint_fields_never_silently_drop_z(self):
        programs = [
            _p([{"op": "create_wall", "id": "W1", "p0_mm": [0, 0, 100],
                 "p1_mm": [1000, 0, 100],
                 "level": {"by": "element_id", "value": 42}}]),
            _p([{"op": "create_floor", "id": "F1",
                 "outline": [[0, 0, 10], [1000, 0, 10], [0, 1000, 10]],
                 "level": {"by": "element_id", "value": 42}}]),
        ]
        for program in programs:
            with self.subTest(op=program["ops"][0]["op"]):
                out = compile_program(program, snapshot={})
                self.assertFalse(out.ok)
                self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_ref_values_are_normalized_before_dag_resolution(self):
        out = compile_program(_p([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [1000, 0], "level": {"by": "ref", "value": " L1 "}},
        ]), snapshot={})
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("Level __lv_W1 = __el_L1", out.csharp)

    def test_dimension_duplicate_refs_are_compared_after_normalization(self):
        out = compile_program(_p([
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [1000, 0], "level": {"by": "ref", "value": "L1"}},
            {"op": "create_dimension", "id": "D1",
             "in_view": {"by": "element_id", "value": 10},
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "ref", "value": " W1 "}],
             "line_at": [0, 0]},
        ]), snapshot={})
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_arbitrarily_large_json_integers_are_typed_not_panics(self):
        huge = 10 ** 1000
        programs = [
            _p([{"op": "create_grid", "id": "G", "p0_mm": [huge, 0],
                 "p1_mm": [0, 1000]}]),
            _p([{"op": "create_text", "id": "T",
                 "in_view": {"by": "element_id", "value": 10},
                 "at": [huge, 0], "content": "x"}]),
            _p([{"op": "grid_array", "id": "M", "origin_mm": [huge, 0],
                 "nx": 1, "ny": 1}]),
        ]
        for program in programs:
            with self.subTest(op=program["ops"][0]["op"]):
                out = compile_program(program)
                self.assertFalse(out.ok)
                self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])

    def test_element_id_is_bounded_to_revit_int64_space(self):
        too_large = (1 << 63)
        programs = [
            _p([{"op": "query_inspect", "id": "Q",
                 "target": {"by": "element_id", "value": too_large}}]),
            _p([{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                 "p1_mm": [1000, 0],
                 "level": {"by": "element_id", "value": too_large}}]),
        ]
        for program in programs:
            out = compile_program(program, snapshot={})
            self.assertFalse(out.ok)
            self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])

    def test_query_element_id_selector_rejects_ignored_kind(self):
        out = compile_program(_p([{
            "op": "query_inspect", "id": "Q",
            "target": {"by": "element_id", "value": 10, "kind": "wall"},
        }]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", [d.code for d in out.diagnostics])

    def test_raw_integer_parameter_is_bounded_to_set_int_overload(self):
        out = compile_program(_p([{
            "op": "set_param", "id": "S",
            "target": {"by": "element_id", "value": 10},
            "param": "P", "value": {"value": 1 << 31, "unit": "raw"},
        }]))
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])
        self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
