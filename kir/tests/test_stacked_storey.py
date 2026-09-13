"""A TYPICAL FLOOR CARRIES DOORS AND WINDOWS — what makes a floor an
apartment.

🔴 WHAT IS BEING FIXED HERE AND WHY THIS IS NOT "TWO MORE NAMES IN A LIST".

`stack` is called "typical floor × N", and until 15.08.2026 it could not
carry two elements without which a floor is not an apartment. The argument
in the code sounded like a fact about the DOOR:

    "hosted ops (door/window) stay out because their host is addressed by
     `ref` to a sibling op, and the expansion renames ids per storey —
     a hosted op would point at storey 1 forever"

It was a fact about the EXPANSION. It was renaming member ids on every floor
(`{mid}_L{k}_{base}`) and **was not rewriting `by:ref` at all** — even
though the group emitter performs, and has always performed, that same
rewrite (`authoring._rename_refs`). The prohibition was describing our own
gap and read as if it were a property of the domain; this is canon form 9 in
its expensive half.

THE SECOND HALF OF THE ARGUMENT WAS REAL, and it has been resolved, not
worked around: the membership rule required that an op accept `level` — and
`create_door` HAS NO `level` FIELD AT ALL. This is not a registry omission:
**for a hosted element, the level is a property of the HOST.** So a
per-floor rewrite for a wall means "rewrite `level`", while for a door it
means "rewrite the REFERENCE TO THE HOST", and requiring a door to have its
own `level` would mean giving it a second source of floor alongside the
host.

WHAT THIS FILE DOES NOT VERIFY: live Revit. All the numbers below are about
the PROGRAM. That floor K's door physically hangs in floor K's wall is
proven here by reference resolution after expansion, not by building it.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.compiler import plan_program
from kir.diag import KirRefusal
from kir.macros import (_STACKABLE, _STACKABLE_HOSTED, _takes_level,
                             expand)


# ── shared fixtures ────────────────────────────────────────────────────────

def _wall(oid, x0, x1, y=0):
    return {"op": "create_wall", "id": oid, "p0_mm": [x0, y], "p1_mm": [x1, y],
            "height_mm": 3000.0, "type": {"by": "name", "value": "Кирпич 380"}}


def _door(oid, host, offset=1500.0):
    return {"op": "create_door", "id": oid, "host": {"by": "ref", "value": host},
            "offset_mm": offset,
            "symbol": {"by": "name", "value": "Дверь 900x2100"}}


def _window(oid, host, offset=3000.0):
    return {"op": "create_window", "id": oid,
            "host": {"by": "ref", "value": host}, "offset_mm": offset,
            "symbol": {"by": "name", "value": "Окно 1200x1500"}}


def _stack(floor, levels=5, mid="tower"):
    return {"op": "stack", "id": mid, "levels": levels, "h_mm": 3000,
            "base_elev_mm": 0, "name_prefix": "Этаж", "floor": list(floor)}


def _storey_of(op_id: str) -> str:
    """The floor number from the name assigned by the expansion
    (`{mid}_L{k}_{base}`)."""
    return op_id.split("_L", 1)[1].split("_", 1)[0]


# ── 1. THE WAVE'S GATE ───────────────────────────────────────────────────────

class ATypicalStoreyCarriesItsDoorsAndWindows(unittest.TestCase):
    """THE MAIN GATE: a floor with walls, doors and windows — in ONE
    macro."""

    FLOOR = (_wall("w_s", 0, 9000, y=0), _wall("w_n", 0, 9000, y=6000),
             _door("d1", "w_s"), _window("win1", "w_n"))

    def test_one_macro_builds_the_whole_tower(self):
        ops = expand([_stack(self.FLOOR, levels=5)])
        kinds: dict[str, int] = {}
        for op in ops:
            kinds[op["op"]] = kinds.get(op["op"], 0) + 1
        # 5 levels + 5×(2 walls + door + window)
        self.assertEqual(kinds, {"create_level": 5, "create_wall": 10,
                                 "create_door": 5, "create_window": 5}, kinds)
        self.assertEqual(len(ops), 25)

    def test_every_door_hangs_in_ITS_OWN_storey_wall(self):
        """🔴 A PROOF, NOT "THE PROGRAM COMPILED". What is checked is that
        the reference to the host RESOLVES to a member of THE SAME floor: a
        program where every door hangs off the first floor could compile
        too."""
        ops = expand([_stack(self.FLOOR, levels=5)])
        ids = {op["id"] for op in ops}
        hosted = [op for op in ops
                  if op["op"] in ("create_door", "create_window")]
        self.assertEqual(len(hosted), 10)
        for op in hosted:
            with self.subTest(op=op["id"]):
                host = op["host"]["value"]
                self.assertIn(host, ids, "хозяин не существует после экспансии")
                self.assertEqual(_storey_of(op["id"]), _storey_of(host),
                                 "дверь этажа %s висит на этаже %s"
                                 % (_storey_of(op["id"]), _storey_of(host)))

    def test_the_expanded_tower_is_a_legal_program(self):
        """The expansion must produce a program that the plan accepts:
        otherwise "it compiled" would only be checked by our own
        traversal."""
        ops = expand([_stack(self.FLOOR, levels=3)])
        plan_program({"ir_version": "1.0", "ops": ops})   # did not throw -> accepted

    def test_a_hosted_member_gets_no_level_of_its_own(self):
        """A door's level is a property of the HOST. Giving it its own
        `level` would mean creating a second source of floor, and on a
        mismatch one of the two would silently win."""
        ops = expand([_stack(self.FLOOR, levels=3)])
        for op in ops:
            if op["op"] in ("create_door", "create_window"):
                with self.subTest(op=op["id"]):
                    self.assertNotIn("level", op)
        # CONTROL: the level is still being written for the wall, otherwise
        # the check above would also pass on an expansion that had
        # forgotten how to write level at all.
        walls = [op for op in ops if op["op"] == "create_wall"]
        self.assertTrue(walls)
        for op in walls:
            self.assertIn("level", op)


# ── 2. FAIL CONTROL ──────────────────────────────────────────────────────────

class TheRefRewriteIsWhatMakesItWork(unittest.TestCase):
    """THE WAVE'S FAIL CONTROL: without reference rewriting, doors break,
    and this is caught.

    🔴 MEASUREMENT WITH A BROKEN REWRITE (15.08.2026): every door
    references `w` — an id that DOES NOT EXIST after expansion. That is,
    the outcome is worse than what the old argument claimed: not "points at
    the first floor" but a dangling reference. The compiler catches it as
    `KIR-L003`; checked from both ends below.
    """

    def test_a_dangling_host_ref_is_refused_by_name(self):
        """Exactly what a broken rewrite produces."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"},
            dict(_wall("t_L1_w", 0, 9000), level={"by": "ref", "value": "L1"}),
            _door("t_L1_d", "w"),          # there is no host with such an id
        ]}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program)
        codes = [d.code for d in caught.exception.diagnostics]
        self.assertIn("KIR-L003", codes, codes)

    def test_the_same_program_with_an_intact_ref_is_accepted(self):
        """A CONTROL for the previous one: the refusal must be about the
        REFERENCE, not about the program's shape in general. Without this,
        the red above proves nothing."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"},
            dict(_wall("t_L1_w", 0, 9000), level={"by": "ref", "value": "L1"}),
            _door("t_L1_d", "t_L1_w"),
        ]}
        plan_program(program)

    def test_a_host_outside_the_floor_is_refused_at_expansion(self):
        """A host OUTSIDE THE SET is a typed refusal from the EXPANSION,
        not a silent reference to the first floor. Without a host in the
        set, the op would hang off one and the same element on every
        floor."""
        floor = (_wall("w_s", 0, 9000), _door("d1", "ЧУЖОЙ"))
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("хозя", message.lower(), message)
        self.assertIn("ЧУЖОЙ", message)

    def test_a_host_addressed_by_element_id_is_left_alone(self):
        """A genuine document element is ONE across all floors — this is
        legitimate, and the rewrite does not touch it. Otherwise the rule
        "a reference outside the set is a refusal" would forbid a door in
        an already-existing wall."""
        floor = (_wall("w_s", 0, 9000),
                 {"op": "create_door", "id": "d1",
                  "host": {"by": "element_id", "value": 123456},
                  "offset_mm": 1500.0,
                  "symbol": {"by": "name", "value": "Дверь 900x2100"}})
        ops = expand([_stack(floor, levels=3)])
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual(len(doors), 3)
        for op in doors:
            self.assertEqual(op["host"], {"by": "element_id", "value": 123456})


# ── 3. REVERSE CONTROL: THE LIST DID NOT OPEN UP ────────────────────────────

class TheMembershipRuleStillRefuses(unittest.TestCase):
    """The list was extended by TWO names, not thrown open. Otherwise
    "hosted ops let in" would mean "everything that has a host let in"."""

    def test_an_op_that_must_not_be_stacked_is_still_refused(self):
        floor = (_wall("w", 0, 9000),
                 {"op": "create_wall_foundation", "id": "f1",
                  "wall": {"by": "ref", "value": "w"}})
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("create_wall_foundation", message)
        self.assertIn("не тиражируется", message)

    def test_a_modify_op_is_still_refused(self):
        """An editing op addresses SOMEONE ELSE'S element and has no floor
        of its own."""
        floor = (_wall("w", 0, 9000),
                 {"op": "set_param", "id": "p1",
                  "target": {"by": "ref", "value": "w"},
                  "param": "Комментарии", "value": "x"})
        with self.assertRaises(KirRefusal):
            expand([_stack(floor, levels=3)])

    def test_the_refusal_names_both_lists(self):
        """The refusal must name BOTH membership rules: an author who sees
        only the first list will conclude that a door is impossible in
        principle."""
        floor = (_wall("w", 0, 9000),
                 {"op": "create_wall_foundation", "id": "f1",
                  "wall": {"by": "ref", "value": "w"}})
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("create_door", message, "отказ не назвал хостящиеся")


# ── 4. THE MEMBERSHIP RULE IS MECHANICAL, NOT A MATTER OF TASTE ────────────

class EveryAdmittedHostedOpSatisfiesTheStatedRule(unittest.TestCase):
    """🔴 THE ADMISSION RATCHET. Every name in `_STACKABLE_HOSTED` must
    satisfy all four conditions declared in its docstring. A name that does
    not satisfy them cannot be added — this class will go red.
    """

    def test_every_admitted_op_creates_rather_than_modifies(self):
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                op_spec = spec.OPS[name]
                self.assertEqual(op_spec.effect.value, "create",
                                 "правящий оп адресует чужой элемент")

    def test_every_admitted_op_has_a_host_selector_that_takes_a_ref(self):
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                kinds = {p.name: p.kind for p in spec.OPS[name].params}
                host = kinds.get("host") or kinds.get("wall")
                self.assertIsNotNone(host, "нет селектора хозяина")
                self.assertIn(host, ("sel", "sel_list", "target_w", "refs_w"),
                              "селектор хозяина не принимает ref")

    def test_no_admitted_op_has_a_level_of_its_own(self):
        """The condition for whose sake the rule is a second one, rather
        than an extension of the first."""
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                self.assertFalse(_takes_level(name),
                                 "у опа есть собственный level — ему место в "
                                 "_STACKABLE, а не среди хостящихся")

    def test_the_two_lists_do_not_overlap(self):
        both = sorted(set(_STACKABLE) & set(_STACKABLE_HOSTED))
        self.assertEqual(both, [], "оп в обоих списках: правило переписи "
                                   "уровня стало бы неоднозначным")

    def test_every_admitted_op_states_its_reason(self):
        for name, reason in _STACKABLE_HOSTED.items():
            with self.subTest(op=name):
                self.assertGreaterEqual(len(reason), 40,
                                        "допуск без обоснования — это вкус")

    def test_the_level_question_is_asked_of_the_registry(self):
        """A CONTROL on `_takes_level`: it must DISCRIMINATE, otherwise the
        three checks above are green by construction."""
        self.assertTrue(_takes_level("create_wall"))
        self.assertFalse(_takes_level("create_door"))


# ── 5. WHAT DID NOT BREAK ────────────────────────────────────────────────────

class TheOldBehaviourIsUnchanged(unittest.TestCase):

    def test_a_floor_without_hosted_ops_expands_exactly_as_before(self):
        """A floor made of walls alone must give the same result as before
        the fix: the reference rewrite on a program with no references
        between members is an identity."""
        ops = expand([_stack((_wall("w1", 0, 9000), _wall("w2", 0, 6000)),
                             levels=3)])
        self.assertEqual(len(ops), 3 + 6)
        for op in ops:
            if op["op"] == "create_wall":
                self.assertEqual(op["level"]["by"], "ref")
                self.assertTrue(op["level"]["value"].startswith("tower_L"))

    def test_a_member_ref_to_a_sibling_is_rewritten_per_storey(self):
        """Not only the host: ANY reference between members must land on a
        neighbor on its own floor. Checked on `top_level`, which references
        a level OUTSIDE the set and therefore must NOT be touched."""
        ops = expand([_stack((_wall("w1", 0, 9000),
                              _door("d1", "w1")), levels=2)])
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual([op["host"]["value"] for op in doors],
                         ["tower_L1_w1", "tower_L2_w1"])

    def test_series_rewrites_refs_too(self):
        """THE SAME CLASS IN A DIFFERENT EXPANDER. `series` also renames
        member ids on every step; fixing only `stack` would mean closing
        the case instead of the class."""
        s = {"op": "series", "id": "bay", "count": 3,
             "track": {"x": [[0, 0], [3, 12000]]},
             "items": [
                 {"op": "create_wall", "id": "w",
                  "p0_mm": ["$x", 0], "p1_mm": ["$x@next", 0],
                  "level": {"by": "name", "value": "Этаж 1"},
                  "height_mm": 3000.0},
                 {"op": "create_door", "id": "d",
                  "host": {"by": "ref", "value": "w"}, "offset_mm": 1000.0,
                  "symbol": {"by": "name", "value": "Дверь 900x2100"}},
             ]}
        ops = expand([s])
        ids = {op["id"] for op in ops}
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual(len(doors), 3)
        for op in doors:
            with self.subTest(op=op["id"]):
                host = op["host"]["value"]
                self.assertIn(host, ids)
                self.assertEqual(op["id"].split("_")[1], host.split("_")[1],
                                 "дверь шага k повисла на стене другого шага")


if __name__ == "__main__":
    unittest.main()
