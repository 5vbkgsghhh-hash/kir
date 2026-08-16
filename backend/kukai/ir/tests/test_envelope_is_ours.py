"""Конверт программы — НАША забота, а не авторская.

ЖИВОЙ ЗАМЕР 16.08.2026. Модель дважды получила на ходе владельца:

    VALIDATION_FAILED  KIR-P004  ir_version обязателен и должен быть '1.0'

и дважды ушла чинить не то, потому что `ir_version` она не писала и из
описания инструмента о нём не знает.

МЕХАНИЗМ, ВОСПРОИЗВЕДЁННЫЙ ИСПОЛНЕНИЕМ (а не выведенный из текста отказа):

    ops = [ {...}, {...} ]        → harvest `ns.ops`      → envelope {}   → KIR-P004
    create_wall(...)              → harvest `dsl.take_ops()` → envelope {ir_version} → OK

Путь ручек штампует версию в `Program.build()`; путь переменной конверта не
имеет вовсе. При этом путь переменной МЫ САМИ объявляем законным — дословно, в
тексте отказа `SANDBOX_NO_OPS`: «альтернатива — присвоить список операций
переменной ops».

ОТСЮДА ФОРМА ПОЧИНКИ, И ОНА ОТЛИЧАЕТСЯ ОТ ПЕРВОНАЧАЛЬНОГО ЗАМЫСЛА. Замысел был
«научить отказ называть настоящую ошибку». Но ошибки автора здесь НЕТ: мы
рекламируем путь и не достраиваем его. Отказ получше оставил бы автора без
рекламируемой возможности; поэтому конверт достраивается, а не отвергается.

ГРАНИЦА, БЕЗ КОТОРОЙ ПОЧИНКА СТАЛА БЫ СОКРЫТИЕМ: штампуется ТОЛЬКО
отсутствующее. Конверт, где автор ЯВНО назвал неверную версию, по-прежнему
обязан получить `KIR-P004` — там автор сказал неправду, а не промолчал. Два
разных факта обязаны давать два разных исхода, и оба проверены ниже.
"""
from __future__ import annotations

import unittest

from kukai.ir import compiler, sandbox
from kukai.ir.spec import IR_VERSION

_OP = ('{"op":"create_wall","id":"w1","p0_mm":[0,0],"p1_mm":[4000,0],'
       '"level":{"by":"name","value":"L1"}}')


def _program_of(script: str) -> tuple[dict, str]:
    """Скрипт → программа ровно так, как её собирает `serving`."""
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
        compiler.plan_program(program)  # не бросает — это и есть проверка

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
    """Контроль с другой стороны границы. Без него починка была бы сокрытием."""

    def test_неверная_версия_в_конверте_даёт_KIR_P004(self):
        program, _ = _program_of(
            f'program = {{"ir_version":"2.0","ops":[{_OP}]}}')
        self.assertEqual(program.get("ir_version"), "2.0",
                         "штамп перезаписал авторскую версию — это сокрытие")
        with self.assertRaises(Exception) as ctx:
            compiler.plan_program(program)
        self.assertIn("KIR-P004", str(ctx.exception))


class ВерсияБерётсяУРеестра(unittest.TestCase):
    """Второе место, обязанное совпадать с реестром, — именной дефект дерева."""

    def test_штамп_не_литерал(self):
        import inspect
        src = inspect.getsource(sandbox)
        self.assertIn("from kukai.ir.spec import IR_VERSION", src,
                      "версия обязана спрашиваться у реестра, а не писаться числом")

    def test_штамп_следует_за_реестром(self):
        program, _ = _program_of(f"ops = [{_OP}]")
        self.assertEqual(program["ir_version"], IR_VERSION)


if __name__ == "__main__":
    unittest.main()
