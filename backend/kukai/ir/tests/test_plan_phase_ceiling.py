"""У ЧИСЛА ФАЗ НЕ БЫЛО ПОТОЛКА ВОВСЕ — ПРОГРАММА НА 200 000 ОПОВ С ЧЁРНОГО ХОДА.

ЗАМЕР 11.08.2026 (`/tmp/wiring/z2.py`, `compiler.split_phases` напрямую,
таблица фаз по 20 опов — то есть каждое звено В ПРЕДЕЛАХ авторского бюджета):

    фаз      2, опов      40 -> ПРИНЯТ,  split   0 мс
    фаз    512, опов  10 240 -> ПРИНЯТ,  split   5 мс
    фаз  2 000, опов  40 000 -> ПРИНЯТ,  split  26 мс
    фаз 10 000, опов 200 000 -> ПРИНЯТ,  split 236 мс

`MAX_OPS_PER_PROGRAM = 20` меряет ОДНО звено и меряет верно. Числа звеньев не
мерил никто, поэтому план обходил авторский бюджет умножением: двадцать опов
в фазе, десять тысяч фаз.

ОТКУДА ВЫВЕДЕН ПОТОЛОК, А НЕ НАЗНАЧЕН. Каждая пишущая фаза становится ОДНОЙ
программой журнала сессии (`plan_stream.publish` зовётся в общем теле на
каждой фазе). Журнал держит `journal._max_programs()` программ и вытесняет
самые старые. Значит план длиннее журнала ВЫТЕСНЯЕТ СОБСТВЕННОЕ НАЧАЛО, пока
ещё строится, и всё, что читает журнал, начинает читать здание без начала:

  * вердикт о здании судит ХВОСТ и сам об этом говорит (`programs_evicted`,
    «судится ХВОСТ здания, а не всё»);
  * пачка проверки на коллизии теряет ранние фазы — и «внесено этим ходом»
    считается против базы, которой уже нет;
  * `base_digest` вьюера покрывает вытеснение, поэтому живой вид обязан
    пересинхронизироваться посреди плана (`StaleBase`).

Потолок поэтому РАВЕН вместимости журнала и СПРАШИВАЕТСЯ у него во время
вызова, а не копируется числом: копия разошлась бы с оригиналом на первой же
правке `KUKAI_KIR_JOURNAL_PROGRAMS` — ровно тот класс, который эта серия и
закрывает.

ЧТО ЭТОТ ПОТОЛОК НЕ ОБЕЩАЕТ. Что вытеснения не будет: сессия, уже объявившая
программы до плана, съедает часть вместимости, и план в пределах потолка всё
равно может вытеснить чужое начало. Это НЕОБХОДИМОЕ условие, а не достаточное,
и `programs_evicted` остаётся тем, кто говорит правду постфактум.
"""
from __future__ import annotations

import asyncio
import unittest

from kukai.ir import serving as S
from kukai.live import journal as _journal


def _plan(nphases: int, ops_per: int = 2) -> dict:
    ops, phases = [], []
    for p in range(nphases):
        ids = []
        for i in range(ops_per):
            oid = f"w{p}_{i}"
            ops.append({"op": "create_level", "id": oid,
                        "name": f"L{p}_{i}",
                        "elevation_mm": float(p * 1000 + i)})
            ids.append(oid)
        phases.append({"index": p, "name": f"ф{p}", "op_ids": ids})
    return {"ops": ops, "phases": phases}


class _Authored:
    from_script = False
    author_digest = ""
    env_digest = ""
    receipt = None
    refusal = None
    args: dict = {}


def _run(program):
    async def _bridge(*a, **k):
        raise AssertionError("мост не должен быть тронут: отказ до записи")

    return asyncio.run(S._run_plan(
        program, None, _bridge, query_id="q", authored=_Authored()))


class ThePhaseCountHasACeiling(unittest.TestCase):

    def test_a_plan_longer_than_the_journal_is_refused_before_any_write(self):
        """ОТКАЗ ДО МОСТА. План, который вытеснит собственное начало, не имеет
        права начать строиться: половина здания уже была бы в модели."""
        result = _run(_plan(S.max_plan_phases() + 1))
        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(result["stage"], "plan")

    def test_the_refusal_names_both_numbers(self):
        over = S.max_plan_phases() + 7
        result = _run(_plan(over))
        self.assertIn(str(over), result["message_ru"])
        self.assertIn(str(S.max_plan_phases()), result["message_ru"])

    def test_the_ceiling_is_asked_of_the_journal_not_copied(self):
        """Копия числа разошлась бы с оригиналом на первой правке потолка
        журнала — тот же класс, что закрывали весь марафон."""
        self.assertEqual(S.max_plan_phases(), _journal._max_programs())

    def test_a_plan_at_the_ceiling_is_not_refused_by_this_rule(self):
        """Потолок, отказывающий на границе, отказывает исправному плану.
        Здесь мост не тронут, поэтому проверяется РОВНО эта причина отказа."""
        result = _run(_plan(3))
        self.assertNotIn("вместимости журнала",
                         str(result.get("message_ru") or ""))

    def test_the_ceiling_moves_with_the_journal(self):
        import os

        prev = os.environ.get("KUKAI_KIR_JOURNAL_PROGRAMS")
        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "16"
        try:
            self.assertEqual(S.max_plan_phases(), 16)
            result = _run(_plan(17))
            self.assertTrue(result["refused"])
        finally:
            if prev is None:
                os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)
            else:
                os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = prev

    def test_the_op_budget_still_measures_one_phase(self):
        """Потолок числа ФАЗ и авторский бюджет ОПОВ — РАЗНЫЕ величины, и одна
        не подменяет другую.

        🔴 ЧИСЛО ОТСЮДА УБРАНО. Прежняя редакция писала
        `assertEqual(C.MAX_OPS_PER_PROGRAM, 20)`, и когда владелец поднял
        бюджет до 100 (15.08), тест покраснел — при том, что предмет его
        проверки не изменился ни на байт: фазы по-прежнему меряются не опами.
        Пин величины в тесте о РАЗЛИЧИИ величин — это тот самый именной дефект
        дерева: число объявлено в `compiler`, прочитано здесь, и ничто не
        заставляло их совпасть.

        Что осталось: обе величины существуют, положительны и НЕ РАВНЫ. Это и
        есть утверждение «их две, и они про разное», и оно переживает любую
        смену любой из них."""
        from kukai.ir import compiler as C

        self.assertGreater(C.MAX_OPS_PER_PROGRAM, 0)
        self.assertGreater(S.max_plan_phases(), 0)
        self.assertNotEqual(S.max_plan_phases(), C.MAX_OPS_PER_PROGRAM)


if __name__ == "__main__":
    unittest.main()
