"""PROMOTING SHAPE INTO BIM: every rule with a KNOWN ANSWER and a FAIL
control.

The subject is `kir/promote.py`. 🔴 DO NOT CONFUSE with its neighbor
`test_shape_promotion.py`: that one is about `kir/shape_promotion.py`,
which works AFTER the planner, over `PlannedProgram`. Here the subject is
the author's: a shape written with the `kir.course.rhino` dictionary
gains BIM meaning BEFORE the plan.

WHY EVERY RULE IS CHECKED TWICE, IN BOTH DIRECTIONS
--------------------------------------------------------
A classifier that answers "wall" to everything is green on any set that
only checks success. So every rule here has a PAIR: an input on which the
rule must fire, and an input differing by ONE NUMBER, on which it must
NOT fire and must name the reason. A pair differing by one changed number
is not decoration: it is the very proof that the measured value decides,
not the input's written form.

Degeneracy is checked separately
(`test_the_three_rules_do_not_collapse`): three inputs must diverge into
THREE different outcomes. A set where all three give "wall" would pass
every paired check above, if the controls had been chosen poorly.

🔴 WHAT THIS SET REFUTED, RATHER THAN CONFIRMED
--------------------------------------------
The roof rule (`nz` between vertical and horizontal) is BUILT and is
TODAY UNREACHABLE: not a single word of the author's dictionary produces
a pair of facing faces with a sloped normal. `loft` lays sections
horizontally, `rotate` only rotates around Z, `prism` is a value with no
mesh. This is measured, not inferred:
`test_no_author_word_reaches_the_sloped_rule_today` iterates over the
words and checks the outcome. The branch is kept, not deleted, because it
is correct, and the day the dictionary learns a sloped plane must be
visible: the test will go red and demand a real check with a known
answer.
"""
from __future__ import annotations

import unittest
import math

from kir import dsl, promote as P
from kir.course import rhino


def кольцо(w, h, x0=0.0, y0=0.0):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def тело(w, h, t, *, x0=0.0, y0=0.0, z0=0.0):
    """A straight prism via the author's dictionary: a section at the bottom and the same one at the top."""
    r = кольцо(w, h, x0, y0)
    return rhino.loft([(r, z0), (r, z0 + t)])


def наклонная_плита():
    from kir.mesh import extrude

    mesh = extrude(кольцо(6000, 4000), 200)
    angle = math.radians(25)
    mesh["vertices_mm"] = [[x, y * math.cos(angle) - z * math.sin(angle),
                            y * math.sin(angle) + z * math.cos(angle)]
                           for x, y, z in mesh["vertices_mm"]]
    op = dsl.create_directshape(mesh=mesh, category="mass", name="Наклонная плита")
    return {"mesh": mesh, "ops": [op]}


class PromotionRules(unittest.TestCase):

    def setUp(self) -> None:
        dsl.reset()
        self.этаж = dsl.create_level(elev_mm=0, name="Этаж 1")

    def продвинуть(self, форма, **kw):
        return P.promote(форма, level=self.этаж, **kw)

    # ── RULE 1. A LYING-DOWN SLAB -> FLOOR ────────────────────────────
    def test_a_horizontal_slab_becomes_a_floor(self) -> None:
        r = self.продвинуть(тело(6000, 4000, 200))
        self.assertTrue(r["native"], r.get("reason"))
        self.assertEqual(r["role"], "floors")
        self.assertEqual([o.op for o in r["ops"]], ["create_floor_by_contour"])
        self.assertEqual(r["measured"]["толщина_мм"], 200.0)

    def test_control_a_horizontal_body_too_thick_stays_a_form(self) -> None:
        """The same input, ONE number changed: 200 -> 700 mm."""
        r = self.продвинуть(тело(6000, 4000, 700))
        self.assertFalse(r["native"])
        self.assertEqual(r["reason_key"], "too_thick")
        self.assertIn("700", r["reason"])

    # ── RULE 2. A STANDING STRIP -> WALL ──────────────────────────────
    def test_a_vertical_strip_becomes_a_wall(self) -> None:
        r = self.продвинуть(тело(6000, 200, 3000, y0=5000))
        self.assertTrue(r["native"], r.get("reason"))
        self.assertEqual(r["role"], "walls")
        self.assertEqual([o.op for o in r["ops"]], ["create_wall"])

    def test_the_wall_axis_is_the_face_shifted_by_half_a_thickness(self) -> None:
        """A KNOWN ANSWER. The strip lies in y = 5000..5200, the axis
        must land at y = 5100 — otherwise the wall would be built 100 mm
        off, and this is exactly the quiet shift this module was written
        against."""
        self.продвинуть(тело(6000, 200, 3000, y0=5000))
        стена = [o for o in dsl.current().ops if o["op"] == "create_wall"][0]
        self.assertAlmostEqual(стена["p0_mm"][1], 5100.0, places=6)
        self.assertAlmostEqual(стена["p1_mm"][1], 5100.0, places=6)
        self.assertAlmostEqual(стена["height_mm"], 3000.0, places=6)

    def test_control_a_stubby_vertical_plate_is_not_a_wall(self) -> None:
        """ONE number changed: length 6000 -> 1500 at the same thickness
        600. 1500 < 3 x 600, and this no longer reads as a wall."""
        r = self.продвинуть(тело(1500, 600, 3000, y0=5000))
        self.assertFalse(r["native"])
        self.assertEqual(r["reason_key"], "not_slender")
        self.assertIn("1500", r["reason"])
        self.assertIn("600", r["reason"])

    # ── RULE 3. A POST -> COLUMN, BUT ONLY WITH A TYPE SIZE ─────────────
    def test_control_a_column_without_a_symbol_stays_a_form(self) -> None:
        r = self.продвинуть(тело(400, 400, 3000, x0=8000))
        self.assertFalse(r["native"])
        self.assertEqual(r["reason_key"], "column_needs_symbol")

    def test_a_column_with_a_symbol_becomes_a_column(self) -> None:
        """The same input, ONE name added — the type size."""
        r = self.продвинуть(тело(400, 400, 3000, x0=8000),
                            symbol={"by": "name", "value": "К 400x400"})
        self.assertTrue(r["native"], r.get("reason"))
        self.assertEqual(r["role"], "columns")
        колонна = [o for o in dsl.current().ops if o["op"] == "create_column"][0]
        self.assertAlmostEqual(колонна["xy"][0], 8200.0, places=6)
        self.assertAlmostEqual(колонна["xy"][1], 200.0, places=6)

    # ── DEGENERACY ─────────────────────────────────────────────────────
    def test_the_three_rules_do_not_collapse(self) -> None:
        """Three inputs — three DIFFERENT outcomes. Without this, every
        paired check above would pass for a classifier that always says
        "wall"."""
        исходы = [self.продвинуть(тело(6000, 4000, 200))["role"],
                  self.продвинуть(тело(6000, 200, 3000, y0=5000))["role"],
                  self.продвинуть(тело(400, 400, 3000, x0=8000),
                                  symbol={"by": "name", "value": "К"})["role"]]
        self.assertEqual(исходы, ["floors", "walls", "columns"])

    # ── SUBSTITUTION, NOT ADDITION ─────────────────────────────────────
    def test_promotion_retracts_the_geometry_it_replaces(self) -> None:
        """Otherwise the building ends up built TWICE: as a body and as a
        wall in the same place, and the native-op share does not see this
        — it counts operation kinds."""
        r = self.продвинуть(тело(6000, 200, 3000, y0=5000))
        self.assertEqual(r["retracted"], 1)
        роды = [o["op"] for o in dsl.current().ops]
        self.assertNotIn("create_solid_blend", роды)
        self.assertEqual(роды, ["create_level", "create_wall"])

    def test_control_a_form_that_stayed_keeps_its_geometry(self) -> None:
        r = self.продвинуть(тело(6000, 4000, 700))
        self.assertEqual(r["retracted"], 0)
        self.assertIn("create_solid_blend",
                      [o["op"] for o in dsl.current().ops])

    # ── THE MODULE'S LAW: A VALUE IS EITHER IN THE TYPE, OR NAMED ───────
    def test_a_dimension_handed_to_the_type_is_named(self) -> None:
        r = self.продвинуть(тело(6000, 200, 3000, y0=5000))
        self.assertEqual(r["dimension_from_type"]["толщина_мм"], 200.0,
                         "толщину решает ТИП: без имени параметра она обязана "
                         "быть названа как отданная, а не умолчана")

    def test_a_type_named_by_the_author_is_still_a_handover(self) -> None:
        """A named TYPE decides the thickness exactly as a default: the
        author named a NAME, not a size, and nobody has checked that the
        name matches the shape."""
        r = self.продвинуть(тело(6000, 200, 3000, y0=5000),
                            type={"by": "name", "value": "Кирпич 250"})
        self.assertEqual(r["dimension_from_type"]["толщина_мм"], 200.0)

    def test_a_column_hands_its_whole_section_to_the_symbol(self) -> None:
        """For a column, the WHOLE cross-section is handed over to the
        type — and this must be named. In the fixture's catalog the only
        type size is «К 300x300»: a 400x400 shape would silently end up
        at 300x300."""
        r = self.продвинуть(тело(400, 400, 3000, x0=8000),
                            symbol={"by": "name", "value": "К 300x300"})
        self.assertEqual(r["dimension_from_type"]["сечение_мм"], [400.0, 400.0])

    def test_control_a_thickness_carried_into_the_type_is_not_named(self) -> None:
        r = self.продвинуть(тело(6000, 200, 3000, y0=5000),
                            type_param="Толщина")
        self.assertIsNone(r["dimension_from_type"])

    # ── REFUTATION: THE ROOF IS UNREACHABLE TODAY ────────────────────────
    def test_no_author_word_reaches_the_sloped_rule_today(self) -> None:
        """A MEASUREMENT, not reasoning: an iteration over the
        dictionary's words, not one of which produces a pair of facing
        faces with a sloped normal.

        The day the dictionary learns a sloped plane must be visible: the
        test will go red and demand a real check with a known answer.
        """
        r = кольцо(6000, 4000)
        сдвинутое = кольцо(6000, 4000, 3000, 0)
        попытки = {
            "loft прямой": lambda: rhino.loft([(r, 0), (r, 200)]),
            "loft со сдвигом (сдвиг)": lambda: rhino.loft([(r, 0), (сдвинутое, 200)]),
            "loft с сужением (усечённая пирамида)":
                lambda: rhino.loft([(r, 0), (кольцо(3000, 2000, 1500, 1000), 200)]),
            "поворот вокруг Z": lambda: rhino.rotate(
                rhino.loft([(r, 0), (r, 200)]), 30),
        }
        наклонных = []
        for имя, сделать in попытки.items():
            dsl.reset()
            уровень = dsl.create_level(elev_mm=0, name="Э")
            try:
                res = P.promote(сделать(), level=уровень)
            except Exception as exc:                          # noqa: BLE001
                res = {"role": f"ОТКАЗ {type(exc).__name__}"}
            if res.get("role") == "roofs":
                наклонных.append(имя)
        self.assertEqual(наклонных, [],
                         "словарь научился наклонной грани — правило кровли "
                         "стало достижимым, и его пора проверить известным "
                         "ответом, а не этим опровержением")

    # ── A CLOSED LIST OF CAUSES ────────────────────────────────────────
    def test_the_list_of_reasons_is_closed_and_its_gaps_are_named(self) -> None:
        """A cause that nobody can obtain is a promise, not a rule. The
        uncovered ones are named here by name, and the list is closed."""
        def один_уровень():
            return dsl.create_level(elev_mm=0, name="Э")

        def нет_уровней():
            """The level is NEITHER declared NOR passed — the environment has nowhere to take it from."""
            return None

        def уровень_выше():
            dsl.create_level(elev_mm=10000, name="Э10")
            return None

        def два_на_отметке():
            dsl.create_level(elev_mm=0, name="Э-а")
            dsl.create_level(elev_mm=0, name="Э-б")
            return None

        собрано = set()
        # (how to prepare the program, what to build, extra arguments)
        for приготовить, сделать, kw in (
                (один_уровень, lambda: тело(6000, 4000, 700), {}),
                (один_уровень, lambda: тело(1500, 600, 3000), {}),
                (один_уровень, lambda: тело(400, 400, 3000), {}),
                (один_уровень, lambda: {"не форма": 1}, {}),
                # ── a level the author did not name (02.09.2026)
                (нет_уровней, lambda: тело(6000, 200, 3000), {}),
                (уровень_выше, lambda: тело(6000, 200, 3000), {}),
                (два_на_отметке, lambda: тело(6000, 200, 3000), {}),
                (lambda: {"by": "element_id", "value": 42},
                 lambda: тело(6000, 200, 3000), {}),
                (один_уровень, lambda: тело(6000, 200, 3000, z0=16000), {}),
                (один_уровень, наклонная_плита, {})):
            dsl.reset()
            уровень = приготовить()
            r = P.promote(сделать(), level=уровень, **kw)
            if r.get("reason_key"):
                собрано.add(r["reason_key"])
        непокрыто = set(P.REASONS) - собрано
        self.assertEqual(непокрыто, {
            "no_cap_pair",            # a mesh with no pair of facing faces: revolve
            "ring_not_planar",        # a face with no ring
            "axis_not_recoverable",   # a vertical face did not land as a segment
            "form_is_spoken_for",     # a group took the shape
        }, "список причин изменился — покрой новую либо назови её здесь")


class PlacementSurvivesPromotion(unittest.TestCase):
    """D7: source elevations survive into native IR and generated setters.

    Compiler checks are not live Revit readback; the result says so explicitly.
    """

    def setUp(self):
        dsl.reset()

    def compile_current(self, version="2026"):
        from kir import compiler
        from kir.tests.fixtures import GROUND_SNAPSHOT

        out = compiler.compile_program(
            {"ir_version": "1.0", "ops": list(dsl.current().ops)},
            revit_version=version, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
        return out.csharp

    def test_wall_preserves_absolute_base_height_and_joint_translation(self):
        for elevation, base, height in ((0, 0, 3000), (0, 1200, 3000),
                                        (0, -800, 3000), (4500, 5700, 3200),
                                        (4500, 3800, 2800), (-3000, -1800, 3000)):
            with self.subTest(elevation=elevation, base=base):
                dsl.reset()
                level = dsl.create_level(elev_mm=elevation, name="Э")
                result = P.promote(тело(6000, 200, height, z0=base), level=level)
                wall = dsl.current().ops[-1]
                self.assertTrue(result["native"], result.get("reason"))
                self.assertEqual(wall["base_offset_mm"], base - elevation)
                self.assertEqual(elevation + wall["base_offset_mm"], base)
                self.assertEqual(wall["height_mm"], height)
                self.assertEqual(result["status"], "authored_candidate")
                self.assertFalse(result["verified"])
                for version in ("2023", "2026"):
                    code = self.compile_current(version)
                    self.assertIn("WALL_BASE_OFFSET", code)
                    self.assertIn(f".Set(U({float(base - elevation)}))", code)

    def test_implicit_level_does_not_mean_zero_offset(self):
        low = dsl.create_level(elev_mm=4500, name="Э")
        dsl.create_level(elev_mm=9000, name="Верхний")
        result = P.promote(тело(6000, 200, 3000, z0=5700))
        wall = dsl.current().ops[-1]
        self.assertTrue(result["native"])
        self.assertEqual(wall["level"], low.as_selector())
        self.assertEqual(wall["base_offset_mm"], 1200)

    def test_authored_name_and_ref_resolve_to_the_actual_definition(self):
        for selector in ("Э", {"by": "name", "value": "Э"},
                         {"by": "ref", "value": "level1"}):
            with self.subTest(selector=selector):
                dsl.reset()
                level = dsl.create_level(elev_mm=4500, name="Э")
                result = P.promote(тело(6000, 200, 3000, z0=5700), level=selector)
                self.assertTrue(result["native"], result.get("reason"))
                self.assertEqual(dsl.current().ops[-1]["level"], level.as_selector())
                self.assertEqual(dsl.current().ops[-1]["base_offset_mm"], 1200)

    def test_floor_anchors_top_and_names_type_dependent_bottom(self):
        for elevation, base in ((0, 1200), (4500, 5700), (4500, 3500),
                                (-3000, -4200)):
            with self.subTest(elevation=elevation, base=base):
                dsl.reset()
                level = dsl.create_level(elev_mm=elevation, name="Э")
                result = P.promote(тело(6000, 4000, 200, z0=base), level=level)
                self.assertTrue(result["native"], result.get("reason"))
                floor = dsl.current().ops[-1]
                self.assertEqual(elevation + floor["height_offset_mm"], base + 200)
                self.assertEqual(result["measured"]["placement"]["anchor"], "top")
                self.assertEqual(result["measured"]["placement"]["bottom"],
                                 "depends_on_type_thickness")
                self.assertEqual(result["dimension_from_type"]["толщина_мм"], 200)
                for version in ("2023", "2026"):
                    code = self.compile_current(version)
                    self.assertIn("FLOOR_HEIGHTABOVELEVEL_PARAM", code)
                    self.assertIn(f".Set(U({float(base + 200 - elevation)}))", code)

    def test_column_encodes_both_ends_instead_of_using_family_default_height(self):
        for with_top in (False, True):
            with self.subTest(with_top=with_top):
                dsl.reset()
                level = dsl.create_level(elev_mm=4500, name="Э")
                top = dsl.create_level(elev_mm=9000, name="Верх") if with_top else level
                result = P.promote(тело(400, 400, 4200, z0=5700), level=level,
                                   symbol={"by": "name", "value": "К 300x300"})
                self.assertTrue(result["native"], result.get("reason"))
                column = dsl.current().ops[-1]
                top_elev = 9000 if with_top else 4500
                self.assertEqual(column["base_offset_mm"], 1200)
                self.assertEqual(column["top_level"], top.as_selector())
                self.assertEqual(top_elev + column["top_offset_mm"], 9900)
                for version in ("2023", "2026"):
                    code = self.compile_current(version)
                    self.assertIn("FAMILY_BASE_LEVEL_OFFSET_PARAM", code)
                    self.assertIn("FAMILY_TOP_LEVEL_PARAM", code)
                    self.assertIn("FAMILY_TOP_LEVEL_OFFSET_PARAM", code)
                    self.assertIn(f".Set(U({float(9900 - top_elev)}))", code)

    def test_column_can_be_below_its_explicit_level_with_negative_offsets(self):
        level = dsl.create_level(elev_mm=4500, name="Э")
        result = P.promote(тело(400, 400, 3000, z0=1200), level=level,
                           symbol={"by": "name", "value": "К 300x300"})
        self.assertTrue(result["native"], result.get("reason"))
        column = dsl.current().ops[-1]
        self.assertEqual(column["base_offset_mm"], -3300)
        self.assertEqual(column["top_offset_mm"], -300)
        self.assertEqual(column["top_level"], level.as_selector())
        for version in ("2023", "2026"):
            self.compile_current(version)

    def test_wall_offset_limits_are_inclusive(self):
        from kir import spec

        offset = next(p for p in spec.OPS["create_wall"].params
                      if p.name == "base_offset_mm")
        for value in (offset.min_val, offset.max_val):
            with self.subTest(offset=value):
                dsl.reset()
                level = dsl.create_level(elev_mm=0, name="Э")
                result = P.promote(тело(6000, 200, 3000, z0=value), level=level)
                self.assertTrue(result["native"], result.get("reason"))
                self.assertEqual(dsl.current().ops[-1]["base_offset_mm"], value)

    def test_unknown_level_keeps_each_original_shape(self):
        for selector in ({"by": "element_id", "value": 42},
                         {"by": "name", "value": "Неизвестный"},
                         {"by": "ref", "value": "missing"}):
            for w, h, depth, kwargs in ((6000, 200, 3000, {}),
                                        (6000, 4000, 200, {}),
                                        (400, 400, 3000, {"symbol": "К"})):
                with self.subTest(selector=selector, size=(w, h, depth)):
                    dsl.reset()
                    shape = тело(w, h, depth, z0=1200)
                    before = list(dsl.current().ops)
                    result = P.promote(shape, level=selector, **kwargs)
                    self.assertFalse(result["native"])
                    self.assertEqual(result["reason_key"], "level_elevation_unknown")
                    self.assertEqual(result["status"], "geometry_only")
                    self.assertEqual(result["retracted"], 0)
                    self.assertEqual(list(dsl.current().ops), before)

    def test_missing_nonfinite_or_contradictory_level_elevation_is_not_zero(self):
        for elevation in (None, float("nan"), float("inf"), True, 9000):
            with self.subTest(elevation=elevation):
                dsl.reset()
                level = dsl.create_level(elev_mm=4500, name="Э")
                dsl.current().ops[0]["elev_mm"] = elevation
                shape = тело(6000, 200, 3000, z0=5700)
                result = P.promote(shape, level=level)
                self.assertEqual(result["reason_key"], "level_elevation_unknown")
                self.assertEqual(result["retracted"], 0)

    def test_unexpressible_offsets_keep_geometry_for_all_three_roles(self):
        for w, h, depth, kwargs in ((6000, 200, 3000, {}),
                                    (6000, 4000, 200, {}),
                                    (400, 400, 3000, {"symbol": "К"})):
            for base in (-16000, 16000):
                with self.subTest(size=(w, h, depth), base=base):
                    dsl.reset()
                    level = dsl.create_level(elev_mm=0, name="Э")
                    shape = тело(w, h, depth, z0=base)
                    before = list(dsl.current().ops)
                    result = P.promote(shape, level=level, **kwargs)
                    self.assertEqual(result["reason_key"], "placement_out_of_bounds")
                    self.assertEqual(result["retracted"], 0)
                    self.assertEqual(list(dsl.current().ops), before)

    def test_column_top_offset_limit_can_be_satisfied_by_an_authored_upper_level(self):
        level = dsl.create_level(elev_mm=0, name="Э")
        shape = тело(400, 400, 20000)
        first = P.promote(shape, level=level, symbol="К")
        self.assertEqual(first["reason_key"], "placement_out_of_bounds")
        top = dsl.create_level(elev_mm=20000, name="Верх")
        second = P.promote(shape, level=level, symbol={"by": "name", "value": "К 300x300"})
        self.assertTrue(second["native"], second.get("reason"))
        self.assertEqual(dsl.current().ops[-1]["top_level"], top.as_selector())
        self.assertEqual(dsl.current().ops[-1]["top_offset_mm"], 0)
        self.compile_current()

    def test_dry_candidate_is_not_authored_or_live_verified(self):
        shape = тело(6000, 200, 3000, z0=1200)
        before = list(dsl.current().ops)
        result = P.classify(shape)
        self.assertTrue(result["native"])
        self.assertEqual(result["status"], "geometry_candidate")
        self.assertFalse(result["verified"])
        self.assertEqual(result["retracted"], 0)
        self.assertEqual(list(dsl.current().ops), before)

    def test_sloped_roof_remains_geometry_until_placement_is_defined(self):
        level = dsl.create_level(elev_mm=0, name="Э")
        shape = наклонная_плита()
        before = list(dsl.current().ops)
        candidate = P.classify(shape)
        self.assertEqual(candidate["role"], "roofs")
        self.assertEqual(candidate["status"], "geometry_candidate")
        result = P.promote(shape, level=level)
        self.assertEqual(result["reason_key"], "roof_placement_unresolved")
        self.assertEqual(result["retracted"], 0)
        self.assertEqual(list(dsl.current().ops), before)


class PromotedProgramCompiles(unittest.TestCase):
    """The native share counts operation KINDS and is blind to whether
    they compile. So the share's number means nothing without this check:
    a program made entirely of native ops that never reaches C# would
    show 100 %."""

    def test_the_promoted_program_reaches_csharp_on_both_versions(self) -> None:
        from kir import compiler
        from kir.tests.fixtures import GROUND_SNAPSHOT

        dsl.reset()
        этаж = dsl.create_level(elev_mm=0, name="Этаж 1")
        for форма, kw in ((тело(6000, 4000, 200), {}),
                          (тело(6000, 200, 3000, y0=5000), {}),
                          (тело(400, 400, 3000, x0=8000),
                           {"symbol": {"by": "name", "value": "К 300x300"}})):
            r = P.promote(форма, level=этаж, **kw)
            self.assertTrue(r["native"], r.get("reason"))
        ops = list(dsl.current().ops)
        self.assertEqual([o["op"] for o in ops],
                         ["create_level", "create_floor_by_contour",
                          "create_wall", "create_column"])
        for версия in ("2021", "2026"):
            out = compiler.compile_program({"ir_version": "1.0", "ops": ops},
                                           revit_version=версия,
                                           snapshot=GROUND_SNAPSHOT)
            self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
            self.assertGreater(len(out.csharp or ""), 10000, версия)


class ThicknessFindsItsTypeThroughTolerance(unittest.TestCase):
    """A TOLERANCE OF REPRESENTATION, NOT OF SIZE — and both sides are
    checked.

    The shape side is EXACT (measurement: a 380 mm strip gives exactly
    380.0, both axis-aligned and rotated). The CATALOG SIDE diverges:
    Revit stores lengths in feet, and 250 mm arrives as
    250.00000000000003. The pool here carries exactly such values — not
    rounded "for looks", but the ones you get by converting through
    feet: `250 / 304.8 * 304.8`. Exact equality FAILS on them, and this
    is shown by the control.
    """

    ПУЛ = [{"id": 100, "name": "Кирпич 250",
            "params": {"Толщина": 250 / 304.8 * 304.8}},
           {"id": 101, "name": "ЖБ 380",
            "params": {"Толщина": 380 / 304.8 * 304.8}}]

    def _снимок(self):
        import copy
        from kir.tests.fixtures import GROUND_SNAPSHOT
        snap = copy.deepcopy(GROUND_SNAPSHOT)
        snap["wall_types"] = copy.deepcopy(self.ПУЛ)
        return snap

    def _собрать(self, **kw):
        dsl.reset()
        этаж = dsl.create_level(elev_mm=0, name="Этаж 1")
        r = P.promote(тело(6000, 380, 3000, y0=5000), level=этаж, **kw)
        self.assertTrue(r["native"], r.get("reason"))
        return list(dsl.current().ops)

    def test_the_catalog_is_not_exact_and_that_is_the_whole_point(self) -> None:
        """A guard on the fixture itself: if the pool ever became exact,
        both tests below would turn green by degeneracy, checking
        nothing."""
        self.assertNotEqual(self.ПУЛ[1]["params"]["Толщина"], 380.0)
        self.assertLess(abs(self.ПУЛ[1]["params"]["Толщина"] - 380.0), 1e-9)

    def test_a_thickness_finds_its_type_within_the_tolerance(self) -> None:
        from kir import compiler
        out = compiler.compile_program(
            {"ir_version": "1.0", "ops": self._собрать(type_param="Толщина")},
            revit_version="2026", snapshot=self._снимок())
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
        # What travels to C# is the type's ADDRESS, not its name:
        # `doc.GetElement(new ElementId(101))`. 101 is «ЖБ 380», 100 is
        # «Кирпич 250». BOTH are checked, otherwise the test would also
        # pass on a program that grabbed the wrong type.
        self.assertIn("ElementId(101)", out.csharp or "")
        self.assertNotIn("ElementId(100)", out.csharp or "")

    def test_control_exact_equality_refuses_the_very_same_catalog(self) -> None:
        """FAIL CONTROL. The same input, ONE thing differs: there is no tolerance."""
        from kir import compiler
        ops = self._собрать(type_param="Толщина")
        стена = [o for o in ops if o["op"] == "create_wall"][0]
        стена["type"]["disambiguate_by"].pop("tol_mm")
        out = compiler.compile_program({"ir_version": "1.0", "ops": ops},
                                       revit_version="2026",
                                       snapshot=self._снимок())
        self.assertFalse(out.ok, "точное равенство приняло каталог, "
                                 "переведённый через фут, — тогда допуск "
                                 "не нужен и его надо снять")


class TheJudgeCanSeeWhatWasPromoted(unittest.TestCase):
    """🔴 THE NUMBER THIS WAVE MOVES, AND IT IS NOT THE "NATIVE SHARE".

    The gate required a native share >= 80 % on the course's recipes. A
    measurement on 02.09.2026 showed they were green BEFORE the work:
    «оболочка» 85.7 %, «жильё» 100 %. A gate that is green before the
    work says nothing about the work.

    What moves is this: THE DESIGN'S SELF-CHECK IS BLIND TO FREE-FORM
    SHAPE. A room made of four strips and a slab, written with the shape
    dictionary, arrives at the judge as `walls 0` — it reads operation
    kinds, and `create_solid_blend` is not a wall. After promotion, the
    same script gives `walls 4`. The judge does not add any rules in the
    process (there are still no rooms in the program, `HAB000`), and this
    is honest: the test guards VISIBILITY, not the verdict.
    """

    ФОРМА = (
        'этаж = create_level(elev_mm=0, name="Этаж 1")\n'
        'def кольцо(w, h, x0=0.0, y0=0.0):\n'
        '    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]\n'
        'ю = loft([(кольцо(6000, 200, 0, -200), 0), (кольцо(6000, 200, 0, -200), 3000)])\n'
        'с = loft([(кольцо(6000, 200, 0, 4000), 0), (кольцо(6000, 200, 0, 4000), 3000)])\n'
        'з = loft([(кольцо(200, 4000, -200, 0), 0), (кольцо(200, 4000, -200, 0), 3000)])\n'
        'в = loft([(кольцо(200, 4000, 6000, 0), 0), (кольцо(200, 4000, 6000, 0), 3000)])\n')
    ПРОДВИНУТЬ = 'for ф in (ю, с, з, в):\n    promote(ф, level=этаж)\n'
    СУД = 'design_check()\n'

    def _прочитано(self, source: str) -> str:
        from kir import sandbox
        res = sandbox.execute_author_script(source)
        self.assertTrue(res.ok, res.refusal)
        строка = [ln for ln in (res.stdout or "").splitlines()
                  if ln.startswith("прочитано:")]
        self.assertEqual(len(строка), 1, res.stdout)
        return строка[0]

    def test_free_geometry_is_invisible_to_the_judge(self) -> None:
        self.assertIn("walls 0", self._прочитано(self.ФОРМА + self.СУД))

    def test_promotion_makes_the_same_script_visible(self) -> None:
        прочитано = self._прочитано(self.ФОРМА + self.ПРОДВИНУТЬ + self.СУД)
        self.assertIn("walls 4", прочитано)


if __name__ == "__main__":
    unittest.main()
