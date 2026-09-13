"""CENSUS OF THE UNWIRED: what is built in the package and is not called by prod code.

    PYTHONPATH=/opt/kir python3.12 tools/unwired_census.py [--list] [--kind KIND]

WHY, IN THE OWNER'S WORDS (15.08.2026): "we have a bad habit — we do the
work and don't wire it in, and it just sits somewhere sticking out";
"I can't see everything myself". Nobody can enumerate this from memory —
so an instrument has to count it.

And a second reason, bought on 27.08.2026 by a whole shift: **six tasks
out of seven came back refuted** — the ledger was complete, the
mechanism was built, the move was finished, the member was named. The
work was planned against IMAGINED holes, because no one held the
current map, including the author of the plan. This census is an
attempt to have a map.

═══════════════════════════════════════════════════════════════════════════
🔴 HOW THIS INSTRUMENT IS ALREADY LESS THAN THE HOST'S INSTRUMENT, AND THIS IS STATED, NOT LEFT UNSAID
═══════════════════════════════════════════════════════════════════════════

The host (the instrument of the same name in its tree) has THREE census
passes, and the first is the CALL GRAPH from `graphify`. There is no
graph here:

    pip show graphifyy  ->  Package(s) not found        (measured 27.08.2026)
    import graphify     ->  ModuleNotFoundError

**The host's instrument does not even start without the graph** — it
begins with it. So here ONLY THE THIRD pass runs, over the AST, and it
answers a DIFFERENT, NARROWER question. The difference must travel
together with the number:

    THE GRAPH answers   who CALLS whom, and distinguishes "only tests
                        call it" from "nobody calls it"
    THE AST answers     whether the NAME is used as an identifier in at
                        least one NON-test module of the package

The second question is blinder to direction and WIDER in the candidates
it covers: the graph sees only what fell into it, while the AST walk
sees every definition.

🔴 **And one property of the third pass makes it not a substitute but
the STRONGEST link.** The host's docstring records a measurement: **the
bare graph gives 37% false readings**, because it does not see a
function passed by VALUE into a registry — and the project stands on
registries (`RuleSpec`, `spec.OPS`, dispatch tables). It was exactly the
AST pass that recovered that 37%: the registry entry
`light.check_hab030` is an `ast.Attribute`, and it sees it. Here this
pass is the only one, so the census has NO registry blindness.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS CENSUS DOES NOT SEE — THE LIST IS CLOSED AND NOT COMPLETE
═══════════════════════════════════════════════════════════════════════════

The error is ONE-SIDED: the instrument can accuse something innocent
and cannot exonerate something guilty. Invisible:

* a call through ``getattr(mod, "name")`` and dispatch BY STRING;
* a name in a STRING annotation (``"CensusEntry"``);
* an entry point called by name from C#, from configuration, from the
  environment;
* a package entry point called from OUTSIDE (the consumer is the host,
  not us).

The last one weighs more here than for the host: **the package is
published separately**, and it has legitimate public names with no
internal caller. That is why membership in ``__all__`` is counted as a
SEPARATE kind, and not mixed into "wired in": "declared public" and
"called from inside" are different facts.

Dunders (``__init__``, ``__post_init__``, ``__enter__``) are excluded:
the runtime calls them, nobody ever calls them by name, and without the
exclusion they would produce hundreds of false positives.

═══════════════════════════════════════════════════════════════════════════
THE ROOT COMES FROM THE PACKAGE'S LOCATION, NOT BY STEPPING UPWARD
═══════════════════════════════════════════════════════════════════════════

The host's instrument computes the root like this::

    BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

🔴 This is exactly the form that the 27.08 sweep swept up: **13 carriers
in the package**, and all of them pointed astray after the split. Here
the root is taken from `kir.__file__` — the layout changes, the
package's location does not. The package name is not hard-coded either:
in the host, `kukai/` stands as a literal TWICE, and an "as-is" port
would have given zero by construction.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING ON 01.09.2026 — A DOOR VS A
# JOURNAL. A module's docstring is a PUBLIC DOOR: `help()` prints it to a
# reader of the published package, and our machine's address tells them
# nothing. The knowledge is not erased — it is here, in the journal,
# where it belongs:
#     the host's census  /opt/kukai-rebuild1/backend/tools/unwired_census.py
from __future__ import annotations

import argparse
import ast
import collections
import os
import pathlib

from kir import env
import sys

#: The kinds that findings are sorted into. The list is CLOSED AND NOT
#: COMPLETE: it says what the instrument CAN DISTINGUISH on its own, not
#: what exists in the world. Everything it cannot distinguish goes into
#: `нужно_читать` — and that is more honest than guessing.
KINDS = (
    "по_построению",  # there IS NO caller AND THERE WILL BE NONE — this is a design property, not a debt
    "публичное",     # declared in __all__ — a legitimate entry point from outside the package
    "фикстура",      # exists for the sake of tests, a caller in prod is unnecessary by definition
    "приватное",     # name starts with an underscore: not a surface, and not called
    "нужно_читать",  # the instrument cannot tell — a PERSON decides
)

#: 🔴 THE DISTINCTION WITHOUT WHICH THE CENSUS ACCUSES THE MOST CORRECT
#: THING IN THE PACKAGE.
#:
#: "not called" is a DEBT. "CANNOT be called by name" is a DESIGN
#: PROPERTY. Conflating them means writing off the port's protocol as a
#: debt — exactly the thing the package is separated from the host for.
#:
#: 🔴 A PREDICATE ON A PROPERTY, NOT A LIST OF NAMES — AND THIS IS NOT
#: STYLE (form 54). A guard that pins down the SHAPE of the first case
#: goes blind on the second: the 25.08 rule looked for
#: `(__[A-Z]\w*)\s*\(` and stayed silent on `__src`, because that one is
#: written lowercase. A list of names would go stale at the very first
#: new port; a predicate does not.
#:
#: Every kind carries its REASON as a line. A kind with no reasons would
#: become a place where inconvenient things get swept, and in a month
#: nobody would tell a design property from a debt.
BY_CONSTRUCTION_REASONS = {
    "protocol": "протокол: структурный контракт поставщика. Его не создают и не "
                "зовут — по нему СВЕРЯЮТ. Вызывающего нет по определению",
    "pydantic_validator": "валидатор pydantic: зовётся ПРИ ПОСТРОЕНИИ объекта по "
                          "регистрации декоратором, по имени — никогда",
    "route": "обработчик маршрута: фреймворк зовёт по ПУТИ, а не по имени функции",
}

#: Decorators that register a function with someone else's mechanism.
_REGISTERING_DECORATORS = {
    "model_validator": "pydantic_validator",
    "field_validator": "pydantic_validator",
    "root_validator": "pydantic_validator",
}
#: Application-router methods: `@app.post("/rpc")`, `@router.get(...)`.
_ROUTE_METHODS = frozenset({"post", "get", "put", "patch", "delete", "websocket"})


def by_construction_reason(node: ast.AST) -> str | None:
    """Why this definition cannot have a caller BY NAME.

    Returns a reason key or None. It asks about a PROPERTY of the node
    (base class, registering decorator), not about how it is spelled.
    """
    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            name = base.attr if isinstance(base, ast.Attribute) else getattr(
                base, "id", None)
            if name == "Protocol":
                return "protocol"
        return None
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for dec in node.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Attribute):
            if func.attr in _REGISTERING_DECORATORS:
                return _REGISTERING_DECORATORS[func.attr]
            # `@app.post("/rpc")` — a route only with a PATH in the call;
            # a bare `x.get` without a call is not a route.
            if func.attr in _ROUTE_METHODS and isinstance(dec, ast.Call):
                return "route"
        elif isinstance(func, ast.Name) and func.id in _REGISTERING_DECORATORS:
            return _REGISTERING_DECORATORS[func.id]
    return None


class UnwiredCensusError(RuntimeError):
    """Census is impossible: the package was not found."""


def package_root() -> pathlib.Path:
    """The package directory — FROM THE PACKAGE'S LOCATION, not by
    stepping upward from this file.

    Counting by steps is not allowed: the layout change
    `backend/kukai/ir` -> `backend/kir` -> `/opt/kir/kir` moved the
    answer twice, both times silently (the form was swept up on
    27.08.2026, 13 carriers).
    """
    try:
        import kir
    except ImportError as exc:                                # pragma: no cover
        raise UnwiredCensusError(
            "пакет `kir` не импортируется: %s\n"
            "   СЛЕДУЮЩИЙ ХОД: PYTHONPATH=/opt/kir python3.12 %s\n"
            "   (`PYTHONPATH=.` здесь ОПАСЕН: посторонний kir.py затеняет пакет)"
            % (exc, " ".join(sys.argv))) from exc
    return pathlib.Path(kir.__file__).resolve().parent


def _is_test(rel: str) -> bool:
    """Whether this is a test module.

    🔴 FIXTURE DIRECTORIES ARE NOT INCLUDED HERE, AND THIS IS A FIX, NOT A
    MATTER OF TASTE. The first version treated anything containing
    "fixture" as a test, and thereby struck `checker/fixtures/builders.py`
    out of the DEFINITIONS, which meant the "fixture" kind could never
    fire and was printed as zero. For the host this file is the census's
    largest entry (16 items) and the most harmless one. A kind that can
    never fire is a vacuous zero (form 29).
    """
    rel = rel or ""
    base = os.path.basename(rel)
    return ("/tests/" in rel or rel.startswith("tests/")
            or "/test_" in rel or base.startswith("test_")
            or base == "conftest.py")


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def scan(root: pathlib.Path) -> dict[str, object]:
    """One walk: definitions, uses, public surface, unread files."""
    defined: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    used: dict[str, set[str]] = collections.defaultdict(set)
    exported: set[str] = set()
    by_construction: dict[str, str] = {}
    unparsed: list[str] = []
    modules = 0
    test_modules = 0

    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "venv", ".git")]
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            path = pathlib.Path(base) / name
            rel = str(path.relative_to(root.parent))
            if _is_test(rel):
                test_modules += 1
                continue
            modules += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                # NOT SILENTLY. An unread module NARROWS the set of found
                # uses, that is, it inflates "not wired in". The host's
                # measurement of 15.08: FIVE files failed to parse under
                # 3.10, including `authoring.py` — the compiler's most
                # imported code.
                unparsed.append(rel)
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    if not _is_dunder(node.name):
                        defined[node.name].append((rel, node.lineno))
                        reason = by_construction_reason(node)
                        if reason is not None:
                            by_construction[node.name] = reason
                elif isinstance(node, ast.Name):
                    used[node.id].add(rel)
                elif isinstance(node, ast.Attribute):
                    used[node.attr].add(rel)
                elif isinstance(node, ast.alias):
                    used[(node.asname or node.name).split(".")[-1]].add(rel)
                elif isinstance(node, ast.Assign):
                    # __all__ — the package's public surface. Strings, not
                    # identifiers, so an ordinary pass does not catch them.
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__all__":
                            for elt in ast.walk(node.value):
                                if isinstance(elt, ast.Constant) and isinstance(
                                        elt.value, str):
                                    exported.add(elt.value)
    return {
        "defined": defined, "used": used, "exported": exported,
        "by_construction": by_construction,
        "unparsed": unparsed, "modules": modules, "test_modules": test_modules,
    }


def _kind(name: str, sites: list[tuple[str, int]], exported: set[str],
          by_construction: dict[str, str] | None = None) -> str:
    """A kind is only what the instrument distinguishes ON ITS OWN. The
    rest is handed to a person.

    "Is this a shelf or is it dead" cannot be guessed: the difference is
    in INTENT, not in the text. So there are no such kinds here, and
    `нужно_читать` is not a gap but an honest refusal to distinguish.
    """
    # BY CONSTRUCTION is asked FIRST: a protocol declared in __all__
    # remains a protocol. "Public" describes VISIBILITY, "by
    # construction" describes the POSSIBILITY of being called, and the
    # second is stronger.
    if by_construction and name in by_construction:
        return "по_построению"
    if name in exported:
        return "публичное"
    if any("fixture" in rel or "builders" in rel for rel, _ in sites):
        return "фикстура"
    if name.startswith("_"):
        return "приватное"
    return "нужно_читать"


def host_usage(host: pathlib.Path) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str], int]:
    """Which of the package's CONSUMERS calls a name. The second corpus,
    and it is mandatory.

    🔴 AFTER THE SPLIT, "NOT CALLED FROM INSIDE" BECAME FAR WEAKER THAN IT
    WAS. In the host's tree, `serving.handle_revit_ir` called
    `kukai/api/admin_kir.py` — the same corpus, and the graph saw it. Now
    the consumer is in a DIFFERENT repository, and without it the census
    accuses the package's entire external surface: live, `handle_revit_ir`,
    `inject_revit_ir_schema` and all the ports fell into "not called" —
    exactly the thing the package exists for.

    Returns TWO dicts, and the split carries weight: a name that only the
    host's TESTS call is exactly the original question, "built, and only
    tests call it".
    """
    prod: dict[str, set[str]] = collections.defaultdict(set)
    test: dict[str, set[str]] = collections.defaultdict(set)
    unparsed: list[str] = []
    scanned = 0
    for base, dirs, names in os.walk(host):
        dirs[:] = [d for d in dirs
                   if d not in ("__pycache__", "venv", ".git", "node_modules")]
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            path = pathlib.Path(base) / name
            rel = str(path.relative_to(host))
            if rel.startswith("kir/"):     # this is the package ITSELF, not a consumer
                continue
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                unparsed.append(rel)
                continue
            sink = test if _is_test(rel) else prod
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    sink[node.id].add(rel)
                elif isinstance(node, ast.Attribute):
                    sink[node.attr].add(rel)
                elif isinstance(node, ast.alias):
                    sink[(node.asname or node.name).split(".")[-1]].add(rel)
    return prod, test, unparsed, scanned


def census(root: pathlib.Path | None = None,
           host: pathlib.Path | None = None) -> dict[str, object]:
    root = root or package_root()
    seen = scan(root)
    defined = seen["defined"]
    used = seen["used"]
    exported = seen["exported"]
    by_construction = seen["by_construction"]

    # 🔴 THE DEFINITION OF "WIRED IN" WAS FIXED BEFORE PUBLICATION, AND
    # THE MISS IS NAMED.
    #
    # The first version counted as wired in only what was used in a
    # FOREIGN module (`where_used - own`). A run gave 3022 of 5488
    # definitions, i.e. MORE THAN HALF the tree, and 2428 of them were
    # "self-contained".
    #
    # An implausible number is a statement about the MATCHER, not about
    # the subject. The reason: a private helper called by neighboring
    # methods of ITS OWN class is perfectly normal WIRED-IN code, and
    # most code in any tree is like that. The instrument was not
    # measuring "built and not called", it was measuring "is not a
    # cross-module surface".
    #
    # This is exactly the form the task warned about: that morning
    # `capability_graph` returned "modules 123 · live 0", because it
    # searched for roots that do not exist in the package. The only
    # difference is that here the zero was in the other direction.
    #
    # The correct definition is the host's: a name used as an identifier
    # ANYWHERE in non-test code (including its own module) is WIRED IN.
    # That is exactly how, for the host, `CensusEntry` went into the
    # refuted findings — it is used in an annotation inside its own
    # module.
    rows = []
    self_contained = 0
    for name, sites in defined.items():
        where_used = used.get(name, set())
        own = {rel for rel, _ in sites}
        if where_used:
            if not (where_used - own):
                # Wired in, but talks only to its own module. This is NOT
                # "not wired in"; it is a separate, weaker signal, and it
                # is printed as a separate number, not mixed into the main
                # one.
                self_contained += 1
            continue
        rows.append({
            "name": name,
            "sites": sites,
            "kind": _kind(name, sites, exported, by_construction),
            "why": by_construction.get(name, ""),
        })

    host_prod = host_test = None
    host_stat: dict[str, object] = {"scanned": 0, "unparsed": [], "present": False}
    if host is not None and host.is_dir():
        hp, ht, hu, hs = host_usage(host)
        host_prod, host_test = hp, ht
        host_stat = {"scanned": hs, "unparsed": hu, "present": True,
                     "root": str(host)}
        for row in rows:
            n = row["name"]
            if hp.get(n):
                row["host"] = "прод_хозяина"
            elif ht.get(n):
                row["host"] = "тесты_хозяина"
            else:
                row["host"] = "никто"
    else:
        for row in rows:
            row["host"] = "НЕ СПРОШЕН"

    by_kind = collections.Counter(r["kind"] for r in rows)
    by_host = collections.Counter(r["host"] for r in rows)
    return {
        "by_host": by_host,
        "host_stat": host_stat,
        "root": str(root),
        "modules": seen["modules"],
        "test_modules": seen["test_modules"],
        "defined": sum(len(v) for v in defined.values()),
        "unique_names": len(defined),
        "unwired": rows,
        "self_contained": self_contained,
        "by_kind": dict(by_kind),
        "by_construction": by_construction,
        "exported": len(exported),
        "unparsed": seen["unparsed"],
        "interpreter": "%d.%d.%d" % sys.version_info[:3],
    }


def _header(out: dict[str, object]) -> str:
    """The provenance header. Calls the shared carrier; its absence is a
    NAMED refusal.

    As of 27.08.2026, `kir.instruments.measure_header` sits in someone
    else's UNCOMMITTED wave. Duplicating it here would mean setting up a
    second carrier of the same knowledge — the tree's named defect; so
    the import is lazy, and its failure is printed, not swallowed.
    """
    blind = (
        "ГРАФА ВЫЗОВОВ НЕТ (graphify не установлен) — работает только проход "
        "по AST: он отвечает «употреблено ли ИМЯ», а не «кто кого зовёт»",
        "невидимы: getattr, диспетчеризация по строке, строковая аннотация, "
        "вход по имени из C# или конфигурации",
        "«не зовётся изнутри» НЕ значит «не нужно»: пакет публикуется, и у него "
        "есть законные внешние потребители — см. род «публичное»",
        "дандеры исключены: их зовёт рантайм, по имени не зовёт никто",
    )
    refusal = ("интерпретатор %s не разобрал %d файл(ов): %s"
               % (out["interpreter"], len(out["unparsed"]),
                  ", ".join(out["unparsed"]))) if out["unparsed"] else ""
    try:
        from kir.instruments.measure_header import measure_header
    except Exception as exc:                                  # noqa: BLE001
        return ("🔴 ШАПКА ЗАМЕРА НЕДОСТУПНА: %s\n"
                "   (kir.instruments.measure_header — незакоммиченная чужая "
                "волна; дублировать его здесь запрещено)\n"
                "   источник: %s · прочитано модулей: %d · интерпретатор: %s\n"
                "   слепые пятна: %s%s"
                % (exc, out["root"], out["modules"], out["interpreter"],
                   " | ".join(blind),
                   "\n   ОТКАЗ: " + refusal if refusal else ""))
    return measure_header(source=out["root"], read=out["modules"],
                          note="   (модулей пакета без тестов)",
                          blind=blind, refusal=refusal)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="перечислить поимённо")
    parser.add_argument("--kind", choices=KINDS, help="только этот род")
    # 🔴 THE DEFAULT WAS REMOVED ON 28.08.2026: a package published
    # separately has no right to carry the address of someone else's
    # install (guarded by `test_authority_boundaries`). Without `--host`
    # (and without `KIR_HOST_ROOT`) the number remains an UPPER BOUND, and
    # this is already printed as a refusal — the behavior does not
    # change, only the guesswork disappears.
    parser.add_argument("--host", default=env.get("KIR_HOST_ROOT"),
                        help="дерево ПОТРЕБИТЕЛЯ пакета; без него число — "
                             "верхняя граница, и это печатается отказом. "
                             "Можно назвать переменной KIR_HOST_ROOT")
    args = parser.parse_args(argv[1:])

    try:
        out = census(host=pathlib.Path(args.host) if args.host else None)
    except UnwiredCensusError as exc:
        print("🔴 ОТКАЗ: %s" % exc)
        return 2

    if out["unparsed"]:
        # DISQUALIFICATION AT THE TOP, NOT AS A FOOTNOTE AT THE BOTTOM: a
        # number taken while a file went unread INFLATES the "not wired
        # in" count, and inflates it silently.
        print("🔴 ОТЧЁТ ДИСКВАЛИФИЦИРОВАН: интерпретатор %s не разобрал %d "
              "файл(ов) — %s.\n   Всякое имя, употреблённое ТОЛЬКО там, уедет "
              "в «не соединено» ЛОЖНО."
              % (out["interpreter"], len(out["unparsed"]),
                 ", ".join(out["unparsed"])))
        print()

    print(_header(out))
    print("модулей пакета (без тестов)      : %d" % out["modules"])
    print("тестовых модулей (не читались)   : %d" % out["test_modules"])
    print("определений (не дандеры)         : %d в %d уникальных имён"
          % (out["defined"], out["unique_names"]))
    print("имён в __all__                   : %d" % out["exported"])
    print("НЕ ЗОВЁТСЯ НИГДЕ В ПРОД-КОДЕ      : %d" % len(out["unwired"]))
    print("соединено, но только со СВОИМ модулем: %d  (это НЕ несоединённое —\n"
          "   приватный помощник своего класса нормален; число дано отдельно,\n"
          "   потому что среди них прячется полка, разговаривающая сама с собой)"
          % out["self_contained"])
    print()
    for kind in KINDS:
        print("   %-16s %d" % (kind, out["by_kind"].get(kind, 0)))

    hs = out["host_stat"]
    if not hs.get("present"):
        print()
        print("🔴 ПОТРЕБИТЕЛЬ НЕ СПРОШЕН (%s не каталог): число выше — ВЕРХНЯЯ\n"
              "   ГРАНИЦА. Внешняя поверхность пакета (handle_revit_ir, порты)\n"
              "   попадёт в «не зовётся» ЛОЖНО." % args.host)
    else:
        print()
        print("ВТОРОЙ КОРПУС: %s — модулей %d, не разобрано %d"
              % (hs["root"], hs["scanned"], len(hs["unparsed"])))
        for label in ("прод_хозяина", "тесты_хозяина", "никто"):
            print("   зовёт %-16s %d" % (label, out["by_host"].get(label, 0)))

    # 🔴 THE BREAKDOWN IS COMPUTED OVER THE SAME SET IT IS PRINTED UNDER.
    #
    # A DEFECT FOUND ON 27.08.2026, AND IT WAS NOT IN THE SCANNER BUT IN
    # THE REPORT. The previous version computed the breakdown over ALL 273
    # lines, but printed it right under the "nobody calls it: 179" block.
    # Every reader attributed it to that line — and TWO did, in a row, in
    # one evening, both of them careful readers.
    #
    # The price: `checker/fixtures/builders.py 16` read as "sixteen
    # fixtures nobody calls", whereas in "nobody" there are EXACTLY ZERO
    # of them — all sixteen are called by the host's tests, and the
    # scanner knew this. `bridge/client.py 8` lied the same way (one in
    # "nobody") and so did `serving.py 8` (two in "nobody").
    #
    # The instrument was RIGHT, the report was not. This is canon form
    # 24: the unit of MEASUREMENT and the unit of the REPORT are
    # different things, and the second can rot independently of the
    # first; no control on the instrument catches this, because the
    # instrument is correct.
    # And form 23: a statement has not only text but also a PLACE, and
    # the place is part of the statement.
    #
    # The fix is not "print more carefully" but COMPUTE THE SAME THING
    # YOU ARE SHOWING, and to name the subset in the heading so that
    # attributing it to the wrong line becomes impossible even on a
    # quick read.
    rows = out["unwired"]
    scope = "НЕ ЗОВЁТСЯ В ПРОД-КОДЕ KIR"
    if hs.get("present"):
        rows = [r for r in rows if r["host"] == "никто"]
        scope = "зовёт НИКТО (ни KIR, ни прод хозяина, ни его тесты)"
    if args.kind:
        rows = [r for r in rows if r["kind"] == args.kind]
        scope += " · род «%s»" % args.kind

    print()
    print("РАЗБИВКА ПО МОДУЛЯМ — подмножество «%s», строк %d" % (scope, len(rows)))
    by_module = collections.Counter(r["sites"][0][0] for r in rows)
    for path, count in by_module.most_common(20):
        print("   %-56s %d" % (path, count))

    in_scope = collections.Counter(r["kind"] for r in rows)
    if in_scope.get("по_построению"):
        print()
        print("   из них ПО ПОСТРОЕНИЮ (устройство, НЕ долг): %d"
              % in_scope["по_построению"])
        for row in sorted(rows, key=lambda r: r["name"]):
            if row["kind"] == "по_построению":
                print("      %-36s %s"
                      % (row["name"], BY_CONSTRUCTION_REASONS[row["why"]]))
        print("   ЧЕСТНЫЙ ДОЛГ: %d" % (len(rows) - in_scope["по_построению"]))

    if args.list:
        print()
        for row in sorted(rows, key=lambda r: (r["sites"][0][0], r["name"])):
            rel, line = row["sites"][0]
            print("   %-46s %-34s %s:%d"
                  % (row["kind"], row["name"], rel, line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
