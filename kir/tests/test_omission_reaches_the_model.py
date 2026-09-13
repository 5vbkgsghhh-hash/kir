"""WHAT GETS DECIDED WITHOUT THE AUTHOR must reach the model, not just sit
in the registry.

THE COST OF SILENCE WAS MEASURED LIVE, and it is not hypothetical.
`create_column.top_level` is omitted — the height comes from the TYPE's
default, not from the program: **420 columns silently ended up at 2500 mm
instead of 3600-4500**. Not a single refusal, not a line in the receipt;
three audits walked right past it. The same with a room: an omitted
`upper_offset_mm` leaves the upper limit at 2438, and `HAB022` screams about
a figure the author had no way to set.

Knowledge of this sat in the registry THE WHOLE TIME —
`ParamSpec.omission_transfers`, eight fields, each with its cause spelled
out in words — and it was PASSIVE: it described the consequence and went
nowhere. The constitution demands the opposite: the model CANNOT SEE, so the
environment must TELL, and in the same units the model wrote in.

🔴 WHAT THIS GUARD IS NOT. It does not check that the list of eight fields
is COMPLETE — completeness is unattainable here and is not claimed. It
checks that what is ALREADY named in the registry reaches the reader, and
what is not named stays silent.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.ground import describe_omissions_ru, omitted_authorities
from kir.serving import _RECEIPT_ORDER_HEAD


def _wall(**over) -> dict:
    op = {"op": "create_wall", "id": "W1",
          "level": {"by": "name", "value": "L01"},
          "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3200}
    op.update(over)
    return op


class ПосылкаПодКоторойСтоитПрибор(unittest.TestCase):
    """A named definition resting on an unchecked premise is not a
    measurement.

    The instrument treats the ABSENCE of a key in the op as an omission.
    That is true exactly as long as the field has no registry default: a
    field with a default the registry will fill in by itself, and the
    "omission" becomes indistinguishable from a filled-in field.
    """

    def test_no_field_with_omission_transfers_carries_a_registry_default(self):
        виноватые = [
            f"{op.name}.{p.name}"
            for op in spec.OPS.values() for p in op.params
            if p.omission_transfers and p.default is not None]
        self.assertEqual(виноватые, [], (
            "поле с omission_transfers получило реестровое умолчание: реестр "
            "заполнит его сам, и прибор перестанет видеть пропуск, ничего об "
            "этом не сказав"))

    def test_the_registry_carries_the_knowledge_at_all(self):
        сколько = sum(1 for op in spec.OPS.values() for p in op.params
                      if p.omission_transfers)
        self.assertGreater(сколько, 0, (
            "ни одного поля с omission_transfers — тогда весь этот сторож "
            "зелен по ПОСТРОЕНИЮ и меряет пустоту"))


class ПропускДоезжает(unittest.TestCase):

    def test_an_omitted_slot_names_what_takes_power(self):
        строки = omitted_authorities([_wall()])
        self.assertEqual([(r["op"], r["param"]) for r in строки],
                         [("create_wall", "top_level")])
        текст = describe_omissions_ru(строки)
        self.assertIn("top_level", текст)
        self.assertIn("height_mm", текст,
                      "строка обязана нести ПРИЧИНУ из реестра, а не только имя")

    def test_the_column_case_that_cost_420_columns(self):
        колонна = {"op": "create_column", "id": "C1", "xy": [0, 0],
                   "level": {"by": "name", "value": "L01"}}
        текст = describe_omissions_ru(omitted_authorities([колонна]))
        self.assertIn("умолчания типа", текст, (
            "именно эта фраза отличает «высоту решит ТИП» от «высота не "
            "задана»; без неё модель не знает, что есть о чём спрашивать"))

    def test_a_member_of_a_group_is_not_lost(self):
        группа = {"op": "create_group", "id": "g1",
                  "members": [_wall(id="m1")]}
        строки = omitted_authorities([группа])
        self.assertEqual([r.get("inside_group") for r in строки], ["g1"], (
            "член единицы обязан быть назван вместе с группой: unit() — приём, "
            "который курс рекомендует для квартиры"))


class РАЗЛИЧИТЕЛИ(unittest.TestCase):
    """Without them, the guard is green even for an instrument that says
    ALWAYS.

    Today's shift caught four tests green by construction: one measured a
    finding count insensitive to the fix; another looked at the first line
    only where it had found a name; a third kind could never fire at all.
    Below are three negative cases, and each must turn red for a
    chatterbox instrument.
    """

    def test_a_given_slot_is_silent(self):
        строки = omitted_authorities(
            [_wall(top_level={"by": "name", "value": "L02"})])
        self.assertEqual(строки, [], "автор сказал — говорить не о чем")
        self.assertEqual(describe_omissions_ru(строки), "", (
            "примечание «ничего не произошло» есть шум, а шум учит не читать "
            "примечаний"))

    def test_a_field_without_omission_transfers_is_silent(self):
        строки = omitted_authorities([_wall()])
        опущенные = {"arc", "location_line", "structural"}
        назван = {r["param"] for r in строки} & опущенные
        self.assertEqual(назван, set(), (
            f"опущено и НЕ названо в реестре, но прибор заговорил: {назван}. "
            "Пропуск украшения — не пропуск механизма"))

    def test_an_empty_program_says_nothing(self):
        self.assertEqual(omitted_authorities([]), [])
        self.assertEqual(describe_omissions_ru([]), "")


class ДоездДоЧитателя(unittest.TestCase):

    def test_the_receipt_keeps_it_when_truncated(self):
        self.assertIn("omissions_note_ru", _RECEIPT_ORDER_HEAD, (
            "строка, которую режут первой, не предотвратила бы ни одной из "
            "420 колонн"))
        self.assertIn("omitted_authorities", _RECEIPT_ORDER_HEAD)

    def test_it_stands_beside_its_siblings_not_instead_of_them(self):
        for сосед in ("defaults_note_ru", "resolved_refs_note_ru"):
            self.assertIn(сосед, _RECEIPT_ORDER_HEAD, (
                "три вопроса — три отчёта; потерять соседа значит слить "
                "«что выбрал компилятор» с «что решится без меня»"))


if __name__ == "__main__":
    unittest.main()
