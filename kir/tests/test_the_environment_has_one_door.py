"""READING THE ENVIRONMENT HAS ONE DOOR, AND THE EXCEPTION LIST IS CLOSED.

WHY, AND THIS IS NOT A REPEAT OF ITS NEIGHBOR. Living nearby is
`test_env_names_belong_to_the_language::test_no_module_of_the_package_reads_a_renamed_name_directly`
— a ratchet that forbids reading a name from the `env.RENAMED` table
DIRECTLY. It is honest and BLIND BY CONSTRUCTION: it takes its list of
violations from that same table, so it has nothing to use to forbid a
direct read of a name that is not in the table.

🔴 THE PRICE OF THIS BLINDNESS, BY A MEASUREMENT ON 02.09.2026 (an `ast`
walk, production code without tests):

    references to the environment outside `kir/env.py` and                73 in 42 files
    `kir/install_paths.py`
    of which `KUKAI_*` names NOT PRESENT in the table                     42

That is, the gate stood green over forty-two direct reads of another
product's name. Twenty-four of them the eye never saw at all: they go
through a HELPER (`_int_env(name, …)`, `_env_float(name, …)`), where the
name is a call ARGUMENT, not a literal at the point of reference.

That is why a DIFFERENT property is asked here, and it depends neither on
the table nor on the shape of the call: **`os.environ` and `os.getenv` do
not occur anywhere in the package at all, except at the door and the NAMED
exceptions.** A gate that cannot be bypassed by rewriting the shape of the
reference is the only kind that guards anything (form 54).

═══ WHY EXCEPTIONS AND NOT ZERO, AND WHY EACH ONE HAS A CHECKED ARGUMENT ═══

🔴 AN ARGUMENT NOBODY CHECKS IS JUST A WORD. Paid for in this tree on
02.09.2026: eleven names were declared "named in the lesson," the name was
removed from the lesson — the gate stayed GREEN. That is why each
exception below carries an `argument` — a predicate over the SOURCE that
must be true — and `names` — the exact set of names read there. Should the
reason evaporate or the set change — red.

`debt` is a separate field, and it is NOT an excuse but a CLAIM: a
reference not covered by an argument, waiting for the smith of the
neighboring holding. It too is checked against a set: fix one, and the
gate goes red and demands the debt be reduced.

Run: pytest kir/tests/test_the_environment_has_one_door.py -q
"""
from __future__ import annotations

import ast
import pathlib
import re

_PKG = pathlib.Path(__file__).resolve().parents[1]

#: The one READING door. `install_paths.py` stopped being a door on
#: 02.09.2026: it queried `os.environ` itself, that is, it was a SECOND
#: place to remember. Now it is a consumer like everyone else.
_DOOR = ("env.py",)

#: The names by which a reference to the environment is recognized. What is
#: asked is the PROPERTY "the code touches the process environment," not
#: the shape of the call: `os.environ.get`, `os.getenv`, `environ[...]`
#: after `from os import environ`, `os.putenv` — all the same thing, and
#: rewriting the form gives no way around it.
_ENV_ATTRS = frozenset({"environ", "getenv", "putenv", "unsetenv"})


def _touches(tree: ast.AST) -> list[int]:
    """Lines where the module touches the process environment."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _ENV_ATTRS:
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id in _ENV_ATTRS:
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            lines += [node.lineno for a in node.names if a.name in _ENV_ATTRS]
    return sorted(lines)


def _names_read(tree: ast.AST) -> set[str]:
    """Environment variable names resolvable by parsing: a literal or a
    constant."""
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            consts[node.targets[0].id] = node.value.value

    def is_environ(n: ast.AST) -> bool:
        return (isinstance(n, ast.Attribute) and n.attr == "environ") or (
            isinstance(n, ast.Name) and n.id == "environ")

    def name_of(arg: ast.AST) -> str | None:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return consts.get(arg.id)
        return None

    found: set[str] = set()
    for node in ast.walk(tree):
        arg: ast.AST | None = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "setdefault", "pop") \
                and is_environ(node.func.value) and node.args:
            arg = node.args[0]
        elif isinstance(node, ast.Call) and node.args and (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "getenv")
                or (isinstance(node.func, ast.Name) and node.func.id == "getenv")):
            arg = node.args[0]
        elif isinstance(node, ast.Subscript) and is_environ(node.value):
            arg = node.slice
        if arg is not None:
            got = name_of(arg)
            if got:
                found.add(got)
    return found


# ─────────────────────────────────────────────────────── ARGUMENTS (checked)

def _the_child_is_built_and_wiped_here(tree: ast.AST, src: str) -> bool:
    """The sandbox ASSEMBLES the child's environment and WIPES it inside
    the child.

    Neither of these is expressible through the reading door: `env.get`
    answers "what value," while here what is being decided is WHAT
    ENVIRONMENT THE PROCESS WILL HAVE AT ALL. The child, moreover, reads
    its result fd BEFORE even one of our modules is brought up inside it.

    The argument dies together with its cause: should there be no child, or
    no wiping — red.
    """
    has_child = any(isinstance(n, ast.FunctionDef) and n.name == "_child_main"
                    for n in ast.walk(tree))
    return has_child and "os.environ.clear()" in src


def _only_inside_bench(tree: ast.AST, src: str) -> bool:
    """All references sit inside `_bench` — a benchmark, not the service
    path.

    `_bench` sets itself a journal path in a temporary directory and
    restores the previous one in `finally`. This is a WRITE, while the door
    `env.get` answers a question about READING; but the obligation is
    narrow, and it is not checked by a word: if even one reference leaks
    out of `_bench` into the service path — red.
    """
    bench = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_bench"]
    if not bench:
        return False
    inside = set()
    for fn in bench:
        inside.update(_touches(fn))
    return sorted(inside) == _touches(tree)


def _nothing_claimed(tree: ast.AST, src: str) -> bool:
    """There is no argument: the whole reference is DEBT. It does not
    pretend to be an excuse."""
    return True


class _Исключение:
    __slots__ = ("сколько", "имена", "почему", "довод", "долг")

    def __init__(self, *, сколько, имена, почему, довод, долг=()):
        self.сколько = сколько
        self.имена = frozenset(имена)
        self.почему = почему
        self.довод = довод
        self.долг = frozenset(долг)


#: A CLOSED list. The key is a path relative to `kir/`.
ИСКЛЮЧЕНИЯ: dict[str, _Исключение] = {
    "sandbox.py": _Исключение(
        сколько=9,
        имена={"KIR_SANDBOX_CFG", "KIR_SANDBOX_JAIL", "KIR_SANDBOX_RESULT_FD",
               "KUKAI_IR_AUTHOR_GEOMETRY_LIBS"},
        почему="родитель собирает окружение ребёнка с нуля, ребёнок читает свой "
               "fd результата до подъёма наших модулей и стирает окружение "
               "целиком — дверь ЧТЕНИЯ этого не выражает",
        довод=_the_child_is_built_and_wiped_here,
        # 🔴 A CLAIM for the sandbox smith: an ordinary flag, NOT covered by
        # the argument above.
        долг={"KUKAI_IR_AUTHOR_GEOMETRY_LIBS"},
    ),
    "serving.py": _Исключение(
        сколько=4,
        имена={"KUKAI_A5_CONFIRM_TOKEN", "KUKAI_ADMIN_DEVICES",
               "KUKAI_IR_GROUND_REUSE"},
        почему="дверь ПРОДУКТА в надел другого кузнеца; два имени продуктовые "
               "(аренда A5, служебные устройства) и уедут ПОРТОМ, третье — "
               "обычный флаг языка и ждёт правки",
        довод=_nothing_claimed,
        долг={"KUKAI_IR_GROUND_REUSE"},
    ),
    "live/journal_store.py": _Исключение(
        сколько=2,
        имена={"KIR_JOURNAL_STORE_PATH"},
        почему="`--bench` ставит себе путь во временный каталог и возвращает "
               "прежний; это ЗАПИСЬ на мерке, а не путь службы",
        довод=_only_inside_bench,
    ),
}


#: 🔴 THE DENOMINATOR OF THE WALK. A measurement on 02.09.2026 (the command
#: is in the function body below): **299** production files across 13
#: subpackages. The floor is set WITH MARGIN and DELIBERATELY does not
#: equal the measurement: an exact number would turn the gate red on every
#: new module, and the floor's subject is not the growth of the tree but
#: LOSS OF THE SUBJECT. 240 sits below today's 299 and ABOVE the loss of
#: any major subpackage: without `decompile` there would remain 238,
#: without the package root — 169.
ФАЙЛОВ_НЕ_МЕНЬШЕ = 240


def _production_files() -> list[pathlib.Path]:
    """The package's production code: without the suites and without
    `conftest`.

    Tests are excluded DELIBERATELY and by the same argument as the
    neighboring ratchet: they set up their own environment, and do so
    through `kir.tests.envtools.подменить_env`, whose return value is an
    obligation, not a promise.

    🔴 THE DENOMINATOR LIVES HERE, ONE FOR THE WHOLE FILE, AND THIS IS NOT A
    FORMALITY. A walk that lost its subject hands back "no violators" —
    that is, a PROVEN one door, the most expensive silence possible for
    this file: three assertions out of five would pass VACUOUSLY and read
    as a win. This shape was paid for in the tree twice on 02.09.2026 (a
    walk over the satellites went red because it had a denominator; the
    emitter gate saw 35 names out of 72 and stayed green, because it
    checked only non-emptiness).

    There are TWO assertions about the walker, and the second is stronger
    than the first: the count catches a walk that went off into emptiness,
    while the by-name check catches a walk that went off INTO A DIFFERENT
    TREE, where there could be even more files.

        PYTHONPATH=/opt/kir python -c "import pathlib;p=pathlib.Path('/opt/kir/kir');\
        print(sum(1 for f in p.rglob('*.py') if 'tests/' not in str(f.relative_to(p))\
        and f.name!='conftest.py'))"      # 02.09.2026 -> 299
    """
    out = []
    файлов = 0
    for path in sorted(_PKG.rglob("*.py")):
        rel = str(path.relative_to(_PKG))
        if "tests/" in rel or path.name == "conftest.py":
            continue
        файлов += 1
        out.append(path)
    assert файлов >= ФАЙЛОВ_НЕ_МЕНЬШЕ, (
        f"\n🔴 ОБХОД ПРОШЁЛ {файлов} файлов при поле {ФАЙЛОВ_НЕ_МЕНЬШЕ} "
        f"(замер 02.09.2026 — 299).\n"
        "Это заявление о ХОДОКЕ, а не о двери: столько файлов пакет от правки\n"
        "не теряет. Проверь `_PKG` и раскладку прежде, чем верить любому числу\n"
        "этого файла — при обеднённом обходе «нарушителей нет» значит «никого\n"
        "не спрашивали», а читается как доказанная одна дверь.")
    видно = {str(p.relative_to(_PKG)) for p in out}
    обязаны = set(_DOOR) | set(ИСКЛЮЧЕНИЯ)
    assert обязаны <= видно, (
        f"\n🔴 ОБХОД НЕ УВИДЕЛ СВОЕГО ЖЕ ПРЕДМЕТА: {sorted(обязаны - видно)}.\n"
        "Дверь и каждое названное исключение обязаны лежать в обойдённом\n"
        "дереве. Их отсутствие значит, что ходок ушёл в ЧУЖОЕ дерево, — и\n"
        "счёта файлов такому обходу мало: там их может быть и больше.")
    return out


def _parsed(path: pathlib.Path):
    src = path.read_text(encoding="utf-8")
    return ast.parse(src), src


# ─────────────────────────────────────────────────────────────── ASSERTIONS

def test_no_module_outside_the_door_touches_the_environment():
    """🔴 THE MAIN POINT: NOBODY reads the environment bypassing the door,
    except those named."""
    нарушители: list[str] = []
    for path in _production_files():
        rel = str(path.relative_to(_PKG))
        if rel in _DOOR or rel in ИСКЛЮЧЕНИЯ:
            continue
        tree, _ = _parsed(path)
        строки = _touches(tree)
        if строки:
            нарушители.append(f"{rel}:{','.join(map(str, строки))}")
    assert not нарушители, (
        "окружение читается мимо `kir/env.py`. Зови `env.get(<имя>)` — она "
        "знает и прежнее имя, поэтому живая служба хозяина правки не заметит. "
        f"Носители: {нарушители}")


def test_every_exception_is_exactly_as_declared():
    """The count, the set of names, and the DEBT of each exception are
    checked against the tree."""
    расхождения: list[str] = []
    for rel, исключение in sorted(ИСКЛЮЧЕНИЯ.items()):
        path = _PKG / rel
        if not path.exists():
            расхождения.append(f"{rel}: файла нет — убери исключение")
            continue
        tree, _ = _parsed(path)
        было, стало = исключение.сколько, len(_touches(tree))
        if было != стало:
            расхождения.append(
                f"{rel}: обращений {стало}, объявлено {было} — поправь число")
        имена = _names_read(tree)
        if имена != исключение.имена:
            расхождения.append(
                f"{rel}: имена {sorted(имена)} != объявленных "
                f"{sorted(исключение.имена)}")
        чужие = исключение.долг - имена
        if чужие:
            расхождения.append(
                f"{rel}: долг {sorted(чужие)} уже погашен — вычеркни его")
    assert not расхождения, расхождения


def test_every_exception_still_earns_its_reason():
    """🔴 THE ARGUMENT IS CHECKED, NOT MERELY READ.

    Otherwise an exception outlives its cause silently — exactly the shape
    that was paid for on 02.09.2026 (eleven names "named in the lesson,"
    the name removed from the lesson, the gate green).
    """
    мёртвые: list[str] = []
    for rel, исключение in sorted(ИСКЛЮЧЕНИЯ.items()):
        path = _PKG / rel
        if not path.exists():
            continue
        tree, src = _parsed(path)
        if not исключение.довод(tree, src):
            мёртвые.append(f"{rel}: довод «{исключение.почему}» БОЛЬШЕ НЕ ВЕРЕН")
    assert not мёртвые, мёртвые


def test_the_door_is_one_and_it_is_the_one_that_reads_two_names():
    """Exactly one door is named, and it is the one that knows the old
    name.

    Without this, "one door" is a file's location, not a property: any
    module reading `os.environ` bare could be declared a door.
    """
    from kir import env

    assert _DOOR == ("env.py",)
    tree, _ = _parsed(_PKG / "env.py")
    assert _touches(tree), "дверь не трогает окружение — тогда это не дверь"
    assert env.RENAMED, "таблица прежних имён пуста — двойного чтения нет"
    assert callable(env.get) and callable(env.set_default)


def test_the_debt_is_named_and_nonzero_only_where_declared():
    """Debt lives ONLY in declared exceptions, and it is tracked by name.

    The total debt is a number that must fall: today 2 names in 2 files,
    both in someone else's holding (`sandbox.py`, `serving.py`), and both
    filed as a claim.
    """
    долг = {rel: sorted(искл.долг) for rel, искл in ИСКЛЮЧЕНИЯ.items()
            if искл.долг}
    assert долг == {"sandbox.py": ["KUKAI_IR_AUTHOR_GEOMETRY_LIBS"],
                    "serving.py": ["KUKAI_IR_GROUND_REUSE"]}, долг


# ────────────────────────────── THE SECOND NUMBER: OWNER'S NAMES IN THE LANGUAGE'S CODE

#: 🔴 WHY THIS IS A SEPARATE NUMBER, NOT THE SAME ONE. The assertion above
#: says: the environment is read through one door. It says NOTHING about
#: what NAME the language pronounces: `env.get("KUKAI_IR_CLASH")` would
#: sail straight through it.
#:
#: MEASURED on 02.09.2026, by a command (also in the function body below):
#: in the production code (docstrings do not count, the `env.RENAMED` table
#: does not count — it is the reference itself) there remain **27**
#: `KUKAI_*` names. Before the same day's fix there were 42 at the READING
#: sites alone.
#:
#: The number splits exactly in two, and the split carries weight:
#:
#:   PRODUCT (14)  concepts of ANOTHER product — LLM models, A5 leasing,
#:                 service devices, the DB pool. Renaming them to `KIR_*`
#:                 would mean declaring someone else's subject as our own;
#:                 this is BOUNDARY debt, and it is cured by a PORT, not by
#:                 letters. The list must REMAIN.
#:   REMAINDER (13) concepts of the LANGUAGE, still written under the
#:                 owner's name. Reading for all of them already goes
#:                 through the door, so this is SPEECH (refusal text, an
#:                 operator hint) and live carriers in someone else's
#:                 holdings (`sandbox.py`, `serving.py`). The list must
#:                 SHRINK.
ПРОДУКТ: frozenset[str] = frozenset({
    "KUKAI_A5_CONFIRM_TOKEN", "KUKAI_ADMIN_DEVICES", "KUKAI_AGY_MODEL",
    "KUKAI_ANTIGRAVITY_MODEL", "KUKAI_CODEXPROXY_", "KUKAI_CODEXPROXY_MODEL",
    "KUKAI_CODEXPROXY_MODEL_FALLBACK", "KUKAI_DB_POOL_MIN",
    "KUKAI_FALLBACK_TIERS", "KUKAI_LLM_FALLBACK_MODEL",
    "KUKAI_LLM_LAST_RESORT_MODEL", "KUKAI_LLM_MODEL",
    "KUKAI_LLM_THINKING_MODEL", "KUKAI_MODELING_LLM_MODEL",
})

#: 🔴 THIS LIST IS A CLAIM, NOT AN EXCUSE. Every name here is waiting for a
#: fix, and five of the thirteen sit in someone else's holdings
#: (`sandbox.py`, `serving.py`). Clear one, and the gate will GO RED and
#: demand it be struck out; introduce a new one, and it will go red too.
#: That is exactly why this is a set, not "no more than N."
ОСТАТОК: frozenset[str] = frozenset({
    # speech: the owner's name is spoken to a human in a refusal or a hint
    "KUKAI_CHECKER_V2", "KUKAI_COMPILE_REQUIRED_VERSIONS",
    "KUKAI_DECOMPILE_DATA", "KUKAI_IR_BUILDING_GRAPH", "KUKAI_KIR_DECOMPILE",
    "KUKAI_KIR_SCENE_CACHE_DIR", "KUKAI_KIR_TRANSFER", "KUKAI_WEAK_SANDBOX",
    # live carriers and speech in someone else's holdings — a claim for the
    # serving/sandbox smiths
    "KUKAI_IR_AUTHOR_GEOMETRY_LIBS", "KUKAI_IR_GROUND_REUSE",
    "KUKAI_IR_JOURNAL", "KUKAI_IR_MERGE3", "KUKAI_IR_REBUILD",
})

_KUKAI = re.compile(r"\bKUKAI_[A-Z0-9_]+\b")


def _host_names_in_code() -> set[str]:
    """The owner's names, written in production CODE. Not in docstrings.

    A docstring is NARRATIVE (the distinction was introduced by its
    neighbor `test_the_package_does_not_know_the_host`): a record of what
    used to be where must remain verbatim. The values of `env.RENAMED` in
    the door itself do not count, for the same reason a dictionary does not
    count as usage of a word: the table of former names IS the place they
    are supposed to stand.
    """
    from kir import env

    found: set[str] = set()
    for path in _production_files():
        rel = str(path.relative_to(_PKG))
        tree, _ = _parsed(path)
        доки = set()
        for n in ast.walk(tree):
            body = getattr(n, "body", None)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)) and body \
                    and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                доки.add(id(body[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and id(n) not in доки:
                for m in _KUKAI.findall(n.value):
                    if rel in _DOOR and m in env.LEGACY_NAMES:
                        continue
                    found.add(m)
    return found


def test_the_host_names_left_in_the_code_are_exactly_the_named_ones():
    """27 owner names, and each is named: 14 product + 13 remainder."""
    видно = _host_names_in_code()
    объявлено = ПРОДУКТ | ОСТАТОК
    новые = sorted(видно - объявлено)
    исчезли = sorted(объявлено - видно)
    assert not новые, (
        "в коде языка появилось НЕНАЗВАННОЕ имя хозяина. Читать его надо "
        f"дверью `env.get(<новое имя>)`, пара — в `env.RENAMED`: {новые}")
    assert not исчезли, (
        "имя хозяина ушло из кода — вычеркни его из списка, иначе список "
        f"переживёт свою причину: {исчезли}")
    assert len(ПРОДУКТ) == 14 and len(ОСТАТОК) == 13, (
        f"замер 02.09.2026: 14 продуктовых + 13 остатка; сейчас "
        f"{len(ПРОДУКТ)} + {len(ОСТАТОК)}")


def test_no_product_name_ever_entered_the_rename_table():
    """🔴 THE OWNER'S DECISION: a PRODUCT concept is not renamed into
    `KIR_*`.

    Without this assertion, the boundary is held up by attentiveness alone:
    the next wave would "clean up" `KUKAI_LLM_MODEL` into `KIR_LLM_MODEL`
    and declare someone else's subject its own. Boundary debt is cured by a
    PORT, not by letters in a name.
    """
    from kir import env

    захвачено = sorted(ПРОДУКТ & env.LEGACY_NAMES)
    assert not захвачено, (
        "продуктовое имя попало в таблицу переименований: "
        f"{захвачено}. Это не косметика — это объявление чужого предмета своим")
