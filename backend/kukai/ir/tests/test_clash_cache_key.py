"""КЛЮЧ КЭША ОБЯЗАН ПОКРЫВАТЬ КАЖДЫЙ ВХОД, СПОСОБНЫЙ ПРЕВРАТИТЬ ОТВЕТ В ОТКАЗ.

ВОСПРОИЗВЕДЁННЫЙ ДЕФЕКТ (замер 11.08.2026, `/tmp/wiring/m_cachekey.py`, одна
пачка из 40 воздуховодов, флаг включён):

    KUKAI_IR_CLASH_MAX_PAIRS=8      -> status=over_cap, work=219
    KUKAI_IR_CLASH_MAX_PAIRS=100000 -> status=over_cap   <- КЭШ ОТДАЛ СТАРОЕ
    кэш очищен, то же окружение     -> status=ok, пар=219

Ключ считался по `sha(pack)` + `sha(sections)` + `new_from` и НЕ покрывал
четыре потолка (`KUKAI_IR_CLASH_MAX_{ELEMENTS,BODIES,OFFERS,PAIRS}`), хотя
каждый из них читается ВО ВРЕМЯ ВЫЗОВА и каждый решает между настоящим
ответом и отказом «ПРОВЕРКА НА КОЛЛИЗИИ НЕ СЧИТАЛАСЬ… это "не смотрели"».

ЭТО ОПРОВЕРГАЕТ СОБСТВЕННЫЙ ДОКСТРИНГ КЭША, который обещает дословно:
«ключ — sha самой пачки, поэтому промах двух потоков стоит лишнего счёта, но
не может отдать ЧУЖОЙ ответ». Отдавал.

И БЬЁТ ОН РОВНО ТАМ, ГДЕ ЧЕЛОВЕК БОЛЬШЕ ВСЕГО ДОВЕРЯЕТ ОТВЕТУ. Потолок
поднимают ИМЕННО ПОТОМУ, что большое здание отказало; поднявший получает
обратно кэшированный отказ и читает его как «всё ещё слишком велико», хотя
второй раз никто не смотрел.

ТРЕТИЙ СЛУЧАЙ ОДНОГО ДЕФЕКТА В ЭТОМ МОДУЛЕ ЗА МАРАФОН:
  * потолок с именем «число ТЕЛ», сравнивавший число ЭЛЕМЕНТОВ;
  * ключ кэша без `new_from` — та же пачка с другой границей хода;
  * ключ кэша без потолков — этот.
Общее у них не тема, а форма: ВЕЛИЧИНА, НЕ ПОКРЫВАЮЩАЯ ТОГО, ЧТО МЕНЯЕТ
ОТВЕТ. Поэтому список входов живёт рядом с ключом и держится тестом: пятый
добавленный потолок обязан ВЫНУДИТЬ решение, а не тихо остаться снаружи.
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import clash_bundle as CB


def _ducts(n, step=60.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


class _Env:
    """Окружение, возвращаемое дословно: тест, оставивший потолок за собой,
    отравил бы соседние."""

    NAMES = ("KUKAI_IR_CLASH", "KUKAI_IR_CLASH_MAX_ELEMENTS",
             "KUKAI_IR_CLASH_MAX_BODIES", "KUKAI_IR_CLASH_MAX_OFFERS",
             "KUKAI_IR_CLASH_MAX_PAIRS")

    def __enter__(self):
        self._saved = {n: os.environ.get(n) for n in self.NAMES}
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        CB._CACHE.clear()
        return False


class ARaisedCeilingIsAFreshQuestion(unittest.TestCase):
    """Сердцевина: поднятый потолок обязан дать НОВЫЙ ответ, а не старый."""

    def test_raising_the_pair_cap_stops_returning_the_refusal(self):
        pack = [{"ops": _ducts(40)}]
        with _Env():
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "8"
            refused = CB._report(pack)
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "100000"
            again = CB._report(pack)
        self.assertEqual(refused["status"], "over_cap", refused)
        self.assertEqual(again["status"], "ok",
                         "кэш вернул отказ на поднятом потолке")
        self.assertGreater(again["total_findings"], 0)

    def test_lowering_a_cap_stops_returning_the_answer(self):
        """И в обратную сторону: опущенный потолок обязан отказать, а не
        отдать вчерашний успех."""
        pack = [{"ops": _ducts(40)}]
        with _Env():
            ok = CB._report(pack)
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "8"
            now = CB._report(pack)
        self.assertEqual(ok["status"], "ok", ok)
        self.assertEqual(now["status"], "over_cap", now)

    def test_every_cap_moves_the_key(self):
        """Не «какой-то из потолков», а КАЖДЫЙ: потолок, не двигающий ключ,
        и есть тот, который однажды отдаст чужой ответ."""
        pack = [{"ops": _ducts(6)}]
        with _Env():
            base = CB._cache_key(pack, None, None)
            for name, _reader in CB.ANSWER_INPUTS:
                var = f"KUKAI_IR_CLASH_{name.upper()}"
                self.assertIn(var, os.environ.get(var, "") or var)
                os.environ[var] = "17"
                moved = CB._cache_key(pack, None, None)
                os.environ.pop(var, None)
                self.assertNotEqual(base, moved, f"{name} не входит в ключ")


class TheKeyShowsWhatWentIntoIt(unittest.TestCase):
    """ЧЕТЫРЕ ПОТОЛКА НЕ СВЁРНУТЫ В ОДНО ЧИСЛО МОЛЧА. Свёрнутые в sha, они
    стали бы невидимы, и следующий, кто добавит пятый, не узнал бы, что его
    надо туда положить."""

    def test_the_key_names_every_input_it_covers(self):
        with _Env():
            key = CB._cache_key([{"ops": _ducts(3)}], None, 2)
        for name, _reader in CB.ANSWER_INPUTS:
            self.assertIn(name, key, f"{name} не виден в ключе")
        self.assertIn("new_from=2", key)
        self.assertIn("bundle=", key)

    def test_the_bundle_digest_is_still_a_digest(self):
        """Пачка сворачивается в sha намеренно: она бывает в тысячи операций.
        Видимыми обязаны быть МАЛЫЕ входы, а не весь вход."""
        with _Env():
            key = CB._cache_key([{"ops": _ducts(3)}], None, None)
        self.assertNotIn("create_duct", key)
        self.assertLess(len(key), 400)

    def test_absent_and_present_sections_are_different_keys(self):
        with _Env():
            a = CB._cache_key([{"ops": _ducts(3)}], None, None)
            b = CB._cache_key([{"ops": _ducts(3)}], {"levels": []}, None)
        self.assertNotEqual(a, b)

    def test_absent_and_zero_new_from_are_different_keys(self):
        """«Границы не называли» и «граница на первой программе» дают разные
        ответы (`none` против `whole_bundle_new`), значит и разные ключи."""
        with _Env():
            a = CB._cache_key([{"ops": _ducts(3)}], None, None)
            b = CB._cache_key([{"ops": _ducts(3)}], None, 1)
        self.assertNotEqual(a, b)


class TheListOfInputsIsClosedAndForcesADecision(unittest.TestCase):
    """ЗАМОК ОТ ПЯТОГО ПОТОЛКА. Умолчания нет: потолок, добавленный в модуль и
    не внесённый в `ANSWER_INPUTS`, обязан уронить ЭТОТ тест, а не однажды
    отдать оператору кэшированный отказ."""

    def test_every_ceiling_in_the_module_is_covered(self):
        ceilings = {name for name in dir(CB)
                    if name.startswith("_max_") and callable(getattr(CB, name))}
        # имя входа — это имя функции без ведущего подчёркивания
        covered = {f"_{name}" for name, _reader in CB.ANSWER_INPUTS}
        self.assertEqual(ceilings - covered, set(),
                         f"потолки вне ключа: {sorted(ceilings - covered)}")

    def test_each_entry_reads_the_live_value(self):
        """Вход, читающий не то, что читает сам отказ, — тот же дефект с
        другой стороны: ключ двигался бы, а ответ нет."""
        with _Env():
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "123"
            live = dict((name, reader()) for name, reader in CB.ANSWER_INPUTS)
        self.assertEqual(live["max_pairs"], 123)

    def test_the_flag_itself_cannot_serve_a_cached_answer(self):
        """Флаг в ключ НЕ входит, и это не пробел: `bundle_clash_report`
        проверяет его ДО кэша и возвращает `None`, не заглядывая внутрь.
        Проверено, а не предположено."""
        pack = [{"ops": _ducts(6)}]
        with _Env():
            self.assertEqual(CB.bundle_clash_report(pack)["status"], "ok")
            os.environ.pop("KUKAI_IR_CLASH", None)
            self.assertIsNone(CB.bundle_clash_report(pack))


if __name__ == "__main__":
    unittest.main()
