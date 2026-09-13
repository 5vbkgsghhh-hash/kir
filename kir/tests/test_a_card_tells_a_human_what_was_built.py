"""THE CARD TELLS THE HUMAN WHAT WAS BUILT — AND THE INSTRUMENT SPEAKS SECOND.

Bought by a live turn of the owner's, 2026-09-08. He wrote «make a cube».
A one-operation program was accepted and HELD in KIR (`held_in_kir`),
meaning the cube stood ready to transfer. What arrived in the window, as
the first line, was this:

    census: drawn 94 of 98 (95.92%) · 4 not shown — the op has no drawing
    rule [create_floor_by_contour] · 43 approximated — thickness unknown … ·
    declared by floor: #2607 — 6 · … (over a hundred levels) …
    ⇣ transfer to Revit (124 ops) … signature 93310f4797afc6ed …

and a second card «Level 1 · DECLARED by the program — the model was not
read · programs in the journal: 195». The owner's own words: «what kind of
crap is it dumping in the chat… I asked it to build a cube — it can't».

THREE QUANTITIES THAT EXPLAIN THIS, AND NOT ONE IS ABOUT TASTE:

1. 94 of 98, 124 ops, 195 programs, «#2607 — 6» — NOT ABOUT HIS CUBE. The
   census was taken from a JOURNAL SLICE by floor (`plan_stream._slice_for`,
   a ceiling of 1500 operations), while «declared by floor» came from
   `journal.SessionJournal.summary()`, i.e. the whole session. The human's
   program is one operation out of a hundred and ninety-five programs, and
   it is not visible in these numbers at all.
2. The first line was led by the INSTRUMENT («census», «DECLARED», a
   sixteen-character signature), not the subject («a cube 3000×3000×3000
   mm»). The constitution requires the opposite: the environment must
   speak in units of the model and the human.
3. The hold receipt (`serving`, `held_in_kir`) named the button but did not
   name the SUBJECT: «The program was accepted and shown in the KIR window»
   — accepted WHAT? The human did not understand the cube was ready and
   decided the build had failed.

This instrument pins the outcome, not the text: the FIRST line of the card
is about the subject and the next move; the instrument's words and the
census numbers are in the second half (`details`), and none of them are
lost.
"""
from __future__ import annotations

import re
import unittest


КУБ = {
    "ir_version": "1.0",
    "intent": "куб",
    "ops": [
        {"op": "create_level", "id": "L1", "name": "Уровень 1",
         "elevation_mm": 0},
        {"op": "create_solid_extrusion", "id": "SE1",
         "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                               "size_mm": [3000, 3000]}},
         "height_mm": 3000, "category": "generic_model", "name": "куб"},
    ],
}

#: A sixteen-character signature — exactly what the window printed next to the button.
_HEX16 = re.compile(r"\b[0-9a-f]{16}\b")


class ПерваяСтрокаПроПредмет(unittest.TestCase):

    def test_headline_names_the_body_in_millimetres(self):
        from kir.preview import program_headline

        строка = program_headline(КУБ)
        # Metres, not millimetres: the owner's own words on 09-08 — «A cube 3x3x3 m».
        self.assertIn("3×3×3 м", строка)
        self.assertIn("Уровень 1", строка)
        self.assertIn("1 опер", строка)

    def test_the_first_line_carries_no_instrument_words(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1)
        первая = карточка["summary_ru"].splitlines()[0]
        for слово in ("перепись", "ЗАЯВЛЕНО", "САМОПРОВЕРКА",
                      "модель не читалась", "Модель НЕ читалась"):
            self.assertNotIn(слово, первая, f"{слово!r} в первой строке")
        self.assertIsNone(_HEX16.search(первая), первая)

    def test_the_first_line_names_a_button_that_exists(self):
        """🔴 НАДПИСЬ БЕРЁТСЯ У ЕЁ АВТОРА, А НЕ ПЕРЕПИСЫВАЕТСЯ СЮДА.

        Здесь стоял литерал «перенести в Revit (1 оп» — второй экземпляр
        величины, которая живёт в `preview.TRANSFER_BUTTON_RU`. 13.09.2026
        кнопку переименовали в «Одобрить» (слово владельца: ярлык, а не
        фраза), и литерал покраснел — не потому, что предмет сломался, а
        потому, что в тесте была КОПИЯ. Теперь тест читает автора: он
        покраснеет, если карточка перестанет называть кнопку, и не покраснеет
        от смены слова на ней. Что надпись совпадает с той, что на экране,
        сверяет `backend/tests/test_held_receipt_names_a_real_button.py`.
        """
        from kir.preview import TRANSFER_BUTTON_RU, program_card

        карточка = program_card(КУБ, ops=1)
        self.assertTrue(TRANSFER_BUTTON_RU.strip(),
                        "контроль негоден: у кнопки нет надписи вовсе")
        self.assertIn(TRANSFER_BUTTON_RU, карточка["summary_ru"])
        self.assertIn("3×3×3 м", карточка["summary_ru"])


class ПереписьТолькоПоЭтойПрограмме(unittest.TestCase):

    def test_census_counts_this_program_and_not_a_journal(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1)
        перепись = карточка["details"]["census"]
        # Both operations of THIS program and none foreign from the journal:
        # the body is drawn, the level is counted and named «not visible in the plan».
        self.assertEqual(2, перепись["considered"])
        self.assertEqual(1, перепись["drawn"], "куб не нарисован")
        self.assertEqual({"built": 1, "declarations": 1, "transferred": 1},
                         карточка["details"]["ops_breakdown"])

    def test_declared_levels_are_only_the_levels_of_this_program(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1)
        уровни = [строка["level"] for строка in карточка["levels"]]
        self.assertEqual(["Уровень 1"], уровни)
        self.assertEqual([1], [строка["declared"] for строка in карточка["levels"]])

    def test_level_index_is_cheap_and_program_scoped(self):
        from kir.preview import program_level_index

        индекс = program_level_index(КУБ["ops"])
        self.assertEqual((("Уровень 1", 1),), индекс)


class НичегоНеСпрятано(unittest.TestCase):

    def test_details_keep_every_number_and_every_instrument_word(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1)
        подробности = карточка["details"]
        self.assertIn("census_lines", подробности)
        self.assertTrue(подробности["census_lines"])
        # The honesty outcome is kept — second, not first.
        self.assertIn("модель", подробности["assertion_ru"].lower())
        self.assertIn("ЗАЯВЛЕНО", подробности["instrument_ru"])

    def test_the_human_assertion_says_what_a_human_can_act_on(self):
        from kir.preview import HUMAN_ASSERTION_RU

        self.assertIn("по программе", HUMAN_ASSERTION_RU)
        self.assertNotIn("ЗАЯВЛЕНО", HUMAN_ASSERTION_RU)


#: SESSION SLICE: the level is declared by ANOTHER program, and its `id` is
#: the ElementId of the live document. That is how `built_verdict.datum_ops`
#: presents it («op id = level ElementId in Revit»), and that is how it sits
#: in `journal.SessionJournal.datums`, from where `plan_stream._slice_for`
#: places it BEFORE the slice's own programs.
СРЕЗ = [
    {"op": "create_level", "id": "2607", "name": "Этаж 9", "elev_mm": 27000.0},
    {"op": "create_level", "id": "2608", "name": "Этаж 10", "elev_mm": 30300.0},
    {"op": "create_grid", "id": "G1", "name": "А",
     "p0_mm": [0, 0], "p1_mm": [0, 12000]},
]

#: The human's program: ONE wall on a level it did not declare. This exact
#: shape stood in the owner's window on 09-08 — «declared by floor: #2607 — 6».
СТЕНА_НА_ЧУЖОМ_УРОВНЕ = {
    "ir_version": "1.0",
    "intent": "стена",
    "ops": [
        {"op": "create_wall", "id": "W1",
         "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": {"by": "element_id", "value": 2607}},
    ],
}


class КарточкаВидитДатумыСреза(unittest.TestCase):
    """"Not done" item #3 of wave 9: the floor name did not resolve and was printed as a key.

    Verbatim from the preview-3 register: «`pack[-1]` — only the operations
    of the program itself, and if `create_level` arrived as a separate
    program, the floor's name in its headline will not resolve». Measurement
    before the fix: the headline read (product output, quoted verbatim)
    `стена длиной 6 м · на уровне «#2607» · 1 операция`, while next to it,
    when the same program declared the level ITSELF, the index gave TWO rows
    for one floor — `('#2607', 1)` and `('Этаж 9', 0)`.
    """

    def test_a_level_declared_by_another_program_is_named_from_the_slice(self):
        from kir.preview import program_card

        карточка = program_card(СТЕНА_НА_ЧУЖОМ_УРОВНЕ, ops=1, context=СРЕЗ)
        self.assertIn("на уровне «Этаж 9»", карточка["summary_ru"])
        self.assertEqual([{"level": "Этаж 9", "declared": 1}],
                         карточка["levels"])

    def test_without_the_slice_the_level_stays_unnamed(self):
        """FAIL CONTROL: strip the context — and the floor is a nameless key again.

        Without this class, the neighbouring test's green would be worth
        nothing: it could have been bought by the name resolving from
        somewhere else entirely.
        """
        from kir.preview import program_card

        карточка = program_card(СТЕНА_НА_ЧУЖОМ_УРОВНЕ, ops=1)
        self.assertIn("«#2607»", карточка["summary_ru"])
        self.assertEqual(["#2607"], [с["level"] for с in карточка["levels"]])

    def test_the_slice_gives_names_and_never_a_denominator(self):
        """The context enters NEITHER the census, NOR the op count, NOR the floors.

        This is exactly how the 09-08 card lied: the census was taken from a
        journal slice (94 of 98), while «declared by floor» came from the
        whole session. Here the slice has TWO levels and a grid; the program
        touched ONE, and one is what lands in the card.
        """
        from kir.preview import program_card

        без = program_card(СТЕНА_НА_ЧУЖОМ_УРОВНЕ, ops=1)
        со = program_card(СТЕНА_НА_ЧУЖОМ_УРОВНЕ, ops=1, context=СРЕЗ)
        self.assertEqual(без["details"]["census"], со["details"]["census"])
        self.assertEqual(без["details"]["ops_breakdown"],
                         со["details"]["ops_breakdown"])
        self.assertEqual(1, со["details"]["census"]["considered"])
        self.assertEqual(1, len(со["levels"]),
                         f"этаж среза попал в карточку: {со['levels']}")

    def test_one_floor_is_one_row_whichever_selector_addressed_it(self):
        """`{"by": "ref"}` and `{"by": "element_id"}` — ONE floor, not two.

        Measurement before the fix, on a program that declared the level
        ITSELF: `(('#2607', 1), ('Этаж 9', 0))` — the built count sat on the
        nameless half, and the name sat with a zero.
        """
        from kir.preview import build_program_preview, program_level_index

        своя = list(СРЕЗ[:1]) + list(СТЕНА_НА_ЧУЖОМ_УРОВНЕ["ops"])
        self.assertEqual((("Этаж 9", 1),), program_level_index(своя))
        планы = build_program_preview({"ops": своя}).plans
        self.assertEqual(["Этаж 9"], [п.level_name for п in планы])
        self.assertEqual(27000.0, планы[0].level_elevation_mm,
                         "отметка потерялась вместе с ключом")

    def test_only_an_element_id_shaped_id_is_merged(self):
        """A NAMED LIMIT: only NUMERIC `id`s are merged, and only those.

        The equality «op `id` = ElementId» holds exactly for datums of the
        live document (`built_verdict.datum_ops` is what makes them so). An
        authored `create_level id="L1"` has no relation to Revit element
        #1, and merging `{"by": "element_id", "value": 1}` with it would
        invent a connection — buying the same disease from the other side.
        """
        from kir.preview import program_level_index

        авторский = [{"op": "create_level", "id": "L1", "name": "Этаж 1",
                      "elev_mm": 0}]
        стена = [{"op": "create_wall", "id": "W1",
                  "p0_mm": [0, 0], "p1_mm": [6000, 0],
                  "level": {"by": "element_id", "value": 1}}]
        self.assertEqual((("#1", 1),),
                         program_level_index(стена, context=авторский))


class ДиагнозЖурналаПоРусски(unittest.TestCase):
    """"Not done" item #2 of the `journal-key` shard: the field exists, the human line does not.

    Wave 9 carried the recovery diagnosis as far as the `journal_restore`
    receipt field and stopped there. A field nobody unfolds is an
    instrument's journal, not a message: the owner's own words on 09-08
    about such labels — «even I don't know».
    """

    ОТКАЗ = {
        "restored": 0,
        "refused": "journal_of_another_document_with_the_same_name",
        "programs_by_name": 194,
        "document_name": "Проект1",
        "legacy_key": ("устройство", "Проект1"),
        "next_step_ru": "сохраните документ и откройте заново",
        "detail": "на складе есть 194 программ под именем «Проект1»",
    }

    def test_the_card_unfolds_the_refusal_into_one_human_line(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1, journal_restore=self.ОТКАЗ)
        строки = карточка["summary_ru"].splitlines()
        self.assertEqual(3, len(строки), карточка["summary_ru"])
        # The FIRST line stays the subject of the request, the diagnosis is THIRD.
        self.assertIn("3×3×3 м", строки[0])
        self.assertIn("194", строки[2])
        self.assertIn("с таким же именем", строки[2])
        self.assertIn("НЕ подняты", строки[2])
        self.assertIn("сохраните документ", строки[2])
        self.assertEqual(строки[2], карточка["summary"]["journal_ru"])

    def test_the_human_line_carries_no_instrument_words(self):
        from kir.preview import journal_note_ru

        строка = journal_note_ru(self.ОТКАЗ)
        for слово in ("journal_of_another", "refused", "legacy_key",
                      "programs_by_name", "restored"):
            self.assertNotIn(слово, строка, f"{слово!r} в строке человека")

    def test_the_instrument_keeps_every_word_in_details(self):
        from kir.preview import program_card

        карточка = program_card(КУБ, ops=1, journal_restore=self.ОТКАЗ)
        подробности = карточка["details"]["journal_restore"]
        self.assertEqual("journal_of_another_document_with_the_same_name",
                         подробности["refused"])
        self.assertEqual(194, подробности["programs_by_name"])

    def test_a_turn_without_a_diagnosis_says_nothing(self):
        """A CONTROL: silence where there is nothing to say, not a cheerful «all fine»."""
        from kir.preview import journal_note_ru, program_card

        self.assertEqual("", journal_note_ru(None))
        self.assertEqual("", journal_note_ru({"restored": 7}))
        карточка = program_card(КУБ, ops=1)
        self.assertEqual(2, len(карточка["summary_ru"].splitlines()))
        self.assertNotIn("journal_ru", карточка["summary"])


class КвитанцияУдержания(unittest.TestCase):

    def test_held_receipt_leads_with_the_subject_then_the_button(self):
        import kir.serving as S

        квитанция = S._held_receipt(КУБ, ops=1)
        первая = квитанция["message_ru"].splitlines()[0]
        self.assertIn("3×3×3 м", первая)
        self.assertNotIn("перепись", первая)
        self.assertIsNone(_HEX16.search(первая), первая)
        from kir.preview import TRANSFER_BUTTON_RU
        self.assertIn(TRANSFER_BUTTON_RU, квитанция["message_ru"])
        # The honesty outcome is not lost: it is in the details.
        self.assertIn("НИЧЕГО НЕ ЗАПИСАНО", квитанция["details"]["honesty_ru"])

    def test_a_receipt_without_a_bridge_document_stays_silent_about_it(self):
        """Nothing to compare against is not a reason to say «it matches»."""
        import kir.serving as S

        квитанция = S._held_receipt(КУБ, ops=1)
        self.assertNotIn("document_identity", квитанция)
        # THREE lines — subject, move, honesty outcome. There is no fourth
        # («ATTENTION…»): there was nothing to compare, and silence here is the correct answer.
        строки = квитанция["message_ru"].splitlines()
        self.assertEqual(3, len(строки), строки)
        self.assertNotIn("ВНИМАНИЕ", квитанция["message_ru"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
