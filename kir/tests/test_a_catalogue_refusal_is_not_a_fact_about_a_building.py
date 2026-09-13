"""A CATALOGUE REFUSAL IS NOT A FACT ABOUT A BUILDING. THREE SPOTS, ONE CLASS.

Audit findings `F-186`, `F-187`, `F-188` (2026-08-29), `kir/corpus_catalog.py`.
One class: a read failure was recorded with the SAME value as a legal
answer, and travelled outward as an assertion about a building.

`F-186` — ANY READABLE TEXT BECAME A BUILDING. `parse_card` computed the
signal «the first line starts with `# KIR Passport — `» and THREW IT AWAY,
keeping only `doc_name`. On a non-passport, `doc_name` = `'?'` — but `'?'`
is a LEGAL name, written by the producer itself (`pipeline.py:1581`
`passport.get('doc_name', '?')`). So garbage and a genuine passport of an
unknown building produced a byte-identical card, and `load_catalog` filed
the garbage as an ordinary `Entry`, with a name search finding it as a
building.

`F-187` — THREE STATES, ONE VALUE. `_status_of` returned `("", "")` both
when `status.json` is absent, when it is broken, and when it is valid with
an empty stage. `Missing.alive` (`stage != "error"`) declared the parse
ALIVE in all three — although in the first two there is no evidence of life
at all. The absence of an accusation is not proof of life.

`F-188` — A REQUIREMENT IN THE DOCSTRING, VIOLATED BY THE VERY NEXT LINE.
`_course_labels` promised: «"no labels" must be distinguishable from "labels
are empty"» — and returned `{}` in both cases. `Catalog` carried no signal,
and the label dictionary could disappear silently.

🔴 WHAT MAKES THESE THREE ONE CLASS, NOT THREE COINCIDENCES. In each, the
requirement was ALREADY WRITTEN DOWN — in the docstring (`F-187`, `F-188`)
or computed outright and thrown away (`F-186`). The fix is not "add a
check" but "stop losing what we already know": the signal is kept, failure
stops being a value, availability travels TOGETHER with the dictionary.

AN UNFIT CHECK FOR `F-186`, NAMED EXPLICITLY: `doc_name != "?"`. That is
exactly the trap — it would filter out genuine passports of unknown
buildings too, i.e. the second mistake in place of the first. What must be
checked is the KIND of document, not the value.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from kir import corpus_catalog as cc

_GOOD = "# KIR Passport — Дом-1\n- Revit: 2023\n- elements: 5\n"
_UNKNOWN = "# KIR Passport — ?\n- Revit: 2024\n- elements: 5\n"
_GARBAGE = "totally malformed but readable"


def _run(root: str, name: str, *, passport: str | None = None,
         status: str | None = None) -> str:
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    if passport is not None:
        with open(os.path.join(d, cc.CARD_NAME), "w", encoding="utf-8") as fh:
            fh.write(passport)
    if status is not None:
        with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as fh:
            fh.write(status)
    return d


class ЧитаемыйМусорНеЗдание(unittest.TestCase):
    """F-186."""

    def test_the_legal_question_mark_is_not_the_discriminator(self) -> None:
        """🔴 SUBJECT OF THE FINDING: both give `doc_name == '?'`, and that is LEGAL."""
        self.assertEqual(cc.parse_card(_GARBAGE).doc_name, "?")
        self.assertEqual(cc.parse_card(_UNKNOWN).doc_name, "?")
        # It is the kind of document that tells them apart.
        self.assertFalse(cc.parse_card(_GARBAGE).well_formed)
        self.assertTrue(cc.parse_card(_UNKNOWN).well_formed)

    def test_readable_garbage_does_not_become_an_entry(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _run(root, "garbage", passport=_GARBAGE)
            _run(root, "unknown", passport=_UNKNOWN)
            _run(root, "named", passport=_GOOD)
            cat = cc.load_catalog(root=root)
            self.assertEqual(sorted(e.run for e in cat.entries),
                             ["named", "unknown"])
            miss = {m.run: m for m in cat.missing}
            self.assertIn("garbage", miss)
            self.assertIn("не «# KIR Passport", miss["garbage"].reason)

    def test_an_incomplete_passport_is_still_a_building(self) -> None:
        """🔴 A GREEN OUTCOME WITHOUT WHICH THE FIX WOULD BUY A SECOND MISTAKE.
        The KIND of a document and its COMPLETENESS are different questions:
        `parse_card` deliberately turns an unreadable number into `None`,
        and a passport of an incomplete parse exists legally."""
        card = cc.parse_card("# KIR Passport — Дом-2\n")
        self.assertTrue(card.well_formed)
        self.assertIsNone(card.elements)
        with tempfile.TemporaryDirectory() as root:
            _run(root, "thin", passport="# KIR Passport — Дом-2\n")
            self.assertEqual([e.run for e in cc.load_catalog(root=root).entries],
                             ["thin"])


class ТриСостоянияСтатусаТриОтвета(unittest.TestCase):
    """F-187."""

    def test_three_states_of_the_status_file_are_three_answers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            no = _run(td, "nofile")
            bad = _run(td, "broken", status="{not json")
            notmap = _run(td, "notmap", status="[1, 2]")
            ok = _run(td, "ok", status=json.dumps({"stage": "", "errors": []}))
            self.assertIsNone(cc._status_of(no))
            self.assertIsNone(cc._status_of(bad))
            self.assertIsNone(cc._status_of(notmap))
            # 🔴 THE GREEN OUTCOME IS MANDATORY: without it, the check would
            # read as «an empty stage is forbidden», and it is LEGAL.
            self.assertEqual(cc._status_of(ok), ("", ""))

    def test_a_status_we_could_not_read_does_not_prove_life(self) -> None:
        """`alive` is derived from the fact of reading. The absence of an
        accusation is not proof of life."""
        with tempfile.TemporaryDirectory() as root:
            _run(root, "silent")                      # neither a passport nor a status
            _run(root, "живой", status=json.dumps({"stage": "geometry"}))
            _run(root, "мёртвый", status=json.dumps(
                {"stage": "error", "errors": ["extract_failed"]}))
            miss = {m.run: m for m in cc.load_catalog(root=root).missing}
            self.assertFalse(miss["silent"].status_read)
            self.assertFalse(miss["silent"].alive, "разбор без статуса объявлен живым")
            # BOTH LEGAL OUTCOMES on a status that was read:
            self.assertTrue(miss["живой"].status_read)
            self.assertTrue(miss["живой"].alive)
            self.assertTrue(miss["мёртвый"].status_read)
            self.assertFalse(miss["мёртвый"].alive)

    def test_the_two_facts_travel_out_together(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _run(root, "silent")
            row = cc.load_catalog(root=root).missing[0].to_dict()
            self.assertIn("status_read", row)
            self.assertIs(row["alive"], False)


class ЯрлыковНетИСпроситьНечем(unittest.TestCase):
    """F-188."""

    def test_the_availability_travels_with_the_dictionary(self) -> None:
        labels, ok = cc._course_labels()
        self.assertIsInstance(labels, dict)
        self.assertTrue(ok)
        self.assertGreater(len(labels), 0)   # denominator control

    def test_a_broken_source_is_not_an_empty_dictionary(self) -> None:
        """🔴 SUBJECT. We swap the import so the source fails to come up, and
        require TWO DIFFERENT answers where there used to be one `{}`."""
        import builtins
        real = builtins.__import__

        def boom(name, *a, **kw):
            if name == "kir.course.corpus":
                raise ImportError("источник не поднялся")
            return real(name, *a, **kw)

        builtins.__import__ = boom
        try:
            labels, ok = cc._course_labels()
        finally:
            builtins.__import__ = real
        self.assertEqual(labels, {})
        self.assertFalse(ok, "«спросить нечем» неотличимо от «ярлыков нет»")

    def test_the_catalogue_carries_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _run(root, "named", passport=_GOOD)
            self.assertTrue(cc.load_catalog(root=root).labels_source_available)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
