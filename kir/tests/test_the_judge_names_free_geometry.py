"""THE JUDGE MUST NAME THE BODIES IT CANNOT SEE.

🔴 THE NUMBER THIS FILE EXISTS FOR. A room made of four strips, written with
a free-form dictionary, arrives at self-check as `walls 0`: the judge reads
OPERATION KINDS, and `create_solid_blend` is not a wall. The rules about
walls stay SILENT the whole time — and a rule's silence is, from the
outside, indistinguishable from its consent. The author reads a verdict
that looks clean, over a building the judge never parsed.

Promotion (`kir/promote.py`, commit `0d0938a`) fixed exactly half of this:
`promote()` was called ONLY by the author's own hand. Whoever did not know
about it did not learn it from the verdict either. Here the second half is
closed: the self-check itself names the bodies, their future kind, and
what they did NOT become.

WHAT IS GUARDED, IN ORDER OF IMPORTANCE

1. A dry run and an actual promotion give the SAME kind. There is exactly
   one fork (`promote._native`), and this test goes red on the day someone
   sets up a separate "parse for the judge": the block's promise would
   diverge from what `promote()` actually does, and diverge silently.
2. The block APPEARS on a free-form and STAYS SILENT after promotion
   (otherwise it is noise, and noise stops being read).
3. Reading moves NOTHING: neither the program nor the shapes.
4. Descent into group members: in a real building, 82.6% of operations
   live inside groups.
5. A body the environment cannot read is NAMED, not skipped. A silent skip
   would make the report more confident the less the environment can do.
"""
from __future__ import annotations

import copy
import unittest


def _кольцо(w, h, x0=0.0, y0=0.0):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


ФОРМА = (
    'этаж = create_level(elev_mm=0, name="Этаж 1")\n'
    'def кольцо(w, h, x0=0.0, y0=0.0):\n'
    '    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]\n'
    'ю = loft([(кольцо(6000, 200, 0, -200), 0), (кольцо(6000, 200, 0, -200), 3000)])\n'
    'с = loft([(кольцо(6000, 200, 0, 4000), 0), (кольцо(6000, 200, 0, 4000), 3000)])\n'
    'з = loft([(кольцо(200, 4000, -200, 0), 0), (кольцо(200, 4000, -200, 0), 3000)])\n'
    'в = loft([(кольцо(200, 4000, 6000, 0), 0), (кольцо(200, 4000, 6000, 0), 3000)])\n')
ПРОДВИНУТЬ = 'for ф in (ю, с, з, в):\n    promote(ф, level=этаж)\n'
СУД = 'design_check()\n'


def _прогон(source: str) -> str:
    from kir import sandbox
    res = sandbox.execute_author_script(source)
    assert res.ok, res.refusal
    return res.stdout or ""


class TheJudgeNamesWhatItCannotSee(unittest.TestCase):
    """The real door: the author's script through the sandbox, output as-is."""

    def test_free_geometry_is_named_with_its_future_role(self) -> None:
        вывод = _прогон(ФОРМА + СУД)
        self.assertIn("прочитано: doors 0, levels 1, rooms 0, stairs 0, "
                      "walls 0, windows 0", вывод)
        self.assertIn("СУДЬЯ НЕ ВИДИТ СВОБОДНОЙ ГЕОМЕТРИИ: тел 4", вывод)
        # the kind is named for each of the four, and named as MEASURED, not guessed
        self.assertEqual(вывод.count("-> стало бы walls"), 4)
        self.assertIn("толщина 200 мм, длина 6000 мм", вывод)
        self.assertIn("promote(форма)", вывод)

    def test_after_promotion_the_block_is_silent(self) -> None:
        """A block that always speaks stops being read."""
        вывод = _прогон(ФОРМА + ПРОДВИНУТЬ + СУД)
        self.assertIn("walls 4", вывод)
        self.assertNotIn("СУДЬЯ НЕ ВИДИТ СВОБОДНОЙ ГЕОМЕТРИИ", вывод)

    def test_the_verdict_itself_did_not_move(self) -> None:
        """The prefix is ADDED to the verdict, it did not replace it.

        Both halves of the previous text must stay in place: the verdict
        itself, and the `HAB000` prefix. The test for the prefix is
        nearby, in `test_course`.
        """
        вывод = _прогон(ФОРМА + СУД)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", вывод)
        self.assertIn("HAB000", вывод)


class TheDryRunIsTheSameLaw(unittest.TestCase):
    """🔴 LOAD-BEARING. One parse for both the promise and the action."""

    def _комната(self):
        from kir import dsl
        from kir.course import rhino as R
        dsl.reset()
        уровень = dsl.create_level(elev_mm=0, name="Этаж 1")
        формы = [
            R.loft([(_кольцо(6000, 200, 0, -200), 0),
                    (_кольцо(6000, 200, 0, -200), 3000)]),
            R.loft([(_кольцо(200, 4000, -200, 0), 0),
                    (_кольцо(200, 4000, -200, 0), 3000)]),
            R.loft([(_кольцо(6000, 4000), 3000), (_кольцо(6000, 4000), 3200)]),
        ]
        return dsl, уровень, формы

    def test_dry_and_wet_agree_on_the_role(self) -> None:
        from kir import promote as P
        dsl, уровень, формы = self._комната()
        сухо = [P.classify(ф)["role"] for ф in формы]
        мокро = [P.promote(ф, level=уровень)["role"] for ф in формы]
        self.assertEqual(сухо, мокро)
        self.assertEqual(сухо, ["walls", "walls", "floors"])

    def test_the_dry_run_moves_nothing(self) -> None:
        from kir import promote as P
        dsl, _уровень, формы = self._комната()
        до = copy.deepcopy(dsl.current().ops)
        итоги = [P.classify(ф) for ф in формы]
        self.assertEqual(dsl.current().ops, до)
        self.assertEqual([i["retracted"] for i in итоги], [0, 0, 0])
        # and the shapes themselves are intact: the refusal removed nothing
        self.assertEqual([len(ф["ops"]) for ф in формы], [1, 1, 1])

    def test_reading_a_program_agrees_with_reading_the_shapes(self) -> None:
        """`unpromoted` over operations = `classify` over live shapes."""
        from kir import promote as P
        dsl, _уровень, формы = self._комната()
        по_формам = [P.classify(ф)["role"] for ф in формы]
        по_программе = [z["role"] for z in P.unpromoted(dsl.current().ops)]
        self.assertEqual(по_программе, по_формам)


class TheReaderDescendsIntoGroups(unittest.TestCase):
    """A top-level-only walk would be blind on exactly the real buildings."""

    def test_a_body_inside_a_group_is_still_seen(self) -> None:
        вывод = _прогон(
            'def кольцо(w, h, x0=0.0, y0=0.0):\n'
            '    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]\n'
            'ю = loft([(кольцо(6000, 200, 0, -200), 0),'
            ' (кольцо(6000, 200, 0, -200), 3000)])\n'
            'create_group(members=ю["ops"], placements=[[0, 0]], name="секция")\n'
            + СУД)
        self.assertIn("СУДЬЯ НЕ ВИДИТ СВОБОДНОЙ ГЕОМЕТРИИ: тел 1", вывод)
        self.assertIn("-> стало бы walls", вывод)


class WhatTheEnvironmentCannotReadIsNamed(unittest.TestCase):
    """Skipping it silently would mean becoming more confident from one's own inability."""

    def test_a_revolve_is_named_not_skipped(self) -> None:
        вывод = _прогон(
            'revolve([(0, 0), (2000, 0), (2000, 3000), (0, 3000)],'
            ' axis_xy_mm=[0, 0])\n' + СУД)
        self.assertIn("СУДЬЯ НЕ ВИДИТ СВОБОДНОЙ ГЕОМЕТРИИ: тел 1", вывод)
        self.assertIn("родом не стало", вывод)
        self.assertIn("create_solid_revolve", вывод)
        self.assertNotIn("-> стало бы", вывод)

    def test_a_directshape_is_read_from_the_op_itself(self) -> None:
        """For `create_directshape`, the mesh LIES IN the operation — nothing to rebuild."""
        from kir.course import rhino as R
        меш = {"vertices_mm": [[0, 0, 0]], "triangles": [[0, 0, 0]]}
        форма = R._shape_from_op({"op": "create_directshape", "mesh": меш,
                                 "id": "ds1"})
        self.assertIsNotNone(форма)
        self.assertIs(форма["mesh"], меш)
        self.assertEqual(форма["ops"], [])

    def test_an_op_we_never_built_reads_as_none(self) -> None:
        from kir.course import rhino as R
        self.assertIsNone(R._shape_from_op({"op": "create_solid_extrusion",
                                           "profile": {"outer": []},
                                           "height_mm": 100}))


class TheRebuiltMeshIsTheBuildersOwn(unittest.TestCase):
    """Rebuilding is checked against WHO ACTUALLY BUILT IT, not against my expectation."""

    def test_shape_from_op_reproduces_the_live_loft_mesh(self) -> None:
        from kir import dsl
        from kir.course import rhino as R
        dsl.reset()
        живая = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        собранная = R._shape_from_op(dsl.current().ops[0])
        self.assertIsNotNone(собранная)
        self.assertEqual(собранная["mesh"], живая["mesh"])


class TheReceiptCarriesItToTheWire(unittest.TestCase):
    """🔴 THE PRIMARY USER READS THE RECEIPT, NOT CALLS `design_check()`.

    The owner's word of 02.09.2026: KIR is building A MULTI-AGENT
    ENVIRONMENT. A measurement of this same tree: out of 323 live scripts,
    `design_check()` is called in THREE. So the knowledge that lives only
    behind that call never reaches the primary user — and the block must
    travel inside the receipt itself, unasked.

    The subtle spot the class exists for: a program made of a single
    free-form geometry always gives "0 of 20 rules", and the self-check
    goes into `silent_because`. It is precisely on this branch that the
    block is needed most, and precisely this branch that is easiest to
    forget.
    """

    def _программа(self, строй):
        from kir import dsl
        dsl.reset()
        строй(dsl)
        return {"ops": dsl.current().ops}

    def _свободная(self, dsl):
        from kir.course import rhino as R
        dsl.create_level(elev_mm=0, name="Этаж 1")
        R.loft([(_кольцо(6000, 200, 0, -200), 0),
                (_кольцо(6000, 200, 0, -200), 3000)])
        R.loft([(_кольцо(200, 4000, -200, 0), 0),
                (_кольцо(200, 4000, -200, 0), 3000)])
        R.revolve([(0, 0), (2000, 0), (2000, 3000), (0, 3000)],
                  axis_xy_mm=[0, 0])
        R.loft([(_кольцо(400, 400), 0), (_кольцо(400, 400), 3000)])

    def test_the_silent_branch_still_carries_the_block(self) -> None:
        from kir import serving
        блок = serving._self_check_block(self._программа(self._свободная))
        self.assertIn("silent_because", блок)
        fg = блок.get("free_geometry")
        self.assertIsNotNone(fg, "именно в молчащей ветке блок и нужен")
        self.assertEqual(fg["bodies"], 4)
        self.assertEqual(fg["would_be"], {"walls": 2})
        self.assertEqual(fg["not_native"], {"column_needs_symbol": 1})
        self.assertEqual(fg["unread"], 1)

    def test_the_head_line_says_it_in_one_clause(self) -> None:
        from kir import serving
        блок = serving._self_check_block(self._программа(self._свободная))
        строка = serving._self_check_note_ru(блок)
        self.assertIn("СУДЬЯ НЕ ВИДЕЛ СВОБОДНОЙ ГЕОМЕТРИИ: тел 4", строка)
        self.assertIn("walls 2", строка)
        self.assertIn("формы 1 среда не читает", строка)

    def test_a_native_program_gets_no_block_at_all(self) -> None:
        """A block that always speaks stops being read."""
        from kir import serving

        def родная(dsl):
            у = dsl.create_level(elev_mm=0, name="Этаж 1")
            dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                            level=у)

        блок = serving._self_check_block(self._программа(родная))
        self.assertNotIn("free_geometry", блок)
        self.assertNotIn("СВОБОДНОЙ ГЕОМЕТРИИ",
                         serving._self_check_note_ru(блок))

    def test_the_receipt_counts_by_key_not_by_wording(self) -> None:
        """The reason travels as a KEY: counting by text means counting by wording."""
        from kir import promote as P
        from kir.course import rhino as R
        from kir import dsl
        dsl.reset()
        R.loft([(_кольцо(400, 400), 0), (_кольцо(400, 400), 3000)])
        z = P.unpromoted(dsl.current().ops)[0]
        self.assertEqual(z["reason_key"], "column_needs_symbol")
        self.assertIn(z["reason_key"], P.REASONS)


class TheEnvironmentTakesTheLevelTheAuthorDeclared(unittest.TestCase):
    """🔴 HALF OF THE MEASURED REASON WHY REVIT PRODUCES BOOTHS.

    Of 82 registry operations, **32 require a level**, and the shape has
    no level and nowhere to get one from. Now `promote(shape)` takes the
    level that the author declared THEMSELVES — the nearest one BELOW the
    bottom of the body.

    THIS IS NOT A SOLVER (the owner's word of 02.09: "I don't want a
    solver producing a limited set of floor plans"): nothing is laid out,
    what was written is taken as-is. AND THIS IS NOT NEW GRAMMAR: the
    selector `{"by": "ref"}` is exactly what the author's own handle turns
    into, so neither grounding, nor canonicalization, nor the reverse pass
    move at all. The selector `{"by": "elevation"}` was being built and
    was dropped on 02.09 precisely because it required seven boundaries.
    """

    def _две_отметки(self):
        from kir import dsl
        from kir.course import rhino as R
        dsl.reset()
        dsl.create_level(elev_mm=0, name="Этаж 1")
        dsl.create_level(elev_mm=3000, name="Этаж 2")
        низ = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        верх = R.loft([(_кольцо(6000, 200), 3000), (_кольцо(6000, 200), 6000)])
        return dsl, низ, верх

    def test_each_body_gets_the_level_under_it(self) -> None:
        """A discriminating input: two bodies at different elevations, DIFFERENT levels.

        A check that "a level got substituted" would pass on a single
        level too — it would not distinguish selection from substituting
        whatever came first.
        """
        from kir import promote as P
        _dsl, низ, верх = self._две_отметки()
        r1, r2 = P.promote(низ), P.promote(верх)
        self.assertEqual(r1["role"], "walls")
        self.assertEqual(r2["role"], "walls")
        self.assertEqual(r1["measured"]["уровень"]["имя"], "Этаж 1")
        self.assertEqual(r2["measured"]["уровень"]["имя"], "Этаж 2")

    def test_the_slot_is_byte_identical_to_an_authored_handle(self) -> None:
        """No new grammar was set up: it is the same slot as the author's own handle."""
        from kir import dsl, promote as P
        from kir.course import rhino as R
        dsl.reset()
        ручка = dsl.create_level(elev_mm=0, name="Этаж 1")
        рукой = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                                level=ручка)
        тело = R.loft([(_кольцо(6000, 200, 0, 4000), 0),
                       (_кольцо(6000, 200, 0, 4000), 3000)])
        P.promote(тело)
        опы = {o["id"]: o for o in dsl.current().ops}
        средой = [o for o in dsl.current().ops
                  if o["op"] == "create_wall" and o["id"] != рукой.id][0]
        self.assertEqual(средой["level"], опы[рукой.id]["level"])
        self.assertEqual(средой["level"], {"by": "ref", "value": ручка.id})

    def test_an_explicit_level_still_wins(self) -> None:
        from kir import dsl, promote as P
        _dsl, низ, верх = self._две_отметки()
        свой = [o for o in dsl.current().ops
                if o["op"] == "create_level" and o["name"] == "Этаж 2"][0]
        r = P.promote(низ, level={"by": "ref", "value": свой["id"]})
        self.assertEqual(r["role"], "walls")
        self.assertNotIn("уровень", r["measured"])

    def test_no_level_declared_is_a_named_refusal_not_a_guess(self) -> None:
        from kir import dsl, promote as P
        from kir.course import rhino as R
        dsl.reset()
        тело = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        r = P.promote(тело)
        self.assertIsNone(r["role"])
        self.assertEqual(r["reason_key"], "no_level_in_program")
        self.assertIn("create_level", r["reason"])
        # and the shape is INTACT: the refusal removed nothing
        self.assertEqual(r["retracted"], 0)
        self.assertEqual(len(dsl.current().ops), 1)

    def test_all_levels_above_the_body_refuse_rather_than_lift_it(self) -> None:
        """Placing an element on the level ABOVE it would silently raise it."""
        from kir import dsl, promote as P
        from kir.course import rhino as R
        dsl.reset()
        dsl.create_level(elev_mm=10000, name="Этаж 4")
        тело = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        r = P.promote(тело)
        self.assertEqual(r["reason_key"], "no_level_below")
        self.assertIn("10000", r["reason"])

    def test_two_levels_at_one_elevation_refuse(self) -> None:
        from kir import dsl, promote as P
        from kir.course import rhino as R
        dsl.reset()
        dsl.create_level(elev_mm=0, name="Э-а")
        dsl.create_level(elev_mm=0, name="Э-б")
        тело = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        r = P.promote(тело)
        self.assertEqual(r["reason_key"], "level_is_ambiguous")

    def test_the_dry_run_never_asks_for_a_level(self) -> None:
        """A dry run answers about the SHAPE: program state is not its concern."""
        from kir import dsl, promote as P
        from kir.course import rhino as R
        dsl.reset()
        тело = R.loft([(_кольцо(6000, 200), 0), (_кольцо(6000, 200), 3000)])
        self.assertEqual(P.classify(тело)["role"], "walls")


if __name__ == "__main__":
    unittest.main()
