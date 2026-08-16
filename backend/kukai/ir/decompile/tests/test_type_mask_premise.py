"""КОНТРОЛЬ ПРЕМИССЫ «маска первого экземпляра = маска типа».

🔴 ЭТОТ ФАЙЛ СУЩЕСТВУЕТ, ЧТОБЫ ПРЕМИССУ НЕЛЬЗЯ БЫЛО ПРИНЯТЬ ЗАНОВО.

Она стояла в `axes_census.BLIND_SPOTS` как «не доказано, а принято», и на ней
держится множитель ×4.4…×20.9 протокола «сначала тип». Замер 15.08.2026 на
четырёх зданиях её ОПРОВЕРГ, причём отказ идёт в опасную сторону: у экземпляра
бывает ключ, которого не было у первого, и живой протокол его НЕ СПРОСИТ —
значение уедет из L0 МОЛЧА.

    sob62_r23_v5      1 тип из 71,    7 ключей,   0.46 % элементов
    k2_ar_rd_v8       6 типов из 486, 2908 ключей, 1.27 % элементов

МЕХАНИЗМ, а не случайность: `WALL_HEIGHT_TYPE` (привязка верха стены) есть у 7
экземпляров одного типа и отсутствует у 5, потому что верх привязан к уровню не
у всех. Существование параметра — свойство СОСТОЯНИЯ ЭКЗЕМПЛЯРА.

ЧТО ИМЕННО ДЕРЖАТ ЭТИ ТЕСТЫ. Не число расхождений на корпусе — корпус
машинно-локальный, и тест, требующий его, на чужой машине скажет «чисто» там,
где он просто ничего не видел. Держат ДВЕ вещи, обе проверяемые где угодно:

 1. перепись СЧИТАЕТ расхождение и отдаёт его рядом с множителем;
 2. на входе с расхождением она это расхождение НАХОДИТ, а на входе без —
    не выдумывает. Контроль в обе стороны: тест, который краснеет только в
    одну, не отличает исправный прибор от всегда-кричащего.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kukai.ir.decompile import axes_census


def _l0(path: pathlib.Path, elements: list[dict]) -> None:
    """Минимальный L0: только записи элементов — перепись большего не требует."""
    with path.open("w", encoding="utf-8") as handle:
        for element in elements:
            handle.write(json.dumps({"record": "element", "element": element}) + "\n")


def _element(eid: str, type_id: str, params: dict) -> dict:
    return {"element_id": eid, "type_id": type_id, "category": "OST_Walls",
            "type_name": "T", "params": params}


class ПерепaverСчитаетЦенуПремиссы(unittest.TestCase):
    """Расхождение обязано доехать до строки отчёта, а не остаться в голове."""

    def _census(self, elements: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            _l0(directory / "L0.jsonl", elements)
            row = axes_census.census(directory, budget=38)
        assert row is not None, "перепись отказалась читать собранный L0"
        return row

    def test_расхождение_найдено_когда_оно_есть(self):
        """Второй экземпляр несёт ключ, которого не было у первого.

        Это ровно случай `WALL_HEIGHT_TYPE`: живой протокол его не спросит.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 1, "B": 2, "WALL_HEIGHT_TYPE": 9}),
        ])
        self.assertEqual(row["mask_diverged_types"], 1)
        self.assertEqual(row["mask_lost_keys"], 1)
        self.assertEqual(row["mask_lost_instances"], 1)

    def test_расхождения_НЕТ_когда_маски_совпадают(self):
        """КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ.

        Без него предыдущий тест не отличает прибор, который СЧИТАЕТ, от
        прибора, который всегда кричит. Ровно та форма, которой этот файл
        посвящён: зелёное без акта различения.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 7, "B": 8}),
        ])
        self.assertEqual(row["mask_diverged_types"], 0)
        self.assertEqual(row["mask_lost_keys"], 0)

    def test_лишний_ключ_у_первого_НЕ_считается_потерей(self):
        """У первого ключ есть, у второго нет — это лишний зонд, а не потеря.

        Разница стоит разного: перерасход виден в счёте, потеря не видна
        НИКОМУ. Смешать их значило бы потерять единственное различие, ради
        которого этот счётчик заведён.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 1}),
        ])
        self.assertEqual(row["mask_lost_keys"], 0,
                         "избыток у первого посчитан как потеря")

    def test_потеря_копится_по_всем_экземплярам(self):
        row = self._census([
            _element("1", "T1", {"A": 1}),
            _element("2", "T1", {"A": 1, "X": 2}),
            _element("3", "T1", {"A": 1, "Y": 3}),
        ])
        self.assertEqual(row["mask_lost_keys"], 2)
        self.assertEqual(row["mask_lost_instances"], 2)
        self.assertEqual(row["mask_diverged_types"], 1)


class ГраницаНазываетОпровержение(unittest.TestCase):
    """Прибор обязан НЕСТИ опровержение, а не помнить его.

    Число ×20.9 переживёт любую беседу; текст рядом с ним — единственное, что
    не даст прочесть его как план работ.
    """

    def test_границы_называют_премиссу_опровергнутой(self):
        text = axes_census.BLIND_SPOTS
        self.assertIn("ОПРОВЕРГНУТА", text)
        self.assertIn("WALL_HEIGHT_TYPE", text,
                      "механизм не назван — останется догадкой")
        self.assertIn("ВЕРХНЯЯ ГРАНИЦА", text,
                      "не сказано, чем стали два множителя после опровержения")

    def test_границы_называют_и_вторую_половину(self):
        """Мёртвая пара — факт о ПРОЕКТЕ, а не о схеме Ревита.

        Замер по четырём зданиям: живых пар в объединении 19, общих всем 4.
        Статический список, снятый с одного проекта, на другом выбросит живые.
        """
        self.assertIn("ФАКТ О ПРОЕКТЕ", axes_census.BLIND_SPOTS)


if __name__ == "__main__":
    unittest.main()
