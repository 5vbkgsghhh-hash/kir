"""A wall's location line is a defining degree of freedom, and it was missing.

Revit stores a wall as a location CURVE plus a rule (``WALL_KEY_REF_PARAM``)
naming one of its planes: centreline, core centreline, or one of four faces.
Before this change the compiler could neither read that rule nor write it, so
it travelled through no round trip at all.

WHAT THE RULE IS, measured on live Revit 2023 on 2026-07-28 --
``docs/2026-07-28-location-line-measurement.md``, and it is NOT what this file
used to claim:

* the ``LocationCurve`` the API returns is ALWAYS the centre plane of the wall
  body -- for every ordinal, on 724 real walls of the operator's facade model
  (solid tessellation: the two faces sit at exactly -w/2 and +w/2);
* the rule therefore does not describe an offset that already exists; it
  decides WHICH PLANE STAYS PUT when the wall's thickness later changes.
  Measured: swap a 200 mm type for a 400 mm one under ordinal 2 and the
  exterior face holds while the location curve itself slides 100 mm to the new
  centre;
* setting the parameter after ``Wall.Create`` moves neither curve nor body.

So the honest claim is narrow and this file pins it: the emitted wall stands
exactly where Revit natively puts it (which is exactly where the original
stood -- rebuild of a real ordinal-2 wall reproduced its body to the micron),
and the rule is carried as SEMANTIC state, never as proven geometry.
"""

from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.decompile import extract


#: Schema spellings, in Revit's ``WallLocationLine`` order. The names are
#: language-neutral on purpose (INVARIANT #1): a Russian-language Revit reports
#: the same integer.
#: What the op OFFERS: only the planes the emitter can realise from the type's
#: width alone.  Revit's full enum is wider (the core planes), and the lift
#: turns those into honest atoms rather than programs the compiler refuses.
LOCATION_LINES = (
    "wall_centerline",
    "finish_face_exterior",
    "finish_face_interior",
)


class TheExtractorReadsTheLocationLine(unittest.TestCase):
    def test_the_census_pulls_the_wall_key_ref_param(self):
        self.assertIn("WALL_KEY_REF_PARAM", extract._ELEMENT_HELPERS_CS)

    def test_it_is_pulled_as_an_integer_not_a_length(self):
        # The parameter is an enum ordinal. Reading it as a length would
        # silently unit-convert it and produce a plausible, wrong number.
        line = next(l for l in extract._ELEMENT_HELPERS_CS.splitlines()
                    if "WALL_KEY_REF_PARAM" in l and "BuiltInParameter" in l)

        self.assertIn("__PutIntParam", line)


class TheWallOpCanExpressTheLocationLine(unittest.TestCase):
    def setUp(self):
        self.op = spec.OPS["create_wall"]
        self.param = next(
            (p for p in self.op.params if p.name == "location_line"), None)

    def test_create_wall_has_a_location_line_param(self):
        self.assertIsNotNone(
            self.param,
            "create_wall cannot say which plane of the wall its curve is")

    def test_it_offers_every_rule_revit_has(self):
        self.assertEqual(tuple(self.param.choices), LOCATION_LINES)

    def test_it_has_no_default_so_existing_programs_stay_byte_stable(self):
        # Same discipline as base_offset_mm: absent stays absent, so every
        # program authored before this change emits the identical C# and keeps
        # its canon hash.
        self.assertIsNone(self.param.default)
        self.assertFalse(self.param.required)


if __name__ == "__main__":
    unittest.main()


class TheOrdinalTable(unittest.TestCase):
    def test_the_reverse_table_loses_no_row(self):
        """То же утверждение, названное своим именем (переписано 12.08.2026).

        Здесь стояло `test_the_two_directions_are_exact_inverses`: сверка
        ORDINALS с обращением NAMES, где NAMES ПОСТРОЕН обращением ORDINALS
        (`ops_authoring.py:22`).  Сила у него РОВНО ТА ЖЕ, что у строки ниже,
        и это измерено, а не выведено:

            чистая таблица         старый зелён   новый зелён
            ПЕРЕСТАНОВКА пары      старый зелён   новый зелён
            ДУБЛИКАТ ординала      старый КРАСНЫЙ новый КРАСНЫЙ

        Так что менялась НЕ мощность, а честность имени.  Прежнее обещало
        «две таблицы — точные обращения друг друга», то есть звучало как
        проверка ПАР; проверяло же оно единственное, что обращение способно
        не сохранить, — что ординалы попарно различны.  Два имени с одним
        ординалом схлопывают обратную таблицу, и лифт молча читает чужое
        слово; вот это и стоит здесь, прямо.

        Оговорка, чтобы не сползти в обратную крайность: тест НЕ вакуумен —
        на неинъективной таблице он краснеет.  Он вакуумен ровно на том
        классе, который нам сегодня и важен, — на ПЕРЕСТАНОВКАХ.

        ПАРУ имя-ординал этот файл НЕ ПИННИТ И НЕ МОЖЕТ — см. блок над самой
        таблицей: оба конца компилятора берут число оттуда же, поэтому
        свидетель не способен возразить таблице.
        """
        from kukai.ir.ops_authoring import (
            WALL_LOCATION_LINE_NAMES, WALL_LOCATION_LINE_ORDINALS)

        self.assertEqual(len(WALL_LOCATION_LINE_NAMES),
                         len(WALL_LOCATION_LINE_ORDINALS),
                         "обращение потеряло строку: два имени делят ординал")

    def test_every_offered_choice_has_an_ordinal(self):
        from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

        param = next(p for p in spec.OPS["create_wall"].params
                     if p.name == "location_line")

        for name in param.choices:
            with self.subTest(location_line=name):
                self.assertIn(name, WALL_LOCATION_LINE_ORDINALS)

    def test_the_table_still_carries_revits_full_enum(self):
        # The table is Revit's truth, not the op's menu: the lift needs every
        # ordinal to recognise a core plane and refuse it honestly.
        from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

        self.assertEqual(len(WALL_LOCATION_LINE_ORDINALS), 6)

    def test_the_ordinals_are_revits_own_order(self):
        from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

        self.assertEqual(list(WALL_LOCATION_LINE_ORDINALS.values()),
                         [0, 1, 2, 3, 4, 5])


def _wall(**extra):
    op = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(extra)
    return {"ir_version": "1.0", "intent": "test", "ops": [op]}


class TheEmittedCode(unittest.TestCase):
    def _csharp(self, program):
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        return out.csharp

    def test_it_sets_the_parameter_to_the_requested_ordinal(self):
        code = self._csharp(_wall(location_line="finish_face_exterior"))

        self.assertIn("WALL_KEY_REF_PARAM", code)
        self.assertIn(".Set(2);", code)

    def test_a_wall_without_the_field_emits_nothing_about_it(self):
        # Byte-stability: every program authored before this field existed must
        # produce the identical C#, or its canon hash moves for no reason.
        self.assertNotIn("WALL_KEY_REF_PARAM", self._csharp(_wall()))

    def test_the_postcondition_checks_it_by_equality(self):
        code = self._csharp(_wall(location_line="finish_face_interior"))

        # An enum ordinal has no "close enough": the verdict is equality.
        self.assertIn("AsInteger() != 3", code)

    def test_the_verdict_does_not_claim_the_geometry_axis(self):
        # §18.3: the axis in the message is machine-read (serving.py splits the
        # geometry/topology/semantic triple on exactly these substrings). This
        # check reads back an ordinal the emitter itself wrote, and the live
        # measurement says that ordinal moves NOTHING -- so signing it as
        # geometry told every consumer that a placement had been verified when
        # none had. The rule is real state, and semantic is what it is.
        code = self._csharp(_wall(location_line="finish_face_exterior"))

        self.assertNotIn("location line mismatch (geometry)", code)
        self.assertIn("location line mismatch (semantic)", code)

    def test_the_op_post_says_out_loud_that_the_body_does_not_move(self):
        # §18.3 allows "written but moves nothing" ONLY as kind=semantic with
        # explicit text saying so in post. Without that sentence the op's own
        # contract still promises a placement it does not make.
        post = spec.OPS["create_wall"].post

        self.assertIn("location line", post)
        self.assertIn("semantic", post)
        self.assertIn("не смещает", post.lower())

    def test_the_endpoints_are_never_offset_by_half_a_width(self):
        # The refuted hypothesis, pinned so it cannot come back quietly:
        # shifting p0/p1 by factor*width would NOT "realise the effect", it
        # would introduce a displacement -- the rebuilt wall would land half a
        # thickness off the original (measured: 15 mm on a 30 mm wall, exactly
        # w/2). Every location_line must create the wall on the authored line.
        for name in LOCATION_LINES:
            with self.subTest(location_line=name):
                self.assertIn(
                    "Line.CreateBound(P(0, 0, 0), P(6000, 0, 0))",
                    self._csharp(_wall(location_line=name)))

    def test_the_realisable_planes_emit_their_own_ordinal(self):
        from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

        for name in LOCATION_LINES:
            with self.subTest(location_line=name):
                self.assertIn(f".Set({WALL_LOCATION_LINE_ORDINALS[name]});",
                              self._csharp(_wall(location_line=name)))

    def test_no_plane_ever_touches_the_create_offset_argument(self):
        # Measured 2026-07-26: that argument is the wall's BASE offset from
        # its level, not a plan offset. Half a type width went there once and
        # silently raised a wall 100mm (WALL_BASE_OFFSET read back +100) while
        # the plan position -- the only thing the endpoint check looks at --
        # stayed put. Every location_line must leave the literal alone.
        for name in LOCATION_LINES:
            with self.subTest(location_line=name):
                self.assertIn("U(3000.0), 0.0, false, false)",
                              self._csharp(_wall(location_line=name)))

    def test_a_centreline_wall_keeps_the_historical_zero_literal(self):
        # Byte-stability of the overwhelmingly common case.
        self.assertIn("U(3000.0), 0.0, false, false)",
                      self._csharp(_wall(location_line="wall_centerline")))
        self.assertIn("U(3000.0), 0.0, false, false)", self._csharp(_wall()))

    def test_a_core_plane_is_not_offered_at_all(self):
        # The schema advertises exactly what the compiler can realise, so a
        # core plane is an ordinary out-of-choices type error rather than a
        # special case buried in the emitter -- and never a guessed offset.
        from kukai.ir.compiler import compile_program
        from kukai.ir.diag import KirRefusal
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        for name in ("core_centerline", "core_exterior", "core_interior"):
            with self.subTest(location_line=name):
                try:
                    out = compile_program(_wall(location_line=name),
                                          snapshot=GROUND_SNAPSHOT)
                    codes = [d.code for d in out.diagnostics]
                    self.assertFalse(out.ok)
                except KirRefusal as refusal:
                    codes = [d.code for d in refusal.diagnostics]
                self.assertIn("KIR-T001", codes)


class TheCertificateKnowsTheRule(unittest.TestCase):
    """The second hole this fix found, and it was invisible from the emitter.

    ``create_wall`` had NO obligation with key ``location_line`` at all: the
    emitter placed a witness the certificate had never heard of, so deleting
    that witness would have left the certificate saying "proven". That is the
    exact class the certificate exists to catch (the same one the segment
    diameter hit in July).
    """

    def _obligation(self):
        from kukai.ir.translation_cert import _ensure_table

        return next(
            (o for o in _ensure_table()["create_wall"].obligations
             if o.key == "location_line"), None)

    def test_the_obligation_exists(self):
        self.assertIsNotNone(
            self._obligation(),
            "эмиттер ставит свидетеля location_line, а сертификат о нём не "
            "знает — удаление проверки осталось бы «доказанным»")

    def test_it_is_semantic_not_geometry(self):
        from kukai.ir.translation_cert import KIND_SEMANTIC

        self.assertEqual(self._obligation().kind, KIND_SEMANTIC)

    def test_it_is_required_only_when_the_field_is_there(self):
        obligation = self._obligation()

        self.assertTrue(obligation.conditional)
        self.assertEqual(obligation.param, "location_line")

    def test_a_wall_with_the_rule_certifies_proven(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        from kukai.ir.translation_cert import certify_op

        for name in LOCATION_LINES:
            with self.subTest(location_line=name):
                op = ground_mod.ground(
                    _parse_and_check(_wall(location_line=name)),
                    GROUND_SNAPSHOT)[0]
                certificate = certify_op(op, "2024")

                self.assertTrue(certificate.proven, certificate.gaps)
                verdict = next(v for v in certificate.clauses
                               if "location line" in v.clause)
                self.assertTrue(verdict.discharged, verdict.reason)


class TheFrameworkAcceptsAnOptionalEnum(unittest.TestCase):
    """A framework-level gap this change had to open first.

    ``ParamSpec(kind="enum")`` read its value as ``op.get(name, default)``, so
    an optional enum with no default resolved to ``None``, which is in no
    ``choices`` -- every program omitting the field was refused with a type
    error. No op could declare such a param at all, which is why none did.
    """

    def test_omitting_an_optional_enum_is_not_a_type_error(self):
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        out = compile_program(_wall(), snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_supplying_a_value_outside_the_choices_is_still_refused(self):
        from kukai.ir.compiler import compile_program
        from kukai.ir.diag import KirRefusal
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        try:
            out = compile_program(
                _wall(location_line="nonsense"), snapshot=GROUND_SNAPSHOT)
        except KirRefusal as refusal:
            codes = [d.code for d in refusal.diagnostics]
        else:
            codes = [d.code for d in out.diagnostics]
            self.assertFalse(out.ok)

        self.assertIn("KIR-T001", codes)
