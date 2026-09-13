"""THE SPATIAL TAG IS A DIFFERENT CLASS, AND WHAT TELLS THEM APART IS THEIR
TARGET, NOT THE AUTHOR.

WHY. Measured on 13.08.2026 on `len_ar_me_r24_v1` — the second residential
building read in full (all ten stages, 57 809 elements): **7 067** elements
were falling into the `unsupported_forward_signature` atom for a single
reason — "a tag of kind `spatial` is a SpatialElementTag (room/area/space),
and the forward pass builds a tag by exactly one route, IndependentTag.
Create". This is the largest single cause of this kind on the building.

The reverse pass has been ready since 30.07: `tag_extract` reads BOTH kinds
and extracts the view, the point, the target, the leader, and the type. It
was the LIFTER that was refusing, and refusing ON PURPOSE, naming the route.
The hole was in the FORWARD pass.

WHAT IS PINNED DOWN HERE is the shape of the emitted C#, not Revit's
behavior. Live, the op is NOT VERIFIED, and this is said out loud: in which
axes `UV` is expressed for `NewRoomTag` is not settled by compilation. A
guess would be a silently offset tag, so the point is not guessed at — the
`head_at` witness reads `TagHeadPosition` back in the SAME view basis in
which it was placed, and a wrong axis will produce a TYPED VIOLATION, not a
silent shift.

ALL SIX VERSIONS are closed by compilation separately (13.08): a program
with a wall and a tag compiles 6/6; the `NewRoomTagZZZ` and `RoomTag.RoomZZZ`
controls give 6/6 CS1061 — meaning the branch is not dead and its members
are not invented.
"""

from __future__ import annotations

import unittest

from kir.compiler import compile_program


def _emit(revit_version: str = "2026", **tag_extra: object) -> str:
    tag: dict[str, object] = {
        "op": "create_tag", "id": "TAG1",
        "in_view": {"by": "element_id", "value": 900},
        "target": {"by": "ref", "value": "W1"},
        "at": [3000, 800],
    }
    tag.update(tag_extra)
    program = {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 100}},
        tag,
    ]}
    out = compile_program(program, revit_version=revit_version,
                          snapshot=None, bulk=True)
    assert out.ok, [d.as_dict() for d in (out.diagnostics or [])][:3]
    return out.csharp


class TheBranchIsChosenByTheTargetAtRuntime(unittest.TestCase):
    """The tag's class follows from its target, and it is Revit that
    decides this, not us."""

    def setUp(self) -> None:
        self.cs = _emit()

    def test_the_target_is_asked_whether_it_is_spatial(self) -> None:
        # The branch lives in C#, not in Python, BY CONSTRUCTION:
        # `create_tag.target` has no pool (`ref_kinds=ELEMENT`), the
        # target's class is unknown at emission time.
        self.assertIn("as SpatialElement", self.cs)

    def test_each_spatial_kind_has_its_own_creator(self) -> None:
        for member in ("NewRoomTag", "NewSpaceTag", "NewAreaTag"):
            with self.subTest(member):
                self.assertIn(member, self.cs)

    def test_the_independent_path_is_untouched(self) -> None:
        # The branch was ADDED, not a replacement for the previous one: 851
        # tags in the corpus and the entire previous witness must travel
        # the old road byte for byte.
        self.assertIn("IndependentTag.Create(", self.cs)

    def test_the_base_property_absent_from_the_dlls_is_never_asked(self) -> None:
        # Case #78: `SpatialElementTag.SpatialElement` is documented in all
        # six XML files and IS ABSENT from all six DLLs. A side stage got
        # burned on it on 30.07 — the body did not compile on ANY version,
        # meaning tags were not being read anywhere. The target is taken
        # from the SUBCLASS.
        self.assertNotIn(".SpatialElement;", self.cs)
        self.assertNotIn(".SpatialElement ", self.cs)


class EveryRefusalNamesItsSubject(unittest.TestCase):
    """The refusal was designed together with the success path, not after
    it."""

    def setUp(self) -> None:
        self.cs = _emit()

    def test_an_unplaced_spatial_element_is_refused(self) -> None:
        # Revit gives GARBAGE, not an error, on an unplaced room — which is
        # why the check is ours, not its.
        self.assertIn("НЕ РАЗМЕЩЁН", self.cs)
        self.assertIn(".Location == null", self.cs)

    def test_a_leader_is_refused_with_its_reason(self) -> None:
        # For a tag WITH a leader, the point means the END OF THE LEADER,
        # while what is checked is the HEAD. A silent drift of the head is
        # not caught by comparing on the head.
        self.assertIn("КОНЕЦ ВЫНОСКИ", _emit(leader=True))

    def test_the_leader_guard_is_absent_when_no_leader_was_asked(self) -> None:
        """A guard without a trigger is a dead branch, not a safety margin.

        The first edition always wrote `if (false) { отказ }`: a
        constantly-false guard. For witnesses, exactly this shape is
        rejected by `translation_cert.analyze_witness_cs`; in creation the
        certificate does not look at this, and it would have lived
        unnoticed. BOTH sides are checked — it appears on request and is
        absent without one.
        """
        self.assertNotIn("КОНЕЦ ВЫНОСКИ", self.cs)
        self.assertNotIn("if (false)", self.cs)

    def test_an_area_outside_a_plan_view_is_refused_by_the_view_kind(self) -> None:
        self.assertIn("ViewPlan", self.cs)
        # The refusal must name the ACTUAL kind of the view, not just say
        # "wrong view": otherwise the next move is unknown to the reader.
        self.assertIn(".ViewType.ToString()", self.cs)

    def test_an_unknown_spatial_kind_is_refused_rather_than_left_null(self) -> None:
        # Without this branch `__el_` would remain null, and the reason
        # would be lost behind a generic "returned null".
        self.assertIn("__ClassName(__se_TAG1)", self.cs)
        self.assertNotIn(".GetType().Name", self.cs)


class TheWitnessReadsTheClassThatCarriesTheAnswer(unittest.TestCase):

    def setUp(self) -> None:
        self.cs = _emit()

    def test_the_binding_is_read_from_each_subclass(self) -> None:
        for member in (".Room", ".Area", ".Space"):
            with self.subTest(member):
                self.assertIn(member, self.cs)

    def test_the_head_is_read_from_whichever_class_the_tag_is(self) -> None:
        self.assertIn("as IndependentTag", self.cs)
        self.assertIn("SpatialElementTag)", self.cs)

    def test_the_head_goes_through_the_same_view_basis_as_the_placement(self) -> None:
        # The inversion must be EXACT, not a similar-looking formula
        # defined elsewhere: otherwise a wrong `UV` axis would remain
        # invisible, and that axis is the one thing we do not know about
        # this op.
        self.assertIn("RightDirection", self.cs)
        self.assertIn("UpDirection", self.cs)


class TheVersionSurfaceDidNotMove(unittest.TestCase):
    """The version-dependent refusal site has remained exactly one, and
    this is checked.

    `tag_type` refused on 2021 before and still refuses AT EMISSION time
    (`IndependentTag.Create(symId,...)` only appeared in 2022). For a
    spatial tag the type is set by `ChangeTypeId` only AFTER creation, and
    the temptation was to move the refusal into execution. Moving it would
    have shifted the surface of version-fragility watched by
    `test_version_fragile_asks_the_emitter` — so the 2021 behavior has not
    been touched by a single byte.
    """

    def test_tag_type_on_2021_is_still_an_emit_time_refusal(self) -> None:
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "height_mm": 3000, "level": {"by": "element_id", "value": 100}},
            {"op": "create_tag", "id": "TAG1",
             "in_view": {"by": "element_id", "value": 900},
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800],
             "tag_type": {"by": "element_id", "value": 777}},
        ]}
        out = compile_program(program, revit_version="2021",
                              snapshot=None, bulk=True)
        self.assertFalse(out.ok)
        codes = {d.code for d in (out.diagnostics or ())}
        self.assertIn("KIR-E003", codes)

    def test_the_type_is_applied_after_creation_only_when_asked(self) -> None:
        self.assertNotIn("ChangeTypeId", _emit())
        self.assertIn("ChangeTypeId",
                      _emit(revit_version="2022",
                            tag_type={"by": "element_id", "value": 777}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
