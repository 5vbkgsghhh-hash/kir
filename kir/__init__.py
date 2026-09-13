"""KIR — a typed intermediate representation and compiler for BUILDINGS.

A building is a program. The language specification ships with the package:
``kir/specs/SPEC_V1.md``.

Canonical home of the IR spec, registry, schema generator and compiler
(arbitration Q3). Query family v1. Public surface:

    from kir import (
        compile_program, plan_program, program_schema, export_capability_cells,
    )

Modules you author with — `kir.dsl` first, and this line is why: measured
2026-09-04 from a clean install, the road to a compiled building was 17 steps
through `kir.sdk` (raw selector dicts, three of them guessed and refused) and
6 steps through `kir.dsl`, which fills those selectors itself. The short road
was in the package and named nowhere.

    kir.dsl      handles: `create_wall(...)` returns a handle; slots you did
                 not name are filled from it. Start here.
    kir.sdk      the same 83 builders over plain dicts, when you want the JSON.
    kir.spec     the registry itself: OPS, IR_VERSION.
    kir.preview  an SVG of the plan, and a census of what it could not draw.

Or type `kir demo` — the command ships with this package.
"""
# 🔴 THE FIRST LINE OF THIS FILE IS THE FIRST THING `help(kir)` PRINTS, AND IT
# SHIPPED WRONG IN THE PUBLIC PACKAGE (31.08.2026). It used to say "Kukai
# Revit-IR (SPEC: /root/kukai-ir/SPEC_V1.md on yta)" — three mistakes at once:
# KIR was named after SOMEONE ELSE'S project (the owner's word of 27.08: KIR,
# KUKAI, and 27B are THREE different projects, and KUKAI is only ONE of the
# environments where KIR is driven); it pointed to another machine's
# hostname alias; and the spec was looked up at a dead external path, even
# though it SHIPS INSIDE THE PACKAGE ITSELF.
#
# 🔴 AND THE EXPLANATION IS DELIBERATELY A COMMENT, NOT PART OF THE DOCSTRING:
# the docstring is what `help(kir)` prints to an outside person, and our
# internal history is not what they asked. The purchased knowledge is kept,
# but not behind the PUBLIC door.

#: The package version. 🔴 IT DID NOT EXIST AT ALL (29.08.2026, an outsider's
#: gate). `kir.__version__` is the first thing asked in a bug report, and the
#: package could not name itself from the inside. It is taken from the
#: INSTALL, not a literal: a literal would become a second carrier of the
#: same value next to `pyproject.toml` and would silently diverge from it.
#: 🔴 THE WRONG NAME WAS BEING ASKED, AND THE ANSWER WAS A PLAUSIBLE
#: FALSEHOOD (measured 01.09.2026). The DISTRIBUTION name is `kir-building`
#: (`pyproject.toml`), the IMPORT name is `kir`; the second one was being
#: asked here. For an INSTALLED package, `importlib.metadata.version("kir")`
#: raises `PackageNotFoundError`, and `__version__` printed "not installed
#: (running from the tree)" — exactly the case it is meant to distinguish. A
#: run in a clean venv with the wheel:
#:
#:     kir.__file__ = <venv>/site-packages/kir/__init__.py
#:     version: не установлен (запуск из дерева)      ← false, the package IS installed
#:
#: The refusal was HONESTLY NAMED and so read as a fact about the
#: environment, not about our question. The distribution name is taken from
#: one place and named here in full: two names for one value is a named
#: defect of this tree, and it is caught only by a run IN THE INSTALL, not
#: from the tree, where both answers coincide.
_DIST = "kir-building"

try:                                                            # noqa: SIM105
    from importlib.metadata import PackageNotFoundError, version as _version
    __version__ = _version(_DIST)
except Exception:                                               # noqa: BLE001
    #: The package is not installed (working directly from the tree) — this
    #: is a LEGITIMATE answer, and it is named, not replaced by a number.
    __version__ = "не установлен (запуск из дерева)"

# 🔴 THE PACKAGE NO LONGER PULLS IN THE COMPILER ON IMPORT (02.09.2026), AND
# THIS IS NOT HYGIENE, IT IS REMOVING THE LAST NAMED REMNANT.
#
# There used to be four ordinary imports here — `compiler`, `midend`,
# `schema_gen`, `spec` — and they turned `import kir` into loading THIRTY-
# EIGHT modules. The cost was not in milliseconds but in a LAYER: anyone who
# touched anything inside `kir/` executed `kir/__init__.py` and thereby
# pulled in the compiler. Three packages carried an apology in their headers,
# "we import nothing at module level because `kir/__init__` pulls in the
# compiler" (`kir/live`, `kir/viewer`, `kir/course`) — meaning the layer was
# held up by NEIGHBORS' POLITENESS, not by design.
#
# Measured with the same traversal as the live-plan gate: the
# `kir.live.plan_stream` renderer reached the compiler through EXACTLY ONE
# edge, and that edge was the package itself.
#
#     import kir                    ->  1 module    (was 38)
#     import kir.live.plan_stream   ->  5 modules, NOT ONE solver
#
# PEP 562 (module-level `__getattr__`) preserves the public door byte for
# byte: `from kir import compile_program` works as it worked,
# `kir.CompileOutput` too — the module simply loads AT THE MOMENT OF ASKING,
# not on package import. The path into the compiler still REMAINS, and an
# import traversal still sees it: the names moved into the `_PUBLIC` string
# literals. This is not a weakening — what disappeared is not the edge but
# its EXECUTION, and that is asked separately by the guard
# `kir/tests/test_import_kir_is_light.py`, run in a clean interpreter.
#
# NOTE: kir.compile_cache (CachedCompileClient) is deliberately NOT
# re-exported here: it pulls compile_client -> httpx into this package's
# import chain, which must stay light and offline-safe (decompile subprocess
# tests run under interpreters without httpx). Import it from its own module:
#     from kir.compile_cache import CachedCompileClient

#: THE PUBLIC DOOR: name -> module where it lives. The single carrier of this
#: mapping; `__all__` and `__dir__` are DERIVED from it, not written
#: alongside as a second list — two places required to match are a named
#: defect of this tree.
_PUBLIC: dict[str, str] = {
    "CompileOutput": "kir.compiler",
    "compile_program": "kir.compiler",
    "plan_program": "kir.compiler",
    "GroundedProgram": "kir.midend",
    "GroundingContext": "kir.midend",
    "PlannedProgram": "kir.midend",
    "program_schema": "kir.schema_gen",
    "export_capability_cells": "kir.spec",
    "IR_VERSION": "kir.spec",
}

__all__ = ["__version__", *sorted(_PUBLIC)]


def __getattr__(name: str):
    """A public name loads at the moment it is asked for (PEP 562).

    A refusal on an unknown name is a plain `AttributeError` with the same
    text Python itself gives: replacing it with our own would mean starting
    a second dictionary of errors next to the language's own.
    """
    where = _PUBLIC.get(name)
    if where is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    value = getattr(importlib.import_module(where), name)
    globals()[name] = value      # asked once, an ordinary attribute after that
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_PUBLIC))
