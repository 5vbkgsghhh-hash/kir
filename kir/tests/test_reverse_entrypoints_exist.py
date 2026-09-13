"""A declared entry point of the reverse pass must be REACHABLE.

MEASURED 2026-08-11 (from the code, not from hearsay). `reverse_contract.py`
declares `create_group` COMPOSED and names the emitting entry point
`component_to_group_program`; validation in the same file REQUIRES a
composed contract to name an entry point — the contract set itself a
condition and fulfilled it BY NAME. Measured:

    component_to_group_program — materialize.py:1315, exported,
        called ONLY from tests (test_materialize.py:1134,1140);
    place_group_ops — component.py:627, its ENTRY POINT, has ZERO callers
        at all, even in tests: there is nobody to build a place_op;
    the function itself returns None while native_group_enabled() is off,
        and tests/test_capability_map_wiring.py SEPARATELY asserts that
        this gate is dead, and fails if it ever reports as wired;
    the sole producer of a create_group op-dict on the reverse pass is
        native_group_op_to_ir, and it is called exactly from this
        unreachable function (materialize.py:1375).

That is, the reverse pass TODAY never emits create_group at all.

WHY THIS IS OUR CLASS OF DEFECT. A value is asserted in one place (the
`entrypoints` field) and read nowhere. The guarding test compared a NAME
STRING (`assertEqual(contract.entrypoints,
("component_to_group_program",))`), i.e. it confirmed that the name was
WRITTEN, not that what the name names exists.

WHAT THIS FILE DOES NOT DECIDE: it does not redeclare the mode. Whether
COMPOSED or DECOMPOSED is correct for a group is a question about what the
reverse pass PROMISES; it touches the ReverseMode taxonomy and the parsing
territory. The measurement is attached, the decision is the lead's. What is
closed here is the gap between the NAME and REACHABILITY, and it does not
depend on the mode.
"""
from __future__ import annotations

import ast
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_entrypoint_queue.jsonl"))

from kir.reverse_contract import REVERSE_CONTRACTS  # noqa: E402

#: 🔴 THE ROOT AFTER THE SPLIT (2026-08-28). `parents[3]` from
#: `kir/kir/tests/x.py` gives `/opt` — the directory where our package sits
#: next to foreign trees. Before 08-27 the same count from
#: `backend/kukai/ir/tests/x.py` gave the installation root. The correct
#: root is the one the package is INSIDE of.
_BACKEND = pathlib.Path(__file__).resolve().parents[2]
_INDEX: dict | None = None

_ENTRYPOINTS_NAMED_IN_ADVANCE: dict[str, str] = {
    # 🔴 THE `lift_joins` RECORD WAS REMOVED ON 2026-09-01: BOTH OF ITS
    # SEAMS ARE CLOSED, AND IT OUTLIVED ITS OWN TRUTH. It used to say "the
    # lifter is written and works, but NOBODY CALLS IT," and named two
    # seams in other files. Both were closed on 08-22, meaning the record
    # stood false for ten days, and it only turned red once a guard reached
    # it:
    #
    #   seam 1 — "`orchestrator.decompile` does not accept `join_index` at
    #           all": it does accept it, `orchestrator.py:195`, and the fix
    #           is dated 08-22 in the comment above the parameter itself;
    #   seam 2 — "the result cannot be placed into `LiftResult` while
    #           `serialize_lift_result` is assembled by hand":
    #           `lift_cache` now carries the `joins` field and BUMPED the
    #           record version to /2 (08-22).
    #
    # AND THE CALL IS LIVE, and this is not an inference from the closed
    # seams but a place in the code: `decompile/lift.py:5587` —
    # `replace(result, joins=lift_joins(...))` guarded by
    # `if join_index is not None`, while `decompile/pipeline.py:2067` feeds
    # `join_index=joins` with `enabled=True` (the risk of feeding it was
    # measured 08-29 on a live corpus: 7 decompiles, 0 failures out of 11).
    #
    # Leaving the record would mean holding, in the ledger of what is
    # owed, something already delivered — and a ledger of what is owed is
    # valuable precisely because it holds ONLY what is undelivered.
    "component_to_group_program": (
        "склад native_group: функция возвращает None, пока гейт выключен, а "
        "её вход place_group_ops не зовёт НИКТО, даже тесты — питать её "
        "нечем. Потолок пути замерен: 7.52% листьев, сосредоточенных в двух "
        "зданиях из десяти, и библиотеку компонентов не строит никто. Это не "
        "«ещё не подключено», а «нечем питаться»"),
}


def _reference_index() -> dict:
    """References from PRODUCTION to the name — of ANY kind, not only a
    call.

    BOUGHT BY A BUG IN THIS VERY FILE: the first version counted a literal
    ast.Call as reachability and declared unreachable almost all `_lift_*`
    functions, which are dispatched BY NAME STRING from the
    `lift._CANDIDATES` table. The canon warns about exactly this: a
    reference to a function AS A VALUE is an edge, because dispatch here is
    indirect. The probe that required a literal call committed the very
    class of defect it was written to catch.

    Counted as a reference: a call, a name used as a value, a table's
    string literal. NOT counted: the contract-declaration file itself —
    otherwise the contract would be confirming itself with its own text,
    which is the very defect being analyzed.
    """

    global _INDEX
    if _INDEX is not None:
        return _INDEX
    index: dict = {}
    for path in sorted(_BACKEND.rglob("*.py")):
        rel = str(path.relative_to(_BACKEND))
        if "/tests/" in rel or rel.startswith("tests/") or "test_" in path.name:
            continue
        if rel.endswith("reverse_contract.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # `__all__` IS NOT A REFERENCE, IT IS A DECLARATION. A module
        # exporting a name does not use it; counting an export as
        # reachability would bring back exactly the defect this file
        # analyzes — confirming that a name was WRITTEN instead of that
        # what it names exists. Measured on itself: without this filter,
        # component_to_group_program is "reachable" from
        # materialize.py:1389, i.e. from its own __all__.
        exported = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__all__"
                            for t in node.targets)):
                for el in ast.walk(node.value):
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        exported.add((el.value, el.lineno))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if (node.value, node.lineno) in exported:
                    continue
                name = node.value
            if name:
                index.setdefault(name, []).append("%s:%d" % (rel, node.lineno))
    _INDEX = index
    return index


def _references(symbol: str) -> list:
    return list(_reference_index().get(symbol, ()))


class DeclaredEntrypointsMustExist(unittest.TestCase):

    def test_every_declared_entrypoint_is_reachable_or_named_in_advance(self):
        """CHECKING REACHABILITY, NOT A STRING. A contract naming an entry
        point that does not exist promises the third state of the reverse
        pass — a named receipt — without holding it."""
        for op_name, contract in sorted(REVERSE_CONTRACTS.items()):
            for entry in contract.entrypoints:
                with self.subTest(op=op_name, entrypoint=entry):
                    refs = _references(entry)
                    if refs:
                        self.assertNotIn(
                            entry, _ENTRYPOINTS_NAMED_IN_ADVANCE,
                            "%s: точка входа СТАЛА достижимой (%s) — запись "
                            "журнала аванса пережила свою правду"
                            % (entry, refs[:2]))
                        continue
                    self.assertIn(
                        entry, _ENTRYPOINTS_NAMED_IN_ADVANCE,
                        "%s объявляет точку входа %r, на которую в продакшне "
                        "нет НИ ОДНОЙ ссылки: контракт называет выход, "
                        "которого нет" % (op_name, entry))

    def test_the_advance_ledger_carries_a_reason_not_a_label(self):
        for entry, why in sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE.items()):
            with self.subTest(entrypoint=entry):
                self.assertGreater(len(why), 60, entry)

    def test_the_ledger_names_only_declared_entrypoints(self):
        declared = {e for c in REVERSE_CONTRACTS.values() for e in c.entrypoints}
        for entry in sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE):
            with self.subTest(entrypoint=entry):
                self.assertIn(entry, declared)

    def test_the_group_entrypoint_is_still_fed_by_nobody(self):
        """The entry point's own entry: `place_group_ops` is publicly
        exported and, apart from that export, is not mentioned in
        production ANYWHERE. As long as this holds, the composed group
        path will not execute even with the gate turned on."""
        self.assertEqual(_references("place_group_ops"), [])

    def test_the_indirect_dispatch_is_visible_to_this_instrument(self):
        """A GUARD AGAINST REPEATING OUR OWN MISTAKE. `_lift_wall` is not
        called literally — its name sits as a STRING in
        `lift._CANDIDATES`. If the instrument stops seeing this, it will
        again declare the living dead."""
        self.assertTrue(_references("_lift_wall"),
                        "прибор снова считает только литеральный вызов")


if __name__ == "__main__":
    print("named-in-advance:", sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE))
    for _op, _c in sorted(REVERSE_CONTRACTS.items()):
        for _e in _c.entrypoints:
            print("%-26s %-30s refs=%s"
                  % (_op, _e, (_references(_e) or ["NONE"])[:2]))