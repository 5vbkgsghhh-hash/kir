"""A SOURCE-CODE WALK MUST DECLARE A DENOMINATOR.

    PYTHONPATH=/opt/kir python3.12 -m kir.instruments.walk_denominator
    PYTHONPATH=/opt/kir python3.12 -m kir.instruments.walk_denominator --names
    PYTHONPATH=/opt/kir python3.12 -m kir.instruments.walk_denominator --self-check

🔴 THE BODY LIVES IN THE PACKAGE, NOT IN `tools/`, AND THIS WAS PAID FOR BY
ITS OWN GUARD ON THE INSTRUMENT'S BIRTHDAY (2026-09-02). The first edition
sat in `tools/`, and the ratchet imported it via `sys.path.insert` — and the
KIR<->product boundary guard immediately counted 2 HARD CROSSINGS instead of
1. `tools/` is NOT part of the installable package: for a stranger, such a
test would break on import. This shape was closed in this tree on 08-28 for
`canon_state` — and returned four days later as a new instance. The instance
was closed, not the kind.

🔴 WHY, AND THIS IS A MEASUREMENT FROM 2026-09-02. A wave of layer changes
relocated carriers — and TWO source-code walks went blind on the same day:

    the satellite walk looked for the TEXT of wrapper calls
        `return struct_emit.emit_foundation(...)`. The wave removed 29 of 41
        wrappers, and the walk found 4 delegations instead of 41 and ZERO
        refusal sites instead of six
    the emitter guard read a table out of `authoring.py`'s text and saw 35
        names out of 72: the bodies of 32 emitters had moved into satellites

The first TURNED RED, the second did NOT. The difference is exactly one
thing: the first had the line "the walk found fewer than six sites — this is
a claim about the WALKER, not about the registry", the second had `assert
names`, which only catches emptiness. **Fewer findings = fewer found defects,
and that is green, bought with blindness.**

Hence the rule this census watches for: a walk that COLLECTS a set over the
tree must declare how many places it is REQUIRED to find. Not "not zero" — A NUMBER.

WHAT COUNTS AS A WALK, AND WHAT DOES NOT
-----------------------------------------
    A WALK        there is a tree search (`rglob`/`glob`/`iterdir`/`walk`)
                 AND source reading (`read_text`/`getsource`/`ast.parse`)
    NOT a walk    reading ONE function (`getsource(f)` + substring): there is
                 no population, and demanding a number from it would mean
                 setting up a rule for the rule's own sake

    A DENOMINATOR `assert*`, where one side is `len(...)` and the other is A
                 NUMBER. An indirect denominator (the registry is checked in
                 BOTH directions, and an empty walk drops the reverse half)
                 is NOT VISIBLE to this instrument and will not be credited —
                 see the limit below

🔴 THE INSTRUMENT'S LIMIT, NAMED HONESTLY. The signal is syntactic: it sees
the shape `len(X) >= N`, not the meaning. Which means it will (a) not credit
a denominator expressed some other way (via a two-way registry check — that
is how the boundary guard is built), and (b) will credit `len(x) == 3` about
a subject unrelated to the walk. So the number here is an UPPER BOUND on the
debt, not a verdict on the file; the ratchet is pinned on the NUMBER, and
lowering it is only allowed together with a genuine fix.

WHAT THE INSTRUMENT DOES NOT DO: it does not fix tests and does not set up
exceptions. A list of exceptions with prose would be exactly what was paid
for on 09-02: eleven arguments of "named in the lesson" held up on word alone
until someone started checking them.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

import kir

#: 🔴 AN ANCHOR, NOT A COUNT OF STEPS UPWARD (2026-09-02). It used to say
#: `pathlib.Path(__file__).resolve().parent.parent` — correct for exactly ONE
#: layout, and `test_no_path_is_counted_in_steps_up` turned this very
#: instrument red on its birthday, naming the line. An instrument against
#: walk-blindness was itself a walk tied to the depth of its own file: let
#: `instruments/` move one level deeper, and the census would silently walk a
#: DIFFERENT tree, handing back "0 without a denominator", which would read
#: as a win. The package root is known by the package itself.
ПАКЕТ = pathlib.Path(kir.__file__).resolve().parent
ПОИСК = {"rglob", "glob", "iterdir", "walk"}
ЧТЕНИЕ = {"read_text", "getsource", "getsourcelines", "parse"}
ЗНАМ = {"assertGreaterEqual", "assertGreater", "assertEqual", "assertLessEqual"}


def _вызовы(t: ast.AST):
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            yield n, (getattr(n.func, "attr", None) or getattr(n.func, "id", None))


def это_обход(t: ast.AST) -> bool:
    имена = {и for _n, и in _вызовы(t)}
    return bool(имена & ПОИСК) and bool(имена & ЧТЕНИЕ)


def _числовые_константы(t: ast.AST) -> dict[str, int]:
    """NAME -> POSITIVE INTEGER for constants at ANY level of the module.

    A denominator named `ФАЙЛОВ_НЕ_МЕНЬШЕ = 700` is just as much a
    denominator as a literal; the instrument's first edition did not see it
    and did NOT CREDIT a genuine fix. Paid for right away, on its very first conversion.

    🔴 THE SAME LESSON PAID FOR A SECOND TIME, 2026-09-02: the second edition
    read ONLY `t.body`, i.e. the module level. A denominator declared RIGHT
    NEXT TO ITS OWN WALK — inside the test, one line above
    `assertGreaterEqual` — was not credited, and the census showed debt where
    it had already been closed. Five genuine conversions in a row stayed invisible.

    Where it is declared is a property of READABILITY, not a property of the
    denominator: for a walk living inside one test, a constant next to it is
    BETTER than one in the file header, because it reads together with its
    subject. An instrument that demanded module level would be demanding a
    LAYOUT, not a number — and would push people to move the number away
    from its walk just to get credit. There is no weakening here: the limit
    "will credit a threshold about an unrelated subject" is named in the
    header and has been with the instrument since birth; this fix removes a
    false NO, it does not introduce a new YES.
    """
    out: dict[str, int] = {}
    for узел in ast.walk(t):
        цели = (узел.targets if isinstance(узел, ast.Assign)
                else [узел.target] if isinstance(узел, ast.AnnAssign) else [])
        зн = getattr(узел, "value", None)
        if (isinstance(зн, ast.Constant) and isinstance(зн.value, int)
                and not isinstance(зн.value, bool) and зн.value > 0):
            for ц in цели:
                if isinstance(ц, ast.Name):
                    out[ц.id] = зн.value
    return out


def знаменатель(t: ast.AST) -> list[int]:
    """Lines where a COUNT is checked against a POSITIVE threshold.

    Two legitimate forms, and both occur in the tree:
      `self.assertGreaterEqual(len(sites), 6)`      a count against a literal
      `assert файлов >= ФАЙЛОВ_НЕ_МЕНЬШЕ`           a count against a CONSTANT

    A bare `assert` requires an ORDERING (`>=`/`>`): a bare name equal to a
    number is an ordinary statement about the subject, not a claim about the
    walker, and crediting it would mean handing out credit for shape alone.
    """
    константы = _числовые_константы(t)

    def порог(x) -> bool:
        if (isinstance(x, ast.Constant) and isinstance(x.value, int)
                and not isinstance(x.value, bool) and x.value > 0):
            return True
        return isinstance(x, ast.Name) and x.id in константы

    места: list[int] = []
    for n, имя in _вызовы(t):
        if имя not in ЗНАМ or len(n.args) < 2:
            continue
        пара = (n.args[0], n.args[1])
        есть_len = any(isinstance(x, ast.Call)
                       and getattr(x.func, "id", None) == "len" for x in пара)
        # A COUNTER NEXT TO THE WALK is the same shape as `len(...)`:
        # `files += 1` in a loop, then `assertGreaterEqual(files, THRESHOLD)`.
        # Demanding `len` specifically would mean crediting by SPELLING, not
        # by subject; paid for on its very first conversion, 2026-09-02.
        счётчик = имя in {"assertGreaterEqual", "assertGreater"} and any(
            isinstance(x, ast.Name) for x in пара)
        if (есть_len or счётчик) and any(порог(x) for x in пара):
            места.append(n.lineno)
    for узел in ast.walk(t):
        if not isinstance(узел, ast.Assert):
            continue
        пр = узел.test
        if (isinstance(пр, ast.Compare) and len(пр.ops) == 1
                and isinstance(пр.ops[0], (ast.GtE, ast.Gt))
                and порог(пр.comparators[0])
                and isinstance(пр.left, (ast.Name, ast.Call))):
            места.append(узел.lineno)
    return места


class ПереписьНеполна(RuntimeError):
    """Part of the files did not get read — and a share computed off the remainder is invalid.

    🔴 SET UP 2026-09-04 (RT-13). `перепись()` had a mute
    `except SyntaxError: continue`, and a file that failed to parse
    disappeared from BOTH buckets at once — both "with a denominator" and
    "without". This is the worst possible kind of loss here: the
    `БЕЗ_ЗНАМЕНАТЕЛЯ` ratchet is pinned on the SECOND bucket and only allows
    it to shrink, which means a BROKEN file would move it in the green
    direction. The debt would get closed by corrupting a file.

    The other end of the same road was even quieter: `read_text` had NO
    guard, and an unreadable file dropped the whole census. Silence and a
    crash are reduced to one and the same answer — a count.
    """


def перепись(корень: pathlib.Path = ПАКЕТ, *,
             непрочитанные: "dict | None" = None
             ) -> tuple[list[str], list[str]]:
    """(with a denominator, without a denominator) — paths relative to the package root.

    What could not be read goes into `непрочитанные` (path -> reason), and if
    no ledger was set up, `ПереписьНеполна` is raised: this census has no
    right to silently return two buckets that something has fallen out of.
    """
    с, без = [], []
    потеряно: dict = {}
    for f in sorted(корень.rglob("test_*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            текст = f.read_text(encoding="utf-8")
        except OSError as exc:
            потеряно[str(f)] = f"НЕ ПРОЧЁЛСЯ: {type(exc).__name__}: {exc}"
            continue
        try:
            t = ast.parse(текст)
        except SyntaxError as exc:
            потеряно[str(f)] = f"НЕ РАЗОБРАЛСЯ: SyntaxError: {exc}"
            continue
        if not это_обход(t):
            continue
        путь = str(f.relative_to(корень.parent))
        (с if знаменатель(t) else без).append(путь)
    if потеряно:
        if непрочитанные is None:
            raise ПереписьНеполна(
                f"перепись не прочла {len(потеряно)} файл(ов); доля «со "
                f"знаменателем» с остатка есть заявление о ПРИБОРЕ:\n  "
                + "\n  ".join(f"{p}: {w}" for p, w in sorted(потеряно.items())))
        непрочитанные.update(потеряно)
    return с, без


def самопроверка() -> int:
    """A FAIL control for the INSTRUMENT: both outcomes on inputs with a known answer."""
    беды = []
    случаи = [
        ("обход со знаменателем",
         "import pathlib\n"
         "def t(self):\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    self.assertGreaterEqual(len(x), 6)\n", True, True),
        ("обход без знаменателя",
         "import pathlib\n"
         "def t(self):\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    self.assertEqual(x, [])\n", True, False),
        ("НЕ обход: одна функция",
         "import inspect\n"
         "def t(self):\n"
         "    self.assertIn('x', inspect.getsource(f))\n", False, False),
        ("НЕ обход: поиск без чтения",
         "import pathlib\n"
         "def t(self):\n"
         "    self.assertTrue(list(pathlib.Path('.').rglob('*.py')))\n",
         False, False),
        ("обход со знаменателем-КОНСТАНТОЙ (форма сторожа границы)",
         "import pathlib\n"
         "ФАЙЛОВ_НЕ_МЕНЬШЕ = 700\n"
         "def t():\n"
         "    n = 0\n"
         "    for p in pathlib.Path('.').rglob('*.py'):\n"
         "        p.read_text(); n += 1\n"
         "    assert n >= ФАЙЛОВ_НЕ_МЕНЬШЕ\n", True, True),
        # 🔴 THIS CASE WAS SET UP AFTER ITS OWN CONTROL MISSED A MUTATION
        # (2026-09-02). A "remove the threshold check" mutation broke the
        # analysis while the self-check stayed green: not one of its inputs
        # checked `len` against a NON-threshold. A control that does not
        # cover a mutation is half a control.
        ("len против len — НЕ знаменатель: порога нет",
         "import pathlib\n"
         "def t(self):\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    self.assertEqual(len(x), len(x))\n", True, False),
        # 🔴 THIS CASE WAS SET UP AFTER THE INSTRUMENT MISSED SOMETHING
        # (2026-09-02): five genuine conversions in a row declared their
        # threshold RIGHT NEXT TO THEIR OWN WALK, inside the test — and the
        # census credited not one of them, because it only read `t.body`. A
        # number taken by an instrument that demands a LAYOUT instead of A
        # NUMBER is a claim about the instrument.
        ("порог-константа объявлена ВНУТРИ теста, рядом с обходом",
         "import pathlib\n"
         "def t(self):\n"
         "    ФАЙЛОВ_НЕ_МЕНЬШЕ = 250\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    self.assertGreaterEqual(len(x), ФАЙЛОВ_НЕ_МЕНЬШЕ)\n", True, True),
        ("порог-константа внутри теста, но НУЛЕВАЯ — не порог",
         "import pathlib\n"
         "def t(self):\n"
         "    ФАЙЛОВ_НЕ_МЕНЬШЕ = 0\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    self.assertGreaterEqual(len(x), ФАЙЛОВ_НЕ_МЕНЬШЕ)\n", True, False),
        ("счётчик против константы через assertGreaterEqual",
         "import pathlib\n"
         "ПОРОГ = 200\n"
         "def t(self):\n"
         "    n = 0\n"
         "    for p in pathlib.Path('.').rglob('*.py'):\n"
         "        p.read_text(); n += 1\n"
         "    self.assertGreaterEqual(n, ПОРОГ)\n", True, True),
        ("assertEqual имени числу — НЕ пол, а обычное утверждение",
         "import pathlib\n"
         "def t(self):\n"
         "    n = 0\n"
         "    for p in pathlib.Path('.').rglob('*.py'):\n"
         "        p.read_text(); n += 1\n"
         "    self.assertEqual(n, 3)\n", True, False),
        ("голое равенство имени числу — НЕ знаменатель",
         "import pathlib\n"
         "def t():\n"
         "    x = [p.read_text() for p in pathlib.Path('.').rglob('*.py')]\n"
         "    assert x == 3\n", True, False),
    ]
    for имя, текст, ждём_обход, ждём_знам in случаи:
        t = ast.parse(текст)
        if это_обход(t) != ждём_обход:
            беды.append(f"{имя}: обход={это_обход(t)}, ждали {ждём_обход}")
        elif ждём_обход and bool(знаменатель(t)) != ждём_знам:
            беды.append(f"{имя}: знаменатель={bool(знаменатель(t))}, ждали {ждём_знам}")
    if беды:
        print("🔴 САМОПРОВЕРКА ПРИБОРА НЕ ПРОШЛА:")
        for b in беды:
            print("   ", b)
        return 1
    print(f"самопроверка прибора: {len(случаи)}/{len(случаи)} — оба исхода "
          "различены, и «не обход» не принят за обход")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="walk_denominator_census")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args(argv)
    if a.self_check:
        return самопроверка()
    непрочитанные: dict = {}
    с, без = перепись(непрочитанные=непрочитанные)
    if непрочитанные:
        # THE LOSS IS NAMED BEFORE THE NUMBERS: a file that falls out of both
        # buckets moves the debt ratchet in the green direction — and does so silently.
        print(f"🔴 НЕ ВОШЛИ В ПЕРЕПИСЬ: {len(непрочитанные)} файл(ов) — числа "
              f"ниже сняты с того, что прочлось")
        for путь, почему in sorted(непрочитанные.items()):
            print(f"   · {путь}: {почему}")
    print(f"обходов по дереву (поиск + чтение исходника): {len(с) + len(без)}")
    print(f"  СО ЗНАМЕНАТЕЛЕМ: {len(с)}")
    print(f"  БЕЗ ЗНАМЕНАТЕЛЯ: {len(без)}  <- верхняя граница долга")
    if a.names:
        print()
        for f in без:
            print("   ", f)
    # `2` means "the instrument DID NOT JUDGE", as with its neighbors in this
    # directory: a census that lost a file has no right to exit zero together
    # with a debt number.
    return 2 if непрочитанные else 0


if __name__ == "__main__":
    sys.exit(main())
