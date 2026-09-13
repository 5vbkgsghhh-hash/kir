"""The sheet's footer does not run off the sheet, and truncation IS NAMED.

🔴 WHAT BOUGHT THIS FILE, MEASUREMENT OF 25.08.2026.

The footer holds four independent budget constants — 7 lines of omissions,
5 approximations, 4 anomalies, 4 kinds of blindness. They were counted
WITHOUT regard for how many lines the footer itself holds:
`SHEET_H - FOOTER_Y = 288` px at a step of 17 px — that is 16.9 lines.

A run over the grid of approximations × anomalies, lines PAST the sheet's
edge:

        an=0  1   2   3   4   5
  ap=4    0   0   0   0   0   1
  ap=5    0   0   0   0   1   2
  ap=6    0   0   0   1   2   3

And it was exactly the LAST lines of the right-hand column that ran off —
that is, the BLINDNESS list and the line «… и ещё N вид(а) слепоты», set up
precisely against silent truncation. Its own comment says: «список
слепоты, урезанный молча, читается как „слепота вот такая" — то есть врёт
ровно в ту сторону, в которую этому листу врать нельзя». The sheet was
lying exactly that way.

The module written to forbid silence was silent itself, and understated
its own blindness.

BOUNDARY. What is measured is the y of the TEXT, not the font's rendering:
a line that slightly overshoots the footer's rectangle but stays on the
sheet is still readable — that is a matter of appearance, not loss. What is
guarded here is loss.
"""

from __future__ import annotations

import re
import unittest

from kir import preview as P


def _подвал(приближений: int, аномалий: int) -> str:
    census = P.PreviewCensus(
        considered=10, drawn=7,
        omitted=(P.OmissionGroup(list(P.OmitReason)[0], "OST_Doors", 3),),
        approx=tuple(P.ApproxGroup(r, 2, ())
                     for r in list(P.ApproxReason)[:приближений]),
        anomalies=tuple(P.AnomalyGroup(r, 1, ())
                        for r in list(P.AnomalyReason)[:аномалий]),
    )
    план = P.FloorPlan(
        source=list(P._SOURCE_STYLE)[0], doc_name="d", level_name="L",
        level_elevation_mm=0.0, elements=(), census=census, datums=(),
        notes=(), frame_mm=None, outliers=())
    return P._footer(план, P._SOURCE_STYLE[план.source])


def _за_краем(svg: str) -> int:
    return sum(1 for y in re.findall(r'y="([\d.]+)"', svg)
               if float(y) > P.SHEET_H)


class ПодвалПомещаетсяНаЛист(unittest.TestCase):

    def test_ни_одна_строка_не_уезжает_за_лист(self):
        плохие = []
        for ap in range(len(P.ApproxReason) + 1):
            for an in range(len(P.AnomalyReason) + 1):
                за = _за_краем(_подвал(ap, an))
                if за:
                    плохие.append((ap, an, за))
        self.assertEqual(
            плохие, [],
            f"строки подвала за краем листа при {len(плохие)} сочетаниях: "
            f"{плохие[:4]}. Уезжает ХВОСТ правой колонки — список слепоты.")

    def test_урезание_называется(self):
        """Silent truncation is the very thing this sheet was written against."""
        svg = _подвал(len(P.ApproxReason), len(P.AnomalyReason))
        self.assertIn("не поместились на лист", svg,
                      "подвал урезан МОЛЧА: читатель решит, что это всё")

    def test_КОНТРОЛЬ_обычный_лист_не_урезается(self):
        """The instrument must not make noise where everything fit."""
        svg = _подвал(1, 1)
        self.assertNotIn("не поместились на лист", svg)
        self.assertEqual(_за_краем(svg), 0)

    def test_КОНТРОЛЬ_список_слепоты_доезжает_когда_место_есть(self):
        svg = _подвал(0, 0)
        self.assertIn("ЭТОТ ЭКРАН НЕ ПОКАЖЕТ", svg)
        self.assertIn("вид(а) слепоты", svg)


if __name__ == "__main__":
    unittest.main()
