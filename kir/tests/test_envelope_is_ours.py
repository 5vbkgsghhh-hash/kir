"""The program's envelope is OUR concern, not the author's.

A LIVE MEASUREMENT ON 16.08.2026. The model got this twice on the owner's turn:

    VALIDATION_FAILED  KIR-P004  ir_version is required and must be '1.0'

and twice went off to fix the wrong thing, because it never wrote `ir_version` and
does not know about it from the tool's description.

THE MECHANISM, REPRODUCED BY EXECUTION (not inferred from the refusal's text):

    ops = [ {...}, {...} ]        → harvest `ns.ops`      → envelope {}   → KIR-P004
    create_wall(...)              → harvest `dsl.take_ops()` → envelope {ir_version} → OK

The handle path stamps the version inside `Program.build()`; the envelope-variable path has
no such thing at all. And yet WE OURSELVES declare the variable path legitimate — verbatim, in
the text of the `SANDBOX_NO_OPS` refusal: "the alternative is to assign the list of operations
to the ops variable."

HENCE THE SHAPE OF THE FIX, AND IT DIFFERS FROM THE ORIGINAL INTENT. The intent was
"teach the refusal to name the real error." But there IS NO author error here: we
advertise a path and fail to finish building it. A better refusal would leave the author without
the advertised capability; so the envelope gets completed, not rejected.

THE BOUNDARY WITHOUT WHICH THE FIX WOULD BE A COVER-UP: ONLY
what is missing gets stamped. An envelope where the author EXPLICITLY named the wrong version
still must get `KIR-P004` — there, the author said something false, not stayed silent. Two
different facts must produce two different outcomes, and both are checked below.
"""
from __future__ import annotations

import unittest

from kir import compiler, sandbox
from kir.spec import IR_VERSION

_OP = ('{"op":"create_wall","id":"w1","p0_mm":[0,0],"p1_mm":[4000,0],'
       '"level":{"by":"name","value":"L1"}}')


def _program_of(script: str) -> tuple[dict, str]:
    """Script → program exactly the way `serving` assembles it."""
    res = sandbox.execute_author_script(script)
    if not res.ok:
        raise AssertionError(f"песочница отказала: {res.refusal.render()[:200]}")
    harvest = (res.isolation or {}).get("harvest", "?")
    return {**(res.envelope or {}), "ops": res.ops}, harvest


class ДваПутиАвтораДаютОдинРабочийКонверт(unittest.TestCase):

    def test_список_в_переменной_доезжает_до_плана(self):
        program, harvest = _program_of(f"ops = [{_OP}]")
        self.assertEqual(harvest, "ns.ops", "изменился путь сбора — тест смотрит не туда")
        self.assertEqual(program.get("ir_version"), IR_VERSION)
        compiler.plan_program(program)  # does not raise — that is exactly the check

    def test_ручки_доезжают_как_и_прежде(self):
        program, harvest = _program_of(
            'create_wall(id="w1", p0_mm=[0,0], p1_mm=[4000,0], '
            'level={"by":"name","value":"L1"})')
        self.assertEqual(harvest, "dsl.take_ops()")
        self.assertEqual(program.get("ir_version"), IR_VERSION)
        compiler.plan_program(program)

    def test_оба_пути_дают_ОДИНАКОВЫЙ_конверт(self):
        a, _ = _program_of(f"ops = [{_OP}]")
        b, _ = _program_of('create_wall(id="w1", p0_mm=[0,0], p1_mm=[4000,0], '
                           'level={"by":"name","value":"L1"})')
        self.assertEqual(a.get("ir_version"), b.get("ir_version"))


class ЯвнаяНеправдаОВерсииПоПрежнемуОтвергается(unittest.TestCase):
    """A control from the other side of the boundary. Without it, the fix would be a cover-up."""

    def test_неверная_версия_в_конверте_даёт_KIR_P004(self):
        program, _ = _program_of(
            f'program = {{"ir_version":"2.0","ops":[{_OP}]}}')
        self.assertEqual(program.get("ir_version"), "2.0",
                         "штамп перезаписал авторскую версию — это сокрытие")
        with self.assertRaises(Exception) as ctx:
            compiler.plan_program(program)
        self.assertIn("KIR-P004", str(ctx.exception))


class ВерсияБерётсяУРеестра(unittest.TestCase):
    """A second place required to match the registry — a named defect class of the tree."""

    def test_штамп_не_литерал(self):
        import inspect
        src = inspect.getsource(sandbox)
        self.assertIn("from kir.spec import IR_VERSION", src,
                      "версия обязана спрашиваться у реестра, а не писаться числом")

    def test_штамп_следует_за_реестром(self):
        program, _ = _program_of(f"ops = [{_OP}]")
        self.assertEqual(program["ir_version"], IR_VERSION)


if __name__ == "__main__":
    unittest.main()
