"""Three refuting tests: what HANGS, and what LIES.

A refusal is a normal, safe outcome: it is typed and carries a route. These
three defects belong to a different class — each violates the system's single
invariant of "zero silently-wrong outcomes":

* `create_stairs` left Revit with a modal dialog open, and the bridge died on
  EVERY subsequent call (observed live on 27.07: the stairs got built, then
  six «Execution was cancelled before Revit started it» in a row);
* `KIR-X003` claimed «элемент/тип исчез между grounding и исполнением» on
  ANY runtime failure — including «NewFamilyInstance вернул null» and
  «NewElbowFitting: failed to insert elbow», where nothing had actually
  vanished;
* the `beam_types` pool handed out point-based families that `create_beam`
  cannot use — a fact known at ground time was surfacing at runtime.
"""
from __future__ import annotations

import unittest

from kir import serving
from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT


def _stairs_program() -> dict:
    return {"ir_version": "1.0", "intent": "лестница",
            "ops": [{"op": "create_stairs", "id": "S",
                     "p0_mm": [0, 0], "p1_mm": [4000, 0],
                     "base_level": {"by": "element_id", "value": 42},
                     "top_level": {"by": "element_id", "value": 43},
                     "width_mm": 1200}]}


class StairsMustNotLeaveAModalDialog(unittest.TestCase):
    """`create_stairs` is the only op with its own program template, and it
    had NONE of what every normal program has: no SetFailuresPreprocessor, no
    SetForcedModalHandling(false), no dismissal of warnings. Its own handler
    on StairsEditScope.Commit returned Continue without dismissing them —
    unlike the main one."""

    def setUp(self) -> None:
        out = compile_program(_stairs_program(), revit_version="2023")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.cs = out.csharp

    def test_transaction_installs_a_failure_preprocessor(self):
        self.assertIn("SetFailuresPreprocessor", self.cs)

    def test_modal_handling_is_disabled(self):
        self.assertIn("SetForcedModalHandling(false)", self.cs)

    def test_warnings_are_swallowed_not_shown(self):
        self.assertIn("DeleteWarning", self.cs)

    def test_scope_commit_preprocessor_also_deletes_warnings(self):
        """StairsEditScope.Commit takes its OWN handler — a warning can still
        surface there, already outside the transaction."""
        scope = self.cs[self.cs.index("__KirStairsFailures : IFailuresPreprocessor"):]
        self.assertIn("DeleteWarning", scope)


class RefusalMessageMustNotInventACause(unittest.TestCase):
    """`__Refuse` tags ALL runtime failures with one marker, stale_or_failed,
    and serving translated it into «элемент/тип исчез между grounding и
    исполнением». On the «NewFamilyInstance (балка) вернул null» failure this
    is a lie: nothing had vanished, and the user was sent off to hunt for
    model drift."""

    def _translate(self, message: str) -> dict:
        return serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "X",
                       "message": message}})

    def test_api_null_is_not_reported_as_a_vanished_element(self):
        """09.08.2026: the CODE changed here too, and this is a continuation
        of the same fix, not its reversal. The 27.07 patch split the two
        worlds apart by TEXT, but left them one shared code, X003 — and a
        reader of the corpus sees the code, not the prose: a measurement over
        1306 lines showed that all 38 living X003s are unattributable for
        exactly this reason. A runtime failure now carries its own KIR-X009;
        X003 remains what `diag.py` declares it to be — model drift."""
        diag = self._translate("NewFamilyInstance (балка) вернул null")
        self.assertEqual(diag["code"], "KIR-X009")
        self.assertNotIn("исчез", diag["message_ru"])
        self.assertIn("null", diag["detail"])

    def test_fitting_failure_is_not_reported_as_a_vanished_element(self):
        diag = self._translate(
            "NewElbowFitting: failed to insert elbow. (angle=90.0deg, 100.0/100.0mm)")
        self.assertNotIn("исчез", diag["message_ru"])

    def test_a_real_grounding_drift_still_says_so(self):
        """The message is not gutted: the genuine case keeps its previous
        text, otherwise we would simply have made the diagnostic useless."""
        diag = self._translate(
            "level: уровень не найден (модель изменилась после grounding)")
        self.assertEqual(diag["code"], "KIR-X003")
        self.assertIn("исчез", diag["message_ru"])


class LevelGuardMustNotClaimDriftForAWrongType(unittest.TestCase):
    """Measured live on 27.07 twice (`create_beam` x16, two runs ~74 min
    apart, one editor, one local file, journalctl kukai-backend): X003 said
    «уровень не найден (модель изменилась после grounding)» 130-460ms AFTER
    `ground_snapshot` had just returned this very same level catalog —
    physically too little time for anyone to have manually deleted a level
    between two calls of one bridge.

    The cause: `_level_expr` emits ONE static C# message for
    `doc.GetElement(id) as Level == null`, and that null can arise from TWO
    different causes — the id genuinely vanished from the document
    (consistent with drift), OR the id exists but does not point to a Level.
    The second cause does NOT by itself prove a grounding bug: `ground.py`
    documents `by: element_id` as an INTENTIONAL pass-through
    (existence/type are re-checked ONLY here, at runtime — see the docstring
    of the `ground.py` module), so a wrong id could just as well have come
    from the caller. The fix therefore does not invent a cause: the message
    names the OBSERVED fact (wrong type) and honestly states that the cause
    is not determined at runtime — the same discipline that
    `RefusalMessageMustNotInventACause` already applied to «NewFamilyInstance
    вернул null» / «NewElbowFitting: failed to insert elbow», but one layer
    deeper: there, `_translate_runtime` was guessing the cause from Revit's
    RAW text; here, the C# guard itself decided on Revit's behalf, in
    advance, what had happened, and always called it drift — ANY null cast,
    including «никогда не был уровнем»."""

    def _beam_cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "балка", "ops": [{
            "op": "create_beam", "id": "B",
            "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_guard_distinguishes_absent_from_wrong_type(self):
        """Before the fix, `as Level == null` leads to a SINGLE static
        message regardless of the cause: the C# never looks at the actual
        type of what sits at that id. This check requires a second branch —
        otherwise `_translate_runtime` cannot honestly distinguish «исчез»
        from «не тот класс», no matter how many signatures you invent in
        Python: the information simply isn't in the message the compiler
        emitted."""
        cs = self._beam_cs()
        # The class is read via the __ClassName helper from the preamble, not
        # by querying the runtime environment for the type: that form of
        # writing is rejected by the version-bridge validator prior to
        # 06.07.2026 (a live refusal on 04.08.2026). The contract is
        # unchanged — the SECOND branch must name the actual class, otherwise
        # there will again be nowhere to distinguish «исчез» from «не тот
        # класс».
        self.assertIn("__ClassName(__lv_raw_", cs)

    def test_wrong_type_message_does_not_claim_drift(self):
        """The «не тот тип» message must not carry the «после grounding»
        signature — otherwise `_translate_runtime` will again call it drift,
        the same tautology under new text."""
        diag = serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "B",
                       "message": ("id уровня резолвится не в Level, а в Wall "
                                   "— причина (дрейф модели или неверный id) "
                                   "не определена рантаймом")}})
        self.assertNotIn("исчез", diag["message_ru"])

    def test_wrong_type_message_does_not_blame_grounding(self):
        """`ground.py` documents `by: element_id` as a pass-through without a
        type check (existence/type are re-checked only at runtime) — meaning
        a wrong id could have come from the caller's side, not from a
        grounding bug. The message must name the OBSERVED fact, not invent
        whose bug it is."""
        cs = self._beam_cs()
        seg = cs[cs.index("id уровня резолвится не в Level"):]
        clause = seg[:seg.index(";")]
        self.assertNotIn("grounding привязал", clause)
        self.assertIn("не определена", clause)

    def test_genuine_absence_still_claims_drift(self):
        """And conversely: when the element is TRULY absent (raw == null),
        the fix must keep the previous honest text — not gut the diagnostic
        in the other direction (symmetric to
        `test_a_real_grounding_drift_still_says_so`)."""
        diag = serving._translate_runtime(
            {"error": "stale_or_failed",
             "layer": {"error": "stale_or_failed", "op_id": "B",
                       "message": "уровень не найден (модель изменилась после grounding)"}})
        self.assertIn("исчез", diag["message_ru"])


class BeamPoolMustNotOfferPointPlacedFamilies(unittest.TestCase):
    """Measured 27.07: all 36 frame families in the real building are
    FamilyPlacementType.OneLevelBased (point-based). NewFamilyInstance(Line,
    …, Beam) on such a family returns null, and the pool was handing them out
    as if nothing were wrong. Ground must refuse with KIR-G104 «пусто в
    модели» — an honest «не на чем» instead of a runtime null."""

    def test_snapshot_pool_filters_by_placement_type(self):
        from kir.open_model import GROUND_SNAPSHOT_CS
        line = next(ln for ln in GROUND_SNAPSHOT_CS.splitlines()
                    if '__AddPool("beam_types"' in ln)
        self.assertIn("FamilyPlacementType", line)

    def test_query_types_pool_filters_by_placement_type(self):
        from kir.compiler import _TYPE_POOL_COLLECTOR_CS
        self.assertIn("FamilyPlacementType", _TYPE_POOL_COLLECTOR_CS["beam_types"])

    def test_other_symbol_pools_are_untouched(self):
        """Point placement is normal for windows/doors/columns; the filter
        applies ONLY to beams, where the emitter requires a curve."""
        from kir.compiler import _TYPE_POOL_COLLECTOR_CS
        for pool in ("window_symbols", "door_symbols",
                     "column_symbols_structural", "foundation_symbols"):
            self.assertNotIn("FamilyPlacementType", _TYPE_POOL_COLLECTOR_CS[pool], pool)


class BeamLevelWitnessMustReadTheParameterABeamActuallyHas(unittest.TestCase):
    """Measured 27.07 by direct probing: for a beam created with
    NewFamilyInstance(Line, symbol, level, StructuralType.Beam), the level
    lives ONLY in INSTANCE_REFERENCE_LEVEL_PARAM. Everything else is empty:

        INSTANCE_REFERENCE_LEVEL_PARAM = 172458 («L_01_+0.000»)
        FAMILY_LEVEL_PARAM   = -1
        SCHEDULE_LEVEL_PARAM = -1
        LEVEL_PARAM          = no such parameter
        fi.LevelId           = -1

    The witness's shared chain did not know about this parameter, so the beam
    was rolled back with «level binding mismatch (topology)» EVEN WHEN the
    level was exactly the one requested — that is, the witness was accusing a
    correct build. The chain is short-circuited, so appending to the tail
    changes nothing for ops whose earlier parameter is already filled."""

    def _beam_cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "балка", "ops": [{
            "op": "create_beam", "id": "B",
            "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_beam_witness_consults_the_reference_level_parameter(self):
        self.assertIn("INSTANCE_REFERENCE_LEVEL_PARAM", self._beam_cs())

    def test_beam_does_not_assert_a_level_the_api_never_promised(self):
        """Second measurement of the same probe: Revit bound the beam NOT to
        the passed level — L_01 @ 0mm was passed, the curve is at Z=3000, the
        binding went to L_01ДОО1_+2.500 (nearest below). So `level` in
        NewFamilyInstance(Line, …, Beam) is placement context, not a promise,
        and requiring equality would mean rolling back a correct beam. The
        witness checks for the PRESENCE of a level, and reads which one from
        the result; the position, meanwhile, is pinned at both ends in 3D
        with a 5mm tolerance."""
        cs = self._beam_cs()
        self.assertIn("нет опорного уровня (topology)", cs)
        self.assertNotIn("level binding mismatch", cs)
        self.assertIn('"reference_level_id"', cs)

    def test_level_chain_skips_a_link_that_holds_no_element(self):
        """`HasValue` is true even for InvalidElementId — measured on a beam:
        `FAMILY_LEVEL_PARAM: HasValue=True, AsElementId=-1`. The chain broke
        on an empty link and compared «-1» against the expected id. The
        transition must require a REAL id, not mere presence."""
        # place_family is the op that actually emits the chain (the wall
        # reads WALL_BASE_CONSTRAINT directly and never reaches the chain).
        out = compile_program({"ir_version": "1.0", "intent": "семейство", "ops": [{
            "op": "place_family", "id": "P", "xyz": [0, 0, 0],
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 1000}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("ElementId.InvalidElementId) __lp =", out.csharp)


class RollbackMustNameItsCause(unittest.TestCase):
    """Assembly of the whole building died on «transaction commit status:
    RolledBack» and said nothing further. Revit rolls back this way when it
    hits an ERROR-level failure: our handler was dismissing warnings and
    DELIBERATELY not suppressing the error — but also wasn't recording it, so
    the cause was lost irrecoverably.

    A live probe on 27.07 showed the text is available: the message
    intercepted via FailuresAccessor can be read (`GetSeverity()` +
    `GetDescriptionText()`). A silent rollback is exactly the mute outcome
    that this compiler forbids."""

    def _cs(self) -> str:
        out = compile_program({"ir_version": "1.0", "intent": "стена", "ops": [{
            "op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
            "level": {"by": "element_id", "value": 42}}]},
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        return out.csharp

    def test_errors_are_collected_not_only_warnings_deleted(self):
        cs = self._cs()
        self.assertIn("GetDescriptionText()", cs)
        self.assertIn("public static List<string> Seen", cs)

    def test_warnings_are_still_swallowed(self):
        """Warnings are still dismissed: otherwise the dialog would freeze
        Revit."""
        self.assertIn("DeleteWarning", self._cs())

    def test_failure_names_the_failing_elements_not_only_the_type(self):
        """The refusal «Экземпляры ДВг_21х10.5_П_900 в свету ничего не
        вырезают» names the TYPE, and there are seven such doors in the
        building. The guilty instance cannot be found from the type alone —
        but FailureMessageAccessor.GetFailingElementIds() exists in all six
        versions and returns exactly the ids that Revit is complaining about.
        Without them, every subsequent check hits the general area instead of
        the target."""
        cs = self._cs()
        self.assertIn("GetFailingElementIds()", cs)

    def test_rollback_refusal_carries_the_revit_text(self):
        cs = self._cs()
        self.assertIn("transaction commit status: ", cs)
        self.assertIn("| Revit: ", cs)

    def test_the_log_is_cleared_before_each_run(self):
        """The list is static and outlives the run — otherwise the next
        program will get someone else's cause."""
        cs = self._cs()
        self.assertIn("__KirMainFailures.Seen.Clear()", cs)
        # What matters is not the order relative to Start, but that the
        # cleanup precedes ANY operation: only then does what was collected
        # belong to this run.
        self.assertLess(cs.index("Seen.Clear()"), cs.index("Wall.Create"))


if __name__ == "__main__":
    unittest.main()
