"""КУРС ПО `program_py` — тесты, которые держат его честным.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, И ПОЧЕМУ ИМЕННО ЭТО.

1. ЧИСЛА ПЕРЕСЧИТЫВАЮТСЯ. Каждый замер курса берётся заново с диска и
   сверяется с записанным. Устаревший замер в курсе неотличим от выдумки, и
   отличить их может только пересчёт.
2. ПРИМЕРЫ ИСПОЛНЯЮТСЯ. Каждый рецепт гоняется НАСТОЯЩЕЙ песочницей
   (отдельный процесс, chroot, ноль сети, `replay_check` — то есть проверка
   детерминизма замером) и его выход компилируется на ШЕСТИ версиях Revit.
   Пример, который не запускали, — это обещание.
3. ПОКАЗАННЫЕ ЧИСЛА — ЗАМЕР ЭТОГО ПРОГОНА. `Recipe.ops`/`elements` сверяются
   с тем, что реально вышло. Курс не вправе обещать одно, а строить другое.
4. ШОВ ЦЕЛЫЙ ИЛИ ЕГО НЕТ. Указатель в описании инструмента обещает имена;
   тест требует, чтобы обещанное было ДОСТИЖИМО из песочницы. Половина шва —
   красный тест, а не тихий раунд, потерянный моделью.
5. ДВА КУРСА НЕ ПЕРЕСЕКАЮТСЯ. `skill.py` — про поле `program` и макросы, этот
   — про `program_py`. Пересечение оплачивается дважды и расходится на первой
   правке.

ЦЕНА НАБОРА. Восемь прогонов песочницы по ~0.3 с плюс шесть эмиссий на
рецепт. Это самый дорогой тест пакета, и он такой намеренно: дешёвая проверка
курса проверяла бы текст, а не работу.
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import compiler, sandbox, skill, spec
from kukai.ir import course as C
from kukai.ir.course import corpus, lessons, recipes
from kukai.ir.ground import ground
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

#: Рецепты исполняются РОВНО тем составом имён, который получит модель после
#: шва: язык плюс курс. Ни одного послабления политики, кроме `replay_check` —
#: он ужесточает, а не ослабляет: скрипт гоняется дважды со сверкой дайджестов.
POLICY = sandbox.SandboxPolicy(dsl_module="kukai.ir.course.language",
                               replay_check=True)


def _program(result: sandbox.SandboxResult) -> dict:
    envelope = dict(result.envelope or {})
    envelope.pop("ir_version", None)
    return {"ir_version": spec.IR_VERSION, **envelope, "ops": result.ops}


class _Run:
    """Один прогон рецепта. Кэшируется на класс: восемь рецептов × шесть
    версий — это уже заметное время, и платить за него дважды незачем."""

    _cache: dict[str, sandbox.SandboxResult] = {}

    @classmethod
    def of(cls, name: str) -> sandbox.SandboxResult:
        if name not in cls._cache:
            cls._cache[name] = sandbox.execute_author_script(
                recipes.RECIPES[name].source, policy=POLICY)
        return cls._cache[name]


# ═════════════════════════════════════════════════════════════════════════
# 1. ЧИСЛА
# ═════════════════════════════════════════════════════════════════════════

class EveryNumberRecomputes(unittest.TestCase):

    def test_every_measurement_is_recomputed_from_the_corpus(self) -> None:
        """Замер против его собственного источника, по одному зданию.

        Пропуск объявляется ПОИМЁННО: «разбора нет на этом боксе» и «разбор
        есть, но пуст» — разные факты, и путать их дороже, чем не мерить.
        """
        missing = [b for b in corpus.BUILDINGS if not corpus.available(b)]
        if len(missing) == len(corpus.BUILDINGS):
            self.skipTest(f"корпуса нет на боксе: {corpus.DECOMPILE_ROOT}")
        drift = []
        for key, m in corpus.MEASUREMENTS.items():
            if m.recompute is None:
                continue
            try:
                got = m.recompute()
            except FileNotFoundError:
                continue                       # этого здания на боксе нет
            if abs(got - m.value) > 0.051:
                drift.append(f"{key}: записано {m.value}, пересчёт {got}")
        self.assertEqual(drift, [], "замеры курса разошлись с корпусом")

    def test_the_derived_map_comes_from_acceptance_and_is_not_empty(self) -> None:
        """Второго списка производных категорий не заводится: он взят у
        приёмки, где несёт вес. Переименование `_OP_DERIVED` обязано сломать
        курс ГРОМКО."""
        derived = corpus.derived_categories()
        self.assertGreater(len(derived), 10)
        for category, ops in derived.items():
            self.assertTrue(category.startswith("OST_"), category)
            for op_name in ops:
                self.assertIn(op_name, spec.OPS, f"{category} <- {op_name}")

    def test_no_derived_category_has_an_op_of_its_own(self) -> None:
        """Урок «даром» стоит на этом: элементы производных категорий писать
        НЕЧЕМ. Утверждение проверяется по клеткам способности реестра."""
        derived = set(corpus.derived_categories())
        claimed = {kind for op in spec.OPS.values() for _a, kind in op.capability}
        self.assertEqual(derived & claimed, set())

    def test_our_own_trace_still_shows_zero_group_uses(self) -> None:
        """Число, ради которого курс написан. Пересчитывается по живой
        телеметрии, если она на боксе есть."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(C.__file__))))),
            "data", "telemetry", "kir_rejections.jsonl")
        if not os.path.exists(path) or not os.access(path, os.R_OK):
            self.skipTest("телеметрии отказов нет на этом боксе")
        import json
        ops = set()
        rows = 0
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rows += 1
                ops.add((json.loads(line) or {}).get("op_requested"))
        self.assertNotIn("create_group", ops)
        self.assertGreaterEqual(rows, corpus.LIVE_REJECTIONS_MEASURED)


# ═════════════════════════════════════════════════════════════════════════
# 2-3. ПРИМЕРЫ ИСПОЛНЯЮТСЯ, И ЧИСЛА — ЗАМЕР
# ═════════════════════════════════════════════════════════════════════════

class EveryRecipeRuns(unittest.TestCase):

    def test_every_recipe_runs_in_the_real_sandbox(self) -> None:
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                result = _Run.of(name)
                self.assertTrue(
                    result.ok,
                    result.refusal and result.refusal.render())
                self.assertTrue(result.isolation.get("replay_checked"))

    def test_the_numbers_the_course_shows_are_the_numbers_it_produces(self) -> None:
        """Показанное и построенное не могут разойтись по построению."""
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                item = recipes.RECIPES[name]
                got = C.measure(_Run.of(name).ops)
                self.assertEqual(got["операций написано"], item.ops)
                self.assertEqual(got["элементов объявлено"], item.elements)

    def test_every_recipe_compiles_on_all_six_revit_versions(self) -> None:
        """«Скрипт отработал» и «программа строится» — разные утверждения.
        Эмиссия ветвится по версиям, поэтому шесть, а не одна."""
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                program = _program(_Run.of(name))
                planned = compiler.plan_program(program, bulk=True)
                ground(planned.to_ops(), GROUND_SNAPSHOT)   # бросит при отказе
                for version in spec.REVIT_VERSIONS:
                    out = compiler.compile_program(
                        program, revit_version=version,
                        snapshot=GROUND_SNAPSHOT, bulk=True)
                    self.assertTrue(getattr(out, "ok", False),
                                    f"{name} не собрался под {version}")

    def test_the_pair_recipes_really_differ_in_form_not_in_result(self) -> None:
        """Пара «джуниор — сеньор» обязана давать ОДИН результат разной
        формой: сравнение, в котором различается и то и другое, ничего не
        показывает. Исключение названо — этажи покрывают разное число уровней,
        и это записано в `covers`."""
        for senior, junior in (("санузел", "санузел-джуниор"),):
            s, j = recipes.RECIPES[senior], recipes.RECIPES[junior]
            self.assertEqual(s.elements, j.elements)
            self.assertEqual(s.covers, j.covers)
            self.assertLess(s.ops, j.ops)

    def test_the_group_recipe_actually_produces_a_native_group(self) -> None:
        """Главный оп курса — целиком, до заземления членов.

        `create_group` был вызван 0 раз на 51 574 поднятых операции ровно
        потому, что заземление не заходило внутрь `members`. Тест держит
        починку: члены разрешаются ПО ИМЕНИ, как обычные опы.
        """
        ops = _Run.of("санузел").ops
        self.assertEqual(len(ops), 1)
        group = ops[0]
        self.assertEqual(group["op"], "create_group")
        self.assertEqual(len(group["members"]), 3)
        self.assertEqual(len(group["placements"]), 5)
        self.assertEqual(group["name"], "Кабинка су")
        grounded = ground(
            compiler.plan_program(_program(_Run.of("санузел")),
                                  bulk=True).to_ops(),
            GROUND_SNAPSHOT)
        for member in grounded[0]["members"]:
            self.assertIn("__grounded__", member["level"])
            self.assertEqual(member["level"]["__grounded__"]["via"], "name")

    def test_a_ref_inside_a_group_member_is_refused_and_says_why(self) -> None:
        """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ к уроку «единица». Показанная граница,
        которая на деле проходит, учит модель бояться работающего приёма."""
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'with unit("Блок", placements=[(3000, 0)]):\n'
                  '    w = create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                  'level=LVL, height_mm=3000)\n'
                  '    create_door(host=w, offset_mm=1500)\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        with self.assertRaises(Exception) as caught:
            compiler.plan_program(_program(result), bulk=True)
        self.assertIn("ref", str(caught.exception).lower())

    def test_a_group_member_cannot_stand_on_a_level_this_program_creates(self):
        """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ к «две программы».

        Найдено прогоном примера, а не рассуждением, и стоит здесь потому,
        что цена незнания — раунд. Обе ветки закрыты, и каждая своим кодом:
        ручка уровня — KIR-T001 на разборе, ИМЯ того же уровня — KIR-G101 на
        заземлении. Отсюда и правило урока: новый этаж и группа на нём это
        две программы.
        """
        by_handle = ('lvl = create_level(elev_mm=0, name="Новый")\n'
                     'with unit("Блок", placements=[(3000, 0)]):\n'
                     '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                     'level=lvl, height_mm=3000)\n')
        result = sandbox.execute_author_script(by_handle, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        with self.assertRaises(Exception) as caught:
            compiler.plan_program(_program(result), bulk=True)
        self.assertIn("KIR-T001", str(caught.exception))

        by_name = ('create_level(elev_mm=0, name="Новый")\n'
                   'with unit("Блок", placements=[(3000, 0)]):\n'
                   '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                   'level={"by": "name", "value": "Новый"}, height_mm=3000)\n')
        second = sandbox.execute_author_script(by_name, policy=POLICY)
        self.assertTrue(second.ok, second.refusal and second.refusal.render())
        planned = compiler.plan_program(_program(second), bulk=True)
        with self.assertRaises(Exception) as caught:
            ground(planned.to_ops(), GROUND_SNAPSHOT)
        self.assertIn("KIR-G101", str(caught.exception))

        # …и урок об этом ПРЕДУПРЕЖДАЕТ: граница, известная коду и неизвестная
        # курсу, — это раунд, потраченный моделью на наше молчание.
        text = lessons.lesson("единица")
        self.assertIn("KIR-T001", text)
        self.assertIn("KIR-G101", text)
        self.assertIn("ДВЕ ПРОГРАММЫ", text)

    def test_an_empty_unit_refuses_instead_of_making_an_empty_group(self) -> None:
        script = ('with unit("Пусто"):\n'
                  '    pass\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertFalse(result.ok)
        self.assertIn("не собрал ни одной операции", result.refusal.message_ru)

    def test_the_unit_context_restores_the_outer_program(self) -> None:
        """Единица не должна утаскивать за собой соседей: то, что написано
        ПОСЛЕ блока, обязано попасть в программу, а не в группу."""
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'with unit("Блок", placements=[(3000, 0)]):\n'
                  '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), level=LVL, '
                  'height_mm=3000)\n'
                  'create_room(xy=(1500, 1500), level=LVL, name="После")\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual([op["op"] for op in result.ops],
                         ["create_group", "create_room"])


# ═════════════════════════════════════════════════════════════════════════
# 4. ШОВ
# ═════════════════════════════════════════════════════════════════════════

class TheSeamIsWholeOrAbsent(unittest.TestCase):

    NAMES = ("course", "recipe", "unit", "score", "preview", "design_check")

    def test_the_course_names_are_reachable_through_the_shim(self) -> None:
        """Вторая половина шва проверена ЖИВЬЁМ до того, как его проведут."""
        script = "\n".join(
            [f'print("{name}", callable({name}))' for name in self.NAMES]
            + ['query_count(kind="wall")'])
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        for name in self.NAMES:
            self.assertIn(f"{name} True", result.stdout)

    def test_the_shim_still_drains_the_program(self) -> None:
        """`take_ops` в `dsl.__all__` намеренно нет; шим обязан импортировать
        его ИМЕНЕМ, иначе программа собиралась бы, а наружу выходил бы ноль
        операций — самый тихий из возможных дефектов."""
        from kukai.ir.course import language
        self.assertTrue(callable(getattr(language, "take_ops", None)))
        result = sandbox.execute_author_script(
            'create_level(elev_mm=0, name="L")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.isolation["harvest"], "dsl.take_ops()")

    def test_the_pointer_and_reachability_are_one_thing(self) -> None:
        """ГЛАВНЫЙ ТЕСТ ШВА. Указатель обещает имена — значит имена обязаны
        быть достижимы ИЗ ПРОДОВОЙ политики, а не только из шима. Пока шов не
        проведён, в описании инструмента указателя нет, и утверждение
        выполняется пусто; после — обе половины обязаны стоять вместе.
        Половина шва падает здесь, а не молча стоит раунда модели.
        """
        from kukai.ir.tool_doc import build_tool_description
        advertised = "course()" in build_tool_description()
        probe = sandbox.execute_author_script(
            'print("есть" if "course" in dir() else "нет")\n'
            'query_count(kind="wall")\n')
        self.assertTrue(probe.ok, probe.refusal and probe.refusal.render())
        reachable = "есть" in probe.stdout
        self.assertEqual(
            advertised, reachable,
            "указатель курса и достижимость его имён разошлись: "
            f"в описании {'есть' if advertised else 'нет'}, "
            f"в песочнице {'есть' if reachable else 'нет'}")

    def test_the_pointer_is_small_enough_to_hang_permanently(self) -> None:
        """Постоянная плата названа числом. Порог описания — 30 000 символов.

        ПРАВЛЕНО ПОСЛЕ ШВА, и это не ослабление, а исправление ДВОЙНОГО СЧЁТА.
        Тест писался, когда указателя в описании ещё НЕ БЫЛО, и моделировал
        «сколько станет, если добавить»: `len(описание) + len(указателя)`.
        После того как `tool_doc._course_pointer()` вставил его на место строки
        про `tools/design/examples/*`, та же арифметика считает указатель
        ДВАЖДЫ и объявляет перебор там, где его нет (29 685 + 705 = 30 390 при
        настоящих 29 685).

        Сохранены оба настоящих утверждения: указатель мал сам по себе, и
        описание целиком влезает в порог. Потерян только артефакт момента, в
        который тест был написан.
        """
        from kukai.ir.tool_doc import build_tool_description
        size = sum(len(line) + 1 for line in C.POINTER)
        self.assertLess(size, 700)
        description = build_tool_description()
        # Указатель обязан быть УЖЕ внутри — иначе двойной счёт был бы верен,
        # а шов разорван (это стережёт соседний тест про достижимость).
        self.assertIn("course(", description)
        self.assertLess(len(description), 30_000)

    def test_the_seam_is_described_and_names_real_places(self) -> None:
        self.assertEqual(len(C.SEAM), 2)
        for where, _what in C.SEAM:
            self.assertTrue(where.startswith("kukai/ir/"), where)
        self.assertEqual(sorted(C.SANDBOX_NAMES), sorted(self.NAMES))
        for value in C.SANDBOX_NAMES.values():
            self.assertTrue(callable(value))


# ═════════════════════════════════════════════════════════════════════════
# 5. ДВА КУРСА НЕ ПЕРЕСЕКАЮТСЯ; ТЕКСТ ВЛЕЗАЕТ В КАНАЛ
# ═════════════════════════════════════════════════════════════════════════

class TheCourseFitsAndDoesNotRepeatItself(unittest.TestCase):

    def test_every_lesson_fits_the_sandbox_stdout(self) -> None:
        """Урок обязан оставить место печати самой модели: `stdout` обрезается
        на `MAX_STDOUT_CHARS`, и курс, съевший обратную связь, отнимает ровно
        то, ради чего канал заведён."""
        for name in lessons.ORDER:
            with self.subTest(lesson=name):
                text = lessons.lesson(name)
                self.assertLessEqual(len(text), C.LESSON_CAP)
                self.assertLess(len(text), sandbox.MAX_STDOUT_CHARS)
                self.assertLessEqual(
                    max(len(line) for line in text.splitlines()), 88)

    def test_every_recipe_fits_the_sandbox_stdout(self) -> None:
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                self.assertLess(len(recipes.RECIPES[name].source),
                                sandbox.MAX_STDOUT_CHARS - 400)

    def test_the_index_names_every_lesson_and_every_recipe(self) -> None:
        index = lessons.index()
        for name in lessons.ORDER:
            self.assertIn(name, index)
        self.assertEqual(sorted(lessons.ORDER), sorted(lessons.LESSONS))
        self.assertEqual(sorted(recipes.ORDER), sorted(recipes.RECIPES))

    def test_an_unknown_topic_refuses_with_the_list_of_topics(self) -> None:
        """Отказ без списка — это второй раунд: модель не угадает написание,
        она попробует синоним."""
        with self.assertRaises(KeyError) as caught:
            lessons.lesson("группировка")
        for name in lessons.ORDER:
            self.assertIn(name, str(caught.exception))

    def test_the_two_courses_do_not_overlap(self) -> None:
        """`skill.py` — про поле `program` и макросы, этот курс — про
        `program_py`. Пересечение оплачивается дважды и расходится на первой
        правке. Мерится по ДЛИННЫМ общим фразам, а не по словам."""
        theirs = skill.build_skill_text()
        for name in lessons.ORDER:
            mine = lessons.lesson(name)
            sentences = [s.strip() for s in mine.replace("\n", " ").split(". ")
                         if len(s.strip()) > 60]
            for sentence in sentences:
                self.assertNotIn(sentence, theirs,
                                 f"урок «{name}» повторяет skill.py")

    def test_the_course_never_claims_a_macro_exists_in_the_script(self) -> None:
        """Самая дорогая возможная ложь этого курса: макросы в песочнице
        недостижимы, и совет ими воспользоваться стоил бы раунда."""
        for name in recipes.ORDER:
            source = recipes.RECIPES[name].source
            for macro in ("stack(", "series(", "grid_array("):
                self.assertNotIn(macro, source, f"{name}: {macro}")


# ═════════════════════════════════════════════════════════════════════════
# МЕТРИКА ПЕРЕНЯТИЯ
# ═════════════════════════════════════════════════════════════════════════

class TheExamplesAreNotPromises(unittest.TestCase):
    """Пример из `tools/design/examples/` — такой же артефакт, как рецепт.

    Соседи по каталогу (`tower_numpy.py`, `contour_shapely.py`) написаны до
    песочницы и НЕ МОГУТ быть отправлены моделью: там numpy и shapely. Новые
    два обязаны проходить прод-путь целиком, иначе они врут жанром.
    """

    ROOT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(C.__file__))))),
        "tools", "design", "examples")

    def _example(self, name: str):
        path = os.path.join(self.ROOT, name)
        if not os.path.exists(path):
            self.skipTest(f"примера нет на этом боксе: {path}")
        import importlib.util
        spec_ = importlib.util.spec_from_file_location(f"_ex_{name[:-3]}", path)
        module = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(module)
        return module

    def test_the_method_example_goes_the_whole_way(self) -> None:
        module = self._example("method_group_and_repeat.py")
        result = sandbox.execute_author_script(module.SCRIPT, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        got = C.measure(result.ops)
        self.assertGreater(got["определений групп"], 0)
        self.assertGreater(got["элементов внутри групп, %"], 0)
        program = _program(result)
        ground(compiler.plan_program(program, bulk=True).to_ops(),
               GROUND_SNAPSHOT)
        for version in spec.REVIT_VERSIONS:
            out = compiler.compile_program(program, revit_version=version,
                                           snapshot=GROUND_SNAPSHOT, bulk=True)
            self.assertTrue(getattr(out, "ok", False), version)

    def test_the_baseline_example_recomputes_the_line(self) -> None:
        module = self._example("method_baseline.py")
        rows = module.per_building()
        self.assertEqual(len(rows), len(corpus.BUILDINGS))
        measured = [row for _title, row in rows if "пропуск" not in row]
        if not measured:
            self.skipTest("корпуса нет на боксе")
        self.assertTrue(any(row["копий на определение"] > 1 for row in measured))


class TheAdoptionMetric(unittest.TestCase):

    def test_the_baseline_comes_from_the_corpus_not_from_taste(self) -> None:
        for key, (value, why) in C.BASELINE.items():
            self.assertGreater(value, 0, key)
            self.assertGreater(len(why), 20, key)

    def test_the_metric_separates_the_two_forms_of_the_same_result(self) -> None:
        """ГЛАВНОЕ УТВЕРЖДЕНИЕ МЕТРИКИ: она обязана различать формы, которые
        дают ОДИНАКОВЫЙ результат. Если бы не различала, мерить было бы
        нечего."""
        senior = C.measure(_Run.of("санузел").ops)
        junior = C.measure(_Run.of("санузел-джуниор").ops)
        self.assertEqual(senior["элементов объявлено"],
                         junior["элементов объявлено"])
        self.assertEqual(senior["элементов внутри групп, %"], 100.0)
        self.assertEqual(junior["элементов внутри групп, %"], 0.0)
        self.assertGreater(senior["элементов на операцию"],
                           junior["элементов на операцию"])

    def test_derived_elements_are_never_guessed_into_the_count(self) -> None:
        """Витраж объявляет ровно свои опы: сколько импостов родит Revit, из
        программы не видно, и число, поставленное «на глаз», было бы ровно тем
        молчаливым враньём, ради запрета которого построена приёмка."""
        got = C.measure(_Run.of("витраж").ops)
        self.assertEqual(got["элементов объявлено"],
                         got["операций написано"])

    def test_ops_without_elements_are_taken_from_acceptance(self) -> None:
        from kukai.ir.acceptance import _OPS_WITHOUT_ELEMENTS
        for name in _OPS_WITHOUT_ELEMENTS:
            self.assertEqual(C._element_count({"op": name}), 0, name)


if __name__ == "__main__":
    unittest.main()
