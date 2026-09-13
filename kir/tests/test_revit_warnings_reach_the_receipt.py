"""THE WORD REVIT MUST REACH THE RECEIPT, NOT BE ERASED ALONG THE WAY.

WHY THIS FILE, AS OF THE 20.08.2026 READING. The Revit failure
preprocessor lived in FOUR copies of the text — `authoring.py:7850` and
`:8327`, `stairs_run_emit.py:434`, `stairs_landing_emit.py:587` — and each
one had:

    if (__sev == FailureSeverity.Warning) { __fa.DeleteWarning(__f); continue; }

`continue` STOOD BEFORE `Seen.Add`. Every Revit WARNING was deleted
without making it into the receipt. The deletion itself is CORRECT and
stays that way: there is no one to click the modal dialog, and Revit parks
on the UI thread (a live incident with the staircase on 27.07 — the bridge
died on the six calls that followed in a row). What was wrong was the
FORGETTING.

The cost is named by the KIND of outcome, not by frequency. Revit says "I
threw out your lock" (`DimensionUnlocked`, `UndeletedConstraints` — 58
`BuiltInFailures.DimensionFailures` plus 4 `ConstraintFailures` per
`data/api_surface/`, zero drift across six versions), we erase this
silently, the program commits GREEN, and the building carries no declared
relation. For a package whose cardinal invariant is "zero silently-wrong
outcomes", this is a violation of the invariant itself, not an unfinished
detail.

🔴 WHAT EXACTLY IS PINNED HERE, AND WHY BY FOUR DIFFERENT QUESTIONS.
A wire has two ends and a middle, and green at one end says nothing about
the other (the form "a fact produced with no reader"):

    emission    does the C# record the warning BEFORE clearing it
    receipt     does `serving` lift the recorded item into the witness
    history     does it survive `_summarize_tool_result` (only TOP-level
                scalars; a list of dicts is replaced with "collapsed")
    copies      does the rule still have ONE point of text, not four

THE INPUT BUILDS PROD CODE (form 27): the C# is assembled by
`authoring.emit_program` via the same path the parity corpus takes, the
witness is `serving._witness_for_success`, the collapsing is the real
`chat_helpers._summarize_tool_result`. A hand-written fixture here would
answer NO to a question it isn't even able to ask.

THE BOUNDARY, NAMED HONESTLY: this file does not observe a live warning.
It proves that the CHANNEL exists and cannot silently close; how many
warnings arrive on a real building will be answered by the channel itself
once it reaches the deployed service. Before 20.08 the question "what did
Revit tell us" had no source at all, and a zero there would have read as
"no one to ask" (form 4).
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

# 27.08.2026: HOST capability is taken from the PORT. There are no stubs
# on purpose — a test that needs a host must be SKIPPED with a named
# reason, not green by construction.
from kir import ports as _порты

try:
    _summarize_tool_result = _порты.need(_порты.CHAT_HELPERS)._summarize_tool_result
    _НЕТ_ХОСТА = ""
except _порты.PortMissing as _exc:                          # pragma: no cover
    _summarize_tool_result = None
    _НЕТ_ХОСТА = str(_exc)
# 🔴 THE IMPORT WAS RAISED TO MODULE LEVEL (28.08.2026), AND THIS IS NOT A
# MATTER OF TASTE. `generate_fixtures` ON IMPORT does `os.environ.setdefault(
# "KIR_REJECTIONS_PATH", …)` — and it must, otherwise the rejection feed
# would take the real path and parity generation would write into the live
# corpus. But when this import stood INSIDE the function, the environment
# edit happened IN THE MIDDLE of someone else's test, and the environment
# guard (`conftest.py`) accused whoever simply happened to be nearby of the
# leak. At module level it happens during COLLECTION — before the first
# environment snapshot.
from kir.tests.emit_parity_fixtures.generate_fixtures import (  # noqa: E402
    GROUND_SNAPSHOT,
    _parse_and_check,
)
from kir import serving
from kir.emit_utils import (
    failure_channel_reset_cs,
    failure_preprocessor_cs,
    failure_warnings_into_results_cs,
)

CAP = 600

#: One genuine pair from those Revit sends on a locked dimension. The GUID
#: is the identity, the text is localized and cannot serve as identity.
_WARNING_ROW = {
    "guid": "b7f6b7d8-9b5e-4f1a-9c2a-2b0f4a6d1e33",
    "text": "Ограничения не выполнены и были удалены",
    "elements": ["987654"],
}


def _emitted_authoring_cs() -> str:
    """C# of an ordinary writing program — from the PROD FUNCTION, not
    from memory."""

    from kir import ground as ground_mod
    from kir.authoring import emit_program
    from kir.tests.test_authoring import _prog, _wall

    grounded = ground_mod.ground(
        _parse_and_check(_prog([_wall()], intent="стена 6м")), GROUND_SNAPSHOT)
    return emit_program(grounded, "2023", "стена 6м")


def _prod_receipt(payload: dict) -> dict:
    """A success receipt in the exact form `serving` assembles it."""

    witness = serving._witness_for_success("authoring", payload, ["create_wall"])
    result = {"ok": True, "kir": True, "witness": witness,
              "outcome": {"kind": "built"}}
    serving.lift_witness_note(result)
    return result


class TheEmissionRecordsBeforeItDeletes(unittest.TestCase):
    """Order is the whole defect: only what's been recorded can be
    cleared."""

    def test_the_warning_is_recorded_before_it_is_deleted(self) -> None:
        cs = _emitted_authoring_cs()
        add = cs.find("Warned.Add(")
        delete = cs.find("DeleteWarning(")
        self.assertNotEqual(add, -1, "предупреждение нигде не записывается")
        self.assertNotEqual(delete, -1, "снятие предупреждения исчезло — "
                                        "модальное окно паркует Revit")
        self.assertLess(
            add, delete,
            "запись обязана стоять ДО снятия: снять можно только то, что уже "
            "записано, и обратный порядок и есть дефект 20.08")

    def test_the_old_shape_can_never_come_back(self) -> None:
        """`DeleteWarning(...); continue;` — that exact form, verbatim."""
        cs = _emitted_authoring_cs()
        self.assertIsNone(
            re.search(r"DeleteWarning\(__f\);\s*continue;", cs),
            "вернулась форма, которая стирала предупреждение до квитанции")

    def test_identity_is_the_guid_not_the_localised_text(self) -> None:
        """The owner's text is Russian; checking the translation is not
        identity."""
        cs = _emitted_authoring_cs()
        self.assertIn("GetFailureDefinitionId()", cs)

    def test_the_error_channel_did_not_lose_its_own_wiring(self) -> None:
        """The warnings fix must not weaken the ERRORS channel."""
        cs = _emitted_authoring_cs()
        self.assertIn("Seen.Add(", cs)
        self.assertIn("__KirMainFailures.Seen.Count > 0", cs)


class TheRuleHasOneCarrier(unittest.TestCase):
    """There were FOUR copies, and nothing forced them to agree.

    The authority here is a SEARCH OVER THE TREE, not a list of files: a
    ratchet that names a path measures the path (form 25), and this is
    exactly how the four version-check failures became invisible when the
    emitter bodies moved out into `*_emit.py` satellites.
    """

    def test_delete_warning_is_written_in_exactly_one_place(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        carriers = sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*.py")
            if "tests" not in p.parts and "DeleteWarning" in
            p.read_text(encoding="utf-8", errors="replace"))
        self.assertEqual(
            carriers, ["emit_utils.py"],
            "правило «что делать с предупреждением» снова размножилось: "
            + ", ".join(carriers))

    def test_both_buckets_are_reset_together(self) -> None:
        """Forgetting one `Clear()` means carrying someone else's lines
        into your own program.

        Both buckets are static; a program that reset only the errors
        would report the PREVIOUS turn's warnings as its own.
        """
        cs = _emitted_authoring_cs()
        self.assertIn("__KirMainFailures.Seen.Clear();", cs)
        self.assertIn("__KirMainFailures.Warned.Clear();", cs)


class TheReceiptCarriesWhatRevitSaid(unittest.TestCase):

    def test_the_witness_lifts_the_warnings(self) -> None:
        witness = serving._witness_for_success(
            "authoring", {"revit_warnings": [_WARNING_ROW]}, ["create_wall"])
        self.assertEqual(witness.get("revit_warnings"), [_WARNING_ROW])

    def test_silence_carries_no_key_at_all(self) -> None:
        """THE CONTROL WITHOUT WHICH THE PREVIOUS ONE MEANS NOTHING.

        A field that is ALWAYS present does not distinguish "Revit spoke"
        from "Revit stayed silent", and green with it would read exactly
        like green without it.
        """
        witness = serving._witness_for_success("authoring", {}, ["create_wall"])
        self.assertNotIn("revit_warnings", witness)

    def test_the_axes_stay_green_and_the_warning_stands_beside_them(self) -> None:
        """The triple is honest on every axis and lies as a whole — the
        field sits BESIDE it, not inside it.

        What was built matches what was declared: geometry, meaning, and
        topology agree. Whether Revit revoked the declared relation is a
        DIFFERENT question, and mixing it into the axes would mean running
        one code for two outcomes.
        """
        witness = serving._witness_for_success(
            "authoring", {"revit_warnings": [_WARNING_ROW]}, ["create_wall"])
        for axis in ("geometry_ok", "semantic_ok", "topology_ok"):
            self.assertIs(witness.get(axis), True)
        self.assertIn("revit_warnings", witness)

    def test_a_read_only_turn_is_untouched(self) -> None:
        self.assertEqual(
            serving._witness_for_success("query", {"revit_warnings": [_WARNING_ROW]}),
            {"read_only": True})


@unittest.skipIf(_summarize_tool_result is None,
                 "сворачивание результата для чата — дело ХОСТА: " + _НЕТ_ХОСТА)
class ItSurvivesTheHistoryFold(unittest.TestCase):
    """What the model cannot RECALL is not a loop.

    🔴 THE SKIP WAS WIRED IN ON 28.08.2026, AND THE LABEL HAD BEEN WAITING
    FOR IT FROM THE START. The file's header requires: "a test that needs
    a host must be SKIPPED with a named reason, not green by
    construction." The label `_НЕТ_ХОСТА` was being set, but read by NO
    ONE — and without a host three tests failed with `TypeError:
    'NoneType' object is not callable`, that is, a failure about US, in
    the voice of an assertion about the product. The requirement stood in
    prose and did not stand in code.
    """

    def _folded(self, payload: dict) -> str:
        return _summarize_tool_result(
            json.dumps(_prod_receipt(payload), ensure_ascii=False), CAP)

    def test_the_warning_is_named_after_the_fold(self) -> None:
        text = self._folded({"revit_warnings": [_WARNING_ROW]})
        self.assertIn("REVIT СКАЗАЛ", text)
        self.assertIn("Ограничения не выполнены", text)

    def test_the_count_is_printed_so_truncation_cannot_read_as_one(self) -> None:
        rows = [dict(_WARNING_ROW, elements=[str(i)]) for i in range(5)]
        text = self._folded({"revit_warnings": rows})
        self.assertIn("REVIT СКАЗАЛ (5)", text)
        self.assertIn("и ещё 4", text)

    def test_silence_prints_nothing(self) -> None:
        """CONTROL: a line printed always is noise, not signal."""
        text = self._folded({})
        self.assertNotIn("REVIT СКАЗАЛ", text)
        self.assertIn("оси:", text)

    def test_the_note_stays_within_its_own_ceiling(self) -> None:
        """The receipt's ceiling is declared; a new field must not break
        through it."""
        rows = [dict(_WARNING_ROW, text="Ограничение " + "очень длинное " * 20)
                for _ in range(9)]
        note = serving.witness_note(
            serving._witness_for_success(
                "authoring", {"revit_warnings": rows},
                ["create_wall", "set_param"]))
        self.assertLessEqual(len(note), serving._NOTE_CAP)


class ThePreprocessorSourceIsWhole(unittest.TestCase):
    """The digest reads as text — meaning its form is checkable without
    Revit."""

    def test_the_name_travels_and_the_body_does_not(self) -> None:
        main = failure_preprocessor_cs("__KirMainFailures")
        stairs = failure_preprocessor_cs("__KirStairsFailures")
        self.assertIn("private class __KirMainFailures", main)
        self.assertIn("private class __KirStairsFailures", stairs)
        self.assertEqual(
            main.replace("__KirMainFailures", "X"),
            stairs.replace("__KirStairsFailures", "X"),
            "тела разошлись: имена различают ОБЛАСТЬ, а не правило")

    def test_an_error_is_never_deleted(self) -> None:
        """AN ERROR IS NOT CLEARED. The law is unchanged, the argument is
        new.

        🔴 THE DOCSTRING HERE WAS WRONG SINCE 24.08.2026 and is being
        fixed together with the behavior. It used to say "a genuine ERROR
        is still handed back to Revit — it isn't ours." Handing it to
        Revit WAS ITSELF the modal dialog: `RevitAPI.xml` states, verbatim,
        at `Continue`, that the interface will show the error to the user.
        Now the error is RESOLVED once and named, and the unresolvable one
        goes to rollback. Clearing it is still not allowed: `DeleteWarning`
        on an error is "green silence" — the opposite disease with the
        same symptom.

        THE CHECK BECAME STRUCTURAL, NOT LINE-BY-LINE. The previous one
        required `FailureSeverity.Warning` ON THE SAME LINE as
        `DeleteWarning` — that is, it checked the WRITING, not the law,
        and went red on any refactor that preserved the meaning. Today it
        did exactly that — it went red.
        """
        body = failure_preprocessor_cs("__KirMainFailures")
        self.assertIn("DeleteWarning", body, "снятие исчезло вовсе")
        # The body of the warning branch — from the condition to the
        # `continue` that closes it. All clearing must lie INSIDE it.
        head, _, rest = body.partition("if (__sev == FailureSeverity.Warning)")
        self.assertTrue(rest, "ветка предупреждения исчезла")
        branch, _, tail = rest.partition("continue;")
        self.assertTrue(tail, "ветка предупреждения не закрывается continue")
        self.assertIn("DeleteWarning", branch,
                      "снятие вышло из ветки предупреждения")
        self.assertNotIn("DeleteWarning", head + tail,
                         "снятие стоит и вне ветки предупреждения — "
                         "ошибка была бы проглочена")

    def test_continue_is_never_the_answer_to_an_error(self) -> None:
        """🔴 THE WAVE'S MAIN LAW: `Continue` on an error is a modal
        dialog.

        `RevitAPI.xml`, `FailureProcessingResult.Continue`, verbatim: "In
        the absence of any other available handlers, this means that the
        Revit user interface will display any errors to the user for
        resolution".

        Live measurement, 23.08: three programs out of four rolled back
        with `commit status: Pending` while the owner was closing the
        endless "keep joined or disjoin" dialog. The dialog was the CAUSE
        of the rollback, not its consequence.

        Hence an error has exactly two outcomes: resolved ->
        `ProceedWithCommit`, could not resolve -> `ProceedWithRollBack`.
        `Continue` remains only for the case "there were no errors at
        all".
        """
        body = failure_preprocessor_cs("__KirMainFailures")
        self.assertIn("ProceedWithRollBack", body,
                      "неразрешимой ошибке некуда деться, кроме окна")
        self.assertIn("ProceedWithCommit", body,
                      "разрешённая ошибка обязана просить повторный коммит")
        self.assertIn("__fa.ResolveFailure(", body, "разрешение не зовётся")
        # `Continue` must come AFTER both — that is, be the last word,
        # not the first one that happened to be there.
        i_roll = body.index("ProceedWithRollBack")
        i_commit = body.index("ProceedWithCommit")
        i_cont = body.rindex("FailureProcessingResult.Continue")
        self.assertGreater(i_cont, i_roll, "Continue перехватывает откат")
        self.assertGreater(i_cont, i_commit, "Continue перехватывает коммит")

    def test_the_documented_infinite_loop_is_guarded(self) -> None:
        """Repeating a resolution is forbidden — and this is a
        documentation requirement.

        `RevitAPI.xml` at `ResolveFailure`: "the preprocessor code should
        take care to attempt a different resolution the next time the
        failure appears, **to avoid an infinite loop**", and it also
        THROWS if the same failure is resolved twice with the same type.

        We have no other type of resolution, so the attempt is exactly
        one, and a repeat goes to rollback. The owner cranked this very
        cycle by hand: "you click Disjoin — the little window pops up
        again, endlessly."
        """
        body = failure_preprocessor_cs("__KirMainFailures")
        self.assertIn("Attempts", body, "счётчика попыток нет")
        self.assertIn("__tried >= 1", body,
                      "порог попытки не назван — цикл ничем не ограничен")

    def test_resolved_errors_are_not_folded_into_warnings(self) -> None:
        """A resolved error is a THIRD bucket, not a line among the
        warnings.

        Revit decides for us (disjoins the walls), and the reader must
        see EXACTLY THAT. Merging it into one list would make Revit's
        decision indistinguishable from our own observation — and those
        are different facts with a different cost.
        """
        body = failure_preprocessor_cs("__KirMainFailures")
        self.assertIn("Resolved", body)
        self.assertIn("__r[\"resolution\"]", body,
                      "подпись применённого разрешения не записана")
        into = failure_warnings_into_results_cs("__KirMainFailures")
        self.assertIn("revit_errors_resolved", into,
                      "разрешённые ошибки не доезжают до квитанции")
        self.assertIn("revit_warnings", into, "предупреждения потерялись")

    def test_attempts_reset_with_the_other_buckets(self) -> None:
        """The attempt counter is reset together with the buckets, and
        this is not housekeeping.

        It is static, and programs run one after another in ONE Revit
        process: without zeroing it, the second program would see
        "already tried" left by the first and would go to rollback
        without even attempting. The building migration on 23.08 — 55
        programs in a row, meaning 54 false rollbacks.
        """
        reset = failure_channel_reset_cs("__KirMainFailures")
        for bucket in ("Seen", "Warned", "Resolved", "Attempts"):
            self.assertIn(f"__KirMainFailures.{bucket}.Clear();", reset,
                          f"{bucket} не сбрасывается")


if __name__ == "__main__":
    unittest.main()
