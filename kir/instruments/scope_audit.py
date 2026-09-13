"""A NAME IS CALLED WHERE IT IS NOT BOUND — an instrument for scopes.

    venv/bin/python tools/scope_audit.py            # the whole kukai package
    venv/bin/python tools/scope_audit.py Name Other # only these names
    venv/bin/python tools/scope_audit.py --verbose  # plus what was skipped and why

WHY. On 2026-08-20 a live receipt said: "COLLISION CHECK NOT PERFORMED:
NameError: name 'snapshot_file_exists' is not defined". The collision check
was silently not performed on the LIVE path — and "did not look" reads as
"clean", and that is the most expensive lie there is.

The cause turned out to be six hours old and one character wide: a 12:51 edit
replaced `l0.exists()` with `snapshot_file_exists(l0)` in `load()`, while the
import of that name sat LOCALLY inside the neighboring function
`resolve_run()`. Python binds a function-local import ONLY in its own
function — and stays silent about it right up to the call.

🔴 WHY GREP AND TWO HOMEMADE INSTRUMENTS GAVE ZERO. Both walked the module
body via `ast.walk` and thereby DESCENDED into nested functions, crediting
their local imports to the whole module. To the eye the file also looks like
it is importing: the name is written in it. The only way to tell the
difference is a genuine scope analysis — collecting a scope's bindings
WITHOUT descending into someone else's — or execution.

WHAT THE INSTRUMENT DELIBERATELY DOES NOT LOOK AT, AND WHY THIS IS NAMED, NOT HIDDEN:

* files with `from X import *` — the module scope is opaque, what it brought
  in is not statically knowable. Such a file is skipped ENTIRELY (there are
  20 of them), and this is an honest hole in the instrument, not cleanliness
  of the corpus;
* annotations under `from __future__ import annotations` (PEP 563) — they are
  strings and are never evaluated. Without this carve-out the instrument
  would give five false findings on type annotations, and the very first
  reader would learn to ignore it;
* `globals()`, `exec`, dynamic imports — beyond the reach of any AST.

The instrument is checked by itself: `kukai/ir/tests/test_names_are_bound_where_
they_are_called.py` keeps the corpus at zero and contains a FAIL control — a
file with a known defect on which the instrument MUST turn red.
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import sys

#: Bound by the interpreter, there is no binding in the AST.
_MODULE_DUNDERS = frozenset({
    "__file__", "__name__", "__doc__", "__builtins__", "__spec__",
    "__package__", "__loader__", "__path__", "__all__", "__debug__",
    "__annotations__", "__dict__", "__class__", "__module__",
    "__qualname__", "__init_subclass__", "__set_name__",
})
ALWAYS_BOUND = frozenset(dir(builtins)) | _MODULE_DUNDERS

_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: 🔴 A COMPREHENSION HAS ITS OWN SCOPE, AND THE INSTRUMENT DID NOT KNOW THAT
#: (2026-09-04, RT-11). The distinguishing case was reproduced by EXECUTION,
#: not by reasoning:
#:
#:     def f():
#:         [x for x in ()]
#:         return x
#:
#:     unbound_names -> []            the instrument stayed silent
#:     f()           -> NameError: name 'x' is not defined
#:
#: `_bindings` descended inside and credited the target `x` to the WHOLE
#: function — exactly the same mistake for which a class body turned red on
#: 08-29, only on a different node. Python 3 binds the target in the
#: expression's OWN scope; the only thing that escapes it is a walrus
#: assignment (PEP 572), and that is collected separately.
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _annotations_are_strings(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(a.name == "annotations" for a in node.names):
                return True
    return False


def _bindings(scope) -> set:
    """Names bound DIRECTLY in the scope's body. No descending into nested ones."""
    out: set = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = scope.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                    args.vararg, args.kwarg):
            if arg is not None:
                out.add(arg.arg)

    def visit(node) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPE_NODES):
                out.add(child.name)
                continue                      # its own scope — not our concern
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, _COMPREHENSIONS):
                # Its own scope: targets do NOT escape it. Only a walrus
                # escapes (`[y := f(v) for v in xs]` binds `y` HERE, PEP 572),
                # and missing it would produce a false finding on live code —
                # an instrument blinded by a legitimate construct would be
                # rejected by the very first reader.
                for sub in ast.walk(child):
                    if (isinstance(sub, ast.NamedExpr)
                            and isinstance(sub.target, ast.Name)):
                        out.add(sub.target.id)
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    out.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(child, ast.Name) and isinstance(
                    child.ctx, (ast.Store, ast.Del)):
                out.add(child.id)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                out.update(child.names)
            # 🔴 THE NAME `except ... as e` IS NO LONGER HERE (2026-09-04,
            # RT-11). Python binds it ONLY in the handler's body and DELETES
            # it on exit (`del e` in the bytecode), so reading the same name
            # after the `try` is a NameError, yet the instrument used to
            # credit it as bound to the whole function. The name is granted
            # to the handler's body in `_loads`, not to the scope.
            visit(child)

    visit(scope)
    return out


def _comprehension_targets(node) -> set:
    """Names bound by the expression ITSELF: the targets of all its `for` clauses."""
    out: set = set()
    for generator in node.generators:
        for sub in ast.walk(generator.target):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                out.add(sub.id)
    return out


def _loads(scope, skip_annotations: bool):
    """(read node, names bound LOCALLY above it) — within this scope.

    The pair's second member is what the instrument lacked before
    2026-09-04: a name visible NOT TO THE WHOLE scope, but only to a fragment
    of the tree inside it. There are two such fragments, and both are genuine
    Python scopes, not exceptions:

        `except E as e:`   the name lives ONLY in the handler's body
        `[x for x in xs]`  the target lives ONLY inside the expression

    While they were counted among the bindings of the WHOLE function, the
    instrument stayed silent about a read after a `try` and after a
    comprehension — that is, about the very construct it was set up against.
    """
    out: list = []

    def visit(node, extra: frozenset) -> None:
        if isinstance(node, (*_SCOPE_NODES, ast.Lambda)):
            return                       # its own scope — not our concern
        if isinstance(node, ast.ExceptHandler):
            if node.type is not None:    # the type is evaluated WITHOUT the name
                visit(node.type, extra)
            inner = extra | ({node.name} if node.name else frozenset())
            for statement in node.body:
                visit(statement, inner)
            return
        if isinstance(node, _COMPREHENSIONS):
            inner = extra | _comprehension_targets(node)
            for child in ast.iter_child_nodes(node):
                visit(child, inner)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.append((node, extra))
        for child in ast.iter_child_nodes(node):
            visit(child, extra)

    if skip_annotations:
        _strip_annotations(scope)
    for child in ast.iter_child_nodes(scope):
        visit(child, frozenset())
    return out


def _strip_annotations(scope) -> None:
    """PEP 563: annotations are strings, their names are NEVER evaluated."""
    for node in ast.walk(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
            for arg in (*node.args.posonlyargs, *node.args.args,
                        *node.args.kwonlyargs, node.args.vararg,
                        node.args.kwarg):
                if arg is not None:
                    arg.annotation = None
        elif isinstance(node, ast.AnnAssign):
            node.annotation = ast.Constant(value=None)


def unbound_names(source: str, path: str = "<строка>") -> list:
    """(line, name) for every read of a name not bound in its scopes."""
    tree = ast.parse(source)
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
           for n in ast.walk(tree)):
        raise _StarImport(path)
    skip = _annotations_are_strings(tree)
    found: list = []

    def walk(scope, chain) -> None:
        here = chain + [(_bindings(scope), isinstance(scope, ast.ClassDef))]
        # Visible: this scope, enclosing FUNCTIONS (closures) and the
        # module. A CLASS's scope is deliberately left out of the chain for
        # nested ones — that is exactly what Python does, and confusing this
        # would mean missing defects.
        #
        # 🔴 THIS IS EXACTLY WHAT THE COMMENT PROMISED AND THE CODE DID NOT DO
        # (2026-08-29). It used to say `for enclosing in here[1:-1]: visible
        # |= enclosing`, i.e. the chain was merged WHOLESALE, class bodies
        # included. A live distinguishing case, reproduced by execution:
        #
        #     class C:
        #         token = 1
        #         def f(self): return token
        #
        #     unbound_names -> []            the instrument stayed silent
        #     C().f()       -> NameError: name 'token' is not defined
        #
        # That is, an instrument set up precisely against "a name is called
        # where it is not bound" was missing this exact defect in its most
        # common form — referring to a class attribute without `self.` inside
        # a method.
        visible = set(here[0][0]) | set(here[-1][0])
        for binds, is_class in here[1:-1]:
            if is_class:
                continue
            visible |= binds
        for name, local in _loads(scope, skip):
            if (name.id not in ALWAYS_BOUND and name.id not in visible
                    and name.id not in local):
                found.append((name.lineno, name.id))
        # 🔴 DESCENT IS STEP-BY-STEP ONLY. The first version looked for
        # nested scopes via `ast.walk`, and it handed them back AT ALL DEPTHS
        # AT ONCE: a function sitting inside two functions got a chain
        # missing the intermediate one — i.e. its closure was treated as
        # nonexistent. The instrument produced three false findings on the
        # live corpus and would have been rejected by the very first reader.
        def descend(node) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, _SCOPE_NODES):
                    walk(child, here)
                else:
                    descend(child)

        descend(scope)

    walk(tree, [])
    return sorted(set(found))


class _StarImport(Exception):
    """A file with `from X import *`: the module scope is opaque."""


class AuditIncomplete(RuntimeError):
    """Part of the corpus did not get read, and the walk has no right to stay silent about it.

    🔴 SET UP 2026-09-04 (RT-12). There used to be TWO mute `continue`
    statements here — `except OSError` and `except SyntaxError` — and next to
    them sat a `skipped` list that they did NOT POPULATE. A file that failed
    to open or to parse vanished from the walk without a trace: `findings: N`
    became a fact about WHAT COULD BE READ, yet was read as a fact about the
    CORPUS, and the CLI exited ZERO. This is exactly the case the instrument
    is set up against (the header: "did not look reads as clean") — and it
    lived inside the instrument itself.

    The refusal is only raised if the caller did NOT SET UP a ledger:
    `audit(..., refusals={})` populates it and keeps counting (a consumer
    obliged to finish counting over an incomplete corpus says so EXPLICITLY),
    while `audit()` with no ledger turns red — because silently returning a
    number here is not an option.
    """


def audit(root: pathlib.Path, names=(), *,
          refusals: "dict | None" = None) -> tuple[list, list]:
    """Findings and files with `import *`. What could not be read goes into `refusals` or raises.

    `refusals` (if passed) is populated as path -> REASON: "failed to read"
    and "failed to parse" are different answers, with a different next move
    for each.
    """
    hits, skipped = [], []
    не_прочлось: dict = {}
    for path in sorted(root.rglob("*.py")):
        if "/tests/" in str(path):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            не_прочлось[str(path)] = (
                f"НЕ ПРОЧЁЛСЯ: {type(exc).__name__}: {exc}")
            continue
        try:
            rows = unbound_names(source, str(path))
        except SyntaxError as exc:
            не_прочлось[str(path)] = f"НЕ РАЗОБРАЛСЯ: SyntaxError: {exc}"
            continue
        except _StarImport:
            skipped.append(str(path))
            continue
        for line, name in rows:
            if names and name not in names:
                continue
            hits.append((str(path), line, name))
    if не_прочлось:
        if refusals is None:
            raise AuditIncomplete(
                f"обход не прочёл {len(не_прочлось)} файл(ов), и число находок "
                f"без них есть факт о ПРИБОРЕ, а не о корпусе:\n  "
                + "\n  ".join(f"{p}: {w}"
                               for p, w in sorted(не_прочлось.items())))
        refusals.update(не_прочлось)
    return hits, skipped


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    # 🔴 THE ROOT USED TO BE `parents[1] / "kukai"`, I.E. `kir/kukai`
    # (2026-08-29). No such directory exists under any layout; `rglob` over
    # it is empty, and the CLI printed "findings: 0" with exit code 0, HAVING
    # READ NOT A SINGLE FILE. An instrument set up against "did not look
    # reads as clean" had itself become that very case. The root is taken
    # from the package — the package knows its own location.
    import kir as _kir_pkg
    root = pathlib.Path(_kir_pkg.__file__).resolve().parent
    base = root.parent
    # The ledger is set up EXPLICITLY: the CLI must finish counting and show
    # findings even over an incomplete corpus — but has no right to exit zero
    # as if the corpus had been read in full.
    отказы: dict = {}
    hits, skipped = audit(root, tuple(args), refusals=отказы)

    # THE DENOMINATOR FIRST. Zero findings means "clean" only together with
    # proof that there was something to read: an empty walk and a clean
    # corpus print identically and mean opposite things.
    read = sum(1 for p in root.rglob("*.py")
               if "/tests/" not in str(p) and "__pycache__" not in p.parts)
    if not read:
        print(f"🔴 ОБХОД НЕ СОСТОЯЛСЯ: под {root} не прочитано ни одного "
              f".py — «находок: 0» отсюда есть факт о приборе, а не о коде")
        return 2

    for path, line, name in hits:
        print(f"🔴 {pathlib.Path(path).relative_to(base)}:{line}  {name}")
    if verbose:
        print(f"[пропущено из-за `import *`: {len(skipped)} файл(ов)]")
        for path in skipped:
            print("   ", pathlib.Path(path).relative_to(base))
    if отказы:
        # THE LOSS IS NAMED RIGHT NEXT TO THE NUMBER, not as a footnote under the table.
        print(f"🔴 НЕ ВОШЛИ В ОБХОД: {len(отказы)} файл(ов) из {read} — "
              f"находки ниже сняты с того, что прочлось")
        for path, why in sorted(отказы.items()):
            print(f"   · {pathlib.Path(path).relative_to(base)}: {why}")
    print(f"находок: {len(hits)} "
          f"(прочитано файлов: {read - len(отказы)} из {read})")
    # Code `2` means "the instrument DID NOT JUDGE": the same meaning as its
    # neighbors in this directory use. An unread file makes "findings: 0"
    # unverifiable, and a silent zero here is more costly than a red result:
    # this is exactly the lesson this instrument was paid for on 08-20 by a
    # live receipt.
    if отказы:
        return 2
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
