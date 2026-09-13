"""THE DIAGNOSTIC SEAM: a `ref` hint must be EXECUTABLE, not just look like one.

WHAT IS CAUGHT HERE (reproduced live 26.08.2026 through the real
`compile_program`, not through a call into internals):

    create_level(id="lvl", name="МОЙ-ТИП-200")
    create_wall(type={"by": "name", "value": "МОЙ-ТИП-200"})

    KIR-G101  wall_types: «МОЙ-ТИП-200» не найден.
      СЛЕДУЮЩИЙ ХОД: … сошлись на него: {"by": "ref", "value": "lvl"}
        type  sel: name|element_id|default|ref(wall_type)   ← ДВУМЯ СТРОКАМИ НИЖЕ

One refusal names TWO next moves, and they contradict each other: the
first offers a reference to `create_level` (kind `level`), the second
prints that the slot only accepts `ref(wall_type)`. A model that listens
to the first gets `KIR-L004` on the very next turn and loses the loop.

THE LAW THIS BREAKS is written in `ground.py`, verbatim: «отказ,
называющий невыполнимый ход, дороже отказа, не называющего никакого».
Silence is cheaper than advice here, so the fix is not "suggest something
else" but "do not suggest something unworkable".

WHY THE TEST CHECKS A PROPERTY, NOT A CASE. Pinning the literal text of
one refusal would pin the SHAPE of the first case (canon form 54). What
is checked is an invariant: if a refusal named `{"by": "ref", "value":
X}`, then the kind of X's operation result must fit the slot the refusal
is about. Fitness is asked of the authority —
`ParamSpec.accepts_reference` — not of a table set up by this test.
"""
from __future__ import annotations

import re
import unittest

from kir import compiler, spec


#: A snapshot with a SINGLE wall type: «МОЙ-ТИП-200» is absent from it by
#: construction, so grounding must give `KIR-G101`, and nothing else.
SNAPSHOT = {
    "levels": [{"id": 111, "name": "Этаж 1"}],
    "wall_types": [{"id": 222, "name": "Наружная 300"}],
}

#: A name absent from the snapshot, which ONE of the program's operations creates.
НОВОЕ_ИМЯ = "МОЙ-ТИП-200"

_REF_В_ПОДСКАЗКЕ = re.compile(
    r'\{"by":\s*"ref",\s*"value":\s*"([^"]+)"\}')


def _стена(type_value: str) -> dict:
    return {"op": "create_wall", "id": "w1",
            "p0_mm": [0, 0], "p1_mm": [5000, 0],
            "level": {"by": "name", "value": "Этаж 1"},
            "height_mm": 3000,
            "type": {"by": "name", "value": type_value}}


def _скомпилировать(ops: list) -> list:
    out = compiler.compile_program(
        {"ir_version": "1.0", "intent": "проба шва", "ops": ops},
        revit_version="2023", snapshot=SNAPSHOT, bulk=True)
    return list(getattr(out, "diagnostics", None) or [])


def _подсказанный_ref(diags) -> str | None:
    """The name of the operation the refusal pointed to as a reference. `None` means it did not."""
    for d in diags:
        m = _REF_В_ПОДСКАЗКЕ.search(getattr(d, "message_ru", "") or "")
        if m:
            return m.group(1)
    return None


class ПодсказкаСсылкиОбязанаБытьВыполнима(unittest.TestCase):

    def test_производитель_чужого_рода_не_предлагается(self):
        """`create_level` does not fit the `create_wall.type` slot — stay silent."""
        diags = _скомпилировать([
            {"op": "create_level", "id": "lvl", "elev_mm": 3000,
             "name": НОВОЕ_ИМЯ},
            _стена(НОВОЕ_ИМЯ),
        ])
        подсказан = _подсказанный_ref(diags)
        self.assertIsNone(
            подсказан,
            "отказ послал ссылаться на операцию «%s», чей род результата в "
            "слот `create_wall.type` не годится. Совет, который компилятор "
            "сам отвергнет следующим ходом, стоит модели круга и хуже "
            "молчания.\nПолный текст:\n%s"
            % (подсказан, "\n".join(
                (getattr(d, "message_ru", "") or "") for d in diags)))

    def test_производитель_годного_рода_ПО_ПРЕЖНЕМУ_предлагается(self):
        """PASS CONTROL: the fix has no right to switch the hint off.

        `create_wall_type(host_kind="wall")` produces the kind
        `wall_type`, and that is exactly what the slot accepts. If this
        test goes red, the hint was not fixed but disabled, and that is a
        regression, not a repair.
        """
        diags = _скомпилировать([
            {"op": "create_wall_type", "id": "wt",
             "new_name": НОВОЕ_ИМЯ, "host_kind": "wall",
             "source_type": {"by": "name", "value": "Наружная 300"},
             "layers": [{"width_mm": 200.0, "function": "Structure"}]},
            _стена(НОВОЕ_ИМЯ),
        ])
        self.assertEqual(
            _подсказанный_ref(diags), "wt",
            "подсказка про `ref` пропала у ГОДНОГО производителя — значит "
            "починка выключила её, а не сузила.\nПолный текст:\n%s"
            % "\n".join((getattr(d, "message_ru", "") or "") for d in diags))

    def test_всякая_названная_ссылка_годится_в_свой_слот(self):
        """An invariant of the class, not the shape of a case.

        Both programs above are walked; for every hint found, the kind of
        the named operation's result is asked of the registry and checked
        against the slot via `ParamSpec.accepts_reference` — the same
        authority the compiler itself uses (`compiler`, reference check).
        """
        программы = [
            [{"op": "create_level", "id": "lvl", "elev_mm": 3000,
              "name": НОВОЕ_ИМЯ}, _стена(НОВОЕ_ИМЯ)],
            [{"op": "create_wall_type", "id": "wt", "new_name": НОВОЕ_ИМЯ,
              "host_kind": "wall",
              "source_type": {"by": "name", "value": "Наружная 300"},
              "layers": [{"width_mm": 200.0, "function": "Structure"}]},
             _стена(НОВОЕ_ИМЯ)],
        ]
        for ops in программы:
            with self.subTest(производитель=ops[0]["op"]):
                diags = _скомпилировать(ops)
                for d in diags:
                    m = _REF_В_ПОДСКАЗКЕ.search(
                        getattr(d, "message_ru", "") or "")
                    if not m:
                        continue
                    цель = m.group(1)
                    producer = next(o for o in ops if o.get("id") == цель)
                    pspec = next(
                        p for p in spec.OPS["create_wall"].params
                        if p.name == getattr(d, "field_name", ""))
                    род = spec.OPS[producer["op"]].result_for(
                        producer).reference_kind
                    self.assertTrue(
                        pspec.accepts_reference(род),
                        "отказ назвал ref на «%s» (род %s), а слот "
                        "`create_wall.%s` принимает %s"
                        % (цель, род, pspec.name,
                           [k.value for k in pspec.ref_kinds]))


class ШовНеЗаменяетОтказИнцидентом(unittest.TestCase):
    """The seam works on the path of a REFUSAL — a program there can be garbage.

    Paid for by our own probe on 26.08.2026, BEFORE the report: the first
    edition of the kind-check wrote `spec.OPS.get(_op.get("op"))` without
    checking the value's kind, and dropped a
    `TypeError: unhashable type: 'list'` ON TOP OF an already-assembled
    `KIR-P002`. The parse had done its job correctly and named the next
    move; the seam, whose docstring promises "never raises", replaced a
    typed refusal with an incident.

    What is checked is the CLASS: any value in the `op` slot, not just
    the list from the first case. The unhashable ones (`list`, `dict`)
    are the ones that used to crash; the hashable ones (`float`, `None`,
    an empty string) are the control, proving the test tells states
    apart rather than being green by construction.
    """

    ЗНАЧЕНИЯ = ([ "create_wall" ], {"x": 1}, 3.5, None, "", 0)

    def test_любой_мусор_в_слоте_op_даёт_отказ_а_не_исключение(self):
        for плохое in self.ЗНАЧЕНИЯ:
            with self.subTest(op=repr(плохое)):
                try:
                    out = compiler.compile_program(
                        {"ir_version": "1.0", "intent": "мусор", "ops": [
                            {"op": плохое, "id": "a", "name": НОВОЕ_ИМЯ},
                            _стена(НОВОЕ_ИМЯ)]},
                        revit_version="2023", snapshot=SNAPSHOT, bulk=True)
                except Exception as exc:      # noqa: BLE001 — this is exactly what is being caught
                    self.fail(
                        "шов бросил %s вместо типизированного отказа: %s"
                        % (type(exc).__name__, exc))
                self.assertFalse(getattr(out, "ok", None))
                self.assertTrue(
                    getattr(out, "diagnostics", None),
                    "отказ без диагностик — исход хуже исключения: молчит")


if __name__ == "__main__":
    unittest.main()
