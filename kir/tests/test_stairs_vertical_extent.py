"""THE RUN'S VERTICAL EXTENT: the reference was checked, the GEOMETRY was
not.

THE DEFECT THIS FILE GREW OUT OF is the third and last of three vertical
overruns measured on 18-19.08.2026. The first two (column, wall) were
closed by `test_vertical_extent.py`; here it is the staircase.

MEASUREMENT 19.08, A CLEAN MODEL, NINE RUNS, THE WITNESS GREEN ON ALL NINE:

    "Floor 1"→"Floor 2"  declared 0…5400     geometry 0…6770   overrun 1370 mm
    "Floor 2"→"Floor 3"  declared 5400…9300  geometry …10295   overrun  995 mm
    … eight at 995, the first at 1370

On 18.08, on the live benchmark, the same thing: an overrun of 1202 mm on
11 of 12 runs.

A LAW ESTABLISHED BY READING AND CONFIRMED BY ARITHMETIC ON TWO RISES:

    rise 5400 · DesiredRisersNumber=29 · ActualRisersNumber=36
    ActualRiserHeight=186.2 = 5400/29     ActualTreadDepth=250
    type "Riser max. 190 mm, tread width 250 mm"

Revit computes the riser height CORRECTLY from the rise. But it takes the
NUMBER of risers from the RUN LENGTH divided by the TYPE's tread. A length
of 8680 with a tread of 250 gives 35 treads and 36 risers instead of the 29
needed: (8680 − 28×250)/250 = 6.7 → 7 extra, exactly 36 − 29. On a typical
floor: 20×250 = 5000 is needed, 6160 was sent, a surplus of 4.6 → 5 risers
× 185.7 = 928 mm; 995 was measured (the bbox adds a tread thickness of ≈ 66
mm).

WHY THE AUTHOR COULD NOT HAVE NAMED THE LENGTH RESPONSIBLY. The tread and
the maximum riser live in the staircase's TYPE. `create_stairs` does not
select a type at all (the document default is taken), and there is no
`stairs_types` pool in the script's catalog — `model.pools()` returns 39
names, and this is not among them. That is, the value on which the
correctness of the length depends is unavailable to the author by any
means. So the refusal MUST return a number, not merely name the trouble.

WHY THE GUARD IS ONE-SIDED — and here the reason is STRUCTURAL, not "THE
QUANTITY IS UNMEASURED" as with the column. There is nothing to justify an
overrun with: the run climbed above the declared top, there is no other
reading. A shortfall is LEGITIMATE: `create_stairs` lays down ONE run, and
a staircase made of several runs with landings is completed by
`create_stairs_landing`, and before that completion actual < desired is a
correct intermediate state. Both numbers go into the receipt, so a
shortfall is VISIBLE without being fatal.

THERE IS NO TOLERANCE HERE AT ALL, and this is better than a tolerance:
WHOLE NUMBERS of risers are compared, not millimeters. There was not a
single moment where a threshold had to be invented.

🔴 WHAT THIS FILE CAUGHT IN ITSELF. The obligation's marker was originally
the API name `DesiredRisersNumber` — and the "cut out the guard" mutation
left the certificate PROVEN, because the same name also appears in the
RECEIPT, which is emitted after the commit and rolls nothing back. The
obligation was being discharged by a place that does not check anything.
The marker has been replaced with `__actR` — a variable that exists ONLY
in the guard. This is exactly the class of thing mutation tests are
written for: without the mutation, the witness would have looked like it
worked.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_stairs_vext_queue.jsonl"))

from kir import authoring                                  # noqa: E402
from kir import spec                                       # noqa: E402
from kir import translation_cert as tc                     # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

_L1 = {"__grounded__": {"id": 42, "name": "Этаж 1", "via": "element_id"}}
_L2 = {"__grounded__": {"id": 43, "name": "Этаж 2", "via": "element_id"}}

#: The start of the guard in the emitted text — the mutation uses it to find its boundaries.
_GUARD_HEAD = "        try\n        {\n            int __desR_"


def _stairs(**over):
    op = {"op": "create_stairs", "id": "st", "p0_mm": [0, 0],
          "p1_mm": [7000, 0], "base_level": _L1, "top_level": _L2,
          "width_mm": 1400}
    op.update(over)
    return op


def _span(text: str) -> tuple[int, int]:
    i = text.find(_GUARD_HEAD)
    if i < 0:
        raise AssertionError("сторож не найден в эмиссии — тест устарел")
    j = text.find("catch { __post.Add", i)
    j = text.find("\n", text.find("}\n", j)) + 1
    return i, j


class TheObligationExists(unittest.TestCase):
    def test_registry_declares_the_vertical_extent_obligation(self) -> None:
        keys = [o.key for o in tc._ensure_table()["create_stairs"].obligations]
        self.assertIn("vertical_extent", keys)

    def test_it_is_geometry_not_topology(self) -> None:
        # The point of this: the neighboring obligation already reads
        # where base/top level POINT. One more topological check would
        # add nothing — nine runs on 19.08 passed it green and still
        # overran the top.
        ob = next(o for o in tc._ensure_table()["create_stairs"].obligations
                  if o.key == "vertical_extent")
        self.assertEqual(ob.kind, tc.KIND_GEOMETRY)

    def test_it_is_unconditional(self) -> None:
        # base_level and top_level are BOTH required for this op, so the
        # rise is always derivable and there is no room for
        # conditionality.
        ob = next(o for o in tc._ensure_table()["create_stairs"].obligations
                  if o.key == "vertical_extent")
        self.assertFalse(ob.conditional)
        self.assertIsNone(ob.param)

    def test_no_tolerance_was_invented(self) -> None:
        # Whole numbers of risers are compared. If a millimeter threshold
        # ever appears here, it must be measured and declared — this test
        # will force an explanation of where it came from.
        self.assertNotIn("vertical_span_mm",
                         spec.OPS["create_stairs"].tolerances)


class TheGuardIsInTheEmission(unittest.TestCase):
    def test_it_is_emitted_on_every_shipped_version(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                cs = authoring.emit_stairs_program(_stairs(), ver)
                self.assertIn("__actR_", cs)
                self.assertIn("DesiredRisersNumber", cs)

    def test_the_refusal_carries_the_length_the_author_needs(self) -> None:
        """Without a number the author cannot fix anything: the tread and
        the maximum riser live in the type, and this op does not let a
        type be chosen, nor is one visible in the catalog."""
        cs = authoring.emit_stairs_program(_stairs(), "2023")
        self.assertIn("длина марша должна быть", cs)
        self.assertIn("(__desR_st - 1) * __td_st", cs)

    def test_the_guard_is_one_sided(self) -> None:
        """A shortfall is legitimate — the staircase gets completed with
        landings. If `!=` or `<` ever appears here, the test must go
        red."""
        cs = authoring.emit_stairs_program(_stairs(), "2023")
        self.assertIn("__actR_st > __desR_st", cs)
        self.assertNotIn("__actR_st != __desR_st", cs)
        self.assertNotIn("__actR_st < __desR_st", cs)

    def test_the_numbers_reach_the_receipt_even_when_the_guard_is_silent(self) -> None:
        """A shortfall does not roll back — so it MUST be visible in the
        receipt, otherwise "the run is not finished" is indistinguishable
        from "the run landed correctly"."""
        cs = authoring.emit_stairs_program(_stairs(), "2023")
        for key in ("risers_desired", "tread_depth_mm",
                    "riser_height_mm", "run_length_for_top_mm"):
            with self.subTest(key=key):
                self.assertIn(key, cs)


class CuttingTheGuardMustBreakTheCertificate(unittest.TestCase):
    """A witness that cannot be made to fail is not a witness."""

    def setUp(self) -> None:
        self._orig = authoring._SOLO_PROGRAMS["create_stairs"]
        self.addCleanup(
            lambda: authoring._SOLO_PROGRAMS.__setitem__(
                "create_stairs", self._orig))

    def test_the_honest_emission_is_proven(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                self.assertTrue(tc.certify_op(_stairs(), ver).proven)

    def test_cutting_the_guard_leaves_it_unproven(self) -> None:
        orig = self._orig

        def cut(op, ver, *a, **k):
            text = orig(op, ver, *a, **k)
            i, j = _span(text)
            return text[:i] + text[j:]

        authoring._SOLO_PROGRAMS["create_stairs"] = cut
        for ver in VERSIONS:
            with self.subTest(version=ver):
                self.assertFalse(tc.certify_op(_stairs(), ver).proven)

    def test_the_readback_alone_does_not_discharge_it(self) -> None:
        """🔴 THIS IS EXACTLY WHAT WAS BROKEN. The marker was the API
        name, and cutting out the guard left the certificate proven,
        because the same name also appears in the receipt — and the
        receipt is emitted AFTER the commit and rolls nothing back."""
        orig = self._orig

        def cut(op, ver, *a, **k):
            text = orig(op, ver, *a, **k)
            i, j = _span(text)
            return text[:i] + text[j:]

        authoring._SOLO_PROGRAMS["create_stairs"] = cut
        cut_text = cut(_stairs(), "2023")
        # The API name REMAINS in the text — and still proves nothing.
        self.assertIn("DesiredRisersNumber", cut_text)
        self.assertFalse(tc.certify_op(_stairs(), "2023").proven)

    def test_a_vacuous_sapling_is_caught(self) -> None:
        """The marker is in place, the check is dead: `if (false)`."""
        orig = self._orig

        def vacuous(op, ver, *a, **k):
            text = orig(op, ver, *a, **k)
            i, j = _span(text)
            sapling = ("        if (false)\n        {\n"
                       "            int __actR_dead = "
                       "__st_st.ActualRisersNumber;\n"
                       '            __post.Add("never");\n        }\n')
            return text[:i] + sapling + text[j:]

        authoring._SOLO_PROGRAMS["create_stairs"] = vacuous
        self.assertIn("__actR_", vacuous(_stairs(), "2023"))
        self.assertFalse(tc.certify_op(_stairs(), "2023").proven)


class TheExemptionTableCannotLoseAnEntrySilently(unittest.TestCase):
    """🔴 A GUARD FOR A CLASS THAT WAS PAID FOR TWICE.

    `_NON_WITNESSABLE_CLAUSES` is an ordinary dict literal. By writing in
    a SECOND key with the same name, an author silently erases the first:
    Python takes the last one, and by the time the object is built the
    duplicate is ALREADY GONE — it can only be seen in the source.

    On 19.08 I erased the `sole op` entry for `create_stairs` this way,
    along with the honest KIR-L002 exception, and the audit went red in a
    completely different place, blaming a clause I had never touched. On
    09.08 the same dictionary had already been the subject of a comment on
    `create_beam_system`: "both waves were appending to the end of the
    same exceptions dictionary, and whichever side won would erase two
    honestly named absences". Back then the merge was done by hand; no
    guard was put in place.

    The check runs over the AST of the SOURCE TEXT, not over the object —
    otherwise it would be checking the very place where the evidence is
    already gone.
    """

    def test_no_duplicate_keys_in_the_exemptions(self) -> None:
        import ast
        import pathlib

        src = pathlib.Path(tc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        found: list[str] = []
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
            # 22.08.2026: the literal moved into `_CLAUSE_NOTES` (the
            # entry gained a ROLE), and `_NON_WITNESSABLE_CLAUSES` became
            # its projection — i.e. an `ast.DictComp`, not an `ast.Dict`.
            # The guard must look at the LITERAL: in the projection the
            # duplicate key is already gone, and it would pass silently.
            # The name here is the only thing tying the guard to its
            # subject, which is why it is updated together with the move.
            if target != "_CLAUSE_NOTES":
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            found = [k.value for k in node.value.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            break
        # 🔴 THE DENOMINATOR, MEASURED 02.09.2026: the `_CLAUSE_NOTES`
        # literal has **25** keys. `assertTrue(found)` catches ONLY
        # EMPTINESS — this is the very same `assert names` shape with
        # which, on 02.09, the emitters' guard stayed GREEN while seeing
        # only 35 of 72 names. A table shrunk down to a single key has no
        # duplicates by construction, and "no duplicates" below would
        # become true of nothing at all.
        КЛЮЧЕЙ_ИСКЛЮЧЕНИЙ_НЕ_МЕНЬШЕ = 20
        self.assertTrue(found, "литерал таблицы исключений не найден в исходнике")
        self.assertGreaterEqual(
            len(found), КЛЮЧЕЙ_ИСКЛЮЧЕНИЙ_НЕ_МЕНЬШЕ,
            f"разбор снял {len(found)} ключей при поле "
            f"{КЛЮЧЕЙ_ИСКЛЮЧЕНИЙ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 25). Это "
            f"заявление о ХОДОКЕ: литерал переехал или сменил имя, и "
            f"«дубликатов нет» ниже НИЧЕГО не означает")
        dupes = sorted({k for k in found if found.count(k) > 1})
        self.assertEqual(dupes, [], f"дубликаты ключей стирают друг друга молча: {dupes}")

    def test_the_kir_l002_exemption_is_still_there(self) -> None:
        """This is exactly the one that got erased. A check by substance,
        not by record count."""
        markers = [m for m, _why in tc._NON_WITNESSABLE_CLAUSES["create_stairs"]]
        self.assertIn("sole op", markers)
        self.assertIn("недобор подступенков", markers)

    def test_the_registry_audit_is_clean(self) -> None:
        self.assertEqual(tc.audit_registry_coverage(), ())


class WhatThisGuardDoesNotCatch(unittest.TestCase):
    """Named, not forgotten."""

    def test_undershoot_is_deliberately_allowed(self) -> None:
        # A run shorter than needed is a legitimate intermediate state of
        # a staircase that is being completed with landings. The witness
        # stays silent BY DECISION, and the decision is written down here,
        # not merely implied.
        cs = authoring.emit_stairs_program(_stairs(), "2023")
        self.assertIn("__actR_st > __desR_st", cs)

    def test_the_stairs_type_is_not_choosable_and_that_is_the_root(self) -> None:
        # As long as a type is not selected and its tread is not read, the
        # author CANNOT name the length responsibly. If this op ever gets
        # a `type`, this test must go red and force the refusal to be
        # reconsidered.
        self.assertNotIn("type",
                         [p.name for p in spec.OPS["create_stairs"].params])


if __name__ == "__main__":
    unittest.main()
