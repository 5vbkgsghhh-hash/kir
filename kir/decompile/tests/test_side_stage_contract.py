"""The IMPLICIT CONTRACT of a side stage — now explicit and checked.

THE LIVE CASE OF 30.07 this file exists because of. A new annotation stage
passed all 30 of its tests, its C# ran on the bridge perfectly (two notes,
378 ms, text/view/view name/coordinates/type — all in place), and the full
run against the Snowdon Towers sample died after a minute and a half with
``side_stage_count_mismatch: annotation: requested 26, without a row and
without a receipt 26``.

The cause was ONE FIELD NAME. The §18.2 verifier asks the batch result for
``records`` and ``failures``; the new stage named its field ``text_notes``,
the verifier saw zero reports and honestly failed the run. The law of the
census worked exactly as intended, but the conclusion drawn from its message
("the stage lost elements") pointed away from where the defect actually was.

The contract was IMPLICIT: nowhere is it written that a stage's result must
answer to ``records``. The tests below make it explicit for EVERY registered
stage, so that the next new stage fails here, rather than on a live model
forty minutes into reading it.
"""
from __future__ import annotations

import dataclasses
import unittest

from kir.decompile import pipeline as pipe
from kir.decompile.annotation_extract import (
    AnnotationExtraction,
    AnnotationFailure,
    TextNoteRecord,
)
from kir.decompile.curtain_extract import CurtainExtraction
from kir.decompile.dimension_extract import (
    DimensionExtraction,
    DimensionFailure,
    DimensionRecord,
)
from kir.decompile.curve_extract import CurveExtraction
from kir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
)
from kir.decompile.group_extract import GroupExtraction
from kir.decompile.geom_extract import GeometryExtraction
from kir.decompile.join_extract import JoinExtraction
from kir.decompile.mep_system_extract import MepSystemExtraction
from kir.decompile.sketch_extract import ProfileExtraction
from kir.decompile.tag_extract import (
    TagExtraction,
    TagFailure,
    TagRecord,
)


#: Stage -> the type of its result. A row is added TOGETHER with the stage:
#: a stage with no row here is a stage whose contract no one has checked.
STAGE_RESULT_TYPES = {
    "curve": CurveExtraction,
    "sketch": ProfileExtraction,
    "curtain": CurtainExtraction,
    "family_placement": FamilyPlacementExtraction,
    "group": GroupExtraction,
    "annotation": AnnotationExtraction,
    "mep_system": MepSystemExtraction,
    "tag": TagExtraction,
    "dimension": DimensionExtraction,
    "geometry": GeometryExtraction,
    # The joins wave (18.08.2026). The row was a day late behind the stage:
    # the stage was registered in `_default_cs_builders`, but not entered
    # here, and this test turned red for exactly what it was written for.
    # Entered AFTER checking the substance, not for the sake of green:
    #   * `records` on it is a PROPERTY (alias `joins`), not a field — the
    #     §18.2 verifier is satisfied by that, and the test below allows it
    #     deliberately;
    #   * `failures` is a real field, and a receipt counts as a report:
    #     `_accounted_ids(JoinExtraction(failures=(f,)))` gives ['77'],
    #     an empty stage remains silent (checked by execution);
    #   * the law of the receipt is honored at the level of a WALL END too:
    #     `EndJoin` refuses an unread end with no reason — "without it,
    #     'we didn't ask' is indistinguishable from 'there are no
    #     neighbors'".
    "join": JoinExtraction,
}


class SideStageContractTests(unittest.TestCase):

    def test_every_registered_stage_has_a_declared_result_type(self) -> None:
        """A new stage must appear in this file, or it is unchecked."""
        registered = set(pipe._default_cs_builders())
        declared = set(STAGE_RESULT_TYPES)
        self.assertEqual(
            registered, declared,
            "стадии зарегистрированы, но их контракт не объявлен: "
            f"{sorted(registered - declared)}; объявлен, но не зарегистрирован: "
            f"{sorted(declared - registered)}")

    def test_every_stage_result_answers_to_the_reconciler(self) -> None:
        """``records`` and ``failures`` — the names §18.2 asks by.

        The CLASS is checked, not an instance: different stages have
        different required constructor arguments, and the contract test
        must not know their shape. A name counts as available if it is
        among the dataclass's fields OR among the class's properties — the
        verifier does not care how it is implemented.
        """
        for stage, result_type in STAGE_RESULT_TYPES.items():
            with self.subTest(stage=stage):
                names = {f.name for f in dataclasses.fields(result_type)}
                names |= {
                    name for name in dir(result_type)
                    if isinstance(getattr(result_type, name, None), property)}
                for attribute in ("records", "failures"):
                    self.assertIn(
                        attribute, names,
                        f"{stage}: результат стадии не отвечает на "
                        f"{attribute!r} — сверщик посчитает, что стадия не "
                        f"отчиталась НИ ЗА ОДИН запрошенный id")

    def test_every_stage_has_a_category_row_or_is_whole_model(self) -> None:
        """A stage with no categories, and not whole-model, gets not a single id."""
        whole_model = {"group"}
        for stage in pipe._default_cs_builders():
            with self.subTest(stage=stage):
                if stage in whole_model or stage in pipe._DYNAMIC_STAGE_IDS:
                    continue
                self.assertTrue(
                    pipe._STAGE_CATEGORIES.get(stage),
                    f"{stage}: нет строки в _STAGE_CATEGORIES — конвейер "
                    f"никогда не запросит для неё ни один id")


class AnnotationReconcilerTests(unittest.TestCase):
    """The exact same case, reproduced in the smallest possible form."""

    def test_a_read_note_counts_as_accounted(self) -> None:
        extraction = AnnotationExtraction(
            text_notes=(TextNoteRecord("26", "900", "вид", (1.0, 2.0), "т"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["26"])

    def test_a_refused_note_also_counts_as_accounted(self) -> None:
        """A receipt is also a report: "we didn't read it, and here is why" is not silence."""
        extraction = AnnotationExtraction(
            failures=(AnnotationFailure("26", "нет вида", "aspect_not_present"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["26"])

    def test_silence_stays_silence(self) -> None:
        """An empty result for a requested id must remain unreported."""
        self.assertEqual(list(pipe._accounted_ids(AnnotationExtraction())), [])


class TagReconcilerTests(unittest.TestCase):
    """The same check for the tags stage — BEFORE a live run, not after.

    The annotation wave learned about the name ``records`` forty minutes
    into reading Snowdon. The tags stage learns about it here, and that is
    the only difference this file exists for.
    """

    def _record(self) -> TagRecord:
        return TagRecord(
            element_id="4300", owner_view_id="900", owner_view_name="вид",
            at_view_mm=(1.0, 2.0), tagged_element_id="512",
            tag_family="independent", leader=False, orientation="Horizontal")

    def test_a_read_tag_counts_as_accounted(self) -> None:
        extraction = TagExtraction(tags=(self._record(),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["4300"])

    def test_a_refused_tag_also_counts_as_accounted(self) -> None:
        """A tag on a link element is a receipt, not silence and not a guess."""
        extraction = TagExtraction(
            failures=(TagFailure("4300", "linked host", "tag_target_not_local"),))
        self.assertEqual(list(pipe._accounted_ids(extraction)), ["4300"])

    def test_silence_stays_silence(self) -> None:
        self.assertEqual(list(pipe._accounted_ids(TagExtraction())), [])

    def test_the_stage_is_paged_not_whole_model(self) -> None:
        """The stage has a category row, so ids will arrive for it."""
        self.assertEqual(pipe._STAGE_CATEGORIES["tag"],
                         __import__(
                             "kir.decompile.tag_extract",
                             fromlist=["TAG_CATEGORIES"]).TAG_CATEGORIES)

    def test_the_builder_is_bound_to_a_revit_version(self) -> None:
        """The tags stage is the only one whose C# depends on the version.

        Without a version the builder must still compile (otherwise the
        enumeration of stages the contract is checked against would fail),
        but the version must CHANGE the text — otherwise the 2022 seam
        exists only in words.
        """
        default = pipe._default_cs_builders()["tag"](["1"])
        old = pipe._default_cs_builders("2021")["tag"](["1"])
        new = pipe._default_cs_builders("2024")["tag"](["1"])
        self.assertNotEqual(old, new)
        self.assertEqual(default, new)


class SideStageGateCoverageTests(unittest.TestCase):
    """The SECOND implicit stage contract: its C# must compile on SIX versions.

    THE LIVE CASE OF 30.07 this class exists because of. Decompiling a
    59-story tower on **Revit 2023** hung dead and kept repeating, every
    5-20 seconds, the same failure:

        EXEC_PIPELINE declarative revit_ir/decompile_read TEMPLATE COMPILE
        FAILED (server bug): CS1503: Argument 1: cannot convert from 'long'
        to 'Autodesk.Revit.DB.BuiltInParameter'   bridge_roundtrips=0

    NOTHING reached Revit at all. The six-version gate (``kir.gate_runner``)
    compiled FOUR side stages out of nine: ``family_placement`` / ``group`` /
    ``curtain`` / ``sketch``. Three stages added on 30-31.07 (annotations,
    MEP systems, tags) never passed the gate ONCE and were proved live only
    against the public Snowdon sample — which is R2026. A construct legal
    in 2026 and illegal in 2023 shipped unnoticed.

    The sister test above requires that a stage have a DECLARED result
    contract. This one requires that it have a DECLARED gate entry: the
    pipeline registry and the gate registry are checked against each other
    by their set of names, and can no longer silently diverge in either
    direction.
    """

    def _gate_names(self, version: str = "2026") -> set[str]:
        from kir import gate_runner
        return set(gate_runner.side_stage_gate_bodies(version))

    def test_every_registered_stage_is_compiled_by_the_six_version_gate(
        self,
    ) -> None:
        from kir import gate_runner
        registered = set(pipe._default_cs_builders())
        expected = registered | set(gate_runner.UNREGISTERED_GATE_STAGES)
        self.assertEqual(
            self._gate_names(), expected,
            "стадия зарегистрирована, но ворота её не компилируют: "
            f"{sorted(registered - self._gate_names())}; "
            "ворота компилируют незарегистрированную стадию, не объявленную "
            "в UNREGISTERED_GATE_STAGES: "
            f"{sorted(self._gate_names() - expected)}")

    def test_the_gate_emits_per_version_not_once(self) -> None:
        """The gate must emit PER VERSION, not send the same text six times.

        For tags the C# depends on the version by construction (the
        ``TaggedLocalElementId`` / ``GetTaggedLocalElementIds`` seam at
        2022). A gate that emits once would be checking one surface six
        times — the exact defect ``tools/compile_gate_offline.py`` already
        described in its own docstring.
        """
        from kir import gate_runner
        self.assertNotEqual(
            gate_runner.side_stage_gate_bodies("2021")["tag"],
            gate_runner.side_stage_gate_bodies("2024")["tag"])

    def test_the_gate_body_is_the_body_the_pipeline_ships(self) -> None:
        """The gate compiles the SAME text that will go into the model.

        Not "similar": the pipeline registry is the sole source of
        builders, and the gate must call it, rather than its own list of
        imports, which would diverge from it at the very first edit.
        """
        from kir import gate_runner
        for stage, builder in pipe._default_cs_builders("2023").items():
            with self.subTest(stage=stage):
                self.assertEqual(
                    gate_runner.side_stage_gate_bodies("2023")[stage],
                    builder(gate_runner.GATE_SIDE_STAGE_IDS))


if __name__ == "__main__":
    unittest.main()
