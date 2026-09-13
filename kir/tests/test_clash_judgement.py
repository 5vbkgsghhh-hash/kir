"""THE JUDGEMENT LAYER: a pair becomes what the designer will accept.

WHAT WAS MEASURED BEFORE THE FIX (09.08, `snowdon_plumb_v5`, 11,069 elements,
122 bodies). The `all_physical_diagnostic` scope produced 99 pairs, and the
`clash/review.py` layer placed **66 of them at the top rung** («критично»).
All 66 are slabs of ONE floor. Analysis against the real geometry showed that
the problem is neither the search scope nor the threshold, but two
coarsenings introduced by the compiler itself:

  * 62 of 76 «перекрытие~перекрытие» pairs have DECLARED CONTOURS that do NOT
    INTERSECT — only their CONVEX hulls intersect (`hulls.build_hull` makes
    the slab's footprint convex and fills in its openings). The coarsening
    explains 61 of them: the 62nd is convex on both sides, and there is
    nothing there to explain;
  * the slab's extent along Z is coarsened BY A FACTOR OF TWO by
    `clash_bundle._slab_geometry` itself.

A report two-thirds of which the designer throws away is worse than no
report at all.

Run:
    venv/bin/python -m pytest kir/tests/test_clash_judgement.py -q
"""
from __future__ import annotations

import copy
import math
import unittest

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir import clash_judgement as J
from kir.decompile.extract import _SPEC_BY_NAME


# ═════════════════════════════════════════════════════════════════════════
# Material: the detector finding is assembled BY HAND in exactly the shape
# that `detect.Finding.as_dict()` returns — otherwise the test would be
# checking its own fantasy.
# ═════════════════════════════════════════════════════════════════════════

def side(element_id: str, category: str, label: str, *,
         hull_source: str = "axis_section") -> dict:
    return {"source_element_id": element_id, "category": category,
            "label": label, "hull_grade": "conservative",
            "hull_source": hull_source, "level_id": "lvl", "type_name": None,
            "section_source": "diameter", "section_radius_mm": 100.0}


def finding(a: dict, b: dict, *, relation: str = "overlap",
            depth: float = 80.0, grade: str = "conservative",
            pair_kind: str = "interference",
            translation: list[float] | None = None,
            verdict: str | None = None) -> dict:
    return {
        "finding_id": f"{a['source_element_id']}~{b['source_element_id']}",
        "a": a, "b": b,
        "pair_class": "~".join(sorted((a["label"], b["label"]))),
        "signed_distance_mm": -depth, "hull_overlap_depth_mm": depth,
        "clearance_mm": 0.0, "clearance_deficit_mm": depth,
        "ranking_tol_mm": H.TOL_GRADE_MM[grade], "ranking_significant": True,
        "hull_grade": grade, "pair_kind": pair_kind,
        "hull_relation": relation,
        "verdict": verdict or ("confirmed" if grade == "exact" else "possible"),
        "certified_separating_translation_mm": translation,
        "translation_unavailable_reason": None,
    }


PIPE = side("p1/pipe1", "OST_PipeCurves", "pipe")
DUCT = side("p2/duct1", "OST_DuctCurves", "duct")
DUCT2 = side("p2/duct2", "OST_DuctCurves", "duct")
WALL = side("p3/w1", "OST_Walls", "wall", hull_source="bbox")
FLOOR = side("p3/f1", "OST_Floors", "floor", hull_source="profile")
BEAM = side("p4/b1", "OST_StructuralFraming", "beam", hull_source="bbox")
COLUMN = side("p4/c1", "OST_Columns", "column", hull_source="bbox")
EQUIP = side("p5/eq1", "OST_MechanicalEquipment", "equipment",
             hull_source="bbox")


def exact(s: dict) -> dict:
    """The exact side for a positive contract of future geometry."""
    return {**s, "hull_grade": "exact"}


def one(*args, **kwargs) -> J.Judged:
    return J.judge([finding(*args, **kwargs)]).judged[0]


def sealed_exact_duplicate() -> dict:
    """Future exact producer fixture issued through the real detector.

    Production currently emits no ``grade=exact`` body.  The positive branch
    still needs an executable contract, otherwise a permanently-false safety
    predicate could look safe while silently disabling the feature forever.
    """

    def record(source_id: str) -> H.HullRecord:
        hull = G.Prism(
            ((0.0, 0.0), (1000.0, 0.0),
             (1000.0, 100.0), (0.0, 100.0)),
            0.0, 100.0)
        inner = H.certify_analytic_inner_for_test(
            inner=hull,
            body=hull,
            outer=hull,
            subject_source_id=source_id,
            body_source_digest=H.analytic_hull_digest(hull),
            body_source_revision=f"fixture:{source_id}:body-r1",
        )
        return H.HullRecord(
            source_id=source_id,
            category="OST_PipeCurves",
            label="pipe",
            mvp_side="mep",
            hull=hull,
            grade="exact",
            hull_source="future_exact_body",
            inner=inner,
        )

    detected = D.evaluate(record("p1/exact-a"), record("p1/exact-b"))
    assert detected is not None
    return detected.as_dict()


# ═════════════════════════════════════════════════════════════════════════
# 1. THE DICTIONARIES ARE SOMEONE ELSE'S, AND A TEST HOLDS THIS DOWN
# ═════════════════════════════════════════════════════════════════════════

class TheDictionariesAreNotOurs(unittest.TestCase):

    def test_the_discipline_comes_from_the_extractor_table_and_nowhere_else(self):
        """A SECOND SECTION DICTIONARY HAS ALREADY BEEN KILLED HERE (fold,
        28.07): its own copy knew 17 of 47 categories and read the entire
        ЭОМ as «не знаем, что это»."""
        for category, spec in _SPEC_BY_NAME.items():
            self.assertEqual(J.discipline_of(category), spec.discipline,
                             category)

    def test_a_category_the_extractor_does_not_know_reads_as_unknown(self):
        """Emptiness is visible, a guess is not. Measured 09.08: five
        categories of `hulls.KIND_TABLE` are unknown to the extractor's
        table."""
        absent = [c for c in H.KIND_TABLE if c not in _SPEC_BY_NAME]
        self.assertTrue(absent, "выборка пуста — тест стал бы вакуумным")
        for category in absent:
            self.assertEqual(J.discipline_of(category), "unknown", category)
        self.assertEqual(J.discipline_of("OST_NoSuchThing"), "unknown")

    def test_every_label_of_the_closed_hull_table_has_a_role(self):
        """A closed table of roles: a new label must be NOTICED, not
        silently assigned to whatever bucket happens to be handy."""
        for category, rule in H.KIND_TABLE.items():
            self.assertIn(rule.label, J.ROLE_BY_LABEL,
                          f"{category}: метка {rule.label!r} без роли")

    def test_a_physical_element_never_carries_the_not_a_body_role(self):
        """The `not_a_body` role and search eligibility are one and the same
        assertion, and they have no right to diverge."""
        for category, rule in H.KIND_TABLE.items():
            if not rule.eligible:
                continue
            self.assertNotEqual(J.role_of(rule.label), "not_a_body", category)

    def test_the_role_table_names_no_label_that_does_not_exist(self):
        known = {rule.label for rule in H.KIND_TABLE.values()}
        self.assertEqual(sorted(set(J.ROLE_BY_LABEL) - known), [],
                         "роль назначена метке, которой в KIND_TABLE нет")


# ═════════════════════════════════════════════════════════════════════════
# 2. THE RULE TABLE — EVERY RULE FIRES, AND EVERY ONE IS JUSTIFIED
#
# WHY SYNTHETIC DATA. Neither of the two real buildings this wave was
# measured on puts a single MEP body into the search: `snowdon_plumb_v5`
# contains no pipes or ducts at all (measured at L0: 0 of 11,069), and at
# `sklnk_eom_r26_v10` all 77 trays remain without a cross-section. Half the
# table is VACUOUS on them by construction, and admitting that is more
# honest than declaring it tested.
# ═════════════════════════════════════════════════════════════════════════

class TheRulesAreFacts(unittest.TestCase):

    def test_two_runs_in_one_volume_are_a_collision(self):
        """Two route bodies cannot occupy one volume."""
        item = one(DUCT, DUCT2)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_meets_run"))

    def test_a_pipe_through_a_wall_is_a_penetration_not_a_collision(self):
        """A network MUST pass between rooms: this is a sleeve, not a
        defect."""
        item = one(PIPE, WALL)
        self.assertEqual((item.kind, item.rule_id),
                         ("penetration", "run_through_envelope"))
        self.assertNotIn("create_opening", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_a_duct_through_a_beam_is_a_collision(self):
        """An opening in a beam is a calculation and an approval, not a
        standard detail."""
        item = one(DUCT, BEAM)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_through_bearing"))

    def test_a_run_inside_equipment_is_a_collision(self):
        item = one(PIPE, EQUIP)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_meets_equipment"))

    def test_a_floor_meeting_a_wall_is_adjacency(self):
        """A slab bears on a wall — that is how the building is assembled."""
        item = one(FLOOR, WALL, relation="contact", depth=0.0)
        self.assertEqual((item.kind, item.rule_id),
                         ("adjacency", "structure_contact"))
        self.assertEqual(item.rung, "note")

    def test_the_author_declared_host_is_never_a_clash(self):
        """A fact about the DECLARATION, not about construction: a door
        inside its own wall."""
        door = side("p3/d1", "OST_Doors", "door", hull_source="bbox")
        ops = {"p3/d1": {"op": "create_door", "id": "d1",
                         "host": {"by": "ref", "value": "w1"}},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(door, WALL, depth=200.0)], ops=ops).judged[0]
        self.assertEqual((item.kind, item.rule_id),
                         ("adjacency", "host_declared"))

    def test_a_declared_host_of_someone_else_does_not_excuse_the_pair(self):
        """The host checks the `id` of the OTHER side, not merely whether
        the field is present."""
        door = side("p3/d1", "OST_Doors", "door", hull_source="bbox")
        ops = {"p3/d1": {"op": "create_door", "id": "d1",
                         "host": {"by": "ref", "value": "СОВСЕМ ДРУГАЯ"}},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(door, WALL, depth=200.0)], ops=ops).judged[0]
        self.assertNotEqual(item.rule_id, "host_declared")

    def test_every_rule_that_the_table_declares_can_be_reached(self):
        """A rule that can never fire is decoration, not a contract."""
        reached = {
            J.judge([finding(*args, **kw)]).judged[0].rule_id
            for args, kw in (
                ((DUCT, DUCT2), {}),
                ((PIPE, WALL), {}),
                ((DUCT, BEAM), {}),
                ((PIPE, EQUIP), {}),
                ((FLOOR, WALL), {"relation": "contact", "depth": 0.0}),
                ((DUCT, DUCT2), {"pair_kind": "coincident_duplicate"}),
                ((side("p9/x", "OST_Furniture", "furniture",
                       hull_source="bbox"),
                  side("p9/y", "OST_StairsRailing", "railing",
                       hull_source="bbox")), {}),
            )}
        declared = {rule.rule_id for rule in J.RULES} - {"host_declared",
                                                         "hull_over_approximation"}
        self.assertEqual(declared - reached, set(),
                         f"недостижимые правила: {sorted(declared - reached)}")


# ═════════════════════════════════════════════════════════════════════════
# 3. REFUSED RULES ARE PART OF THE CONTRACT
# ═════════════════════════════════════════════════════════════════════════

class TheRefusalsAreLoud(unittest.TestCase):

    def test_two_structures_interpenetrating_get_no_rule_and_say_why(self):
        """It is MATERIAL that distinguishes cast-in-place from steel, and
        the program does not express it."""
        item = one(FLOOR, COLUMN, depth=295.0, grade="coarse")
        self.assertEqual(item.kind, "unclassified")
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")
        self.assertIn("МАТЕРИАЛ", item.why_ru)

    def test_two_runs_merely_touching_are_not_ruled_on(self):
        """The code-mandated clearance between routes is not expressed by
        the program."""
        item = one(DUCT, DUCT2, relation="contact", depth=0.0)
        self.assertEqual(item.rule_id, "run_meets_run_clearance")
        self.assertEqual(item.kind, "unclassified")

    def test_every_refused_rule_carries_its_own_justification(self):
        for name, why in J.REFUSED_RULES.items():
            self.assertGreater(len(why), 80, name)

    def test_a_refusal_is_counted_apart_from_a_rule_that_filtered(self):
        """«Правило сняло пару» and «правила нет» are different facts and
        different counters."""
        verdict = J.judge([finding(FLOOR, COLUMN, depth=295.0, grade="coarse"),
                           finding(FLOOR, WALL, relation="contact", depth=0.0)])
        self.assertEqual(verdict.refused_by_rule,
                         {"structure_meets_structure_overlap": 1})
        self.assertEqual(verdict.filtered_by_rule, {"structure_contact": 1})


# ═════════════════════════════════════════════════════════════════════════
# 4. RUNG = EVIDENTIARY STRENGTH × KIND × DEPTH
# ═════════════════════════════════════════════════════════════════════════

class TheRungIsAContract(unittest.TestCase):

    def test_a_bounding_box_never_reaches_the_repair_rung(self):
        """THE MAIN LAW OF RUNGS. A body is not proven by its bounding box,
        and you cannot promise the designer more than what is proven."""
        item = one(DUCT, BEAM, depth=900.0, grade="coarse")
        self.assertEqual(item.kind, "collision")
        self.assertEqual(item.rung, "look")
        self.assertIsNone(item.proven)

    def test_an_exact_outer_word_without_inner_proof_does_not_reach_repair(self):
        item = one(exact(DUCT), exact(DUCT2), depth=900.0, grade="exact")
        self.assertEqual(item.rung, "look")
        self.assertIsNone(item.proven)

    def test_rectangular_duct_outer_capsules_do_not_become_a_proven_clash(self):
        """REGRESSION proof-firebreak.

        Two 100×100 mm ducts have a 20 mm clearance between the bodies. The
        cross-section is currently raised as a capsule with a radius equal
        to the half-diagonal; the capsules overlap by 21.421 mm even though
        the rectangular bodies are separated. The detector honestly says
        `possible`; judgement used to raise this to `proven=True`,
        `rung=fix`, and offer an executable relocation.
        """
        radius = math.hypot(50.0, 50.0)

        def duct_record(element_id: str, y: float) -> H.HullRecord:
            return H.HullRecord(
                source_id=element_id,
                category="OST_DuctCurves", label="duct", mvp_side="run",
                hull=G.Capsule(((0.0, y, 0.0), (1000.0, y, 0.0)), radius),
                grade="conservative", hull_source="axis_section",
                section_radius_mm=radius, section_round=False,
                section_source="width+height")

        raw = D.evaluate(duct_record("p1/a", 0.0),
                         duct_record("p1/b", 120.0))
        self.assertIsNotNone(raw)
        self.assertEqual(raw.verdict, "possible")
        self.assertAlmostEqual(raw.hull_overlap_depth_mm, 21.421356, places=5)

        item = J.judge([raw.as_dict()]).judged[0]
        self.assertEqual(item.geometry_verdict, "possible")
        self.assertIs(item.proven, False)
        self.assertEqual(item.rung, "look")
        self.assertNotIn("сдвинуть", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_an_overlap_inside_the_grades_own_tolerance_is_not_a_repair(self):
        """The only depth threshold here belongs to SOMEONE ELSE: the
        shell's own grade tolerance (`hulls.TOL_GRADE_MM`). There is no
        in-house 100 or 10 mm here."""
        item = one(DUCT, DUCT2, depth=H.TOL_GRADE_MM["conservative"] / 2)
        self.assertEqual(item.rung, "look")

    def test_the_module_invents_no_depth_threshold_of_its_own(self):
        """Structural protection: depth-threshold numbers are not introduced
        into this module. A threshold written in by reasoning is a class of
        defect under this code."""
        import pathlib
        import re
        source = pathlib.Path(J.__file__).read_text(encoding="utf-8")
        code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        for number in re.findall(r"\b\d+\.\d+\b", code):
            self.assertIn(number, {"0.0", "1e-6"},
                          f"число {number} в коде: порог с потолка?")

    def test_the_ladder_ends_where_there_is_nothing_to_do(self):
        keys = [key for key, _, _ in J.RUNGS]
        self.assertEqual(keys[-1], "note")
        self.assertEqual(keys[0], "fix")
        for _, _, action in J.RUNGS:
            self.assertGreater(len(action), 40, "ступень не назвала действие")


# ═════════════════════════════════════════════════════════════════════════
# 5. DESTRUCTIVE INSTRUCTIONS — ONLY ON WHAT IS PROVEN
# ═════════════════════════════════════════════════════════════════════════

class TheDestructiveInstructionIsGated(unittest.TestCase):

    def test_real_sealed_exact_equality_still_requires_semantic_review(self):
        item = J.judge([sealed_exact_duplicate()]).judged[0]
        self.assertEqual(item.kind, "duplicate")
        self.assertIs(item.proven, True)
        self.assertEqual(item.rung, "look")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)
        self.assertIn("автоматически удалять нельзя", item.next_move_ru)

    def test_tampered_exact_equality_cannot_keep_the_delete_capability(self):
        forged = copy.deepcopy(sealed_exact_duplicate())
        forged["exact_body_equality_proof"]["a"]["hull_source"] = "bbox"
        item = J.judge([forged]).judged[0]
        # Physical overlap remains independently proven; only the equality
        # capability is revoked.  Conflating the axes would hide this exact
        # class of proof tamper.
        self.assertIs(item.proven, True)
        self.assertNotIn("удалить ОДИН", item.next_move_ru)
        self.assertIn("удалять по такой находке нельзя", item.next_move_ru)

    def test_a_duplicate_seen_through_two_bounding_boxes_never_orders_deletion(self):
        """A DEFECT FIXED ON A SIBLING BRANCH (`c9d21573`): the two
        diagonals of a square have ONE bounding box, and the advice
        «удалить одну из них» was erasing a live element. On this branch
        `detect.pair_kind_of` still judges by boxes — so the instruction
        must be locked out here."""
        a = side("p1/x", "OST_Walls", "wall", hull_source="bbox")
        b = side("p1/y", "OST_Walls", "wall", hull_source="bbox")
        item = one(a, b, pair_kind="coincident_duplicate", grade="coarse")
        self.assertEqual(item.kind, "duplicate")
        self.assertNotIn("удалить", item.next_move_ru)
        self.assertIn("сверить", item.next_move_ru)

    def test_an_exact_outer_word_alone_never_orders_deletion(self):
        item = one(exact(DUCT), exact(DUCT2),
                   pair_kind="coincident_duplicate", grade="exact")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)

    def test_two_outer_axes_never_order_deletion(self):
        item = one(DUCT, DUCT2, pair_kind="coincident_duplicate")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)

    def test_the_box_is_refused_by_its_own_name_not_only_by_the_grade(self):
        """DEFENSE IN DEPTH. Today `hulls.py` emits `bbox` only with the
        `coarse` grade (line 816), meaning the grade catches this case on
        its own. The prohibition also holds by the NAME of the source: the
        link «бокс ⇒ coarse» is a property of someone else's module, and the
        day it comes apart must not license a deletion."""
        a = side("p1/x", "OST_Walls", "wall", hull_source="bbox")
        b = side("p1/y", "OST_Walls", "wall", hull_source="bbox")
        item = one(a, b, pair_kind="coincident_duplicate", grade="conservative")
        self.assertNotIn("удалить", item.next_move_ru)

    def test_two_hulls_built_by_different_means_never_prove_coincidence(self):
        """A grid line compared against a footprint does not prove the
        bodies coincide: only like can be compared with like."""
        a = side("p1/x", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/y", "OST_Floors", "floor", hull_source="axis_section")
        item = one(a, b, pair_kind="coincident_duplicate")
        self.assertNotIn("удалить", item.next_move_ru)

    def test_proven_is_three_valued_and_none_is_not_no(self):
        """The same law as in `detect.hulls_coincide`: `None` means «сказать
        нечего», and it must not be confused with `False` in either
        direction."""
        self.assertIsNone(one(DUCT, BEAM, grade="coarse").proven)
        self.assertIs(one(DUCT, DUCT2).proven, False)
        self.assertIsNone(one(exact(DUCT), exact(DUCT2), grade="exact").proven)


# ═════════════════════════════════════════════════════════════════════════
# 6. A COARSENING WE INTRODUCED OURSELVES
# ═════════════════════════════════════════════════════════════════════════

class Prism:
    """A minimal prism of the shape `geom.Prism` — only `bounds()` is
    needed."""

    def __init__(self, z0: float, z1: float) -> None:
        self.z0, self.z1 = z0, z1

    def bounds(self):
        return (0.0, 0.0, self.z0), (1000.0, 1000.0, self.z1)


class Record:
    def __init__(self, source_id: str, hull) -> None:
        self.source_id, self.hull = source_id, hull


def plate_slack(t: float, *, z_ref: float = 0.0,
                grow_class: str | None = "create_floor") -> dict:
    """A record of the coarsening in EXACTLY the shape that `clash_bundle`
    puts into `BundleGeometry.slack`: half-thickness, elevation, and the
    CLASS of the growth convention. `grow_class=None` is a snapshot where
    the convention is not named."""
    rec: dict = {"z_mm": t, "z_ref_mm": z_ref, "why": "plate_z_doubling"}
    if grow_class is not None:
        rec["grow_class"] = grow_class
    return rec


class TheSlackWeAddedIsNotEvidence(unittest.TestCase):

    def test_two_plates_on_one_level_are_not_excused_by_z_doubling(self):
        """THIS TEST SWITCHED SIDES, AND HERE IS WHY. It used to assert the
        opposite — that such a pair is `unproven` — and in doing so it
        locked a certificate into the CONTRACT that could never fail to
        fire: the old condition reduced to
        `2·min(tₐ,t_b) − tₐ − t_b = −|tₐ − t_b| ≤ 0`, true for any
        thicknesses whatsoever and never once asking about the plan (see
        `_plate_can_miss`).

        Two slabs of ONE class at one elevation, whose declared contours
        genuinely intersect in plan, share a volume — and that is a finding.
        The honest neighbor `profile_convexified` is rightly silent here:
        the contours intersect, and it has nothing to refute. The
        measurement of 09.08 (66 «критично» of 99 on `snowdon_plumb_v5`)
        clears not pairs like this one, but the 62 of 76 whose declared
        contours do NOT intersect: the work is done by the contour, not by
        the extent along Z."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        crossing = [[500, 500], [1500, 500], [1500, 1500], [500, 1500]]
        # The contours genuinely intersect — otherwise the test would pass
        # for the wrong reason: the footprint would have cleared it, and it
        # would have said nothing about Z.
        self.assertIs(J.loops_overlap(el, crossing), True)
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/f2": Record("p1/f2", Prism(-152.4, 152.4))}
        profiles = {"p1/f1": {"exterior_loop": el},
                    "p1/f2": {"exterior_loop": crossing}}
        slack = {"p1/f1": plate_slack(152.4), "p1/f2": plate_slack(152.4)}
        item = J.judge([finding(a, b, depth=304.8)], hulls=hulls,
                       profiles=profiles, slack=slack).judged[0]
        self.assertEqual(item.slack, ())
        self.assertNotEqual(item.kind, "unproven")
        self.assertIs(item.proven, False)
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")

    # ── ∃ walks the DIAGONAL of readings, not their square ───────────────

    def test_two_floors_on_one_level_are_never_refuted_by_z_doubling(self):
        """A REGRESSION THAT NOTHING COULD HAVE CAUGHT. The old certificate
        computed `2·min(tₐ,t_b) − tₐ − t_b = −|tₐ − t_b| ≤ 0` —
        IDENTICALLY true for any positive thicknesses, without a single
        reference to the plan. Below, it fires on 25 pairs out of 25; a
        certificate that cannot fail to fire reads as proof without being
        one.

        The diagonal of readings keeps both slabs of ONE class read
        consistently, and under either of the two readings they overlap by
        min(tₐ,t_b) > 0 — ∃ is honestly not found on a single pair."""
        thicknesses = (100.0, 150.0, 200.0, 250.0, 300.0)
        fired_old = fired_new = 0
        for ta in thicknesses:
            for tb in thicknesses:
                a = side("p1/f1", "OST_Floors", "floor",
                         hull_source="profile")
                b = side("p1/f2", "OST_Floors", "floor",
                         hull_source="profile")
                hulls = {"p1/f1": Record("p1/f1", Prism(-ta, ta)),
                         "p1/f2": Record("p1/f2", Prism(-tb, tb))}
                slack = {"p1/f1": plate_slack(ta), "p1/f2": plate_slack(tb)}
                # The earlier condition is written out here VERBATIM: the
                # test must show exactly what it catches, not rely on memory.
                overlap_z = min(ta, tb) - max(-ta, -tb)
                if overlap_z - ta - tb <= 0.0:
                    fired_old += 1
                item = J.judge([finding(a, b, depth=2.0 * min(ta, tb))],
                               hulls=hulls, slack=slack).judged[0]
                if "plate_z_doubling" in item.slack:
                    fired_new += 1
                self.assertNotIn("plate_z_doubling", item.slack,
                                 msg=f"ta={ta} tb={tb}")
        self.assertEqual(fired_old, len(thicknesses) ** 2)
        self.assertEqual(fired_new, 0)

    def test_a_floor_and_a_ceiling_on_one_level_may_still_be_refuted(self):
        """THE CERTIFICATE SURVIVES WHERE IT IS HONEST. A slab and a ceiling
        are two DIFFERENT operations, and their growth conventions differ;
        so the reading «пол вниз, потолок вверх» is legitimate, and under it
        the cross-sections diverge each to its own side of the elevation.
        Narrowing the set of readings is not a ban on the certificate, but a
        requirement that it have grounds."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Ceilings", "ceiling", hull_source="profile")
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/c1": Record("p1/c1", Prism(-152.4, 152.4))}
        slack = {"p1/f1": plate_slack(152.4, grow_class="create_floor"),
                 "p1/c1": plate_slack(152.4, grow_class="create_ceiling")}
        item = J.judge([finding(a, b, depth=304.8)],
                       hulls=hulls, slack=slack).judged[0]
        self.assertIn("plate_z_doubling", item.slack)
        self.assertEqual(item.kind, "unproven")
        self.assertIs(item.proven, False)

    def test_absent_grow_class_is_not_a_refutation(self):
        """SILENCE IS NOT PROOF. The same pair that is cleared under
        different classes remains a finding without the classes: having not
        named the convention, the snapshot refuted nothing, and passing this
        off silently as a refutation is not allowed."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Ceilings", "ceiling", hull_source="profile")
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/c1": Record("p1/c1", Prism(-152.4, 152.4))}
        slack = {"p1/f1": plate_slack(152.4, grow_class=None),
                 "p1/c1": plate_slack(152.4, grow_class=None)}
        item = J.judge([finding(a, b, depth=304.8)],
                       hulls=hulls, slack=slack).judged[0]
        self.assertNotIn("plate_z_doubling", item.slack)

    def test_a_plate_pierced_deeper_than_the_slack_stays_a_finding(self):
        """The coarsening clears EXACTLY as much as it introduced, and not a
        millimeter more: a column that has gone into the slab deeper than
        its thickness remains."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Columns", "column", hull_source="bbox")
        hulls = {"p1/f1": Record("p1/f1", Prism(-100.0, 100.0)),
                 "p1/c1": Record("p1/c1", Prism(-3000.0, 100.0))}
        slack = {"p1/f1": {"z_mm": 100.0}}
        item = J.judge([finding(a, b, depth=200.0, grade="coarse")],
                       hulls=hulls, slack=slack).judged[0]
        self.assertEqual(item.slack, ())
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")

    def test_tiling_plates_do_not_overlap_though_their_convex_hulls_do(self):
        """MEASURED 09.08: 62 of 76 pairs on `snowdon_plumb_v5` are exactly
        this kind (the coarsening explains 61: the 62nd is convex on both
        sides). An L-shaped slab and its neighbor share an EDGE, while their
        convex hulls share an area."""
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        neighbour = [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]
        self.assertFalse(J.loop_is_convex(el))
        self.assertIs(J.loops_overlap(el, neighbour), False)

    def test_a_polygon_swallowed_by_another_is_an_overlap(self):
        outer = [[0, 0], [3000, 0], [3000, 3000], [0, 3000]]
        inner = [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]
        self.assertIs(J.loops_overlap(outer, inner), True)

    def test_a_degenerate_loop_answers_nothing_rather_than_no(self):
        self.assertIsNone(J.loops_overlap([[0, 0], [1, 1]],
                                          [[0, 0], [1, 0], [0, 1]]))

    def test_two_non_convex_plates_that_really_overlap_are_not_excused(self):
        """THE REFUTATION WORKS BOTH WAYS. Non-convexity by itself clears
        nothing: what clears it is the NON-INTERSECTION of the declared
        contours, and when the contours genuinely intersect, the finding
        remains a finding."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        crossing = [[500, 500], [1500, 500], [1500, 1500], [500, 1500]]
        self.assertFalse(J.loop_is_convex(el))
        self.assertIs(J.loops_overlap(el, crossing), True)
        profiles = {"p1/f1": {"exterior_loop": el},
                    "p1/f2": {"exterior_loop": crossing}}
        item = J.judge([finding(a, b, depth=50.0)],
                       profiles=profiles).judged[0]
        self.assertNotIn("profile_convexified", item.slack)

    def test_the_convexified_footprint_only_excuses_a_non_convex_contour(self):
        """A convex contour equals its own hull — there is nothing for it to
        explain."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        square = [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]
        far = [[5000, 5000], [6000, 5000], [6000, 6000], [5000, 6000]]
        profiles = {"p1/f1": {"exterior_loop": square},
                    "p1/f2": {"exterior_loop": far}}
        item = J.judge([finding(a, b, depth=50.0)],
                       profiles=profiles).judged[0]
        self.assertNotIn("profile_convexified", item.slack)


# ═════════════════════════════════════════════════════════════════════════
# 7. NOTHING SILENTLY
# ═════════════════════════════════════════════════════════════════════════

class NothingIsSilent(unittest.TestCase):

    def test_every_judged_pair_names_a_rule_that_exists(self):
        known = {rule.rule_id for rule in J.RULES} | set(J.REFUSED_RULES)
        pairs = [finding(DUCT, DUCT2), finding(PIPE, WALL),
                 finding(FLOOR, COLUMN, grade="coarse"),
                 finding(FLOOR, WALL, relation="contact", depth=0.0),
                 finding(DUCT, DUCT2, pair_kind="coincident_duplicate")]
        for item in J.judge(pairs).judged:
            self.assertIn(item.rule_id, known, item)
            self.assertIn(item.kind, J.KINDS, item)
            self.assertTrue(item.why_ru, item)
            self.assertTrue(item.next_move_ru, item)

    def test_the_three_counts_add_up_to_every_pair_and_none_is_lost(self):
        """A dispute, a pair cleared by a rule, and «правила нет» are three
        different facts, and together they must cover EVERY pair: a lost
        pair reads as the absence of a pair."""
        pairs = [finding(DUCT, DUCT2), finding(PIPE, WALL),
                 finding(FLOOR, COLUMN, grade="coarse"),
                 finding(FLOOR, WALL, relation="contact", depth=0.0)]
        verdict = J.judge(pairs)
        total = (len(verdict.actionable)
                 + sum(verdict.filtered_by_rule.values())
                 + sum(verdict.refused_by_rule.values()))
        self.assertEqual(total, len(pairs))
        self.assertEqual(sum(verdict.by_kind.values()), len(pairs))
        self.assertEqual(sum(verdict.by_rung.values()), len(pairs))

    def test_a_rule_that_fired_publishes_its_justification(self):
        verdict = J.judge([finding(PIPE, WALL),
                           finding(FLOOR, COLUMN, grade="coarse")])
        self.assertEqual(sorted(verdict.justifications),
                         ["run_through_envelope",
                          "structure_meets_structure_overlap"])

    def test_the_next_move_names_the_op_the_author_can_edit(self):
        """The program is not fixed on the basis of an outer-only finding."""
        ops = {"p1/pipe1": {"op": "create_pipe", "id": "pipe1",
                            "diameter_mm": 110},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(PIPE, WALL)], ops=ops).judged[0]
        self.assertNotIn("create_opening", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_an_outer_translation_without_inner_proof_is_not_executable(self):
        item = one(exact(DUCT), exact(DUCT2), grade="exact",
                   translation=[0.0, 0.0, -84.0])
        self.assertNotIn("-84", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_judging_nothing_says_nothing_rather_than_all_clear(self):
        verdict = J.judge([])
        self.assertEqual(verdict.judged, ())
        self.assertEqual(verdict.by_kind, {})


if __name__ == "__main__":
    unittest.main()
