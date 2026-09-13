"""THE MUTENESS SEAM READ THE AUTHOR'S ENVELOPE, WHILE INDICES WERE
ASSIGNED AGAINST A DIFFERENT LIST.

🔴 WHY (25.08.2026, TWO audit findings in one place, both reproduced).

On the refusal branch, `compile_program` built `raw_ops` from
`program["ops"]` — the AUTHOR's field. But the diagnostics' `op_index`
is assigned in `_parse_and_check_internal` against the list AFTER
normalization and macro expansion. Two different lists, and nothing
forced them to agree.

```
THE "ONE OP WITHOUT A LIST" FORM (legalized on 17.08)
    ops is a dict. `len(raw_ops)` gave the number of KEYS,
    `raw_ops[idx]` raised a KeyError, the fallback walk went over the
    string keys, and enrichment never fired for a single refusal from
    such a program.

A PROGRAM WITH A MACRO
    A `stack` from one author op yields 4. Diagnostics arrive with
    `op_index=3,4` and `op_id='sec_L1_W'` — an index past the end of
    the author's list, and an id minted by expansion that never
    appears in the envelope. Measurement: 39 characters with no
    "NEXT MOVE," against 243 for the same error in a program without
    a macro.
```

**Telemetry went mute too:** `coverage_feed.record_rejections`
receives the SAME argument and was writing `op_requested=None` — that
is, the instrument we use to measure the muteness of refusals was
itself mute on these programs.

Fixed in two moves: a PARSE-time refusal carries its own list
(`KirRefusal.expanded_ops`); a refusal AFTER parsing takes its list
from the PLAN, which by that point has already been built.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

СНИМОК = {"wall_types": [{"id": 9, "name": "Базовая"}],
          "levels": [{"id": 1, "name": "Э1"}]}
ПЛОХОЙ_ТИП = {"by": "name", "value": "НЕТ ТАКОГО ТИПА"}

ПРОСТАЯ = {"ir_version": "1.0", "ops": [
    {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "height_mm": 2800, "level": {"by": "element_id", "value": 1},
     "type": ПЛОХОЙ_ТИП}]}

МАКРО = {"ir_version": "1.0", "ops": [
    {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
     "name_prefix": "Этаж",
     "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "height_mm": 2800,
                "type": ПЛОХОЙ_ТИП}]}]}

ОДИН_ОП = {"ir_version": "1.0", "ops": {
    "op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
    "height_mm": 2800, "level": {"by": "element_id", "value": 1},
    "type": ПЛОХОЙ_ТИП}}


def _первая(prog):
    out = compile_program(prog, revit_version="2026", snapshot=СНИМОК)
    assert not out.ok
    return out.diagnostics[0]


class ОТКАЗНАЗЫВАЕТСЛЕДУЮЩИЙХОДВЕЗДЕ(unittest.TestCase):

    def test_простая_программа_как_была(self):
        """PASS control: this path worked and must remain."""
        self.assertIn("СЛЕДУЮЩИЙ ХОД", str(_первая(ПРОСТАЯ).message_ru))

    def test_программа_с_МАКРОСОМ_тоже(self):
        """🔴 RED before the fix: 39 characters, no move."""
        d = _первая(МАКРО)
        self.assertEqual(d.op_id, "sec_L1_W",
                         "id отчеканен экспансией — в конверте его нет")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", str(d.message_ru))

    def test_один_оп_БЕЗ_СПИСКА_тоже(self):
        """The form was legalized on 17.08; a dict where a list is
        expected is silence."""
        self.assertIn("СЛЕДУЮЩИЙ ХОД", str(_первая(ОДИН_ОП).message_ru))

    def test_текст_у_ВСЕХ_ТРЁХ_одинаковой_длины(self):
        """One error — one answer, no matter how it was recorded."""
        длины = {имя: len(str(_первая(p).message_ru))
                 for имя, p in (("простая", ПРОСТАЯ), ("макро", МАКРО),
                                ("один оп", ОДИН_ОП))}
        self.assertEqual(len(set(длины.values())), 1, длины)


class ОТКАЗРАЗБОРАНЕСЁТСВОЙСПИСОК(unittest.TestCase):

    def test_KirRefusal_умеет_нести_развёрнутые_опы(self):
        from kir.diag import KirRefusal
        self.assertTrue(hasattr(KirRefusal, "expanded_ops"))

    def test_поле_НЕОБЯЗАТЕЛЬНОЕ(self):
        """Whoever can, provides it; whoever cannot, DOES NOT LIE:
        `None`, not an empty value."""
        from kir.diag import KirRefusal
        self.assertIsNone(KirRefusal([]).expanded_ops)


if __name__ == "__main__":
    unittest.main()
