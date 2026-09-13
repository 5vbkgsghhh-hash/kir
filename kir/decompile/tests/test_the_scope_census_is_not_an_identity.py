"""THE REGION'S CENSUS LAW MUST BE CHECKABLE, NOT AN IDENTITY.

🔴 WHY (E-56, re-checked 03.09.2026). `ScopeCensus` holds the law
`nodes in the region = shelled + named refusals` and IS CAPABLE of
turning red: `ScopeCensus(10, 7, {})` refuses. But the sole
construction site outside the tests was feeding `len(node_ids)` into
BOTH fields and `refusals={}` as a literal — meaning the law degenerated
into `N + 0 == N` and was checking itself.

Right beside it stood a comment promising the opposite, verbatim: "A
subject outside the graph is a NAMED refusal of the region, not a
silent skip: it shrinks the census's denominator and must be visible."
The code, meanwhile, was doing `continue`. The prose promised, the
mechanism was not there.

🔴 AND WHY THIS FILE EXISTS, NOT JUST THE FIX. Having fixed the
construction, I checked it with a control: I put the identity back on a
copy of the tree — and 47 tests stayed GREEN, both times. Meaning the
fix would have been a WORD: nothing distinguishes it from its absence.
Here it becomes a number.
"""
from __future__ import annotations

import unittest

from kir.decompile.graph_clash_query import GraphBuildError, ScopeCensus


class ЗаконПереписиУмеетКраснеть(unittest.TestCase):
    """A FAIL control of the law itself: it must be capable of refusing."""

    def test_несходящаяся_перепись_отвергнута(self) -> None:
        with self.assertRaises(GraphBuildError) as e:
            ScopeCensus(nodes_in_scope=10, nodes_with_hull=7, refusals={})
        self.assertIn("не сходится", str(e.exception))

    def test_сходящаяся_с_названным_отказом_принята(self) -> None:
        c = ScopeCensus(nodes_in_scope=10, nodes_with_hull=7,
                        refusals={"субъект вне графа": 3})
        self.assertEqual(c.refused, 3)
        self.assertEqual(c.nodes_in_scope, c.nodes_with_hull + c.refused)


class ПостройкаНеПодаётОдноЧислоДважды(unittest.TestCase):
    """🔴 LOAD-BEARING: a guard on the SOURCE of the one live construction site.

    The subject here is deliberately the TEXT itself. There is nothing
    to run `query_from_decompile` with: it needs a decompile on disk, a
    live graph, and a live detector — the suite has no fixture for any
    of it, and inventing one would mean testing our own fiction. But
    the shape of the defect is TEXTUAL, and exactly the one that
    existed: the same expression fed into both fields of the law. That
    is what is guarded here, with the limit named out loud.

    The day a fixture for a real decompile appears, it must replace
    this guard with a run — and then this docstring becomes its reason.
    """

    def test_знаменатель_и_числитель_не_одно_выражение(self) -> None:
        """🔴 PARSING, NOT A REGEX, AND THIS WAS PAID FOR ON MYSELF
        WITHIN ONE MINUTE.

        The first revision was searching for `ScopeCensus(...)` with a
        regex over the source — and caught MY OWN COMMENT, which quoted
        the broken construction
        `ScopeCensus(len(node_ids), len(node_ids), {})`. The guard
        turned red on the description of the defect instead of the
        defect itself.

        Parsing sees the CALL, not the text: comments do not make it
        into the tree.
        """
        import ast
        import inspect
        import textwrap

        from kir.decompile import graph_clash_query as Q

        дерево = ast.parse(textwrap.dedent(
            inspect.getsource(Q.query_from_decompile)))
        вызовы = [n for n in ast.walk(дерево)
                  if isinstance(n, ast.Call)
                  and getattr(n.func, "id", None) == "ScopeCensus"]
        self.assertEqual(len(вызовы), 1,
                         "постройка переписи не одна — сторож смотрит не туда")
        поля = {k.arg: ast.unparse(k.value) for k in вызовы[0].keywords}
        self.assertIn("nodes_in_scope", поля)
        self.assertIn("nodes_with_hull", поля)
        self.assertNotEqual(
            поля["nodes_in_scope"], поля["nodes_with_hull"],
            "оба поля закона получают ОДНО выражение — закон вырожден в "
            "`N + 0 == N` и проверяет сам себя (E-56)")
        отказы = поля.get("refusals", "")
        self.assertNotIn(
            отказы, ("{}", "dict()"),
            "отказы области поданы пустым литералом: закон не может увидеть "
            "ни одного отказа, сколько бы их ни было")

    def test_отказ_области_собирается_а_не_пропускается(self) -> None:
        """A silent `continue` on a subject outside the graph — the thing the defect lived on."""
        import inspect

        from kir.decompile import graph_clash_query as Q

        src = inspect.getsource(Q.query_from_decompile)
        self.assertIn("вне_графа.update", src,
                      "субъекты вне графа снова пропускаются молча")
        self.assertIn("субъект вне графа", src,
                      "у отказа области нет НАЗВАНИЯ — счёт без имени "
                      "читателю не поможет")


if __name__ == "__main__":
    unittest.main()
