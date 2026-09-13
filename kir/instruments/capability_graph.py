"""Reachability as a MACHINE question — an import graph over the sources.

WHY THIS FILE EXISTS (2026-08-03). A flag in `.env` was read as "the subsystem
is on in prod". `KUKAI_CHECKER_V2=1` is set on the live service and the code it
switches is reached by NOTHING: no router, no LLM tool, no systemd unit, no
timer, no cron. "The flag is set" and "the code runs" are two different facts,
and only the second one is a capability. A judgement about reachability goes
stale the moment somebody deletes a call site; a traversal does not.

So: no reading, no remembering, no `grep` by eye. Build the graph, walk it.

OPERATIONAL DEFINITION USED HERE
--------------------------------
A capability is REACHABLE iff a path of imports exists from a real process
entry point — declared by the HOST through the `tools.entry_points` port, never
by this package — to the module that reads its switch.
Import-reachability is a NECESSARY condition, not a sufficient one — see
BLIND_SPOTS at the bottom, which is part of the contract, not a disclaimer.

Tests are NOT entry points. That is the entire point: `kukai/modeling/` is
imported by its own tests and by nothing else in the live process, and calling
that "reachable" is the defect this file exists to kill.

NOTHING IS EXECUTED. The graph is built with `ast` over the source text, so a
module that crashes on import, needs a database, or needs a Revit bridge is
traversed exactly like any other.

EDGES THE WALK FOLLOWS (all of them are legitimate ways to connect code, and a
walk that missed any of them would be a walk people learn to distrust):
  * `import a.b.c`, `from a.b import c` — plus every parent package, which
    Python really does execute.
  * relative imports at any level (`from . import x`, `from ..y import z`).
  * LAZY imports inside function bodies. `kukai/main.py` imports all thirteen
    of its routers inside `create_app()`; a top-of-file-only scan would call
    the entire HTTP surface dead.
  * `importlib.import_module(...)` with a non-literal argument — the
    `_MODULE_MAP` indirection at `kukai/modules/registry.py:66`. Rule: if a
    module imports dynamically at all, every dotted string literal in it that
    names a real module in this tree becomes an edge. Over-connects rather
    than under-connects, deliberately: a false "reachable" is an annoyance, a
    false "dead" is how you delete working code.
  * f-string module paths — `f"kukai.norm_leaves.{m.name}"` at
    `kukai/norm_tree.py:176` sweeps a whole package via `pkgutil`. The literal
    prefix is resolved to the package and every submodule of it is linked.

STRUCTURE, NOT CONTENTS — a standing rule for anything that prints system state
------------------------------------------------------------------------------
**A tool that reports on the system prints its STRUCTURE by default, never its
CONTENTS.** A value appears only where the answer does not exist without it,
and then as a deliberate exception with a reason next to it.

This is not caution, it is scope. The question here is "can a running process
reach this code", and no value answers any part of it. Printing values anyway
gave the first draft of this report a live admin token, a database password and
the API keys, sitting in a file inside the repository tree. Redacting the
things that *look* like secrets then left the working model name, the internal
proxy address and the binary path — competitive and infrastructural detail,
leaked by a report that never needed it, in a project preparing to go open
source.

So the value column is gone, replaced by the only fact the law actually uses:
WHERE the flag is declared (`.env`, the example file, both, neither). Not even
"empty vs non-empty" survives — for an API key that single bit still discloses
whether a provider is configured, and it answers nothing about reachability.

Enforced, not remembered: `render_report` refuses to return text containing any
non-generic value from the production `.env` (`_assert_no_env_values`). One
gate covers stdout, the `-o` file, and the tests alike — a leak into somebody's
terminal scrollback or a CI log is no better than one into a file.

The rule governs what the tool PRINTS ABOUT THE SYSTEM. It is not a ban on
English: `shadow` is a local variable here and also, by coincidence, the value
of four flags, and a check that forbade the word would be switched off inside a
week. Nor does it touch a value a test must SET to drive the code under test
(`monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")`) — that is an input, not a
report.

🔴 ОБЕ ГРАНИЦЫ НЕ СТОРОЖИТ НИЧТО, И ЭТО СКАЗАНО ЗДЕСЬ, А НЕ ПОДРАЗУМЕВАЕТСЯ
(аудит 30.08.2026, E-29). Здесь стояло «Both boundaries are asserted in
`test_capability_reachability.py`». Такого файла в этом дереве НЕТ: он остался
в раскладке, из которой KIR вырезали, и грепом по всему пакету имя встречается
ТОЛЬКО в тексте этого модуля — четырежды. Обещанные ворота, которых нет, хуже
отсутствующих: читатель, поверив строке, не станет проверять то, что она
обещала. Границы держатся сегодня только чтением этого файла.

Run it:
    python tests/capability_graph.py                 # markdown to stdout
    python tests/capability_graph.py -o report.md    # …to a file
"""
from __future__ import annotations

import ast
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

# 🔴 2026-08-27: IT USED TO BE TWO STEPS UP, and that was correct while
# the file lived in `backend/tests/`. After the move to `kir/instruments/`
# the same two steps landed on the package itself — and module names came
# out as `live.journal` instead of `kir.live.journal`. The graph still
# BUILT and looked correct; only lookups by name broke (`KeyError:
# 'kir.live.journal'`), meaning the instrument lied not by refusal but by
# a miss. The root is the directory CONTAINING the package: that way the
# module name starts with `kir.`.
BACKEND = Path(__file__).resolve().parents[2]

#: Skipped at ANY depth. Deliberately short. An earlier version of this list
#: also held data-ish names like "data" and "knowledge" — and silently ate
#: `kukai/knowledge/` and `kukai/data/`, which are real packages, reporting
#: `KUKAI_RAG_WIKI_ROUTER` as having no reader at all. A too-eager skip list
#: manufactures exactly the false "dead" this file exists to prevent, so the
#: only names here are ones that can never contain importable source.
_SKIP_ANYWHERE = {"__pycache__", ".git", "node_modules", ".pytest_cache", "venv"}

#: Where source lives. `kukai` is the package; `tools`/`scripts` are loose
#: scripts (no `__init__.py`) and get synthetic dotted names. Non-source trees
#: (`data/`, `knowledge/`, `compile-service/`, …) are simply never walked.
# 🔴 2026-08-27: it used to be ("kukai", "tools", "scripts") — names of
# the PAST layout. After the split, the graph silently built EMPTY over
# these roots, and a lookup by name gave a KeyError. The instrument was
# not refusing — it was missing, and a miss reads as "no such module
# exists", that is, as a fact about the subject.
_SOURCE_ROOTS = ("kir",)

#: 🔴 ENTRY POINTS BELONG TO THE OWNER, NOT TO THIS PACKAGE (edit
#: 2026-09-01). A dictionary of four literals used to stand here — module
#: names and systemd unit names OF THE PRODUCT, checked against
#: `/etc/systemd/system` on 2026-08-03. It violated the owner's law ("KIR
#: is environment-agnostic") and was printed to every reader of the
#: package. Now the owner names them through the `ports.ENTRY_POINTS` port.
_PORT_NAME = "tools.entry_points"


def _entry_points() -> dict[str, str]:
    """The owner's entry points. Empty is a legitimate answer, and it SOUNDS below."""
    from kir import ports  # noqa: PLC0415 — the port is queried LAZILY
    supplier = ports.ask(ports.ENTRY_POINTS)
    if supplier is None:
        return {}
    got = supplier.entry_points() if hasattr(supplier, "entry_points") else supplier
    return dict(got or {})

#: Run by a human, never by the machine. Kept apart on purpose: "reachable only
#: if someone runs a script by hand" is a THIRD answer, and collapsing it into
#: either "live" or "dead" loses the thing the operator needs to know.
_MANUAL_ROOT_DIRS = ("scripts", "tools")

_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
#: 🔴 TWO FAMILIES, NOT ONE (audit 2026-08-29, E-29). Only `KUKAI_` used
#: to stand here — a name from the PAST layout that KIR was cut out of.
#: Measured against the package's sources: `KUKAI_*` names — 80, `KIR_*`
#: names — 47, and the mask let through NONE of the forty-seven. That is,
#: the KIR package's capability inventory did not see the KIR package's
#: own entries, while the report looked complete: what went missing was
#: not a line but a WHOLE KIND of finding — the `KIR_*` flag, declared and
#: read by nobody, was unreachable here IN PRINCIPLE.
#:
#: The list is CLOSED to two names on purpose. Widening the mask to any
#: `[A-Z]+_` would have pulled in `PATH`, `HOME`, `PYTHONPATH` — foreign
#: entries this package promises nothing about; a closed list of two
#: families is checkable.
_FLAG_NAME = re.compile(r"^(?:KUKAI|KIR)_[A-Z0-9_]+$")


# ── the module index ────────────────────────────────────────────────────────

def missing_source_roots(backend: Path) -> tuple[str, ...]:
    """Which declared source roots were NOT FOUND under this tree.

    🔴 The `_iter_source_files` traversal stays mute on purpose — it is a
    generator, and the reason lives with the CALLER (the same convention
    as `snapshot_pins._iter_python_files` + `scan_reach`). It needs to be
    asked here: "the root doesn't exist" and "there's no Python in the
    root" give an equally empty traversal, and reachability computed from
    an empty traversal is a fact ABOUT THE MACHINE.
    """
    return tuple(root for root in _SOURCE_ROOTS
                 if not (backend / root).is_dir())


def _iter_source_files(backend: Path) -> Iterator[Path]:
    for root in _SOURCE_ROOTS:
        base = backend / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if any(part in _SKIP_ANYWHERE for part in path.relative_to(backend).parts):
                continue
            yield path
    for path in backend.glob("*.py"):
        yield path


def _module_name(path: Path, backend: Path) -> str:
    rel = path.relative_to(backend).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass
class Module:
    name: str
    path: Path
    tree: ast.Module
    imports: set[str] = field(default_factory=set)          # static edges
    dynamic_imports: set[str] = field(default_factory=set)  # importlib/f-string
    #: flag name → line numbers where this module READS it
    flag_reads: dict[str, list[int]] = field(default_factory=dict)
    #: unresolved dynamic flag names (`f"KUKAI_{x}"`) — reported, never hidden
    flag_reads_unresolved: list[int] = field(default_factory=list)
    #: `def <name>_enabled()` defined here → line
    enabled_defs: dict[str, int] = field(default_factory=dict)
    #: flag → the `*_enabled()` function whose body reads it. THIS is what
    #: separates a capability switch from a tuning knob: `KUKAI_DB_POOL_MIN`
    #: changes a number, `KUKAI_CHECKER_V2` decides whether a subsystem exists.
    gate_flags: dict[str, str] = field(default_factory=dict)
    #: flag → the DEFAULT the gate falls back to when the variable is unset.
    #: An undeclared gate that defaults ON is a feature running in production
    #: with no trace of it in the configuration; one that defaults OFF is
    #: shelved code. Same "undeclared" verdict, opposite meaning.
    gate_defaults: dict[str, str] = field(default_factory=dict)
    #: every call `foo(...)` / `x.foo(...)` made anywhere in this module, with
    #: import aliases resolved back to the REAL name
    calls: set[str] = field(default_factory=set)
    #: names called inside the module that defines them
    self_calls: set[str] = field(default_factory=set)

    @property
    def is_test(self) -> bool:
        parts = self.name.split(".")
        return any(p == "tests" or p.startswith("test_") or p == "conftest"
                   for p in parts)


#: FORM 26 — AN INSTRUMENT MUST NAME ITS OWN CALL (paid for on 2026-08-15).
#:
#: This traversal DECOMPILES sources with whatever interpreter it is run
#: under, and so its answer is a function of TWO things: the tree and the
#: Python version. Measured on 15.08 on the same tree:
#:
#:     python3.10   1149 modules · 409 alive · 5 files not decompiled
#:     python3.12   1154 modules · 425 alive · 0 files not decompiled
#:
#: **Sixteen live modules were declared dead**, and among them
#: `authoring.py` — the emitter, i.e. the compiler's most imported code.
#: The cause is not in the code: PEP 701 allowed nested quotes in
#: f-strings starting with 3.12, and five files in the tree use them. The
#: previous edition printed this as a FOOTNOTE at the end of the report,
#: and the footnote additionally claimed "their Python doesn't import it
#: either" — an untruth: the live service imports all five.
#:
#: Hence three rules, and all three are enforced below, not promised:
#:   1. the report prints its own interpreter on the FIRST line;
#:   2. an undecompiled file is a NAMED REFUSAL, not a footnote;
#:   3. a report taken with a non-empty list of undecompiled files
#:      **disqualifies itself** — its numbers are not fit to be cited.
INTERPRETER = "%d.%d.%d" % sys.version_info[:3]

#: The minimum version on which the tree decompiles WHOLLY. Not a matter
#: of taste: below it `ast.parse` trips over PEP 701, and the traversal's
#: answer understates reachability. The number is CHECKED, not asserted:
#: `disqualified()` looks at the fact of the parse, not at this constant.
#: It is needed only for the refusal text.
MIN_INTERPRETER = (3, 12)


class UnparsableTreeError(RuntimeError):
    """The tree was NOT decompiled wholly — the traversal's numbers are invalid.

    Raised by those who need a FULL answer (the project map). The
    traversal itself does not raise it: a partial graph is legitimate for
    debugging, it is only illegitimate to PASS IT OFF as complete.
    """


class Graph:
    def __init__(self, backend: Path = BACKEND) -> None:
        self.backend = backend
        self.interpreter = INTERPRETER
        self.modules: dict[str, Module] = {}
        self.unparsable: list[Path] = []
        for path in _iter_source_files(backend):
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(path))
            except (SyntaxError, OSError, ValueError):
                # NOT "a file that Python doesn't import". This is a file
                # THIS interpreter FAILED TO DECOMPILE — different
                # statements, and the previous edition confused them in
                # favor of the pleasant one.
                self.unparsable.append(path)
                continue
            name = _module_name(path, backend)
            if name:
                self.modules[name] = Module(name=name, path=path, tree=tree)
        for mod in self.modules.values():
            self._scan(mod)

    def disqualified(self) -> str:
        """The reason this traversal's numbers CANNOT be cited. Empty —
        the traversal is complete.

        The answer rests on the FACT of the parse, not on a version
        comparison: an interpreter newer than the minimum that trips on
        new syntax must be caught the same way an older one is.
        """
        if not self.unparsable:
            return ""
        names = ", ".join(sorted(p.name for p in self.unparsable))
        return (
            "обход снят интерпретатором %s и НЕ РАЗОБРАЛ %d файл(ов): %s. "
            "Достижимость занижена: недостающий модуль неотличим от мёртвого. "
            "Перезапустить на %d.%d+ (PEP 701: вложенные кавычки в f-строках)."
            % (self.interpreter, len(self.unparsable), names,
               MIN_INTERPRETER[0], MIN_INTERPRETER[1]))

    def reachability_unmeasurable(self) -> str:
        """The reason there is nothing to compute a REACHABILITY SHARE from here.

        🔴 SEPARATE FROM `disqualified()`, AND THIS IS THE DECISIVE
        DISTINCTION. That one answers "the traversal is INCOMPLETE" — the
        instrument is broken, not a single number can be trusted. This one
        answers "the SUBJECT IS ABSENT": the traversal is complete and
        honest, but the entry points live in the product tree, and they
        can NEVER be found over the KIR package alone.

        The two cannot be merged into one gate: `canon_state._reachability`
        on `disqualified()` REFUSES to issue the state at all, and the
        language canon would stop building in its own tree. Verified by
        execution: the first edition of this fix dropped 5 canon tests and
        errored on 4.

        Caught by another person's gate on 2026-08-29: on a bare
        installation the report printed «Проиндексировано модулей: 838,
        достижимо из точек входа: 0 (0%)» — a plausible-looking
        catastrophic conclusion ABOUT THE LANGUAGE where it is really a
        fact ABOUT THE HOST. The `⚠ МОДУЛЬ НЕ НАЙДЕН` mark in the table
        was there and did not save it: it explains the LINE, while what
        stops the reader is the HEADER.
        """
        declared = _entry_points()
        if not declared:
            # 🔴 EMPTY IS NOT SILENCE. The previous edition returned "" here
            # and printed a reachability share out of an EMPTY set, i.e. a
            # zero indistinguishable from a dead tree.
            return (
                "ТОЧЕК ВХОДА НЕ ОБЪЯВЛЕНО: их называет хозяин портом "
                "«%s», и без него доля достижимости не считается вовсе. "
                "Обход при этом ПОЛОН — сломанного здесь ничего нет, и это "
                "факт О СРЕДЕ, а не о языке." % _PORT_NAME)
        if any(name in self.modules for name in declared):
            return ""
        return (
            "НИ ОДНА из %d объявленных точек входа не найдена в этом дереве "
            "(%s). Доля достижимости ниже есть факт О ХОСТЕ, а не о языке: "
            "точки входа принадлежат дереву продукта, и обход над одним "
            "пакетом KIR их не увидит никогда. Обход при этом ПОЛОН — "
            "сломанного здесь ничего нет."
            % (len(declared), ", ".join(sorted(declared))))

    def require_complete(self) -> None:
        """Refuse if the tree was not decompiled wholly. For those who need
        a full answer: a partial map looks complete, and decisions get made from it."""
        why = self.disqualified()
        if why:
            raise UnparsableTreeError(why)

    # -- per-module AST scan ------------------------------------------------
    def _scan(self, mod: Module) -> None:
        consts = _module_level_strings(mod.tree)
        pkg = mod.name if mod.path.name == "__init__.py" else mod.name.rpartition(".")[0]
        dynamic = _uses_dynamic_import(mod.tree)
        aliases = _import_aliases(mod.tree)

        for node in ast.walk(mod.tree):
            # ---- static imports (top-level AND lazy — `ast.walk` sees both)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod.imports |= self._resolve(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = _relative_base(pkg, node.level, node.module)
                if base is None:
                    continue
                mod.imports |= self._resolve(base)
                for alias in node.names:
                    if alias.name != "*":
                        mod.imports |= self._resolve(f"{base}.{alias.name}")

            # ---- dynamic imports built from an f-string prefix
            elif isinstance(node, ast.JoinedStr) and dynamic:
                mod.dynamic_imports |= self._resolve_prefix(_joinedstr_prefix(node))

            # ---- calls: flag reads, and the call census for `*_enabled()`
            elif isinstance(node, ast.Call):
                called = _call_name(node)
                # `from … import revit_ir_enabled as _kir_enabled` then
                # `if _kir_enabled():` — without this the two capabilities the
                # panel actually gates read as "called by nobody".
                mod.calls.add(called)
                mod.calls.add(aliases.get(called, called))
                arg = node.args[0] if node.args else None
                flag = _as_flag(arg, consts)
                if flag:
                    mod.flag_reads.setdefault(flag, []).append(node.lineno)
                elif isinstance(arg, ast.JoinedStr) and \
                        (_joinedstr_prefix(arg) or "").startswith("KUKAI_"):
                    mod.flag_reads_unresolved.append(node.lineno)

            # ---- os.environ["KUKAI_X"]
            elif isinstance(node, ast.Subscript):
                if _is_environ(node.value):
                    flag = _as_flag(node.slice, consts)
                    if flag:
                        mod.flag_reads.setdefault(flag, []).append(node.lineno)

            # ---- `def foo_enabled()` / `def enabled()` / `def is_enabled()`
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ("enabled", "is_enabled") or node.name.endswith("_enabled"):
                    mod.enabled_defs[node.name] = node.lineno

        if dynamic:
            for text in _string_constants(mod.tree):
                if _DOTTED.match(text) and text in self.modules:
                    mod.dynamic_imports.add(text)

        mod.self_calls = mod.calls & set(mod.enabled_defs)

        # second pass, scoped: which flag does each gate FUNCTION consult?
        for node in ast.walk(mod.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in mod.enabled_defs:
                continue
            for inner in ast.walk(node):
                flag, default = None, None
                if isinstance(inner, ast.Call) and inner.args:
                    flag = _as_flag(inner.args[0], consts)
                    if len(inner.args) > 1 and isinstance(inner.args[1], ast.Constant):
                        default = str(inner.args[1].value)
                elif isinstance(inner, ast.Subscript) and _is_environ(inner.value):
                    flag = _as_flag(inner.slice, consts)
                if flag:
                    mod.gate_flags.setdefault(flag, node.name)
                    if default is not None:
                        mod.gate_defaults.setdefault(flag, default)

    # -- name resolution ----------------------------------------------------
    def _resolve(self, dotted: str) -> set[str]:
        """`a.b.c` → every prefix of it that is a real module here.

        Parents included because importing `a.b.c` executes `a/__init__.py`
        and `a/b/__init__.py` too — code reached that way is reached.
        """
        out: set[str] = set()
        parts = dotted.split(".")
        for i in range(1, len(parts) + 1):
            cand = ".".join(parts[:i])
            if cand in self.modules:
                out.add(cand)
        return out

    def _resolve_prefix(self, prefix: str | None) -> set[str]:
        """`f"kukai.norm_leaves.{name}"` → the package and all its submodules."""
        if not prefix:
            return set()
        pkg = prefix.rstrip(".")
        if not pkg or pkg not in self.modules:
            return set()
        return {pkg} | {m for m in self.modules if m.startswith(pkg + ".")}

    # -- traversal ----------------------------------------------------------
    def edges(self, name: str) -> set[str]:
        mod = self.modules.get(name)
        return (mod.imports | mod.dynamic_imports) if mod else set()

    def reachable(self, roots: Iterable[str]) -> dict[str, list[str]]:
        """BFS. Returns module → the shortest import path from a root."""
        paths: dict[str, list[str]] = {}
        queue: deque[str] = deque()
        for r in roots:
            if r in self.modules and r not in paths:
                paths[r] = [r]
                queue.append(r)
        while queue:
            cur = queue.popleft()
            for nxt in sorted(self.edges(cur)):
                if nxt not in paths:
                    paths[nxt] = paths[cur] + [nxt]
                    queue.append(nxt)
        return paths

    # -- convenience --------------------------------------------------------
    def live(self) -> dict[str, list[str]]:
        """Modules the running production process can reach."""
        if not hasattr(self, "_live"):
            self._live = self.reachable(_entry_points())
        return self._live

    def manual_roots(self) -> list[str]:
        return sorted(
            m for m in self.modules
            if m.split(".")[0] in _MANUAL_ROOT_DIRS and m not in _entry_points()
        )

    def module_classes(self) -> tuple[set[str], set[str], set[str]]:
        """THREE classes over the non-test sources, never two. Added 2026-08-09.

        The flag inventory above already knows the distinction (`LIVE` /
        `MANUAL-ONLY` / `DEAD`) but only ever applies it to FLAGS. The same
        three-way answer about MODULES had no home, so `kukai/clash/` — 3 294
        lines, 135 tests, zero importers outside itself — was invisible to
        every ratchet in this repo. It is computed here, next to the walk that
        answers it, so the test does not grow a second traversal.

        Returns `(live, manual_only, dark)`, a partition:

        * **live** — a path of imports runs from a real service entry point.
        * **manual_only** — no such path, but a hand-run root under
          `scripts/`/`tools/` reaches it. A measuring instrument nobody wired
          into the service is doing exactly what it was built for; calling it
          dead would teach people to distrust the word.
        * **dark** — neither. THIS is the set that owes an explanation.

        The boundary is stated because it bites: `manual_roots()` matches on
        the TOP-LEVEL directory, so a hand-run CLI living inside the package
        (`python -m kir.decompile.axes_census`) lands in `dark` even
        though it is morally manual-only. Widening the rule here would move
        flag verdicts too, so the honest fix is a ledger entry that says so —
        not a quieter instrument.
        """
        non_test = {n for n, m in self.modules.items() if not m.is_test}
        live = set(self.live()) & non_test
        manual_only = (set(self.reachable(self.manual_roots())) & non_test) - live
        return live, manual_only, non_test - live - manual_only

    def readers_of(self, flag: str) -> dict[str, list[int]]:
        return {m.name: lines for m in self.modules.values()
                if (lines := m.flag_reads.get(flag))}

    def callers_of(self, func: str, defined_in: str) -> set[str]:
        """Modules that call `func` AND import the module that defines it.

        The import requirement matters: bare names like `enabled()` and
        `is_enabled()` repeat across the tree, and matching on the name alone
        credits `turn_progress.enabled` with `turn_ledger`'s callers. Requiring
        the edge costs nothing and stops the table from lying upward.
        """
        out = set()
        for m in self.modules.values():
            if func in m.calls and (defined_in in m.imports
                                    or defined_in in m.dynamic_imports):
                out.add(m.name)
        return out

    def gate_readers(self) -> dict[str, list[tuple[str, str]]]:
        """flag → [(module, gate function)] for flags consulted by a `*_enabled()`."""
        out: dict[str, list[tuple[str, str]]] = {}
        for m in self.modules.values():
            if m.is_test:
                continue
            for flag, fn in m.gate_flags.items():
                out.setdefault(flag, []).append((m.name, fn))
        return out

    def gate_default(self, flag: str) -> str | None:
        for m in self.modules.values():
            if not m.is_test and flag in m.gate_defaults:
                return m.gate_defaults[flag]
        return None


#: Defaults that mean "off". Everything else means the gate is OPEN when the
#: variable is absent — which for an undeclared flag means the feature is live
#: in production and invisible in the configuration.
OFF_DEFAULTS = {"", "0", "false", "off", "no", "none"}


def default_is_on(default: str | None) -> bool | None:
    if default is None:
        return None
    return default.strip().lower() not in OFF_DEFAULTS


# ── AST helpers ─────────────────────────────────────────────────────────────

def _module_level_strings(tree: ast.Module) -> dict[str, str]:
    """`_FLAG = "KUKAI_TURN_LEDGER"` — the name later handed to `os.getenv`."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
            out[node.target.id] = node.value.value
    return out


def _string_constants(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """local name → real name, for `from x import real as local`."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    out[alias.asname] = alias.name.rpartition(".")[2] or alias.name
    return out


def _uses_dynamic_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in {
                "import_module", "__import__", "load_module", "exec_module"}:
            return True
    return False


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _joinedstr_prefix(node: ast.JoinedStr) -> str | None:
    if node.values and isinstance(node.values[0], ast.Constant) \
            and isinstance(node.values[0].value, str):
        return node.values[0].value
    return None


def _is_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return True
    return isinstance(node, ast.Name) and node.id == "environ"


def _as_flag(node: ast.AST | None, consts: dict[str, str]) -> str | None:
    """A `KUKAI_*` name, whether written inline or held in a module constant.

    Only the FIRST positional argument of a call counts, so a tuple of names or
    a dict key that merely mentions a flag is not mistaken for reading it. This
    also picks up every local wrapper — `_env_float("KUKAI_WIKI_W_DOMAIN", 2.0)`,
    `_int_env_chat("KUKAI_CHAT_IMAGE_MAX_KB", 400)` — without enumerating them.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    elif isinstance(node, ast.Name):
        text = consts.get(node.id, "")
    else:
        return None
    return text if _FLAG_NAME.match(text) else None


def _relative_base(pkg: str, level: int, module: str | None) -> str | None:
    if not level:
        return module
    parts = pkg.split(".") if pkg else []
    if level - 1 > len(parts):
        return None
    base = parts[: len(parts) - (level - 1)]
    if module:
        base = base + module.split(".")
    return ".".join(base) or None


# ── declared surface: .env files and pydantic Settings ──────────────────────

def missing_env_files(backend: Path) -> tuple[str, ...]:
    """Which variable DECLARATION files were not found under this tree.

    🔴 THE COMPANION of `parse_env_file`. That one returns `{}` for a
    missing file, and the answer must not be dropped: the inventory must
    assemble even without `.env`. But an empty dict means "no
    declarations", and that is NOT the same as "no file".

    The cost is narrow and precise: flag names arrive in the report from
    THREE sources — `.env`, `.env.example`, and a flag being read in code.
    A flag that IS READ will be found even without the files. What is lost
    is exactly the one that is DECLARED and READ BY NOBODY — that is, the
    `NO_READER` case this instrument was written for. What silently
    disappears is not a report line but a whole KIND of finding.

    For the other person, `.env` is ALWAYS absent (gate measurement
    2026-08-29), so here this is not an edge case but the ordinary state.
    """
    return tuple(name for name in (".env", ".env.example")
                 if not (backend / name).exists())


def settings_classes_absent(graph: "Graph") -> str:
    """An empty string if the tree has at least one `BaseSettings` class;
    otherwise — the REASON in words.

    🔴 THE FORMULA'S FOURTH TERM WAS SILENT (audit 2026-08-29, E-29). The
    report prints «код ∪ `.env` ∪ `.env.example` ∪ Settings» and speaks,
    via the header, about TWO of the four empty sources
    (`missing_env_files`), about the fifth failed one in a separate block
    (`reachability_unmeasurable`), and says nothing at all about the third
    empty one. The reader sees a formula with four terms and concludes
    that all four were checked.

    Measured 2026-08-29: across the whole package `BaseSettings` occurs in
    ONE file — this very parser — and there are NO subclasses of it at
    all. So the term contributes zero ALWAYS, by construction.

    The cost is the same as for `.env`, and it is the same class already
    closed in `parse_env_file`: what disappears is not a report line but a
    KIND of finding. A flag declared as a `Settings` field and read by
    nobody is `NO_READER`, the very thing this instrument was written for,
    and here it is invisible twice over.

    What is asked is the CLASS, not a substring: the word `BaseSettings`
    also appears in this very module (in the base comparison and in
    docstrings), and a text-based check would go green off its own
    source — the instrument would be testifying about itself.
    """
    for mod in graph.modules.values():
        for node in ast.walk(mod.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for b in node.bases}
            if "BaseSettings" in bases:
                return ""
    return ("классов `BaseSettings` в этом дереве нет ни одного — четвёртое "
            "слагаемое формулы «код ∪ `.env` ∪ `.env.example` ∪ Settings» "
            "вносит ноль ПО ПОСТРОЕНИЮ. Это факт О ДЕРЕВЕ (KIR — пакет без "
            "pydantic-настроек), а не о флагах: флаг, объявленный полем "
            "`Settings` и никем не читаемый, отсюда не виден вовсе")


def parse_env_file(path: Path) -> dict[str, str]:
    """`KUKAI_X=value` → {X: value}. Commented-out lines are NOT declarations."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if _FLAG_NAME.match(key):
            out[key] = val.strip()
    return out


def _env_prefix(cls: ast.ClassDef) -> str | None:
    """`model_config = {"env_prefix": "KUKAI_"}` or `class Config: env_prefix=…`."""
    for node in ast.walk(cls):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "env_prefix" \
                        and isinstance(v, ast.Constant) and isinstance(v.value, str):
                    return v.value
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "env_prefix":
                    return node.value.value
    return None


def settings_flags(graph: "Graph") -> dict[str, list[tuple[str, int]]]:
    """Flags declared by a pydantic `BaseSettings` field rather than by a string.

    `env_prefix = "KUKAI_"` means the field `llm_timeout` IS the flag
    `KUKAI_LLM_TIMEOUT`, and that name appears NOWHERE in the source. Skipping
    this would report `KUKAI_HOST` and `KUKAI_DATABASE_URL` as unread.

    Attributed to the DEFINING module, never to a hard-coded `kukai.config`.
    That distinction is load-bearing: `kukai/llm/config.py` is a stale copy of
    the same class that nothing imports, so the flags only it declares —
    `KUKAI_LLM_REASONING_EFFORT` among them — are dead, and pinning the scan to
    one well-known module would have called them live.
    """
    out: dict[str, list[tuple[str, int]]] = {}
    for mod in graph.modules.values():
        for node in ast.walk(mod.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for b in node.bases}
            if "BaseSettings" not in bases:
                continue
            prefix = _env_prefix(node)
            if not prefix:
                continue
            for stmt in node.body:
                target = None
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    target = stmt.target.id
                elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                        and isinstance(stmt.targets[0], ast.Name):
                    target = stmt.targets[0].id
                if target and not target.startswith("_") and target != "model_config":
                    out.setdefault(f"{prefix}{target.upper()}", []).append(
                        (mod.name, stmt.lineno))
    return out


# ── the inventory ───────────────────────────────────────────────────────────

LIVE, MANUAL, DEAD, NO_READER = "LIVE", "MANUAL-ONLY", "DEAD", "NO-READER"

def declared_as(row: "FlagRow") -> str:
    """WHERE the flag is declared — the only thing about it the law consumes.

    Replaces the old value column outright. "Declared in the production `.env`"
    and "promised by the example file only" are different claims about a
    capability; what the value happens to be is a different question, asked
    somewhere else, by someone who has already opened the file.
    """
    if row.in_env and row.in_example:
        return "`.env` + образец"
    if row.in_env:
        return "`.env`"
    if row.in_example:
        return "только образец"
    return "нигде"


#: Values too generic to identify anything: booleans, wildcards, plain numbers.
#: They are skipped by the leak check because `1` and `true` occur throughout
#: ordinary prose and would make the check unusable — and because neither
#: carries configuration a reader could not have guessed. Stated here rather
#: than left implicit: this IS the boundary of the guarantee.
_GENERIC_VALUES = {"0", "1", "true", "false", "on", "off", "yes", "no", "*", ""}
_PLAIN_NUMBER = re.compile(r"^\d+(\.\d+)?$")


#: A value that is just a lowercase-ish word (`shadow`, `stage2`, `medium`) is
#: indistinguishable from an ordinary identifier or an English word. In OUTPUT
#: that ambiguity does not arise — the report has no business emitting it
#: either way — but in SOURCE it does, so `only_distinctive` skips them and the
#: check says plainly that it cannot speak about that class.
_BARE_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def env_value_leaks(text: str, backend: Path,
                    *, only_distinctive: bool = False) -> list[str]:
    """Flags whose production value appears verbatim in `text`.

    Word-bounded so a value like `shadow` is not "found" inside an unrelated
    identifier such as `capability_shadow_enabled` — a check that cried wolf
    would be switched off within a week, and then it would guard nothing.

    `only_distinctive=True` narrows to values no one would type by accident —
    anything carrying `/ : , @` or longer than 16 characters, i.e. model names,
    URLs, paths, provider lists, tokens. Use it on SOURCE, where a bare word
    may honestly be a variable name; use the strict form on anything PRINTED.
    """
    leaks: list[str] = []
    for flag, value in parse_env_file(backend / ".env").items():
        if value.lower() in _GENERIC_VALUES or _PLAIN_NUMBER.match(value):
            continue
        if only_distinctive and _BARE_WORD.match(value) and len(value) <= 16:
            continue
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text):
            leaks.append(flag)
    return sorted(leaks)


def _assert_no_env_values(text: str, backend: Path) -> str:
    """The gate every rendered byte passes through, including stdout.

    A leak into somebody's terminal scrollback or CI log is no better than a
    leak into a file, so this sits in the renderer rather than at the call
    sites — there is no path to output that can forget it.
    """
    leaks = env_value_leaks(text, backend)
    if leaks:
        raise RuntimeError(
            "отчёт содержит значения из .env: " + ", ".join(leaks) +
            ". Инструмент печатает СТРУКТУРУ, а не СОДЕРЖИМОЕ — убрать значение "
            "либо, если без него ответа нет, вписать осознанное исключение.")
    return text


@dataclass
class FlagRow:
    flag: str
    verdict: str
    value: str | None            # as set in prod .env, if declared there
    in_env: bool
    in_example: bool
    readers: dict[str, list[int]]
    path: list[str] | None       # import path from an entry point, if LIVE
    where: str                   # file:line of the reader that decides the verdict
    via_settings: bool = False

    @property
    def declared(self) -> bool:
        return self.in_env or self.in_example

    @property
    def short_path(self) -> str:
        if not self.path:
            return "—"
        if len(self.path) <= 3:
            return " → ".join(self.path)
        return f"{self.path[0]} → … ({len(self.path) - 2}) … → {self.path[-1]}"


def build_inventory(graph: "Graph | None" = None) -> tuple["Graph", list[FlagRow]]:
    graph = graph or Graph()
    live = graph.live()
    manual = graph.reachable(graph.manual_roots())
    env = parse_env_file(graph.backend / ".env")
    example = parse_env_file(graph.backend / ".env.example")
    settings = settings_flags(graph)

    names = set(env) | set(example) | set(settings)
    for mod in graph.modules.values():
        names |= set(mod.flag_reads)

    rows: list[FlagRow] = []
    for flag in sorted(names):
        readers = graph.readers_of(flag)
        prod = {m: l for m, l in readers.items() if not graph.modules[m].is_test}
        for mod_name, lineno in settings.get(flag, ()):
            prod.setdefault(mod_name, []).append(lineno)
        live_readers = [m for m in prod if m in live]
        manual_readers = [m for m in prod if m in manual]
        if live_readers:
            # the reader nearest an entry point — the one the operator should look at
            primary = min(live_readers, key=lambda m: len(live[m]))
            verdict, path = LIVE, live[primary]
        elif manual_readers:
            verdict, path, primary = MANUAL, None, sorted(manual_readers)[0]
        elif prod:
            verdict, path, primary = DEAD, None, sorted(prod)[0]
        else:
            verdict, path, primary = NO_READER, None, None

        if primary is None:
            where = "—"
        else:
            rel = graph.modules[primary].path.relative_to(graph.backend)
            extra = f" (+{len(prod) - 1})" if len(prod) > 1 else ""
            tag = " [Settings]" if any(m == primary for m, _ in settings.get(flag, ())) \
                else ""
            where = f"{rel}:{min(prod[primary])}{extra}{tag}"

        rows.append(FlagRow(
            flag=flag, verdict=verdict, value=env.get(flag), in_env=flag in env,
            in_example=flag in example, readers=prod, path=path, where=where,
            via_settings=flag in settings,
        ))
    return graph, rows


# ── what the walk cannot see. Stated up front, not buried. ──────────────────

BLIND_SPOTS = [
    "* **Импорт ≠ вызов.** Достижимость по импортам НЕОБХОДИМА, но не достаточна: "
    "модуль может быть импортирован, а функция под гейтом — не вызвана ни разу. "
    "Обход отвечает на «может ли управление сюда дойти», а не «доходит ли». "
    "Достаточность добирал бы живой набор панели — 🔴 но его в этом дереве "
    "НЕТ: `test_capability_reachability.py` остался в раскладке, из которой "
    "KIR вырезали (проверено грепом 30.08.2026: имя встречается только в "
    "тексте самого прибора). Значит достаточность СЕГОДНЯ НЕ ДОБИРАЕТ НИКТО, "
    "и это слепое пятно, а не ссылка на чужую работу.",
    "* **Мёртвая ветка внутри живого модуля.** `if False:` вокруг вызова "
    "обход не заметит: модуль-то импортирован.",
    "* **Конфигурация вне кода.** Строка в `nginx`, задание в чужом кроне, вызов "
    "по HTTP из клиента Revit — вне графа Python. Точки входа перечислены руками "
    "(`ENTRY_POINTS`) и сверены с `/etc/systemd/system`; новый юнит нужно вписать "
    "туда, иначе обход объявит его код мёртвым.",
    "* **`getattr`-диспетчеризация.** Если код зовут через `getattr(mod, name)`, "
    "ребро импорта до `mod` обход видит, а до конкретной функции — нет.",
    "* **Слой C#.** Мост, `checker/extractor.cs`, `scripts/op_revit.py` — свой мир; "
    "обход по `.py` там ничего не доказывает.",
    "* **Флаг, влияющий на ЧУЖОЙ процесс.** `KUKAI_CODEXPROXY_*` частью читает "
    "backend, частью — сторонний `cli-proxy-api`; вторую половину граф не видит.",
    "* **Значение флага не толкуется.** `=0` и `=1` одинаково «заявлены»; "
    "обход отвечает на достижимость кода, а не на то, что флаг сейчас включён.",
    "* **Умолчание гейта читается только вторым аргументом** "
    "(`os.getenv(FLAG, \"1\")`). Гейт, который ветвится на `None` "
    "(`kukai/rag/phrasings.py:182`), помечен «не разобрано» — не угадан.",
]

#: Why the awkward edges are not optional, measured rather than argued: a walk
#: that followed only top-of-file imports reached 42 modules where the full one
#: reaches 330. It would have called seven eighths of the running system dead
#: and passed every other test in the suite while doing it.
GUARD_NOTE = [
    "🔴 САМ ОБХОД СЕГОДНЯ НЕ ЗАПЕРТ НИЧЕМ. Ниже перечислено, чем он был "
    "заперт ДО разреза, — в файле `tests/test_capability_reachability.py`, "
    "которого в дереве KIR НЕТ (проверено грепом 30.08.2026). Список "
    "оставлен: он говорит, какие рёбра обход обязан видеть, и это знание "
    "дороже молчания. Но читать его надо как ТРЕБОВАНИЕ К БУДУЩЕМУ СТОРОЖУ, "
    "а не как отчёт о существующем:",
    "",
    "* `test_the_walk_still_sees_every_edge_it_claims_to_see` — пришпиливает "
    "ленивый импорт (`kukai.api.chat_http` из `create_app`), динамический "
    "`importlib` (`kukai.audit`, `kukai.commands` — иначе недостижимы) и "
    "подметание пакета f-строкой (`kukai.norm_leaves.*`). Замер: обход только "
    "по импортам верхнего уровня даёт **42** живых модуля вместо **330**, то "
    "есть «упрощение» объявило бы мёртвыми семь восьмых работающей системы — "
    "и прошло бы все остальные тесты файла.",
    "* `test_tests_are_not_an_entry_point` — свойство, на котором держится "
    "весь ответ: тест не является точкой входа. Иначе `KUKAI_CHECKER_V2` снова "
    "стал бы «достижимым», теперь уже с авторитетом машины.",
    "* `test_the_dead_list_does_not_rot` — строка исключения удаляется в тот "
    "день, когда перестаёт быть правдой.",
]


# ── report ──────────────────────────────────────────────────────────────────

def _table(rows: list[FlagRow], show_value: bool = True) -> list[str]:
    if show_value:
        out = ["| флаг | объявлен | достижим? | читается в | путь от точки входа |",
               "|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| `{r.flag}` | {declared_as(r)} | {r.verdict} "
                       f"| {r.where} | {r.short_path} |")
    else:
        out = ["| флаг | достижим? | читается в |", "|---|---|---|"]
        for r in rows:
            out.append(f"| `{r.flag}` | {r.verdict} | {r.where} |")
    if len(out) == 2:
        return ["_пусто_"]
    return out


def render_report(graph: "Graph", rows: list[FlagRow]) -> str:
    from datetime import date
    live = graph.live()
    L: list[str] = []

    L += ["# ИНВЕНТАРЬ СПОСОБНОСТЕЙ — достижимость снята обходом", "",
          f"Сгенерировано `tests/capability_graph.py` {date.today().isoformat()} "
          f"**интерпретатором Python {graph.interpreter}**, разобрано "
          f"{len(graph.modules)} модулей, не разобрано {len(graph.unparsable)}. "
          "Ничего не исполнялось: граф построен `ast` по исходникам.", "",
          "🔴 **ВЫЗОВ ЕСТЬ ЧАСТЬ ОТВЕТА.** Обход разбирает исходники тем "
          "интерпретатором, под которым запущен, поэтому число без версии "
          "Python — не число. Замер 15.08 на ОДНОМ дереве: 3.10 дал "
          "1149/409 при пяти неразобранных файлах, 3.12 — 1154/425 при нуле. "
          "Шестнадцать живых модулей были объявлены мёртвыми, среди них "
          "`authoring.py`.", ""]

    # THE REFUSAL STANDS AT THE TOP AND DISQUALIFIES THE WHOLE REPORT. The
    # previous edition printed this as a footnote at the end — both the
    # footnote and its place equally invited reading the numbers as valid.
    _why = graph.disqualified()
    if _why:
        L += ["> 🔴🔴🔴 **ЭТОТ ОТЧЁТ ДИСКВАЛИФИЦИРОВАН И ЦИТИРОВАНИЮ НЕ "
              "ПОДЛЕЖИТ.**", ">",
              f"> {_why}", ">",
              "> Числа ниже занижают достижимость на неизвестную величину: "
              "модуль, которого нет в графе, неотличим от модуля без "
              "импортёров. Это ОТКАЗ ПРИБОРА, а не находка о продукте.", ""]

    # 🔴 UNFOUND ROOTS ARE NAMED SEPARATELY FROM THE ENTRY POINTS: "there
    # was nothing to traverse" and "we traversed, found no entry points"
    # are different facts, and the first explains the second. Caught by
    # its own ratchet on 2026-08-29: the function had been written and WAS
    # CALLED BY NOBODY (E-7).
    # 🔴 DECLARATIONS THAT WERE NOT READ ARE NAMED BEFORE THE FLAG TABLE:
    # without these files, what disappears from the report is not a line
    # but a KIND of finding — a flag declared and read by NOBODY.
    _no_env = missing_env_files(BACKEND)
    if _no_env:
        L += [f"> 🔴 **ФАЙЛОВ ОБЪЯВЛЕНИЙ НЕТ: {', '.join(_no_env)}.** Флаги "
              f"ниже собраны только по ЧТЕНИЮ в коде; объявленный и не "
              f"читаемый никем отсюда не виден вовсе.", ""]

    # 🔴 THE FORMULA'S FOURTH SOURCE IS NAMED IN THE SAME PLACE AS THE
    # SECOND AND THIRD (E-29). `.env` is spoken of a line above; nothing
    # was ever said about Settings — even though it is empty by
    # construction.
    _no_settings = settings_classes_absent(graph)
    if _no_settings:
        L += [f"> 🔴 **ОБЪЯВЛЕНИЙ ЧЕРЕЗ `Settings` НЕТ:** {_no_settings}.", ""]

    _no_roots = missing_source_roots(BACKEND)
    if _no_roots:
        L += [f"> 🔴 **КОРНИ ИСХОДНИКОВ НЕ НАЙДЕНЫ: {', '.join(_no_roots)}.** "
              f"Обход шёл по дереву, где их нет; всё, что ниже, снято с того, "
              f"что осталось.", ""]

    _unmeasurable = graph.reachability_unmeasurable()
    if _unmeasurable:
        L += ["> 🔴 **ДОЛЮ ДОСТИЖИМОСТИ ЗДЕСЬ СЧИТАТЬ НЕ ОТ ЧЕГО.**", ">",
              f"> {_unmeasurable}", ">",
              "> Число ниже читать как «не измерено», а не как «мертво».", ""]

    L += ["## Точки входа (называет ХОЗЯИН портом `%s`)" % _PORT_NAME, "",
          "| модуль | чем запускается |", "|---|---|"]
    for name, how in sorted(_entry_points().items()):
        warn = "" if name in graph.modules else "  ⚠ МОДУЛЬ НЕ НАЙДЕН"
        L.append(f"| `{name}` | {how}{warn} |")
    # 🔴 A SHARE OF AN EMPTY SET IS NOT PRINTED AT ALL: "0 (0%)" next to a
    # caveat still reads as a verdict on the tree — people see the header,
    # not always the caveat. The promise is made earlier in the text, and
    # printing the number after it would mean lying with one's own prose.
    if not _entry_points():
        L += ["", f"Проиндексировано модулей: **{len(graph.modules)}**; "
                  f"доля достижимости НЕ СЧИТАЕТСЯ: точек входа не объявлено "
                  f"(порт `{_PORT_NAME}`).", ""]
    else:
        L += ["", f"Проиндексировано модулей: **{len(graph.modules)}**, "
                  f"достижимо из точек входа: **{len(live)}** "
                  f"({100 * len(live) // max(len(graph.modules), 1)}%).", ""]

    declared = [r for r in rows if r.declared]
    L += ["## Счёт", "", "| | штук |", "|---|---|",
          f"| флагов известно всего (код ∪ `.env` ∪ `.env.example` ∪ Settings) | {len(rows)} |",
          # 🔴 THE BREAKDOWN IS MANDATORY (E-29). The mask was widened
          # from `KUKAI_` to `KUKAI_|KIR_`, and the count grew because of
          # it. Without the breakdown, the growth would read as "there are
          # now MORE flags", i.e. an edit to the INSTRUMENT would look
          # like a change in the SUBJECT — exactly the substitution this
          # whole report was set up against.
          f"| — из них семейства `KIR_*` | "
          f"{sum(1 for r in rows if r.flag.startswith('KIR_'))} |",
          f"| — из них семейства `KUKAI_*` | "
          f"{sum(1 for r in rows if r.flag.startswith('KUKAI_'))} |",
          f"| **ЗАЯВЛЕНО** в `.env`/`.env.example` | {len(declared)} |",
          f"| — из них ДОСТИЖИМО | {sum(1 for r in declared if r.verdict == LIVE)} |",
          f"| — из них МЁРТВО (читатель есть, вход не ведёт) | "
          f"{sum(1 for r in declared if r.verdict == DEAD)} |",
          f"| — из них ТОЛЬКО ИЗ РУЧНОГО СКРИПТА | "
          f"{sum(1 for r in declared if r.verdict == MANUAL)} |",
          f"| — из них БЕЗ ЧИТАТЕЛЯ (имени нет в коде вовсе) | "
          f"{sum(1 for r in declared if r.verdict == NO_READER)} |",
          f"| НЕ заявлено, код читает, и он ЖИВОЙ | "
          f"{sum(1 for r in rows if not r.declared and r.verdict == LIVE)} |", ""]

    L += ["## 1. ЗАЯВЛЕНО и НЕ ДОСТИЖИМО — это и есть находки", "",
          "🔴 Каждая строка ОБЯЗАНА БЫЛА стоять в `EXPECTED_UNREACHABLE` "
          "с причиной текстом — но ни этого имени, ни файла "
          "`test_capability_reachability.py` в дереве KIR НЕТ (проверено "
          "грепом 30.08.2026: единственное вхождение `EXPECTED_UNREACHABLE` "
          "во всём пакете — эта самая строка, то есть обещание ссылается на "
          "себя). Пустой раздел ниже означает «прибор не нашёл», а НЕ "
          "«сторож подтвердил». Строки ниже не красит сегодня ничто, "
          "и в этом вся находка.", ""]
    L += _table([r for r in declared if r.verdict != LIVE])
    L.append("")

    L += ["## 2. Заявлено и достижимо", ""]
    L += _table([r for r in declared if r.verdict == LIVE])
    L.append("")

    gates = graph.gate_readers()
    undeclared = [r for r in rows if not r.declared]
    shadow = [r for r in undeclared if r.flag in gates and r.verdict == LIVE]
    knobs = [r for r in undeclared if r.flag not in gates and r.verdict == LIVE]
    settings_knobs = [r for r in knobs if r.via_settings]

    L += ["## 3. ОБРАТНАЯ ПРОВЕРКА — код читает, никто не объявлял", "",
          "Флаг, которого нет ни в `.env`, ни в `.env.example`. Разделено по "
          "тому, ЧТО он решает, иначе интересное тонет в настройках: "
          "`KUKAI_DB_POOL_MIN` меняет число, "
          "`KUKAI_CHECKER_V2` решает, существует ли подсистема.", "",
          f"### 3a. ТЕНЕВЫЕ ВЫКЛЮЧАТЕЛИ — {len(shadow)} шт.", "",
          "Читаются внутри `*_enabled()`, то есть включают или выключают "
          "способность, живут в достижимом коде — и в конфигурации о них "
          "не сказано ничего. Колонка «по умолчанию» решает, что это значит:", "",
          "* **ON** — способность РАБОТАЕТ в проде прямо сейчас, и увидеть её "
          "в `.env` нельзя. Выключателя, о котором никто не знает, не должно быть.",
          "* **OFF** — код лежит на складе; вреда нет, но и учёта нет.", "",
          "| флаг | по умолчанию | гейт | читается в |", "|---|---|---|---|"]
    for r in sorted(shadow, key=lambda x: (default_is_on(graph.gate_default(x.flag))
                                           is not True, x.flag)):
        mod_name, fn = gates[r.flag][0]
        d = graph.gate_default(r.flag)
        on = default_is_on(d)
        mark = "**ON**" if on else ("OFF" if on is False else "не разобрано")
        shown = f"`{d}`" if d not in (None, "") else ("`\"\"`" if d == "" else "—")
        L.append(f"| `{r.flag}` | {mark} ({shown}) | `{mod_name}.{fn}()` | {r.where} |")
    L += ["", f"### 3b. Настроечные ручки без объявления — {len(knobs)} шт.", "",
          f"Из них {len(settings_knobs)} — поля `BaseSettings` со значением "
          "по умолчанию прямо в коде: отсутствие в `.env` для них НОРМА, "
          "а не находка. Остальные "
          f"{len(knobs) - len(settings_knobs)} — таймауты, пути, пороги.", "",
          "<details><summary>развернуть</summary>", ""]
    L += _table(knobs, show_value=False)
    L += ["", "</details>", ""]
    dead_undeclared = [r for r in undeclared if r.verdict != LIVE]
    L += [f"### 3c. Незаявленных и НЕживых: {len(dead_undeclared)}", "",
          (", ".join(f"`{r.flag}`" for r in dead_undeclared) or "нет"), ""]

    L += ["## 4. Функции-гейты `*_enabled()`", "",
          "Столбец «флаг» — то, что функция реально читает из окружения; "
          "прочерк значит, что решение принимается не по переменной среды. "
          "Псевдонимы импорта развёрнуты: `revit_ir_enabled as _kir_enabled` "
          "засчитывается вызывающему.", "",
          "| функция | где определена | флаг | модуль достижим? | кто зовёт |",
          "|---|---|---|---|---|"]
    for mod in sorted(graph.modules.values(), key=lambda m: m.name):
        if mod.is_test:
            continue
        for fn, lineno in sorted(mod.enabled_defs.items()):
            callers = {c for c in graph.callers_of(fn, mod.name)
                       if c != mod.name and not graph.modules[c].is_test}
            live_callers = sorted(c for c in callers if c in live)
            reach = LIVE if mod.name in live else DEAD
            if live_callers:
                who = f"`{live_callers[0]}`" + (f" (+{len(live_callers) - 1})"
                                                if len(live_callers) > 1 else "")
            elif callers:
                who = f"только мёртвые: `{sorted(callers)[0]}`"
            elif fn in mod.self_calls:
                who = "только внутри своего модуля"
            else:
                who = "**никем**"
            flag = next((f for f, g in mod.gate_flags.items() if g == fn), "—")
            L.append(f"| `{fn}()` | `{mod.name}`:{lineno} | `{flag}` | {reach} | {who} |")
    L.append("")

    reg = graph.modules.get("kukai.modules.registry")
    if reg:
        L += ["## 5. Реестр модулей (`kukai/modules/registry.py`)", "",
              "Рёбра сняты с ДИНАМИЧЕСКОГО `importlib.import_module(module_path)` "
              "(строка 66) — обход их видит, литералы берутся из `_MODULE_MAP`.", "",
              "| целевой модуль | достижим? |", "|---|---|"]
        for target in sorted(reg.dynamic_imports):
            L.append(f"| `{target}` | {LIVE if target in live else DEAD} |")
        L.append("")

    L += ["## 6. Чего обход НЕ видит (граница честная, не оговорка)", ""]
    L += BLIND_SPOTS
    L.append("")
    unresolved = [(m.name, m.flag_reads_unresolved)
                  for m in graph.modules.values() if m.flag_reads_unresolved]
    if unresolved:
        L.append("Собранные имена флагов (`f\"KUKAI_{…}\"`), которые обход "
                 "принципиально не разрешает:")
        for name, lines in sorted(unresolved):
            L.append(f"* `{name}` — строки {lines}")
    else:
        L.append("Собранных имён флагов (`f\"KUKAI_{…}\"`) в коде НЕТ — "
                 "проверено обходом, а не предположено.")
    # THE UNDECOMPILED IS NOT A FOOTNOTE. The full line must stand here
    # too, because section 6 is read separately from the header; but the
    # claim "their Python doesn't import it either" is no longer here — it
    # was a lie: the live service imports all five files that 3.10
    # tripped over.
    if graph.unparsable:
        L += ["", f"🔴 **ЭТОТ интерпретатор ({graph.interpreter}) не разобрал "
                  f"{len(graph.unparsable)} файл(ов), и отчёт этим "
                  f"дисквалифицирован** — см. отказ в шапке. Неразобранный "
                  f"файл в графе ОТСУТСТВУЕТ, то есть неотличим от мёртвого: "
              + ", ".join(f"`{p.name}`" for p in graph.unparsable[:10])]
    else:
        L += ["", f"Дерево разобрано ЦЕЛИКОМ интерпретатором "
                  f"{graph.interpreter}: неразобранных файлов 0. "
                  f"Знаменатель здоров."]
    L += ["", "## 7. Чем проверен САМ обход", ""] + GUARD_NOTE
    return _assert_no_env_values("\n".join(L) + "\n", graph.backend)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="capability reachability inventory")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args(argv)
    graph, rows = build_inventory()
    text = render_report(graph, rows)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"written: {args.out}  ({len(rows)} flags, "
              f"{len(graph.live())}/{len(graph.modules)} modules live)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
