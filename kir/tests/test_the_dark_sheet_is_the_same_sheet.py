"""THE DARK SHEET IS THE SAME SHEET, AND THE HUMAN-FACING ONE HAS NO WORDS
FROM THE INSTRUMENT.

Bought by the owner's word on 08.09.2026, looking at the KIR window after
"make a cube": "there's a pile of junk info for a human… they should see
the minimum amount of info and the maximum amount of action from the
agents… they shouldn't have to guess what our labels mean. Even I don't
know." And in the same breath: the dark theme must be FULLY-FLEDGED.

Fully-fledged is not "we inverted the background." The sheet has colors
THAT CARRY MEANING (anomaly, approximation, refusal), and they must remain
readable. That is why contrast here is COMPUTED per WCAG, rather than
eyeballed.

"The same sheet" is also checked, not promised: dark is produced by ONE
substitution via `preview.DARK_PALETTE` over the finished light version,
and the inverse substitution must return the light version BYTE FOR BYTE.
There is no second branch in the markup — so there is nothing to diverge;
this instrument guards against one ever being introduced.
"""
from __future__ import annotations

import re
import unittest

import kir.preview as P


КУБ = {
    "ir_version": "1.0",
    "intent": "куб",
    "ops": [
        {"op": "create_level", "id": "L1", "name": "Уровень 1", "elev_mm": 0},
        {"op": "create_solid_extrusion", "id": "SE1",
         "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                               "size_mm": [3000, 3000]}},
         "height_mm": 3000, "category": "generic_model", "name": "куб"},
    ],
}

#: Instrument words the human never asked for and whose meaning, by the
#: owner's own word, not even he knows.
СЛОВА_ПРИБОРА = ("перепись", "ПЕРЕПИСЬ", "digest", "САМОПРОВЕРКА", "ЗАЯВЛЕНО",
                 "слепот", "СЛЕПОТ", "аномал", "АНОМАЛ", "покрытие",
                 "НАРИСОВАНО", "нарисовано", "модель не читалась",
                 "ЭТОТ ЭКРАН НЕ ПОКАЖЕТ")

#: The WCAG 2.1 AA readable-text threshold.
ПОРОГ = 4.5

#: Colors whose VALUE carries meaning: losing them is losing a fact, not
#: beauty.
СМЫСЛОВЫЕ = ("#c0392b",   # anomaly
             "#8a5200",   # approximation (grid instead of body)
             "#b0392e",   # refusal: empty / north not set
             "#2b3440",   # primary ink
             "#3c4855",   # element labels and the footer
             "#5a6673")   # coverage line


def _лист(**kw) -> str:
    план = P.build_program_preview(КУБ).plans[0]
    return P.render_svg(план, title_ru=P.program_headline(КУБ), **kw)


def _без_метаданных(svg: str) -> str:
    """The machine channel is excluded from the comparison: it is neither
    colored nor addressed."""
    return re.sub(r"<metadata.*?</metadata>", "", svg, flags=re.S)


class ТемаМеняетТолькоЦвета(unittest.TestCase):

    def test_dark_is_the_light_sheet_with_the_table_applied(self):
        светлый = _без_метаданных(_лист())
        тёмный = _без_метаданных(_лист(theme="dark"))
        self.assertNotEqual(светлый, тёмный, "тёмный лист не отличается вовсе")
        обратно = тёмный
        # Long values first: the substitution must not eat a substring.
        for светлое, тёмное in sorted(P.DARK_PALETTE.items(),
                                      key=lambda kv: -len(kv[1])):
            обратно = обратно.replace(тёмное, светлое)
        self.assertEqual(светлый, обратно,
                         "тёмный лист отличается НЕ только цветами таблицы")

    def test_metadata_is_not_painted(self):
        светлый = _лист()
        тёмный = _лист(theme="dark")
        взять = lambda s: re.search(r"<metadata.*?</metadata>", s, re.S).group(0)
        self.assertEqual(взять(светлый), взять(тёмный))

    def test_every_colour_on_the_sheet_is_in_the_table(self):
        """A color forgotten in the table would glow as a white patch on the
        dark sheet."""
        for адресат in P.AUDIENCES:
            svg = _без_метаданных(_лист(audience=адресат))
            for цвет in set(re.findall(r"#[0-9a-f]{6}", svg)):
                self.assertIn(цвет, P.DARK_PALETTE,
                              f"{цвет} нет в DARK_PALETTE ({адресат})")

    def test_an_unknown_colour_is_refused_not_kept(self):
        with self.assertRaises(P.PreviewError):
            P._to_dark('<rect fill="#123456"/>')

    def test_a_wrong_theme_is_refused(self):
        with self.assertRaises(P.PreviewError):
            _лист(theme="sepia")


class СмыслНеТонетНиВОднойТеме(unittest.TestCase):

    def test_meaningful_colours_stay_readable_in_both_themes(self):
        фон = {"light": "#fcfcfd", "dark": P.DARK_PALETTE["#fcfcfd"]}
        плохие = []
        for светлый in СМЫСЛОВЫЕ:
            пары = (("light", светлый), ("dark", P.DARK_PALETTE[светлый]))
            for тема, цвет in пары:
                к = P.contrast_ratio(цвет, фон[тема])
                if к < ПОРОГ:
                    плохие.append(f"{тема} {цвет} к полю {фон[тема]}: {к:.2f}")
        self.assertEqual([], плохие, "контраст ниже 4.5: " + "; ".join(плохие))

    def test_the_dark_theme_is_not_a_downgrade(self):
        """The dark sheet has no right to be PALER than the light one in any
        single color."""
        хуже = []
        for светлый, тёмный in P.DARK_PALETTE.items():
            к_св = P.contrast_ratio(светлый, "#fcfcfd")
            к_тм = P.contrast_ratio(тёмный, P.DARK_PALETTE["#fcfcfd"])
            if к_тм < к_св - 0.2:
                хуже.append(f"{светлый}->{тёмный}: {к_св:.2f} -> {к_тм:.2f}")
        self.assertEqual([], хуже, "тёмная тема бледнее светлой: "
                         + "; ".join(хуже))


class ЛистЧеловекуМолчитПоПрибору(unittest.TestCase):

    def test_the_human_sheet_carries_no_instrument_words(self):
        видимое = _без_метаданных(_лист())
        найдено = [w for w in СЛОВА_ПРИБОРА if w in видимое]
        self.assertEqual([], найдено, f"на листе человека: {найдено}")

    def test_the_human_sheet_carries_the_owners_own_line(self):
        видимое = _без_метаданных(_лист())
        self.assertIn("куб 3×3×3 м", видимое)
        self.assertIn("Уровень 1", видимое)

    def test_nothing_is_lost_the_addressee_changed(self):
        """Everything that left the sheet lies in the machine channel of THE
        SAME file."""
        человеку = _лист()
        мета = re.search(r"<metadata.*?</metadata>", человеку, re.S).group(0)
        for ключ in ("census", "considered", "drawn", "approx", "assertion"):
            self.assertIn(ключ, мета, f"{ключ} потерян вместе с листом")
        прибору = _без_метаданных(_лист(audience="instrument"))
        for слово in ("ПЕРЕПИСЬ", "ЭТОТ ЭКРАН НЕ ПОКАЖЕТ", "digest"):
            self.assertIn(слово, прибору, f"лист прибора потерял {слово}")


class ЛистРисуетПРЕДМЕТПРОСЬБЫ(unittest.TestCase):

    def test_a_single_extrusion_draws_one_subject(self):
        план = P.build_program_preview(КУБ).plans[0]
        self.assertEqual(1, план.census.drawn)
        self.assertEqual(1, len(план.elements))
        self.assertEqual("SE1", план.elements[0].element_id)

    def test_the_body_says_it_is_not_bound_to_a_level(self):
        план = P.build_program_preview(КУБ).plans[0]
        причины = {g.reason for g in план.census.approx}
        self.assertIn(P.ApproxReason.LEVEL_NOT_BOUND, причины)

    def test_context_is_dimmed_not_deleted(self):
        стены = [{"op": "create_level", "id": "L1", "name": "Уровень 1",
                  "elev_mm": 0}]
        стены += [{"op": "create_wall", "id": f"W{i}",
                   "p0_mm": [i * 1000.0, 0.0], "p1_mm": [i * 1000.0, 6000.0],
                   "level": {"by": "ref", "value": "L1"}} for i in range(4)]
        план = P.build_program_preview({"ops": стены + КУБ["ops"][1:]}).plans[0]
        svg = P.render_svg(план, focus=["SE1"])
        self.assertIn('data-el="SE1"', svg)
        self.assertIn('data-context="1"', svg, "чужое не погашено")
        self.assertIn('data-el="W0"', svg, "чужое исчезло вместо того, "
                                           "чтобы погаснуть")
        self.assertEqual(4, svg.count('data-context="1"'))
        # Without focus, nothing fades: the default does not hide anything.
        self.assertNotIn('data-context="1"', P.render_svg(план))


УРОВЕНЬ = {"op": "create_level", "id": "L1", "name": "Уровень 1",
           "elev_mm": 0}

#: The REVOLVE body. The profile is read in AXIAL coordinates (`ops_solid`:
#: x is the RADIUS from the axis, y is the elevation along the axis, "x >= 0"
#: per Revit's own requirement), so its points do NOT lie in the plan: an
#: annulus of radii 500…800 mm.
ВРАЩЕНИЕ = {"op": "create_solid_revolve", "id": "RV1", "name": "колонна",
            "profile": {"outer": {"shape": "rect", "origin": [500, 0],
                                  "size_mm": [300, 3000]}},
            "axis_xy_mm": [0.0, 0.0], "sweep_deg": 360,
            "category": "generic_model"}

#: The TRANSITION body. Both profiles lie in parallel XY planes, so the
#: plan honestly shows the LOWER one, and its difference from the upper one
#: is named.
ПЕРЕХОД = {"op": "create_solid_blend", "id": "BL1", "name": "переход",
           "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                 "size_mm": [2000, 2000]}},
           "profile_top": {"outer": {"shape": "rect", "origin": [500, 500],
                                     "size_mm": [1000, 1000]}},
           "height_mm": 3000, "category": "generic_model"}


class СледТелаВращенияИПереходаНеМолчит(unittest.TestCase):
    """"NOT DONE" #4 of wave 9: revolve/blend had NOTHING in the plan.

    Before the fix, both fell into `OmitReason.NO_LEVEL_SLOT` — "the
    operation has no level field at all" — and the program sheet for a
    single revolve body came out EMPTY, exactly the way the cube's sheet
    came out empty before 08.09. In this case a human sees either someone
    else's slice or nothing, and both answers are wrong.

    WHAT IS CHECKED HERE IS NOT BEAUTY BUT THE HONESTY OF THE TRACE: for a
    transition, the plan shows the LOWER profile (the upper one is said to
    differ), for a revolve, it shows an annular sector spanning the
    profile's RADIAL extent (the profile itself does not lie in the plan —
    said so), and when a trace is not produced at all, the census names
    this by its own name, not as "there is no geometry."
    """

    def test_a_revolve_draws_its_swept_sector_and_names_the_approximation(self):
        план = P.build_program_preview({"ops": [УРОВЕНЬ, ВРАЩЕНИЕ]}).plans[0]
        self.assertEqual(1, план.census.drawn, "тело вращения не нарисовано")
        причины = {g.reason for g in план.census.approx}
        self.assertIn(P.ApproxReason.REVOLVE_TRACE_IS_SWEPT_SECTOR, причины)
        # THE TRACE IS AN ANNULUS, NOT THE PROFILE: all points lie between
        # radii 500 and 800 mm from the axis (0,0), that is, within the
        # profile's span along x.
        точки = [точка
                 for форма in план.elements[0].shapes
                 if isinstance(форма, P.Poly)
                 for контур in форма.loops for точка in контур]
        радиусы = [round((x * x + y * y) ** 0.5) for x, y in точки]
        self.assertEqual({500, 800}, set(радиусы),
                         f"след не кольцевой: радиусы {sorted(set(радиусы))}")

    def test_a_blend_draws_its_bottom_profile_and_says_the_top_differs(self):
        план = P.build_program_preview({"ops": [УРОВЕНЬ, ПЕРЕХОД]}).plans[0]
        self.assertEqual(1, план.census.drawn, "тело перехода не нарисовано")
        причины = {g.reason for g in план.census.approx}
        self.assertIn(P.ApproxReason.BLEND_TOP_PROFILE_DIFFERS, причины)

    def test_an_underivable_trace_is_a_named_refusal_not_silence(self):
        """The author's input is COMPLETE, and there is no trace — there is
        nothing for them to fix, and this is said."""
        слепое = dict(ВРАЩЕНИЕ, id="RV2",
                      profile={"outer": {"shape": "circle", "r_mm": 900}})
        перепись = P.build_program_preview({"ops": [УРОВЕНЬ, слепое]}).census
        причины = {g.reason for g in перепись.omitted}
        self.assertIn(P.OmitReason.BODY_TRACE_NOT_DERIVABLE, причины)
        self.assertNotIn(P.OmitReason.NO_LEVEL_SLOT, причины,
                         "род поддержан — «нет поля уровня» тут неправда")
        строки = [с["ru"] for с in P.census_lines(перепись)
                  if с["reason"] == "body_trace_not_derivable"]
        self.assertEqual(1, len(строки))
        self.assertIn("не выводится", строки[0])

    def test_the_new_bodies_do_not_bring_a_colour_outside_the_table(self):
        """The dark sheet must hold up on new bodies too."""
        for тело in (ВРАЩЕНИЕ, ПЕРЕХОД):
            план = P.build_program_preview({"ops": [УРОВЕНЬ, тело]}).plans[0]
            for адресат in P.AUDIENCES:
                svg = _без_метаданных(P.render_svg(план, audience=адресат))
                for цвет in set(re.findall(r"#[0-9a-f]{6}", svg)):
                    self.assertIn(цвет, P.DARK_PALETTE,
                                  f"{цвет} нет в DARK_PALETTE ({адресат})")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
