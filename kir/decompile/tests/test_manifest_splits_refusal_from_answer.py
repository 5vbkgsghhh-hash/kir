"""The manifest must say WHAT its ``failures`` consist of.

MEASURED 2026-08-13, ``len_ar_me_r24_v1`` (a real building, 57,809 elements,
a live read, 53,686 side-index rows). A director read the manifest and
commissioned work on the ``failures`` column:

    total "refusals"               12,073   22.5% of rows — manifest headline
    ├─ aspect absent                10,267   a CORRECT negative answer
    │    curtain not_curtain         9,715 — the wall is NOT a curtain wall,
    │                                        the reader is right
    ├─ wrong kind at the input       1,710   a filter on the CALLER, not
    │                                        the reader
    └─ a genuine cut                    96   0.18% — this is the only
                                              real work

``curtain`` leads the manifest with 99.5% "refusal" and is perfectly healthy.

AND THIS HAPPENED A SECOND TIME. The first was 2026-07-29 on the tower:
``curtain`` at 14,343 against 19 genuine cuts. Back then ``SideFailureKind``
was created along with the full ``SIDE_FAILURE_KINDS`` dictionary, wired into
``run.json``, and a test was written asserting that no unclassified reason
can exist. The INSTRUMENT was fixed — and one of its OUTPUTS was not. The
manifest was left with a single word, and it was that word that got the work
commissioned two weeks later.

    The pattern: a defect class is closed at the SOURCE and left open at
    every CONSUMER that carries the same value under the same name.

WHAT THESE TESTS DO NOT COVER, in words: the correctness of the
classification itself (guarded by ``test_every_reason_is_classified`` on the
dictionary) and whether the stage ran at all. What is checked here is
exactly one thing — that the breakdown REACHED the manifest, closes into the
total, and did not leak into the resume comparison key.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import pipeline as pipe
from kir.decompile.side_contract import SideFailure, SideFailureReason
from kir.decompile.tests.test_pipeline import FakePipelineBridge

#: Exactly two reasons are "facts about the model". The list is duplicated
#: here ON PURPOSE, rather than imported: if someone reclassifies a reason,
#: this test must say so, while an import would go along silently.
DETERMINATIONS = (
    SideFailureReason.ASPECT_NOT_PRESENT,
    SideFailureReason.ELEMENT_KIND_MISMATCH,
)


class _Extraction:
    """The minimum that ``_side_counts`` and ``_side_breakdown`` read."""

    def __init__(self, records: tuple, failures: tuple) -> None:
        self.records = records
        self.failures = failures


class ManifestSplitsRefusalFromAnswer(unittest.TestCase):

    def test_a_stage_that_only_answered_shows_zero_cuts(self) -> None:
        """CONTROL-PASS. A healthy stage: many refusals, zero cuts.

        This is ``curtain`` from the real building, in miniature: 9,715 rows
        of "wall is not a curtain wall". By ``failures`` the stage is the
        worst in the run; by ``cuts`` it is flawless. The test asserts that
        these are DIFFERENT numbers in the manifest, not one.
        """
        extraction = _Extraction(
            records=(),
            failures=tuple(
                SideFailure(element_id=str(n), reason=reason.value,
                            typed_reason=reason)
                for n, reason in enumerate(DETERMINATIONS * 4)),
        )
        breakdown = pipe._side_breakdown(extraction, "curtain")
        self.assertEqual(8, breakdown["determinations"])
        self.assertEqual(0, breakdown["cuts"])
        self.assertEqual(0, breakdown["failures_untyped"])
        self.assertEqual(
            8, pipe._side_counts(extraction)["failures"],
            "заголовочное число обязано остаться прежним — меняется не оно, "
            "а то, что стоит рядом")

    def test_a_stage_that_gave_up_shows_cuts(self) -> None:
        """CONTROL-FAIL of the instrument: a cut must be DISTINGUISHABLE from an answer.

        An instrument that prints the same thing for cuts as for answers
        measures neither of them. These are exactly those 96 rows from the
        real building: a railing with no base level set, a profile with a
        disjoint contour, exactly two dependent sketches.
        """
        extraction = _Extraction(
            records=(),
            failures=(
                SideFailure(
                    element_id="1", reason="railing base level unavailable",
                    typed_reason=SideFailureReason.READ_FAILED),
                SideFailure(
                    element_id="2", reason="disjoint/nested exterior",
                    typed_reason=(
                        SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED)),
                SideFailure(
                    element_id="3", reason="not_curtain",
                    typed_reason=SideFailureReason.ASPECT_NOT_PRESENT),
            ),
        )
        breakdown = pipe._side_breakdown(extraction, "sketch")
        self.assertEqual(2, breakdown["cuts"])
        self.assertEqual(1, breakdown["determinations"])

    def test_the_breakdown_closes_on_a_real_run(self) -> None:
        """The breakdown's sum equals the headline — on EVERY stage of the run.

        A sum that does not close means a reason silently fell out of both
        buckets; that is exactly how ``not_curtain`` lived until 2026-07-29.
        """
        with TemporaryDirectory() as tmp:
            result = asyncio.run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="manifest-breakdown-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            stages = manifest["stages"]
            self.assertTrue(stages, "прогон не записал ни одной стадии")
            for stage, row in stages.items():
                for field in ("cuts", "determinations", "failures_untyped"):
                    self.assertIn(
                        field, row, f"стадия {stage} без поля {field}")
                self.assertEqual(
                    row["failures"],
                    row["cuts"] + row["determinations"]
                    + row["failures_untyped"],
                    f"разбивка стадии {stage} не сходится с её заголовком")

    def test_the_breakdown_is_not_part_of_the_resume_key(self) -> None:
        """The breakdown does NOT take part in the comparison — otherwise the archive would become invalid.

        ``_side_counts`` is the key by which resume decides whether an
        already-stored index can be reused. Any new field in it declares
        UNFIT every decompile taken earlier: their manifests do not carry
        that field, and 4.1 GB of archive would have to be reread for the
        sake of a record's shape.

        This test is the one thing standing between a convenient edit ("I'll
        just put the breakdown straight into ``_side_counts``, it's more
        logical there") and silently devaluing every past run.
        """
        extraction = _Extraction(
            records=("a", "b"),
            failures=(SideFailure(
                element_id="1", reason="not_curtain",
                typed_reason=SideFailureReason.ASPECT_NOT_PRESENT),))
        self.assertEqual(
            {"rows", "failures"}, set(pipe._side_counts(extraction)),
            "ключ сверки resume расширен — старые манифесты перестанут "
            "совпадать, и архив разборов придётся перечитывать")

        # And the second half of the same assertion: a manifest WITHOUT a
        # breakdown (taken before this wave) must still be accepted.
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / pipe._SIDE_MANIFEST_NAME).write_text(json.dumps({
                "schema_version": pipe._SIDE_MANIFEST_VERSION,
                "stages": {"curtain": {
                    "rows": 2, "failures": 1, "source": None}},
            }), encoding="utf-8")
            self.assertTrue(
                pipe._side_counts_agree(directory, "curtain", extraction),
                "манифест, снятый до разбивки, перестал переиспользоваться")


if __name__ == "__main__":
    unittest.main()
