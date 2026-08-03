"""group_by on query_count — the single largest live read-failure mode, landed.

Motive, measured 2026-07-28 (own re-derivation from data/telemetry):

    kir_shadow.jsonl (kir-shadow rows, the query_model feasibility shadow):
    583 rows, 363 mappable=false, and group_by is the SOLE blocking feature
    on 307 of them (any-cause 323) — "Сколько стен по типам" ("how many
    walls by type") dwarfs every kind gap combined (91 UNSUPPORTED_KIND rows
    total in kir_rejections.jsonl, ALL causes).

History: this file began life as a TRIPWIRE pinning the typed refusal
(KIR-P003, field_name='group_by', candidates=['id','kind','op','where'] —
measured live 2026-07-28, query_id groupby-probe-1) while compiler.py was
off-limits as another wave's dirty file. The draft patch was prepared and
Roslyn 6/6-verified against a scratch copy the same night. On 2026-07-29 the
operator confirmed the dirty files were our own, the defaults/stack.transform
hunks landed in HEAD (ebe1bd18), and the patch was applied — these tests
flipped from asserting the refusal to asserting the capability, exactly as
the tripwire design intended.
"""
import unittest

from kukai.ir.compiler import compile_program


class GroupByIsACapabilityNotAGuess(unittest.TestCase):
    def test_query_count_group_by_compiles_to_grouped_count(self):
        """The exact program that refused on 2026-07-28 now compiles: a
        grouped Dictionary<string,int> count, not a silent plain count."""
        out = compile_program({
            "ir_version": "1.0",
            "intent": "сколько стен по типам",
            "ops": [{"op": "query_count", "id": "q0", "kind": "wall",
                     "group_by": "type_name"}],
        }, query_id="groupby-probe-1")
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertIn("__groups", out.csharp)
        self.assertNotIn("KIR-P003", [d.code for d in out.diagnostics])

    def test_group_by_vocabulary_is_closed(self):
        """group_by is a CLOSED enum reusing _emit_row's field vocabulary —
        a free-string grouping would be a silent-wrong count. An unknown
        value stays a typed refusal."""
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q0", "kind": "wall",
                     "group_by": "definitely_not_a_field"}],
        }, query_id="groupby-probe-3")
        self.assertFalse(out.ok)
        self.assertIsNone(out.csharp)

    def test_query_list_group_by_is_still_a_typed_unknown_field(self):
        """query_list deliberately did NOT grow group_by (the live evidence —
        kir_shadow's group_by rows and kir_rejections' op_requested='count'
        rows — is a grouped-COUNT need; a grouped LIST is a distinct,
        unevidenced ask). The refusal stays typed."""
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_list", "id": "q0", "kind": "door",
                     "group_by": "level_name"}],
        }, query_id="groupby-probe-2")
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertIn("KIR-P003", codes)

    def test_ungrouped_query_count_unaffected(self):
        """Byte-parity smoke: a program that never mentions group_by must be
        untouched by the capability landing."""
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q0", "kind": "wall"}],
        }, query_id="groupby-smoke-1")
        self.assertTrue(out.ok)
        self.assertIn('__r["count"]', out.csharp)
        self.assertNotIn("__groups", out.csharp)


if __name__ == "__main__":
    unittest.main()
