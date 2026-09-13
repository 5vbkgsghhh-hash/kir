"""Every dispatch to Revit is either bound to an artifact, or NAMED explicitly.

Binding proves that exactly the bytes that passed acceptance made it to Revit.
The bridge's guard can notice a SUBSTITUTED binding, and it cannot ask
"should this dispatch have been bound at all": without both keys it
let anything through. Whoever is capable of rewriting `code` is also capable of stripping
the keys — that is, the hole sat right under the very adversary the
guard's own docstring names.

Closing the list is the second of our two remedies. This test is the lock itself: it
TRAVERSES THE PACKAGE and requires that every literal (tool, op) pair on calls to
`run_declarative` be either a bound write lane, or named in
`UNBOUND_DISPATCH_OPS` with a reason. A new route will not slip through silently.

WHAT THE TRAVERSAL DOES NOT SEE is named here, rather than left implicit: three calls pass
`op` as a VARIABLE (`serving.py` — the forwarder, `family`, and the acceptance-reading
phase). Their values were read out of the code by a measurement on 11.08.2026 — `query`/`write` for
the family, and `acceptance_before`/`acceptance_after` for the reader — and they sit in the list
as literals. Should a fourth dynamic call appear, the traversal will NOT report it,
a runtime refusal will, and this is a deliberate trade-off: the list guards what is
statically visible, and the runtime guards the rest.
"""
from __future__ import annotations

import ast
import os
import unittest

from kir.acceptance_evidence import REGULAR_WRITE_EXECUTION_LANE
# 27.08.2026: the HOST's capability is obtained through a PORT. There are deliberately no stubs —
# a test that needs a host must be SKIPPED with a named reason, rather than
# green by construction.
from kir import ports as _порты

try:
    UNBOUND_DISPATCH_OPS = _порты.need(_порты.EXECUTION).UNBOUND_DISPATCH_OPS
    _НЕТ_ХОСТА = ""
except _порты.PortMissing as _exc:                          # pragma: no cover
    UNBOUND_DISPATCH_OPS = ()
    _НЕТ_ХОСТА = str(_exc)

DISPATCH_CALLS = {"run_declarative", "_run_declarative"}

#: A bound lane: the one pair that must NOT be in the list.
BOUND_LANE = ("revit_ir", "write")


def _package_root() -> str:
    """The package root is obtained from the package ITSELF, not by the product's name.

    It used to be `from kukai import ir` — the name `kukai` inside a language that
    does not depend on the product. `ir.__file__` is also accessible through an already-imported module.
    """
    import kir as ir
    return os.path.dirname(os.path.dirname(os.path.abspath(ir.__file__)))


#: A floor for the dispatch traversal's denominator. Measured 02.09.2026 — 11 literal pairs.
_ПАР_ОТПРАВКИ_НЕ_МЕНЬШЕ = 8


def _literal_dispatch_pairs() -> tuple[set[tuple[str, str]], list[str]]:
    """(literal pairs, calls with a dynamic op) across the whole package."""
    pairs: set[tuple[str, str]] = set()
    dynamic: list[str] = []
    root = _package_root()
    # 🔴 THE TRAVERSAL WALKS THE PACKAGE, NOT ITS PARENT (30.08.2026, E-11).
    # `_package_root()` returns `/opt/kir` — and right next to the package sits
    # `build/lib/kir/**`, A SECOND, stale copy of it. The instrument was judging a
    # MIXTURE of two trees: half of its dynamic findings were coming from
    # the build artifact, which differs from the live file and is a day and a half
    # older than it. The verdict did not change in the process — and that is exactly what makes it dangerous: the accusation
    # would have landed at an address that does not exist in the live tree.
    import kir as _pkg
    package_dir = os.path.dirname(os.path.abspath(_pkg.__file__))
    for folder, dirs, files in os.walk(package_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if os.path.sep + "tests" in folder:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(folder, fname)
            try:
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), path)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None))
                if name not in DISPATCH_CALLS:
                    continue
                keywords = {kw.arg: kw.value for kw in node.keywords}

                def literal(value: ast.AST | None) -> str | None:
                    return (value.value
                            if isinstance(value, ast.Constant)
                            and isinstance(value.value, str) else None)

                if name == "_run_declarative":
                    op = (literal(node.args[3]) if len(node.args) > 3
                          else literal(keywords.get("op")))
                    tool = "revit_ir"
                else:
                    op = literal(keywords.get("op"))
                    tool = literal(keywords.get("tool"))
                where = f"{os.path.relpath(path, root)}:{node.lineno}"
                if op is None or tool is None:
                    dynamic.append(where)
                else:
                    pairs.add((tool, op))
    # 🔴 THE DENOMINATOR INSIDE THE TRAVERSAL, MEASURED 02.09.2026: **11** literal pairs
    # and 4 dynamic dispatches. The callers use `assertTrue(pairs)` —
    # it catches ONLY EMPTINESS, while a traversal that lost half the tree returns
    # something non-empty and accuses based on incomplete material. This file's header already
    # names the price of that kind of half-blindness with its own measurement: `_package_root()`
    # was returning a root next to which `build/lib/kir/**` sits, and the instrument was judging a
    # MIXTURE of two trees. The number is placed here to hold BOTH
    # consumers — the binding, and the list of removed routes.
    assert len(pairs) >= _ПАР_ОТПРАВКИ_НЕ_МЕНЬШЕ, (
        f"обход нашёл {len(pairs)} литеральных пар при поле "
        f"{_ПАР_ОТПРАВКИ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 11). Это заявление о "
        f"ХОДОКЕ, а не о маршрутах: меньше найденных отправок значит меньше "
        f"найденных несвязанных")
    return pairs, dynamic


@unittest.skipIf(bool(_НЕТ_ХОСТА),
                 "закрытый список отправок принадлежит ХОСТУ: " + _НЕТ_ХОСТА)
class UnboundDispatchIsAClosedList(unittest.TestCase):
    """🔴 THE SKIP WAS WIRED UP ON 29.08.2026, AND THE FLAG HAD BEEN WAITING FOR IT FROM THE VERY START.

    This file's header requires, verbatim: "a test that needs a host must
    be SKIPPED with a named reason, rather than green by construction". The flag
    ``_НЕТ_ХОСТА`` was introduced on line 40 and WAS READ BY NO ONE. The requirement
    stood in the prose and did not stand in the code — the same form that was fixed on 28.08 in
    three files of the same family.

    WHAT EXACTLY HAPPENED WITHOUT AN OWNER, measured from both sides:

        port not supplied    UNBOUND_DISPATCH_OPS = ()      — 16 entries are lost
        port supplied        UNBOUND_DISPATCH_OPS = 16 pairs

    With an empty tuple, ``test_every_literal_dispatch_is_bound_or_named``
    accuses EVERY pair found by the traversal except the bound lane — that is,
    a refusal ABOUT US speaks in the voice of an assertion about the product. Two neighboring tests
    turn green VACUOUSLY at the same time: ``BOUND_LANE not in ()`` is true by
    construction, and so is "the list holds no removed routes" — there is nothing to
    hold in an empty list. One and the same emptiness produced both a false accusation and a false
    confirmation.

    🔴 THE SIGN OF THE SKIP IS "THERE IS NO OWNER", NOT "THE LIST IS EMPTY". This is not
    nitpicking: the owner IS ENTITLED to supply the port and name not a single unbound
    dispatch, and such an empty list is a genuine answer that must be
    checked, not skipped. Confusing the two kinds of emptiness would mean
    introducing exactly the defect this whole file stands against.

    ──────────────────────────────────────────────────────────────────────
    🔴 WHAT THIS TEST SAYS WHEN THE OWNER IS PRESENT. MEASURED ON 29.08.2026,
    SO THE NEXT PERSON DOES NOT HAVE TO REDISCOVER IT.
    ──────────────────────────────────────────────────────────────────────
    The skip above makes the test honest, but does NOT make it green. With
    the port supplied (16 entries in the list) it gives 1 passed, 2 failed, and
    both refusals are worth reading before fixing anything:

    1. ``('revit_ir', 'ground_identity')`` — A REAL HOLE. A live dispatch at
       `serving.py:596`, not bound to a write lane and not named in the list.
       Exactly what the file was written for: a new route slipped through silently while
       the lock was switched off by a skip-by-construction.

    2. ``('apply_revit_write', 'create_element')`` and
       ``('revit_ir', 'cleanup_stamps')`` are declared REMOVED ROUTES, and
       that is WRONG. Both are alive at the OWNER'S:

           kukai/write/create_element.py:1406   tool=apply_revit_write
           kukai/api/admin_kir.py:1032          "cleanup_stamps"

       The reason is not the list drifting, but THE BOUNDARY OF THE TRAVERSAL: ``_package_root()``
       returns the root of the `kir` package, while the list belongs to the OWNER and covers
       ITS routes too. The instrument is judging material it cannot see — the
       same class as `agreements.кто_спрашивает_про_сжатие` (audit finding F-105),
       and the fix is NOT to extend the traversal onto `kukai`: the product's name has no
       business being in this file. It is fixed by having the OWNER ITSELF name the material
       for its own half — that is, through a third field on the port, rather than through a grep.

    Until this field is set up, the third test below tells the truth only about
    KIR's own routes and has no right to speak about the owner's.
    """

    def test_every_literal_dispatch_is_bound_or_named(self):
        pairs, _dynamic = _literal_dispatch_pairs()
        self.assertTrue(pairs, "обход не нашёл ни одной отправки — он сломан")
        unaccounted = sorted(
            pair for pair in pairs
            if pair != BOUND_LANE and pair not in UNBOUND_DISPATCH_OPS)
        self.assertEqual(
            unaccounted, [],
            "отправка не связана артефактом и не названа в "
            "UNBOUND_DISPATCH_OPS — назовите её с причиной либо свяжите")

    def test_the_bound_lane_is_not_on_the_unbound_list(self):
        """Otherwise the list would silently permit the very thing it was written to guard against."""
        self.assertNotIn(BOUND_LANE, UNBOUND_DISPATCH_OPS)
        self.assertEqual(REGULAR_WRITE_EXECUTION_LANE, "kir_regular_write")

    def test_the_list_holds_no_entry_the_code_stopped_making(self):
        """The list is a LOCK, not an archive: a removed route must leave it.

        Otherwise the permission would outlive its route, and the next pair with the same
        name would go through on someone else's grounds. Dynamic calls are excluded from the
        list: the traversal cannot see them by construction, and demanding a
        literal match from them would mean deleting correct lines.
        """
        pairs, _dynamic = _literal_dispatch_pairs()
        # 🔴 PHASES PASSED AS A VARIABLE ARE ASKED OF THEIR OWNER, RATHER THAN
        # REPEATED AS A LITERAL (18.08.2026). The traversal only sees `op="..."` in
        # the source; a phase arriving as a variable does not exist for it, and
        # a handwritten list of such phases is exactly the table that must
        # match the registry and does not. `built_reread` proved exactly this:
        # it had been entered into the closed list of routes (otherwise the built-judge
        # would refuse BEFORE the bridge), and here nobody named it — and the guard declared
        # a LIVE route removed.
        #
        # `built_verdict.PHASE` is the very same object that goes into
        # `_run_declarative(code, PHASE, ...)`. Should the phase be renamed, the guard
        # will find out about it on its own.
        from kir.built_verdict import PHASE as _BUILT_REREAD_PHASE
        dynamic_ops = {
            ("revit_ir", "query"),            # family
            ("revit_ir", "acceptance_before"),  # the acceptance-reading phase
            ("revit_ir", "acceptance_after"),
            ("revit_ir", _BUILT_REREAD_PHASE),  # the built-judge
        }
        stale = sorted(
            pair for pair in UNBOUND_DISPATCH_OPS
            if pair not in pairs and pair not in dynamic_ops)
        self.assertEqual(
            stale, [],
            "в списке остался маршрут, которого в коде больше нет")


if __name__ == "__main__":
    unittest.main()
