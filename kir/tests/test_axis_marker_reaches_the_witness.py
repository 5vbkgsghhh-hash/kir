"""AN AXIS MARKER WITH A QUALIFIER WAS MARKING THE WRONG AXIS RED.

🔴 MEASUREMENT 2026-08-22. `_axes_from_violations` looked for the EXACT
substring `(geometry)`. Messages living in `authoring.py` have a qualifier
inside the same parentheses — a census of every parenthetical form in the module:

    (geometry)                                102
    (semantic)                                 59
    (topology)                                 55
    (geometry, tolerance 0.1deg)                4
    (semantic, re-read)                         2
    (semantic, VIEW-BINDING LAW…)               2
    (semantic_ok)                               1
    (geometry, Revit подгоняет под контент)     1

Five of them are GEOMETRY with a qualifier, and not one matched. The
violation drifted into semantics: an arc wall with the wrong center and a
family rotated the wrong way reported `geometry_ok: True`, and the wrong
axis turned red.

The cost in numbers, from a decompile of MNVNK: `create_wall` (arc) 7,845 +
`place_family` (rotation) 5,340 + `create_column` (rotation) 2 = **13,187
operations out of 19,041, 69% of a real building**.

This is the worst kind of mistake a witness can make: not "stayed silent,"
but "said green about the very axis that is broken."
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from kir.serving import _axes_from_violations, _axis_marked


class ПометкаСУточнениемПопадаетВСВОЮОсь(unittest.TestCase):

    def test_геометрия_с_допуском_краснит_ГЕОМЕТРИЮ(self):
        axes = _axes_from_violations(
            ["rotation mismatch (geometry, tolerance 0.1deg)"])
        self.assertFalse(axes["geometry_ok"], "сломана геометрия")
        self.assertTrue(axes["semantic_ok"],
                        "семантика тут ни при чём — прежде краснела она")
        self.assertTrue(axes["topology_ok"])

    def test_геометрия_с_прозой_в_скобках_тоже(self):
        axes = _axes_from_violations(
            ["bbox mismatch (geometry, Revit подгоняет под контент)"])
        self.assertFalse(axes["geometry_ok"])
        self.assertTrue(axes["semantic_ok"])

    def test_простая_пометка_работает_как_прежде(self):
        for marker, broken in (("(geometry)", "geometry_ok"),
                               ("(topology)", "topology_ok")):
            with self.subTest(marker=marker):
                axes = _axes_from_violations([f"что-то не так {marker}"])
                self.assertFalse(axes[broken])
                self.assertTrue(axes["semantic_ok"])

    def test_семантика_с_уточнением_остаётся_семантикой(self):
        for item in ("value mismatch (semantic, re-read)",
                     "target не виден (semantic, VIEW-BINDING LAW)",
                     "флаг (semantic_ok)"):
            with self.subTest(item=item):
                axes = _axes_from_violations([item])
                self.assertFalse(axes["semantic_ok"])
                self.assertTrue(axes["geometry_ok"])
                self.assertTrue(axes["topology_ok"])

    def test_непомеченное_по_прежнему_семантика(self):
        axes = _axes_from_violations(["просто нарушение без пометки"])
        self.assertFalse(axes["semantic_ok"])
        self.assertTrue(axes["geometry_ok"])

    def test_совпадение_по_ПРЕФИКСУ_было_бы_шире_правды(self):
        """`(geometryX)` is not a marker. The axis name is obligated to be followed by `)` or `,`."""
        self.assertFalse(_axis_marked("(geometryX)", "geometry"))
        self.assertFalse(_axis_marked("(geometrical)", "geometry"))
        self.assertTrue(_axis_marked("(geometry)", "geometry"))
        self.assertTrue(_axis_marked("(geometry, что угодно)", "geometry"))

    def test_несколько_осей_в_одном_прогоне_складываются(self):
        axes = _axes_from_violations([
            "a (geometry, tolerance 0.1deg)", "b (topology)", "c без пометки"])
        self.assertFalse(axes["geometry_ok"])
        self.assertFalse(axes["topology_ok"])
        self.assertFalse(axes["semantic_ok"])


class ВсеСКОБОЧНЫЕ_ФОРМЫ_ЭМИТТЕРА_РАЗБИРАЮТСЯ(unittest.TestCase):
    """🔴 THE RULE IS CHECKED AGAINST THE LIVE EMITTER, NOT AGAINST EXAMPLES.

    Otherwise tomorrow's sixth marker form will drift into the wrong axis
    just as quietly as these five did — and the guard will stay green on
    its own made-up examples.
    """

    #: 🔴 THE WALK GOES OVER STRING LITERALS, NOT OVER THE WHOLE FILE, and
    #: this is not fastidiousness. The first edition swept the whole text and
    #: caught the form `(geometry ±tol AND topology: …)` from the module's
    #: PROSE (`authoring.py:14`, the description of the in-transaction gate).
    #: A witness message is a string literal; a paragraph of documentation
    #: will never become one, and demanding parseability of it would mean
    #: measuring the wrong subject.
    _LITERAL = re.compile(r'"([^"\n]*)"')

    def test_ни_одна_форма_не_остаётся_неразобранной(self):
        text = (Path(__file__).resolve().parents[1] / "authoring.py"
                ).read_text(encoding="utf-8")
        forms: set[str] = set()
        for literal in self._LITERAL.findall(text):
            forms.update(re.findall(
                r"\((?:geometry|topology|semantic)[^)]*\)", literal))
        self.assertGreaterEqual(
            len(forms), 8,
            "перепись подозрительно мала — прибор смотрит не туда")
        for form in sorted(forms):
            with self.subTest(форма=form):
                axes = _axes_from_violations([f"нарушение {form}"])
                broken = [k for k, v in axes.items() if not v]
                self.assertEqual(
                    len(broken), 1,
                    f"форма {form} обязана краснить РОВНО ОДНУ ось, "
                    f"а покраснели {broken}")
                expected = ("geometry_ok" if form.startswith("(geometry")
                            else "topology_ok" if form.startswith("(topology")
                            else "semantic_ok")
                self.assertEqual(broken[0], expected,
                                 f"{form} уехала в {broken[0]}")


if __name__ == "__main__":
    unittest.main()
