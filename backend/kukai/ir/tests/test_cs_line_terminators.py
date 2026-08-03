"""C# line terminators inside emitted string literals.

JSON escaping covers CR/LF but leaves U+0085/U+2028/U+2029 raw, and C# counts
all three as line terminators: a literal ends mid-string and its tail becomes
source.  Before the fix the compiler answered ``ok=True`` with an empty
diagnostics list while emitting C# that cannot compile.
"""
import importlib
import json
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.emit_utils import cs_string_literal  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

# Written as codepoints on purpose: the raw characters are invisible in a diff.
LINE_SEPARATOR = chr(0x2028)
PARAGRAPH_SEPARATOR = chr(0x2029)
NEXT_LINE = chr(0x0085)
TERMINATORS = (LINE_SEPARATOR, PARAGRAPH_SEPARATOR, NEXT_LINE)


def _wall_program(op_id):
    return {"ir_version": "1.0", "intent": "line-terminator-test", "ops": [
        {"op": "create_wall", "id": op_id, "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "height_mm": 3000, "level": {"by": "name", "value": "Этаж 1"},
         "type": {"by": "element_id", "value": 901}}]}


def _unbalanced_quote_lines(csharp):
    """Lines whose string literals do not close — a split literal."""
    return [line for line in csharp.splitlines()
            if (line.count('"') - line.count('\\"')) % 2]


class LineTerminatorsNeverReachEmittedSource(unittest.TestCase):
    def test_separator_in_op_id_does_not_split_a_literal(self):
        for terminator in TERMINATORS:
            with self.subTest(codepoint=f"U+{ord(terminator):04X}"):
                out = compile_program(
                    _wall_program("W" + terminator + "1"),
                    snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
                self.assertNotIn(terminator, out.csharp)
                self.assertEqual(_unbalanced_quote_lines(out.csharp), [])

    def test_success_is_not_reported_over_unemittable_source(self):
        """The regression itself: ok=True plus a broken literal."""
        out = compile_program(
            _wall_program("W" + LINE_SEPARATOR + "1"),
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertEqual(out.diagnostics, [])
        for terminator in TERMINATORS:
            self.assertNotIn(terminator, out.csharp)

    def test_query_filter_uses_the_same_literal_boundary(self):
        for terminator in TERMINATORS:
            with self.subTest(codepoint=f"U+{ord(terminator):04X}"):
                out = compile_program({
                    "ir_version": "1.0",
                    "ops": [{
                        "op": "query_count",
                        "id": "q",
                        "kind": "wall",
                        "where": {"name_contains": "A" + terminator + "B"},
                    }],
                })
                self.assertTrue(
                    out.ok, [item.as_dict() for item in out.diagnostics])
                self.assertNotIn(terminator, out.csharp)

    def test_snapshot_parameter_projection_uses_shared_boundary(self):
        from kukai.ir import serving

        code = serving._snapshot_cs({
            "disambiguate_by": {
                "param": "A" + LINE_SEPARATOR + "B",
            },
        })
        self.assertNotIn(LINE_SEPARATOR, code)
        self.assertIn(r'"A\u2028B"', code)

    def test_reverse_emitters_delegate_to_shared_boundary(self):
        helpers = (
            ("mep_system_extract", "_csharp_string"),
            ("sketch_extract", "_csharp_string"),
            ("geom_extract", "_csharp_string"),
            ("annotation_extract", "_csharp_string"),
            ("family_placement_extract", "_csharp_string"),
            ("recompile", "_cs_string"),
            ("side_contract", "csharp_string"),
            ("tag_extract", "_csharp_string"),
            ("group_extract", "_csharp_string"),
            ("curtain_extract", "_csharp_string"),
            ("curve_extract", "_csharp_string"),
        )
        value = "A" + NEXT_LINE + LINE_SEPARATOR + PARAGRAPH_SEPARATOR + "B"
        expected = cs_string_literal(value)
        for module_name, helper_name in helpers:
            with self.subTest(module=module_name):
                module = importlib.import_module(
                    "kukai.ir.decompile." + module_name)
                self.assertEqual(getattr(module, helper_name)(value), expected)


class StringLiteralEscaping(unittest.TestCase):
    def test_terminators_become_c_sharp_escapes(self):
        self.assertEqual(cs_string_literal("a" + LINE_SEPARATOR + "b"),
                         '"a\\u2028b"')
        self.assertEqual(cs_string_literal("a" + PARAGRAPH_SEPARATOR + "b"),
                         '"a\\u2029b"')
        self.assertEqual(cs_string_literal("a" + NEXT_LINE + "b"),
                         '"a\\u0085b"')

    def test_ordinary_text_stays_byte_identical(self):
        """Byte-parity: only the three raw terminators may change."""
        for value in ("Этаж 1", "wall", 'quote " inside', "tab\tseparated",
                      "line\nbreak", "carriage\rreturn", "", "back\\slash"):
            with self.subTest(value=value):
                self.assertEqual(cs_string_literal(value),
                                 json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
