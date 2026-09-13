"""THE LIST OF "WHOSE DEFAULT TYPE CARRIES THE DOCUMENT" LIVED IN THREE CARRIERS.

🔴 WHY (24.08.2026). An audit finding, REPRODUCED BY A RUN, not
taken on faith. Three places decided one question and each held a different
set:

    `_resolve_one`   (explicit `{"by":"default"}`)          KNEW 1: create_wall
    `_needs_pool`    (whether a snapshot is needed at all)  KNEW 4
    the resolve loop (whether to read the pool for a param) KNEW 8

Every addition (09.08 ×3, 10.08 ×1) landed in ONE carrier, while the header of
`_omitted_param_is_irrelevant` asserted about this very list: "Both already
stand in both carriers identically." The assertion was false, and there was
nothing to turn red on it.

TWO CONSEQUENCES, BOTH MEASURED:

1. B versus C. A program that assembles with an EMPTY snapshot (no pool is
   read at all) REFUSES to assemble WITHOUT a snapshot — `KIR-G103` requires
   an artifact that, by construction, is never read. Reproduced on
   `create_wall_foundation`, `create_extrusion_roof`, `create_filled_region`.

2. A versus C, and this one is worse. For seven ops out of eight, an EXPLICIT
   `{"by":"default"}` and an OMITTED parameter gave the OPPOSITE outcome: the
   omission went through to the document, while the explicit request fell
   into the "only one in the pool" rule and was refused on a real
   project. **The author who said out loud what the system does
   silently was refused FOR IT.**
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir import ground as g
from kir.diag import KirRefusal

#: Minimal programs: `type` is OMITTED, everything else is addressed by id,
#: meaning no pool is needed for anything except the disputed parameter.
ПРОГРАММЫ = {
    "create_wall": {"op": "create_wall", "id": "A", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0], "height_mm": 3000,
                    "level": {"by": "element_id", "value": 42}},
    "create_wall_foundation": {"op": "create_wall_foundation", "id": "A",
                               "wall": {"by": "element_id", "value": 42}},
    "create_extrusion_roof": {"op": "create_extrusion_roof", "id": "A",
                              "level": {"by": "element_id", "value": 42},
                              "profile_mm": [[0, 0], [6000, 0], [6000, 3000]],
                              "ref_plane": "xz",
                              "extrusion_mm": [0.0, 6000.0]},
    "create_filled_region": {"op": "create_filled_region", "id": "A",
                             "view": {"by": "element_id", "value": 42},
                             "contour": {"outer": {"shape": "rect",
                                                   "origin": [0, 0],
                                                   "size_mm": [1000, 1000]}}},
}


def _исход(op: dict, snapshot):
    try:
        g.ground([dict(op)], snapshot)
        return "ok"
    except KirRefusal as exc:
        return str(exc).split(":")[0].strip()


class ПустойСнимокИОтсутствиеСнимкаСОГЛАСНЫ(unittest.TestCase):
    """The invariant is declared in the guard file's header, and it WAS BEING VIOLATED."""

    def test_собирается_с_пустым_снимком_собирается_и_без_него(self):
        расхождения = []
        for имя, op in ПРОГРАММЫ.items():
            с_пустым = _исход(op, {"pools": {}})
            без = _исход(op, None)
            if с_пустым == "ok" and без != "ok":
                расхождения.append(f"{имя}: {{}} -> ok, None -> {без}")
        self.assertEqual(расхождения, [], "\n".join(расхождения))

    def test_МУТАЦИЯ_сужение_дома_меняет_ответ_ОБОИХ_носителей(self):
        """🔴 This is what it's all for: both carriers READ the house.

        THE FIRST DRAFT OF THIS TEST REQUIRED THE NARROWING TO RETURN
        A DISCREPANCY, AND IT WAS WRONG. The narrowing makes both carriers stricter
        IN THE SAME WAY: `_needs_pool` requires a snapshot, the resolve loop goes into the pool
        and refuses on an empty one. No discrepancy arises — and that is exactly
        what proves the shared house. Requiring redness here would mean
        requiring that the fix not work.

        What we check is what actually decides the matter: the answer CHANGED (meaning
        the sites read the set, not their own literal) and stayed
        CONSISTENT (meaning they read the SAME ONE).
        """
        было = {имя: (_исход(op, {"pools": {}}), _исход(op, None))
                for имя, op in ПРОГРАММЫ.items()}
        with mock.patch.object(g, "OPS_WITH_DOC_DEFAULT_TYPE",
                               frozenset({"create_wall"})):
            стало = {имя: (_исход(op, {"pools": {}}), _исход(op, None))
                     for имя, op in ПРОГРАММЫ.items()}
        сдвинулись = [имя for имя in ПРОГРАММЫ if было[имя] != стало[имя]]
        self.assertEqual(sorted(сдвинулись),
                         ["create_extrusion_roof", "create_filled_region",
                          "create_wall_foundation"],
                         "площадки обязаны ЧИТАТЬ множество, а не помнить его")
        for имя, (с_пустым, без) in стало.items():
            self.assertEqual(с_пустым == "ok", без == "ok",
                             f"{имя}: носители разошлись под мутацией")
        self.assertEqual(стало["create_wall"], ("ok", "ok"),
                         "оп, ОСТАВШИЙСЯ в доме, обязан не измениться")


class ЯвноеУмолчаниеИПропускДАЮТОДНОИТОЖЕ(unittest.TestCase):

    def test_by_default_совпадает_с_пропуском(self):
        """Saying out loud what the system does silently cannot be a mistake."""
        for имя, op in ПРОГРАММЫ.items():
            с_пропуском = g.ground([dict(op)], {"pools": {}})[0].get("type")
            явный = dict(op)
            явный["type"] = {"by": "default"}
            с_явным = g.ground([явный], {"pools": {}})[0].get("type")
            self.assertEqual(с_пропуском, с_явным, имя)

    def test_оба_пути_дают_ИМЕННО_документный_тип(self):
        """CONTROL: they could have coincided even by both merely reading the pool."""
        for имя, op in ПРОГРАММЫ.items():
            got = g.ground([dict(op)], {"pools": {}})[0].get("type")
            self.assertIsInstance(got, dict, имя)
            self.assertEqual(got["__grounded__"]["via"], "doc_default", имя)


class ДомОДИН_ИЭтоПРОВЕРЯЕТСЯ(unittest.TestCase):

    def test_литерального_списка_опов_в_файле_больше_НЕТ(self):
        """A fourth carrier gets introduced by copy-paste — we turn red on that.

        The FORM of the source is checked here, and this is deliberately weaker than behavior:
        the strong half is held up by the mutation tests above. What is caught here is
        exactly the move that introduced the defect in the first place — a hand-written
        list next to a ready-made one.
        """
        import inspect
        src = inspect.getsource(g)
        подозрительные = [
            строка for строка in src.splitlines()
            if строка.count("create_") >= 3
            and "OPS_WITH_DOC_DEFAULT_TYPE" not in строка
            and not строка.lstrip().startswith("#")]
        self.assertEqual(подозрительные, [], "\n".join(подозрительные))

    def test_в_доме_ровно_восемь_и_это_НЕ_украшение(self):
        """The number was paid for: 09.08 ×3 and 10.08 ×1 on top of the base four."""
        self.assertEqual(len(g.OPS_WITH_DOC_DEFAULT_TYPE), 8)


if __name__ == "__main__":
    unittest.main()
