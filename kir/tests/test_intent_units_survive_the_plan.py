"""THE TABLE OF UNITS OF INTENT WAS BEING LOST ON EXACTLY THE LIVE DOOR.

🔴 WHY (25.08.2026, an audit finding, confirmed by execution).

`course.unit()` lets the author write in composites — "apartment," "typical
floor" — and the unit table rides along in the receipt, so an observation
about arity N can NAME THE INTENT, rather than a list of ops. The comment on
the field declared this fixed: "the intent used to break off here… the unit
table now rides in the response in full."

It kept breaking off just the same, and precisely in production:

    `_units_of` read `units` ONLY from a `Mapping`.
    The live door passes `compile_program` NOT a dict but a `PlannedProgram`
    (`serving.py`: `compile_input = routed_plan if routed_plan is not None
    else program`), and the plan HAD NO `units` FIELD AT ALL.

The upshot: in production `CompileOutput.units` is ALWAYS empty, the `units`
key is NEVER placed in the receipt, and a model authored as a composite gets
back a list of ops and a number, `u0`, that means nothing to it.

The promise stood in the comment; the reading did not. The tree's named
kind: a quantity ASSERTED in one place and READ in another.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program, plan_program

ПРОГРАММА = {
    "ir_version": "1.0",
    "intent": "квартира",
    "units": [{"id": "u0", "name": "квартира", "ops": ["W1"]}],
    "ops": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}}],
}


class ЗамыселПереживаетПлан(unittest.TestCase):

    def test_словарём_и_планом_дают_ОДНО_И_ТО_ЖЕ(self):
        """🔴 RED before the fix: empty via the plan, not via the dict."""
        словарём = compile_program(ПРОГРАММА, revit_version="2026")
        планом = compile_program(plan_program(ПРОГРАММА),
                                 revit_version="2026")
        self.assertTrue(словарём.ok and планом.ok)
        self.assertEqual(планом.units, словарём.units)
        self.assertEqual(планом.units,
                         [{"id": "u0", "name": "квартира", "ops": ["W1"]}])

    def test_квитанция_несёт_ключ_units(self):
        """This is what the table rides along for: to name the INTENT, not
        the number u0."""
        планом = compile_program(plan_program(ПРОГРАММА),
                                 revit_version="2026")
        self.assertEqual(планом.as_dict().get("units"), планом.units)

    def test_план_несёт_замысел_кортежем(self):
        """The plan is immutable: a list inside it would be a hole in that
        immutability."""
        план = plan_program(ПРОГРАММА)
        self.assertIsInstance(план.units, tuple)

    def test_КОНТРОЛЬ_без_таблицы_ключа_НЕТ(self):
        """An empty `units` in the receipt would read as "the intent was
        empty"."""
        без = {k: v for k, v in ПРОГРАММА.items() if k != "units"}
        планом = compile_program(plan_program(без), revit_version="2026")
        self.assertEqual(планом.units, [])
        self.assertNotIn("units", планом.as_dict())


class ПОДПИСЬПЛАНАНЕСДВИНУЛАСЬ(unittest.TestCase):
    """🔴 A DECISION, NOT AN OVERSIGHT.

    `units` is NOT part of `_unsigned_evidence`: the compiler does not
    interpret it, it is a passenger all the way to the receipt. Signing it
    would mean shifting `plan_digest` for EVERY already-saved plan for the
    sake of a label.

    The cost is named plainly: an unsigned passenger can be swapped
    unnoticed, and it cannot be relied on as EVIDENCE — it names, it does
    not prove.
    """

    def test_добавление_таблицы_НЕ_меняет_plan_digest(self):
        с_таблицей = plan_program(ПРОГРАММА)
        без = plan_program({k: v for k, v in ПРОГРАММА.items()
                            if k != "units"})
        self.assertEqual(с_таблицей.plan_digest, без.plan_digest)

    def test_ИНАЧЕ_ГОВОРЯ_таблица_НЕ_улика(self):
        """The same fact, said from the subject's side: the signature does
        not cover it."""
        план = plan_program(ПРОГРАММА)
        self.assertNotIn("units", план._unsigned_evidence())


if __name__ == "__main__":
    unittest.main()


class КВИТАНЦИЯМОДЕЛИНЕСЁТЗАМЫСЕЛ(unittest.TestCase):
    """🔴 THE THIRD BREAK IN ONE CHAIN, and it was found by a LIVE RUN
    (25.08.2026).

    The table was fixed twice within an hour: the plan learned to CARRY it,
    `_units_of` learned to READ it. A live run through `/admin/kir/run`
    revealed a third: `CompileOutput.units` is populated, but the MODEL'S
    RECEIPT does not copy it. There were ZERO readers of the field anywhere
    in the tree — meaning the fix to the first two links gave the model
    NOTHING.

    Measured before the fix: a program with `units` builds
    (`committed·accepted`), the response carries `units: null`. After:
    `[{"id":"u0","name":"пробная единица","ops":["U1","U2"]}]`.
    """

    def test_живая_дверь_КОПИРУЕТ_units_в_квитанцию(self):
        """THE WIRING. Without it, the field would live on and remain
        invisible."""
        import inspect
        from kir import serving
        src = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertIn('out_result["units"]', src,
                      "квитанция модели обязана нести таблицу единиц")

    def test_отсутствие_НЕ_кладёт_пустой_ключ(self):
        """`units: []` would read as "the intent was empty," when there was
        none at all."""
        import ast
        import inspect
        from kir import serving
        src = inspect.getsource(serving._handle_revit_ir_inner)
        # the assignment must sit UNDER the non-emptiness condition
        строки = [l.strip() for l in src.splitlines()]
        i = next(n for n, l in enumerate(строки) if 'out_result["units"]' in l)
        self.assertTrue(any("if _units" in l for l in строки[max(0, i - 3):i]),
                        "присваивание обязано стоять под проверкой непустоты")


class ЧЕТВЁРТЫЙРАЗРЫВ_КОНВЕРТПЕСОЧНИЦЫ(unittest.TestCase):
    """🔴 THE CHAIN WAS BROKEN IN FOUR PLACES, AND THE FOURTH IS THE MOST
    IMPORTANT.

    Three links were fixed on 25.08 (the plan carries it · `_units_of`
    reads it · the receipt copies it). And none of that gave ANYTHING on
    the path the model ACTUALLY travels: an authored script through the
    sandbox.

    A live run before the fix: `with unit("санузел"): create_wall(...)`
    produced the envelope `{"ir_version": "1.0"}` — and nothing else.
    `course.take_ops()` assembles the table CORRECTLY, but
    `sandbox._ENVELOPE_KEYS` did not know it, and the filter loop discarded
    it WITHOUT A SINGLE WORD. The same script with `phase()` got its
    envelope.

    BOTH ENDS OF THE PIPE WERE BUILT: `compiler.known_top` has known
    `units` from the very start. What was missing was ONE NAME in the
    filter list.

    The lesson about the technique itself: a filter list stays silent
    about what it discards — which is exactly why the three fixes above
    looked complete.
    """

    СКРИПТ = (
        'with unit("санузел"):\n'
        '    create_wall(p0_mm=[0, 0], p1_mm=[3000, 0], height_mm=2700,\n'
        '                level={"by": "element_id", "value": 42})\n')

    def _конверт(self):
        from kir import sandbox
        r = sandbox.execute_author_script(
            self.СКРИПТ,
            policy=sandbox.SandboxPolicy(
                dsl_module="kir.course.language"))
        self.assertTrue(r.ok, getattr(r, "diagnostics", None))
        return r.envelope

    def test_конверт_несёт_таблицу_единиц(self):
        """🔴 RED before the fix: the envelope was {'ir_version': '1.0'}."""
        конверт = self._конверт()
        self.assertIn("units", конверт)
        self.assertEqual(конверт["units"][0]["name"], "санузел")

    def test_КОНТРОЛЬ_компилятор_принимал_ключ_ВСЕГДА(self):
        """Both ends of the pipe were built — the filter was missing a
        name."""
        import inspect
        from kir import compiler
        # The key is declared in `_parse_and_check_internal`, not in
        # `plan_program`: the first draft of this control looked in the
        # wrong function and turned red on ITS OWN wrong address — "the
        # instrument answered a different question."
        src = inspect.getsource(compiler._parse_and_check_internal)
        self.assertIn("known_top", src)
        self.assertIn('"units"', src)

    def test_скрипт_БЕЗ_unit_конверта_с_units_НЕ_получает(self):
        """Absence remains absence here too."""
        from kir import sandbox
        r = sandbox.execute_author_script(
            'create_wall(p0_mm=[0, 0], p1_mm=[3000, 0], height_mm=2700,\n'
            '            level={"by": "element_id", "value": 42})\n',
            policy=sandbox.SandboxPolicy(
                dsl_module="kir.course.language"))
        self.assertTrue(r.ok)
        self.assertNotIn("units", r.envelope)
