"""A LIFTED RELATION EITHER REACHES THE PROGRAM OR IS COUNTED (E-30).

THE TRIGGER. The owner saw a building, carried over into another document,
as "a Frankenstein whose walls bulge outward": the walls are built, but not
one join exists between them. The cause was sought in capture and in the
lift, but it lies in the ROUTE — and the route diverged THREE times, not
once:

1. the live pipeline collected `join.index.json` and `group.index.json` and
   did NOT hand them to the lift (`pipeline.py`), so `LiftResult.joins` and
   `.groups` were `None` — "not asked" on a parse where the stage had
   ALREADY read the relations;
2. even when the indexes are supplied (as `orchestrator.decompile` does),
   the lifted operations DISAPPEAR: `DecompileResult` has no `joins` field
   at all, and `tree.json` carries only leaves;
3. the materializer accepts `joins=` (see `test_join_reaches_program.py`) —
   and receives it from NOBODY; it has no `groups=` parameter at all.

🔴 THE NUMBER THAT DECIDED THE SHAPE OF THE FIX (measured 2026-08-29, live
corpus, read-only). `lift_joins` on real indexes lifts 1 887 · 1 992 · 1 758 ·
1 339 operations across four buildings, `lift_groups` — 35 and 28. Not one of
them reaches the program today. So "zero joins in the program" is a fact
about the ROUTE, not about the building, and the difference between these
two statements is the whole subject of §18.2.

WHAT IS GUARDED HERE. Not "the route is laid" — it is not, and laying it
means touching `serving.py` and the materializer. What is guarded is that
THE SILENCE IS COUNTED: while relations do not reach their destination, the
passport must name how many were lifted and why they did not arrive. And the
HONESTY of this receipt is guarded: the moment the route appears,
`relations_delivered_to_program: 0` will become a lie, and the test must
turn red BEFORE anyone reads that lie.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_lifted_relations_are_counted.py -q
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from kir.decompile.fold import iter_l1_leaves
from kir.decompile.join_extract import JoinExtraction, JoinRecord
from kir.decompile.lift import lift_document_detailed
from kir.decompile.materialize import leaves_to_program
from kir.decompile.orchestrator import decompile
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)
from kir.decompile.side_contract import (
    RELATIONS_UNDELIVERED_REASON,
    relations_reach,
)

_TREE = pathlib.Path(__file__).resolve().parents[3]
_KIR = _TREE / "kir"


def _wall(element_id: int, x0: float, x1: float) -> L0Element:
    return L0Element(
        element_id=str(element_id), category="OST_Walls", category_ru="Стены",
        type_id="7", type_name="W200", level_id="10", level_name="L1",
        geom_kind=GeometryKind.CURVE, p0_mm=(x0, 0.0, 0.0),
        p1_mm=(x1, 0.0, 0.0), rotation_deg=None,
        bbox_min_mm=(x0, -100.0, 0.0), bbox_max_mm=(x1, 100.0, 3000.0),
        host_id=None, params={"WALL_USER_HEIGHT_PARAM": 3000.0})


def _two_joined_walls() -> tuple[L0Document, JoinExtraction]:
    document = L0Document(
        doc_name="d", revit_version="2024", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(),
        elements=(_wall(100, 0.0, 5000.0), _wall(101, 5000.0, 9000.0)))
    index = JoinExtraction(joins=(
        JoinRecord("100", joined_to=("101",)),
        JoinRecord("101", joined_to=("100",)),
    ))
    return document, index


class TheReceiptSeparatesTwoSilences(unittest.TestCase):
    """ "Not asked" and "asked, and got zero" are DIFFERENT claims."""

    def test_no_index_is_not_asked_and_carries_no_reason(self):
        summary = relations_reach(None, None)
        self.assertEqual(
            summary["relations_not_asked"], ["create_group", "join_elements"])
        self.assertEqual(summary["relations_lifted_total"], 0)
        self.assertIsNone(
            summary["relations_reach_reason"],
            "причина недоставки у разбора, где индекса не подавали, была бы "
            "утверждением о маршруте вместо утверждения о нашем незнании")

    def test_a_lifted_relation_is_counted_and_its_silence_named(self):
        document, index = _two_joined_walls()
        lifted = lift_document_detailed(document, None, None, join_index=index)
        self.assertEqual(len(lifted.joins.ops), 1, "лифт соединение не поднял")

        summary = relations_reach(lifted.joins, lifted.groups)
        self.assertEqual(summary["relations_lifted"], {"join_elements": 1})
        self.assertEqual(summary["relations_not_asked"], ["create_group"])
        self.assertEqual(summary["relations_delivered_to_program"], 0)
        self.assertEqual(
            summary["relations_reach_reason"], RELATIONS_UNDELIVERED_REASON)
        self.assertIn("до программы доехало 0",
                      summary["relations_reach_summary_ru"])


class TheZeroIsAboutTheRouteNotTheBuilding(unittest.TestCase):
    """The behavioral half: a lifted relation STILL does not reach its destination."""

    def test_the_offline_route_drops_the_lifted_join(self):
        """The orchestrator ACCEPTS the indexes — and loses the lifted result on the way out."""
        document, index = _two_joined_walls()
        result = decompile(document, join_index=index)
        self.assertFalse(
            hasattr(result, "joins"),
            "у `DecompileResult` появилось поле `joins`: поднятое отношение "
            "теперь переживает разбор, и квитанция обязана это учесть")

        leaves = list(iter_l1_leaves(result.tree))
        program = leaves_to_program(leaves, mode="same_document")
        names = [op["op"] for chunk in program.programs for op in chunk["ops"]]
        self.assertEqual(
            names.count("join_elements"), 0,
            "соединение доехало до программы — значит маршрут проложен, и "
            "`relations_delivered_to_program: 0` стало ЛОЖЬЮ. Правь квитанцию "
            "(`side_contract.relations_reach`), а не этот тест")

    def test_the_same_materializer_carries_it_when_handed(self):
        """Two-sidedness: the mechanism WORKS, it simply is not handed an input."""
        document, index = _two_joined_walls()
        lifted = lift_document_detailed(document, None, None, join_index=index)
        result = decompile(document, join_index=index)
        leaves = list(iter_l1_leaves(result.tree))
        program = leaves_to_program(
            leaves, mode="same_document", joins=lifted.joins)
        names = [op["op"] for chunk in program.programs for op in chunk["ops"]]
        self.assertEqual(
            names.count("join_elements"), 1,
            "материализатор перестал принимать `joins=` — тогда предыдущая "
            "проверка зеленеет по НЕВЕРНОЙ причине")


#: Wrappers that CALL the function handed to them, rather than invoking it
#: in place.
#: 🔴 WITHOUT THIS LIST THE MATCHER IS BLIND TO THE LIVE CALL, and this is
#: not a guess: the first edition of this test found ZERO lift calls in
#: `pipeline.py`, because it has `_offload(cached_lift_document_detailed, …)`
#: there — the name arrives AS AN ARGUMENT. The instrument was green in
#: shape and blind to the subject.
_DISPATCHERS = frozenset({"_offload", "_timed", "run_in_executor"})


class _Calls(ast.NodeVisitor):
    """The keyword arguments of every call to a named function in one module.

    Both a direct call and a call through a dispatcher wrapper are counted:
    the named arguments there are the same, but `func` is a different name.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.keywords: list[set[str]] = []

    @staticmethod
    def _callee(node: ast.Call) -> str | None:
        func = node.func
        return (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        called = self._callee(node)
        if called in _DISPATCHERS:
            for argument in node.args:
                if isinstance(argument, ast.Name) and argument.id == self.name:
                    called = self.name
                    break
        if called == self.name:
            self.keywords.append(
                {kw.arg for kw in node.keywords if kw.arg is not None})
        self.generic_visit(node)


def _call_keywords_in(source: str, name: str) -> list[set[str]]:
    visitor = _Calls(name)
    visitor.visit(ast.parse(source))
    return visitor.keywords


def _call_keywords(path: pathlib.Path, name: str) -> list[set[str]]:
    return _call_keywords_in(path.read_text(encoding="utf-8"), name)


class TheMatcherHasBothOutcomes(unittest.TestCase):
    """The instrument is proven from BOTH SIDES — on invented source, not on the tree.

    A check that only ever turns green guards nothing, and one that turns
    green INCORRECTLY gives no sign of it. So the matcher here is shown both
    outcomes on samples whose answer is known in advance.
    """

    def test_it_sees_a_direct_call(self):
        self.assertEqual(
            _call_keywords_in("leaves_to_program(x, joins=j)",
                              "leaves_to_program"),
            [{"joins"}])

    def test_it_sees_a_call_behind_the_offload_wrapper(self):
        self.assertEqual(
            _call_keywords_in(
                "_offload(cached_lift_document_detailed, d, join_index=j)",
                "cached_lift_document_detailed"),
            [{"join_index"}])

    def test_it_stays_silent_on_a_call_it_was_not_asked_about(self):
        self.assertEqual(
            _call_keywords_in("leaves_to_program(x, joins=j)",
                              "cached_lift_document_detailed"),
            [])


def _production_modules() -> list[pathlib.Path]:
    """Tree modules outside tests and outside `build/` — the suite's second copy."""
    return [
        path for path in sorted(_KIR.rglob("*.py"))
        if "tests" not in path.parts and "build" not in path.parts
    ]


class TheClaimIsCheckedAgainstTheCode(unittest.TestCase):
    """The structural half: the receipt is checked against CALLS, not against memory.

    The "who calls with what" list is NOT kept by hand here — it is
    computed. A cell that must be remembered drifts apart from the code at
    the first edit; a cell that is computed turns red.
    """

    def test_the_live_pipeline_hands_both_indexes_to_the_lift(self):
        calls = _call_keywords(
            _KIR / "decompile" / "pipeline.py", "cached_lift_document_detailed")
        self.assertTrue(calls, "живой вызов лифта в конвейере не найден")
        for keywords in calls:
            for name in ("join_index", "group_index"):
                self.assertIn(
                    name, keywords,
                    f"конвейер снова зовёт лифт без `{name}` — квитанция "
                    "будет считать «не спрашивали» на разборе, где стадия "
                    "связи ПРОЧИТАЛА (E-30)")

    def test_nobody_delivers_relations_so_the_zero_is_still_honest(self):
        handing: list[str] = []
        for path in _production_modules():
            for keywords in _call_keywords(path, "leaves_to_program"):
                if "joins" in keywords or "groups" in keywords:
                    handing.append(str(path.relative_to(_TREE)))
        self.assertEqual(
            handing, [],
            "кто-то начал подавать материализатору отношения: "
            f"{handing}. Значит `relations_delivered_to_program: 0` больше не "
            "правда — правь `side_contract.relations_reach` и "
            "`RELATIONS_UNDELIVERED_REASON`, а не этот список")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
