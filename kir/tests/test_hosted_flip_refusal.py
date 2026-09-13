"""A family that Revit refuses to flip must not kill the program.

WHERE THE RULE COMES FROM — THE LIVE CORPUS. `data/telemetry/kir_witness.jsonl`,
all 16 red `create_door` lines (21.07, Revit 2026): 4 — `KIR-X004` (violated
postconditions), 12 — `KIR-X003` (runtime failures, the cause is NOT recorded
in the corpus: not one of the 1306 lines carries a field with the failure
text). Three distinct violations, verbatim:

    2026-07-21T16:26:28  KIR-X004  committed=false
        ["PD: hand flip state mismatch (semantic)",
         "PD: facing flip state mismatch (semantic)"]
    2026-07-21T16:05:06  KIR-X004  committed=false
        ["PD: mirrored state mismatch (semantic)",
         "PD: facing flip state mismatch (semantic)"]
    2026-07-21T12:40:36  KIR-X004  committed=false
        ["PD: mirrored state mismatch (semantic)"]

In all three, `geometry_ok=true` and `topology_ok=true`: the door landed in
the right wall, at the right point, at the right elevation. ONE leaf failed
to match — and the whole program rolled back (`committed=false`).

WE NAME THE MEASURED COST, NOT A PRETTY ONE. All 16 red lines are programs
made of TWO ops (`create_wall`+`create_door`), so the corpus lost one correct
wall per door. What matters is not this number but the SCALE of the
mechanism: the witness's verdict is program-scoped by construction, so on a
rebuild the same defect costs a whole chunk of the materializer
(`MAX_BULK_OPS`), while a refusal under `per_op` costs exactly its own op.

WHOSE FACT THIS IS. Not a "silently inserted default": `tests/test_silent_defaults.py`
measured on 31.07 that flips do NOT land in a normalized op when the caller
is silent (six silent defaults, none of them flips). So the caller NAMED the
flips, and `CanFlipHand`/`CanFlipFacing=false` is a fact about the FAMILY:
Revit refuses to change this type's handing. There is nothing to do about it
after the fact: the one workaround — `MirrorElements(mirrorCopies=true)` — is
forbidden forever by a live measurement on 27.07 (SOB6.2), where mirroring a
hosted door carried off the geometry of OTHER doors on another host to point
[0,0], and a per-op SubTransaction did not contain it (`8a8c3038`).

WHAT WAS WRONG. The fact about the family was expressed as a VIOLATED
POSTCONDITION, and that is program-scoped: the witness's verdict fails the
whole transaction, no matter how many ops are in it. Yet `place_family`, in
the same file, has a REFUSAL for exactly this case, not a postcondition —
meaning the compiler behaved in two different ways in the same situation,
and hosted was the side where the whole program paid.

WHAT SHOULD BE. A typed refusal that NAMES the family and the NEXT MOVE (take
a different type). Under `per_op` it carries off only its own op — the
neighbors remain committed; under `atomic` (a single-op program) the
rollback is honest and unavoidable, but it now has a named cause. The rule
"no mirrors on hosted" is not weakened by a single byte in the process: a
refusal is the ABSENCE of an action, not a new action.

THE MIRROR IS ALREADY CLOSED, NOT HERE, AND IT MATTERS NOT TO FIX IT TWICE.
A hosted instance has no lever for `Mirrored` at all: since F5 v4 the emitter
does not set a mirror (`mirror = ""`), and `Mirrored` is a DERIVED trait (=
Hand XOR Facing, live probes P2/P3/P6 on 21.07). Five of the ten violations
of this cluster in the corpus are exactly `mirrored` (three of them on
`place_family`). All of them are removed BEFORE emission:
`authoring_validation` refuses the contradictory triple at parse time
(`KIR-T002`, «mirrored — производное состояние»), and that refusal already
stood in the tree. Here it is only pinned down by a test — only the
`hand`/`facing` branches changed.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_fw_queue.jsonl"))

from kir.compiler import compile_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _door(**extra):
    op = {"op": "create_door", "id": "PD",
          "host": {"by": "ref", "value": "W1"}, "offset_mm": 1000}
    op.update(extra)
    return op


def _prog(*ops):
    return {"ir_version": "1.0", "intent": "двери",
            "ops": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                     "p1_mm": [6000, 0],
                     "level": {"by": "element_id", "value": 42}},
                    *ops]}


def _compile(*ops, isolation: str = "atomic"):
    return compile_program(copy.deepcopy(_prog(*ops)), revit_version="2023",
                           snapshot=GROUND_SNAPSHOT, bulk=True,
                           isolation=isolation)


def _cs(*ops, isolation: str = "atomic") -> str:
    out = _compile(*ops, isolation=isolation)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


class AFamilyThatCannotFlipMustRefuseItsOwnOp(unittest.TestCase):
    """The refuting test for the corpus lines at 16:26:28 and 16:05:06."""

    def test_hand_flip_that_revit_forbids_is_a_refusal_not_a_violation(self):
        """`CanFlipHand=false` must refuse ON THE SPOT, not linger until the
        postcondition. Before the fix, this was `if (CanFlipHand) {
        flipHand(); }` with no else branch — an unreachable flip vanished
        silently, and the only trace left was «PD: hand flip state mismatch
        (semantic)», that is, a program-wide rollback."""
        cs = _cs(_door(hand_flipped=True))
        # We are checking precisely the unreachability branch: a refusal must
        # stand behind `!CanFlipHand`, not emptiness.
        self.assertIn("if (!__el_PD.CanFlipHand)", cs)
        self.assertIn("__el_PD.flipHand();", cs)

    def test_facing_flip_that_revit_forbids_is_a_refusal_not_a_violation(self):
        cs = _cs(_door(facing_flipped=True))
        self.assertIn("if (!__el_PD.CanFlipFacing)", cs)
        self.assertIn("__el_PD.flipFacing();", cs)

    def test_the_refusal_names_the_family_and_the_next_move(self):
        """A refusal without a next move is a dead end. The message must name
        both the FAMILY (which specific type won't flip) and what to do
        next."""
        cs = _cs(_door(hand_flipped=True, facing_flipped=True))
        # The family name — via `FamilySymbol.Family` (documented in all six
        # RevitAPI.xml), not via `FamilySymbol.FamilyName` (0 of 6).
        self.assertIn("__sy_PD.Family.Name", cs)
        self.assertIn("выберите другой тип двери", cs)
        self.assertIn("не допускает смену стороны навески (CanFlipHand=false)",
                      cs)
        self.assertIn(
            "не допускает смену направления открывания (CanFlipFacing=false)",
            cs)

    def test_a_window_names_its_own_noun(self):
        """`_emit_hosted` also serves the window — the next move must be
        about the window, otherwise the advice leads the wrong way."""
        cs = _cs({"op": "create_window", "id": "WN",
                  "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
                  "facing_flipped": True})
        self.assertIn("выберите другой тип окна", cs)

    def test_mirrored_without_a_lever_is_already_refused_at_parse_time(self):
        """The 12:40:36 line (the lone «PD: mirrored state mismatch») is
        closed elsewhere, NOT here, and that is worth stating so it isn't
        fixed twice.

        A hosted instance has no lever for `Mirrored` at all: since F5 v4 the
        emitter sets no mirror, and `Mirrored` is a DERIVED trait (= Hand XOR
        Facing, live probes on 21.07). `authoring_validation` already refuses
        at PARSE time, before any emission and before the live loop: an
        unreachable requirement never reaches Revit."""
        out = _compile(_door(mirrored=True))
        self.assertFalse(out.ok)
        codes = {d.code for d in out.diagnostics}
        self.assertIn("KIR-T002", codes)
        self.assertTrue(any("производное состояние" in (d.message_ru or "")
                            for d in out.diagnostics))

    def test_mirrored_with_a_lever_stays_a_witnessed_consequence(self):
        """When the flip lever is present, Mirrored is a consequence of what
        WE set (= Hand XOR Facing), and checking it is legitimate. There must
        be no refusal here, otherwise we would be refusing something
        achievable."""
        cs = _cs(_door(mirrored=True, hand_flipped=True))
        self.assertIn("mirrored state mismatch (semantic)", cs)


class TheRefusalIsOpScopedUnderPerOp(unittest.TestCase):
    """What it's all for: under `per_op` a refusal carries off ITS OWN op,
    not the neighbors."""

    def test_per_op_throws_the_op_local_sentinel(self):
        cs = _cs(_door(hand_flipped=True), isolation="per_op")
        # `refuse_stmt` is the sole owner of the refusal form; under per_op
        # that is `throw __OpRefuse`, which is swallowed by that same op's
        # catch.
        self.assertIn("throw __OpRefuse(\"PD\"", cs)
        # A whole-program form inside a wrapped create is forbidden
        # (KIR-E005).
        head = cs[:cs.index("// witness")] if "// witness" in cs else cs
        self.assertNotIn("__t.RollBack(); return __Refuse(\"PD\"", head)

    def test_atomic_still_rolls_back_but_names_the_cause(self):
        cs = _cs(_door(hand_flipped=True))
        self.assertIn("__t.RollBack(); return __Refuse(\"PD\"", cs)


class TheNeverMirrorLawIsUntouched(unittest.TestCase):
    """The F5 v4 law (`8a8c3038`) — the most expensive piece of knowledge in
    this seam."""

    def test_no_mirror_call_survives_on_any_hosted_flip_combination(self):
        for kwargs in ({"mirrored": True, "hand_flipped": True},
                       {"hand_flipped": True, "facing_flipped": True},
                       {"facing_flipped": True},
                       {"mirrored": False, "hand_flipped": False,
                        "facing_flipped": False}):
            with self.subTest(**kwargs):
                self.assertNotIn("MirrorElements", _cs(_door(**kwargs)))

    def test_a_door_that_asks_for_nothing_emits_no_flip_branch_at_all(self):
        """«What's absent stays absent»: a silent caller gets neither a flip,
        nor a refusal, nor a postcondition."""
        cs = _cs(_door())
        for marker in ("CanFlipHand", "CanFlipFacing", "flipHand", "flipFacing",
                       "MirrorElements", "mirrored state mismatch",
                       "hand flip state mismatch", "facing flip state mismatch"):
            self.assertNotIn(marker, cs, marker)


if __name__ == "__main__":
    unittest.main()
