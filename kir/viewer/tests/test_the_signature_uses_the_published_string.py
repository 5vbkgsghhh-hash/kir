"""WHAT IS SIGNED IS WHAT WAS PUBLISHED, NOT WHAT IT WAS MADE FROM (F-009).

🔴 HOW COSTLY THIS WAS. `_level_id(None)` publishes `"?"` into the row
table, and the panel signs EXACTLY THAT (`scene-data.js`:
`H.levels[d.level[i]]`). The server, in the same record, was signing
`str(level or "")` — an EMPTY string. EVERY `create_directshape` has no
level by construction, so the signatures diverged for ANY scene with a
mesh, and the "Send to Revit" button refused with
`Refusal.SHOWN_MISMATCH`. The entire FOURTH KIND of the form was dead.

MEASURED END-TO-END, WITH THE REAL CLIENT MODULE IN `node` (29.08.2026):

    BEFORE x whole (base): panel bc4fab00… != server e5fdaebd…   RC=1
    AFTER  ok whole (base): bc4fab00…                              RC=0

🔴 What matters is not "it went green" but WHAT EXACTLY MOVED: the
PANEL's signatures are THE SAME in both runs (`bc4fab00…`,
`7f88599a…`), only the server shifted. That is, the client was right,
and it was our side that needed fixing — exactly what the package
claimed, in disagreement with the journal.

🔴 WHAT THIS FILE CANNOT DO, AND WHY. Cross-checking against the REAL
client lives in `verify_shown.mjs` and requires `node` and a KUKAI
file. What is held here is the python half of the invariant: the signed
string must be THE SAME ONE that is published in the table. Two places
computing it differently is exactly F-009, and it is exactly this pair
that is checked, not "the signatures match" (the latter goes green on
any scene without meshes, and those are the majority in the fixtures).
"""
from __future__ import annotations

import unittest

from kir.viewer.codec import SceneBuilder

_ТРЕУГОЛЬНИК = ([[0, 0, 0], [1000, 0, 0], [0, 1000, 0]], [[0, 1, 2]])


def _запись(level):
    b = SceneBuilder(origin_mm=(0.0, 0.0, 0.0))
    kind, slot = b.add_mesh(*_ТРЕУГОЛЬНИК)
    b.add_element(element_id="D1", category="OST_GenericModel", level=level,
                  trust=1, fidelity=1, label="create_directshape", kind=kind,
                  slot=slot, axes=0, authority=0, existence=0, flags=0)
    a = b.records[0].find(b"OST_GenericModel") + 17
    z = b.records[0].find(b"create_directshape") - 1
    return b, b.records[0][a:z].decode("utf-8")


class ПодписьБерётОпубликованнуюСтроку(unittest.TestCase):

    def test_у_элемента_БЕЗ_уровня_подпись_равна_строке_таблицы(self):
        """The main case: a mesh. It has no level by construction."""
        b, подписано = _запись(None)
        опубликовано = list(b._levels)[0]
        self.assertEqual(опубликовано, "?", "таблица перестала называть незнание")
        self.assertEqual(подписано, опубликовано,
                         "сервер подписал не то, что показал панели: "
                         "перенос ЛЮБОЙ сетки откажет SHOWN_MISMATCH")

    def test_у_элемента_С_уровнем_ничего_не_изменилось(self):
        """THE SECOND HALF: an ADDITIVE fix.

        Checked against HEAD byte-for-byte when the fix was made; what
        is held here is a property that will survive the file being
        moved.
        """
        b, подписано = _запись("Уровень 1")
        self.assertEqual(подписано, "Уровень 1")
        self.assertEqual(подписано, list(b._levels)[0])

    def test_пустое_имя_уровня_не_путается_с_отсутствием(self):
        """The third case, and it is NOT degenerate: `""` is a
        legitimate level name, and it must remain an empty string, not
        become `"?"`. Otherwise the fix would cure one form of
        not-knowing by introducing another."""
        b, подписано = _запись("")
        self.assertEqual(list(b._levels)[0], "")
        self.assertEqual(подписано, "")
        _b2, без_уровня = _запись(None)
        self.assertNotEqual(подписано, без_уровня,
                            "«уровень назван пустым» и «уровня нет» слились "
                            "в один факт")

    def test_источник_строки_ОДИН(self):
        """A direct check of what was fixed: the row and the signature
        must take the string from ONE owner. A local copy of `"?"` next
        to the signature would drift on the very first edit of
        `_level_id` — and it drifted exactly that way."""
        for имя in (None, "", "Уровень 1", "?"):
            with self.subTest(уровень=имя):
                b = SceneBuilder(origin_mm=(0.0, 0.0, 0.0))
                номер = b._level_id(имя)
                ключ = [k for k, v in b._levels.items() if v == номер][0]
                self.assertEqual(SceneBuilder._level_key(имя), ключ)


if __name__ == "__main__":
    unittest.main()
