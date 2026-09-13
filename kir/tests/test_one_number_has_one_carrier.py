"""ONE NUMBER — ONE CARRIER. A SECOND ONE WILL DRIFT, IT IS ONLY A MATTER OF
TIME.

A class of audit findings from 29.08.2026 (`F-117`, `F-190`, `F-192`,
`F-193`, `F-316`): a language limit is recorded TWICE — in the validator
(the authority) and in text the MODEL reads (a tool schema, a course
lesson, an expressiveness census). Measurement showed all five pairs had
already drifted apart:

    create_group.members   schema 200        <- registry 1000            (F-190)
    create_group.members   lesson "1..200"   <- registry 1000            (F-192)
    op budget               lesson "300"      <- compiler 100 000         (F-193)
    grid_array.dx_mm       schema unbounded  <- unfolder 100..1e5        (F-117)
    graph-edge endpoint     schema "string"   <- node name: length+pattern (F-117)
    plane.origin_mm        census 500 000    <- validator 100 000 000    (F-316)
    wall_layers.function    census "six"      <- registry 8               (F-316)

🔴 THE COST FOR THIS LANGUAGE IS SPECIAL. KIR's primary user is an LLM, not a
human with a mouse. Drifted text is not cosmetic, it is a direct lie to
whoever writes a program BY IT: the model either spends a round on a
program the text permitted and the compiler rejected, or fails to build
something that can, in fact, be built.

WHY THE NUMBERS ARE NOT CHECKED HERE. A literal `1000` in the test would
become a THIRD carrier and would turn red on a LAWFUL move of the ceiling,
demanding a fix to itself. Every check reads the AUTHORITY CONSTANT. The
fixes that closed these findings made the second carrier DERIVED — so most
of the checks below are green BY CONSTRUCTION, and that is the intent: they
guard exactly the places derivation has not yet reached, and stop the
hand-typed number from being brought back there.

A FAIL CONTROL was carried out for each one: reverting the corresponding fix
turns EXACTLY its own check red (see
`/opt/kir-audit/patches/F-{117,190,192,193,316}.md`).
"""
from __future__ import annotations

import unittest


class СхемаНеШиреВалидатора(unittest.TestCase):
    """The schema is what the model writes by and what decodes it. Wider
    than the validator, it means a round spent for nothing; narrower, a
    ban on something lawful."""

    def test_the_schema_group_cap_is_the_registry_cap(self):
        """F-190. We read the CONSTANT, not a digit."""
        from kir import schema_gen, spec
        sch = schema_gen._op_schema(spec.OPS["create_group"])
        self.assertEqual(sch["properties"]["members"]["maxItems"],
                         spec.GROUP_MEMBERS_MAX)

    def test_the_schema_and_the_authoring_validator_agree_on_the_edge(self):
        """F-190, BOTH OUTCOMES on the same input: at the ceiling —
        accepted, at ceiling+1 — rejected. Checking only one end would
        leave open "the schema bans everything."""
        import jsonschema
        from kir import schema_gen, spec
        V = jsonschema.Draft202012Validator(schema_gen.program_schema())

        def prog(count: int) -> dict:
            return {"ir_version": "1.0", "ops": [{
                "op": "create_group", "id": "g",
                "members": [{"op": "create_wall", "id": f"w{i}",
                             "p0_mm": [0, 0], "p1_mm": [1000, 0],
                             "level": "Этаж 1"} for i in range(count)],
                "placements": [[0, 0]]}]}

        self.assertFalse(list(V.iter_errors(prog(spec.GROUP_MEMBERS_MAX))),
                         "законная группа на потолке реестра отвергнута схемой")
        self.assertTrue(list(V.iter_errors(prog(spec.GROUP_MEMBERS_MAX + 1))),
                        "за потолком схема обязана отказывать")

    def test_the_macro_schema_numbers_are_the_expanders_numbers(self):
        """F-117. A walk over ALL numbers in the macro schema against the
        unfolder's constants.

        The check goes over pairs "path in the schema -> `macros` constant,"
        not over one drifted field: the finding was born precisely because
        one place was guarded while all of them were hand-typed. `dx_mm`/
        `dy_mm` had already drifted; the rest matched BY COINCIDENCE and
        were held by nothing.
        """
        from kir import macros, schema_gen
        by_op = {v["properties"]["op"]["const"]: v["properties"]
                 for v in schema_gen._macro_schemas()}
        # DENOMINATOR CONTROL: an empty walk would be green about nothing.
        self.assertEqual(set(by_op), {"stack", "grid_array", "series"})
        checks = [
            ("stack", "levels", "maximum", macros.MAX_STACK_LEVELS),
            ("grid_array", "nx", "maximum", macros.MAX_GRID_AXIS),
            ("grid_array", "ny", "maximum", macros.MAX_GRID_AXIS),
            ("grid_array", "dx_mm", "minimum", macros.GRID_SPACING_MIN_MM),
            ("grid_array", "dx_mm", "maximum", macros.GRID_SPACING_MAX_MM),
            ("grid_array", "dy_mm", "minimum", macros.GRID_SPACING_MIN_MM),
            ("grid_array", "dy_mm", "maximum", macros.GRID_SPACING_MAX_MM),
            ("series", "count", "maximum", macros.MAX_SERIES_COUNT),
            ("series", "items", "maxItems", macros.MAX_SERIES_OPS),
        ]
        bad = []
        for op, field, key, authority in checks:
            got = by_op[op][field].get(key)
            if got != authority:
                bad.append(f"{op}.{field}.{key}: схема {got!r} != "
                           f"раскрыватель {authority!r}")
        self.assertEqual(bad, [], "\n  ".join([""] + bad))

    def test_the_schema_refuses_a_grid_step_the_expander_refuses(self):
        """F-117, BOTH OUTCOMES: past the boundary the schema refuses, AT
        the boundary — it accepts. Without the second half this would be
        "the schema bans everything."""
        import jsonschema
        from kir import macros, schema_gen
        V = jsonschema.Draft202012Validator(schema_gen.program_schema())

        def errs(dx: float) -> list:
            return list(V.iter_errors({"ir_version": "1.0", "ops": [
                {"op": "grid_array", "id": "n", "nx": 1, "ny": 1,
                 "dx_mm": dx, "dy_mm": dx}]}))

        self.assertTrue(errs(macros.GRID_SPACING_MIN_MM - 1))
        self.assertTrue(errs(macros.GRID_SPACING_MAX_MM + 1))
        self.assertFalse(errs(macros.GRID_SPACING_MIN_MM))
        self.assertFalse(errs(macros.GRID_SPACING_MAX_MM))

    def test_an_edge_end_has_the_same_shape_as_a_node_name(self):
        """F-117. An edge endpoint MUST point at a node
        (`connect.graph_validate`, KIR-L003), so they share one shape. What
        is compared are the schema OBJECTS, not the presence of keys: they
        can drift apart on a single `maxLength` too."""
        from kir import schema_gen, spec
        for op_name in ("route_pipe_system", "route_duct_system"):
            gs = schema_gen._op_schema(spec.OPS[op_name])
            node = gs["properties"]["nodes"]["items"]["properties"]["id"]
            seg = gs["properties"]["segments"]["items"]["properties"]
            for end in ("from", "to"):
                self.assertEqual(
                    seg[end], node,
                    f"{op_name}: конец ребра `{end}` и имя узла — одно и то "
                    f"же значение, и схема обязана описывать их одинаково")

    def test_the_edge_end_refuses_what_the_node_name_refuses(self):
        """BEHAVIOR, not a field: the same values on both ends of the pair.
        A green outcome is mandatory — otherwise "the edge bans
        everything."""
        import jsonschema
        from kir import schema_gen, spec
        gs = schema_gen._op_schema(spec.OPS["route_pipe_system"])
        node = jsonschema.Draft202012Validator(
            gs["properties"]["nodes"]["items"]["properties"]["id"])
        seg = jsonschema.Draft202012Validator(gs["properties"]["segments"]["items"])
        for value in ("", "   ", "x" * 200, "узел-1"):
            edge_ok = not list(seg.iter_errors({"from": value, "to": "a"}))
            node_ok = not list(node.iter_errors(value))
            self.assertEqual(edge_ok, node_ok,
                             f"{value[:16]!r}: ребро {edge_ok}, узел {node_ok}")
        self.assertFalse(list(node.iter_errors("узел-1")),
                         "законное имя узла обязано проходить — иначе проверка "
                         "выше зелена оттого, что запрещено всё")


class УрокКурсаНеУчитУстаревшемуПределу(unittest.TestCase):
    """The lesson is the last place the model goes SPECIFICALLY for the boundary."""

    def test_the_unit_lesson_quotes_the_registry_cap(self):
        """F-192. `assertNotIn` is mandatory on its own: without it, a fix
        that "writes 1000 in next to the 200" would pass, and the lesson
        would carry both numbers at once."""
        from kir import spec
        from kir.course import lessons
        text = lessons.lesson("единица")
        self.assertIn(f"1..{spec.GROUP_MEMBERS_MAX}", text)
        self.assertNotIn("1..200", text)
        # A green outcome proving the instrument sees the lesson's TEXT, not
        # an empty string: otherwise a red test is indistinguishable from a
        # broken render.
        self.assertIn("авторинг-опов", text)

    def test_no_stale_op_budget_in_any_lesson(self):
        """F-193, THE MIRROR of `test_skill.
        test_no_stale_literal_for_the_op_budget`.

        That guard cured the STATIC text and did not see text served ON
        DEMAND — the disease survived next door. The new guard's scope is
        named explicitly: ALL lessons of the course, not one; repeating the
        neighbor's narrowness would mean buying the same defect a third
        time.
        """
        from kir.compiler import MAX_OPS_PER_PROGRAM
        from kir.course import lessons
        topics = list(lessons.LESSONS)
        self.assertGreaterEqual(len(topics), 10)  # denominator control
        stale = [t for t in topics if "300 операций" in lessons.lesson(t)]
        self.assertEqual(stale, [], f"устаревший бюджет опов в уроках: {stale}")
        self.assertIn(str(MAX_OPS_PER_PROGRAM), lessons.lesson("границы"))


class ПотолокПереписиНазываетЭтотЖеПотолок(unittest.TestCase):
    """F-316. The census declares itself a MEASUREMENT (an `execution`), yet
    its ceilings were hand-typed right next to the constant that knows
    them."""

    def test_a_ceiling_that_names_a_bound_names_THIS_bound(self):
        """The check does not parse prose: it takes pairs "census line ->
        authority" declared RIGHT HERE and requires that the authority's
        value BE FOUND AS A NUMBER in the ceiling. It was precisely a word
        ("six") that hid the `wall_layers` discrepancy from any grep for
        digits.

        A line whose ceiling is already computed from the authority passes
        by construction — and that is the intent: the dictionary of pairs
        SHRINKS with every such fix, rather than growing. `surface` is not
        in it: its ceiling itself declares the numbers to be ASSIGNED, they
        have no authority by construction, and adding it in would mean
        making one up.
        """
        from kir import plane, registry_base as rb
        from kir.contour import MAX_HOLES, MAX_RING_POINTS, MIN_RING_POINTS
        from kir.course import expressiveness as ex
        from kir.mesh import MAX_TRIANGLES, MAX_VERTICES
        from kir.ops_boolean import BOOLEAN_PARTS_MAX, BOOLEAN_PARTS_MIN

        def _digits(x) -> str:
            return f"{x:.0f}" if float(x) == int(float(x)) else f"{x:g}"

        pairs = {
            "plane": (plane.PLANE_ORIGIN_ABS_MAX_MM,
                      plane.ORTHOGONALITY_COS_TOL),
            "wall_layers": (rb.WALL_LAYERS_MAX, rb.WALL_LAYER_MIN_MM,
                            rb.WALL_LAYER_MAX_MM,
                            len(rb.WALL_LAYER_FUNCTIONS)),
            "region": (MIN_RING_POINTS, MAX_RING_POINTS, MAX_HOLES),
            "mesh": (MAX_VERTICES, MAX_TRIANGLES),
            "solid_parts": (BOOLEAN_PARTS_MIN, BOOLEAN_PARTS_MAX),
        }
        # DENOMINATOR CONTROL: empty pairs would make the test green about nothing.
        self.assertGreaterEqual(len(pairs), 5)
        bad = []
        for kind, values in pairs.items():
            ceiling = ex.CENSUS[kind].ceiling
            flat = ceiling.replace(" ", "").replace(" ", "")
            for v in values:
                if _digits(v) not in flat and f"{v:g}" not in flat:
                    bad.append(f"{kind}: потолок «{ceiling}» не называет {v}")
        self.assertEqual(bad, [], "\n  ".join([""] + bad))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
