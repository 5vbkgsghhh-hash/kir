"""Каждое имя пространства скрипта либо ДОКУМЕНТИРОВАНО, либо тёмное С ПРИЧИНОЙ.

**Дыра, ради которой это написано, не в коде — она между кодом и знанием
модели.** Замер 2026-08-12: пространство скрипта несёт **98 имён** (69 опов из
реестра плюс 29 прочих), и **18 из них не встречались в отрендеренной
документации ни разу**. Среди тёмных были все конструкторы селекторов, а сам
язык при этом принимает форму КОРОЧЕ любой из них — `level="Этаж 1"`, — и её
дока не называла ВООБЩЕ. Модель писала двадцать пять ручных словарей-селекторов
там, где хватало строки.

Слой опов при этом полон ПО ПОСТРОЕНИЮ и отставать не может: `dsl` порождает
функции прямо из `spec.OPS` (`{name: _make_op_fn(ospec) ...}` → `globals()` →
`__all__`), так что 69 = 69 и новый оп появляется сам. **Полнота кода ничего не
обещает про полноту доки** — это разные списки с разными авторитетами, и
второй до сегодня никто не проверял.

Поэтому здесь не «документируйте всё»: часть имён тёмная ПРАВИЛЬНО — типы,
которые скрипт получает, но не строит; жизненный цикл программы, который
песочница ведёт сама. Требование другое и слабее: **темнота обязана быть
РЕШЕНИЕМ с причиной, а не недосмотром.** Новое имя в песочнице краснит тест и
заставляет выбрать — описать модели или объявить тёмным и сказать почему.

Род списка назван прямо, потому что от него зависит смысл отсутствия записи:
:data:`DARK_ON_PURPOSE` — **ЗАКРЫТ, НО НЕ ПОЛОН**. Его состав держится
дисциплиной, а не выводится из авторитета: «этого имени модели знать не надо» —
суждение, и автоматически его не вычислить. Отсутствие имени здесь означает «мы
не решали», а не «имя нужно модели».
"""

import re
import unittest

from kukai.ir import dsl, sandbox, spec
from kukai.ir.course import SANDBOX_NAMES
from kukai.ir.skill import build_skill_text, build_walkthrough_programs_text
from kukai.ir.tool_doc import build_tool_description

#: Имя тёмное НАМЕРЕННО, и рядом причина. Закрытый, но не полный список.
DARK_ON_PURPOSE: dict[str, str] = {
    "Program": "тип программы; скрипт его получает, но никогда не строит",
    "Handle": "тип ручки; возвращается вызовом опа, конструировать нечем",
    "DslRefusal": "исключение языка; ловить его скрипту незачем — отказ уезжает "
                  "в квитанцию сам",
    "build": "песочница забирает программу сама; `build()` — дверь хоста",
    "plan": "планирование ведёт компилятор после песочницы",
    "current": "программа в скрипте ровно одна и подразумевается",
    "reset": "вторая программа за вызов запрещена по построению",
    "OMIT": "часовой «поле не передано»; в питоне это делает само опущение "
            "аргумента",
    "MAX_BULK_OPS": "число уже названо в доке словами («до 300 операций»); "
                    "имя константы модели не нужно",
    "by_name": "вытеснен КОРОТКОЙ формой: `level=\"Этаж 1\"` даёт тот же узел",
    "by_element_id": "вытеснен короткой формой: `level=1100` даёт тот же узел",
    "by_ref": "внутри скрипта ссылка — это РУЧКА, возвращённая вызовом; "
              "писать `by_ref` руками незачем",
}


def _documentation() -> str:
    """То, что модель ПОЛУЧАЕТ, а не исходники, которые это порождают.

    Разница не косметическая: греп по `tool_doc.py`/`skill.py` объявил тёмными
    **31** имя, включая **десять опов** (`create_roof`, `create_duct`,
    `move_elements`…). Ложная тревога целиком: опы попадают в текст ИЗ РЕЕСТРА
    при рендере, литералами в исходнике их нет. Авторитет — отрендеренный
    документ.
    """
    return "\n".join((build_tool_description(),
                      build_skill_text(),
                      build_walkthrough_programs_text()))


class EverySandboxNameIsDocumentedOrDeclaredDark(unittest.TestCase):

    def _names(self) -> set[str]:
        # 🔴 ОБЛАСТЬ СТОРОЖА БЫЛА УЖЕ ЕГО СОБСТВЕННОГО ОБЕЩАНИЯ (правка 15.08).
        # Шапка говорит «каждое имя пространства скрипта», а область была
        # `dsl.__all__ | SANDBOX_NAMES` — то есть без имён, которые песочница
        # кладёт САМА. `model` жил непроверенным с появления каталога. Теперь
        # третье слагаемое берётся у авторитета (`sandbox.HOST_NAMES`), который
        # сверяется с фактическим впрыском и отказывает на расхождении.
        return set(dsl.__all__) | set(SANDBOX_NAMES) | set(sandbox.HOST_NAMES)

    def test_the_op_layer_cannot_fall_behind(self):
        """69 = 69, и это по построению, а не по счастью."""
        ops = set(spec.OPS)
        self.assertEqual(
            ops - set(dsl.__all__), set(),
            "оп реестра не экспортирован песочницей — порождение функций из "
            "`spec.OPS` сломано")

    def test_no_name_is_dark_without_a_reason(self):
        text = _documentation()
        # Контроль-PASS и контроль-FAIL у прибора, а не у подопытного:
        # документированное имя обязано находиться, выдуманное — нет.
        self.assertRegex(text, r"\bcreate_wall\b",
                         "прибор не видит заведомо документированного имени — "
                         "сломан рендер, а не документация")
        self.assertNotRegex(text, r"\b__имени_которого_нет__\b")

        dark = {n for n in self._names()
                if not re.search(rf"\b{re.escape(n)}\b", text)}
        undeclared = sorted(dark - set(DARK_ON_PURPOSE))
        self.assertEqual(
            undeclared, [],
            "имя есть в пространстве скрипта, но модель о нём не знает и "
            "никто не решал, что так и надо:\n  " + "\n  ".join(undeclared)
            + "\nОпиши его в `tool_doc`/`skill` ЛИБО внеси в DARK_ON_PURPOSE "
              "с причиной.")

    def test_the_dark_list_has_not_outlived_its_names(self):
        """Запись про имя, которого больше нет, — ложь, стареющая молча."""
        stale = sorted(set(DARK_ON_PURPOSE) - self._names())
        self.assertEqual(
            stale, [],
            "DARK_ON_PURPOSE называет имена, которых в песочнице нет: "
            f"{stale}")

    def test_every_reason_says_something(self):
        for name, reason in sorted(DARK_ON_PURPOSE.items()):
            with self.subTest(name=name):
                self.assertGreater(
                    len(reason.strip()), 20,
                    f"{name}: причина слишком коротка, чтобы быть решением")

    def test_the_short_selector_form_is_taught(self):
        """Самая короткая форма обязана быть НАЗВАНА, а не подразумеваться.

        Она и была дырой: язык принимал `level="Этаж 1"` с самого начала, а
        дока показывала только словарь.
        """
        text = _documentation()
        self.assertIn(
            'level="Этаж 1"', text,
            "короткая форма селектора не названа модели — она снова будет "
            "писать словарь руками")


class TheHintsHaveOneOwner(unittest.TestCase):
    """Отказ языка и дока модели читают ОДИН словарь, а не две копии."""

    def test_the_doc_is_built_from_the_refusal_hints(self):
        from kukai.ir import tool_doc
        rendered = " ".join(tool_doc._selector_forms_in_python())
        for form in ("name", "element_id", "default", "ref"):
            with self.subTest(form=form):
                self.assertIn(dsl._SELECTOR_HINTS[form], rendered,
                              "дока переписала подсказку своими словами вместо "
                              "того, чтобы взять её у языка")

    def test_a_new_form_would_reach_the_doc_by_itself(self):
        original = dict(dsl._SELECTOR_HINTS)
        dsl._SELECTOR_HINTS["name"] = "ПРОБНАЯ ФОРМА"
        try:
            from kukai.ir import tool_doc
            rendered = " ".join(tool_doc._selector_forms_in_python())
            self.assertIn(
                "ПРОБНАЯ ФОРМА", rendered,
                "правка авторитета не доехала до доки — связь только на вид")
        finally:
            dsl._SELECTOR_HINTS.clear()
            dsl._SELECTOR_HINTS.update(original)


if __name__ == "__main__":
    unittest.main()
