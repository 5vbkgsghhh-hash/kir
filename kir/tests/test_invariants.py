"""Gate (e): runtime-invariant checklist for the query family + registry/schema
sanity (SPEC 12.6, revit-mcp practitioner categories)."""
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import spec, schema_gen  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.spec import export_capability_cells  # noqa: E402


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

    def test_catalog_selectors_advertise_ref_exactly_when_it_is_creatable(self):
        """A catalog selector offers `ref` EXACTLY WHEN there is an op that
        creates an element of that kind.

        🔴 THREE LITERALS STOOD HERE, AND THEY WENT STALE IN ONE COMMIT.
        The claim, verbatim: `create_wall.level` HAS a reference,
        `create_wall.type` does NOT, and neither staircase level has one.
        The reasoning was correct — "reference emission for catalog pools
        is not written" — but it was recorded as an enumeration, not as a
        law.

        On 23.08.2026 `create_wall_type` appeared, a wall type became
        creatable within the same program, and `_emit_wall` gained a
        `via == "ref"` branch (`WallType __wt = __el_<ref>`). The literal
        `assertNotIn("ref", kinds(wall["type"]))` turned red — correct to
        the letter and wrong in substance: the emission was written, the
        invariant simply didn't know about it.

        A law instead of an enumeration: the registry declares `ref_kinds`
        on the selector, and the schema must match the registry exactly;
        and a kind declared in `ref_kinds` must be PRODUCED by someone —
        otherwise the program offers the model an addressing scheme with
        nowhere for it to come from. The three previous cases remain
        checked: they are derived from the law, not enumerated.

        🔴 WHICH HALF DOES THE WORK, AND WHICH GUARDS THE FUTURE — SAID OUT
        LOUD. The first (schema == registry) checks 93 `sel` parameters, 44
        of which declare `ref`; it turns red on any divergence, and that is
        its job today. The second (kind is producible) is EMPTY as of
        23.08.2026: all five reference kinds have a creating op, so there
        is nothing for it to turn red on. It is not decoration — it will
        come alive the day someone declares `ref` for a kind with no
        creator — but it must not be passed off as a working check. This
        tree has already caught a control that is green BY CONSTRUCTION
        three times today; here it is named, not hidden.
        """
        schemas = {sub["properties"]["op"]["const"]: sub
                   for sub in schema_gen.program_schema()
                   ["properties"]["ops"]["items"]["oneOf"]
                   if "const" in sub.get("properties", {}).get("op", {})}

        # KINDS ARE TAKEN FROM THE WHOLE OP, NOT FROM A SINGLE `result`
        # (24.08.2026). `create_wall_type` produces FOUR kinds — which one
        # is decided by `host_kind`. An instrument reading only `result`
        # here would declare `create_floor.type` as advertising a
        # nonexistent producer and would turn red against a CORRECT
        # registry: the law would hold, and the instrument would lie —
        # exactly the class of defect this file catches.
        creatable = {rspec.reference_kind
                     for op in spec.OPS.values()
                     if op.effect.value == "create"
                     for rspec in op.result_kinds if rspec.referenceable}

        checked = 0
        for op_name, ospec in spec.OPS.items():
            sub = schemas.get(op_name)
            if sub is None:
                continue
            for p in (ospec.params or ()):
                if p.kind != "sel":
                    continue
                node = sub["properties"].get(p.name)
                if not isinstance(node, dict) or "oneOf" not in node:
                    continue
                by = {v["properties"]["by"]["const"] for v in node["oneOf"]
                      if "const" in v.get("properties", {}).get("by", {})}
                declared = bool(getattr(p, "ref_kinds", ()) or ())
                self.assertEqual(
                    "ref" in by, declared,
                    f"{op_name}.{p.name}: схема и реестр разошлись по `ref`")
                for kind in (getattr(p, "ref_kinds", ()) or ()):
                    self.assertIn(
                        kind, creatable,
                        f"{op_name}.{p.name} предлагает ref({kind.value}), "
                        "а создать элемент этого рода нечем")
                checked += 1
        self.assertGreater(checked, 20, "закон проверен на слишком малом числе")

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
