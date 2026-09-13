"""`kir/clash/` WAS DARK — AND NOW IT HAS A PROD ENTRY POINT.

WHAT WAS MEASURED BEFORE THE FIX (09.08, `tests/capability_graph.py`). The
package `kir/clash/` — SAT/MTV, convex hull, broad phase, a closed
category table, a canonical byte-for-byte report, six test suites — had
NOT A SINGLE importer reachable from prod: `graph.live()` contained not
one `kir.clash.*` module. The only entry point was a manual CLI. The
refuting measurement is recorded here honestly, and the test below checks
AFTER.

THE SEAM IS THE BUNDLE, not a program: a reference across a program
boundary is illegal (`KIR-V002`), so the two disciplines (architecture /
structural / HVAC) will never end up in the same program, and the session
bundle is the only place where the compiler holds links from different
authors at once. A check inside `check_ops` would be vacuous BY
CONSTRUCTION for the very case it is built for.

A FINDING IS EVIDENCE, NOT A VERDICT. Half of this file is precisely
about this: a clash must not change the `verdict`, must not enter
`blocking`, and must not cost a turn. A false refusal of a correct build
is the class `acceptance-broke-on-Cyrillic`, and it costs more than a
missed finding.

Run:
    KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_clash_in_the_receipt.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from kir import env
from unittest import mock

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.clash import hulls as H  # noqa: E402
from kir import clash_bundle as CB  # noqa: E402
from kir import design_check as DC  # noqa: E402
from kir import serving, spec  # noqa: E402
from kir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.live import journal as J  # noqa: E402
from kir.live import verdict as V  # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode

#: 🔴 TWO DIFFERENT ROOTS, AND UNTIL 28.08.2026 THEY WERE ONE (28.08.2026).
#:
#: Here stood `BACKEND = parents[3]` — before the split this was the
#: install root, where OUR code and the HOST'S instruments (`tools/`) lay
#: side by side. After the split the same count gives `/opt`: a directory
#: in which `/opt/kir` simply sits next to other people's trees.
#: `Graph(/opt)` would traverse all of them, and `import capability_map`
#: would look for `/opt/tools/capability_map.py`, which does not exist.
#:
#: There are now two roots, and they are DIFFERENT SUBJECTS:
PACKAGE = Path(__file__).resolve().parents[1]      #: our package `kir/`
#: the HOST's root — optional: KIR stands even without it, and in that
#: case claims about the host's instruments are SKIPPED WITH A REASON,
#: rather than turning red.
HOST_ROOT = Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════
# Material: a building in THREE links, exactly as a multi-agent layout
# must build it — architecture writes the shell, HVAC routes ducts,
# plumbing routes pipe.
# ═════════════════════════════════════════════════════════════════════════

BOX = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
       ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
       ((4000, 0), (4000, 5000))]

_L1 = {"by": "ref", "value": "lvl"}
_L1_BY_NAME = {"by": "name", "value": "Этаж 1"}


def ar_program() -> dict:
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
    ]
    for i, (p0, p1) in enumerate(BOX, start=1):
        ops.append({"op": "create_wall", "id": f"w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": _L1, "height_mm": 3000})
    ops.append({"op": "create_room", "id": "r1", "xy": [6000, 2500],
                "level": _L1, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": "r2", "xy": [2000, 2500],
                "level": _L1, "name": "Лестничная клетка"})
    ops.append({"op": "create_door", "id": "d1", "offset_mm": 2500,
                "host": {"by": "ref", "value": "w5"}})
    ops.append({"op": "create_door", "id": "entrance", "offset_mm": 2000,
                "host": {"by": "ref", "value": "w1"}})
    ops.append({"op": "create_window", "id": "win", "offset_mm": 2500,
                "host": {"by": "ref", "value": "w2"}})
    return {"ir_version": "1.0", "ops": ops}


def ov_program(duct_id: str = "duct1") -> dict:
    """HVAC: a trunk line along the building and a branch across it —
    they INTERSECT."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_duct", "id": duct_id,
         "p0_mm": [200, 1000, 2700], "p1_mm": [7800, 1000, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 400},
        {"op": "create_duct", "id": "duct2",
         "p0_mm": [4000, 200, 2700], "p1_mm": [4000, 4800, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 300},
    ]}


def touching_ducts_program() -> dict:
    """Two ducts standing FLUSH against each other: axes 350 mm apart,
    radii 200 and 150. The runs touching is exactly the case for which
    the rule is REFUSED: the clearance between systems is regulated, and
    the program does not express its magnitude."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_duct", "id": "near1",
         "p0_mm": [5000, 1000, 2700], "p1_mm": [7800, 1000, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 400},
        {"op": "create_duct", "id": "near2",
         "p0_mm": [5000, 1350, 2700], "p1_mm": [7800, 1350, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 300},
    ]}


def grid_programs(programs: int = 3, per: int = 8,
                  span: float = 60_000.0) -> list[dict]:
    """A grid of ducts across SEVERAL LEGITIMATE programs: the author's
    budget is 20 operations per program (`MAX_OPS_PER_PROGRAM`), and
    working around it in the test would mean testing a door that does not
    exist."""
    out: list[dict] = []
    total = programs * per
    for index in range(programs):
        ops = []
        for j in range(per):
            k = index * per + j + 1
            t = k * span / (total + 1)
            if k % 2:
                p0, p1 = [0.0, t, 2700.0], [span, t, 2700.0]
            else:
                p0, p1 = [t, 0.0, 2700.0], [t, span, 2700.0]
            ops.append({"op": "create_duct", "id": f"d{k}", "p0_mm": p0,
                        "p1_mm": p1, "level": _L1_BY_NAME,
                        "diameter_mm": 400})
        out.append({"ir_version": "1.0", "ops": ops})
    return out


def vk_program() -> dict:
    """Plumbing: a pipe with a declared diameter — and it is NOMINAL."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_pipe", "id": "pipe1",
         "p0_mm": [200, 3000, 2500], "p1_mm": [7800, 3000, 2500],
         "level": _L1_BY_NAME, "diameter_mm": 100},
    ]}


class _Door(unittest.TestCase):
    """The full prod door: gate open, device is admin, bridge
    substituted."""

    def setUp(self) -> None:
        # 🔴 EVERYTHING IS CLEANED UP THROUGH `addCleanup`, NOT THROUGH
        # `tearDown` (28.08.2026).
        #
        # THE MEASUREMENT THAT PAID FOR THIS FIX: fifteen "test left the
        # process environment behind it" ERRORS, and not one was about
        # its own subject. `enter_kir_mode` below issues a LEGITIMATE
        # skip when the host has not set up the `llm.turn_context` port —
        # and `unittest`, when `setUp` fails (a skip included), **never
        # calls `tearDown` at all**. Three variables stayed set, the
        # environment guard (`conftest.py`) saw them on the NEXT test and
        # blamed it.
        #
        # That is, an honest skip turned into a mess, and the mess into
        # someone else's red. `addCleanup` registers AT THE MOMENT it is
        # set up and always fires, no matter how many steps of `setUp`
        # managed to run.
        self.DEVICE = serving.ADMIN_DEVICE
        self._set("KUKAI_KIR_TOOL", "stage2")
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=self.DEVICE)
        self._device.start()
        self.addCleanup(self._device.stop)
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acc = tempfile.TemporaryDirectory()
        self.addCleanup(self._acc.cleanup)
        self._set("KIR_ACCEPTANCE_EVIDENCE_DIR", self._acc.name)
        self._feed = tempfile.TemporaryDirectory()
        self.addCleanup(self._feed.cleanup)
        self._set("KIR_WITNESS_PATH", os.path.join(self._feed.name, "w.jsonl"))
        CB._CACHE.clear()
        J.reset()
        self.addCleanup(J.reset)
        self.addCleanup(CB._CACHE.clear)
        # THE GATE'S THIRD CONDITION (13.08): KIR mode is set EXPLICITLY.
        # It stands LAST deliberately: it can skip the test, and
        # everything above it has already been registered for cleanup by
        # this point.
        enter_kir_mode(self)

    def _set(self, name: str, value: str | None) -> None:
        """Set the variable and IMMEDIATELY register its restoration in
        cleanup.

        What is restored is the value FOUND, including its absence: a
        test that deletes a key that existed before it breaks every test
        that follows — this form has already been paid for by the tree
        (see `test_example_from_corpus._call`).
        """
        previous = os.environ.get(name)

        def restore() -> None:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous

        self.addCleanup(restore)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def send(self, program: dict) -> dict:
        state: dict = {}

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            acceptance = state.get("acceptance")
            if acceptance is None:
                acceptance = state["acceptance"] = PassingAcceptanceBridge(
                    program, bulk=False)

            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        async def go():
            with mock.patch.object(serving, "_run_declarative",
                                   side_effect=fake_exec):
                return await serving.handle_revit_ir(
                    {"program": program}, self.llm, bridge_callback=None)

        return _run(go())

    def build(self, programs) -> dict:
        last: dict = {}
        for program in programs:
            last = self.send(program)
        return last


# ═════════════════════════════════════════════════════════════════════════
# 1. A CLOSED TABLE: NOT ONE OPERATION FALLS OUT SILENTLY
# ═════════════════════════════════════════════════════════════════════════

class TheTableIsClosed(unittest.TestCase):

    def test_every_registered_op_leaves_the_table_with_one_outcome(self) -> None:
        """The same law as `hulls.KIND_TABLE`. A new operation that adds
        bodies to the building must either receive a category, or name
        the reason it has no body — otherwise the search silently loses
        elements, while the report remains "sound"."""
        # TWO OUTCOMES, AND THEY ARE ASKED FOR, NOT DECLARED (11.08.2026).
        # Here stood `set(CB.OP_CATEGORY) | set(CB.OP_NO_BODY)` — a shadow
        # table against the registry. It was removed, the test failed
        # with an `AttributeError`, and THE LAW STOPPED BEING ENFORCED:
        # exactly then two operations silently fell out of the table
        # (`create_space`, `create_curtain_grid_line` — both named in
        # `OP_NO_BODY` when this guard was revived).
        answered = {name for name in CB.body_making_ops()
                    if CB.op_categories(name)}
        covered = answered | set(CB.OP_NO_BODY)
        self.assertEqual(covered, set(spec.OPS),
                         f"вне таблицы: {sorted(set(spec.OPS) - covered)}; "
                         f"лишние: {sorted(covered - set(spec.OPS))}")

    def test_having_a_category_and_having_a_body_are_independent(self) -> None:
        """A CHECK THAT COULD NOT FAIL WAS REPLACED WITH ONE THAT CAN
        (11.08.2026, and the finding is not mine — the lead brought it as
        a red test).

        Here stood `assertEqual(answered & set(CB.OP_NO_BODY), set())`,
        where `answered` was taken from `body_making_ops()`, and
        `body_making_ops()` IS `OPS − OP_NO_BODY`. The intersection is
        empty BY CONSTRUCTION: the assertion could not fail under any
        state of the code. I replaced the dead check with a failable one
        in the same commit whose message is about guards that could not
        fire. A check that cannot fail is WORSE than a missing one: it is
        counted in the suite.

        A NON-EMPTY ANSWER, taken over the WHOLE registry rather than a
        pre-filtered set: `create_face_wall`. A wall on a mass face IS a
        wall (`OST_Walls` — the category is known exactly), and has no
        hull: `FaceWall` is not `Wall` (CS0029 on all six) and has no
        `LocationCurve` at all. Two magnitudes, and they are independent:

            `category_of`  -> where the result ends up in Revit
            `OP_NO_BODY`   -> whether we can build a hull

        One of 69 — and therefore the only one on which substituting one
        magnitude for the other becomes visible. Its mirror is
        `create_curtain_grid_line`: there the category WAS DECLARED by
        the `REGISTRY_GAPS` row, in a place where the body table rejected
        it. The same independence from the two sides.

        The list is closed: a new op that has no body and has a category
        must be entered here BY DECISION, rather than arrive silently.
        """
        both = {name for name in spec.OPS
                if name in CB.OP_NO_BODY and CB.op_categories(name)}
        self.assertEqual(
            both, {"create_face_wall"},
            "изменился состав опов, у которых категория известна, а тела нет. "
            "Это не ошибка сама по себе — но это РЕШЕНИЕ: припишите причину в "
            "`OP_NO_BODY` и назовите оп здесь")
        self.assertEqual(CB.op_categories("create_face_wall"), ("OST_Walls",))
        self.assertIn("LocationCurve", CB.OP_NO_BODY["create_face_wall"])

    def test_every_category_named_here_exists_in_the_closed_hull_table(self) -> None:
        """A category not present in the package's table would go into
        `kind_outside_table` — that is, into a quiet skip with a pretty
        name."""
        # THREE DEAD REFERENCES, NOT ONE (measurement of 11.08.2026).
        # Besides the removed `OP_CATEGORY`, this test read
        # `_column_category` and `_directshape_category` — local
        # resolvers, removed TOGETHER WITH the table: the op's
        # enumeration is now parsed by the registry itself
        # (`spec.op_result_categories`), and `op_categories` iterates it
        # in full. So both rows were not replaced but REMOVED: their
        # answer is contained in the first row by construction, and
        # repeating it would mean setting up a third copy of the same
        # relation.
        named = {c for name in CB.body_making_ops()
                 for c in CB.op_categories(name)}
        self.assertLessEqual(
            {"OST_StructuralColumns", "OST_Columns", "OST_Furniture",
             "OST_GenericModel", "OST_SpecialityEquipment"}, named,
            "перечисление опа перестало разбираться — ответ реестра сузился")
        missing = sorted(c for c in named if c not in H.KIND_TABLE)
        self.assertEqual(missing, [], missing)

    def test_the_section_parameters_are_the_ones_the_emitter_writes(self) -> None:
        """The number is placed under the PARAMETER'S NAME, and the
        package's closed table, not this module, judges whether reading
        it is legitimate. So the name must be the same one the emitter
        writes, and must be known to the table."""
        for op_name, param in CB.SECTION_PARAM_BY_OP.items():
            self.assertIn(param, H.ALL_SECTION_PARAM_NAMES, op_name)
            categories = CB.op_categories(op_name)
            self.assertTrue(categories, op_name)
            for category in categories:
                self.assertIn(param, H.SECTION_RULES[category]["round"],
                              op_name)

    def test_the_bundle_address_is_the_same_one_the_verdict_uses(self) -> None:
        """A clash finding and a verdict finding must lead to ONE line of
        the script: two different addresses for one operation are two
        rounds of fixing."""
        for position, oid in ((1, "wall3"), (7, "duct1")):
            self.assertEqual(CB.bundle_oid(position, oid),
                             DC._bundle_oid(position, oid))


# ═════════════════════════════════════════════════════════════════════════
# 2. WHAT IS ABSENT REMAINS ABSENT
# ═════════════════════════════════════════════════════════════════════════

class AbsentStaysAbsent(_Door):

    def test_the_flag_is_off_by_default(self) -> None:
        self._set("KUKAI_IR_CLASH", None)
        self.assertFalse(CB.clash_enabled())
        self.assertIsNone(CB.bundle_clash_report([{"ops": []}]))

    def test_with_the_flag_off_the_receipt_is_the_one_from_before(self) -> None:
        """PROOF OF INVARIANCE. The same building, two runs. A disabled
        flag adds not a single new key; an enabled one APPENDS text at
        the tail and does not touch a byte before it."""
        self._set("KUKAI_IR_CLASH", None)
        off = self.build([ar_program(), ov_program(), vk_program()])["building"]
        self.assertNotIn("clash", off, sorted(off))

        J.reset()
        CB._CACHE.clear()
        self._set("KUKAI_IR_CLASH", "1")
        on = self.build([ar_program(), ov_program(), vk_program()])["building"]

        self.assertEqual(set(on) - set(off), {"clash"}, sorted(on))
        for field in sorted(off):
            # `receipt_chars` is excluded for the SAME REASON as
            # `message_ru`: it is its length, a function of the excluded
            # field. Checking a derived value while excluding the
            # original is checking the same thing under a different
            # name. The field travels under both positions of the flag as
            # of 13.08: an instrument that answers in only one of two
            # configurations covers part of the range.
            if field in ("message_ru", "receipt_chars"):
                continue
            self.assertEqual(on[field], off[field], field)
        self.assertIn("receipt_chars", off,
                      "размер поля обязан называться и без клеша")
        self.assertEqual(off["receipt_chars"], len(off["message_ru"]))
        self.assertEqual(on["receipt_chars"], len(on["message_ru"]))
        self.assertGreater(on["receipt_chars"], off["receipt_chars"],
                           "находки дописаны, а число о размере не выросло")
        self.assertTrue(on["message_ru"].startswith(off["message_ru"]),
                        "текст вердикта сдвинулся, а не дописался")

    def test_a_broken_check_never_costs_the_turn(self) -> None:
        """A check that failed internally must SAY so and not touch the
        verdict. Silence would read as "no clashes."

        🔴 WHAT IS CHECKED IS INVARIANCE, NOT A SPECIFIC WORD (fix of
        22.08.2026). Here stood `verdict == "pass"`, and this was TRUE BY
        COINCIDENCE: the fixture has no staircase, and the fix to the
        empty-precondition on the same day (23 false BLOCKING on MNVNK)
        moved HAB001/HAB010 into "mandatory not evaluated," and the
        verdict became `not_evaluated`. The test's subject did not
        change by a single word from this: it is about the fact that a
        BROKEN CLASH CHECK does not change the verdict. So that is
        exactly how we ask — by comparison with a healthy run.
        """
        self._set("KUKAI_IR_CLASH", "1")
        healthy = self.build([ar_program(), ov_program()])["building"]
        with mock.patch.object(CB, "_report", side_effect=RuntimeError("бум")):
            block = self.build([ar_program(), ov_program()])["building"]
        self.assertEqual(block["clash"]["status"], "unavailable")
        self.assertIn("не смотрели", block["clash"]["message_ru"])
        self.assertEqual(block["verdict"], healthy["verdict"], block)
        self.assertEqual(block["blocking"], healthy["blocking"], block)
        self.assertEqual(block["rules_evaluated"], healthy["rules_evaluated"])


# ═════════════════════════════════════════════════════════════════════════
# 3. THE FINDING EXISTS, AND IT IS EVIDENCE
# ═════════════════════════════════════════════════════════════════════════

class TheFindingIsEvidence(_Door):

    def setUp(self) -> None:
        super().setUp()
        self._set("KUKAI_IR_CLASH", "1")

    def test_two_authors_crossing_in_one_building_are_found_by_name(self) -> None:
        """THE MAIN CLAIM. A pair of elements and a MEASURED
        penetration — from different programs, that is, from different
        authors."""
        block = self.build([ar_program(), ov_program()])["building"]
        clash = block["clash"]
        self.assertEqual(clash["status"], "ok", clash)
        pairs = {(row["a_element_id"], row["b_element_id"])
                 for row in clash["findings"]}
        self.assertIn(("p2/duct1", "p2/duct2"), pairs, clash["findings"])
        row = next(r for r in clash["findings"]
                   if (r["a_element_id"], r["b_element_id"])
                   == ("p2/duct1", "p2/duct2"))
        self.assertEqual(row["relation"], "overlap", row)
        self.assertAlmostEqual(row["penetration_mm"], 350.0, places=3)

    def test_the_same_element_declared_twice_reads_as_a_duplicate(self) -> None:
        """A multi-agent case in its pure form: a second author declared
        the same duct. The bundle names this a separate KIND — it is
        fixed by deletion, not by moving apart."""
        block = self.build([ar_program(), ov_program(), ov_program()])["building"]
        clash = block["clash"]
        self.assertGreaterEqual(clash["duplicates"], 1, clash)
        dup = next(r for r in clash["findings"]
                   if r["pair_kind"] == "coincident_duplicate")
        self.assertEqual({dup["a_element_id"], dup["b_element_id"]},
                         {"p2/duct1", "p3/duct1"}, dup)
        # THE TEXT MUST AGREE WITH THE TIER, NOT REPEAT THE FORMER
        # WORDING (11.08.2026). Here stood the literal "IN THE SAME
        # PLACE" — a statement OF FACT. The wave replaced it with
        # "POSSIBLE DUPLICATE … not proven: geometry verdict possible,"
        # and this is a correct sentence FOR THE `possible` VERDICT. What
        # is asserted, therefore, is the link, not the string.
        self.assertEqual(dup["rung"], "look", dup)
        self.assertIn("НЕ доказано", dup["text"])
        self.assertIn("ВОЗМОЖНЫЙ ДУБЛИКАТ", dup["text"])

    def test_a_clash_never_moves_the_verdict(self) -> None:
        """THE LAW. A building with a clash and a building without one
        must receive ONE AND THE SAME verdict: a finding travels as
        evidence, not as a refusal. A false refusal of a correct build is
        the class `acceptance-broke-on-Cyrillic`."""
        dirty = self.build([ar_program(), ov_program()])["building"]
        J.reset()
        CB._CACHE.clear()
        clean = self.build([ar_program()])["building"]
        self.assertGreater(dirty["clash"]["total_findings"], 0)
        self.assertEqual(dirty["clash"]["status"], "ok")
        self.assertEqual((dirty["verdict"], dirty["blocking"]),
                         (clean["verdict"], clean["blocking"]))
        self.assertNotIn("clash", dirty["blocking"])

    def test_the_receipt_says_what_stayed_out_of_the_search(self) -> None:
        """NOTHING SILENTLY. Walls do not take part in the search — the
        program does not express their thickness; this must be NAMED by
        a number and a category, otherwise "no findings" reads as "no
        clashes."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        self.assertFalse(clash["search_complete"], clash)
        self.assertEqual(clash["without_body_by_category"].get("OST_Walls"), 5,
                         clash["without_body_by_category"])
        text = clash["message_ru"]
        self.assertIn("БЕЗ ТЕЛА", text)
        self.assertIn("ПО ПОСТРОЕНИЮ", text)

    def test_a_nominal_diameter_does_not_become_a_body(self) -> None:
        """R3's reds, carried over into the compiler. `create_pipe.diameter_mm`
        is emitted into `RBS_PIPE_DIAMETER_PARAM` — this is the NOMINAL,
        and the capsule built from it does not contain the body (DN100:
        50.0 against an outer 57.15). The pipe therefore stays without a
        hull, and this is said in words.

        The test holds the boundary both ways: it will fail both if the
        nominal starts being used silently, and if it stops being talked
        about.

        WHAT IS PINNED IS THE CLAIM, NOT THE WORDING (fixed
        13.08.2026). It used to say `assertIn("НОМИНАЛЬНЫЙ ДИАМЕТР",
        ...)`, and text that said THE SAME THING in other words ("NOMINAL
        ONLY: 1 — the capsule built from the nominal does not contain the
        body") turned the test red. The fact had not moved: both the
        former pair of numbers (50.0 against 57.15) and the current one
        (100 against 114.3) are about the same pipe, the first radii, the
        second diameters; in `extract.py` they stand side by side and
        agree. What diverged was the WORDING.

        SPLIT INTO TWO HALVES, AND THEY DIFFER IN STRENGTH — stated
        outright, because identically-looking `assert`s inspire identical
        trust.

        "The nominal started being used silently" is pinned
        STRUCTURALLY and reliably: should the capsule start counting as a
        body, the pipe would stop being listed under
        `without_body_by_category`, and the counter would drop to zero.

        "It stopped being talked about" is pinned BY TEXT, and there is
        nothing better here: the number `nominal_only_total`, which this
        line prints, IS NOT IN THE RECEIPT — `census` does not enter the
        block at all, `type_sections` carries only `"read"`. That is, the
        value exists only as prose, and there is nothing to ask besides
        the prose. The pin is therefore taken on the ROOT "NOMINAL" plus
        the requirement that a positive number stand in the same line:
        this catches the disappearance of the claim and survives a
        wording edit, but it remains a pin by appearance, and it must not
        be called structural.

        WHAT FOLLOWS FROM THIS FOR THE OWNER OF `clash_bundle`: a number
        that lives only in a sentence is read by nothing but an eye.
        Bring `nominal_only_total` out into the block — and the second
        half of this test will have something to ask."""
        clash = self.build([ar_program(), vk_program()])["building"]["clash"]
        self.assertEqual(clash["without_body_by_category"].get("OST_PipeCurves"),
                         1, clash["without_body_by_category"])
        self.assertRegex(
            clash["message_ru"], r"НОМИНАЛ\w*[^\n]*?[1-9]\d*",
            "об оболочке по номиналу перестали говорить числом")

    def test_a_building_without_a_single_body_says_so(self) -> None:
        """A VACUUM MUST BE NAMED. A building made only of walls yields
        not a single hull — and "0 findings" here means "did not
        look"."""
        clash = self.build([ar_program()])["building"]["clash"]
        self.assertEqual(clash["bodies"], 0, clash)
        self.assertEqual(clash["total_findings"], 0)
        self.assertIn("НИ ОДНОГО ТЕЛА", clash["message_ru"])


# ═════════════════════════════════════════════════════════════════════════
# 3b. THE FINDING BECAME A JUDGMENT — ENTIRELY THROUGH THE PROD DOOR
#
# The measurement that gave rise to this section (09.08, `snowdon_plumb_v5`):
# 99 pairs, 66 of them at the top tier, and all 66 are slabs of one floor,
# clashing ONLY in our own coarsening. The reader discards pairs as a
# check's result.
# ═════════════════════════════════════════════════════════════════════════

class ThePairBecameAJudgement(_Door):

    def setUp(self) -> None:
        super().setUp()
        self._set("KUKAI_IR_CLASH", "1")

    def test_two_crossing_ducts_are_a_collision_with_a_move_to_make(self) -> None:
        """WHAT with WHAT, BY HOW MUCH, HOW CONFIDENT, and WHAT TO DO — in one
        line, and the move is derived from the PROGRAM, not invented."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        row = next(r for r in clash["findings"]
                   if (r["a_element_id"], r["b_element_id"])
                   == ("p2/duct1", "p2/duct2"))
        self.assertEqual(row["kind"], "collision")
        self.assertEqual(row["rule_id"], "run_meets_run")
        # THE RUNG FOLLOWS THE VERDICT, AND THAT IS EXACTLY WHAT GETS CHECKED (11.08.2026).
        # Here stood the literals `rung == "fix"` and `proven is True`. The
        # 11.08 wave tied the rung to the verdict, the literals turned red,
        # and the temptation was to put the line back. The measurement says
        # the opposite: this pair's verdict is `possible`, meaning `fix` was
        # a rung that did NOT FOLLOW the verdict, and what turned red was the
        # assertion, not the behavior.
        self._assert_rung_follows_verdict(row)
        self._assert_next_move_follows_rung(row)
        self.assertTrue(row["why"], row)
        self.assertIn("СТОЛКНОВЕНИЕ", row["text"])

    #: The only mapping asserted here. Rung strings and finding texts may
    #: change; a mismatch between the rung and the evidentiary strength may
    #: not. Understating a supported assertion is as much a defect as
    #: overstating it: an instrument that screams at everything teaches
    #: itself to be ignored.
    _RUNG_FOR_PROVEN = {True: ("fix", "agree"), False: ("look",),
                        None: ("look", "nothing", "note")}

    def _assert_next_move_follows_rung(self, row: dict) -> None:
        """THE MOVE ALSO FOLLOWS THE RUNG, and this is not a relaxation.

        Here stood `assertIn("create_duct p2/duct1", next_move)` — that is,
        a requirement to NAME THE OPERATION TO SHIFT. At the `look` rung such
        a move is forbidden by the very definition of the rung («разрушающее
        указание по такой находке ЗАПРЕЩЕНО»), and issuing it would mean
        advising a fix for a finding that our own coarsening might have
        created.

        The test's original intent — «ход ВЫВЕДЕН из программы, а не
        придуман» — is preserved in full: at `look`, the derived move is
        «добыть недостающее свидетельство», and it must name WHAT is
        missing.
        """
        move = row["next_move"]
        self.assertTrue(move, row)
        if row["rung"] == "fix":
            self.assertIn(row["a_element_id"], move, row)
        else:
            self.assertIn("inner-evidence", move, row)
            self.assertIn("нельзя", move, row)

    def _assert_rung_follows_verdict(self, row: dict) -> None:
        allowed = self._RUNG_FOR_PROVEN[row["proven"]]
        self.assertIn(
            row["rung"], allowed,
            f"ступень {row['rung']!r} не следует за доказательностью "
            f"{row['proven']!r}: {row.get('text')}")

    def test_the_top_rung_is_unreachable_in_production_and_says_so(self) -> None:
        """WHY EVERY FINDING IS «СМОТРЕТЬ», AND THIS IS NOT A CAUTION
        SETTING (measured 11.08.2026).

        `_rung` returns `fix` only when `proven is True`, and
        `_physical_overlap_proof` returns `True` only under the combination
        `verdict == "confirmed"` + a certified internal overlap.
        `detect.VERDICT_REQUIREMENTS` states this in its own words:
        «production builders do not mint inner certificates yet». That is, on
        ANY production snapshot the top rung is unreachable BY
        CONSTRUCTION, and two intersecting pipes — a clash under any reading
        — come out as `look`.

        THIS IS AN UPSTREAM DEFECT, NOT A WORDING ISSUE. The detector
        UNDER-declares where it could decide precisely, because no
        production shell source carries an internal certificate. The test
        keeps the fact in plain view: as long as `VERDICT_REQUIREMENTS` calls
        `confirmed` unreachable, «всё на ступени СМОТРЕТЬ» is a consequence
        of that, not a choice of caution, and it is the certificates that
        need fixing, not the wording.

        WHAT IT DOES NOT COVER: it says nothing about whether the
        `proven -> ступень` mapping is CORRECT. It asserts only that the top
        rung is unreachable today and that the reason is named in the code.
        """
        from kir.clash import detect as _detect
        self.assertIn("confirmed", _detect.VERDICT_REQUIREMENTS)
        self.assertIn("do not mint inner certificates",
                      _detect.VERDICT_REQUIREMENTS["confirmed"])

    def test_the_receipt_counts_disputes_filtered_and_unseen_apart(self) -> None:
        """THREE DIFFERENT FACTS AND THREE DIFFERENT NUMBERS. A pair cleared
        by a rule, a pair that was never seen at all, and a dispute —
        collapsing them into one «находок N» means lying twice."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        for key in ("disputes", "filtered", "unjudged", "without_body"):
            self.assertIn(key, clash, sorted(clash))
        self.assertEqual(
            clash["disputes"] + clash["filtered"] + clash["unjudged"],
            clash["total_findings"], clash)
        self.assertGreater(clash["without_body"], 0, clash)
        text = clash["message_ru"]
        self.assertIn("СПОРОВ", text)
        self.assertIn("НЕ ВИДЕЛИ", text)

    def test_a_refused_rule_names_itself_and_its_reason_in_the_receipt(self) -> None:
        """NOTHING SILENTLY, AND ESPECIALLY NOT A REFUSAL. Two ducts flush
        against each other — a pair this layer REFUSES to judge: the
        code-mandated clearance between networks is not expressed by the
        program. A refusal must name itself with a number and a
        justification."""
        clash = self.build([ar_program(),
                            touching_ducts_program()])["building"]["clash"]
        self.assertEqual(clash["refused_by_rule"],
                         {"run_meets_run_clearance": 1}, clash)
        self.assertIn("run_meets_run_clearance", clash["rules"])
        text = clash["message_ru"]
        self.assertIn("ПРАВИЛО ОТКАЗАНО", text)
        self.assertIn("зазор", text)

    def test_a_hundred_disputes_still_fit_and_each_names_its_move(self) -> None:
        """A grid of 24 ducts: 144 pairs, and every one of them is a genuine
        dispute. The judgement layer is NOT obligated to clear anything when
        there is nothing to clear."""
        clash = self.build([ar_program()] + grid_programs())["building"]["clash"]
        self.assertEqual(clash["disputes"], clash["total_findings"])
        self.assertEqual(clash["by_kind"], {"collision": 144}, clash["by_kind"])
        # THE SUMMARY FOLLOWS THE VERDICTS, not an expected number: on a
        # production snapshot no one issues internal certificates, so
        # `proven` is never True and the top rung is unreachable.
        self.assertEqual(set(clash["by_rung"]), {"look"}, clash["by_rung"])
        self.assertEqual(sum(clash["by_rung"].values()), 144)
        for row in clash["findings"]:
            self._assert_next_move_follows_rung(row)
        self.assertLessEqual(len(clash["message_ru"]), CB._TEXT_CAP)

    def test_the_text_cap_cuts_the_middle_and_never_the_completeness(self) -> None:
        """THE CAP CUTS THE MIDDLE. Before this wave, trimming went BY THE
        TAIL, and the first thing to go under the knife was the «БЕЗ ТЕЛА»
        census — the very thing that has no right to be absent from the
        receipt. The cap is pinned deliberately here: the value itself is a
        budget decision, while the law of trimming does not depend on it."""
        with mock.patch.object(CB, "_TEXT_CAP", 900):
            clash = self.build([ar_program()]
                               + grid_programs())["building"]["clash"]
        text = clash["message_ru"]
        self.assertTrue(text.startswith("КОЛЛИЗИИ"), text)
        self.assertIn("БЕЗ ТЕЛА", text)
        self.assertIn("ПО ПОСТРОЕНИЮ", text)
        self.assertIn("область `", text)
        self.assertIn("обрезан", text)
        # The first judgement, together with its move, ALWAYS goes through:
        # «СПОРОВ N» without a single shown line is a report the reader will
        # throw away, and a discarded report is worse than none at all.
        self.assertIn("[СМОТРЕТЬ]", text)
        self.assertIn("ХОД:", text)


# ═════════════════════════════════════════════════════════════════════════
# 4. CAPS ARE NAMED BY A NUMBER, THEY DO NOT SILENTLY DROP THE CHECK
# ═════════════════════════════════════════════════════════════════════════

def _dense_ducts(count: int, span: float = 60_000.0) -> list[dict]:
    """A grid: every other duct crosswise — EVERY pair intersects. The worst
    case of the narrow phase, and it must run into the cap, not into the
    clock."""
    ops = []
    for k in range(1, count + 1):
        t = k * span / count
        if k % 2:
            p0, p1 = [0.0, t, 2700.0], [span, t, 2700.0]
        else:
            p0, p1 = [t, 0.0, 2700.0], [t, span, 2700.0]
        ops.append({"op": "create_duct", "id": f"d{k}", "p0_mm": p0,
                    "p1_mm": p1, "level": _L1_BY_NAME, "diameter_mm": 400})
    return [{"ops": ops}]


class TheCapsAreNamed(unittest.TestCase):

    def setUp(self) -> None:
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        for name in ("KUKAI_IR_CLASH_MAX_PAIRS", "KUKAI_IR_CLASH_MAX_OFFERS",
                     "KUKAI_IR_CLASH_MAX_BODIES"):
            os.environ.pop(name, None)
        CB._CACHE.clear()

    def test_a_dense_building_refuses_by_number_instead_of_running_for_ever(self) -> None:
        """320 ducts, every one against every other — 25,918 pairs and eight
        seconds of the narrow phase (measured 09.08). The check must REFUSE,
        naming the number, rather than hand back «находок 0» or leave the
        move hanging."""
        block = CB.bundle_clash_report(_dense_ducts(320))
        self.assertEqual(block["status"], "over_cap", block)
        self.assertGreater(block["work"], block["cap"])
        self.assertIn("не смотрели", block["message_ru"])
        self.assertNotIn("находок 0", block["message_ru"])

    def test_both_caps_can_fire_and_each_names_its_own_phase(self) -> None:
        """Two caps measure two DIFFERENT costs (the wide phase — µs per
        offer, the narrow phase — fractions of a ms per candidate). A single
        cap for both questions would be choosing between a false refusal and
        an hour of runtime."""
        os.environ["KUKAI_IR_CLASH_MAX_OFFERS"] = "1000"
        CB._CACHE.clear()
        broad = CB.bundle_clash_report(_dense_ducts(120))
        self.assertEqual((broad["status"], broad["phase"]),
                         ("over_cap", "широкая фаза"), broad)

        os.environ["KUKAI_IR_CLASH_MAX_OFFERS"] = "10000000"
        os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "64"
        CB._CACHE.clear()
        narrow = CB.bundle_clash_report(_dense_ducts(120))
        self.assertEqual((narrow["status"], narrow["phase"]),
                         ("over_cap", "узкая фаза"), narrow)

    def test_the_body_cap_is_named_too(self) -> None:
        os.environ["KUKAI_IR_CLASH_MAX_BODIES"] = "16"
        CB._CACHE.clear()
        block = CB.bundle_clash_report(_dense_ducts(64))
        self.assertEqual(block["status"], "over_cap", block)
        self.assertIn("не смотрели", block["message_ru"])

    def test_a_sparse_building_at_the_judges_own_cap_still_runs(self) -> None:
        """The other side of it: a cap that refuses a SOUND building is a
        false refusal. 1,200 operations (the judge's own cap), a plausible
        floor layout — it must be counted."""
        ops = []
        for k in range(1, 1_201):
            floor = k % 8
            row = (k // 8) % 12
            x0 = 1_000.0 + ((k // 96) % 5) * 9_000.0
            y = 1_000.0 + row * 2_500.0
            z = 2_700.0 + floor * 3_200.0
            ops.append({"op": "create_duct", "id": f"d{k}",
                        "p0_mm": [x0, y, z], "p1_mm": [x0 + 8_000.0, y, z],
                        "level": {"by": "name", "value": f"Этаж {floor}"},
                        "diameter_mm": 400})
        pack = [{"ops": ops[i:i + 20]} for i in range(0, len(ops), 20)]
        block = CB.bundle_clash_report(pack)
        self.assertEqual(block["status"], "ok", block)
        self.assertEqual(block["bodies"], 1_200)

    def test_the_same_bundle_twice_is_paid_for_once(self) -> None:
        """A cache keyed on the batch's CANONICAL BYTES — the same trick as
        for schema loading. Measured: 116 ms cold, 0.3 ms warm."""
        pack = _dense_ducts(40)
        CB._CACHE.clear()
        first = time.perf_counter()
        cold = CB.bundle_clash_report(pack)
        first = time.perf_counter() - first
        second = time.perf_counter()
        warm = CB.bundle_clash_report(pack)
        second = time.perf_counter() - second
        self.assertEqual(cold["total_findings"], warm["total_findings"])
        self.assertLess(second, first)


# ═════════════════════════════════════════════════════════════════════════
# 5. REACHABILITY — BY INSTRUMENT, NOT BY GREP
# ═════════════════════════════════════════════════════════════════════════

class TheDetectorIsReachable(unittest.TestCase):

    def test_the_clash_package_is_live_from_a_real_entry_point(self) -> None:
        """Before this wave, `graph.live()` contained NOT A SINGLE
        `kir.clash.*` module: the package was reachable only by hand, via the
        CLI."""
        from kir.instruments import capability_graph  # noqa: WPS433
        from kir.tests.host_entry_points import live_or_named_skip  # noqa: WPS433

        # The instrument moved INTO THE PACKAGE at the split — it no longer
        # needs `sys.path` or a `tests` directory nearby: it is imported as a
        # module.
        graph = capability_graph.Graph(PACKAGE.parent)

        # 🔴 REACHABILITY IS A CLAIM ABOUT THE HOST, NOT ABOUT THE LANGUAGE (28.08.2026).
        # Entry points start with `kukai.main` — a PRODUCT unit. In a
        # standalone KIR there is no such module, `reachable` honestly
        # returns empty, and «kir.clash.detect не найден» would read as
        # «пакет мёртв», even though it is not the package that is dead, but
        # the question: there is no one to ask.
        # The skip IS NAMED — a silently passed check reads as passed.
        # Names have been declared by the TEST since 01.09.2026: the package
        # does not hold a map of the product.
        live = live_or_named_skip(self, graph)
        for module in ("kir.clash.detect", "kir.clash.hulls",
                       "kir.clash.geom", "kir.clash.snapshot",
                       "kir.clash.review"):
            self.assertIn(module, live, sorted(
                m for m in live if m.startswith("kir.clash")))

    def test_the_gate_is_wired_and_not_on_the_shelf(self) -> None:
        """A flag that the instrument reports as «на складе» is dark BY
        CONSTRUCTION: turning it on is pointless. What is checked is THE SAME
        instrument the operator uses to measure this, not a bespoke walk of
        our own."""
        if not (HOST_ROOT / "tools" / "capability_map.py").is_file():
            self.skipTest(
                f"прибор ХОЗЯИНА (tools/capability_map.py) здесь недоступен: "
                f"{HOST_ROOT} — утверждение о ЕГО карте способностей "
                f"непроверяемо. Назвать корень: KIR_HOST_ROOT")
        sys.path.insert(0, str(HOST_ROOT / "tools"))
        try:
            import capability_map  # noqa: WPS433
            # 🔴 SPECIFICALLY `tools.capability_manifest`, NOT `capability_manifest`.
            # The short name yields a SECOND module object with its own
            # sentinel class, and `isinstance` on it is ALWAYS false: an
            # instrument failure would read as a measurement. Paid for right
            # here, 17.08.2026, in a single run.
            from tools import capability_manifest  # noqa: WPS433

            gates = {row["flag"]: row for row in capability_map._gates()}
        finally:
            if sys.path and sys.path[0] == str(HOST_ROOT / "tools"):
                sys.path.pop(0)
        row = gates.get("KUKAI_IR_CLASH")
        self.assertIsNotNone(row, sorted(gates))
        self.assertEqual(row["gate_fn"], ["clash_enabled"], row)
        # 🔴 THREE OUTCOMES, NOT TWO (correction 17.08.2026, from measurement).
        #
        # The wiring column GOES DARK when the reviewed module's bytes have
        # moved on: that is an instrument failure, not a finding about the
        # clash. The earlier edit read dark as false and turned red with the
        # text «флаг на складе: никто не зовёт» — that is, it blamed the
        # SUBJECT for the state of the OBSERVER. The measurement that day: 20
        # of 47 reviewed modules are waiting on re-review, among them
        # `serving`, `design_check`, and `clash_bundle` itself, and they were
        # fixed by more than one person. The canon forbids signing someone
        # else's edits inside your own file, so darkness is a legitimate
        # state, not a debt owed by the test.
        #
        # A refusal must be DISTINGUISHABLE from «находок нет» and must carry
        # a path back — exactly the form the canon uses to cure a guard with
        # no instrument.
        if not capability_manifest.wiring_answerable(row["wired_into"]):
            self.skipTest(
                "вердикт проводки ТЁМЕН: отревьюенный замок разъехался с "
                "байтами. Это отказ прибора, а не «флаг на складе». Вернуть "
                "колонку: PYTHONPATH=. python tools/capability_relock.py "
                "(--status покажет, что именно двигалось), и подписывать "
                "только то, что прочитано ЦЕЛИКОМ")
        self.assertTrue(row["wired_into"], "флаг на складе: никто не вызывает")
        self.assertTrue(any("[маршрут]" in chain for chain in row["wired_into"]),
                        row["wired_into"])


if __name__ == "__main__":
    unittest.main()
