"""ХРУПКОСТЬ ПО ВЕРСИИ СПРАШИВАЕТСЯ У ЭМИТТЕРА, А НЕ У ОДНОГО ПРОГОНА.

ЧТО СЛУЧИЛОСЬ (13.08.2026). ``VERSION_FRAGILE`` и кэш ответа ворот
(`version_fragile_gate_answer.json`) собраны из ОДНОГО прогона — `k2_ar_rd_v7`.
Прогон честный, инструмент исправен, ответ верен. И всё же список неполон:
в нём нет пары ``("create_tag", "tag_type")``, хотя эмиттер отказывает по ней
явно и безусловно.

    authoring.py:4620   if g_tagtype is not None:
                            if ver <= "2021": raise KirRefusal([Diagnostic(
                                code=EMIT_UNSUPPORTED, field_name="tag_type", …

Почему её не было видно — замерено, а не предположено:

    деревьев в корпусе                                 52
    из них несут `create_tag`                           1   (`k2_ar_rd_v8`)
    `create_tag` в нём                                851
    из них с `tag_type`                               851   (лифт пишет его ВСЕГДА,
                                                             lift.py:2612)
    `create_tag` в `k2_ar_rd_v7` — на котором взят кэш   0

**Ноль в выборке против безусловной ветки в определении.** Это ровно «прибор
на часть диапазона»: диапазон выбрал не автор списка, а то, какое здание
попало под руку. Лекарство канона первое — СПРОСИТЬ АВТОРИТЕТ: у отказа по
версии есть место определения, и оно перечислимо.

ЧТО ЭТОТ ФАЙЛ ДЕЛАЕТ. Обходит `authoring.py` по СИНТАКСИЧЕСКОМУ ДЕРЕВУ (не
регуляркой: канон прямо называет угадывание синтаксиса Python регулярками
источником четырёх ложных вердиктов), собирает каждое место, где отказ зависит
от версии, и требует, чтобы КАЖДОЕ было названным решением — либо в
``VERSION_FRAGILE``, либо в регистре осознанных исключений ниже.

СТОРОНА У РАТЧЕТА ОДНА, И ЭТО НАМЕРЕННО. ``VERSION_FRAGILE`` имеет право быть
ШИРЕ найденного: ``("create_ceiling", None)`` хрупок целиком и не имеет места
отказа в эмиттере вовсе (`Ceiling.Create` появился в 2022, обходного пути нет
ни на одной из шести). Он не имеет права быть УЖЕ: каждое место отказа обязано
быть решено вслух.
"""

from __future__ import annotations

import ast
import inspect
import unittest

from kukai.ir import authoring, spec

#: (оп, поле) -> почему пара НЕ в ``VERSION_FRAGILE``, хотя эмиттер по ней
#: отказывает. Список ЗАКРЫТ, НО НЕ ПОЛОН в терминах канона: сюда попадает
#: только то, что уже нашёл обход ниже, и отсутствие записи означает «мы не
#: знаем», а не «такого нет». Каждая строка обязана нести ЧИСЛО или прямо
#: сказать, что числа нет.
DELIBERATELY_OUTSIDE: dict[tuple[str, str | None], str] = {
    ("create_tag", "tag_type"): (
        "ОТКРЫТОЕ РЕШЕНИЕ, 13.08.2026, не пропуск. Предикат соло-нарезки "
        "ВЕРСИЙ НЕ ЗНАЕТ (`materialize` вызывает `is_version_fragile` без "
        "версии), а хрупкость здесь ровно одной версии — 2021. Включение "
        "пары нарежет соло 851 марку `k2_ar_rd_v8` на ВСЕХ ШЕСТИ версиях "
        "ради защиты одной, и на 2021 они всё равно не соберутся — тот же "
        "случай, что 81 потолок в оговорке над `VERSION_FRAGILE`. "
        "ЧЕМ ЗАКРЫВАЕТСЯ: прогоном `tools/compile_gate_offline.py` по "
        "`k2_ar_rd_v8` с парой и без неё — числа программ и потерянных опов, "
        "как для трёх прежних пар (2 745 -> 125 потеряно, 2 620 возвращено). "
        "Пока числа нет, молчаливое включение было бы догадкой о стоимости."),
}


def _refusal_sites_in_tree(tree: ast.AST) -> dict[str, list[tuple[str | None, int]]]:
    """Обход одного синтаксического дерева: функция -> места отказа по версии.

    Вынесен из ``version_dependent_refusal_sites`` без изменения поведения,
    чтобы ТОТ ЖЕ обход применялся и к ``authoring``, и к спутникам. Второй
    экземпляр обхода был бы ровно тем дефектом, который этот файл сторожит.
    """
    by_function: dict[str, list[tuple[str | None, int]]] = {}

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Diagnostic":
                keywords = {k.arg: k.value for k in node.keywords}
                code = keywords.get("code")
                if isinstance(code, ast.Name) and code.id == "EMIT_UNSUPPORTED":
                    raw = keywords.get("field_name")
                    if raw is None:
                        field: str | None = None
                    elif isinstance(raw, ast.Constant):
                        field = raw.value
                    else:
                        raise AssertionError(
                            "field_name не литерал в месте отказа по версии, "
                            f"строка {node.lineno}: обход не может назвать поле")
                    enclosing = self.stack[-1] if self.stack else "<модуль>"
                    by_function.setdefault(enclosing, []).append(
                        (field, node.lineno))
            self.generic_visit(node)

    Walk().visit(tree)
    return by_function


def emitter_delegations() -> dict[str, tuple[str, str]]:
    """оп -> (модуль-спутник, функция-вход), спрошено у САМОЙ ОБЁРТКИ.

    32 эмиттера из 63 — четырёхстрочные обёртки вида
    ``return struct_emit.emit_foundation(op, ver, stamp, isolation)``. Имя
    спутника берётся из тела обёртки, а не из суффикса имени функции:
    ``_emit_foundation_struct`` выглядит как соглашение, а соглашение не
    авторитет (форма 7).
    """
    import inspect
    import textwrap

    out: dict[str, tuple[str, str]] = {}
    for op_name, function in authoring._EMITTERS.items():
        try:
            source = textwrap.dedent(inspect.getsource(function))
        except (OSError, TypeError):
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Return):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id.endswith("_emit")):
                out[op_name] = (target.value.id, target.attr)
    return out


def _calls_within(tree: ast.AST) -> dict[str, set[str]]:
    """функция -> имена функций ЭТОГО ЖЕ модуля, которые она зовёт."""
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    graph: dict[str, set[str]] = {}

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            graph.setdefault(node.name, set())
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            if self.stack and isinstance(node.func, ast.Name) \
                    and node.func.id in defined:
                graph[self.stack[-1]].add(node.func.id)
            self.generic_visit(node)

    Walk().visit(tree)
    return graph


def _reachable_from(graph: dict[str, set[str]], start: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        for nxt in graph.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def satellite_refusal_sites() -> set[tuple[str, str | None, str]]:
    """Места отказа по версии в СПУТНИКАХ ``*_emit.py``, привязанные к опу.

    🔴 ЗАЧЕМ ЭТО ЕСТЬ (замер 15.08.2026). Ратчет выше обходил РОВНО
    ``authoring.py``, а тела 32 эмиттеров из 63 уехали в двенадцать спутников
    и оставили в ``authoring`` четырёхстрочные обёртки. Метод был верен —
    спросить авторитет, — а охват стал 6 % нового кода: **четыре места отказа
    по версии оказались невидимы, три из них не названы нигде**:

        struct_emit.py:227    _emit_foundation_slab   поле=holes    НЕ НАЗВАН
        datum_emit.py:511     emit_multistory_stairs  поле=levels   НЕ НАЗВАН
        analysis_emit.py:126  _version_guard          поле=None     НЕ НАЗВАН
        arch_emit.py:115      emit_ceiling            поле=None     покрыт
                                                      (create_ceiling, None)

    Цена не теоретическая: отказ эмиссии роняет ПРОГРАММУ целиком, а кусок
    материализатора — 250 опов. Один фундамент с проёмом на Revit 2021 уносит
    с собой до 249 совместимых соседей.

    ПРИВЯЗКА К ОПУ — ПО ЦЕПОЧКЕ ВЫЗОВОВ, А НЕ ПО МОДУЛЮ. Два места из четырёх
    лежат в ЧАСТНЫХ помощниках (`_emit_foundation_slab`, `_version_guard`), а
    не во входной функции, и модуль обслуживает несколько опов сразу
    (`struct_emit` — шесть). Приписать место всему модулю значило бы объявить
    хрупкими пять опов, которые ни при чём. Поэтому: вход берётся у обёртки,
    внутри спутника строится граф вызовов, и место принадлежит опу тогда и
    только тогда, когда его функция ДОСТИЖИМА от входа этого опа.

    Третий элемент кортежа — адрес `файл:строка`, а не голая строка: сообщение
    ратчета обязано вести к месту, иначе им нельзя воспользоваться.
    """
    import importlib
    import pathlib

    delegations = emitter_delegations()
    cache: dict[str, tuple[ast.AST, dict[str, set[str]],
                           dict[str, list[tuple[str | None, int]]]]] = {}
    sites: set[tuple[str, str | None, str]] = set()

    for op_name, (module_name, entry) in sorted(delegations.items()):
        if module_name not in cache:
            module = importlib.import_module("kukai.ir.%s" % module_name)
            source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            tree = ast.parse(source)
            cache[module_name] = (tree, _calls_within(tree),
                                  _refusal_sites_in_tree(tree))
        _tree, graph, by_function = cache[module_name]
        if not by_function:
            continue
        reachable = _reachable_from(graph, entry)
        for function_name, entries in by_function.items():
            if function_name not in reachable:
                continue
            for field, line in entries:
                sites.add((op_name, field, "%s.py:%d" % (module_name, line)))
    return sites


def version_dependent_refusal_sites() -> set[tuple[str, str | None, int]]:
    """Каждое место в эмиттере, где отказ зависит от версии Revit.

    Авторитет — МЕСТО ОПРЕДЕЛЕНИЯ: узел ``Diagnostic(code=EMIT_UNSUPPORTED,
    …)``. Имя опа берётся не из имени функции (соглашение — не авторитет,
    форма 7), а из таблицы диспетчеризации ``authoring._EMITTERS``.

    Отвечает только за ``authoring.py``. Спутники — у
    ``satellite_refusal_sites``; объединяет их ратчет ниже.
    """

    tree = ast.parse(inspect.getsource(authoring))
    by_function = _refusal_sites_in_tree(tree)

    ops_by_emitter: dict[str, list[str]] = {}
    for op_name, function in authoring._EMITTERS.items():
        ops_by_emitter.setdefault(getattr(function, "__name__", ""), []) \
            .append(op_name)

    sites: set[tuple[str, str | None, int]] = set()
    for function_name, entries in by_function.items():
        op_names = ops_by_emitter.get(function_name)
        if not op_names:
            # Молча выбросить нельзя: место отказа без опа — это либо новая
            # форма диспетчеризации, либо наша слепота, и обе требуют глаз.
            raise AssertionError(
                f"место отказа по версии в {function_name}, которого нет в "
                "authoring._EMITTERS — сопоставление оп<-функция сломалось")
        for field, line in entries:
            for op_name in op_names:
                sites.add((op_name, field, line))
    return sites


class EveryVersionRefusalIsANamedDecision(unittest.TestCase):
    """Ратчет: место отказа обязано быть решено — включением или отказом."""

    def setUp(self) -> None:
        # ОБА ОБХОДА, И ЭТО СУТЬ ПРАВКИ 15.08.2026: `authoring.py` плюс
        # двенадцать спутников `*_emit.py`, куда уехали тела 32 эмиттеров.
        self.sites = {(op, field, "authoring.py:%d" % line)
                      for op, field, line in version_dependent_refusal_sites()}
        self.satellite_sites = satellite_refusal_sites()
        self.sites |= self.satellite_sites
        # ЗНАМЕНАТЕЛЬ ПЕРВЫМ. Пустой обход прошёл бы каждую проверку ниже
        # вакуумно, и «0 непокрытых из 0» читается как «всё покрыто».
        self.assertGreaterEqual(
            len(self.sites), 3,
            "обход нашёл меньше трёх мест отказа по версии — это заявление "
            "о ХОДОКЕ, а не о реестре (три известны поимённо: holes, "
            "contour.holes, tag_type)")
        # ВТОРОЙ ЗНАМЕНАТЕЛЬ — ОТДЕЛЬНО, потому что первый его не сторожит:
        # обход спутников мог бы вернуть пусто (обёртки перестали
        # распознаваться, спутник переименован), и объединение осталось бы
        # выше трёх за счёт `authoring`. Тогда пять пар ниже читались бы как
        # «шире найденного», то есть законно, — и слепота вернулась бы молча.
        self.assertGreaterEqual(
            len(self.satellite_sites), 6,
            "обход спутников нашёл меньше шести мест — замер 15.08 дал ровно "
            "шесть (foundation.holes, multistory_stairs.levels, три нагрузки "
            "и ceiling). Меньше — сломан обход, а не починены спутники")

    def test_every_site_is_covered_or_deliberately_outside(self) -> None:
        undecided = [
            (op, field, where) for op, field, where in sorted(self.sites)
            if (op, field) not in spec.VERSION_FRAGILE
            and (op, field) not in DELIBERATELY_OUTSIDE
        ]
        self.assertEqual(
            undecided, [],
            "эмиттер отказывает по версии, а нарезка об этом не знает и "
            "решения не записано: " + ", ".join(
                f"{op}.{field} ({where})" for op, field, where in undecided))

    def test_the_register_of_exemptions_holds_no_ghosts(self) -> None:
        # Исключение, которого эмиттер больше не порождает, — мёртвая строка,
        # и она делает регистр менее правдивым с каждым днём.
        live = {(op, field) for op, field, _ in self.sites}
        ghosts = sorted(set(DELIBERATELY_OUTSIDE) - live)
        self.assertEqual(
            ghosts, [],
            f"регистр исключений называет пары, которых в эмиттере нет: {ghosts}")

    def test_no_pair_is_both_covered_and_exempted(self) -> None:
        both = sorted(set(DELIBERATELY_OUTSIDE) & set(spec.VERSION_FRAGILE))
        self.assertEqual(both, [], f"пара и включена, и исключена: {both}")

    def test_every_exemption_states_a_number_or_says_it_has_none(self) -> None:
        for pair, reason in DELIBERATELY_OUTSIDE.items():
            with self.subTest(pair=pair):
                self.assertIn(
                    "ЧЕМ ЗАКРЫВАЕТСЯ", reason,
                    "исключение без условия закрытия превращается в архив")
                self.assertTrue(
                    any(ch.isdigit() for ch in reason),
                    "исключение без единого числа — мнение, а не решение")


class TheWalkCanActuallyFindAndActuallyMiss(unittest.TestCase):
    """КОНТРОЛЬ на сам обход: он обязан находить И обязан уметь не найти."""

    def test_the_three_known_sites_are_found_by_name(self) -> None:
        found = {(op, field) for op, field, _ in
                 version_dependent_refusal_sites()}
        for pair in (("create_floor", "holes"),
                     ("create_floor_by_contour", "contour.holes"),
                     ("create_tag", "tag_type")):
            with self.subTest(pair=pair):
                self.assertIn(pair, found)

    def test_a_planted_site_is_found(self) -> None:
        # Контроль-PASS обхода на СИНТЕТИКЕ: если бы он матчил по имени
        # функции или по строке, новая ветка была бы ему невидима.
        source = (
            "def _emit_nonesuch(op, ver):\n"
            "    if ver <= '2021':\n"
            "        raise KirRefusal([Diagnostic(\n"
            "            code=EMIT_UNSUPPORTED, op_id=oid,\n"
            "            field_name='planted', message_ru='x')])\n")
        hits = _sites_in_source(source)
        self.assertEqual(hits, {("_emit_nonesuch", "planted")})

    def test_a_different_code_is_not_mistaken_for_this_one(self) -> None:
        # Контроль-FAIL: обход обязан УМЕТЬ вернуть пусто. Иначе «нашёл три»
        # ничего не сообщает — он нашёл бы три и на чужом коде.
        source = (
            "def _emit_nonesuch(op, ver):\n"
            "    raise KirRefusal([Diagnostic(\n"
            "        code=EMIT_TYPE_MISMATCH, op_id=oid,\n"
            "        field_name='planted', message_ru='x')])\n")
        self.assertEqual(_sites_in_source(source), set())


def _sites_in_source(source: str) -> set[tuple[str, str | None]]:
    """Тот же обход, но над произвольным текстом — для контролей выше."""

    found: set[tuple[str, str | None]] = set()

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Diagnostic":
                keywords = {k.arg: k.value for k in node.keywords}
                code = keywords.get("code")
                if isinstance(code, ast.Name) and code.id == "EMIT_UNSUPPORTED":
                    raw = keywords.get("field_name")
                    field = raw.value if isinstance(raw, ast.Constant) else None
                    found.add((self.stack[-1] if self.stack else "<модуль>",
                               field))
            self.generic_visit(node)

    Walk().visit(ast.parse(source))
    return found


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
