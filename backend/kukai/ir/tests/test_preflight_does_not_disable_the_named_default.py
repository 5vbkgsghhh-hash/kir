"""ВКЛЮЧЕНИЕ `KUKAI_IR_OPEN_MODEL_PREFLIGHT` МОЛЧА ОТКЛЮЧАЕТ НАЗВАННОЕ УМОЛЧАНИЕ.

Найдено офлайн 11.08.2026, на ЖИВОМ пути, без Revit. Развилка стоит в
`serving._handle_revit_ir_inner`:

    if not _open_model_preflight_enabled():
        snapshot = cand                      # СЫРОЙ словарь моста
    else:
        ...
        snapshot = open_model.to_ground_snapshot()   # через типизированный профиль

Счётчик `instances`, на котором стоит `ground._most_used`, эмиссия кладёт в
СЫРУЮ строку (`open_model.py`, внутри `if ((__e as FamilySymbol) != null)`).
Типизированная строка `ModelCatalogEntry` поля для него НЕ ИМЕЕТ, и
`to_ground_row()` собирает ответ из явного списка ключей, где его тоже нет.
Значит круг «сырое -> профиль -> снапшот» счётчик ТЕРЯЕТ.

ЧТО ЭТО ЗНАЧИТ НА ПРАКТИКЕ. `_most_used` возвращает `None`, если хотя бы одна
строка пула без счётчика — намеренно, «старый мост обязан сохранить прежнее
поведение побайтово». Поэтому при включённом префлайте КАЖДАЯ неоднозначность
перестаёт получать названное умолчание и отказывает `KIR-G102`. Флаг, чья цель
— сделать заземление СТРОЖЕ, побочно выключает поставленную способность, и об
этом не сообщается нигде.

Это тот же класс, что и весь список инженерных ловушек: величина ОБЪЯВЛЕНА в
одном месте (эмиссия кладёт `instances`) и ПРОЧИТАНА в другом (типизированный
контракт, у которого такого поля нет), и совпасть их ничто не заставляет.
Особенность в том, что ловушка ВЗВЕДЕНА ЗАРАНЕЕ: префлайт выключен по
умолчанию, его собираются включать, и в день включения `most_used` замолчит.

ЧЕГО ЭТОТ ТЕСТ НЕ УТВЕРЖДАЕТ: он НЕ говорит, что счётчик обязан ехать в
`binding_digest` — тот подписывает ИДЕНТИЧНОСТЬ строки, а число размещений это
её содержимое (ровно та же оговорка стоит у поля `section`). Куда именно класть
счётчик — решение, а не следствие; тест лишь фиксирует, что СЕЙЧАС он теряется.
"""
from __future__ import annotations

import unittest

from kukai.ir import ground
from kukai.ir.open_model import OpenModelProfile


def _raw_snapshot_with_counters() -> dict:
    """Сырой словарь ровно той формы, что присылает мост: со счётчиками."""
    return {
        "door_symbols": [
            {"id": 101, "name": "ДГ 21-8 П", "unique_id": "u-101",
             "class_name": "FamilySymbol", "category": "OST_Doors",
             "family_name": "Дверь", "type_name": "ДГ 21-8 П",
             "instances": 500},
            {"id": 102, "name": "ДГ 21-9 Л", "unique_id": "u-102",
             "class_name": "FamilySymbol", "category": "OST_Doors",
             "family_name": "Дверь", "type_name": "ДГ 21-9 Л",
             "instances": 272},
        ],
    }


class TheCounterMustSurviveTheTypedRoundTrip(unittest.TestCase):

    def test_most_used_fires_on_the_raw_bridge_snapshot(self) -> None:
        """Контроль: на сыром словаре правило работает, 500 против 272 — это
        1.8x, выше `MOST_USED_MIN_RATIO`. Без этого теста следующий был бы
        зелен и у правила, сломанного вообще."""
        raw = _raw_snapshot_with_counters()
        chosen = ground._most_used(raw["door_symbols"], "door_symbols", None)
        self.assertIsNotNone(chosen, "правило не сработало на сырых данных")
        self.assertEqual(chosen["id"], 101)
        self.assertEqual(chosen["via"], "most_used")
        self.assertEqual(chosen["rule_detail"]["instances"], 500)
        self.assertEqual(chosen["rule_detail"]["runner_up"], 272)

    def test_the_typed_profile_round_trip_drops_the_counter(self) -> None:
        """РЕФУТАЦИЯ. Тот же снапшот через типизированный профиль — и правило
        замолкает, потому что счётчика в строке больше нет."""
        raw = _raw_snapshot_with_counters()
        profile = OpenModelProfile.from_ground_snapshot(raw)
        through = profile.to_ground_snapshot()

        rows = through["door_symbols"]
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(all("instances" not in row for row in rows),
                        f"счётчик неожиданно уцелел: {rows}")

        chosen = ground._most_used(rows, "door_symbols", None)
        self.assertIsNone(
            chosen,
            "правило сработало — значит счётчик доехал, и этот тест пора "
            "снимать вместе с находкой")

    def test_the_entry_contract_has_no_field_for_it(self) -> None:
        """Причина, а не симптом: у типизированной строки нет такого поля.

        Красный здесь = поле завели, и тогда обе проверки выше обязаны
        покраснеть вместе с ним — это и есть сигнал, что ловушка снята.
        """
        import dataclasses
        from kukai.ir.open_model import ModelCatalogEntry

        fields = {f.name for f in dataclasses.fields(ModelCatalogEntry)}
        self.assertNotIn("instances", fields)
        self.assertNotIn("instance_count", fields)


if __name__ == "__main__":
    unittest.main()
