"""KIR INSTRUMENTS — moved out of the product's `tools/` on 2026-08-27.

They were always KIR's BY COMPOSITION and product-owned only by their storage
location: `capability_graph` — 1057 lines on stdlib alone, `scope_audit` — 209
likewise, `relift_offline`, `snapshot_janitor` and `bounds_audit` pull in
nothing but `kir.*`. While the language lived inside the product's tree, the
difference did not matter. After the split it became visible at once: five KIR
test files failed to even collect, because they called a tree that is no
longer there.

Owner's decision, 08-27: move them. The same reasoning by which
`kir_idempotence`, `compile_client`, `live` and `operations` moved today —
**composition, not the directory name**.

🔴 WHY NOT `kir/tools/`. The first edition was named exactly that — and
IMMEDIATELY shadowed the product's `tools/`: pytest puts `kir/` on `sys.path`,
and a bare `import tools` started resolving TO HERE. The trap cuts both ways:
a product that ends up with `kir/` on its path would get someone else's
`tools`. The name was chosen so that no layout produces a collision.

🔴 AND ONE MORE THING, ABOUT THIS FILE ITSELF. Its first edition was
syntactically broken: the reasoning was appended AFTER the docstring's closing
quotes, and the whole package stopped importing — four tests failed on
`__init__.py`, not on their own subject. A broken `__init__` indicts everyone
who passes through it.

🔴 HOOK, 2026-08-30 — A LIBRARY RUN AS AN INSTRUMENT NO LONGER STAYS SILENT.

`python -m kir.instruments.measure_header` printed zero characters and
returned `EXIT=0`: A STRANGER, following the canon and typing the module as a
command, got the appearance of full success where there was none — the module
simply executed its `def`s and exited. `measure_header` is, however, NOT A
BROKEN INSTRUMENT (`E-22`): it is a LIVE LIBRARY (117 lines, neither `main`
nor `argparse`), and turning it into an instrument with arguments just to make
it stop staying silent under `-m` would be fixing the wrong thing: it already
has real consumers inside the package.

The subject is not this one library but the KIND: any `kir.instruments.*`
module without an instrument contract (`main`), run with `-m`. The fix is ONE
hook here, not an edit in every such module (and not an edit in every FUTURE
such module): on process exit the hook asks whether this very process was
launched as `-m kir.instruments.<something>`, and if the launched module has
no `main` — it names it a library along with its exports, and terminates the
process with the NON-ZERO code `2` — the same one already used in this
directory by `unwired_census`, `scope_audit`, `snapshot_janitor`,
`compile_gate_offline`: `2` means, everywhere here, "the instrument DID NOT
JUDGE", not "judged and found something".

A module that DOES have `main` (whether with `argparse` or without —
`canon_state`, `scope_audit`) is not touched by the hook at all: it has an
instrument contract, and which code it returns is its own decision, not this
file's. Separately: if the module has already failed with an UNCAUGHT
exception (the interpreter has already printed a traceback and set
`sys.last_type`), the hook stays silent — otherwise it would sign someone
else's crash with its own diagnosis of "this is a library", and two different
failures under one signature are worse than one failure with no signature at
all.

🔴 WHY `os._exit`, NOT `sys.exit`, INSIDE AN `atexit` FUNCTION — VERIFIED, NOT
ASSUMED. `sys.exit()`, called FROM a function registered with `atexit`, does
NOT CHANGE the process's return code: the interpreter prints "Exception
ignored in atexit callback" and still exits with whatever code the script had
already finished with (verified right here: `t1.py`/`t2.py` in the
investigation, `sys.exit(2)` inside the hook gave `EXIT=0`, `os._exit(2)` gave
`EXIT=2`). Which means `os._exit` is exactly what is needed — a blunt exit
that bypasses the remaining `atexit` callbacks, but it is safe here: by the
time the library module exits it has already executed everything except
printing one line of diagnosis.
"""

from __future__ import annotations

import atexit
import os
import sys


def _library_run_as_instrument_guard() -> None:
    """One hook for the whole package — see the file docstring for the full argument.

    Not a general fuse "for any silence": it fires only for a module FROM THIS
    PACKAGE, launched EXACTLY AS `__main__` via `-m`, which has no `main`
    function and has not already explained itself (by crashing with a
    traceback). Everything else is not its business, and it exits at once.
    """
    main_mod = sys.modules.get("__main__")
    spec = getattr(main_mod, "__spec__", None)
    name = getattr(spec, "name", None)
    if not name or not (name == __name__ or name.startswith(__name__ + ".")):
        return                       # not `-m kir.instruments...` — not our case
    if name == __name__:
        return                       # `-m kir.instruments` of the package itself — Python's own error
    if callable(getattr(main_mod, "main", None)):
        return                       # the instrument contract IS present — the return code is its own decision
    if hasattr(sys, "last_type") or hasattr(sys, "last_exc"):
        return                       # the module already failed UNCAUGHT — do not sign someone else's crash

    # 🔴 `__module__` IS COMPARED TO `"__main__"`, NOT TO `name` — CAUGHT
    # RIGHT HERE ON THE FIRST RUN. A module launched with `-m` executes under
    # the name `__main__`, and EVERY function defined directly in it carries
    # `__module__ == "__main__"` — not its own dotted `name` path. Comparing
    # against `name` always found zero exports and printed an empty
    # parenthesis INSTEAD of the real list: the instrument would have lied
    # to the author of its own fix.
    exported = sorted(
        n for n in vars(main_mod)
        if not n.startswith("_")
        and callable(getattr(main_mod, n, None))
        and getattr(getattr(main_mod, n), "__module__", None) == "__main__"
    )
    who = ", ".join(exported) if exported else "(явных функций верхнего уровня не нашлось)"
    sys.stdout.flush()
    print(f"🔴 `{name}` — БИБЛИОТЕКА, А НЕ ПРИБОР: функции `main`, которую "
          f"позвал бы `-m`, здесь нет, и запуск не сделал ничего, кроме "
          f"импорта. Её зовут: {who}.")
    print(f"   Если нужен прибор над этими данными — искать его СРЕДИ "
          f"потребителей модуля, не в нём: превращать библиотеку в прибор "
          f"ради тишины под `-m` значило бы чинить не то (`E-22`).")
    sys.stdout.flush()
    os._exit(2)   # sys.exit() would NOT change the return code here — see the argument above


atexit.register(_library_run_as_instrument_guard)
