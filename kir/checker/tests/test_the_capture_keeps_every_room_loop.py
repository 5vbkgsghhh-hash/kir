"""THE CAPTURE MUST BRING BACK ALL OF A ROOM'S LOOPS, NOT JUST THE OUTER ONE (S-01).

🔴 WHERE IT WAS LOST. `extractor.cs` took `segs[0]` — one loop out of everything
`GetBoundarySegments` returned. A shaft, an atrium, and a cut for a stair vanished RIGHT IN THE CAPTURE,
before Python. `F-041` fixed the SECOND producer of the same model (`design_check`,
the PARSE path from L0); this file guards the FIRST.

🔴 WHY HAB060 DID NOT CATCH THIS, EVEN THOUGH IT SHOULD HAVE. Its mismatch threshold
is RELATIVE, and the shaft's contribution fits inside it. Measured 29.08.2026:

    a 10x10 m room with a 2x2 m shaft, Revit declared 96 m²
    BEFORE  derived 100.0 m²  ->  mismatch 4.2 % < 10 %  ->  HAB060 STAYS SILENT
    AFTER   derived  96.0 m²

That is, the loss was BELOW the resolving power of the instrument that was supposed to
catch it. A threshold guard does not substitute for an honest capture.

🔴 WHAT CANNOT EXIST HERE. A behavioural guard on the C# half does not exist in this tree
and cannot exist: it needs a live Revit. What CAN be checked is exactly one thing — that the
emission's BODY walks ALL the loops and hands over the field. This is a source-text guard, and without it
`segs[0]` will come back on the very next rewrite, silently again.
"""
from __future__ import annotations

import pathlib
import unittest

from kir.checker.derive import derive
from kir.checker.extractor import normalize
from kir.checker.spatial_model import Room, SpatialModel
from kir.checker.thresholds import Thresholds

ВНЕШНИЙ = [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]
ШАХТА = [[4000, 4000], [6000, 4000], [6000, 6000], [4000, 6000]]
ИСТИНА = 96.0

_CS = pathlib.Path(__file__).resolve().parents[1] / "extractor.cs"


def _сырое(*, с_дырой: bool) -> dict:
    комната = {"id": "r1", "name": "Спальня", "level_id": "L0",
               "area_m2": ИСТИНА if с_дырой else 100.0, "height_mm": 2700.0,
               "boundary": ВНЕШНИЙ}
    if с_дырой:
        комната["boundary_holes"] = [ШАХТА]
    return {"building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": [комната],
            "doors": [], "windows": [], "stairs": [], "walls": []}


class СъёмНеТеряетКонтуров(unittest.TestCase):

    def test_контракт_несёт_поле_дыр(self):
        """🔴 AN ORDER GUARD, NOT DECORATION. If the `Room.boundary_holes` field
        disappears (say, F-041 gets reverted), pydantic will drop the payload key
        SILENTLY — the capture would stay honest, the model would again be without the shaft, and both
        ends would look established. This is exactly the kind of failure the whole
        marathon is for: let it turn red here, and by name.
        """
        self.assertIn("boundary_holes", Room.model_fields,
                      "контракт потерял поле дыр — ключ съёма будет "
                      "проглочен молча")

    def test_normalize_доносит_дыры_до_модели(self):
        n = normalize(_сырое(с_дырой=True))
        self.assertEqual(len(n["rooms"][0].get("boundary_holes") or []), 1,
                         "нормализация потеряла дыру между съёмом и моделью")
        m = SpatialModel.model_validate(n)
        self.assertEqual(len(m.rooms[0].boundary_holes), 1)

    def test_выведенная_площадь_сходится_с_заявленной(self):
        m = SpatialModel.model_validate(normalize(_сырое(с_дырой=True)))
        _dm, rep = derive(m, Thresholds())
        d = rep.rooms["r1"]
        self.assertAlmostEqual(d.derived_area_m2, ИСТИНА, places=3)
        self.assertAlmostEqual(d.derived_area_m2, d.declared_area_m2, places=3,
                               msg="выведенное разошлось с тем, что вернул "
                                   "Revit: контур привезён не весь")

    def test_комната_без_шахты_прежняя(self):
        """THE SECOND HALF: an additive fix. Without this case it is
        indistinguishable from "always subtract"."""
        m = SpatialModel.model_validate(normalize(_сырое(с_дырой=False)))
        self.assertEqual(m.rooms[0].boundary_holes, [])
        _dm, rep = derive(m, Thresholds())
        self.assertAlmostEqual(rep.rooms["r1"].derived_area_m2, 100.0,
                               places=3)

    @staticmethod
    def _код_без_комментариев() -> str:
        """🔴 COMMENTS ARE STRIPPED OUT: THE DEPENDENCY LIVES IN CODE.

        The first edition of this guard turned red on MY OWN comment,
        which QUOTES the old form `foreach (var s in segs[0])` while explaining
        what no longer exists. The instrument matched PROSE instead of code — the same kind of bug as
        "the probe caught the label, not the branch". The technique is borrowed from a neighbour
        (`viewer/tests/test_delta.py`), not invented here.
        """
        import re
        текст = _CS.read_text(encoding="utf-8")
        текст = re.sub(r"/\*.*?\*/", "", текст, flags=re.S)
        return re.sub(r"(?m)//.*$", "", текст)

    def test_тело_съёма_обходит_ВСЕ_контуры(self):
        """A SOURCE-TEXT guard on the C# half — the only kind possible here."""
        текст = self._код_без_комментариев()
        self.assertIn("boundary_holes", текст,
                      "съём не отдаёт поле дыр — питон получит только оболочку")
        self.assertNotIn("foreach (var s in segs[0])", текст,
                         "тело снова читает ТОЛЬКО первый контур: шахта "
                         "теряется в съёме, и ни один питоновский сторож "
                         "этого не увидит")
        self.assertIn("for (int li = 0; li < segs.Count; li++)", текст,
                      "обхода всех контуров в теле нет")

    def test_исходный_сторож_умеет_краснеть(self):
        """THE SECOND HALF OF THE SOURCE-TEXT GUARD (rule 2).

        A text-based check is green even on an empty file unless it is checked with a
        reverse substitution. Here it is run against a KNOWN-OLD body, and it
        must reject it — otherwise the guard is not guarding, only present.
        """
        старое = ('var bnd = new List<object>();\n'
                  'var segs = sp.GetBoundarySegments(bopts);\n'
                  'if (segs != null && segs.Count > 0) {\n'
                  '    foreach (var s in segs[0]) { }\n}\n')
        self.assertNotIn("boundary_holes", старое)
        self.assertIn("foreach (var s in segs[0])", старое)
        # AND THE SECOND HALF OF THE STRIPPING ITSELF: a comment quoting the old form
        # must be INVISIBLE to the guard, otherwise it turns red on the explanation.
        self.assertIn("segs[0]", _CS.read_text(encoding="utf-8"),
                      "цитата старой формы исчезла из комментария — разбор "
                      "потерян, следующий купит его заново")
        self.assertNotIn("foreach (var s in segs[0])",
                         self._код_без_комментариев())


if __name__ == "__main__":
    unittest.main()
