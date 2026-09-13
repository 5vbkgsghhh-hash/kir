"""ONE QUESTION — ONE ANSWER. Two dictionaries and one wire, 10.08.2026.

Both defects below are the same trouble, named by the operator at the start
of the session: the work was done twice, because nobody held the whole
compiler in their head. Here it is measured and closed with a test.

  1. "Which Revit category this op's result will fall into" was known by
     TWO dictionaries: `acceptance._OP_CATEGORIES` (43 ops, tuples) and
     `clash_bundle.OP_CATEGORY` (29 ops, strings). Worse: `spec.
     op_census_categories` asked the answer FROM THE ACCEPTANCE JUDGE — the
     registry depended on its own consumer. The table moved into the
     registry; the second dictionary is named a debt and is held by the
     test below.

  2. A refusal code on the wire promises the consumer ONE fix. Six codes
     carried several different names each; the worst was `KIR-T003`, which
     was simultaneously `TYPE_BAD_ENUM` and `TYPE_GEOM_RELATION` in ONE
     file, twelve lines apart.
"""
from __future__ import annotations

import ast
import inspect
import io
import os
import re
import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_one_answer_queue.jsonl"))

from kir import acceptance as A  # noqa: E402
from kir import diag  # noqa: E402
from kir import spec  # noqa: E402
from kir.analysis_emit import ANALYSIS_ZERO_LOAD  # noqa: E402
from kir.macros import MACRO_ERROR  # noqa: E402
from kir.mesh import MESH_DISCONNECTED  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# 1. ONE CATEGORY TABLE, AND THE REGISTRY OWNS IT
# ═════════════════════════════════════════════════════════════════════════

def _consumer_references(source):
    """Import/call syntax, not historical mentions in comments or docstrings."""
    found = []
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if isinstance(node, ast.ImportFrom):
            if node.module == "kir.acceptance" or (node.level and node.module == "acceptance") or (
                    (node.module == "kir" or node.level and node.module is None)
                    and any(item.name == "acceptance" for item in node.names)):
                found.append("import")
        elif isinstance(node, ast.Import) and any(item.name == "kir.acceptance" for item in node.names):
            found.append("import")
        elif isinstance(node, ast.Name) and node.id == "acceptance":
            found.append("reference")
        elif isinstance(node, ast.Call) and node.args:
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in {"__import__", "import_module"} and isinstance(node.args[0], ast.Constant):
                if node.args[0].value == "kir.acceptance":
                    found.append("dynamic import")
    return found


class OneCategoryTableOwnedByTheRegistry(unittest.TestCase):

    def test_the_judge_reads_the_registry_rather_than_holding_a_copy(self):
        """REFUTATION. Before the fix, the table lived in `acceptance`, and
        `spec` took its answer FROM THERE. Now there is exactly one object,
        and acceptance looks at it."""
        self.assertIs(A._OP_CATEGORIES, spec.OP_RESULT_CATEGORIES)
        self.assertEqual(A._category_of_op({"op": "create_wall"}),
                         ("OST_Walls",))

    def test_the_registry_no_longer_imports_its_own_consumer(self):
        """AN ARCHITECTURAL LOCK. `spec.op_census_categories` used to import
        `acceptance._category_of_op` — the registry asked the acceptance
        judge for the category. The dependency direction must run the other
        way."""
        for function in (spec.op_census_categories, spec.op_disciplines):
            self.assertEqual(_consumer_references(inspect.getsource(function)), [])
        with patch.object(A, "_category_of_op", side_effect=AssertionError("consumer called")), \
                patch.object(A, "_OPS_WITHOUT_ELEMENTS", object()):
            self.assertEqual(spec.op_census_categories(spec.OPS["create_wall"]), ("OST_Walls",))
            self.assertEqual(spec.op_disciplines(spec.OPS["set_param"])[0], ("shared",))
            self.assertTrue(spec.op_disciplines(spec.OPS["create_wall"])[0])
        with patch.object(spec, "op_result_categories", return_value=("registry_answer",)) as owner:
            self.assertEqual(spec.op_census_categories(spec.OPS["create_wall"]), ("registry_answer",))
            owner.assert_called_once_with({"op": "create_wall"})

    def test_reverse_dependency_control_ignores_prose_but_detects_imports_and_calls(self):
        self.assertEqual(_consumer_references('"acceptance used to own this"\n# from kir.acceptance import X\n'), [])
        for source in ("from kir.acceptance import _category_of_op as owner",
                       "from .acceptance import _category_of_op as owner", "from . import acceptance as owner",
                       "from kir import acceptance as owner", "import kir.acceptance as owner",
                       "acceptance._category_of_op({})", "importlib.import_module('kir.acceptance')"):
            self.assertTrue(_consumer_references(source), source)

    def test_the_authority_of_element_less_ops_is_one_object(self):
        """A SECOND MOVE BY THE SAME TURN (28.08.2026), and it is held the
        same way.

        `_OPS_WITHOUT_ELEMENTS` used to live with acceptance, and the
        registry asked for it through a lazy import — that is, from its own
        consumer. The list moved into the registry, an ALIAS is left here.
        Identity is checked, not assumed: a copy would drift from the
        original SILENTLY on the very first new op, and that is exactly the
        defect the move was made against.
        """
        self.assertIs(A._OPS_WITHOUT_ELEMENTS, spec.OPS_WITHOUT_ELEMENTS)
        self.assertNotIn("acceptance",
                         inspect.getsource(spec.group_member_yields_one))

    def test_the_resolver_still_answers_every_enum_branch(self):
        """Five ops resolve their category through THEIR OWN closed
        enumeration. The move had to carry the resolver along too, or the
        table would answer incompletely."""
        cases = {
            ("create_column", None): ("OST_StructuralColumns",),
            ("create_column", "architectural"): ("OST_Columns",),
            ("create_opening", "wall_rect"): ("OST_SWallRectOpening",),
            ("create_topography", "toposolid"): ("OST_Toposolid",),
            ("create_foundation", "isolated"): ("OST_StructuralFoundation",),
        }
        for (op_name, choice), expected in cases.items():
            with self.subTest(op=op_name, choice=choice):
                probe = {"op": op_name}
                if choice is not None:
                    key = ("category" if op_name == "create_column"
                           else "variety")
                    probe[key] = choice
                self.assertEqual(spec.op_result_categories(probe), expected)

    def test_no_writing_op_falls_into_silence(self):
        """THERE IS NO GAP — THERE IS A NAMED ABSENCE, and these are
        different things.

        The measurement "15 writing ops are in NEITHER of the two category
        tables" is true and misleading: it compares two registers out of
        four. An op with no category entry is named either blind for the
        census (`_OPS_BLIND`), or as creating no element at all
        (`_OPS_WITHOUT_ELEMENTS`), or is resolved by the resolver's branch.
        Writing a category in for such an op would make acceptance WAIT for
        a category addition it never observes — that is, fail an honest
        build."""
        writing = {name for name, op in spec.OPS.items() if op.writes_model}
        # 🔴 THE LIST IS ASKED FROM THE REGISTRY, NOT MAINTAINED HERE
        # (21.08.2026). Eight names used to stand here by hand, and THREE of
        # them were from the DirectShape family. The free-form wave of
        # 20.08 opened four more ops of the same family
        # (`create_solid_blend`, `create_solid_sweep`, `create_surface`,
        # `create_solid_boolean`) — with the same category enumeration and
        # the same DirectShape — and this list never found out about them.
        # The test stayed red for TWO DAYS, calling them "named by no
        # register," even though the resolver's branch would have resolved
        # them perfectly well.
        #
        # The handwritten half was a SECOND CARRIER of the same trait that
        # lives in `spec._directshape_result_ops()`: "the op has a
        # `category` parameter with the closed DIRECTSHAPE_CATEGORIES
        # table." An eighth op of the same shape will land here BY ITSELF.
        branch_resolved = set(spec._directshape_result_ops()) | {
            # These four are resolved by THEIR OWN branch, each by its own
            # trait, and there is nothing to derive them from in the
            # registry: a column's category comes from a closed
            # enumeration with a default, a foundation's from its kind, a
            # group and an opening have no category at all.
            "create_column", "create_foundation",
            "create_group", "create_opening", "create_topography",
        }
        named = (set(spec.OP_RESULT_CATEGORIES) | set(A._OPS_BLIND)
                 | set(A._OPS_WITHOUT_ELEMENTS) | branch_resolved)
        self.assertEqual(writing - named, set(),
                         "пишущий оп не назван ни одним регистром")
        self.assertEqual(named - writing, set(),
                         "регистр называет несуществующий оп")

    def test_no_second_stored_answer_to_the_category_question_exists(self):
        """THE DEBT IS CLOSED, AND THE RATCHET NOW GUARDS THE SHAPE, NOT THE
        NAME (11.08.2026).

        A ratchet on `clash_bundle.OP_CATEGORY` used to stand here: while
        the duplicate was alive, there had to be exactly one discrepancy
        (`create_railing`). The duplicate was migrated, and the ratchet
        failed with `ImportError` — and along with it three other
        completeness guards that read the same table fell silent.

        WHY NOT `hasattr(CB, "OP_CATEGORY")`, LIKE THE NEIGHBOR. A ban by
        NAME cannot name the next move and catches exactly one spelling: a
        second table named `OP_CATS` or `_CATEGORY_BY_OP` would slip past
        it silently — that is, the instrument would cover only part of its
        own range. What is banned is the SHAPE: any module-level mapping
        "op name -> Revit category," except for the named exceptions. An
        exception is also a decision: to add an entry, you must write it
        in here and explain it.
        """
        from kir import clash_bundle as CB

        #: The only permitted op -> category mapping, and it is NOT a
        #: second answer: the registry stays silent on these ops or answers
        #: with several, and the entry names the choice out loud (see the
        #: `REGISTRY_GAPS` header).
        allowed = {"REGISTRY_GAPS"}
        ops = set(spec.OPS)
        stored: set[str] = set()
        for attr, value in vars(CB).items():
            if not isinstance(value, dict) or not value:
                continue
            if not all(isinstance(k, str) and k in ops for k in value):
                continue
            flat = [v for value_ in value.values()
                    for v in (value_ if isinstance(value_, tuple) else (value_,))]
            if flat and all(isinstance(v, str) and v.startswith("OST_")
                            for v in flat):
                stored.add(attr)
        self.assertEqual(
            stored, allowed,
            "в clash_bundle появилось ХРАНИМОЕ отображение оп -> категория "
            f"({sorted(stored - allowed)}). Ответ на этот вопрос один и живёт "
            "в реестре: спрашивайте `spec.op_result_categories` через "
            "`clash_bundle.category_of`/`op_categories`. Если строка нужна "
            "как названное исключение — впишите её имя в `allowed` здесь и "
            "объясните, чего реестр не отвечает")
        self.assertIs(CB._REGISTRY_CATEGORIES, spec.op_result_categories)
        # The discrepancy the old ratchet was standing guard for can no
        # longer exist: a railing has ONE answer, and it comes from the
        # registry.
        self.assertEqual(spec.OP_RESULT_CATEGORIES["create_railing"],
                         ("OST_Railings", "OST_StairsRailing"))
        self.assertEqual(CB.op_categories("create_railing"),
                         ("OST_StairsRailing",))


# ═════════════════════════════════════════════════════════════════════════
# 2. ONE CODE — ONE FIX
# ═════════════════════════════════════════════════════════════════════════

class OneWireCodeOneRepair(unittest.TestCase):

    def test_the_typecheck_series_no_longer_shares_a_code_with_geometry(self):
        """REFUTATION OF THE WORST CASE. `KIR-T003` meant, at the same time,
        "value outside the closed enumeration" and "the opening crosses the
        contour" — two fixes, one wire, both declared in `diag.py` twelve
        lines apart. A consumer branching on the code could not tell them
        apart."""
        self.assertNotEqual(diag.TYPE_BAD_ENUM, diag.TYPE_GEOM_RELATION)
        self.assertEqual(diag.TYPE_BAD_ENUM, "KIR-T003")
        self.assertEqual(diag.TYPE_GEOM_RELATION, "KIR-T004")

    def test_the_macro_and_mesh_subsystems_no_longer_share_a_code(self):
        self.assertNotEqual(MACRO_ERROR, MESH_DISCONNECTED)
        self.assertEqual(MACRO_ERROR, "KIR-M001")
        self.assertEqual(MESH_DISCONNECTED, "KIR-M006")

    def test_a_zero_load_is_not_an_unsupported_enum(self):
        """A zero load is a meaningless NUMBER, not an unselected option;
        its fix is different, so its code is different too."""
        self.assertEqual(ANALYSIS_ZERO_LOAD, "KIR-E012")
        self.assertNotEqual(ANALYSIS_ZERO_LOAD, "KIR-E007")

    def test_the_never_raised_code_is_gone(self):
        """`KIR-C001` (`COMPILE_FAIL`) was declared, documented, and NEVER
        ONCE issued. A code that is declared but never issued is a promise
        nobody keeps, and it was occupying a whole letter.

        A PROSE READ USED TO STAND HERE, AND IT BROKE FROM ITS OWN
        CORRECTNESS (11.08.2026). The check was `assertNotIn("KIR-C001",
        inspect.getsource(diag))` — that is, it searched for a STRING in the
        whole source, comments included. The moment the comment explained
        that the letter C was freed up and why, the test found the very
        code it named and turned red. It was banning not the code's
        declaration, but any MENTION of it, and by that it was banning
        documenting its own decision.

        The property actually needed: the code is NOT DECLARED — neither
        here, nor in any other module of the package. It is checked by
        declarations, not by text, so the comment, the history, and this
        docstring may name `KIR-C001` as many times as they like.
        """
        self.assertFalse(hasattr(diag, "COMPILE_FAIL"))

        # 1. Not a single constant of `diag` itself carries it.
        in_diag = {name for name, value in vars(diag).items()
                   if name.isupper() and isinstance(value, str)
                   and value == "KIR-C001"}
        self.assertEqual(in_diag, set(),
                         "код снова объявлен константой в diag")

        # 2. Nor does any non-test module of the package — we read
        #    DECLARATIONS with the same parse that `code_collisions` uses
        #    to find name collisions, not raw text.
        declarations = re.compile(
            r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*[\"'](KIR-C001)[\"']", re.M)
        package = os.path.dirname(os.path.abspath(diag.__file__))
        offenders: list[str] = []
        for folder, _dirs, files in os.walk(package):
            if os.path.sep + "tests" in folder or "__pycache__" in folder:
                continue
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(folder, fname)
                with io.open(path, encoding="utf-8") as fh:
                    for name, _code in declarations.findall(fh.read()):
                        offenders.append(f"{os.path.relpath(path, package)}:{name}")
        self.assertEqual(offenders, [],
                         "мёртвый код KIR-C001 снова объявлен в пакете")

    def test_no_code_inside_diag_carries_two_names(self):
        """A lock on the import: this is exactly what was missing when T003 split apart."""
        diag._lint_diag_codes()
        globals_ = vars(diag)
        by_code: dict[str, set[str]] = {}
        for name, value in globals_.items():
            if (name.isupper() and isinstance(value, str)
                    and value.startswith("KIR-")):
                by_code.setdefault(value, set()).add(name)
        doubled = {c: sorted(n) for c, n in by_code.items() if len(n) > 1}
        self.assertEqual(doubled, {})

    def test_the_lint_actually_bites(self):
        """A lock that cannot fire is not a lock. The same law that holds
        the rest of this tree's ratchets."""
        scope = diag._lint_diag_codes.__globals__
        scope["DUPLICATE_PROBE"] = diag.TYPE_BAD_ENUM
        try:
            with self.assertRaises(AssertionError) as caught:
                diag._lint_diag_codes()
            self.assertIn("DUPLICATE_PROBE", str(caught.exception))
        finally:
            scope.pop("DUPLICATE_PROBE", None)
        diag._lint_diag_codes()          # the tree must remain clean

    def test_no_code_carries_two_names_across_the_package(self):
        """The cross-module half. An import cannot close it — there is no
        module that pulls in every emitter — so it is read from the
        sources."""
        self.assertEqual(diag.code_collisions(), {})

    def test_every_named_debt_is_still_a_real_collision(self):
        """The exceptions list is a DEBT, not a dumping ground.

        THE TEST WAS REWRITTEN ON 10.08 together with closing the debts. In
        its previous shape it iterated over a dictionary and, on an EMPTY
        one, passed having checked nothing — the very vacuum green this
        whole file was built against. Now an empty dictionary must MEAN an
        absence of collisions, not an absence of checking.
        """
        debts = diag.CODES_WITH_KNOWN_ALIASES
        if not debts:
            self.assertEqual(
                diag.code_collisions(), {},
                "долгов не объявлено, а столкновения есть — список молчит")
            return
        for code, why in debts.items():
            with self.subTest(code=code):
                self.assertTrue(why.strip(), "долг без причины")
                self.assertRegex(code, r"^KIR-[A-Z]\d+$")

    def test_the_two_collapsed_ideas_have_exactly_one_constant_each(self):
        """REFUTATION. `KIR-E007` used to be declared by FOUR modules,
        `KIR-E008` by THREE, each with its own name and its own literal for
        the same one thought. What became shared is the CODE, not the
        text: each place's `message_ru` stayed its own, because the
        collision was on the wire, not in the prose."""
        import os
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(diag.__file__)))
        pattern = re.compile(
            r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*[\"'](KIR-E00[78])[\"']",
            re.M)
        found: dict[str, set[str]] = {}
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for fname in files:
                if fname.endswith(".py"):
                    path = os.path.join(folder, fname)
                    with open(path, encoding="utf-8") as fh:
                        for name, code in pattern.findall(fh.read()):
                            found.setdefault(code, set()).add(name)
        self.assertEqual(found.get("KIR-E007"), {"EMIT_UNSUPPORTED_ENUM"})
        self.assertEqual(found.get("KIR-E008"), {"EMIT_CONTOUR_HOLES"})

    def test_the_two_shared_codes_still_mean_different_repairs(self):
        """Collapsing had no right to merge the thoughts themselves:
        "enumeration not supported" and "in the opening's contour" are
        different fixes."""
        self.assertNotEqual(diag.EMIT_UNSUPPORTED_ENUM,
                            diag.EMIT_CONTOUR_HOLES)


# ═════════════════════════════════════════════════════════════════════════
# 3. DARK MODULES: REMOVED WITH A REASON, NOT FORGOTTEN
# ═════════════════════════════════════════════════════════════════════════

class ADarkModuleLeavesWithAReason(unittest.TestCase):

    def test_the_annotation_seed_is_gone_and_its_family_lives_on(self):
        """`ops_doc` was the SEED of the annotation family and gave birth to
        it: tag/dimension/text moved into `ops_annotation`, while
        `ops_doc.OPS` has stayed an empty list since 17.07, all through a
        month of neighbors moving in August. An empty module in the
        registry's import list is indistinguishable from a broken one."""
        with self.assertRaises(ImportError):
            __import__("kir.ops_doc")
        family = {"create_tag", "create_dimension", "create_text"}
        self.assertLessEqual(family, set(spec.OPS),
                             "семья аннотаций пропала вместе с семенем")

    def test_removing_it_changed_no_op_count(self):
        """Proof that the seed was EMPTY, not a carrier of ops: the registry
        is still just as full, and not a single op was lost along with the
        module."""
        self.assertGreaterEqual(len(spec.OPS), 68)
        # WHAT IS CHECKED IS THE IMPORT, NOT THE PROSE. The previous
        # version searched for the string "ops_doc" in the source's first
        # 4000 characters — and would fail on ITS OWN tombstone comment
        # naming the removed module. A test must look at what the module
        # DOES.
        self.assertFalse(hasattr(spec, "ops_doc"),
                         "реестр всё ещё импортирует снятый модуль")


# ═════════════════════════════════════════════════════════════════════════
# 4. A FILE THAT JUDGES DRIFT HAS NO RIGHT TO DRIFT ITSELF
# ═════════════════════════════════════════════════════════════════════════

class ToolDocCountsItsOwnRules(unittest.TestCase):

    def test_the_declared_rule_count_matches_the_numbered_list(self):
        """The header promised TWO rules, while the text below referred to
        a third. This file punishes exactly this kind of drift in others
        (`create_dimension`, `UNPROVEN_GAP`) and has no right to carry it
        itself."""
        import re

        from kir import tool_doc

        doc = tool_doc.__doc__ or ""
        words = {"One": 1, "Two": 2, "Three": 3, "Four": 4}
        declared = re.search(r"(\w+) rules govern this module", doc)
        self.assertIsNotNone(declared, "шапка не называет числа правил")
        numbered = re.findall(r"^(\d+)\. \*\*", doc, re.M)
        self.assertEqual(words[declared.group(1)], len(numbered),
                         f"шапка обещает {declared.group(1)!r}, а пунктов "
                         f"{len(numbered)}")
        self.assertEqual(numbered, [str(i + 1) for i in range(len(numbered))],
                         "нумерация правил не сплошная")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
