"""A CAPABILITY THE MODEL CANNOT READ ABOUT IS NOT BUILT — IT IS WRITTEN.

🔴 THE OWNER'S LAW, 15.08.2026: "KIR mode must not operate without
documentation and skills; every new capability arrives TOGETHER with its own
door and its own text."

WHAT THIS FILE FIXES IS A CLASS, NOT SEVEN CASES. In one day, six
capabilities were built, and the model knew about none of them: the unit of
intent, doors in a typical floor, the document catalog, a raised budget, the
`element_map` map, a cache against an already-standing building. None was
forgotten out of carelessness — simply NOTHING REQUIRED writing the text,
while the registry kept growing in the meantime. The argument that this
would keep happening is recorded in the code itself and cost five weeks:
`sdk.py` — 493 lines, unreachable, because there was no door to them.

HOW THIS WORKS. Listed below are the CAPABILITY REGISTRIES — authorities,
each of its own kind. For each, it is stated WHERE the name must be named,
and why exactly there. Adding a name to a registry without a line in the
text turns this file red.

TWO DOORS, AND THEIR COST DIFFERS — hence the placement rule:

  TOOL DESCRIPTION       is paid for on EVERY turn. Here goes what the
                         model cannot do without, or it will pick the WRONG
                         FORM.
  ON REQUEST             `spec(<op>)`, `recipe()`, lessons — read when
                         asked for. Here goes detail and examples.

The test does NOT judge exactly where a capability is named, as long as it
is named SOMEWHERE reachable: arguing about placement is the author's job,
but silence from both doors is a defect, and the machine catches it.
"""
from __future__ import annotations

import io
import contextlib
import unittest

from kir import spec, tool_doc, skill
from kir.assembly_view import UNIT_READS
from kir.course import lessons
from kir.macros import _STACKABLE_HOSTED, MACRO_OPS


def _description() -> str:
    return tool_doc.build_tool_description()


def _on_demand() -> str:
    """Everything the model can READ ON REQUEST, in one line.

    Lessons, the registry catalog (`spec()`), the recipe catalog
    (`recipe()`). Assembled by a call, not by retyping: text assembled by
    hand would guard the fixture (form 27).
    """
    from kir import course

    parts = [lessons.lesson(name) for name in lessons.ORDER]
    for door in ("spec", "recipe"):
        fn = getattr(course, door, None)
        if fn is None:
            continue
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                fn()
            except Exception:  # noqa: BLE001 — a door that refused is also a fact
                pass
        parts.append(buffer.getvalue())
    return "\n".join(parts)


def _everything() -> str:
    return _description() + "\n" + _on_demand()


class EveryCapabilityRegistryIsNamedToTheModel(unittest.TestCase):
    """RATCHET. Capability registry -> the name must be in the text."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.description = _description()
        cls.everywhere = _everything()

    # ── registries whose names must be in the PERMANENT text ───────────────

    def test_every_reading_predicate_is_named_in_the_description(self):
        """Unit readings (`UNIT_READS`) — in the DESCRIPTION, not on
        request.

        A reading decides the FORM of the statement: not knowing that
        `reads_as` exists, the author will write a set without a declared
        intent, and a finding about arity N will never appear. You cannot
        ask about what you do not know.
        """
        for name in UNIT_READS:
            with self.subTest(reading=name):
                self.assertIn(name, self.description,
                              "прочтение %r есть в реестре и НЕ названо в "
                              "описании: модель не сможет его выбрать" % name)

    def test_the_unit_construct_itself_is_named(self):
        self.assertIn("unit(", self.description,
                      "конструкция `unit()` не названа — реестр прочтений "
                      "недостижим целиком")

    def test_the_element_map_is_named_in_the_description(self):
        """`element_map` is the only way to refer to what was BUILT on the
        next turn. Without it, the author searches for the element by name
        again, and that is an extra round on every continuation."""
        self.assertIn("element_map", self.description)

    def test_every_registry_op_is_named(self):
        """The duplication with the neighboring file is DELIBERATE: there it
        is about the completeness of the description, here — about the law
        "a capability arrives with its own text." If `test_tool_doc` is ever
        weakened, the law must keep holding."""
        missing = [n for n in spec.OPS if n not in self.description]
        self.assertEqual(missing, [], "опы реестра не названы: %s" % missing)

    # ── registries for which a door ON REQUEST is enough ────────────────────

    def test_every_macro_is_named_somewhere_reachable(self):
        for name in MACRO_OPS:
            with self.subTest(macro=name):
                self.assertIn(name, self.everywhere,
                              "макрос %r нигде не назван" % name)

    def test_hosted_stackable_ops_are_named_in_the_macro_contract(self):
        """🔴 A WAVE E CAPABILITY — AND THE CHECK LOOKS INTO THE MACRO'S
        CONTRACT, NOT THE WHOLE TEXT.

        The first edit searched for `create_door` in the merged text and was
        GREEN IN A VACUUM: this name is present in the description as the OP
        name, in the list of sections, and would be found even if not a word
        had been said about `stack`. A check without an act of distinction
        is canon form 18, committed inside a test that was written against
        it.

        The measurement that caught this: the "floor" lesson named neither
        `stack` nor doors — the capability really was invisible, and the
        test was green.

        Now the door where the macro's contract actually lives is queried.
        Named ON REQUEST, not in the description, and this decision has a
        reason: there are no macros at all in the script (`program_py`) —
        Python does their work there — and the description teaches the
        script first and foremost.

        🔴 THE HONEST BOUNDARY OF THIS CHECK, MEASURED BY MUTATION
        (15.08.2026): it CANNOT turn red from a new occupant of
        `_STACKABLE_HOSTED`. Adding `create_opening` to the registry left it
        green — and this is not a defect of the test but a property BETTER
        than a ratchet: `_macro_contract` GENERATES the list from the same
        registry, so the text follows the registry on its own, and "add
        without documenting" is physically impossible here.

        Hence the wave's general conclusion, and it matters more than any
        one of the seven capabilities: **generated text does not need a
        ratchet, handwritten text does.** The ratchet below stands where
        text is written by hand (`UNIT_READS` in the description,
        `element_map`, op names), and the mutation shows that it bites
        there. The check here remains not as a guard but as a GENERATION
        CONTROL: it will turn red if the contract stops being assembled from
        the registry and becomes a handwritten list — that is, exactly when
        a ratchet would be needed.
        """
        from kir import course

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            course.spec("stack")
        contract = buffer.getvalue()
        self.assertTrue(contract.strip(), "spec('stack') не отдал ничего")
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                self.assertIn(name, contract,
                              "хостящийся оп %r допущен в stack, а контракт "
                              "макроса о нём молчит" % name)
        # AND THE CAPABILITY ITSELF, NOT JUST THE NAMES: without this line
        # the author will not learn that the host must travel together with
        # the member.
        self.assertIn("ХОЗЯИН", contract.upper(),
                      "контракт не говорит, что хозяин обязан быть членом "
                      "того же этажа — имена без правила бесполезны")

    def test_the_macro_contract_door_answers_for_every_macro(self):
        """EVERY macro must have a contract door. Before 15.08.2026,
        `spec("stack")` answered "there is no such operation in the
        registry" — formally true (a macro is not an op) and practically
        false: the author was asking about an existing capability and was
        told it did not exist."""
        from kir import course

        for name in MACRO_OPS:
            with self.subTest(macro=name):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    course.spec(name)
                text = buffer.getvalue()
                self.assertIn(name, text)
                self.assertGreater(len(text), 120,
                                   "контракт макроса %r пуст или отказ" % name)

    # ── control: the ratchet must be able to turn red ──────────────────────

    def test_the_ratchet_can_actually_fail(self):
        """FAIL CONTROL. The check "the name is in the text" is green by
        construction if the text is large: almost any short string will be
        found in it. The control takes a name that is NOT in the registries
        and requires that it not be found.
        """
        invented = "reads_as_совершенно_несуществующее_прочтение"
        self.assertNotIn(invented, self.everywhere,
                         "текст содержит выдуманное имя — проверка "
                         "вхождения ничего не различает")

    def test_naming_a_capability_did_not_break_the_permanent_budget(self):
        """🔴 THE SECOND HALF OF THE LAW, WITHOUT WHICH THE FIRST IS
        HARMFUL.

        "A capability must be named," without a ceiling, turns into "write
        everything into the permanent text" — and that is exactly how it
        was broken through: eight capabilities arrived in a day, the
        measurement gave 30 427 against a ceiling of 30 000, and NOTHING
        turned red, because there was no budget ratchet here, and
        `test_tool_doc` knows nothing about capabilities.

        The two checks must stand SIDE BY SIDE: naming and fitting within
        budget is one requirement, not two. Split across files, they
        produce a pendulum, where every wave honestly fixes one half and
        honestly breaks the other.
        """
        self.assertLess(
            len(self.description), 30_000,
            "описание пробило потолок: способность названа ценой бюджета, "
            "который платится КАЖДЫМ ходом. Не поднимай потолок — перенеси "
            "подробность в канал спроса (`course(<тема>)`, `spec(<оп>)`, "
            "`recipe()`) и оставь в постоянном тексте одну строку")

    def test_the_registries_are_not_empty(self):
        """THE DENOMINATOR FIRST: an empty registry would pass every check
        above vacuously, and "all capabilities are named" would read as a
        fact."""
        self.assertTrue(UNIT_READS, "реестр прочтений пуст")
        self.assertTrue(_STACKABLE_HOSTED, "реестр хостящихся пуст")
        self.assertTrue(MACRO_OPS, "реестр макросов пуст")
        self.assertGreaterEqual(len(spec.OPS), 60)


class TheTwoDoorsAreBothReachable(unittest.TestCase):
    """Text on request is useless if the door itself is not mentioned in
    the permanent text: you cannot ask about what you do not know."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.description = _description()

    def test_the_on_demand_doors_are_announced(self):
        for door in ("spec(", "recipe"):
            with self.subTest(door=door):
                self.assertIn(door, self.description,
                              "дверь %r не объявлена в постоянном тексте — "
                              "модель о ней не узнает" % door)

    def test_the_on_demand_text_is_not_empty(self):
        text = _on_demand()
        self.assertGreater(len(text), 5_000,
                           "двери по требованию отдали почти пустой текст — "
                           "проверки размещения выше судили бы ни о чём")


if __name__ == "__main__":
    unittest.main()
