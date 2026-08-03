"""Gate (e): runtime-invariant checklist for the query family + registry/schema
sanity (SPEC 12.6, revit-mcp practitioner categories)."""
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import spec, schema_gen  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.spec import export_capability_cells  # noqa: E402


def _emit_everything() -> str:
    ops = []
    for i, kind in enumerate(sorted(spec.KINDS)):
        ops.append({"op": "query_list", "id": f"l{i}", "kind": kind,
                    "where": {"level_name": "Этаж 1", "name_contains": "а"}})
    emitted = []
    for offset in range(0, len(ops), 20):
        out = compile_program({"ir_version": "1.0", "ops": ops[offset:offset + 20]})
        assert out.ok, out.as_dict()
        emitted.append(out.csharp)
    return "\n".join(emitted)


class RuntimeInvariants(unittest.TestCase):
    def test_transactions_none(self):
        """Category 'transactions'/'model state': queries are read-only by
        construction — no Transaction/write API may appear as CODE (string
        literals and comments are stripped before the scan)."""
        cs = _emit_everything()
        cs = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cs)   # blank string literals
        cs = re.sub(r'//[^\n]*', '', cs)              # strip line comments
        for tok in ("Transaction", "doc.Delete", "doc.Create", ".Activate(",
                    "Regenerate", "SaveAs"):
            self.assertNotIn(tok, cs)

    def test_selection_untouched(self):
        self.assertNotIn("Selection", _emit_everything())

    def test_units_mm_only(self):
        """Category 'units': every length leaving the program is converted via
        UnitTypeId.Millimeters; no magic 0.3048/304.8 constants."""
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_inspect", "id": "i",
             "target": {"by": "element_id", "value": 12345}}]})
        cs = out.csharp
        self.assertIn("UnitTypeId.Millimeters", cs)
        self.assertNotIn("0.3048", cs)
        self.assertNotIn("304.8", cs)

    def test_version_safe_id_handling(self):
        """Category 'version drift': element ids surface as .ToString() only —
        IntegerValue (removed 2026) and .Value (absent <=2023) are banned."""
        cs = _emit_everything()
        self.assertNotIn("IntegerValue", cs)
        self.assertNotIn(".Id.Value", cs)

    def test_query_prefixes_are_deterministically_ordered(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_list", "id": "q", "kind": "wall", "limit": 1}]})
        self.assertTrue(out.ok)
        self.assertIn(".OrderBy(e => __IdOf(e))", out.csharp)
        self.assertLess(out.csharp.index(".OrderBy(e => __IdOf(e))"),
                        out.csharp.index(".Take(1)"))

    def test_query_types_are_deterministically_ordered(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_types", "id": "q", "pool": "wall_types"}]})
        self.assertTrue(out.ok)
        self.assertIn(".Cast<Element>().OrderBy(e => __IdOf(e)).ToList()", out.csharp)


class RegistryAndSchema(unittest.TestCase):
    def test_schema_generates_and_is_closed(self):
        s = schema_gen.program_schema()
        self.assertEqual(s["properties"]["ir_version"]["const"], spec.IR_VERSION)
        self.assertFalse(s["additionalProperties"])
        for sub in s["properties"]["ops"]["items"]["oneOf"]:
            self.assertFalse(sub["additionalProperties"], "op schemas must be closed")
        # escape value present in every kind enum (SPEC 12.8)
        for sub in s["properties"]["ops"]["items"]["oneOf"]:
            kind = sub["properties"].get("kind")
            if kind:
                self.assertIn(spec.KIND_ESCAPE, kind["enum"])

    def test_catalog_selectors_do_not_advertise_unimplemented_ref_emission(self):
        schemas = {sub["properties"]["op"]["const"]: sub
                   for sub in schema_gen.program_schema()["properties"]["ops"]["items"]["oneOf"]
                   if "const" in sub.get("properties", {}).get("op", {})}
        wall = schemas["create_wall"]["properties"]
        kinds = lambda node: {v["properties"]["by"]["const"]
                              for v in node["oneOf"]}
        self.assertIn("ref", kinds(wall["level"]))
        self.assertNotIn("ref", kinds(wall["type"]))
        stairs = schemas["create_stairs"]["properties"]
        self.assertNotIn("ref", kinds(stairs["base_level"]))
        self.assertNotIn("ref", kinds(stairs["top_level"]))

    def test_selector_schema_encodes_int64_id_and_shape_laws(self):
        schemas = {sub["properties"]["op"]["const"]: sub
                   for sub in schema_gen.program_schema()["properties"]["ops"]["items"]["oneOf"]}
        level = schemas["create_wall"]["properties"]["level"]
        id_variant = next(v for v in level["oneOf"]
                          if v["properties"]["by"]["const"] == "element_id")
        self.assertEqual(id_variant["properties"]["value"]["maximum"],
                         (1 << 63) - 1)
        default_variant = next(v for v in level["oneOf"]
                               if v["properties"]["by"]["const"] == "default")
        self.assertNotIn("value", default_variant["properties"])
        name_variant = next(v for v in level["oneOf"]
                            if v["properties"]["by"]["const"] == "name")
        disambiguator = name_variant["properties"]["disambiguate_by"]
        self.assertEqual(disambiguator["required"], ["param", "value"])
        self.assertFalse(disambiguator["additionalProperties"])
        self.assertNotIn(
            "disambiguate_by", id_variant["properties"],
            "a pinned element_id is already unambiguous and must not filter a pool")

    def test_capability_export(self):
        cells = export_capability_cells()
        covered = [c for c in cells if c["status"] == "covered-by-IR"]
        self.assertTrue(all(c["action"] and c["object_kind"] for c in covered),
                        "bare cells banned (13.2)")
        self.assertTrue(any(c["action"] == "count" for c in covered))
        route_only = [c for c in cells if c["status"] == "route-only"]
        self.assertEqual(route_only[0]["action"], "consult")

    def test_vocab_deltas_exported(self):
        self.assertIn("geometry", spec.OBJECT_KINDS_ADDED)
        self.assertIn("document", spec.OBJECT_KINDS_ADDED)


if __name__ == "__main__":
    unittest.main()
