"""Gate (a): property-based tests, well-typed-by-construction generator
(SPEC 12.6b — generate from the typing judgment, don't generate-and-filter).
Dependency-free (hypothesis not in prod venv): seeded deterministic PRNG.

Properties, for every generated well-typed program:
  P1  compile_program returns ok (compiler never refuses well-typed IR);
  P2  emitted C# contains NO write-API tokens (query family read-only
      invariant — gate (e) categories: transactions, model state, selection);
  P3  braces balance; exactly one trailing `return __results;`;
  P4  every op id appears as a result key literal;
  P5  compiler never raises (also covered for arbitrary junk in test_negative).
"""
import os
import random
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import spec  # noqa: E402
from kir.compiler import compile_program  # noqa: E402

FORBIDDEN = [
    "new Transaction", "TransactionGroup", "SubTransaction", ".Start(",
    ".Commit(", ".RollBack(", "doc.Delete", ".Delete(", "doc.Create",
    "Create.New", ".Activate(", "SetElementIds", "doc.Regenerate",
    "Document.SaveAs", "File.", "Process.", "Registry.",
]

NASTY_STRINGS = [
    "Стена", 'a"b', "a\\b", "100%", "…", "line1\nline2", "\t", "'quote'",
    '"); doc.Delete(new ElementId(1)); ("', "мм_санузел", "𝓌𝒶𝓁𝓁",
]


#: The view pool for SEEDED generation — frozen on purpose.
#:
#: `gen_program` is used twice: in live property tests (where the pool does
#: not matter) and in the byte-parity corpus, where programs are generated
#: from a fixed seed and their emission is frozen by hashes. As long as the
#: pool was read straight from `spec.KINDS`, adding ANY kind changed the
#: generator's choice for the same seed — and 162 frozen emissions
#: "diverged" even though the emitter had not changed by a single byte
#: (confirmed 27.07: the same 25 programs, generated from the earlier
#: 21-kind set, gave 150 matches and 0 discrepancies on the NEW code).
#:
#: A ratchet that clicks from a neighboring table's growth teaches people to
#: stamp INTENDED_CHANGES without looking — and stops catching what it was
#: built for. So the pool is pinned to the composition the corpus was frozen
#: with. New kinds are still covered by the corpus anyway — as separate
#: `allkinds:` entries, one per kind, and those are ADDITIVE.
FROZEN_QUERY_KINDS: tuple[str, ...] = (
    "cable_tray", "cad_import", "cad_link", "ceiling", "column_architectural",
    "column_structural", "door", "duct", "floor", "grid", "image", "level",
    "pdf_underlay", "pipe", "roof", "room", "sheet", "stair", "view", "wall",
    "window",
)


def gen_program(rng: random.Random) -> dict:
    # sorted() kept verbatim: the pool's order is part of the seeded choice.
    kinds = sorted(k for k in FROZEN_QUERY_KINDS if k in spec.KINDS)
    ops = []
    for i in range(rng.randint(1, 8)):
        choice = rng.random()
        base = {"id": f"op{i}_{rng.randint(0, 999)}"}
        where = {}
        if rng.random() < 0.5:
            where["name_contains"] = rng.choice(NASTY_STRINGS)
        if rng.random() < 0.3:
            where["level_name"] = rng.choice(NASTY_STRINGS)
        if choice < 0.45:
            base.update({"op": "query_count", "kind": rng.choice(kinds)})
            if where:
                base["where"] = where
        elif choice < 0.9:
            nf = rng.randint(1, len(spec.LIST_FIELDS))
            base.update({
                "op": "query_list", "kind": rng.choice(kinds),
                "fields": rng.sample(list(spec.LIST_FIELDS), nf),
                "limit": rng.randint(1, spec.LIST_LIMIT_MAX),
            })
            if where:
                base["where"] = where
        else:
            if rng.random() < 0.5:
                base.update({"op": "query_inspect",
                             "target": {"by": "element_id",
                                        "value": rng.randint(1, 2**40)}})
            else:
                # target names must be non-empty after strip (typing judgment);
                # nasty-but-nonblank strings still exercise escaping.
                nonblank = [s for s in NASTY_STRINGS if s.strip()]
                base.update({"op": "query_inspect",
                             "target": {"by": "name",
                                        "value": rng.choice(nonblank),
                                        "kind": rng.choice(kinds)}})
        ops.append(base)
    return {"ir_version": "1.0", "intent": "pbt", "ops": ops}


class QueryFamilyProperties(unittest.TestCase):
    N = 300
    SEED = 20260716

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            prog = gen_program(rng)
            with self.subTest(case=case):
                out = compile_program(prog)
                self.assertTrue(out.ok, f"P1 refused well-typed: "
                                        f"{[d.as_dict() for d in out.diagnostics][:2]}")
                cs = out.csharp
                # P2 scans CODE only: string literals are blanked first, so an
                # escaped user string containing 'doc.Delete(' is fine (it is
                # data), while the same token as live code is a red failure.
                code_only = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cs)
                for tok in FORBIDDEN:
                    self.assertNotIn(tok, code_only, f"P2 forbidden token {tok!r}")
                self.assertEqual(cs.count("{"), cs.count("}"), "P3 braces")
                self.assertTrue(cs.rstrip().endswith("return __results;"), "P3 return")
                for op in prog["ops"]:                          # P4
                    self.assertIn(f'__results[{_cs(op["id"])}]', cs, "P4 result key")

    def test_all_kinds_compile_standalone(self):
        """Every kind in the table gets at least one direct emit exercise."""
        for kind in spec.KINDS:
            with self.subTest(kind=kind):
                out = compile_program({"ir_version": "1.0", "ops": [
                    {"op": "query_count", "kind": kind, "id": "k"},
                    {"op": "query_list", "kind": kind, "id": "l", "limit": 5},
                ]})
                self.assertTrue(out.ok)


def _cs(s: str) -> str:
    import json
    return json.dumps(s, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
