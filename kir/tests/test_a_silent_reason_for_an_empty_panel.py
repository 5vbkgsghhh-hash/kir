"""The "frame is not drawn" branch is obligated to NAME ITSELF, not stay silent.

🔴 BOUGHT LIVE on 2026-09-02. The owner, in KIR mode, said: "nothing built in
kir and nothing is visible." The autopsy showed every link was sound:

    program in the journal    two records, doc_key='Проект1', seq 0 and 1
    device                    matched the one attached to the WS character for character
    the stream itself         on these SAME programs delivers 2 frames,
                              `transferable: true`, program_ops 18

So the empty window was explained by exactly one of two `publish` branches: "no
panel" or "no event loop." **Both stayed silent.** The `skipped_no_panel`
counter lives in process memory, `stats()` has no route out for it, the
showroom does not write it to disk — from the outside, "the frame was sent"
and "the frame was never drawn" are indistinguishable, and the diagnosis cost
a dedicated measurement where one line would have been enough.

The "send to Revit" button hangs off the same frame (the panel draws it from
`transferable` + `program_digest`), so an "empty window" and a "missing
button" share ONE cause, and this line is obligated to name it.

INFO level is deliberate: a refusal hidden in DEBUG is the named form of this
tree's own defect, and on that same day it cost the service four unreadable
modules.
"""
from __future__ import annotations

import logging
import unittest

from kir.live import plan_stream as ps

ПРОГРАММА = {"ops": [{"op": "create_wall", "id": "w1",
                      "level": {"by": "name", "value": "Уровень 1"},
                      "type": {"by": "name", "value": "Типовой - 200мм"},
                      "p0_mm": [0, 0], "p1_mm": [6000, 0],
                      "height_mm": 2600}]}


class ПустаяПанельНазываетПричину(unittest.TestCase):

    def setUp(self) -> None:
        ps.reset()
        self.addCleanup(ps.reset)

    def _опубликовать(self, *, подключать: bool):
        if подключать:
            ps.attach("устройство-сторожа")
        with self.assertLogs("kir.live.plan_stream", level="INFO") as поймано:
            logging.getLogger("kir.live.plan_stream").info("якорь")
            ps.publish(device_id="устройство-сторожа", doc_key="Документ",
                       program=ПРОГРАММА, source="сторож")
        return [s for s in поймано.output if "якорь" not in s]

    def test_без_панели_причина_НАЗВАНА_и_несёт_адрес(self) -> None:
        строки = self._опубликовать(подключать=False)
        self.assertTrue(строки, "ветка «панели нет» промолчала — "
                                "снаружи её не отличить от отправленного кадра")
        текст = "\n".join(строки)
        self.assertIn("устройство-сторожа", текст, "причина без адреса не лечится")
        self.assertIn("Документ", текст, "документ обязан быть назван: "
                                         "у одного устройства их два")

    def test_с_панелью_лишнего_НЕ_говорит(self) -> None:
        """The control in the other direction: otherwise the line would always fire and mean
        nothing — the shape of "an instrument that cannot say NO"."""
        строки = self._опубликовать(подключать=True)
        немые = [s for s in строки if "панель НЕ подключена" in s]
        self.assertEqual([], немые,
                         "при подключённой панели ветка не срабатывает, "
                         "а строка всё равно печатается — сигнал обесценен")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
