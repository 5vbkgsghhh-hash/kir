"""A GREEN VERDICT MUST SURVIVE EVERY NAMED CHECK.

Audit findings `F-326` and `F-327` (P0), `kir/viewer/compilability.py`. One
class: the indicator declares `state="ok"` — "compiles" — while the check it
itself names either FAILED or was never run.

🔴 CORPUS COVERAGE MEASUREMENT 30.08.2026 (mine, turn 1): the denominator is
64 decompiles that have both raised ops (`lift_cache`) and a document type
snapshot (`open_model.profile.json`); 55 of them have a passport and roll up
into 12 buildings.

    BEFORE: state=ok  grounding=refused   62 decompiles  (11 of 12 buildings)
            state=ok  grounding=ok         2 decompiles
    AFTER:  state=refused grounding=refused 62
            state=ok      grounding=ok       2      <- the green ones stayed green

On `clash_final`, `ground` itself returns 441 diagnostics, the first ones
being KIR-G101 «levels: «Этаж 2» не найден», «wall_types: «Типовой - 200мм»
не найден». That is, the main green verdict stood while a snapshot of the
document's OWN types refutes the program.

`F-326`: `verdict.state` was set BEFORE grounding and never revisited
afterward.
`F-327`: when `programs_evicted > 0`, `check_session` wrote the reason
(«вытеснено и НЕ ПРОВЕРЕНО») and did NOT touch `state`; the module's own
comment calls such a verdict a lie, verbatim.

🔴 A THIRD CASE, FOUND BY THE MEASUREMENT AND NAMED IN NO PACKAGE: when the
plan failed, `planned` is empty, the grounding loop makes NOT A SINGLE
check — and the field declared `grounding="ok"` with the note «0 программ
заземлились». Green, having checked nothing.

NO NEW STATE IS INTRODUCED. The tristate stays as before: `refused` already
means "there is a NAMED refusal" (the grounding refusal is named and sits
in `grounding_note`), and `unknown` means "there is nothing to judge by,
and this is NOT 'everything is fine'", which is exactly an incomplete
batch. A found refusal is STRONGER than not-knowing and is not downgraded
to `unknown`: a fact remains a fact.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from kir.viewer import compilability as C

_LEVEL = {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}


def _wall(level_name: str) -> dict:
    return {"op": "create_wall", "id": "w0", "p0_mm": [0, 0],
            "p1_mm": [5000, 0], "height_mm": 3000,
            "level": {"by": "name", "value": level_name}}


def _snapshot() -> dict:
    """A snapshot in the FORM THAT `ground` READS: a FLAT pool -> list dict
    (header of `ground.py:22`), not the profile's `pools` list.

    🔴 THE FIRST EDIT OF THIS FILE, AND MY OWN COVERAGE MEASUREMENT, GOT
    THIS WRONG. `open_model.profile.json` stores `pools` as a LIST of
    objects, and `ground` does not understand that form: it was refusing
    ALL 64 corpus decompiles, and I read that as "62 of 64 carry the
    defect". The real conversion is done by `serving.py:6784` (pools -> a
    flat dict, plus `levels` from the `document` record in L0). After
    fixing the instrument, the number became 6 of 64. An instrument
    answering truthfully about a DIFFERENT subject is the same class of
    defect as this whole finding.
    """
    return {"levels": [{"id": 1, "name": "L1"}],
            "wall_types": [{"id": 2, "name": "Стена 200"}]}


class ОтказЗаземленияМеняетВердикт(unittest.TestCase):
    """F-326."""

    def test_a_missing_level_is_not_a_green_verdict(self) -> None:
        """🔴 THE SUBJECT. The document snapshot refutes the program."""
        v = C.check_programs([{"ops": [_wall("НЕТ_ТАКОГО_ЭТАЖА")]}],
                             snapshot=_snapshot())
        self.assertEqual(v.grounding, "refused")
        self.assertNotEqual(v.state, "ok",
                            "главный вердикт зелен при отказавшей проверке")

    def test_a_grounded_program_is_still_green(self) -> None:
        """🔴 THE GREEN OUTCOME, AND IT WAS ALSO CHECKED ON THE CORPUS: of
        64 decompiles, two grounded and stayed `ok`. Without this case a fix
        of "always turn red" would pass, and the indicator would stop
        meaning anything."""
        v = C.check_programs([{"ops": [_LEVEL, _wall("L1")]}],
                             snapshot=_snapshot())
        self.assertEqual(v.grounding, "ok")
        self.assertEqual(v.state, "ok")

    def test_without_a_snapshot_the_verdict_is_unchanged(self) -> None:
        """No snapshot — grounding was not run, and the verdict must not
        turn red over a check that never happened. The note says so in
        words."""
        v = C.check_programs([{"ops": [_LEVEL, _wall("L1")]}], snapshot=None)
        self.assertEqual(v.grounding, "not_checked")
        self.assertEqual(v.state, "ok")
        self.assertIn("НЕ ПРОВЕРЕНО", v.grounding_note)

    def test_grounding_nothing_is_not_grounding_ok(self) -> None:
        """🔴 THE THIRD CASE, FOUND BY THE MEASUREMENT. The plan failed ->
        `planned` is empty -> zero checks. Before, the field said `ok` with
        the note «0 программ заземлились»."""
        v = C.check_programs([{"ops": [{"op": "create_wall", "id": "w"}]}],
                             snapshot=_snapshot())
        self.assertEqual(v.state, "refused")
        self.assertNotEqual(v.grounding, "ok",
                            "заземление объявлено успешным, не проверив ничего")


class НеполнаяПачкаНеЗелёная(unittest.TestCase):
    """F-327."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._saved = os.environ.get("KIR_JOURNAL_STORE_PATH")
        os.environ["KIR_JOURNAL_STORE_PATH"] = os.path.join(
            self._dir.name, "j.jsonl")
        self.addCleanup(self._restore)
        from kir.live import journal as J
        self.J = J
        self.key = J.key_for("устр-вытеснение", "док-вытеснение")
        J.reset(self.key)
        self.addCleanup(J.reset, self.key)
        J.append(self.key, {"ops": [_LEVEL]})

    def _restore(self) -> None:
        if self._saved is None:
            os.environ.pop("KIR_JOURNAL_STORE_PATH", None)
        else:
            os.environ["KIR_JOURNAL_STORE_PATH"] = self._saved

    def test_an_evicted_prefix_makes_the_verdict_unknown(self) -> None:
        """🔴 THE SUBJECT OF F-327: the reason existed, the state stayed
        green."""
        self.J.get(self.key).programs_evicted = 7
        out = C.check_session("устр-вытеснение", "док-вытеснение")
        self.assertEqual(out["state"], "unknown")
        self.assertIn("НЕ ПРОВЕРЕНО", out["reason"])
        self.assertIn("НЕ «всё хорошо»", out["state_ru"])

    def test_a_whole_session_is_still_green(self) -> None:
        """🔴 THE GREEN OUTCOME. Without eviction the verdict must stay
        `ok`."""
        out = C.check_session("устр-вытеснение", "док-вытеснение")
        self.assertEqual(out["state"], "ok")
        self.assertEqual(out["session"]["evicted"], 0)

    def test_a_found_refusal_outranks_not_knowing(self) -> None:
        """A found refusal is STRONGER than not-knowing: a fact is not
        downgraded to `unknown`, or eviction would hide a real refusal in
        the tail."""
        self.J.append(self.key, {"ops": [{"op": "create_wall", "id": "w"}]})
        self.J.get(self.key).programs_evicted = 3
        out = C.check_session("устр-вытеснение", "док-вытеснение")
        self.assertEqual(out["state"], "refused")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
