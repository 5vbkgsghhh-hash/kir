"""SPLITTING IS A MAPPING OF OPS, NOT A LIST OF NAMES.

🔴 WHY (24.08.2026). An audit finding, REPRODUCED BY A RUN. The measurement,
verbatim, before the fix:

    ops    = [create_level id=a "Этаж 1", create_level id=a "Этаж 2"]
    phases = [{0: [a]}, {1: [a]}]
    ->  two chunks, BOTH "Этаж 2".
        "Этаж 1" is built by NOBODY, "Этаж 2" is built TWICE —
        each in its own transaction, with its own checkpoint,
        and NOT A SINGLE diagnostic.

A silently-wrong outcome is exactly what this whole package is built
against, and it stood in precisely the function whose docstring declares
splitting to be its ONE AND ONLY law.

**Why the guard could not turn red.** It compared LISTS OF NAMES
(`flat != written`) — reading the APPEARANCE, not the SUBJECT. For two ops
with one id, both sides equal `['a','a']`, and `by_id` had already consumed
the first op by dict assignment by then.

**Why `plan_program` over a chunk did not save it.** Within each chunk the
id is already unique: the duplicate disappears BEFORE the law about it gets
a chance to ask. The `KIR-P006` law existed and worked — on the path
WITHOUT phases. The second path reached the same data around it.
"""
from __future__ import annotations

import unittest

from kir.compiler import split_phases
from kir.diag import KirRefusal

ДВА_ОПА_ОДИН_ID = {
    "ir_version": "1.0",
    "ops": [{"op": "create_level", "id": "a", "name": "Этаж 1", "elev_mm": 0},
            {"op": "create_level", "id": "a", "name": "Этаж 2",
             "elev_mm": 3000}],
    "phases": [{"index": 0, "name": "p0", "op_ids": ["a"]},
               {"index": 1, "name": "p1", "op_ids": ["a"]}],
}

ЧЕСТНЫЙ_ПЛАН = {
    "ir_version": "1.0",
    "ops": [{"op": "create_level", "id": "a", "name": "Этаж 1", "elev_mm": 0},
            {"op": "create_level", "id": "b", "name": "Этаж 2",
             "elev_mm": 3000}],
    "phases": [{"index": 0, "name": "p0", "op_ids": ["a"]},
               {"index": 1, "name": "p1", "op_ids": ["b"]}],
}


class ДубликатIdОТКАЗЫВАЕТ_АНеСЪЕДАЕТ(unittest.TestCase):

    def test_два_опа_с_одним_id_дают_ОТКАЗ(self):
        """🔴 RED before the fix: two chunks came back with no diagnostics."""
        with self.assertRaises(KirRefusal) as поймано:
            split_phases(ДВА_ОПА_ОДИН_ID)
        текст = str(поймано.exception)
        self.assertIn("KIR-P006", текст)
        self.assertIn("дубликат id", текст)

    def test_отказ_называет_СЛЕДУЮЩИЙ_ХОД(self):
        """A trigger with no run is a trigger with no fix (the 23.08
        pattern)."""
        with self.assertRaises(KirRefusal) as поймано:
            split_phases(ДВА_ОПА_ОДИН_ID)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", str(поймано.exception))

    def test_код_ТОТ_ЖЕ_что_на_пути_без_фаз(self):
        """One law, one code. A new kind would make the author learn
        twice."""
        from kir.compiler import plan_program
        with self.assertRaises(KirRefusal) as без_фаз:
            plan_program({"ir_version": "1.0",
                          "ops": ДВА_ОПА_ОДИН_ID["ops"]})
        with self.assertRaises(KirRefusal) as с_фазами:
            split_phases(ДВА_ОПА_ОДИН_ID)
        self.assertIn("KIR-P006", str(без_фаз.exception))
        self.assertIn("KIR-P006", str(с_фазами.exception))


class КОНТРОЛЬ_ЧестныйПланПоПрежнемуРЕЖЕТСЯ(unittest.TestCase):

    def test_разные_id_дают_два_звена_с_РАЗНЫМИ_опами(self):
        """Without it, the refusal above could mean "we're cutting
        everything indiscriminately"."""
        links = split_phases(ЧЕСТНЫЙ_ПЛАН)
        self.assertEqual(len(links), 2)
        имена = [o["name"] for l in links for o in l.program["ops"]]
        self.assertEqual(имена, ["Этаж 1", "Этаж 2"])

    def test_каждый_оп_ровно_в_ОДНОМ_звене(self):
        """The actual split, formulated over OPS."""
        links = split_phases(ЧЕСТНЫЙ_ПЛАН)
        адреса = [id(o) for l in links for o in l.program["ops"]]
        self.assertEqual(len(адреса), len(set(адреса)))


if __name__ == "__main__":
    unittest.main()
