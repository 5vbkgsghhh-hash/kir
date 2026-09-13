"""THE AUTHOR STRUCTURES INTENT WITH WHATEVER PYTHON USES TO STRUCTURE
INTENT.

WHY THIS FILE EXISTS, BY MEASUREMENT ON 20.08.2026. The constitution
requires that the environment not force the LLM to retreat from its
native language into a surrogate: "the unit of an utterance is the
building, not the wall," and describing a building with tuples `p[0]`,
`p[1]` instead of `room.width` is exactly that retreat. The sandbox
whitelist held three stdlib names, and `@dataclass` — three lines the
model writes out of habit — ended in a refusal.

🔴 THERE TURNED OUT TO BE TWO REASONS, AND THE SECOND WAS FOUND BECAUSE
IT WAS SEARCHED FOR AFTER THE FIRST.

    1. `compile()` INHERITS the caller's `__future__`, and
       `sandbox.py:103` has `from __future__ import annotations` —
       written for OUR OWN file. The author silently got PEP 563: his
       annotations turned into strings.
    2. With a string annotation, CPython goes into `dataclasses.py:749`
       (`_is_type`), where `sys.modules.get(cls.__module__).__dict__` is
       written WITH NO GUARD, and the author's frame
       (`kir_author_script`) was not listed in `sys.modules`.

The first is fixed with `dont_inherit=True`, the second by registering
the frame, and neither fixes the other: the author can also write a
string annotation himself, in quotes (`neighbor: "Room | None"` — an
ordinary direct forward reference).

EVERYTHING GOES THROUGH THE REAL SANDBOX (the NAKAZ, §5). The sandbox is
named in the canon as the first of the four boundaries the tests go
around, and it was exactly there that the lab green and the live green
once diverged: `extrude` worked offline and, live, blamed the AUTHOR for
OUR OWN import.
"""
from __future__ import annotations

import sys
import types
import unittest


def _prod_policy():
    """The policy EXACTLY as the build that ships to prod (`serving`),
    with no hand-made copy."""
    from kir import serving
    return serving._sandbox_policy()


def _run(source: str):
    from kir import sandbox
    return sandbox.execute_author_script(source, policy=_prod_policy())


#: The wall exists because a program of ZERO operations is a `KIR-B007`
#: refusal, and it cannot tell «the script ran to completion» from «the
#: script built nothing». The operation turns the outcome into a
#: positive statement, not the absence of a refusal.
_WALL = ('create_wall(id="W1", level="Этаж 1", p0_mm=[0.0, 0.0],\n'
         '            p1_mm=[ширина, 0.0], height_mm=3000.0)\n')


class СтруктураЗамыслаДоезжаетДоПрограммы(unittest.TestCase):
    """Every name is checked by USE, not by the fact of being imported.

    The distinction is not pedantry: `import dataclasses` already
    succeeded BEFORE the fix — it was the decorator that failed. A test
    on the import would have been green exactly where the product was
    broken.
    """

    def test_a_dataclass_describes_the_building_and_the_program_is_built(self):
        r = _run(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Комната:\n"
            "    имя: str\n"
            "    ширина: float\n"
            "к = Комната('Кухня', 3600.0)\n"
            "ширина = к.ширина\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")
        self.assertEqual([o["op"] for o in r.ops], ["create_wall"])
        self.assertEqual(r.ops[0]["p1_mm"][0], 3600.0)

    def test_a_forward_reference_in_quotes_is_the_second_carrier(self):
        """🔴 THE CASE THAT COMPILATION DOES NOT FIX.

        Quotes in an annotation are ordinary Python, `__future__` has
        nothing to do with it, and this is exactly the entry point
        through which the `dataclasses.py:749` branch is still reachable
        after `dont_inherit=True` has removed OUR OWN PEP 563.
        """
        r = _run(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Комната:\n"
            "    ширина: 'float'\n"
            "    сосед: 'Комната | None' = None\n"
            "ширина = Комната(4200.0).ширина\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")
        self.assertEqual(r.ops[0]["p1_mm"][0], 4200.0)

    def test_the_author_may_ask_for_pep_563_himself(self):
        """`from __future__ import annotations` — the most common first
        line."""
        r = _run(
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Комната:\n"
            "    ширина: float\n"
            "ширина = Комната(2400.0).ширина\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")
        self.assertEqual(r.ops[0]["p1_mm"][0], 2400.0)

    def test_collections_and_typing_reach_the_program_too(self):
        r = _run(
            "from collections import namedtuple, defaultdict\n"
            "from typing import NamedTuple\n"
            "П = namedtuple('П', 'x y')\n"
            "class Ось(NamedTuple):\n"
            "    имя: str\n"
            "    шаг: float\n"
            "стены = defaultdict(list)\n"
            "стены['низ'].append(П(0.0, 0.0))\n"
            "ширина = Ось('А', 6000.0).шаг + стены['низ'][0].x\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")
        self.assertEqual(r.ops[0]["p1_mm"][0], 6000.0)


class ДиалектПринадлежитАвтору(unittest.TestCase):
    """The script compiles in the language it was actually written in.

    A CHECK ON THE LAST LINK, not on intent: the assertion is checked by
    THE SCRIPT ITSELF, from inside the sandbox. Remove
    `dont_inherit=True` and the annotation becomes a string, the
    `assert` in the script fails, and the test turns red with
    `KIR-B006`. Nothing outside checks this: a fix in the parent never
    reaches the child.
    """

    def test_annotations_are_objects_unless_the_author_says_otherwise(self):
        r = _run(
            "def f(a: int) -> int:\n"
            "    return a\n"
            "assert f.__annotations__['a'] is int, (\n"
            "    'аннотация пришла строкой: песочница навязала автору свой PEP 563')\n"
            "ширина = 1200.0\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")

    def test_and_they_are_strings_when_he_does(self):
        """Control in the other direction: the author's own resolution
        WORKS.

        Without it, the previous test would also go green on a sandbox
        that does not support PEP 563 at all — meaning it would not
        distinguish «the dialect belongs to the author» from «there is
        no dialect at all».
        """
        r = _run(
            "from __future__ import annotations\n"
            "def f(a: int) -> int:\n"
            "    return a\n"
            "assert f.__annotations__['a'] == 'int', 'PEP 563 не подействовал'\n"
            "ширина = 1200.0\n" + _WALL)
        self.assertTrue(r.ok, r.refusal.message_ru if r.refusal else "")


class ГраницаНеСдвинулась(unittest.TestCase):
    """Extending the whitelist opened nothing beyond what was named."""

    def _refusal(self, source: str):
        r = _run(source)
        self.assertFalse(r.ok, "ожидался отказ")
        return r.refusal

    def test_the_system_family_is_still_refused_by_name(self):
        from kir import diag
        ref = self._refusal("import os\n")
        self.assertEqual(ref.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertIn("доступа к системе", ref.message_ru)

    def test_nondeterminism_is_still_refused_by_name(self):
        from kir import diag
        ref = self._refusal("import random\n")
        self.assertEqual(ref.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertIn("НЕДЕТЕРМИНИЗМ", ref.message_ru)

    def test_the_registered_frame_is_not_an_import_target(self):
        """The author's frame sits in `sys.modules` — and it is NOT
        reachable via import.

        `guarded_import` checks the whitelist BEFORE `sys.modules`, so
        the registration did not open a new path inward. The claim is
        not vacuous: without this order of checks, the registration
        would have opened a name that did not exist before.
        """
        from kir import diag
        ref = self._refusal("import kir_author_script\n")
        self.assertEqual(ref.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(ref.detail.get("module"), "kir_author_script")


class ПочемуЭтиЧетыреСтрокиВообЩеЕсть(unittest.TestCase):
    """A CONTROL ON THE MECHANISM, NOT ON THE PRODUCT — and it runs in
    this process, not in the child.

    The tests above show what works today. This one shows WHY it would
    not work without the registration, and it alone is able to turn red
    from someone else's hand: if CPython one day adds a guard to
    `dataclasses.py:749`, the fix becomes redundant, and that needs to
    be learned here, not a year from now.

    The product itself cannot be mutated from here: the sandbox is a
    separate process, and a fix in the parent never reaches it (a named
    trap in the canon).
    """

    SRC = ("from dataclasses import dataclass\n"
           "@dataclass\n"
           "class Pt:\n"
           "    x: 'float'\n"
           "z = Pt(1.0).x\n")

    def _exec(self, *, register: bool):
        ns = {"__name__": "kir_author_script", "__doc__": None}
        saved = sys.modules.pop("kir_author_script", None)
        try:
            if register:
                module = types.ModuleType("kir_author_script")
                module.__dict__.update(ns)
                sys.modules["kir_author_script"] = module
                ns = module.__dict__
            exec(compile(self.SRC, "<kir-script>", "exec", dont_inherit=True), ns)
        finally:
            sys.modules.pop("kir_author_script", None)
            if saved is not None:
                sys.modules["kir_author_script"] = saved

    def test_without_the_registration_cpython_raises_here(self):
        with self.assertRaises(AttributeError) as caught:
            self._exec(register=False)
        self.assertIn("__dict__", str(caught.exception))

    def test_with_it_the_same_source_passes(self):
        self._exec(register=True)


if __name__ == "__main__":
    unittest.main()
