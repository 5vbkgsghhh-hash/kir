"""A CAPTURE MUST NAME NOT ONLY "THERE IS ONE," BUT "WHICH ONE EXACTLY."

WHAT THIS COST, 26.08.2026, from decompiling a corpus of 110 families
(payload of 21.08).

THE FIRST DEFECT — A RELATION WITH NO ADDRESS. For a sweep, the capture
was placing ONE boolean key, `profile_is_symbol`: "the profile is given
by a loaded family." Which family — it never placed that at all. Twenty
sweeps across eighteen of the eighty-two families were refusing with code
`sweep_profile_is_family_symbol`, and this is the DOMINANT cause of
inexpressibility across the whole corpus — more than the void, the
blend, and the contour combined. There was nothing to attach to: there
was no name.

    before: profile_is_symbol = true
    after:  profile_symbol_source = "api"
            profile_family_name  = "АС - Прямоугольный поручень"
            profile_symbol_name  = "50 x 40"
            + XOffset/YOffset/Angle/IsFlipped — the profile's PLACEMENT
              on the path

The four placement fields here are not a luxury: without them a second
pass would build the correct outline in the wrong place, and would say
nothing about it.

THE SECOND DEFECT — NOT-KNOWING PASSED OFF AS KNOWING. `Sweep.Path3d` was
not being asked at all, and the refusal `sweep_path_unavailable` (6
forms across 5 families) said, verbatim, "there is nothing to tell these
two cases apart with." Now it is asked, and the refusal says WHAT it
heard.

THE THIRD DEFECT — THE CENSUS LAW (§18) WAS HELD FROM ABOVE AND WAS
BROKEN FROM INSIDE. At the top, the payload carries `families_seen` and
`families_read`. Inside a family, the capture was collecting ONLY
`GenericForm` and staying silent about what it skipped. Measured: 27 of
110 families open and yield ZERO forms, and only eight are
two-dimensional by nature (4 "node elements" + 4 "profiles"). The
remaining nineteen — a sofa, a kitchen, elevators, a trash bin, five
windows, a cabinet — plainly have geometry, and for a whole week were
being read as "families with no forms."

🔴 FOUR STATES OF KNOWLEDGE, NOT TWO, AND THIS IS THE HEART OF THE FILE.
A field that is not in the payload at all, and a field that was asked
and came back empty, are different answers: the first is about US, the
second is about the FAMILY. Merging them means declaring the old
snapshot a poor family, i.e. repeating the exact defect all this exists
to fix.

🔴 WHY THE TEST IS SYNTHETIC. The family corpus is machine-local
(`/home/claude/kir-evidence/…`), and a test on it would go green BY
ABSENCE everywhere the corpus is missing. The corpus numbers live in the
wave's report; what is pinned here is the law.
"""
from __future__ import annotations

import unittest

from kir.decompile import family_recipe as FR


def _sweep(**extra) -> dict:
    """A sweep whose profile is a loaded family."""
    form = {"id": "7", "kind": "Sweep", "is_solid": True, "name": "поручень",
            "profile_is_symbol": True,
            "profile_reason": "у формы нет читаемого эскиза",
            "path_mm": [[0, 0, 0], [3000, 0, 0]]}
    form.update(extra)
    return form


def _payload(form: dict, **fam) -> dict:
    row = {"name": "СЕМ", "category": "Мебель", "forms": [form]}
    row.update(fam)
    return {"schema_version": FR.FAMILY_RECIPE_SCHEMA_VERSION,
            "families": [row]}


def _one(form: dict, **fam) -> FR.FamilyRecipe:
    return FR.parse_recipe_payload(_payload(form, **fam))[0]


class TheCaptureAsksForTheProfileByName(unittest.TestCase):
    """The C# body must ASK, otherwise there is nothing to decompile."""

    def test_the_body_asks_the_profile_symbol_not_only_whether_it_exists(self) -> None:
        """🔴 TURNS RED ON THE CODE FROM BEFORE 26.08: there `ProfileSymbol`
        was only checked against `null`, and `FamilySymbolProfile` was
        never mentioned at all."""
        cs = FR.family_recipe_cs()
        self.assertIn("as FamilySymbolProfile", cs)
        self.assertIn("profile_family_name", cs)
        self.assertIn("profile_symbol_name", cs)

    def test_the_body_asks_where_the_profile_sits_not_only_which_it_is(self) -> None:
        """Offsets, rotation, and mirroring — otherwise the outline is
        right, the place is not."""
        cs = FR.family_recipe_cs()
        for member in ("__fsp.XOffset", "__fsp.YOffset",
                       "__fsp.Angle", "__fsp.IsFlipped"):
            self.assertIn(member, cs, member)

    def test_the_body_asks_path3d(self) -> None:
        """The refusal `sweep_path_unavailable` itself named this as its reason."""
        self.assertIn("__sw.Path3d", FR.family_recipe_cs())

    def test_the_body_does_not_declare_a_type_the_prose_never_named(self) -> None:
        """🔴 A CONTROL AGAINST GUESSING. The XML prose about `Path3d` says
        only "The selected curves used for the sweep path" and does NOT
        name the type. So the kind is asked of Revit itself, not
        declared by us."""
        cs = FR.family_recipe_cs()
        self.assertIn("object __p3 = __sw.Path3d", cs)
        self.assertIn("__p3.GetType().Name", cs)

    def test_the_body_counts_every_element_not_only_the_forms(self) -> None:
        """The §18 census inside a family, not only over families."""
        cs = FR.family_recipe_cs()
        self.assertIn("WhereElementIsNotElementType", cs)
        self.assertIn("census_by_class", cs)
        self.assertIn("census_elements", cs)

    def test_kinds_are_counted_independently_because_ancestry_is_unknown(self) -> None:
        """🔴 AN `else if` CHAIN WOULD SILENTLY CREDIT THE PARENT WITH THE
        CHILD.

        Revit's class inheritance is not declared to us by anything:
        `api_surface` carries members, not ancestors. `FreeFormElement`
        might turn out to be a descendant of `GenericForm` — and in a
        chain it would never be counted AT ALL.
        """
        cs = FR.family_recipe_cs()
        for kind in ("GenericForm", "FamilyInstance",
                     "ImportInstance", "FreeFormElement"):
            self.assertIn(f"if (__e2 is {kind})", cs, kind)
        self.assertNotIn("else if (__e2 is", cs)

    def test_it_still_writes_nothing_and_still_closes_what_it_opens(self) -> None:
        """PASS CONTROL: the fix is large, and the body's old laws must still hold."""
        cs = FR.family_recipe_cs()
        for forbidden in ("new Transaction", "tx.Start", ".Delete(", "Document.Save"):
            self.assertNotIn(forbidden, cs)
        self.assertEqual(cs.count("doc.EditFamily"), 1)
        self.assertIn("__fd.Close(false)", cs)


class KnowledgeHasFourStatesNotTwo(unittest.TestCase):
    """"Not asked," "asked and empty," "asked and it threw," "present"."""

    def test_an_old_payload_says_NOT_ASKED_and_never_absent(self) -> None:
        """🔴 THE HEART OF THE FILE. The 21.08 snapshot carries no keys —
        this is about US. Reading it as `absent` would mean declaring
        the family poor."""
        form = _one(_sweep()).forms[0]
        self.assertEqual(form.profile_symbol_source, FR.KNOWLEDGE_NOT_ASKED)
        self.assertEqual(form.path3d_source, FR.KNOWLEDGE_NOT_ASKED)
        self.assertIsNone(form.profile_symbol_name)
        self.assertIsNone(form.path3d_count)

    def test_asked_and_empty_is_a_DIFFERENT_answer_from_never_asked(self) -> None:
        form = _one(_sweep(profile_symbol_source="absent",
                           path3d_source="absent")).forms[0]
        self.assertEqual(form.profile_symbol_source, "absent")
        self.assertEqual(form.path3d_source, "absent")

    def test_a_refused_call_carries_its_reason(self) -> None:
        form = _one(_sweep(path3d_source="refused",
                           path3d_reason="InvalidOperationException")).forms[0]
        self.assertEqual(form.path3d_source, "refused")
        self.assertEqual(form.path3d_reason, "InvalidOperationException")

    def test_a_typo_in_the_source_is_REFUSED_not_read_as_unknown(self) -> None:
        """🔴 A FAIL CONTROL. `"apy"` without a check would read as
        "unknown," yet look like "asked" — quietly, and in the
        convenient direction."""
        with self.assertRaises(FR.FamilyRecipeError):
            _one(_sweep(profile_symbol_source="apy"))


class TheProfileArrivesWithItsPlacement(unittest.TestCase):

    def test_every_field_of_the_symbol_profile_reaches_the_recipe(self) -> None:
        form = _one(_sweep(
            profile_symbol_source="api",
            profile_symbol_name="50 x 40",
            profile_family_name="АС - Прямоугольный поручень",
            profile_x_offset_mm=12.5, profile_y_offset_mm=-3.25,
            profile_angle_deg=90.0, profile_flipped=True)).forms[0]
        self.assertEqual(form.profile_symbol_name, "50 x 40")
        self.assertEqual(form.profile_family_name, "АС - Прямоугольный поручень")
        self.assertEqual(form.profile_x_offset_mm, 12.5)
        self.assertEqual(form.profile_y_offset_mm, -3.25)
        self.assertEqual(form.profile_angle_deg, 90.0)
        self.assertIs(form.profile_flipped, True)

    def test_the_refusal_NAMES_the_dependency_when_the_capture_asked(self) -> None:
        """A refusal naming a dependency with no name sends the reader off to find it."""
        recipe = _one(_sweep(
            profile_symbol_source="api",
            profile_symbol_name="50 x 40",
            profile_family_name="АС - Прямоугольный поручень"))
        lift = FR.form_to_op(recipe.forms[0], category=recipe.category,
                             name=recipe.family_name)
        self.assertIsNotNone(lift.refusal)
        self.assertEqual(lift.refusal.code,
                         FR.RecipeRefusal.SWEEP_PROFILE_IS_SYMBOL)
        self.assertIn("АС - Прямоугольный поручень", lift.refusal.detail)

    def test_the_refusal_says_NOT_ASKED_on_an_old_snapshot(self) -> None:
        """And does not pass our own ignorance off as a property of the family."""
        recipe = _one(_sweep())
        lift = FR.form_to_op(recipe.forms[0], category=recipe.category,
                             name=recipe.family_name)
        self.assertIn("НЕ СПРАШИВАЛИ", lift.refusal.detail)

    def test_the_path_refusal_reports_what_path3d_answered(self) -> None:
        """The text "the reading C# does not ask it yet" would become a lie."""
        # THE PROFILE MUST BE VALID, otherwise the profile refusal fires
        # FIRST and the test goes green for the wrong reason. A
        # rectangle in the YZ plane.
        pts = [(0, 0, 0), (0, 100, 0), (0, 100, 50), (0, 0, 50)]
        loop = [{"kind": "line", "p0": list(pts[i]),
                 "p1": list(pts[(i + 1) % 4])} for i in range(4)]
        recipe = _one({"id": "9", "kind": "Sweep", "is_solid": True,
                       "name": "к", "path_mm": [],
                       "plane_normal": [1, 0, 0], "plane_origin_mm": [0, 0, 0],
                       "plane_x_dir": [0, 1, 0], "loops": [loop],
                       "path3d_source": "api", "path3d_kind": "ReferenceArray",
                       "path3d_count": 4})
        lift = FR.form_to_op(recipe.forms[0], category=recipe.category,
                             name=recipe.family_name)
        self.assertIsNotNone(lift.refusal)
        self.assertIn("ReferenceArray", lift.refusal.detail)
        self.assertIn("4", lift.refusal.detail)
        self.assertNotIn("пока не спрашивает", lift.refusal.detail)


class TheCensusReconcilesOrSaysItDoesNot(unittest.TestCase):

    _CENSUS = {"census_source": "api", "census_elements": 9,
               "census_generic_forms": 1, "census_family_instances": 3,
               "census_import_instances": 0, "census_free_form_elements": 0,
               "census_by_class": {"Sweep": 1, "FamilyInstance": 3,
                                   "ReferencePlane": 5}}

    def test_a_census_that_adds_up_says_so(self) -> None:
        recipe = _one(_sweep(), **self._CENSUS)
        self.assertIs(recipe.census_reconciles, True)
        self.assertEqual(recipe.census_elements, 9)

    def test_a_census_that_does_NOT_add_up_is_announced_not_hidden(self) -> None:
        """🔴 FAIL CONTROL: a broken instrument must scream about itself."""
        broken = dict(self._CENSUS, census_elements=99)
        self.assertIs(_one(_sweep(), **broken).census_reconciles, False)

    def test_no_census_is_a_THIRD_answer_and_not_False(self) -> None:
        """The absence of a census is not "it didn't match." These are different things."""
        recipe = _one(_sweep())
        self.assertEqual(recipe.census_source, FR.KNOWLEDGE_NOT_ASKED)
        self.assertIsNone(recipe.census_reconciles)
        self.assertIsNone(recipe.forms_unseen)

    def test_forms_the_census_saw_and_the_reader_did_not_are_counted(self) -> None:
        """A form lost between the census and the decompile is our own defect."""
        seen_three = dict(self._CENSUS, census_generic_forms=3)
        self.assertEqual(_one(_sweep(), **seen_three).forms_unseen, 2)
        self.assertEqual(_one(_sweep(), **self._CENSUS).forms_unseen, 0)

    def test_the_breakdown_is_sorted_by_how_many_not_by_payload_order(self) -> None:
        """A census is read by eye: the most frequent kind must come first."""
        rows = _one(_sweep(), **self._CENSUS).census_by_class
        self.assertEqual(rows[0], ("ReferencePlane", 5))
        self.assertEqual([n for _c, n in rows], sorted([n for _c, n in rows],
                                                       reverse=True))

    def test_a_boolean_is_not_a_count(self) -> None:
        """🔴 In Python `True == 1`: without the check, a census made
        from `true` would give one element and would look honest."""
        with self.assertRaises(FR.FamilyRecipeError):
            _one(_sweep(), census_source="api", census_elements=True)


if __name__ == "__main__":
    unittest.main()
