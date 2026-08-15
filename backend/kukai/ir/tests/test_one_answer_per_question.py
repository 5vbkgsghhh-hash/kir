"""ОДИН ВОПРОС — ОДИН ОТВЕТ. Два словаря и один провод, 10.08.2026.

Оба дефекта ниже — одна и та же беда, названная операторе в начале сессии:
работа делалась дважды, потому что компилятор целиком никто в голове не
держал. Здесь она измерена и закрыта тестом.

  1. «В какую категорию Revit попадёт результат этого опа» знали ДВА словаря:
     `acceptance._OP_CATEGORIES` (43 опа, кортежи) и `clash_bundle.OP_CATEGORY`
     (29 опов, строки). Хуже: `spec.op_census_categories` спрашивал ответ У
     СУДЬИ ПРИЁМКИ — реестр зависел от своего потребителя. Таблица переехала в
     реестр; второй словарь назван долгом и держится тестом ниже.

  2. Код отказа на проводе обещает потребителю ОДИН ремонт. Шесть кодов несли
     по нескольку разных имён; худший — `KIR-T003`, бывший одновременно
     `TYPE_BAD_ENUM` и `TYPE_GEOM_RELATION` в ОДНОМ файле в двенадцати
     строках друг от друга.
"""
from __future__ import annotations

import inspect
import io
import os
import re
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_one_answer_queue.jsonl"))

from kukai.ir import acceptance as A  # noqa: E402
from kukai.ir import diag  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.analysis_emit import ANALYSIS_ZERO_LOAD  # noqa: E402
from kukai.ir.macros import MACRO_ERROR  # noqa: E402
from kukai.ir.mesh import MESH_DISCONNECTED  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# 1. ОДНА ТАБЛИЦА КАТЕГОРИЙ, И ВЛАДЕЕТ ЕЙ РЕЕСТР
# ═════════════════════════════════════════════════════════════════════════

class OneCategoryTableOwnedByTheRegistry(unittest.TestCase):

    def test_the_judge_reads_the_registry_rather_than_holding_a_copy(self):
        """РЕФУТАЦИЯ. До правки таблица жила в `acceptance`, а `spec` брал
        ответ ОТТУДА. Теперь ровно один объект, и приёмка на него смотрит."""
        self.assertIs(A._OP_CATEGORIES, spec.OP_RESULT_CATEGORIES)
        self.assertEqual(A._category_of_op({"op": "create_wall"}),
                         ("OST_Walls",))

    def test_the_registry_no_longer_imports_its_own_consumer(self):
        """АРХИТЕКТУРНЫЙ ЗАМОК. `spec.op_census_categories` импортировал
        `acceptance._category_of_op` — реестр спрашивал категорию у судьи
        приёмки. Направление зависимости обязано быть обратным."""
        src = inspect.getsource(spec.op_census_categories)
        self.assertNotIn("from kukai.ir.acceptance", src)
        self.assertIn("op_result_categories", src)
        self.assertNotIn("acceptance", inspect.getsource(spec.op_disciplines))

    def test_the_resolver_still_answers_every_enum_branch(self):
        """Пять опов решают категорию СВОИМ закрытым перечислением. Переезд
        обязан был увезти и разрешатель, иначе таблица отвечала бы неполно."""
        cases = {
            ("create_column", None): ("OST_StructuralColumns",),
            ("create_column", "architectural"): ("OST_Columns",),
            ("create_opening", "wall_rect"): ("OST_SWallRectOpening",),
            ("create_topography", "toposolid"): ("OST_Toposolid",),
            ("create_foundation", "isolated"): ("OST_StructuralFoundation",),
        }
        for (op_name, choice), expected in cases.items():
            with self.subTest(op=op_name, choice=choice):
                probe = {"op": op_name}
                if choice is not None:
                    key = ("category" if op_name == "create_column"
                           else "variety")
                    probe[key] = choice
                self.assertEqual(spec.op_result_categories(probe), expected)

    def test_no_writing_op_falls_into_silence(self):
        """ПРОБЕЛА НЕТ — ЕСТЬ ИМЕНОВАННОЕ ОТСУТСТВИЕ, и это разные вещи.

        Замер «15 пишущих опов нет НИ В ОДНОЙ из двух таблиц категорий» верен
        и обманчив: он сравнивает два регистра из четырёх. Оп без строки
        категории назван либо слепым для переписи (`_OPS_BLIND`), либо не
        создающим элемента вовсе (`_OPS_WITHOUT_ELEMENTS`), либо разбирается
        веткой разрешателя. Дописать такому опу категорию значило бы заставить
        приёмку ЖДАТЬ прибавки в категории, которой она не наблюдает, то есть
        валить честную постройку."""
        writing = {name for name, op in spec.OPS.items() if op.writes_model}
        branch_resolved = {
            "create_column", "create_directshape", "create_foundation",
            "create_group", "create_opening", "create_topography",
            "create_solid_extrusion", "create_solid_revolve",
        }
        named = (set(spec.OP_RESULT_CATEGORIES) | set(A._OPS_BLIND)
                 | set(A._OPS_WITHOUT_ELEMENTS) | branch_resolved)
        self.assertEqual(writing - named, set(),
                         "пишущий оп не назван ни одним регистром")
        self.assertEqual(named - writing, set(),
                         "регистр называет несуществующий оп")

    def test_no_second_stored_answer_to_the_category_question_exists(self):
        """ДОЛГ ЗАКРЫТ, И РАТЧЕТ ТЕПЕРЬ СТЕРЕЖЁТ ФОРМУ, А НЕ ИМЯ (11.08.2026).

        Здесь стоял ратчет на `clash_bundle.OP_CATEGORY`: пока дубликат жив,
        расхождение обязано быть ровно одно (`create_railing`). Дубликат
        мигрировали, ратчет упал на `ImportError` — и вместе с ним замолчали
        ещё три сторожа полноты, читавшие ту же таблицу.

        ПОЧЕМУ НЕ `hasattr(CB, "OP_CATEGORY")`, КАК У СОСЕДА. Запрет по ИМЕНИ
        не может назвать следующий ход и ловит ровно одно написание: вторая
        таблица, названная `OP_CATS` или `_CATEGORY_BY_OP`, прошла бы мимо
        него молча — то есть прибор покрывал бы часть своего диапазона.
        Запрещается ФОРМА: любое модульное отображение «имя опа -> категория
        Revit», кроме названных исключений. Исключение — тоже решение: чтобы
        добавить строку, надо вписать её сюда и объяснить.
        """
        from kukai.ir import clash_bundle as CB

        #: Единственное разрешённое отображение оп -> категория, и оно НЕ
        #: второй ответ: реестр на эти опы молчит либо отвечает несколькими,
        #: и строка называет выбор вслух (см. шапку `REGISTRY_GAPS`).
        allowed = {"REGISTRY_GAPS"}
        ops = set(spec.OPS)
        stored: set[str] = set()
        for attr, value in vars(CB).items():
            if not isinstance(value, dict) or not value:
                continue
            if not all(isinstance(k, str) and k in ops for k in value):
                continue
            flat = [v for value_ in value.values()
                    for v in (value_ if isinstance(value_, tuple) else (value_,))]
            if flat and all(isinstance(v, str) and v.startswith("OST_")
                            for v in flat):
                stored.add(attr)
        self.assertEqual(
            stored, allowed,
            "в clash_bundle появилось ХРАНИМОЕ отображение оп -> категория "
            f"({sorted(stored - allowed)}). Ответ на этот вопрос один и живёт "
            "в реестре: спрашивайте `spec.op_result_categories` через "
            "`clash_bundle.category_of`/`op_categories`. Если строка нужна "
            "как названное исключение — впишите её имя в `allowed` здесь и "
            "объясните, чего реестр не отвечает")
        self.assertIs(CB._REGISTRY_CATEGORIES, spec.op_result_categories)
        # Расхождение, ради которого стоял прежний ратчет, теперь не может
        # существовать: у ограждения ответ ОДИН и он реестровый.
        self.assertEqual(spec.OP_RESULT_CATEGORIES["create_railing"],
                         ("OST_Railings", "OST_StairsRailing"))
        self.assertEqual(CB.op_categories("create_railing"),
                         ("OST_StairsRailing",))


# ═════════════════════════════════════════════════════════════════════════
# 2. ОДИН КОД — ОДИН РЕМОНТ
# ═════════════════════════════════════════════════════════════════════════

class OneWireCodeOneRepair(unittest.TestCase):

    def test_the_typecheck_series_no_longer_shares_a_code_with_geometry(self):
        """РЕФУТАЦИЯ ХУДШЕГО СЛУЧАЯ. `KIR-T003` значил одновременно «значение
        вне закрытого перечня» и «отверстие пересекает контур» — два ремонта,
        один провод, оба объявлены в `diag.py` в двенадцати строках друг от
        друга. Потребитель, ветвящийся по коду, различить их не мог."""
        self.assertNotEqual(diag.TYPE_BAD_ENUM, diag.TYPE_GEOM_RELATION)
        self.assertEqual(diag.TYPE_BAD_ENUM, "KIR-T003")
        self.assertEqual(diag.TYPE_GEOM_RELATION, "KIR-T004")

    def test_the_macro_and_mesh_subsystems_no_longer_share_a_code(self):
        self.assertNotEqual(MACRO_ERROR, MESH_DISCONNECTED)
        self.assertEqual(MACRO_ERROR, "KIR-M001")
        self.assertEqual(MESH_DISCONNECTED, "KIR-M006")

    def test_a_zero_load_is_not_an_unsupported_enum(self):
        """Нулевая нагрузка — бессмысленное ЧИСЛО, а не невыбранный вариант;
        ремонт у неё другой, значит и код другой."""
        self.assertEqual(ANALYSIS_ZERO_LOAD, "KIR-E012")
        self.assertNotEqual(ANALYSIS_ZERO_LOAD, "KIR-E007")

    def test_the_never_raised_code_is_gone(self):
        """`KIR-C001` (`COMPILE_FAIL`) был объявлен, задокументирован и НИ
        РАЗУ не выдан. Объявленный, но не выдаваемый код — обещание, которого
        никто не держит, и он занимал целую букву.

        ЗДЕСЬ СТОЯЛО ЧТЕНИЕ ПРОЗЫ, И ОНО СЛОМАЛОСЬ ОТ СОБСТВЕННОЙ ПРАВОТЫ
        (11.08.2026). Проверка была `assertNotIn("KIR-C001",
        inspect.getsource(diag))` — то есть искала СТРОКУ в исходнике целиком,
        вместе с комментариями. Стоило объяснить в комментарии, что буква C
        освободилась и почему, как тест нашёл названный им же код и покраснел.
        Он запрещал не объявление кода, а УПОМИНАНИЕ о нём, и тем самым
        запрещал документировать собственное решение.

        Свойство, которое действительно нужно: код НЕ ОБЪЯВЛЕН — ни здесь, ни
        в другом модуле пакета. Оно проверяется по объявлениям, а не по
        тексту, поэтому комментарий, история и этот докстринг могут называть
        `KIR-C001` сколько угодно раз.
        """
        self.assertFalse(hasattr(diag, "COMPILE_FAIL"))

        # 1. Ни одна константа самого `diag` его не несёт.
        in_diag = {name for name, value in vars(diag).items()
                   if name.isupper() and isinstance(value, str)
                   and value == "KIR-C001"}
        self.assertEqual(in_diag, set(),
                         "код снова объявлен константой в diag")

        # 2. И ни один не-тестовый модуль пакета — читаем ОБЪЯВЛЕНИЯ тем же
        #    разбором, которым `code_collisions` ищет столкновения имён, а не
        #    сырой текст.
        declarations = re.compile(
            r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*[\"'](KIR-C001)[\"']", re.M)
        package = os.path.dirname(os.path.abspath(diag.__file__))
        offenders: list[str] = []
        for folder, _dirs, files in os.walk(package):
            if os.path.sep + "tests" in folder or "__pycache__" in folder:
                continue
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(folder, fname)
                with io.open(path, encoding="utf-8") as fh:
                    for name, _code in declarations.findall(fh.read()):
                        offenders.append(f"{os.path.relpath(path, package)}:{name}")
        self.assertEqual(offenders, [],
                         "мёртвый код KIR-C001 снова объявлен в пакете")

    def test_no_code_inside_diag_carries_two_names(self):
        """Замок на импорте: он и есть то, чего не было, когда T003 разошёлся."""
        diag._lint_diag_codes()
        globals_ = vars(diag)
        by_code: dict[str, set[str]] = {}
        for name, value in globals_.items():
            if (name.isupper() and isinstance(value, str)
                    and value.startswith("KIR-")):
                by_code.setdefault(value, set()).add(name)
        doubled = {c: sorted(n) for c, n in by_code.items() if len(n) > 1}
        self.assertEqual(doubled, {})

    def test_the_lint_actually_bites(self):
        """Замок, который не может сработать, — не замок. Тот же закон, что
        держит остальные ратчеты этого дерева."""
        scope = diag._lint_diag_codes.__globals__
        scope["DUPLICATE_PROBE"] = diag.TYPE_BAD_ENUM
        try:
            with self.assertRaises(AssertionError) as caught:
                diag._lint_diag_codes()
            self.assertIn("DUPLICATE_PROBE", str(caught.exception))
        finally:
            scope.pop("DUPLICATE_PROBE", None)
        diag._lint_diag_codes()          # дерево обязано остаться чистым

    def test_no_code_carries_two_names_across_the_package(self):
        """Межмодульная половина. Импортом её не закрыть — модуля, который
        тянет все эмиттеры, нет, — поэтому она читается по исходникам."""
        self.assertEqual(diag.code_collisions(), {})

    def test_every_named_debt_is_still_a_real_collision(self):
        """Список исключений — ДОЛГ, а не свалка.

        ТЕСТ ПЕРЕПИСАН 10.08 вместе с закрытием долгов. В прежнем виде он
        перебирал словарь и на ПУСТОМ проходил не проверив ничего — та самая
        вакуумная зелень, против которой заведён весь этот файл. Теперь пустой
        словарь обязан ЗНАЧИТЬ пустоту столкновений, а не отсутствие проверки.
        """
        debts = diag.CODES_WITH_KNOWN_ALIASES
        if not debts:
            self.assertEqual(
                diag.code_collisions(), {},
                "долгов не объявлено, а столкновения есть — список молчит")
            return
        for code, why in debts.items():
            with self.subTest(code=code):
                self.assertTrue(why.strip(), "долг без причины")
                self.assertRegex(code, r"^KIR-[A-Z]\d+$")

    def test_the_two_collapsed_ideas_have_exactly_one_constant_each(self):
        """РЕФУТАЦИЯ. `KIR-E007` объявляли ЧЕТЫРЕ модуля, `KIR-E008` — ТРИ,
        каждый своим именем и своим литералом на одну и ту же мысль. Общим
        стал КОД, а не текст: `message_ru` у каждого места осталось своим,
        потому что столкновение было на проводе, а не в прозе."""
        import os
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(diag.__file__)))
        pattern = re.compile(
            r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*[\"'](KIR-E00[78])[\"']",
            re.M)
        found: dict[str, set[str]] = {}
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for fname in files:
                if fname.endswith(".py"):
                    path = os.path.join(folder, fname)
                    with open(path, encoding="utf-8") as fh:
                        for name, code in pattern.findall(fh.read()):
                            found.setdefault(code, set()).add(name)
        self.assertEqual(found.get("KIR-E007"), {"EMIT_UNSUPPORTED_ENUM"})
        self.assertEqual(found.get("KIR-E008"), {"EMIT_CONTOUR_HOLES"})

    def test_the_two_shared_codes_still_mean_different_repairs(self):
        """Схлопывание не имело права слить сами мысли: «перечень не
        поддержан» и «в контуре отверстия» — разные ремонты."""
        self.assertNotEqual(diag.EMIT_UNSUPPORTED_ENUM,
                            diag.EMIT_CONTOUR_HOLES)


# ═════════════════════════════════════════════════════════════════════════
# 3. ТЁМНЫЕ МОДУЛИ: СНЯТО С ПРИЧИНОЙ, А НЕ ЗАБЫТО
# ═════════════════════════════════════════════════════════════════════════

class ADarkModuleLeavesWithAReason(unittest.TestCase):

    def test_the_annotation_seed_is_gone_and_its_family_lives_on(self):
        """`ops_doc` был СЕМЕНЕМ семьи аннотаций и родил её: tag/dimension/
        text уехали в `ops_annotation`, а `ops_doc.OPS` остался пустым списком
        с 17.07, пока соседи двигались весь август. Пустой модуль в списке
        импорта реестра неотличим от сломанного."""
        with self.assertRaises(ImportError):
            __import__("kukai.ir.ops_doc")
        family = {"create_tag", "create_dimension", "create_text"}
        self.assertLessEqual(family, set(spec.OPS),
                             "семья аннотаций пропала вместе с семенем")

    def test_removing_it_changed_no_op_count(self):
        """Доказательство, что семя было ПУСТЫМ, а не носителем опов: реестр
        по-прежнему полон, и ни один оп не потерялся вместе с модулем."""
        self.assertGreaterEqual(len(spec.OPS), 68)
        # ПРОВЕРЯЕТСЯ ИМПОРТ, А НЕ ПРОЗА. Прежняя версия искала строку
        # "ops_doc" в первых 4000 символах исходника — и падала бы на
        # СОБСТВЕННОМ комментарии-надгробии, который снятый модуль называет.
        # Тест обязан смотреть на то, что модуль ДЕЛАЕТ.
        self.assertFalse(hasattr(spec, "ops_doc"),
                         "реестр всё ещё импортирует снятый модуль")


# ═════════════════════════════════════════════════════════════════════════
# 4. ФАЙЛ, КОТОРЫЙ СУДИТ ДРЕЙФ, НЕ ИМЕЕТ ПРАВА ДРЕЙФОВАТЬ САМ
# ═════════════════════════════════════════════════════════════════════════

class ToolDocCountsItsOwnRules(unittest.TestCase):

    def test_the_declared_rule_count_matches_the_numbered_list(self):
        """Шапка обещала ДВА правила, а текст ниже ссылался на третье. Этот
        файл наказывает ровно такой дрейф у других (`create_dimension`,
        `UNPROVEN_GAP`) и не имеет права носить его сам."""
        import re

        from kukai.ir import tool_doc

        doc = tool_doc.__doc__ or ""
        words = {"One": 1, "Two": 2, "Three": 3, "Four": 4}
        declared = re.search(r"(\w+) rules govern this module", doc)
        self.assertIsNotNone(declared, "шапка не называет числа правил")
        numbered = re.findall(r"^(\d+)\. \*\*", doc, re.M)
        self.assertEqual(words[declared.group(1)], len(numbered),
                         f"шапка обещает {declared.group(1)!r}, а пунктов "
                         f"{len(numbered)}")
        self.assertEqual(numbered, [str(i + 1) for i in range(len(numbered))],
                         "нумерация правил не сплошная")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
