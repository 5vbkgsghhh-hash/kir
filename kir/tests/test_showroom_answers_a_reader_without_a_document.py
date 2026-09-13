"""The showroom answers a reader who does not know the document — and STAYS SILENT when there are two such readers.

🔴 BOUGHT BY A LIVE REFUSAL FROM THE OWNER ON 02.09.2026. The «перенести в Revit» button
answered «такой программы сервер не показывал: подписи нет в витрине», having shown
this very same program one second earlier.

The showroom's key is `(устройство, документ)`. The writer has been placing the frame under the ACTUAL
document since 30.08 (`plan_stream.publish(doc_key=…)`, commit c9c17c5), while
the transfer handler assembled the key BY HAND, bypassing the single author
`journal.key_for`, and always with an empty document:

    chat_ws.py::_handle_kir_transfer     key = (device_id or "", "")

Before 30.08 both sides lived on the empty value and matched. After the writer was fixed,
the transfer started missing BY CONSTRUCTION — that is, it was IMPOSSIBLE to build anything
from KIR mode at all, and the refusal still sounded truthful.

WHAT IS PINNED HERE — FOUR ASSERTIONS, AND TWO OF THEM ARE NEGATIVE:
an empty document reads as a QUESTION and gets an answer when there is exactly one; two
candidates mean a REFUSAL, not a choice made on the human's behalf; a named document that does not
match is a real miss with no search involved at all; a foreign device is never visible.
"""
from __future__ import annotations

import unittest

from kir.live import showroom


ПРОГРАММА = [[{"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
               "p1_mm": [6000, 0], "height_mm": 2600}]]


class ВитринаОтвечаетБезДокумента(unittest.TestCase):

    def setUp(self) -> None:
        showroom.forget()
        self.addCleanup(showroom.forget)

    def _показать(self, устройство: str, документ: str):
        return showroom.show((устройство, документ), level="Уровень 1",
                             programs=ПРОГРАММА)

    def test_один_кандидат_находится_по_устройству(self) -> None:
        показано = self._показать("dev-1", "Проект1")
        self.assertIsNotNone(показано)
        найдено = showroom.recall(("dev-1", ""), показано.digest)
        self.assertIsNotNone(
            найдено, "читатель без документа обязан получить ЕДИНСТВЕННЫЙ кадр")
        self.assertEqual(найдено.digest, показано.digest)

    def test_два_кандидата_дают_ОТКАЗ_а_не_выбор(self) -> None:
        a = self._показать("dev-1", "Проект1")
        b = self._показать("dev-1", "Проект2")
        self.assertEqual(a.digest, b.digest, "предпосылка: подпись одна")
        self.assertIsNone(
            showroom.recall(("dev-1", ""), a.digest),
            "строить не в тот документ дороже, чем не строить")

    def test_названный_и_не_совпавший_документ_это_промах(self) -> None:
        показано = self._показать("dev-1", "Проект1")
        self.assertIsNone(
            showroom.recall(("dev-1", "Проект9"), показано.digest),
            "поиск включается ТОЛЬКО когда документ не назван")

    def test_чужое_устройство_не_видно(self) -> None:
        показано = self._показать("dev-1", "Проект1")
        self.assertIsNone(showroom.recall(("dev-2", ""), показано.digest))

    def test_знаменатель_не_пуст(self) -> None:
        """Otherwise green would mean "the showroom is empty", not "the search works"."""
        показано = self._показать("dev-1", "Проект1")
        self.assertIsNotNone(showroom.recall(("dev-1", "Проект1"), показано.digest))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
