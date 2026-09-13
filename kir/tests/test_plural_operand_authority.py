"""THE LANGUAGE'S LEVERAGE IS COUNTED FROM THE REGISTRY, AND "NOT COUNTED"
DOES NOT LOOK LIKE ZERO.

THE MEASUREMENT THAT PAID FOR THIS FILE (18.08.2026, `prod-live` tree, HEAD
`d1dd0cab`). The `tests/test_kir_canon_state_is_current.py` ratchet was red,
and its diff carried the line "with a plural operand **12** → **0**". The
zero would have been written into the canon with a single `--write` command,
and the ratchet would have TURNED GREEN ON IT: the product would have
declared that KIR has not a single operation that spawns many elements.

The truth is **12**. The mechanics of the lie, reproduced by execution:

    plural = [...] if hasattr(spec, "PLURAL_KINDS") else []   # -> []
    if not plural:
        try:    import capability_map as cm    # ModuleNotFoundError ALWAYS:
        except Exception: plural = []          # tools/ is not on sys.path
                                               # -> and there is the zero

Not one step lied on its own. Their SUM lied: an absent answer wore the
costume of an answer. This is the shape "zero of a quantity this instrument
does not count here", and it would have cost us a fact about our own
language.

🔴 A SECOND CARRIER OF THE SAME SHAPE, FOUND BY THE NIGHT'S OWN LAW ("having
caught a shape, look for its second carrier"): the name `PLURAL_KINDS` is
NOT UNIQUE in the tree. The second one lives in
`test_unpinned_plural_witnesses.py` and answers a DIFFERENT question — "does
the parameter's content get walked by a handwritten emitter loop" (does the
golden pin the loop's boundary). Hence it has four more kinds there: `pts`,
`slopes`, `sel_list`, `fields`. A roof's contour is walked by a loop — yet
the roof comes out as ONE. The name collision is coincidental, and "make
them one" would be a regression that looks like cleanup. It turns red below.

Run:
    venv/bin/python -m pytest kir/tests/test_plural_operand_authority.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

from kir import env
import unittest

from kir import spec

_HERE = pathlib.Path(__file__).resolve().parent
_BACKEND = _HERE.parents[2]

#: The HOST's root is optional: KIR stands without it too, and then the
#: SEAM assertions (about ITS instruments) are skipped with a named reason.
_HOST_ROOT = pathlib.Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))


def _load(path: pathlib.Path, name: str):
    s = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(s)
    s.loader.exec_module(module)
    return module


class TheRegistryIsTheOnlyAuthority(unittest.TestCase):

    def test_the_registry_declares_the_set_and_it_is_a_real_param_kind(self):
        kinds = spec.PLURAL_OPERAND_KINDS
        self.assertTrue(kinds, "пустое множество читалось бы как «рычага нет»")
        self.assertLessEqual(
            set(kinds), set(spec.PARAM_KINDS),
            "вид операнда, которого нет в PARAM_KINDS, — опечатка, которая "
            "не ломает НИ ОДНОЙ программы и просто занижает рычаг в каноне")

    def test_the_leverage_is_not_zero_and_names_the_ops(self):
        ops = sorted(n for n, o in spec.OPS.items()
                     if any(p.kind in spec.PLURAL_OPERAND_KINDS
                            for p in o.params))
        self.assertGreater(len(ops), 0)
        # The number is not pinned (a new op would color this test instead
        # of the canon — that is exactly what the canon is generated for).
        # What is pinned are the SAMPLES, whose disappearance would mean
        # something other than what is intended is now being counted.
        for name in ("create_group", "move_elements", "route_pipe_system"):
            self.assertIn(name, ops, f"{name} перестал считаться множественным")

    def test_the_instrument_is_wired_to_the_registry_not_to_a_copy(self):
        # 🔴 THE HOST'S OWN INSTRUMENT, AND THIS MUST BE SAID (28.08.2026).
        # `capability_map.py` stayed in the product tree after the 27.08
        # split, while `_BACKEND = parents[2]` points into ours. The claim
        # "the instrument carries not its own list but our registry" is a
        # SEAM claim: with no second tree there is nothing to check it
        # against, and `FileNotFoundError: '/opt/tools/capability_map.py'`
        # read as a finding about the instrument. The root is named by a
        # variable, the skip by words.
        карта = _HOST_ROOT / "tools" / "capability_map.py"
        if not карта.is_file():
            self.skipTest(
                f"карта способностей — прибор ХОЗЯИНА ({карта}); что она возит, "
                f"здесь непроверяемо. Назвать корень: KIR_HOST_ROOT")
        cm = _load(карта, "cm_probe")
        self.assertIs(
            cm.PLURAL_KINDS, spec.PLURAL_OPERAND_KINDS,
            "прибор снова возит СВОЙ список — это второй экземпляр, а он "
            "разъезжается: наказ п.4, разъехались ВСЕ рукописные и НИ ОДИН "
            "порождаемый")


class AnAbsentAnswerDoesNotLookLikeZero(unittest.TestCase):
    """A built-in FAIL control: remove the source and see what gets
    printed."""

    def test_without_the_registry_set_the_canon_says_NOT_COUNTED_not_zero(self):
        canon = importlib.import_module("kir.instruments.canon_state")
        saved = spec.PLURAL_OPERAND_KINDS
        try:
            del spec.PLURAL_OPERAND_KINDS
            row = [r for r in canon.build().splitlines()
                   if "множественным операндом" in r]
        finally:
            spec.PLURAL_OPERAND_KINDS = saved
        self.assertEqual(len(row), 1, "строка рычага пропала из блока целиком")
        self.assertIn("НЕ ПОСЧИТАНО", row[0])
        self.assertNotIn("**0**", row[0],
                         "прибор снова печатает ноль вместо отказа — ровно та "
                         "строка, ради которой этот файл написан")

    def test_with_the_registry_set_the_canon_prints_the_number(self):
        canon = importlib.import_module("kir.instruments.canon_state")
        row = [r for r in canon.build().splitlines()
               if "множественным операндом" in r][0]
        self.assertNotIn("НЕ ПОСЧИТАНО", row)
        self.assertRegex(row, r"\*\*\d+\*\*")


class TheTwoListsMustNotBeUnified(unittest.TestCase):
    """A second carrier of the shape: one name for two DIFFERENT questions."""

    def test_the_witness_list_is_a_strict_superset_and_the_gap_is_named(self):
        wit = _load(_HERE / "test_unpinned_plural_witnesses.py", "wit_probe")
        theirs, ours = set(wit.PLURAL_KINDS), set(spec.PLURAL_OPERAND_KINDS)
        self.assertLess(
            ours, theirs,
            "множества сведены к одному. Это РЕГРЕСС, а не уборка: «сколько "
            "элементов родит оп» и «обходит ли параметр рукописный цикл» — "
            "разные вопросы, и ответы обязаны различаться")
        self.assertEqual(
            theirs - ours,
            # 21.08.2026: `surface` and `solid_parts` were added. THE
            # EXPLANATION the message below demands. Both kinds were
            # introduced by the free-form wave on 20.08, and both are
            # PLURAL for the witness (emission walks them with a handwritten
            # loop: for a surface it grows with the number of control
            # points — measured 14033 -> 14305 -> 14613, for a boolean with
            # the number of parts), but they are NOT plural as an operand:
            # the op returns ONE element, one DirectShape. That is exactly
            # the difference the two lists exist to keep separate.
            #
            # 24.08.2026: `wall_layers` was added, and its declaration did
            # not keep pace — the red stood for two days. The kind was
            # introduced by `41b4bbc5` (`create_wall_type`), and `feb2b0d2`
            # added it to the witness list by measuring text growth: 1
            # layer -> 212 lines / 10681 characters, 2 -> 213 / 10867, 3 ->
            # 214 / 11051, 5 -> 216 / 11419. One line and ~184 characters
            # PER LAYER — linear growth, a handwritten loop. Yet it is NOT
            # a plural operand, and this is read off the registry, not by
            # eye: `create_wall_type.result.identity_cardinality` is `ONE`.
            # A five-layer stack returns ONE wall type.
            {"pts", "slopes", "sel_list", "fields", "surface", "solid_parts",
             "wall_layers"},
            "разница между двумя вопросами изменилась. Это законно, но её "
            "надо ОБЪЯВИТЬ здесь, а не обнаружить через канон: контур крыши "
            "обходится циклом, а крыша выходит ОДНА")

    def test_every_declared_gap_kind_births_at_most_one_element(self):
        """The declared difference has a CHECKABLE property, not just a
        list.

        🔴 WHY THIS WAS ADDED (26.08.2026). The literal above is maintained
        by hand, and three times in a row it fell behind the witness list:
        `surface` and `solid_parts` on 21.08, `wall_layers` on 24.08 — the
        last one stood red for two days. A handwritten list catches THE
        FACT of a discrepancy itself, and that is its job. But it does NOT
        catch a WRONG discrepancy: adding a name here to make it green is
        exactly as easy as forgetting to add it.

        The law by which a kind is ENTITLED to stand in the difference is
        one, and it is read off the registry: plural for the witness
        (emission walks it with a loop), but NOT plural as an operand —
        meaning the op carrying this kind returns no more than ONE element.
        Measured 26.08 across all seven:

            fields       query_list                 none  (a read, spawns nothing)
            pts          create_floor, create_roof  one
            sel_list     create_multistory_stairs   one
            slopes       create_roof                one
            solid_parts  create_solid_boolean       one
            surface      create_surface             one
            wall_layers  create_wall_type            one

        `none` is EXPLICITLY allowed: a read-only op creates nothing.
        `many` is forbidden — a kind whose op spawns many elements, hidden
        inside the declared difference, would understate the language's
        leverage in the canon.

        🔴 WHAT THIS LAW DOES NOT CATCH, AND THIS IS MEASURED BY A
        MUTATION, NOT DECLARED. The first edition of this docstring claimed
        the law catches every wrong declaration. Checking by substituting
        all seven operand kinds into the difference said otherwise:

            CAUGHT     3 of 7   graph_nodes · graph_segments · refs_w
            MISSED     4 of 7   filters · member_ops · placements · pts_list

        The reason is that the result's cardinality does NOT distinguish
        membership in `PLURAL_OPERAND_KINDS`: `create_group` (member_ops,
        placements) and `create_floor` (pts_list) each spawn ONE element and
        are legitimately listed as plural operands anyway, while
        `query_count` (filters) spawns nothing. The registry's own prose
        ("how many ELEMENTS one op spawns") is read more broadly by its own
        data than it sounds.

        So this test is a PARTIAL guard, and it is named that way on
        purpose. It closes the costliest case (a kind that spawns MANY,
        declared as a difference) and does NOT close the other four. It
        does not replace the literal above: the property says a kind is
        ENTITLED to stand here, not that "it stands here for a reason". A
        human stays in the loop, and this is not a caveat but the
        instrument's boundary.
        """
        wit = _load(_HERE / "test_unpinned_plural_witnesses.py", "wit_probe2")
        gap = set(wit.PLURAL_KINDS) - set(spec.PLURAL_OPERAND_KINDS)
        self.assertTrue(gap, "разница пуста — списки сведены, см. тест выше")
        for kind in sorted(gap):
            ops = [n for n, o in spec.OPS.items()
                   if any(p.kind == kind for p in o.params)]
            with self.subTest(kind=kind, ops=ops):
                self.assertTrue(
                    ops, f"род {kind} не несёт НИ ОДИН оп реестра — "
                         "объявлять разницу по несуществующему роду нельзя")
                for name in ops:
                    result = spec.OPS[name].result
                    card = getattr(
                        getattr(result, "identity_cardinality", None),
                        "value", None) if result is not None else None
                    self.assertIn(
                        card, ("one", "none"),
                        f"{name}.{kind}: оп рождает {card!r} элементов, то "
                        "есть род ПЛЮРАЛЕН КАК ОПЕРАНД — ему место в "
                        "spec.PLURAL_OPERAND_KINDS, а не в объявленной "
                        "разнице. Объявление здесь спрятало бы рычаг языка")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
