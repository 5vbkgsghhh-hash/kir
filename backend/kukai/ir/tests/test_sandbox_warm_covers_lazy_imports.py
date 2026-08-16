"""ПРОГРЕВ ОБЯЗАН ПОКРЫВАТЬ НАШИ СОБСТВЕННЫЕ ЛЕНИВЫЕ ИМПОРТЫ.

🔴 ЭТОТ РАТЧЕТ ЗАВЕДЁН ПО ЖИВОМУ ОТКАЗУ 15.08, И ЭТО ТРЕТЬЕ ВХОЖДЕНИЕ ОДНОГО
ДЕФЕКТА.

Песочница запрещает импорты вне белого списка (`sandbox.ALLOWED_IMPORTS` —
`math`, `itertools`, `functools`). Запрет действует на ВСЁ, что исполняется в
ребёнке, включая НАШ собственный код: имена языка впрыскиваются функциями, и
ленивый `from kukai.… import …` в теле такой функции ловится тем же хуком, что
и импорт автора. Единственный законный способ — прогреть модуль ДО изоляции
(`course.language.warm_for_source`).

Что случалось трижды:

1. `spec()` тянул `kukai.ir.acceptance` / `kukai.ir.decompile.extract` и
   отказывал `KIR-B004` — исправная справка выглядела виной скрипта модели.
   Закрыто строкой в `_WARM_BY_NAME` (комментарий там же).
2. `design_check()` / `preview()` — та же строка, тот же приём.
3. **`unit(reads_as=…)`** — предикат единицы замысла, добавленный 15.08, тянет
   `kukai.ir.assembly_view` за реестром прочтений. Строку прогрева ему не
   завели, и на ЖИВОМ прогоне он ответил:

       KIR-B004: импорт 'kukai.ir.assembly_view' запрещён
       строка 10: with unit("наружная оболочка дома", reads_as="continuous"):
       blame: author

   То есть флагманская способность дня была недостижима автору вовсе, а отказ
   ОБВИНЯЛ АВТОРА за импорт, которого автор не писал, и советовал несвязанную
   починку («язык уже доступен без импорта»).

Офлайновые тесты волны этого не видели: там песочницы нет, импорт проходит.
Дефект живёт РОВНО на настоящей двери — ровно тот класс, ради которого в этом
дереве требуют строить вход прод-кодом.

ПОЧЕМУ РАТЧЕТ, А НЕ ЕЩЁ ОДНА СТРОКА. Таблица `_WARM_BY_NAME` документирует
случай (1) прямо над собой — и случай (3) всё равно произошёл. Значит проза не
держит, держать обязан прогон.
"""
from __future__ import annotations

import ast
import os
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
COURSE = os.path.join(BACKEND, "kukai", "ir", "course", "__init__.py")


def _lazy_kukai_imports_by_function() -> dict[str, set[str]]:
    """Имя функции верхнего уровня -> модули `kukai.*`, импортируемые В ТЕЛЕ.

    Берётся у ИСХОДНИКА разбором, а не грепом: греп по `from kukai` поймал бы
    и модульные импорты, которые прогрева не требуют вовсе.
    """
    with open(COURSE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        found: set[str] = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("kukai."):
                found.add(inner.module)
            elif isinstance(inner, ast.Import):
                for alias in inner.names:
                    if alias.name.startswith("kukai."):
                        found.add(alias.name)
        if found:
            out[node.name] = found
    return out


class ПрогревПокрываетНашиЛенивыеИмпорты(unittest.TestCase):

    def test_every_injected_name_has_its_modules_warmed(self):
        """Модуль, который тянет ВПРЫСНУТАЯ функция, обязан быть в прогреве.

        Иначе способность недостижима автору, а отказ обвиняет автора.
        """
        from kukai.ir.course import SANDBOX_NAMES
        from kukai.ir.course.language import _WARM_BY_NAME

        # РОДИТЕЛЬСКИЙ ПАКЕТ ПРОГРЕВАЕТСЯ САМ, и это не поблажка: импорт
        # `kukai.ir.design_check` кладёт `kukai.ir` в `sys.modules`, а хук
        # песочницы зовётся ТОЛЬКО для того, чего там ещё нет. Без этой строки
        # сторож краснел на `design_check() тянет kukai.ir` — ложная тревога,
        # пойманная им же в первый прогон.
        warmed: set[str] = set()
        for modules in _WARM_BY_NAME.values():
            for module in modules:
                parts = module.split(".")
                for i in range(1, len(parts) + 1):
                    warmed.add(".".join(parts[:i]))

        lazy = _lazy_kukai_imports_by_function()
        missing: list[str] = []
        for name in sorted(SANDBOX_NAMES):
            for module in sorted(lazy.get(name, ())):
                # `kukai.ir.dsl` живёт в ребёнке по построению: он И ЕСТЬ язык,
                # песочница грузит его как `dsl_module` до изоляции.
                if module == "kukai.ir.dsl":
                    continue
                if module not in warmed:
                    missing.append("%s() тянет %s" % (name, module))
        assert not missing, (
            "впрыснутая в песочницу функция лениво импортирует модуль, "
            "которого нет в прогреве — на живом прогоне он отдаст KIR-B004 и "
            "ОБВИНИТ АВТОРА за наш импорт:\n  " + "\n  ".join(missing) +
            "\nдобавь строку в `course.language._WARM_BY_NAME`")

    def test_a_realistic_unit_call_actually_warms_the_predicate(self):
        """Покрытия мало: ключ таблицы обязан СОВПАСТЬ с настоящим вызовом.

        Таблица ищет ключ ПОДСТРОКОЙ в исходнике (форма 7 — соглашение вместо
        авторитета), поэтому покрытие проверяется поведением на том тексте,
        который автор действительно пишет.
        """
        from kukai.ir.course.language import warm_for_source

        source = ('with unit("фасадная лента", reads_as="continuous"):\n'
                  '    create_wall(p0_mm=[0, 0], p1_mm=[1000, 0])\n')
        assert "kukai.ir.assembly_view" in warm_for_source(source), (
            "настоящий вызов `unit(reads_as=…)` не прогревает реестр "
            "прочтений — предикат откажет KIR-B004 на живом ходу")

    def test_the_ratchet_can_actually_fail(self):
        """КОНТРОЛЬ-FAIL. Сторож, не умеющий покраснеть, хуже отсутствующего:
        он создаёт уверенность и не даёт защиты."""
        from kukai.ir.course import language

        original = dict(language._WARM_BY_NAME)
        try:
            language._WARM_BY_NAME.pop("reads_as", None)
            source = 'with unit("x", reads_as="continuous"):\n    pass\n'
            assert "kukai.ir.assembly_view" not in language.warm_for_source(
                source), "нечего было ломать — строка прогрева не решала"
        finally:
            language._WARM_BY_NAME.clear()
            language._WARM_BY_NAME.update(original)

    def test_the_scan_sees_something_at_all(self):
        """КОНТРОЛЬ ЗНАМЕНАТЕЛЯ. Ноль ленивых импортов означал бы, что разбор
        промахнулся мимо файла, и первый тест был бы зелен по построению."""
        lazy = _lazy_kukai_imports_by_function()
        assert len(lazy) >= 3, (
            "разбор нашёл меньше трёх функций с ленивыми импортами — "
            "почти наверняка промах по файлу, а не чистый курс")


if __name__ == "__main__":
    unittest.main()
