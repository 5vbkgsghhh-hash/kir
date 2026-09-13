"""A DIMENSION ON A NAMED FACE PRINTED UNCOMPILABLE C# WHILE `ok = True`.

🔴 WHY (25.08.2026, an audit finding, PROVEN BY ROSLYN on real assemblies).

The named-face branch in `create_dimension` bound only the `Reference` and
went to `continue`, skipping the declaration of `XYZ __gn_<s>_<i>` and the
population of `pt_vars`. The consequences are both GUARANTEED, not merely
probable:

```
1  `__dimDir_<s> = __gn_<s>_0;` reads a variable that does NOT EXIST.
   Roslyn 2026, verbatim: "CS0103 The name '__gn_D1_0' does not exist in
   the current context" — WHILE `out.ok = True`.
   That is, the compiler was saying "sound," and for the user this
   NEVER compiled.
2  `__proj_<s>` is built from `pt_vars`, so for a dimension with named
   faces it is EMPTY: `__expect_.Count == 0` against `__got_.Count == 1`,
   the value witness fails ALWAYS, and under `atomic` that is a rollback
   of the whole program.
```

**Why the offline compile gate did not catch this.** The gate exists and it
is real (`tools/compile_gate_offline.py`, Roslyn against six reference
assemblies), but it compiles DECOMPILED BUILDINGS — and a dimension on a
named face does not occur in those corpora. The gate is sound and answers
its own question; the question here was a different one.

**And the flag was turned on without a live check of the path it opens.**
The same kind as `KUKAI_IR_OPEN_MODEL_PREFLIGHT` two hours earlier: a flag
that gets turned on must be checked on the paths it opens, ON THE SAME DAY.
"""
from __future__ import annotations

import os
import re
import unittest

from kir import faceref
from kir.tests import test_faceref as T


class _ФлагВключён:
    def __enter__(self):
        self._было = os.environ.get(faceref.FACE_REF_FLAG)
        os.environ[faceref.FACE_REF_FLAG] = "1"
        return self

    def __exit__(self, *exc):
        if self._было is None:
            os.environ.pop(faceref.FACE_REF_FLAG, None)
        else:
            os.environ[faceref.FACE_REF_FLAG] = self._было
        return False


СМЕШАННЫЙ = T.TWO_WALLS + [T.dim([T.face(T.REF_W1, side="exterior"),
                                  T.REF_W2])]


class КАЖДАЯССЫЛКАОБЪЯВЛЯЕТСВОЮНОРМАЛЬ(unittest.TestCase):

    def _эмиссия(self, прог, ver="2026"):
        with _ФлагВключён():
            out = T.build(прог, ver=ver)
        self.assertTrue(out.ok, [str(d.message_ru)[:120] for d in out.diagnostics])
        return out.csharp

    def test_названные_грани_объявляют_КАЖДУЮ_нормаль(self):
        """🔴 RED before the fix: usages 1, declarations 0."""
        cs = self._эмиссия(T.NAMED)
        исп = set(re.findall(r"__gn_D1_\d+", cs))
        объяв = set(re.findall(r"XYZ\s+(__gn_D1_\d+)", cs))
        self.assertTrue(исп, "переменная нормали вообще не встречается")
        self.assertEqual(исп - объяв, set(),
                         f"использовано без объявления: {sorted(исп - объяв)}")

    def test_смешанный_случай_тоже(self):
        """[face, ordinary] gave TWO undeclared usages."""
        cs = self._эмиссия(СМЕШАННЫЙ)
        исп = set(re.findall(r"__gn_D1_\d+", cs))
        объяв = set(re.findall(r"XYZ\s+(__gn_D1_\d+)", cs))
        self.assertEqual(исп - объяв, set(), sorted(исп - объяв))

    def test_плоскость_берётся_из_СВЯЗАННОЙ_ссылки(self):
        """Searching for the face again would bring back "some" into a
        branch whose whole point is that the face is NAMED."""
        cs = self._эмиссия(T.NAMED)
        self.assertIn("GetGeometryObjectFromReference(__gref_D1_0)", cs)
        self.assertIn("PlanarFace", cs)

    def test_непланарная_грань_даёт_НАЗВАННЫЙ_отказ(self):
        """There may be no plane — and this must be stated, not passed over in silence."""
        cs = self._эмиссия(T.NAMED)
        self.assertIn("ПЛОСКОСТЬ", cs)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", cs)


class СВИДЕТЕЛЬЗНАЧЕНИЯМОЖЕТПРОЙТИ(unittest.TestCase):

    def test_проекции_пополняются_и_на_названных_гранях(self):
        """🔴 RED before the fix: between the declaration of `__proj_D1` and
        `Sort()` there was EMPTINESS, meaning `__expect_.Count == 0` always."""
        with _ФлагВключён():
            cs = T.build(T.NAMED, ver="2026").csharp
        м = re.search(r"var __proj_D1 = new List<double>\(\);(.*?)__proj_D1\.Sort\(\);",
                      cs, re.S)
        self.assertIsNotNone(м, "блок проекций не найден")
        self.assertTrue(м.group(1).strip(),
                        "проекции не пополняются — свидетель не может пройти")

    def test_КОНТРОЛЬ_обычные_ссылки_как_были(self):
        """A fix has no right to touch a branch that was working."""
        with _ФлагВключён():
            cs = T.build(T.TWO_WALLS + [T.dim([T.REF_W1, T.REF_W2])],
                         ver="2026").csharp
        self.assertIn("__dimGeom_D1(", cs)
        self.assertNotIn("PlanarFace __pf_D1", cs)


if __name__ == "__main__":
    unittest.main()
