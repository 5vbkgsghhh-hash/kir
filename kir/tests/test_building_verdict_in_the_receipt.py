"""IN PROD THE VERDICT DID NOT SEE THE BUILDING — ONLY THE LINK.

WHAT WAS MEASURED ON 04.08. The bundle in prod was already being assembled,
and assembled correctly: `live/journal.py` accumulates the session's
programs, `plan_stream._slice_for` returns them NOT GLUED TOGETHER,
`transfer.redeem()` returns `list[list[dict]]`, and
`chat_ws._handle_kir_transfer` runs it through the prod door one at a time.
But this bundle went to the SHOWROOM and the EXECUTOR — the human and Revit.
It never once reached the JUDGE: `design_check.check_bundle` had EXACTLY ONE
prod caller — `course.design_check` inside the sandbox, meaning only when the
model itself figured out to assemble the bundle by hand and ask.

The consequence is named by the number in `test_verdict_takes_kir_ops`: the
body of a two-story building WITHOUT a staircase must be blocked under
HAB010 — yet putting a staircase into it is forbidden (KIR-L002). That means
each link is unfit ON ITS OWN BY CONSTRUCTION, and the only unit about which
the truth can be told is the BUNDLE.

THE SECOND TRAP, FOR WHICH HALF OF THIS FILE EXISTS. A PASS by SATISFACTION
and a PASS by WAIVER read identically. Measurement: the same building,
differing ONLY in the name of the staircase's room — «Лестничная клетка»
gives PASS, 13 rules out of 20, HAB001/HAB010 EVALUATED; «Кладовая» gives
PASS, 11 out of 20, the same two rules WAIVED by the profile and never
spoken at all. Both lines, on a naive reading: "PASS, 0 blocking." A receipt
that does not distinguish these two cases is a beautiful lie, sent to a
place with nothing to check it against.

`engine.run_checker` does not catch this difference and is not obligated to:
a rule waived by the profile exits via `continue` BEFORE being counted in
`mandatory_not_evaluated` (measurement: the list is EMPTY in both cases
above). So the receipt is the one obligated to distinguish them.

Run: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_building_verdict_in_the_receipt.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import serving  # noqa: E402
from kir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.live import journal as J  # noqa: E402
from kir.live import plan_stream as S  # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode
from kir.tests.envtools import подменить_env  # noqa: E402

#: 🔴 THE ROOT INSIDE WHICH THE PACKAGE LIES (28.08.2026). It used to be
#: `parents[3]` — before the split, the install root; after 27.08 the same
#: count gives `/opt`, and the graph would traverse directory neighbors
#: instead of our code.
BACKEND = Path(__file__).resolve().parents[2]


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════
# Material: a two-story building in THREE programs, each within its
# authoring budget
#
# This is exactly how the model must build it: 20 operations per program,
# the staircase as a separate link (KIR-L002), and the level of the second
# program addressed BY NAME — a reference across the program boundary is
# illegal (KIR-V002).
# ═════════════════════════════════════════════════════════════════════════

BOX = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
       ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
       ((4000, 0), (4000, 5000))]


def storey(tag: str, level: dict, core: str, *, first: bool) -> dict:
    ops: list[dict] = []
    if first:
        ops += [{"op": "create_level", "id": "lvl", "elev_mm": 0,
                 "name": "Этаж 1"},
                {"op": "create_level", "id": "lvl2", "elev_mm": 3000,
                 "name": "Этаж 2"}]
    for i, (p0, p1) in enumerate(BOX, start=1):
        ops.append({"op": "create_wall", "id": f"{tag}w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": level, "height_mm": 3000})
    ops.append({"op": "create_room", "id": f"{tag}r", "xy": [6000, 2500],
                "level": level, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": f"{tag}st", "xy": [2000, 2500],
                "level": level, "name": core})
    ops.append({"op": "create_door", "id": f"{tag}d", "offset_mm": 2500,
                "host": {"by": "ref", "value": f"{tag}w5"}})
    ops.append({"op": "create_window", "id": f"{tag}win", "offset_mm": 2500,
                "host": {"by": "ref", "value": f"{tag}w2"}})
    if first:
        ops.append({"op": "create_door", "id": "entrance", "offset_mm": 2000,
                    "host": {"by": "ref", "value": f"{tag}w1"}})
    return {"ir_version": "1.0", "ops": ops}


def stairs() -> dict:
    return {"ir_version": "1.0", "ops": [{
        "op": "create_stairs", "id": "s1", "width_mm": 1200,
        "p0_mm": [2000, 1000], "p1_mm": [2000, 4000],
        "base_level": {"by": "name", "value": "Этаж 1"},
        "top_level": {"by": "name", "value": "Этаж 2"}}]}


def building(core: str = "Лестничная клетка") -> list[dict]:
    return [storey("a", {"by": "ref", "value": "lvl"}, core, first=True),
            storey("b", {"by": "name", "value": "Этаж 2"}, core, first=False),
            stairs()]


class _Door(unittest.TestCase):
    """The full prod door: gate open, device is admin, bridge substituted."""

    DEVICE = None

    def setUp(self) -> None:
        self.DEVICE = serving.ADMIN_DEVICE
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=self.DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acc = tempfile.TemporaryDirectory()
        self._prev_acc = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._acc.name)
        self._feed = tempfile.TemporaryDirectory()
        self._prev_feed = os.environ.get("KIR_WITNESS_PATH")
        подменить_env(self, "KIR_WITNESS_PATH", os.path.join(self._feed.name, "w.jsonl"))
        J.reset()
        # THE GATE'S THIRD CONDITION (13.08): KIR mode is set EXPLICITLY.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        for name, prev in (("KUKAI_KIR_TOOL", self._prev_flag),
                           ("KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_acc),
                           ("KIR_WITNESS_PATH", self._prev_feed)):
            if prev is None:
                os.environ.pop(name, None)
            else:
                подменить_env(self, name, prev)
        self._acc.cleanup()
        self._feed.cleanup()
        J.reset()

    def send(self, program: dict) -> dict:
        """One turn through `handle_revit_ir` — that very prod path."""
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

    def build(self, core: str = "Лестничная клетка") -> dict:
        """Three turns. Returns the receipt of the LAST one — the whole
        building is there."""
        last: dict = {}
        for program in building(core):
            last = self.send(program)
        return last


# ═════════════════════════════════════════════════════════════════════════
# 1. THE BUNDLE REACHES THE JUDGE
# ═════════════════════════════════════════════════════════════════════════

class ThePackReachesTheJudge(_Door):

    def test_the_receipt_carries_a_verdict_about_the_whole_building(self) -> None:
        """THE MAIN CLAIM. Three programs, three turns — and the receipt of
        the third carries a verdict about the BUILDING, not about a link."""
        receipt = self.build()
        block = receipt.get("building")
        self.assertIsNotNone(block, sorted(receipt))
        self.assertEqual(block["programs"], 3, block)
        self.assertEqual(block["verdict"], "pass", block)
        self.assertEqual(block["blocking"], [], block)

    def test_the_pack_verdict_is_not_the_verdict_of_its_last_link(self) -> None:
        """BY THE NUMBERS: the same building, judged as a LINK, is UNFIT.

        The staircase program by itself is one op without a single room:
        HAB000. A body without a staircase is not judged vertically at all.
        A building becomes fit EXACTLY as a bundle, and that is the only
        reason the bundle goes to the judge.

        🔴 THE MECHANISM OF THE SECOND HALF CHANGED ON 22.08.2026, THE LAW
        DID NOT. Here stood `assertIn("HAB010", body.report.blocking)`: a
        body without a staircase was ACCUSED of having a floor hanging
        without a connection to the ground. On a real building (MNVNK) that
        very accusation turned out false twenty-three times over — there are
        24 staircases there, and our own extraction discarded all 24. The
        precondition is fixed: without a single staircase there are no
        vertical edges BY CONSTRUCTION, and "the floor is hanging" is
        indistinguishable from "there is nothing to descend by."

        What is checked, therefore, is the LAW, not the mechanism: a body
        alone is UNFIT, and the reason for this is NAMED. Silence of a
        mandatory rule is not a green light: `mandatory_not_evaluated` holds
        the verdict back from PASS just as reliably as the accusation used
        to.
        """
        from kir import design_check as dc

        alone = dc.check_ops(stairs(), building_id="звено")
        self.assertIn("HAB000", [v.rule_id for v in alone.report.blocking])

        body = dc.check_bundle(building()[:2], building_id="тело")
        verdict = getattr(body.report.verdict, "value", body.report.verdict)
        self.assertNotEqual(verdict, "pass",
                            "тело без лестницы не имеет права быть пригодным")
        self.assertIn("HAB010", body.report.coverage.mandatory_not_evaluated,
                      "правило обязано МОЛЧАТЬ НАЗВАННО и держать вердикт")
        rows = {o.rule_id: o for o in body.report.coverage.outcomes}
        self.assertIn("лестниц в представлении НЕТ НИ ОДНОЙ",
                      rows["HAB010"].reason or "",
                      "причина обязана называть НАШУ пустоту, а не обвинять "
                      "здание")
        # Whereas the bundle as a whole is fit.
        self.assertEqual(self.build()["building"]["verdict"], "pass")

    def test_the_block_names_the_pack_it_judged(self) -> None:
        """A verdict without a denominator is a claim about nothing: how
        many programs and operations were consumed, and how many the
        journal EVICTED, must travel alongside it."""
        block = self.build()["building"]
        self.assertEqual(block["ops"],
                         sum(len(p["ops"]) for p in building()), block)
        self.assertEqual(block["programs_evicted"], 0, block)
        self.assertIn("3 программ", block["message_ru"])

    def test_a_read_only_turn_does_not_grow_the_building(self) -> None:
        """A query does not belong to the building (measurement of 29.07:
        176 reads per 5 writes). A turn that added nothing to the journal
        has no right to print a verdict — otherwise the same verdict would
        repeat for as long as reading continues."""
        self.build()
        receipt = self.send({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]})
        self.assertIsNone(receipt.get("building"), receipt.get("building"))

    def test_only_the_chat_door_stamps_the_verdict(self) -> None:
        """THE ADMIN DOOR STAYS SILENT, AND THIS IS A DECISION, NOT AN
        OVERSIGHT.

        `handle_revit_ir_bulk` is the decompile-reassembly path: the
        measurement of 30.07 on Snowdon Towers — 6 335 ops, 26 programs in
        chunks of 250. The author there is the materializer, not the model,
        there is no reader for the receipt at all, and a verdict on an
        ever-growing bundle would cost time on every chunk. Structurally,
        not by eyeballing: the marker is removed in exactly one function.
        """
        import ast
        import inspect

        source = inspect.getsource(serving)
        tree = ast.parse(source)
        stampers = {node.name for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_stamp_building_verdict"}
        self.assertEqual(stampers, {"handle_revit_ir"}, stampers)

    def test_the_judge_has_a_live_caller_outside_the_sandbox(self) -> None:
        """REACHABILITY IS MEASURED BY AN INSTRUMENT, NOT BY GREP. Before
        04.08, `check_bundle` had exactly one prod caller — `kir.course`,
        meaning the sandbox: the bundle reached the judge only when the model
        assembled it by hand and asked itself."""
        # The instrument moved INTO THE PACKAGE during the split — it no
        # longer needs `sys.path`.
        from kir.instruments import capability_graph  # noqa: WPS433
        from kir.tests.host_entry_points import live_or_named_skip  # noqa: WPS433

        graph = capability_graph.Graph(BACKEND)
        # 🔴 REACHABILITY OF "LIVE" RESTS ON THE HOST'S ENTRY POINTS
        # (28.08.2026): they start from `kukai.main`, a unit of the PRODUCT.
        # In a standalone KIR there is no such module, `live()` is honestly
        # empty, and "the judge has no live caller" would read as a finding
        # about the judge. The skip is named.
        # As of 01.09.2026 the names are declared by the TEST, not the
        # package: this is a fact about the product.
        live = live_or_named_skip(self, graph)
        callers = {name for name
                   in graph.callers_of("check_bundle", "kir.design_check")
                   if not name.startswith("kir.tests")}
        self.assertIn("kir.course", callers, callers)
        outside = callers - {"kir.course"}
        self.assertTrue(outside, "у судьи по-прежнему только дверь песочницы")
        self.assertTrue([c for c in outside if c in live],
                        f"вызывающий есть, но он не достижим из прода: {outside}")


# ═════════════════════════════════════════════════════════════════════════
# 2. PASS BY SATISFACTION ≠ PASS BY WAIVER
# ═════════════════════════════════════════════════════════════════════════

class TwoKindsOfPass(_Door):

    def test_the_two_passes_differ_by_a_number_the_model_can_read(self) -> None:
        """One building, the difference ONLY in the name of the staircase's
        room.

        Measurement: «Лестничная клетка» -> 13 rules out of 20; «Кладовая» ->
        11 out of 20, and the difference is exactly HAB001 (second exit) +
        HAB010 (floor-to-floor connection). Both are PASS with zero
        blocking.
        """
        named = self.build("Лестничная клетка")["building"]
        J.reset()
        waived = self.build("Кладовая")["building"]

        self.assertEqual((named["verdict"], waived["verdict"]), ("pass", "pass"))
        self.assertEqual((named["blocking"], waived["blocking"]), ([], []))
        # …and yet these are DIFFERENT claims, named by number:
        self.assertEqual(named["rules_evaluated"], 13, named)
        self.assertEqual(waived["rules_evaluated"], 11, waived)
        self.assertEqual(named["rules_total"], waived["rules_total"], 20)
        gap = set(waived["rules_suspended"]) - set(named["rules_suspended"])
        self.assertEqual(gap, {"HAB001", "HAB010"}, gap)

    def test_the_waived_pass_says_suspended_and_gives_the_reason(self) -> None:
        """The number is not enough: the model reads text. A waived rule
        must be named WAIVED (not "passed") and must carry the REASON for
        the waiver — the very one the full verdict prints, while the short
        one refers to "see full"."""
        waived = self.build("Кладовая")["building"]
        text = waived["message_ru"]
        self.assertIn("СНЯТО", text, text)
        self.assertIn("ЭТИМ ЗДАНИЕМ HAB001/HAB010", text, text)
        # The reason itself, not a reference to the reason: it is precisely
        # what fixes the next turn.
        self.assertIn("ЛЕСТНИЦА", text.upper(), text)

    def test_the_always_on_waivers_do_not_cost_the_channel_every_turn(self) -> None:
        """Waivers of the STAGE ITSELF stand for any building and never
        change. Their reasons are ~1100 characters, and printing them on
        every writing turn means paying context for news that is not there.
        They are named by name, but without their reasons; the split is
        STRUCTURAL — by subtracting `DESIGN_STAGE.suspended`, not by
        guessing from the text."""
        from kir.design_check import DESIGN_STAGE

        text = self.build("Кладовая")["building"]["message_ru"]
        self.assertIn("СТАДИЕЙ (стоят при любом замысле", text)
        for rule_id in sorted(DESIGN_STAGE.suspended):
            self.assertIn(rule_id, text)
        # The apartment oracle's long reason does NOT travel into the
        # channel.
        self.assertNotIn("precision mop/core", text, text)
        self.assertLess(len(text), 2_000, len(text))

    def test_the_satisfied_pass_does_not_carry_the_waiver(self) -> None:
        """The flip side: a warning that is always present is noise, and the
        model will stop reading it after two turns."""
        named = self.build("Лестничная клетка")["building"]
        text = named["message_ru"]
        self.assertNotIn("HAB010", text, text)
        self.assertNotIn("HAB001", text, text)

    def test_the_headline_never_reads_stronger_than_the_coverage(self) -> None:
        """THE HEADLINE LAW (`verdict_headline_text`) must apply here too: a
        PASS under incomplete coverage has no right to be printed as the
        word FIT and a period. The headline is the one line that is always
        read."""
        for core, evaluated in (("Лестничная клетка", 13), ("Кладовая", 11)):
            J.reset()
            text = self.build(core)["building"]["message_ru"]
            head = text.splitlines()[0] + " " + text.splitlines()[1]
            self.assertIn(f"{evaluated} ПРАВИЛАМ ИЗ 20", text, head)


# ═════════════════════════════════════════════════════════════════════════
# 3. THE MODEL KNOWS IT IS BUILDING THE BUILDING IN PARTS
# ═════════════════════════════════════════════════════════════════════════

class TheModelIsTold(unittest.TestCase):

    def test_the_tool_description_says_the_programs_accumulate(self) -> None:
        """The second half of the same hole: the channel is built, but the
        model was not told about it. In the 03-04.08 measurement the model
        mastered the bundle EXACTLY because the test bench told it about it;
        in prod there was no such line.

        ONE TRAP IS CHECKED AS A WHOLE, NOT WORDS SCATTERED ACROSS THE WHOLE
        TEXT. The first edit of this test searched for "accumulate" and
        "receipts" in the description AS A WHOLE — and stayed green under a
        mutation that removed half the phrase: the word "receipts" is
        present in the `program_py` description even without it. The claim
        here is COMPOUND ("accumulate" AND "the verdict about the bundle
        arrives on its own" AND "here is the block's name"), so it must be
        measured in one paragraph too.
        """
        from kir.tool_doc import NOTES, build_tool_description

        notes = [n for n in NOTES if "НАКАПЛИВАЮТСЯ" in n]
        self.assertEqual(len(notes), 1, "факт накопления назван 0 или 2 раза")
        note = notes[0]
        for needle in ("КВИТАНЦИИ", "ПАЧКЕ", "`building`", "design_check(["):
            self.assertIn(needle, note, note)
        self.assertIn(note, build_tool_description())

    def test_the_pointer_and_the_receipt_speak_of_the_same_unit(self) -> None:
        """The pointer promises `design_check([...])` for the bundle — and
        the receipt must judge THE SAME unit, otherwise the model learns
        from two different buildings at once."""
        from kir.tool_doc import build_tool_description

        text = build_tool_description()
        self.assertIn("design_check([", text)
        self.assertIn("ПАЧКА", text.upper())
