"""ПЛАН И ВЕРДИКТ — В ЯЗЫКЕ МОДЕЛИ, И БЕЗ ДЫРЫ НАРУЖУ.

Замер 03.08, живой круг на девяти витках. Модель, писавшая скрипт в песочнице,
получала на `preview()` и `design_check()` голый

    KIR-B006: NameError: name 'preview' is not defined

— и ВСЯ собранная программа при этом выбрасывалась: отказ песочницы отдаёт ноль
операций, значит ход терялся целиком. Зрение было построено (`preview.py` —
109 КБ, `design_check.py` — 112 КБ), но двери из него в язык модели не было:
план уходил по вебсокету на панель ЧЕЛОВЕКА, у вердикта не было ни одного
импортёра во всём дереве, кроме собственного теста.

ЧТО ЗДЕСЬ ДЕРЖИТСЯ, кроме самого шва:

1. ГРАНИЦА ПЕСОЧНИЦЫ НЕ СДВИНУЛАСЬ. Два имени внесены УЗКИМИ ФУНКЦИЯМИ, а не
   модулями, и тяжёлые модули, которые они зовут, лежат в `sys.modules` ребёнка
   — то есть ровно там, откуда сбежавший код мог бы их достать. Проверяется
   ЗАМЕРОМ: скрипт по-прежнему не может ни импортировать их, ни открыть файл,
   ни дотянуться до сети, и корень по-прежнему пуст.
2. ЦЕНА ПЛАТИТСЯ ТОЛЬКО ТЕМ, КТО ЗОВЁТ. Модуль вердикта — +536 мс и +43 МБ на
   запуск, а скрипт исполняется ДВАЖДЫ (`replay_check`). Прогрев решает по
   ИСХОДНИКУ (`course.language.warm_for_source`), и ход, который этих имён не
   пишет, обязан остаться прежним по цене.
3. ВЫЗОВ НЕ ЗАБИРАЕТ ПРОГРАММУ. `take_ops()` — дверь песочницы; позвать её из
   `preview()` значило бы напечатать план и оставить ход без программы, причём
   молча: и план, и вердикт при этом печатаются исправно.

Прогон: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_plan_and_verdict_in_the_sandbox.py -q
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir import sandbox  # noqa: E402

#: РОВНО прод: `serving._sandbox_policy()` строит `SandboxPolicy(replay_check=True)`
#: и ничего больше не трогает. Модуль языка — умолчание политики.
POLICY = sandbox.SandboxPolicy(replay_check=True)

#: Маленькое, но замкнутое здание: две комнаты, окно, дверь. Нужно именно
#: замкнутое — на незамкнутом вердикт честно не считает площадей, и тест мерил
#: бы отсутствие геометрии, а не доезд вердикта.
HOUSE = '''
lvl = create_level(elev_mm=0, name="Этаж 1")
walls = []
for p0, p1 in [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
               ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
               ((4000, 0), (4000, 5000))]:
    walls.append(create_wall(p0_mm=p0, p1_mm=p1, level=lvl, height_mm=3000))
create_room(xy=(2000, 2500), level=lvl, name="Жилая комната")
create_room(xy=(6000, 2500), level=lvl, name="Кухня")
create_door(host=walls[4], offset_mm=2500)
create_window(host=walls[0], offset_mm=2000)
create_window(host=walls[2], offset_mm=2000)
'''


class ThePlanAndTheVerdictReachTheModel(unittest.TestCase):

    def test_both_names_are_callable_from_the_script(self) -> None:
        """Шов целиком: имя есть, вызов проходит, ответ приходит В STDOUT
        КВИТАНЦИИ ЭТОГО ЖЕ ХОДА, и программа при этом доезжает."""
        result = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\n", policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.ops), 11)
        self.assertIn("ПЛАН ПРОГРАММЫ", result.stdout)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)

    def test_the_plan_names_what_it_did_not_draw(self) -> None:
        """План без переписи — картинка. Перепись обязана доехать вместе с ним."""
        result = sandbox.execute_author_script(HOUSE + "preview()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("нарисовано", result.stdout)
        self.assertIn("план НЕ показывает", result.stdout)

    def test_the_verdict_sees_the_rooms_the_script_wrote(self) -> None:
        """ГЛАВНОЕ ЧИСЛО. До 03.08 вердикт по операциям KIR отвечал «HAB000 —
        model has no rooms» при живых `create_room`: формы не сходились, а
        диагноз врал про здание."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertNotIn("HAB000", result.stdout)
        self.assertIn("rooms 2", result.stdout)
        self.assertIn("полигон помещения получили 2 из 2", result.stdout)

    def test_the_verdict_headline_is_not_stronger_than_its_body(self) -> None:
        """Заголовок — единственная строка, которую читают всегда."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        head = next(line for line in result.stdout.splitlines()
                    if "ВЕРДИКТ О ЗАМЫСЛЕ" in line)
        if "ПРИГОДЕН" in head and "НЕПРИГОДЕН" not in head:
            self.assertIn("НЕ ОЦЕНЕНО", head, head)

    def test_calling_them_does_not_swallow_the_program(self) -> None:
        """`take_ops()` — дверь ПЕСОЧНИЦЫ. Позвать её из курса значило бы
        напечатать план и оставить ход без программы, причём молча."""
        with_calls = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\nscore()\n", policy=POLICY)
        without = sandbox.execute_author_script(HOUSE, policy=POLICY)
        self.assertTrue(with_calls.ok,
                        with_calls.refusal and with_calls.refusal.render())
        self.assertTrue(without.ok, without.refusal and without.refusal.render())
        self.assertEqual(with_calls.program_digest, without.program_digest,
                         "печать плана/вердикта изменила саму программу")

    def test_two_runs_of_the_same_script_agree(self) -> None:
        """`replay_check` включён в проде, и он ловит недетерминизм ВЫХОДА.
        Тяжёлые модули (numpy поднимает пул потоков OpenBLAS) обязаны его не
        сломать — иначе подпись исходника перестала бы что-либо удостоверять."""
        result = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\n", policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertTrue(result.isolation.get("replay_checked"))


class TheBoundaryDidNotMove(unittest.TestCase):
    """Внесли способность — обязаны ЗАМЕРИТЬ, не внесли ли заодно дыру."""

    def _refusal(self, script: str) -> sandbox.SandboxRefusal:
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertFalse(result.ok, f"скрипт прошёл, а не должен был: {script!r}")
        return result.refusal

    def test_the_warmed_modules_are_still_not_importable(self) -> None:
        """САМОЕ ВАЖНОЕ ЗДЕСЬ. shapely/numpy/networkx теперь лежат в
        `sys.modules` ребёнка — то есть импорт нашёл бы их в КЭШЕ, не спросив
        стража `sys.meta_path` вовсе. Не спасает кэш: белый список стоит на
        `builtins.__import__` скрипта и проверяет ИМЯ, а не наличие.

        Скрипт здесь СНАЧАЛА зовёт вердикт (значит модули точно прогреты) и
        только потом пробует импорт — иначе тест мерил бы запрет на то, чего в
        процессе и не было.
        """
        for module in ("numpy", "shapely", "networkx", "kukai"):
            with self.subTest(module=module):
                refusal = self._refusal(HOUSE + f"design_check()\n"
                                                f"import {module}\n")
                self.assertEqual(refusal.code, "KIR-B004")

    def test_the_injected_names_are_functions_and_not_modules(self) -> None:
        """Модуль в пространстве скрипта отдал бы своё пространство имён
        целиком. Песочница модулей не инжектирует (`_child_main`), и внесённое
        обязано быть УЗКИМ: две функции, и ничего кроме."""
        result = sandbox.execute_author_script(
            'print(type(preview).__name__, type(design_check).__name__)\n'
            'create_level(elev_mm=0, name="Э1")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("function function", result.stdout)

    def test_files_are_still_unreachable(self) -> None:
        refusal = self._refusal('open("/etc/passwd")\n')
        self.assertEqual(refusal.code, "KIR-B005")

    def test_the_network_family_is_still_closed(self) -> None:
        refusal = self._refusal("import socket\n")
        self.assertEqual(refusal.code, "KIR-B004")
        self.assertIn("сети нет", refusal.message_ru)

    def test_isolation_holds_on_a_run_that_warmed_the_heavy_modules(self) -> None:
        """Замер, а не намерение: изоляция докладывается КАЖДЫМ запуском, и
        запуск с прогревом обязан доложить то же самое."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        isolation = result.isolation
        self.assertEqual(isolation["filesystem"], "chroot")
        self.assertTrue(str(isolation["namespaces"]).startswith("user"),
                        isolation["namespaces"])
        self.assertTrue(str(isolation["network_probe"]).startswith("unreachable"),
                        isolation["network_probe"])
        self.assertEqual(isolation["warmed"], ["kukai.ir.design_check"])


class TheBudgetIsNotEatenByOurOwnImports(unittest.TestCase):
    """`memory_mb` обещает СКРИПТУ столько-то мегабайт СВЕРХ занятого.

    ДЕФЕКТ, найденный этим же прогоном 03.08 и починенный тут же. Снимок
    занятого (`_self_vm_size`) брался ДО прогрева, поэтому прогретые
    numpy/shapely съедали бюджет СКРИПТА — адресного пространства они резервируют
    кратно больше, чем занимают RSS (пик 66 МБ при пределе 256). Живая программа
    на 298 операций умирала MemoryError'ом ВНУТРИ `json.dumps` на выходе, а
    наружу это выходило как «KIR-B012: результат не сериализуется» с `blame:
    sandbox` — то есть ход терялся целиком и по неверному адресу.
    """

    def test_the_limit_grows_with_what_we_loaded(self) -> None:
        warm = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                             policy=POLICY)
        plain = sandbox.execute_author_script(HOUSE, policy=POLICY)
        for result in (warm, plain):
            self.assertTrue(result.ok,
                            result.refusal and result.refusal.render())
        self.assertGreater(
            warm.isolation["limits"]["RLIMIT_AS"],
            plain.isolation["limits"]["RLIMIT_AS"],
            "предел адресного пространства не вырос вместе с прогревом — "
            "значит бюджет скрипта съеден нашими же импортами")

    def test_a_big_program_still_survives_the_verdict(self) -> None:
        """Замер, а не арифметика: 250 операций плюс вердикт при бюджете по
        умолчанию."""
        script = (
            'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'for i in range(60):\n'
            '    x = i * 4000\n'
            '    create_wall(p0_mm=(x, 0), p1_mm=(x, 4000), level=lvl, '
            'height_mm=3000)\n'
            '    create_wall(p0_mm=(x, 0), p1_mm=(x + 4000, 0), level=lvl, '
            'height_mm=3000)\n'
            '    create_wall(p0_mm=(x, 4000), p1_mm=(x + 4000, 4000), '
            'level=lvl, height_mm=3000)\n'
            '    create_room(xy=(x + 2000, 2000), level=lvl, '
            'name="Комната %d" % i)\n'
            'design_check()\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertGreater(len(result.ops), 240)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)


class TheCostIsPaidOnlyByWhoAsks(unittest.TestCase):

    def test_a_script_that_never_names_them_warms_nothing(self) -> None:
        """Безусловный прогрев стоил бы +1.1 с КАЖДОМУ ходу при счастливом пути
        в 121 мс. Решает исходник, и это не эвристика: имя, которого модель не
        написала, она вызвать не может — `globals`, `eval`, `exec` и
        `__import__` скрипту закрыты."""
        result = sandbox.execute_author_script(
            'create_level(elev_mm=0, name="Этаж 1")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.isolation.get("warmed"), [])

    def test_the_hook_loads_exactly_what_the_name_needs(self) -> None:
        """Прогрет ПЛАН — не грузим вердикт, и наоборот. Иначе условие было бы
        одним общим тумблером с видом на точность."""
        plan_only = sandbox.execute_author_script(HOUSE + "preview()\n",
                                                  policy=POLICY)
        self.assertTrue(plan_only.ok,
                        plan_only.refusal and plan_only.refusal.render())
        self.assertEqual(plan_only.isolation.get("warmed"),
                         ["kukai.ir.preview"])


class TheBudgetRefusalSaysHowFarItGot(unittest.TestCase):
    """Д-7. Курс велит печатать итоги в конце скрипта — а при исчерпании
    bulk-бюджета скрипт снимается на операции №301, и печать НЕ ВЫПОЛНЯЕТСЯ
    ВООБЩЕ: `stdout` квитанции приходит пустым. Модель узнаёт, что упёрлась, но
    не узнаёт, где резать, и следующий ход начинает вслепую."""

    def test_the_refusal_carries_the_census_of_what_was_collected(self) -> None:
        script = ('lvl = create_level(elev_mm=0, name="Э1")\n'
                  'for i in range(200):\n'
                  '    create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 3000), '
                  'level=lvl, height_mm=3000)\n'
                  '    create_room(xy=(i * 100 + 50, 1500), level=lvl, '
                  'name="К%d" % i)\n'
                  'print("итоги")\n')
        result = sandbox.execute_author_script(
            script, policy=sandbox.SandboxPolicy(replay_check=False))
        self.assertFalse(result.ok)
        text = result.refusal.render()
        self.assertIn("KIR-L001", text)
        # Печать автора действительно не доехала — иначе теста бы не было.
        self.assertEqual(result.stdout, "")
        # …поэтому числа обязаны ехать в самом отказе.
        self.assertIn("СОБРАНО ДО ОТКАЗА: 300 операций", text)
        self.assertIn("create_wall 150", text)
        self.assertIn("create_room 149", text)


class TheOperatorSwitchReachesTheChild(unittest.TestCase):
    """Окружение ребёнка собирается нами с нуля, а потом стирается целиком.
    Не перенесённый тумблер читается в ребёнке как «оператор выключил» — и
    вердикт отвечал бы «включите то, что уже включено»."""

    def test_checker_v2_is_visible_inside_the_sandbox(self) -> None:
        self.assertIn("KUKAI_CHECKER_V2", sandbox.ENV_PASSTHROUGH)
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertNotIn("KUKAI_CHECKER_V2=1 не выставлен", result.stdout)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)

    def test_a_switched_off_checker_refuses_instead_of_falling_back(self) -> None:
        """Выключен — значит отказ С ПРИЧИНОЙ, а не тихий откат на v1: у v1 нет
        ни трёхзначного вердикта, ни покрытия, и отличить его от настоящего
        было бы нечем."""
        was = os.environ.get("KUKAI_CHECKER_V2")
        os.environ["KUKAI_CHECKER_V2"] = "0"
        try:
            result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                                   policy=POLICY)
        finally:
            if was is None:
                os.environ.pop("KUKAI_CHECKER_V2", None)
            else:
                os.environ["KUKAI_CHECKER_V2"] = was
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("ВЕРДИКТ НЕДОСТУПЕН", result.stdout)
        # Программа при этом НЕ теряется: недоступный вердикт — не сорванный ход.
        self.assertEqual(len(result.ops), 11)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
