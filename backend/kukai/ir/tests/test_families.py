"""ops_families gates (a)(b)(d)(e): create_type (FamilySymbol duplication —
symbol-based categories ONLY, see ops_families.py docstring for the
wall/floor-CompoundStructure scope note) and load_family (Document.LoadFamily
/ LoadFamilySymbol). Typed refusals for every runtime failure mode named in
family-load-place.md / family-geometry-authoring.md; idempotent re-run on a
name collision (ElementType.Duplicate throws otherwise — the wiki's own
DuplicateTypeWithSize lesson)."""
import os
import pathlib
import random
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"


def _prog(ops, intent="families-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _ctype(oid="T1", **kw):
    op = {"op": "create_type", "id": oid,
          "source_type": {"by": "element_id", "value": 500},
          "category": "structural", "new_name": "ЖБ 400x400",
          "width_mm": 400.0}
    op.update(kw)
    return op


def _lfam(oid="F1", **kw):
    op = {"op": "load_family", "id": oid, "path": r"C:\Lib\Columns\RC.rfa"}
    op.update(kw)
    return op


class CreateTypeHappyPath(unittest.TestCase):
    def test_width_and_depth_and_material(self):
        out = compile_program(_prog([_ctype(depth_mm=400.0, material="Бетон")]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('GetParameters("b")', cs)
        self.assertIn('GetParameters("h")', cs)
        self.assertIn("__pws_T1.Count != 1", cs)
        self.assertIn("__pds_T1.Count != 1", cs)
        self.assertIn("U(400.0)", cs)
        self.assertIn("STRUCTURAL_MATERIAL_PARAM", cs)
        self.assertIn("__pm2.AsElementId().ToString() != __mat_T1.Id.ToString()", cs)
        self.assertIn('__results["T1"]', cs)

    def test_width_only_omits_depth_block(self):
        out = compile_program(_prog([_ctype()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('GetParameters("b")', cs)
        self.assertNotIn('GetParameters("h")', cs)
        self.assertNotIn("STRUCTURAL_MATERIAL_PARAM", cs)

    def test_custom_param_names(self):
        out = compile_program(_prog([_ctype(
            param_width_name="Width", param_depth_name="Depth", depth_mm=300.0)]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('GetParameters("Width")', cs)
        self.assertIn('GetParameters("Depth")', cs)
        self.assertNotIn('GetParameters("b")', cs)

    def test_architectural_category_grounds_correct_pool(self):
        out = compile_program(_prog([_ctype(
            source_type={"by": "element_id", "value": 501},
            category="architectural")]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("new ElementId(501)", out.csharp)

    def test_name_resolution_pins_id(self):
        out = compile_program(_prog([_ctype(
            source_type={"by": "name", "value": "К 300x300"})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("new ElementId(500)", out.csharp)


class CreateTypeIdempotency(unittest.TestCase):
    """The wiki's DuplicateTypeWithSize lesson: ElementType.Duplicate(name)
    THROWS ArgumentException on a name already used by a sibling type of the
    same Family. A re-run with the same new_name must reuse, not re-throw."""
    def test_emits_twin_search_before_duplicate(self):
        cs = compile_program(_prog([_ctype()]), snapshot=SNAPSHOT).csharp
        i_twin = cs.index("__twin_T1")
        i_dup = cs.index(".Duplicate(")
        self.assertLess(i_twin, i_dup, "must search for an existing same-name "
                                       "sibling BEFORE calling Duplicate")
        self.assertIn("if (__twin_T1 != null) { __el_T1 = __twin_T1; }", cs)

    def test_duplicate_wrapped_in_try_catch(self):
        cs = compile_program(_prog([_ctype()]), snapshot=SNAPSHOT).csharp
        self.assertIn("try { __el_T1 = __src_T1.Duplicate(", cs)
        self.assertIn("catch (Exception __ex_T1)", cs)

    def test_witness_reports_duplicated_flag(self):
        cs = compile_program(_prog([_ctype()]), snapshot=SNAPSHOT).csharp
        self.assertIn('__rb["duplicated"] = __dupd_T1', cs)


class CreateTypeCommitGateInvariants(unittest.TestCase):
    """Gate (e): the same structural guarantees every authoring op proves
    (SPEC 12.5) — textual-order proofs over generated code."""
    def _cs(self):
        out = compile_program(_prog([_ctype(depth_mm=400.0, material="Бетон")]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_single_transaction(self):
        self.assertEqual(self._cs().count("new Transaction"), 1)

    def test_type_level_stamp_not_instance(self):
        """create_type produces a TYPE — the stamp MUST go on
        ALL_MODEL_TYPE_COMMENTS, never ALL_MODEL_INSTANCE_COMMENTS (types have
        no instance-comments slot in the same sense)."""
        cs = self._cs()
        self.assertIn("ALL_MODEL_TYPE_COMMENTS", cs)

    def test_postconditions_before_commit(self):
        cs = self._cs()
        i_check = cs.index("__post.Count > 0")
        i_commit = cs.index("__t.Commit()")
        self.assertLess(i_check, i_commit)

    def test_rollback_guards_present(self):
        cs = self._cs()
        self.assertGreaterEqual(cs.count("__t.RollBack(); return __Refuse("), 3)

    def test_deterministic_emit(self):
        p = _prog([_ctype(depth_mm=400.0)])
        a = compile_program(p, snapshot=SNAPSHOT).csharp
        b = compile_program(p, snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)


class CreateTypeNegative(unittest.TestCase):
    def test_element_id_selector_pinned_not_snapshot_checked(self):
        """by=element_id is PINNED AS-IS (ground.py's documented contract,
        identical to every sibling authoring op — verified against
        create_wall's own by=element_id behavior): the compiler cannot know
        999999 doesn't exist in the LIVE model at ground time; existence is
        deferred to the emitted null-guard at execute time. This is NOT a
        create_type-specific gap — compiles ok, with the runtime guard
        present in the emitted C#."""
        out = compile_program(_prog([_ctype(
            source_type={"by": "element_id", "value": 999999})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("new ElementId(999999)", cs)
        self.assertIn("source_type не найден (модель изменилась после grounding)", cs)

    def test_source_type_name_not_found_offers_candidates(self):
        out = compile_program(_prog([_ctype(
            source_type={"by": "name", "value": "Нет такой колонны"})]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G101"][0]
        self.assertIn("К 300x300", d.candidates)

    def test_missing_required_new_name(self):
        op = _ctype()
        del op["new_name"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any(c.startswith("KIR-P005") or c.startswith("KIR-T001")
                            for c in [d.code for d in out.diagnostics]))

    def test_missing_required_width(self):
        op = _ctype()
        del op["width_mm"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_width_out_of_bounds(self):
        out = compile_program(_prog([_ctype(width_mm=50000.0)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_bad_category_enum(self):
        out = compile_program(_prog([_ctype(category="wood")]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_new_name_too_long_refused_not_silently_truncated(self):
        out = compile_program(_prog([_ctype(new_name="Ы" * 70)]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_no_snapshot_needed_when_selector_is_pure_element_id(self):
        """_ctype()'s default source_type is by=element_id (pinned, no pool
        read needed) — this matches create_wall's own documented behavior
        (a program grounded ENTIRELY by element_id needs no snapshot at all,
        ground.py's _needs_pool optimization). A snapshot IS required the
        moment a by=name/by=default selector appears — see the sibling test."""
        out = compile_program(_prog([_ctype()]), snapshot=None)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_no_snapshot_is_typed_refusal_when_name_selector_present(self):
        out = compile_program(_prog([_ctype(
            source_type={"by": "name", "value": "К 300x300"})]), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_runtime_lookup_failure_is_typed_rollback_not_silent(self):
        """A named width/depth/material param may not exist on an arbitrary
        family template — this is a RUNTIME fact the family controls, not a
        compile-time-detectable one. The emitted C# must roll back and refuse
        typed, never silently proceed with an unset dimension."""
        cs = compile_program(_prog([_ctype(depth_mm=400.0, material="Бетон")]),
                             snapshot=SNAPSHOT).csharp
        self.assertIn('"параметр «b» (width) не найден или неоднозначен', cs)
        self.assertIn('"параметр «h» (depth) не найден или неоднозначен', cs)
        self.assertIn('"параметр материала (STRUCTURAL_MATERIAL_PARAM) недоступен', cs)
        self.assertIn('"материал «Бетон» не найден в документе"', cs)


class LoadFamilyHappyPath(unittest.TestCase):
    def test_whole_family_load(self):
        out = compile_program(_prog([_lfam()]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.LoadFamily(", cs)
        self.assertIn("File.Exists(", cs)
        # НЕ ``GetFamilySymbolIds()``: он возвращает ``ISet<ElementId>`` из
        # ``System.dll``, которой нет у развёрнутого плагина (CS0012).
        self.assertNotIn("GetFamilySymbolIds()", cs)
        self.assertIn("OfClass(typeof(FamilySymbol))", cs)
        self.assertIn("IsActive", cs)
        self.assertIn('__results["F1"]', cs)

    def test_named_type_uses_loadfamilysymbol(self):
        out = compile_program(_prog([_lfam(type_name="0900x2100")]))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.LoadFamilySymbol(", cs)
        self.assertIn('"0900x2100"', cs)
        self.assertNotIn("doc.LoadFamily(", cs)

    def test_named_type_presearch_is_scoped_to_expected_family(self):
        """A type name is not a document-global identity: many families use
        names such as "Default".  The idempotency presearch must include the
        .rfa family identity before it can skip LoadFamilySymbol."""
        cs = compile_program(_prog([_lfam(type_name="Default")])).csharp
        self.assertIn("Path.GetFileNameWithoutExtension", cs)
        self.assertIn("__c.Family.Name.Equals(__family_name_F1", cs)
        self.assertNotIn("FirstOrDefault(__c => __c.Name", cs)

    def test_whole_family_symbol_choice_is_deterministic(self):
        cs = compile_program(_prog([_lfam()])).csharp
        self.assertIn("OrderBy(__x => __x.Name, StringComparer.Ordinal)", cs)
        self.assertIn("ThenBy(__x => __x.Id.ToString(), StringComparer.Ordinal)", cs)

    def test_no_snapshot_needed(self):
        """load_family references no existing model type by selector — it
        should NOT require a ground snapshot (unlike create_type)."""
        out = compile_program(_prog([_lfam()]), snapshot=None)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])


class LoadFamilyCommitGateInvariants(unittest.TestCase):
    def test_single_transaction(self):
        cs = compile_program(_prog([_lfam()])).csharp
        self.assertEqual(cs.count("new Transaction"), 1)

    def test_file_exists_guard_before_load_call(self):
        cs = compile_program(_prog([_lfam()])).csharp
        i_exists = cs.index("File.Exists(")
        i_load = cs.index("doc.LoadFamily(")
        self.assertLess(i_exists, i_load)

    def test_type_level_stamp(self):
        self.assertIn("ALL_MODEL_TYPE_COMMENTS",
                      compile_program(_prog([_lfam()])).csharp)

    def test_load_wrapped_in_try_catch(self):
        cs = compile_program(_prog([_lfam()])).csharp
        self.assertIn("catch (Exception __ex_F1)", cs)


class LoadFamilyPerOpIsolation(unittest.TestCase):
    """28.07 finding (per_op gate run): compile_program(..., isolation=
    "per_op") declares its own op-scoped sentinel ``bool __ok_<s> = false;``
    in the outer decl block (emit_program's per_op scaffold — one sentinel
    per op, set True on SubTransaction commit). The load_family(type_name=…)
    branch ALSO declared a local ``bool __ok_<s>;`` for the LoadFamilySymbol
    out-parameter, inside its OWN nested block — same name, enclosing scope
    -> Roslyn CS0136 ("__ok_F1 ... used in an enclosing local scope"), live,
    every version. Confirmed against the real 6-version compile service. The
    whole-family branch (no type_name) uses ``__loaded_<s>`` instead and
    never collided."""

    def test_named_type_atomic_bytes_are_the_untouched_golden(self):
        """The fix must be isolation-conditional: atomic emission (no outer
        __ok_<s> sentinel exists in atomic mode) keeps its ORIGINAL variable
        name — this byte shape is a golden, not to be moved by a per_op-only
        fix."""
        cs = compile_program(_prog([_lfam(type_name="0900x2100")])).csharp
        self.assertIn("bool __ok_F1;", cs)
        self.assertIn("__ok_F1 = doc.LoadFamilySymbol(", cs)
        self.assertIn("!__ok_F1 || __sym_F1 == null", cs)

    def test_named_type_per_op_has_no_declaration_collision(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.authoring import emit_program
        from kukai.ir.compiler import _parse_and_check

        grounded = ground_mod.ground(
            _parse_and_check(_prog([_lfam(type_name="0900x2100")])), None)
        cs = emit_program(grounded, "2026", "", isolation="per_op")
        # The per_op scaffold's OWN op-sentinel — exactly one, unconditional.
        self.assertEqual(cs.count("bool __ok_F1 = false;"), 1)
        # The emitter's former inner declaration collided with the sentinel
        # above (same name, enclosing scope) — it must be gone/renamed, not
        # merely duplicated with different initializers.
        self.assertNotIn("bool __ok_F1;", cs)
        # The renamed local must still gate the null-check exactly as before
        # (same guard logic, new name) — not silently dropped.
        self.assertIn("__sym_F1 == null", cs)

    def test_whole_family_per_op_was_never_affected(self):
        """Sanity/no-regression: the no-type_name branch (__loaded_<s>) never
        shared a name with the per_op sentinel — must keep compiling exactly
        as before, atomic AND per_op, byte-identical to its own golden."""
        from kukai.ir import ground as ground_mod
        from kukai.ir.authoring import emit_program
        from kukai.ir.compiler import _parse_and_check

        atomic = compile_program(_prog([_lfam()])).csharp
        self.assertIn("bool __loaded_F1;", atomic)
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_lfam()])), None)
        per_op = emit_program(grounded, "2026", "", isolation="per_op")
        self.assertIn("bool __loaded_F1;", per_op)
        self.assertEqual(per_op.count("bool __ok_F1 = false;"), 1)


class LoadFamilyNegative(unittest.TestCase):
    def test_missing_required_path(self):
        op = _lfam()
        del op["path"]
        out = compile_program(_prog([op]))
        self.assertFalse(out.ok)

    def test_path_too_long_refused(self):
        out = compile_program(_prog([_lfam(path="C:\\" + "x" * 300 + ".rfa")]))
        self.assertFalse(out.ok)

    def test_runtime_missing_file_is_typed_rollback(self):
        """File.Exists is checked INSIDE the emitted C# (execute-time, on the
        bridge host) — ground cannot see the caller's filesystem. Confirm the
        guard text names the exact path so the user gets an actionable typed
        message, matching FAM-034's own File.Exists precondition."""
        cs = compile_program(_prog([_lfam(path=r"C:\Missing\Nope.rfa")])).csharp
        # _cs() is json.dumps(...) -> a single backslash in the Python string
        # is emitted as an escaped \\ in the C# string LITERAL (correct C#);
        # match the literal text that actually appears in the emitted source.
        self.assertIn(r"файл не найден: C:\\Missing\\Nope.rfa", cs)

    def test_empty_family_no_symbols_typed_refusal_text_present(self):
        cs = compile_program(_prog([_lfam()])).csharp
        self.assertIn("семейство не содержит ни одного типоразмера", cs)

    def test_type_not_found_in_file_typed_refusal_text_present(self):
        cs = compile_program(_prog([_lfam(type_name="GhostType")])).csharp
        self.assertIn("типоразмер «GhostType» не найден в файле", cs)


class FamiliesPBT(unittest.TestCase):
    """Property tests (gate a): every generated well-typed create_type/
    load_family program compiles Python-side without refusal, braces
    balance, single transaction, every op id appears as a result key."""
    N = 100
    SEED = 20260717

    def test_create_type_properties(self):
        rng = random.Random(self.SEED)
        # (source_type, category) pairs MUST correlate — id 500/"К 300x300"
        # live in column_symbols_STRUCTURAL, id 501 in ARCHITECTURAL
        # (fixtures.py); a mismatched pair is a legitimate NOT_FOUND, not a
        # property of well-typed IR.
        pairs = [({"by": "element_id", "value": 500}, "structural"),
                 ({"by": "name", "value": "К 300x300"}, "structural"),
                 ({"by": "element_id", "value": 501}, "architectural")]
        for case in range(self.N):
            src, cat = rng.choice(pairs)
            op = _ctype(
                source_type=src, category=cat,
                new_name=f"Тип-{rng.randint(0, 99999)}",
                width_mm=float(rng.randint(50, 2000)))
            if rng.random() < 0.6:
                op["depth_mm"] = float(rng.randint(50, 2000))
            if rng.random() < 0.3:
                op["material"] = rng.choice(["Бетон", "Сталь", "Дерево"])
            out = compile_program(_prog([op], intent="pbt"), snapshot=SNAPSHOT)
            with self.subTest(case=case, op=op):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn('__results["T1"]', cs)

    def test_load_family_properties(self):
        rng = random.Random(self.SEED + 1)
        for case in range(self.N):
            op = _lfam(path=r"C:\Lib\Fam" + str(rng.randint(0, 9999)) + ".rfa")
            if rng.random() < 0.5:
                op["type_name"] = f"Type{rng.randint(0, 999)}"
            out = compile_program(_prog([op], intent="pbt"))
            with self.subTest(case=case, op=op):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn('__results["F1"]', cs)


# ГОЛДЕН-КОРПУС ЭТОЙ ВОЛНЫ СНЯТ 13.08.2026, И ПРИЧИНА НЕ «ЭМИТТЕР УЕХАЛ».
#
# Здесь стоял класс `Golden` с двумя программами — `families_create_type_full`
# и `families_load_family_whole`, — писавшими в ОБЩИЙ каталог `golden/`. Его
# докстринг утверждал дословно: «Own files in the SHARED golden/ dir
# (families_*.golden.cs — no filename collision with any other wave's
# programs)». Утверждение перестало быть верным, и НИЧТО этого не заметило:
# позднейшая волна завела ТЕ ЖЕ ДВА ИМЕНИ в `test_golden.PROGRAMS`.
#
# ЗАМЕР 13.08 на сведённой линии `integration/kir-2026-08-13`:
#
#     имя                          test_families        test_golden
#     families_create_type_full    259 симв. программы  277 симв. — РАЗНЫЕ
#     families_load_family_whole   134 симв. программы  263 симв. — РАЗНЫЕ
#     каталог голденов             один и тот же        один и тот же
#     снимок заземления            один и тот же        один и тот же
#
# Один файл не может удовлетворить обе программы. Байты на диске совпадают с
# `test_golden` — значит `test_families` краснел не «дрейфом эмиссии», а тем,
# что у артефакта ДВА ВЛАДЕЛЬЦА. Перезаморозка сделала бы красным другой тест,
# и так по кругу: это не дрейф, а колебание без сходимости.
#
# Коллизия ПРЕДШЕСТВОВАЛА сведению — она есть на базе `ba36f7bc` и на всех
# четырёх ветках одинаково (проверено `git show` по каждой).
#
# ПОКРЫТИЕ НЕ ПОТЕРЯНО, и это замерено, а не заявлено: набор полей опа в обеих
# редакциях СОВПАДАЕТ поимённо (`create_type`: category/depth_mm/material/
# new_name/source_type/width_mm; `load_family`: path), различаются только
# значения `intent` и `path`, ни одно из которых не выбирает ветку эмиттера.
# Богаче — редакция `test_golden`, она и осталась единственным владельцем.
#
# Чтобы утверждение из старого докстринга перестало быть прозой, заведён
# сторож: `test_golden_files_have_one_owner.py` требует, чтобы каждый файл
# `golden/*.golden.cs` заявлялся РОВНО ОДНИМ корпусом.


class NegativeCorpus(unittest.TestCase):
    """Gate (d): malformed IR -> typed diagnostics, never an exception."""
    CASES = [
        (_prog([{"op": "create_type", "id": "T1"}]), "KIR-P005"),   # everything missing but op/id
        (_prog([{"op": "create_type", "id": "T1", "source_type": "not-a-selector",
                 "new_name": "X", "width_mm": 400}]), "KIR-T001"),
        (_prog([{"op": "load_family", "id": "F1"}]), "KIR-P005"),
        (_prog([{"op": "load_family", "id": "F1", "path": 12345}]), "KIR-T001"),
        (_prog([_ctype(), {"op": "query_count", "kind": "wall", "id": "q"}]), "KIR-L002"),  # mixed families
    ]

    def test_corpus(self):
        for prog, want in self.CASES:
            with self.subTest(want=want, prog=str(prog)[:80]):
                out = compile_program(prog, snapshot=SNAPSHOT)  # must never raise
                self.assertFalse(out.ok)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes, f"compiler panic: {codes}")
                self.assertTrue(any(c.startswith(want) for c in codes),
                                f"want {want}, got {codes}")


class Injection(unittest.TestCase):
    """Nasty strings must arrive escaped in emitted C#, never as live code."""
    def test_new_name_injection_escaped(self):
        nasty = '"); doc.Delete(new ElementId(1)); ("'
        out = compile_program(_prog([_ctype(new_name=nasty[:60])]), snapshot=SNAPSHOT)
        # either a typed refusal (len/shape) or a compiled program with the
        # string safely escaped — never live injected code.
        if out.ok:
            code_only = re.sub(r'"(?:[^"\\]|\\.)*"', '""', out.csharp)
            self.assertNotIn("doc.Delete(new ElementId(1))", code_only)

    def test_path_injection_escaped(self):
        nasty = r'C:\Lib\"); doc.Delete(new ElementId(1)); ("'
        out = compile_program(_prog([_lfam(path=nasty)]))
        if out.ok:
            code_only = re.sub(r'"(?:[^"\\]|\\.)*"', '""', out.csharp)
            self.assertNotIn("doc.Delete(new ElementId(1))", code_only)


if __name__ == "__main__":
    unittest.main()
