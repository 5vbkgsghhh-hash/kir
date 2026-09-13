"""JOINS WERE MEASURED AND WEREN'T GETTING THROUGH — ONE UNPASSED ARGUMENT.

WHY THIS FILE, BY THE MEASUREMENT OF 20.08.2026. The session plan recorded
"zero join edges", and this was read as "the third kind of connection was
not measured". A check against the artifact said otherwise: `join.index.json`
sits on disk, schema `/2`, and on `k2v33_join2` it holds 17 982 records. The
graph knows how to use them — `graph_from_l0` accepts `joins` and builds
`JOINED_AT_END`/`JOINED_TO`. The one thing that was not passing them was the
sole caller, `query_from_decompile`.

    joins=None          edges  92 635   joins ZERO
    joins=join_index    edges 106 646   JOINED_AT_END 12 059 · JOINED_TO 1 952

+14 011 edges (+15.1%) on one argument. The "zero" was a fact about the
CALL.

🔴 AND A SECOND MEASUREMENT, WITHOUT WHICH THE FIRST WOULD TEACH THE WRONG
LESSON. On `graph_check` the same argument gives EXACTLY ZERO new edges — and
that is correct: all 280 ends are read (`read: true`) and empty,
`join_allowed_at_end: [False, False]`. There are no joins there IN THE
BUILDING. The gain from the wiring depends on the document, and a zero after
it is an honest answer, not a failure. This is exactly the distinction the
`read` field carries.

WHAT IS PINNED DOWN HERE. Not a number (the corpus is machine-local and a
peer does not have it), but two things that do not depend on the corpus: that
the reader WORKS on input assembled by the producer, and that the prod
function CALLS it.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import tempfile
import unittest


def _index_json() -> str:
    """The index is assembled by the PRODUCER, not a handwritten literal.

    Shape 27: a handwritten input guards a fixture. Here, any discrepancy
    with the real schema would fail right here, not a month later on a live
    decompile.
    """
    from kir.decompile.join_extract import (
        EndJoin, JoinExtraction, JoinRecord)

    left = JoinRecord(
        element_id="301922",
        joined_to=("301999",),
        join_allowed_at_end=(True, True),
        elements_at_end_join=(EndJoin(read=True, elements=("301923",)),
                              EndJoin(read=True, elements=())),
    )
    right = JoinRecord(
        element_id="301923",
        joined_to=(),
        join_allowed_at_end=(True, False),
        # An unread end MUST name a reason — the producer refuses without
        # one, and this is its own guard against "was not asked" being
        # indistinguishable from "there are no neighbors".
        elements_at_end_join=(EndJoin(read=True, elements=("301922",)),
                              EndJoin(read=False, elements=(),
                                      why="LocationCurve отсутствует")),
    )
    return JoinExtraction(joins=(left, right)).to_json()


class ЧитательИндексаСтыков(unittest.TestCase):

    def _read(self, directory: pathlib.Path):
        # 🔴 THE READER MOVED, IT DID NOT DISAPPEAR (codex wave, 31.08.2026).
        # It was the private `graph_clash_query._join_index_on_disk`, it
        # became the public `graph_store.joins_on_disk` — and this is the
        # RIGHT place: the file name lives there too, and so does the graph
        # assembly that supplies it. All four promises below are checked in
        # the new home and hold: compressed data is read through
        # `snapshot_file_exists`/`open_snapshot`, absence gives `None`, not
        # `{}`, a foreign schema refuses loudly through the producer's
        # reader. The tests were re-targeted, NOT deleted: they ARE the
        # memory of those defects.
        from kir.decompile.graph_store import joins_on_disk
        return joins_on_disk(directory)

    def test_it_reads_a_plain_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            (run / "join.index.json").write_text(_index_json(),
                                                 encoding="utf-8")
            index = self._read(run)
        self.assertEqual(sorted(index), ["301922", "301923"])

    def test_it_reads_a_COMPRESSED_index_because_the_janitor_gzips_in_place(self):
        """🔴 A BARE `open` WOULD READ A COMPRESSED INDEX AS ABSENT.

        That is, it would answer "there are no joins" exactly where they are
        merely compressed. This class was closed on 19.08 in seven places;
        an eighth one is not being opened up here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            with gzip.open(run / "join.index.json.gz", "wt",
                           encoding="utf-8") as handle:
                handle.write(_index_json())
            index = self._read(run)
        self.assertEqual(sorted(index), ["301922", "301923"])

    def test_an_absent_index_is_None_and_not_an_empty_map(self):
        """`None` and `{}` are different facts, and the graph distinguishes
        them itself.

        An empty map would say "there are no joins", absence says "was not
        asked". The graph lists sources that were not supplied; an empty map
        would not land on that list and would become a silent negative claim
        about the building.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self._read(pathlib.Path(tmp)))

    def test_a_foreign_schema_refuses_LOUDLY_instead_of_returning_zero(self):
        """Parsing runs through the producer's reader, and this is its main
        benefit.

        A handwritten `json.load(...)["join_index"]` on a foreign schema
        would hand back an empty map — a silent zero instead of a refusal.
        """
        from kir.decompile.join_extract import JoinPayloadError
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            (run / "join.index.json").write_text(
                json.dumps({"schema_version": "kir-decompile-join-index/999",
                            "join_index": {}, "failures": []}),
                encoding="utf-8")
            with self.assertRaises(JoinPayloadError):
                self._read(run)


class ГрафПолучаетТретийРод(unittest.TestCase):

    def test_the_edges_appear_only_when_the_index_is_passed(self):
        """CONTROL FROM BOTH SIDES: without the index there are no edges,
        with it there are."""
        from kir.decompile.building_graph import _end_join_edges
        from kir.decompile.join_extract import JoinExtraction

        index = JoinExtraction.from_json(_index_json()).join_index
        nodes = {"301922": object(), "301923": object()}
        self.assertEqual(list(_end_join_edges(nodes, {})), [])
        edges = list(_end_join_edges(nodes, index))
        self.assertEqual(len(edges), 2)
        self.assertEqual({(e.src, e.dst) for e in edges},
                         {("301922", "301923"), ("301923", "301922")})

    def test_a_read_but_EMPTY_end_yields_no_edge_and_that_is_the_honest_answer(self):
        """A read, empty end means "there is no join", not "we don't know".

        Without this distinction, the wiring would teach that a zero after
        it is a failure; on `graph_check` the zero is HONEST — 280 ends are
        read and empty.
        """
        from kir.decompile.building_graph import _end_join_edges
        from kir.decompile.join_extract import (
            EndJoin, JoinExtraction, JoinRecord)

        lonely = JoinRecord(
            element_id="700001", joined_to=(),
            join_allowed_at_end=(False, False),
            elements_at_end_join=(EndJoin(read=True, elements=()),
                                  EndJoin(read=True, elements=())))
        index = JoinExtraction.from_json(
            JoinExtraction(joins=(lonely,)).to_json()).join_index
        self.assertEqual(list(_end_join_edges({"700001": object()}, index)), [])


class ПроверкаПоследнегоЗвена(unittest.TestCase):
    """🔴 WITHOUT IT, THE WHOLE FILE GUARDS A FIXTURE.

    The tests above call the reader and the builder THEMSELVES, so removing
    the argument from the prod function would not turn them red — the result
    would be "fixed it and moved on". This shape was paid for on 18.08 on the
    restart guard: the call was pulled out of `main()`, and all five of its
    tests stayed green.

    WE ASK THE CODE, NOT THE TEXT: a commented-out line and a mention in a
    docstring do not put a call into `co_names`/`co_consts`.
    """

    def test_query_from_decompile_actually_passes_the_index(self):
        """🔴 THE FIRST REVISION OF THIS TEST DID NOT PASS ITS OWN FAIL
        CONTROL.

        It was asking `co_names`/`co_varnames` about the names
        `_join_index_on_disk` and `joins`. The mutation "remove `joins=` from
        the call" left BOTH names in place — the reader is still called, and
        `joins` remains a local variable — and all seven of the file's tests
        stayed GREEN. The guard was not distinguishing the very thing it was
        written for, and this was learned exactly because the control was
        run by hand, not merely declared.

        What distinguishes it is the CALL'S KEYWORD: CPython puts the names
        of keyword arguments into a separate tuple in `co_consts`. Remove
        `joins=` — the tuple `("joins",)` disappears, and the test goes red.
        Run in both directions.
        """
        # 🔴 THE CHAIN BECAME THREE LINKS LONG (codex wave, 31.08.2026), and
        # the guard must walk it IN FULL. Previously `query_from_decompile`
        # read the index itself; now it asks the canonical graph, and the
        # index is supplied inside the builder. Checking only the first link
        # would mean guarding a call that says nothing about whether the
        # joins actually got through.
        from kir.decompile import graph_clash_query as Q, graph_store as S

        self.assertIn(
            "graph_for_clash_query", set(Q.query_from_decompile.__code__.co_names),
            "запрос больше не спрашивает канонический граф")
        self.assertIn(
            "build_graph_for_run", set(Q.graph_for_clash_query.__code__.co_names),
            "адаптер не зовёт сборщик — отсутствующий артефакт перестанет "
            "восстанавливаться, и граф ответит «стыков ноль»")

        code = S.build_graph_for_run.__code__
        self.assertIn(
            "joins_on_disk", set(code.co_names),
            "читатель индекса не вызывается — граф снова ответит «стыков "
            "ноль», и ни один другой тест этого не заметит")
        # The key is supplied as `kwargs["joins"]`, so the name lies as a
        # STRING in `co_consts`, not as a tuple of keyword arguments. We ask
        # for the shape that is there now, not the one that used to be.
        self.assertIn(
            "joins", [c for c in code.co_consts if isinstance(c, str)],
            "ключ `joins` пропал из подстановки: индекс читается и НЕ "
            "ПЕРЕДАЁТСЯ — ровно тот дефект, который этот файл закрывает "
            "(+14 011 рёбер на k2v33_join2)")


if __name__ == "__main__":
    unittest.main()
