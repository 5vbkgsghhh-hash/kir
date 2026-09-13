"""A REHEARSAL OVER THE WHOLE GOLDEN CORPUS: what the instrument is
responsible for, and what it is not.

WHY. `kir/kir_plan.py` (2026-08-19, moved from `tools/` on 2026-08-27)
answers the question "what WILL be checked, and what WILL NOT" before a
single flight into Revit. It is assembled from ready-made pieces —
`translation_cert.REFINEMENT` and `_NON_WITNESSABLE_CLAUSES` — and so its
own zone of responsibility must be measured, not assumed: an instrument
that silently fails to account for part of its input is worse than having
none.

The corpus here is the same 70 programs that pin the emission
(`test_golden.PROGRAMS`), i.e. 70 of 71 registry operations. THREE claims
are checked:

  1. the rehearsal runs over EVERY program and fails on none;
  2. the operations the instrument is NOT responsible for are exactly the
     four READING ops (`query_count/list/inspect/types`), and their
     absence from `REFINEMENT` is legitimate: `writes_model=False`, there
     is nothing to witness. Any WRITING op without an obligations row
     fails the test;
  3. groups are traversed. Measured 08-19 on an actual live-benchmark
     program: 110 top-level operations, and inside
     `create_group.members` — `create_column` and `create_beam`, unrolled
     into 372 placements. The instrument's first version counted zero
     framing, i.e. it was blind exactly where both measured defects sat.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_rehearsal_corpus_queue.jsonl"))

from kir import spec  # noqa: E402
from kir.tests.test_golden import PROGRAMS  # noqa: E402

_TOOL = pathlib.Path(__file__).resolve().parents[1] / "kir_plan.py"


def _load_rehearsal():
    """The instrument MOVED INTO THE PACKAGE on 2026-08-27
    (`kir/kir_plan.py`).

    It used to live in the product's `tools/`, and a separately installed
    KIR could not see it: the split gate failed exactly these five checks
    with `FileNotFoundError`. The instrument pulls in only `kir.rehearsal`
    — it is KIR by composition, and its place is inside. We load it by the
    path INSIDE the package: the file remains an executable instrument,
    not just a module.

    We deliberately do not carry a copy in here — two copies of the
    instrument drift apart, and the drift would read as a difference in
    subject. The test must measure the very same file a human uses.
    """
    loader = importlib.util.spec_from_file_location("kir_plan_under_test", _TOOL)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


class RehearsalCoversTheCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.kp = _load_rehearsal()

    def test_the_tool_exists_where_the_human_calls_it(self):
        self.assertTrue(_TOOL.is_file(), f"прибора нет по пути {_TOOL}")

    def test_it_rehearses_every_program_of_the_corpus(self):
        """None of the 70 programs fails the rehearsal."""
        self.assertGreaterEqual(len(PROGRAMS), 70)
        for name, program in sorted(PROGRAMS.items()):
            with self.subTest(program=name):
                report = self.kp.rehearse(program)
                self.assertGreater(report["ops_declared"], 0)
                self.assertGreaterEqual(report["elements_total"],
                                        report["ops_declared"])

    def test_only_READING_ops_have_no_obligation_table(self):
        """🔴 A writing op without an obligations row is a hole, not a
        feature.

        The instrument honestly prints who it is not responsible for. The
        test requires this list to consist ONLY of reading operations: for
        them `writes_model=False`, there is nothing to witness, and the
        absence of obligations is legitimate.
        """
        unwitnessed: set[str] = set()
        for program in PROGRAMS.values():
            for entry in self.kp.rehearse(program)["unwitnessed_ops"]:
                unwitnessed.add(entry.split(" ")[0])
        for op_name in sorted(unwitnessed):
            with self.subTest(op=op_name):
                op_spec = spec.OPS.get(op_name)
                self.assertIsNotNone(op_spec, f"{op_name} нет в реестре вовсе")
                self.assertFalse(
                    op_spec.writes_model,
                    f"{op_name} ПИШЕТ в модель и не имеет ни одного "
                    f"обязательства — это дыра, а не читающий оп")

    def test_group_members_are_walked_and_multiplied_by_placements(self):
        """Framing inside a group must be visible, and with the correct
        multiplicity."""
        member = {"op": "create_beam", "id": "b", "p0_mm": [0, 0, 0],
                  "p1_mm": [6000, 0, 0],
                  "level": {"by": "name", "value": "Этаж 1"}}
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g", "name": "рама",
            "members": [member],
            "placements": [[0, 0], [6000, 0], [12000, 0]],
        }]}
        report = self.kp.rehearse(program)
        self.assertEqual(report["ops_declared"], 2,
                         "объявлено две операции: группа и её член")
        # 🔴 FOUR, NOT THREE (F-354, 2026-08-30). Three offsets PLUS the
        # template instance: `create_group` materializes instance 0 — the
        # members themselves — and one more on top of it for each offset.
        # The earlier expectation locked in an UNDERCOUNT: the test was
        # written to match the bug and so did not catch it.
        self.assertEqual(report["counts"]["create_beam"], 4,
                         "три размещения ПЛЮС вхождение-шаблон — четыре "
                         "балки: `want_instances = 1 + len(placements)` "
                         "у эмиттера")
        ignored = {(d["op"], d["param"]): d["count"]
                   for d in report["authority_ignored"]}
        self.assertEqual(ignored.get(("create_beam", "level")), 4,
                         "поле, чьё значение Revit перепишет, обязано быть "
                         "названо по КАЖДОМУ вхождению, а не один раз")

    def test_the_multiplicity_is_the_emitters_own_law(self):
        """🔴 TWO CARRIERS OF ONE LAW, AND THERE WAS NO GUARD BETWEEN THEM.

        Member multiplicity is declared by the EMITTER
        (`authoring._emit_group`, `want_instances = 1 + len(placements)`),
        and counted by the REHEARSAL (`rehearsal._ops_of`). The files are
        different, the law is one — and they drifted apart silently: the
        rehearsal was losing the template instance on EVERY non-empty
        group.

        Both ends are guarded: that the emitter's law is not rewritten, and
        that the rehearsal gives exactly its number across the range of
        placements.
        """
        import inspect
        from kir import authoring

        src = inspect.getsource(authoring._emit_group)
        self.assertIn(
            "want_instances = 1 + len(placements)", src,
            "закон эмиттера переписан — перепиши и репетицию, иначе два "
            "носителя разойдутся снова")

        for places in (0, 1, 3, 11):
            with self.subTest(размещений=places):
                program = {"ir_version": "1.0", "ops": [{
                    "op": "create_group", "id": "g", "name": "рама",
                    "members": [{"op": "create_column", "id": "c",
                                 "xy": [0, 0],
                                 "level": {"by": "name", "value": "Этаж 1"}}],
                    "placements": [[1000.0 * k, 0.0] for k in range(places)]}]}
                self.assertEqual(
                    self.kp.rehearse(program)["counts"]["create_column"],
                    1 + places)

    def test_an_empty_placements_list_still_means_one_placement(self):
        """Measured 08-18: `create_group` materializes the template member
        ON TOP OF placements (59 duplicates across the building). So the
        lower bound here is one, not zero: counting zero would mean failing
        to see what was built."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g", "name": "одна",
            "members": [{"op": "create_column", "id": "c", "xy": [0, 0],
                         "level": {"by": "name", "value": "Этаж 1"}}],
        }]}
        report = self.kp.rehearse(program)
        self.assertEqual(report["counts"]["create_column"], 1)

    def test_the_group_op_multiplicity_does_two_jobs(self):
        """🔴 A GUARD AGAINST A WRONG FIX, NOT AGAINST A FIX (2026-08-30).

        A group op is counted as ONE element, even though the emitter
        builds `1 + len(placements)` group instances. The scope was
        MEASURED against the actual corpus (`group.index.json`, 93
        directories, 67 with an index — 15 raw and 52 compressed, 11
        distinct buildings by fingerprint): it affects 7 of 11 buildings,
        undercounting 6912 group elements. That is not zero, and so the
        finding is named, not forgotten.

        BUT IT CANNOT BE FIXED IN ONE LINE, and that is exactly what is
        guarded here. `mult` does two jobs: counting elements
        (`elements_total`) and the obligations multiplier (`will_check`).
        For `create_group` they diverge, because a group's obligations are
        already quantified per placement by ITS OWN text ("per placement
        offset", "every member of every placement"), while "GroupType Name
        matches name" applies to a single GroupType. The edit
        `out.append((item, 1))` -> `(item, 1 + len(placements))` would fix
        `elements_total` and BREAK both outputs of the instrument: the one
        for the human (`kir_plan.py:80`, `will_check`: geometry 1 -> 36,
        semantic 2 -> 72 on a group with 35 offsets) and the one for the
        model (`serving.py:2807`, the sum of `optional_unused.obligations`
        for a group without `name`: 73 -> 108).

        What is pinned is what must survive ANY CORRECT fix: a group's
        obligations do NOT scale with placements. `elements_total` is
        DELIBERATELY not pinned as a number — its correct value is itself
        the open question, and the guard must not forbid answering it.
        """
        for places in (0, 3, 35):
            with self.subTest(размещений=places):
                program = {"ir_version": "1.0", "ops": [{
                    "op": "create_group", "id": "g", "name": "рама",
                    "members": [{"op": "create_column", "id": "c",
                                 "xy": [0, 0],
                                 "level": {"by": "name", "value": "Этаж 1"}}],
                    "placements": [[1000.0 * k, 0.0] for k in range(places)]}]}
                will = self.kp.rehearse(program)["will_check"]
                self.assertEqual(
                    will.get("create_group\u00b7semantic"), 2,
                    "два обязательства оси semantic у ОДНОГО GroupType; если "
                    "число поехало за размещениями — множитель обязательств "
                    "спутан со счётом элементов")
                self.assertEqual(
                    will.get("create_group\u00b7geometry"), 1,
                    "обязательство геометрии группы САМО говорит «every member "
                    "of EVERY PLACEMENT» — умножать его на размещения значит "
                    "квантифицировать дважды")


if __name__ == "__main__":
    unittest.main()
