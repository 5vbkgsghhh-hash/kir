"""`KIR-P005` and `KIR-T001` must name the NEXT MOVE, not just the cause.

WHAT THIS TEST IS AND WHY IT EXISTS. A live turn by the owner on 16.08.2026 on
the flash model: in ONE turn, two refusals landed side by side and behaved
in OPPOSITE ways. `KIR-T002` ("slopes with not a single angle is a flat roof,
just don't set that field") produced a corrected program in FOUR SECONDS;
`KIR-P003` ("unknown field") killed the turn. The difference is exactly one thing: the first one carried
a next move. `KIR-P003` was closed by commit `74b71035`; here are the next two
by frequency.

THE NUMBERS THAT SET THE ORDER OF WORK (the prod corpus `kir_rejections.jsonl`, records
of the form with `diag_code`, 463 of them over 10–16.08): `KIR-T001` 131 · `KIR-P003` 57
(closed) · `KIR-P005` 51. Three codes — 51% of live refusals.

MEASURED BEFORE THE FIX, on a program with six defects: six refusals, **108
characters**, and not one of them says what to do:

    p0_mm — a point in mm · p1_mm — a point in mm · level is mandatory ×2 ·
    height_mm — a number in mm

WHY THE TEXT IS CHECKED, NOT THE EXISTENCE OF A FUNCTION. The text is the product's
interface: the model reads it, and it alone decides whether the turn continues or dies.
A check for the mere existence of a symbol would go green on an empty string.
"""
from __future__ import annotations

import unittest

from kir import compiler, spec
from kir.diag import Diagnostic
from kir.dsl import _annotation


def _compile(*ops: dict):
    return compiler.compile_program(
        {"ir_version": spec.IR_VERSION, "intent": "контроль", "ops": list(ops)})


def _diag(res, code: str, field: str):
    """A refusal by code and field — or a PROBE FAILURE, never a silent skip.

    A probe that finds no subject must say so in words: "there is no refusal"
    and "the refusal is good" are different facts, and the second cannot be derived from the first.
    """
    for d in (res.diagnostics or []):
        if d.code == code and d.field_name == field:
            return d
    raise AssertionError(
        f"{code} по полю {field!r} не поднялся — зонд слеп, а не предмет "
        f"исправен; поднялись: "
        f"{[(x.code, x.field_name) for x in (res.diagnostics or [])]}")


class TheSlotRefusalNamesTheNextMove(unittest.TestCase):
    """FAIL CONTROL: remove `_name_the_next_move` from `validate` (or make
    `_slot_tail` return an empty string) — every test in this class goes red, and it
    goes red BEHAVIORALLY, on the text the model actually reads."""

    def test_missing_required_slot_names_the_next_move(self):
        res = _compile({"op": "create_wall", "id": "w1",
                        "p0_mm": [0, 0], "p1_mm": [4000, 0]})
        msg = _diag(res, "KIR-P005", "level").message_ru
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg,
                      "отказ «обязателен» назвал повод и не назвал ход")

    def test_wrong_type_names_the_next_move_and_shows_what_came(self):
        res = _compile({"op": "create_wall", "id": "w1",
                        "p0_mm": [0, 0], "p1_mm": [4000, 0],
                        "level": {"by": "default"},
                        "height_mm": "три метра"})
        msg = _diag(res, "KIR-T001", "height_mm").message_ru
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg)
        self.assertIn("три метра", msg,
                      "модель не видит, ЧТО именно она прислала")

    def test_the_slot_form_is_derived_from_the_registry_not_written(self):
        """The slot's rendering must MATCH what the registry itself prints.

        Hand-written text here would become a second opinion about the slot and would diverge
        from the op's shape from `KIR-P003` at exactly the moment the model reads both
        one after another. We check against `dsl._annotation` — the same source.
        """
        ospec = spec.OPS["create_wall"]
        p = next(pp for pp in ospec.params if pp.name == "height_mm")
        expected = str(_annotation(ospec, p))
        res = _compile({"op": "create_wall", "id": "w1",
                        "p0_mm": [0, 0], "p1_mm": [4000, 0],
                        "level": {"by": "default"}, "height_mm": "х"})
        msg = _diag(res, "KIR-T001", "height_mm").message_ru
        self.assertIn(expected, msg,
                      f"вид слота напечатан мимо реестра: ждали {expected!r}")

    def test_the_required_roster_comes_from_the_registry(self):
        """The list of mandatory fields is printed IN FULL and in the registry's order.

        The first draft searched for slot names anywhere in the text and was
        green on a bare "level is mandatory" — that is, it checked not the list
        but a substring match. What we look for here is exactly the list's own line.
        """
        ospec = spec.OPS["create_wall"]
        required = [pp.name for pp in ospec.params if pp.required]
        res = _compile({"op": "create_wall", "id": "w1"})
        joined = "\n".join(d.message_ru or "" for d in res.diagnostics)
        self.assertIn(
            f"обязательные слоты create_wall: {', '.join(required)}", joined,
            "перечень обязательных не выведен из реестра дословно")


class ItDoesNotInventAndDoesNotRepeat(unittest.TestCase):
    """THE OPPOSITE POLE. Without it, the fix would come down to "always give some
    advice", and invented advice is WORSE than silence: it gets checked by a turn."""

    def test_a_field_outside_the_registry_gets_no_advice(self):
        """A field that is in no op's registry gets NO advice.

        FAIL CONTROL: remove the `if p is None:` check in `_slot_tail` —
        it goes red, because the render of the view then runs on `None`.

        CALLED DIRECTLY, AND THIS IS AN HONEST BOUNDARY. The first draft fed
        `defaults` as a whole program and was green with the GUARD REMOVED: that
        refusal is raised outside `validate`, enrichment never sees it at all, and
        the test was checking scope, not the guard. Scope
        is checked separately, by the test below.
        """
        from kir.authoring_validation import _slot_tail
        bogus = Diagnostic(code="KIR-T001", message_ru="x",
                           field_name="такого_слота_нет", op_id="w1")
        self.assertEqual(
            _slot_tail("create_wall", bogus, with_roster=True), "",
            "совет выдуман для поля, которого нет в реестре опа")

    def test_a_refusal_raised_outside_validate_is_left_alone(self):
        """SCOPE: only what `validate` itself raised gets enriched.

        `defaults` is a field of the ENVELOPE: its refusal is raised by a different function, and
        it must not be touched, even if there were something to touch it with.
        """
        # The op must be LEGAL: on a program with no ops, the `defaults` check
        # never runs at all, and the probe would be green without ever reaching the subject.
        # Bought by this same test: the first draft fed `ops: []` and
        # slipped through.
        res = compiler.compile_program(
            {"ir_version": spec.IR_VERSION, "intent": "контроль",
             "defaults": "не объект",
             "ops": [{"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                      "p1_mm": [4000, 0], "level": {"by": "default"}}]})
        d = _diag(res, "KIR-T001", "defaults")
        self.assertNotIn(
            "СЛЕДУЮЩИЙ ХОД", d.message_ru or "",
            "совет выдуман: поля 'defaults' нет ни в одном реестре опа")

    def test_the_roster_is_printed_once_per_op_not_once_per_slot(self):
        """The list of mandatory fields is a property of THE OP. On a program with three
        defects in one op, it must appear exactly ONCE.

        FAIL CONTROL: make `with_roster=True` unconditional — it goes red.
        """
        res = _compile({"op": "create_wall", "id": "w1",
                        "p1_mm": "нет", "height_mm": "нет"})
        joined = "\n".join(d.message_ru or "" for d in res.diagnostics)
        self.assertGreaterEqual(
            len([d for d in res.diagnostics if d.op_id == "w1"]), 2,
            "зонд не дал двух отказов на одном опе — проверять нечего")
        self.assertEqual(
            joined.count("обязательные слоты create_wall"), 1,
            "перечень обязательных повторён на каждом слоте — это токены "
            "хода, в котором 84.6 % времени и так уходит на ожидание модели")

    def test_the_unknown_field_refusal_is_left_exactly_as_it_was(self):
        """`KIR-P003` is enriched by ITS OWN generator (the op's shape in full) in
        `74b71035`. The slot tail has no right to touch it: two texts about
        one refusal would drift apart, and drift apart silently.

        🔴 EXACTLY WHAT PROTECTS IT WAS MEASURED BY MUTATION, NOT ASSUMED.
        Removing the "a NEXT MOVE already exists" check does NOT make this test fail: 14
        of 14 stay green. The protection is STRUCTURAL — `KIR-P003`
        is raised at `compiler.py:527`, that is, BEFORE the call to
        `authoring.validate` at `:532`, and it does not fall into the
        `diags[start:]` slice at all. The first draft of this docstring declared a fail control
        that does not exist; that is exactly how a vacuous control is born — and catching them
        is what this whole file is written for.

        The guard in `_name_the_next_move` stays — but as a second line for
        code raised TWICE INSIDE `validate`, not as what guards
        `KIR-P003`. The test itself is valuable and stays: it will catch a future move of
        `KIR-P003`'s launch site into `validate`.
        """
        res = _compile({"op": "create_wall", "id": "w1",
                        "p0_mm": [0, 0], "p1_mm": [4000, 0],
                        "level": {"by": "default"}, "height": 3000})
        msg = _diag(res, "KIR-P003", "height").message_ru
        self.assertIn("ВСЕ слоты этого опа", msg,
                      "форма опа из KIR-P003 пропала")
        self.assertEqual(msg.count("СЛЕДУЮЩИЙ ХОД"), 1,
                         "совет удвоен: два порождателя пишут об одном отказе")


class TheUnknownKindStopsBeingSilentInRussian(unittest.TestCase):
    """`KIR-G001` — 32 live refusals in the corpus, fourth by frequency.

    Three branches of the hint search for a LATIN neighbor in `spec.KINDS`. Here the user
    writes in Russian, and the model follows suit, and on `kind='стенка'` the refusal
    used to come out as exactly three words.
    """

    def _g001(self, kind: str) -> str:
        res = _compile({"op": "query_list", "id": "l1", "kind": kind})
        return _diag(res, "KIR-G001", "kind").message_ru

    def test_a_cyrillic_guess_gets_the_whole_closed_table(self):
        """FAIL CONTROL: make the empty branch of `_kind_hint` `return ""`."""
        msg = self._g001("стенка")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg)
        for name in ("wall", "door", "pipe"):
            self.assertIn(name, msg,
                          "закрытая таблица напечатана не целиком")

    def test_the_table_is_printed_from_the_registry_whole(self):
        msg = self._g001("стенка")
        missing = [k for k in spec.KINDS if k not in msg]
        self.assertEqual(missing, [],
                         f"из закрытой таблицы выпали виды: {missing[:5]}")

    def test_a_near_miss_still_gets_the_short_pointer_not_the_table(self):
        """THE OPPOSITE POLE: the decision "specific instead of a full list" is still in force.

        Without this, the fix would degenerate into "always dump 662 characters", and
        a refusal that PREVIOUSLY pointed to one correct kind would become longer and
        worse.
        """
        msg = self._g001("wal")
        self.assertIn("ближайшие: wall", msg)
        self.assertNotIn("ВСЕ виды", msg,
                         "перечень вытеснил конкретное указание")

    def test_the_escape_value_still_routes_instead_of_listing(self):
        msg = self._g001("other")
        self.assertIn("recipe", msg)
        self.assertNotIn("ВСЕ виды", msg)


if __name__ == "__main__":
    unittest.main()
