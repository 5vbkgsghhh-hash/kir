"""ВЕРСИЯ РЕВИТА ВЫВОДИТСЯ В ОДНОМ МЕСТЕ, И СЕДЬМОЕ ОБЯЗАНО НАЗВАТЬ СЕБЯ.

13.08.2026 владелец впервые открыл ДВА Ревита сразу — 2026 и 2023 на одном
устройстве. До этого дня умолчание «2026» совпадало с истиной на единственном
устройстве, где всё проверяется, поэтому зелёное живого прогона было фактом о
выборке из одного, а не о коде (разбор — в `kukai/ir/revit_version.py`).

ЧТО ЭТОТ ФАЙЛ СТЕРЕЖЁТ. Не «сколько в дереве годов» — а чтобы величина,
называемая версией Ревита, приходила из ОДНОГО места, и чтобы всякое новое
место падало ЗДЕСЬ, названное по имени.

═══ ПРЕДМЕТ НАЗВАН ДО ТОГО, КАК ЕГО СЧИТАТЬ ═══

Сырое прочитано один раз прежде всякой фильтрации: 56 годовых литералов в 16
файлах `kukai/ir` без тестов. Они НЕ однородны, и различает их ПОЗИЦИЯ, а не
вид — grep по «2026» врал бы в обе стороны:

    ПОТРЕБЛЕНИЕ  `if ver < "2022"`, `TOPOSOLID_MIN_VERSION = "2024"`,
                 `E003_EXPECTED_BELOW = {...}` — ветвление эмиттера и пороги
                 способностей. Версию они ПРИНИМАЮТ и ничего не сообщают о
                 том, какая она у нас. **Запретить их — запретить язык:**
                 эмиттер обязан ветвиться, `Floor.Create` против
                 `doc.Create.NewFloor` — это и есть шесть целевых версий.

    ВЫВОД        `revit_version: str = "2026"`, `x or "2026"`,
                 `m.group(0) if m else "2026"`, `d.get(k, "2026")` — литерал
                 ОТВЕЧАЕТ на вопрос «какая версия», когда никто не сказал.
                 **Это предмет, и только он.**

Третий предмет нашёлся чтением и едва не был пропущен: **КОПИЯ АВТОРИТЕТА** —
последовательность из шести годов, выписанная второй раз. Приедет 2027 в
реестр, копия молча останется шестёркой; ни одно правило про умолчания её не
видит, потому что она не отвечает ни на какой вопрос — она ПОВТОРЯЕТ ответ.

═══ РОД СПИСКОВ ═══

`DERIVATIONS` и `AUTHORITY_COPIES` — **ПОЛНЫЕ ПО ПОСТРОЕНИЮ**: состав не ведут
руками, он вычисляется обходом AST и сверяется с объявленным. «Нет записи»
значит «места нет», а не «мы не знаем». Обе стороны равенства обязательны:
запись без места — тоже красный, иначе реестр переживёт свой предмет.

Но полнота такого списка есть полнота его СОПОСТАВИТЕЛЯ, а не авторитета
(закон дома, оплачен `_emits`, искавшим ярлык вместо ветки). Поэтому
сопоставитель читает ПОЗИЦИЮ в дереве разбора, а не текст строки, и у него
есть контроль в обе стороны — `TheProbeCanSayNo`.

═══ ЧЕГО ЭТОТ ПРИБОР НЕ ПОКРЫВАЕТ (молчание читается как покрытие) ═══

1. **Только `kukai/ir`, и это решение, а не лень.** Компилятор публикуется
   отдельным репозиторием под Apache-2.0; гард, лезущий в `kukai/api` или
   `kukai/llm`, ломает ровно ту границу, ради которой это разделение и
   заведено. Пять мест `api/admin_kir.py` и одно `llm/api_members.py` из
   замера директора — ВНЕ охвата, навсегда, и под этот храповик не встанут
   никогда.

   **Отсюда — вслух, по требованию КОРПУСА, потому что подразумевать это
   нельзя: зелёный храповик говорит «выводов больше нет В МОЁМ КАТАЛОГЕ», а
   НЕ «выводов больше нет».** Тем же самым в этот день опровергли подпись
   замка рецензии: вердикт есть свойство входа, который прибор не назвал.
   Здесь вход назван — `kukai/ir` без тестов, 150 файлов, и число печатается
   в сообщении об ошибке.

   Что стережёт те шесть мест: `kukai/ir/tests/
   test_revit_version_provenance_rides.py` (КОРПУС) — но он ловит одну форму
   возврата и состава НЕ морозит. Дыра названа, а не закрыта.
2. **Аргумент в точке вызова не считается выводом.** `compile_program(prog,
   revit_version="2026", ...)` в `gate_runner` — осознанный выбор стенда, а не
   ответ на незнание. Правило, ловящее и его, ловило бы каждый параметризованный
   прогон.
3. **Год, пришедший не литералом,** — из переменной, из окружения, склеенный из
   кусков — невидим по построению. Прибор читает литералы.
4. **Он не проверяет, ЧТО вернул источник.** Правильность самого
   `revit_version.resolve` — предмет его собственных тестов.
"""
from __future__ import annotations

import ast
import pathlib
import tempfile
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[3]
IR = BACKEND / "kukai" / "ir"

#: Годы, которые в этом доме означают версию Ревита. Диапазон шире реестра
#: НАРОЧНО: прибор обязан увидеть литерал «2027» в тот день, когда его впишут,
#: а не после того, как реестр его примет.
YEARS = {str(y) for y in range(2015, 2036)} | set(range(2015, 2036))

#: ЕДИНСТВЕННОЕ место, где умолчанию версии положено жить.
SOURCE = "kukai/ir/revit_version.py"


# --------------------------------------------------------------------------
# СОПОСТАВИТЕЛЬ: позиция в разборе, а не текст строки
# --------------------------------------------------------------------------

def _is_year(node) -> bool:
    return isinstance(node, ast.Constant) and node.value in YEARS


def _docstrings(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            doc = ast.get_docstring(n, clean=False)
            if doc:
                out.add(doc)
    return out


def _parents(tree) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _is_compared(node, parents: dict[int, ast.AST]) -> bool:
    """Литерал СРАВНИВАЕТСЯ, а не становится ответом.

    Поправка КОРПУСА 13.08, и она уточняет предмет, а не смягчает правило.
    `gate_runner.py:1089` читается целиком так:

        if ver < E003_EXPECTED_BELOW.get(name, "2021")

    `"2021"` тут — сторож со значением «никогда»: нижняя граница, при которой
    `ver < ...` ложно для всех шести версий. Литерал отвечает не на «какая
    версия», а на «ниже какой ждать KIR-E003», и ответ — «ни ниже какой».
    По ФОРМЕ он неотличим от `d.get(k, "2026")`, решает СЕМАНТИКА, и её
    машинный признак вот этот: подняться к родителю и спросить, не операнд ли
    это сравнения.

    Приём одной строкой: **становится ли литерал ответом — или сравнивается с
    ответом.**
    """
    seen = 0
    current = node
    while seen < 4:
        parent = parents.get(id(current))
        if parent is None:
            return False
        if isinstance(parent, ast.Compare):
            return True
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.Return,
                               ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        current, seen = parent, seen + 1
    return False


def _qualname(tree, node) -> str:
    """Ближайшее объемлющее имя — ключ, переживающий сдвиг строк.

    Ключ по `file:line` протух бы от любой правки выше по файлу, и храповик
    краснел бы на чужих коммитах, ничего не сообщая о предмете.
    """
    best, best_span = "<module>", None
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            continue
        end = getattr(n, "end_lineno", n.lineno)
        if n.lineno <= node.lineno <= end:
            span = end - n.lineno
            if best_span is None or span < best_span:
                best, best_span = n.name, span
    return best


def derivations_in(path: pathlib.Path, source: str | None = None) -> list[dict]:
    """Места, ВЫДАЮЩИЕ версию там, где ответа не было."""
    src = source if source is not None else path.read_text(
        encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    docs = _docstrings(tree)
    parents = _parents(tree)
    found: list[dict] = []

    def add(node, form, binding):
        if isinstance(node.value, str) and node.value in docs:
            return
        if _is_compared(node, parents):
            return
        found.append({
            "file": path.as_posix(), "line": node.lineno,
            "qual": _qualname(tree, node), "form": form,
            "binding": binding, "value": str(node.value),
        })

    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            positional = a.posonlyargs + a.args
            pad = [None] * (len(positional) - len(a.defaults))
            pairs = list(zip(positional, pad + list(a.defaults)))
            pairs += list(zip(a.kwonlyargs, a.kw_defaults))
            for arg, default in pairs:
                if default is not None and _is_year(default):
                    add(default, "умолчание параметра", arg.arg)
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            for value in n.values[1:]:
                if _is_year(value):
                    add(value, "запасной ответ `or`", "<выражение>")
        elif isinstance(n, ast.IfExp):
            for branch in (n.body, n.orelse):
                if _is_year(branch):
                    add(branch, "запасной ответ тернарника", "<выражение>")
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and len(n.args) == 2
                and _is_year(n.args[1])):
            add(n.args[1], "умолчание `.get`", "<словарь>")
        elif isinstance(n, ast.Assign) and _is_year(n.value):
            for target in n.targets:
                name = getattr(target, "id", None) or getattr(
                    target, "attr", None)
                if name and "version" in name.lower() and not name.isupper():
                    add(n.value, "присваивание версии", name)
        elif (isinstance(n, ast.AnnAssign) and n.value is not None
                and _is_year(n.value)):
            name = getattr(n.target, "id", None) or getattr(
                n.target, "attr", None)
            if name and "version" in name.lower() and not name.isupper():
                add(n.value, "присваивание версии", name)
    return found


def authority_copies_in(path: pathlib.Path,
                        source: str | None = None) -> list[dict]:
    """Последовательности из >=3 годов — второй экземпляр реестра версий.

    Порог 3, а не 2: пара годов — это чаще всего границы «от и до», а не
    перечисление. Мощность, при которой правило СПОСОБНО сработать, названа
    здесь, потому что при пороге 7 оно молчало бы на сегодняшней шестёрке.
    """
    src = source if source is not None else path.read_text(
        encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            continue
        if not n.elts or not all(_is_year(e) for e in n.elts):
            continue
        if len(n.elts) < 3:
            continue
        out.append({"file": path.as_posix(), "line": n.lineno,
                    "qual": _qualname(tree, n), "n": len(n.elts),
                    "values": [str(e.value) for e in n.elts]})
    return out


def _files() -> list[pathlib.Path]:
    return [p for p in sorted(IR.rglob("*.py")) if "/tests/" not in p.as_posix()]


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def sweep() -> tuple[dict[str, int], dict[str, int], list[str], int]:
    """Состав выводов -> СКОЛЬКО их на месте, а не просто «место есть».

    Ключ несёт СЧЁТ нарочно, и это не украшение. Первая редакция ключевала
    `файл::функция::привязка`, и `shadow._norm_version` — где ДВА тернарника
    отвечают «2026» — схлопывался в одну запись. Значит второй вывод внутри
    уже записанной функции был бы невидим ПО ПОСТРОЕНИЮ: добавь третий, и
    храповик промолчит. Это ровно «мощность 1 не пиннит множественную ветку»,
    моя же находка того же дня, совершённая в приборе против неё.
    """
    derived: dict[str, int] = {}
    copies: dict[str, int] = {}
    answers: set[str] = set()
    for path in _files():
        rel = _rel(path)
        for row in derivations_in(path):
            key = "%s::%s::%s::%s" % (rel, row["qual"], row["binding"],
                                      row["form"])
            derived[key] = derived.get(key, 0) + 1
            answers.add(row["value"])
        for row in authority_copies_in(path):
            key = "%s::%s" % (rel, row["qual"])
            copies[key] = copies.get(key, 0) + 1
    return derived, copies, sorted(answers), len(_files())


# --------------------------------------------------------------------------
# ХРАПОВИК — ПОФАМИЛЬНЫЙ. Число сказало бы «стало больше»; список говорит
# «стало больше ВОТ ЭТИМ», и только второе решает, что делать.
# --------------------------------------------------------------------------

#: Место -> (сколько литералов там выводят версию, почему это ещё так).
#: Счёт обязателен: без него второй вывод в уже записанной функции невидим.
DERIVATIONS: dict[str, tuple[int, str]] = {
    "kukai/ir/compiler.py::emit::revit_version::умолчание параметра":
        (1, "13.08: умолчание ПУБЛИЧНОЙ функции — каллер видит его в "
            "сигнатуре. Оставлено осознанно (довод КОРПУСА): функция без "
            "умолчания заставит каждого каллера выдумать своё, и выводов "
            "станет больше, а не меньше"),
    "kukai/ir/compiler.py::compile_program::revit_version::умолчание параметра":
        (1, "13.08: ГЛАВНОЕ умолчание дома — 12 голденов из 69 "
            "версиезависимы (7 меняют ИСХОД, 5 — только C#). Видимо в "
            "сигнатуре, поэтому остаётся; но если седьмое место появится, "
            "оно появится здесь"),
    "kukai/ir/compiler.py::compile_rebuild_chunk::revit_version::"
    "умолчание параметра":
        (1, "13.08: то же умолчание на пути перестройки"),
    "kukai/ir/coverage_feed.py::record_rejections::revit_version::"
    "умолчание параметра":
        (1, "13.08: телеметрия отказов пишет версию в корпус; умолчание тут "
            "красит СТАТИСТИКУ, а не здание"),
    "kukai/ir/serving.py::_record_pre_effect::revit_version::"
    "умолчание параметра":
        (1, "13.08: умолчание в квитанции до эффекта; после проводки "
            "`1c8ab589` каллер передаёт разрешённое значение, умолчание — "
            "последний рубеж"),
    "kukai/ir/shadow.py::_norm_version::<выражение>::"
    "запасной ответ тернарника":
        (2, "13.08: ДВА тернарника в одной функции, и это ЕДИНСТВЕННОЕ "
            "место дома, спрашивающее spec.REVIT_VERSIONS — при том что "
            "модуль объявлен observe-only. Единственный, кто читал "
            "авторитет, был единственным, чей ответ ничего не решал"),
}

#: Копии реестра версий. Авторитет — `registry_base.REVIT_VERSIONS`.
AUTHORITY_COPIES: dict[str, tuple[int, str]] = {
    "kukai/ir/registry_base.py::<module>":
        (1, "АВТОРИТЕТ. Здесь этой шестёрке и место"),
}


class TheDerivationsAreExactlyThese(unittest.TestCase):
    def test_the_register_matches_what_the_tree_holds(self):
        derived, _copies, _answers, files = sweep()
        self.assertGreater(
            files, 50,
            "обход не нашёл файлов — прибор смотрит не туда, и пустой "
            "результат был бы зелёным по построению")
        declared = {k: n for k, (n, _why) in DERIVATIONS.items()}
        self.assertEqual(
            derived, declared,
            "состав мест, ВЫВОДЯЩИХ версию Ревита, изменился.\n"
            f"  появилось: {sorted(set(derived) - set(declared))}\n"
            f"  исчезло:   {sorted(set(declared) - set(derived))}\n"
            "  счёт разошёлся: "
            f"{ {k: (declared.get(k), v) for k, v in derived.items() if declared.get(k) != v} }\n"
            f"  (просмотрено файлов: {files})\n"
            "Новое место — это седьмой ответ на «какая версия», и он обязан "
            f"быть назван здесь ИЛИ взят из {SOURCE}. Исчезнувшее — снимите "
            "запись вместе с причиной.")

    def test_every_entry_says_why_and_when(self):
        for key, (count, reason) in sorted(DERIVATIONS.items()):
            with self.subTest(site=key):
                self.assertGreater(count, 0, f"{key}: счёт нулевой")
                self.assertTrue(reason.strip(), f"{key}: причина пуста")
                self.assertTrue(
                    any(ch.isdigit() for ch in reason),
                    f"{key}: в причине нет даты — запись без даты не долг, "
                    "а глушилка")

    def test_the_authority_is_not_copied(self):
        _derived, copies, _answers, _files = sweep()
        declared = {k: n for k, (n, _why) in AUTHORITY_COPIES.items()}
        self.assertEqual(
            copies, declared,
            "перечень версий выписан не там, где объявлено.\n"
            f"  появилось: {sorted(set(copies) - set(declared))}\n"
            f"  исчезло:   {sorted(set(declared) - set(copies))}")

    def test_there_is_exactly_one_answer_to_i_do_not_know(self):
        """ОДИН ответ на «не знаю» во всём охвате — и это НОВОЕ состояние.

        Утром 13.08 их было три: 2026, 2023 (`sdk.compile`) и 2021
        (`gate_runner`, оказавшийся сторожем и не выводом). Плюс 2024 в
        `llm/api_members.py` — ВНЕ охвата. Проводка `1c8ab589` свела к одному.

        Число тут стоит не ради числа: каждый ЛИШНИЙ ответ — это место,
        которое разойдётся с остальными ровно на устройстве, где версия не
        та, что у нас. До 13.08 таких устройств не бывало — теперь у
        владельца открыты 2026 и 2023 одновременно.
        """
        _derived, _copies, answers, _files = sweep()
        self.assertEqual(
            answers, ["2026"],
            "ответов на «не знаю» стало больше одного: %s. Второй ответ — "
            "это расхождение, которое проявится только на чужой версии."
            % answers)


class TheProbeCanSayNo(unittest.TestCase):
    """Контроль в обе стороны. Подсадка ПОХОЖА НА ПЛОЩАДКУ, а не на маркер.

    Мощность названа: контроль-FAIL сажает ровно те формы, что живут в дереве
    (умолчание параметра, `or`, тернарник, `.get`), а контроль-PASS — те, что
    прибор обязан ПРОПУСТИТЬ. Без второй половины правило «любой год — вывод»
    прошло бы обе проверки и запретило бы эмиттеру ветвиться.
    """

    def _write(self, text: str) -> pathlib.Path:
        path = pathlib.Path(tempfile.mkdtemp()) / "planted.py"
        path.write_text(text, encoding="utf-8")
        return path

    def test_it_catches_each_shape_of_a_real_derivation(self):
        planted = self._write(
            "import re\n"
            "def resolve(ctx, revit_version: str = '2025'):\n"
            "    v = ctx.reported or '2024'\n"
            "    m = re.search(r'20\\d\\d', ctx.raw)\n"
            "    w = m.group(0) if m else '2023'\n"
            "    z = ctx.meta.get('revit_version', '2022')\n"
            "    doc_version = '2021'\n"
            "    return v, w, z, doc_version\n")
        found = derivations_in(planted)
        forms = {row["form"] for row in found}
        self.assertEqual(
            forms,
            {"умолчание параметра", "запасной ответ `or`",
             "запасной ответ тернарника", "умолчание `.get`",
             "присваивание версии"},
            "прибор не увидел одну из живых форм вывода: %s" % sorted(forms))
        self.assertEqual(len(found), 5, [r["form"] for r in found])

    def test_it_stays_silent_on_consumption_which_is_the_whole_language(self):
        planted = self._write(
            "MIN_VERSION = '2024'\n"
            "SINCE = 2022\n"
            "def emit(ver):\n"
            "    if ver < '2022':\n"
            "        return 'old'\n"
            "    elif ver >= '2024':\n"
            "        return 'new'\n"
            "    return compile_it(ver, revit_version='2026')\n")
        found = derivations_in(planted)
        self.assertEqual(
            found, [],
            "прибор объявил выводом ПОТРЕБЛЕНИЕ версии: %s. Так он запретил "
            "бы эмиттеру ветвиться по шести целевым версиям — то есть язык."
            % [(r["form"], r["line"]) for r in found])

    def test_a_literal_that_is_compared_is_not_a_derivation(self):
        """Поправка КОРПУСА: сторож со значением «никогда» — не ответ.

        Обе половины обязательны и они РЯДОМ, потому что по форме отличаются
        одним словом: в первой `.get` сравнивается, во второй — присваивается.
        Без второй половины правило «`.get` с годом никогда не вывод» прошло
        бы этот тест и ослепило прибор на настоящем умолчании словаря.
        """
        compared = self._write(
            "BELOW = {'a': '2024'}\n"
            "def gate(ver, name):\n"
            "    return ver < BELOW.get(name, '2021')\n")
        self.assertEqual(
            derivations_in(compared), [],
            "сторож нижней границы объявлен выводом версии")

        adopted = self._write(
            "TABLE = {'a': '2024'}\n"
            "def resolve(meta):\n"
            "    revit_version = TABLE.get(meta, '2021')\n"
            "    return revit_version\n")
        found = derivations_in(adopted)
        self.assertEqual(
            [r["form"] for r in found], ["умолчание `.get`"],
            "настоящее умолчание словаря пропущено — правило ослепло: %s"
            % found)

    def test_it_catches_a_second_copy_of_the_registry(self):
        planted = self._write(
            "SUPPORTED = ('2021', '2022', '2023', '2024', '2025', '2026')\n")
        self.assertEqual(len(authority_copies_in(planted)), 1)

    def test_a_pair_of_years_is_not_a_copy(self):
        planted = self._write("BOUNDS = ('2021', '2026')\n")
        self.assertEqual(
            authority_copies_in(planted), [],
            "пара годов — это границы «от и до», а не перечисление; правило "
            "с порогом 2 объявляло бы копией каждый диапазон")


if __name__ == "__main__":
    unittest.main()
