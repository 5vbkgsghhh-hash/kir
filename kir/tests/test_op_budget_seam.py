"""THE SEAM BETWEEN TWO OPERATION BUDGETS — made explicit and checkable.

THE LIVE CASE OF 30.07 THIS FILE EXISTS BECAUSE OF. Autodesk's public sample
(Snowdon Towers Sample Plumbing) was decompiled and rebuilt live: 6,343
elements, 318 programs, 318 successful. The loop closed — and cost 318
rounds instead of the expected ~26.

The cause is NOT speed and NOT the language, but the seam. The system has
TWO operation budgets:

* ``MAX_OPS_PER_PROGRAM = 100`` — the AUTHOR budget: this many operations
  may be in a program written by the model. It is deliberately small and
  deliberately invisible to the LLM (see ``tool_doc``): a model allowed to
  write programs of three hundred operations is a different product with
  different risks.
* ``MAX_BULK_OPS``             — the INTERNAL budget: this many operations
  a materializer chunk holds (``decompile/materialize._pack_groups``),
  which nobody wrote by hand — it is assembled from the live model's
  decompile.

The decompiler cut chunks of 250 ops. The only live door
(``serving.handle_revit_ir``) called ``compile_program`` WITHOUT ``bulk`` —
meaning it measured EVERYTHING by the author budget of 20. Two halves of the
system counted by different budgets, and the rebuild driver had to cut at
20.

Measured on a saved decompile (``snowdon_plumb_v2/tree.json``, 6,544 L1
leaves): chunk_target=20 gives 317 programs, the materializer's default —
26; the op count is 6,335 in both cases.

The tests below:
  DEFECT    a chunk of materializer size passes through the INTERNAL door
            (before the fix, the internal door did not exist at all), and
            the same, end to end, through the rebuild driver's request body
            at /admin/kir/run;
  CHAT      the chat door still caps at 20, and NOT A SINGLE input field
            raises it — an impossibility by CONSTRUCTION (the signature),
            not by agreement;
  SEAM      the materializer chunk's size limit and the ceiling the live
            door accepts in internal mode are ONE number. Both ends are
            measured BEHAVIORALLY (the door itself names its budget in a
            typed refusal), so the test fails the build if the budgets ever
            drift apart again — even if both literals "look the same at a
            glance."
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import compiler, serving  # noqa: E402
from kir.decompile import materialize  # noqa: E402
from kir.decompile.l1_schema import stable_l1_id  # noqa: E402
from kir.decompile.materialize import leaves_to_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode
from kir.tests.envtools import подменить_env  # noqa: E402

_BACKEND = pathlib.Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.run(coro)


def _referenced_names(path: pathlib.Path) -> set[str]:
    """Names the module ACCESSES (and not merely mentions in prose).

    An AST parse, not a substring search: a comment or docstring explaining
    the internal door is not a call. A string literal EQUAL to the name is
    caught separately: `getattr(serving, "handle_revit_ir_bulk")` counts as
    the same access."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def _query_ops(count: int) -> list[dict]:
    """Reading ops: they have no ground stage, so the budget probe does not
    go to the bridge for a snapshot. The budget is counted BEFORE the op's
    family — a reading program is measured against exactly the same
    ceiling as a writing one."""
    return [{"op": "query_count", "id": f"q{index}", "kind": "wall"}
            for index in range(count)]


def _wall_ops(count: int) -> list[dict]:
    """Writing ops under a shared fixture snapshot (level 42, wall_type 100)."""
    return [
        {
            "op": "create_wall", "id": f"w{index}",
            "p0_mm": [float(index) * 6000.0, 0.0],
            "p1_mm": [float(index) * 6000.0 + 5000.0, 0.0],
            "level": {"by": "element_id", "value": 42},
            "height_mm": 2800.0,
            "type": {"by": "element_id", "value": 100},
        }
        for index in range(count)
    ]


def _wall_leaves(count: int, base_id: int = 2000) -> list[dict]:
    """L1 decompile leaves — the materializer's input (a shape from lift.py)."""
    leaves = []
    for index in range(count):
        x = float(index) * 6000.0
        source_id = str(base_id + index)
        leaves.append({
            "kind": "op",
            "op_name": "create_wall",
            "_id": stable_l1_id("op", source_id),
            "type_name": "T",
            "params": {
                "p0_mm": [x, 0.0],
                "p1_mm": [x + 5000.0, 0.0],
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "height_mm": 2800.0,
                "type": {"by": "name", "value": "W200", "_id": "600"},
            },
            "source_element_id": source_id,
            "level_name": "L1",
            "anchor_mm": [x + 2500.0, 0.0, 0.0],
        })
    return leaves


class _DoorHarness(unittest.TestCase):
    """A shared rig: the stage-2 gate is open, the device is admin, the
    bridge is substituted.

    Both doors are called IDENTICALLY — the difference between them must be
    in themselves, not in how the test calls them."""

    #: 🔴 THE ROLLBACK IS REGISTERED RIGHT AFTER THE CHANGE, NOT IN
    #: `tearDown`. `tearDown` IS NOT CALLED if `setUp` fails — and it can:
    #: the last line here is `enter_kir_mode`, which SKIPS the test on an
    #: environment with no host. Then both environment variables stayed
    #: set, `conftest`'s leak guard correctly turned red, and it turned red
    #: on the FOLLOWING tests — 17 errors from a single skip (measured
    #: 27.08.2026, standalone KIR). The defect was latent before too: any
    #: failure in the middle of `setUp` would give the same result, there
    #: simply had been no occasion for it.
    def _вернуть_env(self, ключ: str, было: str | None) -> None:
        if было is None:
            os.environ.pop(ключ, None)
        else:
            подменить_env(self, ключ, было)

    def setUp(self) -> None:
        _прежний = os.environ.get("KUKAI_KIR_TOOL")
        self.addCleanup(self._вернуть_env, "KUKAI_KIR_TOOL", _прежний)
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")

        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.addCleanup(self._device.stop)

        self.llm = mock.Mock()
        self.llm._revit_version = "2026"

        self._acceptance_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._acceptance_dir.cleanup)
        _прежний_каталог = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        self.addCleanup(self._вернуть_env,
                        "KIR_ACCEPTANCE_EVIDENCE_DIR", _прежний_каталог)
        подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._acceptance_dir.name)

        # THE GATE'S THIRD CONDITION (13.08): KIR mode is set EXPLICITLY.
        # Stands LAST and can skip the test — everything above already has
        # its rollback registered.
        enter_kir_mode(self)

    def _call(self, door, program: dict, args: dict | None = None) -> dict:
        acceptance = PassingAcceptanceBridge(
            program, bulk=door is serving.handle_revit_ir_bulk)

        async def fake_exec(_llm, _bridge, _code, op, _timeout_ms):
            def execute(code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, _code, op)

        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            return _run(door(args if args is not None else {"program": program},
                             self.llm, bridge_callback=None))

    def _budget_diagnostic(self, result: dict) -> dict:
        self.assertFalse(result["ok"], result)
        diagnostics = result.get("diagnostics") or []
        self.assertTrue(diagnostics, result)
        self.assertEqual(diagnostics[0]["code"], "KIR-L001", diagnostics[0])
        return diagnostics[0]


# ---------------------------------------------------------------------------
# THE DEFECT — the very one measured live
# ---------------------------------------------------------------------------


class TheLiveDefect(_DoorHarness):
    #: Exactly what the materializer cuts by, by default (``chunk_target``).
    CHUNK = 250

    def test_chat_door_now_accepts_a_materializer_sized_chunk(self) -> None:
        """🔴 FLIPPED BY THE OWNER'S DECISION ON 18.08.2026 (budget 100 ->
        10,000).

        This used to say "chat REFUSES a chunk the size of the
        materializer's," and that was by design: chat measures by the
        author budget, and it used to be smaller. Now the author budget is
        BIGGER than the internal one, and chat accepts such a chunk.

        The test was not deleted but flipped, because what it guards is not
        a number but the SEAM: as long as the internal budget stands at
        300 (chunking for the direct path is not written, `dsl.py:964`), a
        chunk of materializer size must PASS the author door and hit its
        limit deeper in. If this asymmetry disappears, a red is mandatory,
        because a DECISION will have changed, not a literal.
        """
        result = self._call(serving.handle_revit_ir,
                            {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)})
        self.assertLessEqual(self.CHUNK, compiler.MAX_OPS_PER_PROGRAM,
                             "чанк перестал помещаться в авторский бюджет — "
                             "проверь, не опустили ли его обратно")
        self.assertNotIn("diagnostics", {k: v for k, v in result.items()
                                         if k == "diagnostics" and v},
                         f"чат отказал чанку, который обязан принимать: {result}")

    def test_internal_door_runs_a_materializer_sized_chunk(self) -> None:
        """DEFECT OF 30.07: no such door existed, and 6,343 elements cost
        318 rounds instead of 26."""
        program = {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)}
        result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("kir"))

    def test_internal_door_is_the_single_rebuild_policy_point(self) -> None:
        """The internal door must compile a chunk with the SAME helper as
        the dry gate (``compile_rebuild_chunk``): bulk+per_op+de-join — one
        fact, named once. Separate flags on each call have already drifted
        apart three times (21.07)."""
        seen: list[dict] = []
        real = compiler.compile_rebuild_chunk

        def spy(program, *args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return real(program, *args, **kwargs)

        program = {"ir_version": "1.0", "ops": _wall_ops(25)}
        with mock.patch.object(compiler, "compile_rebuild_chunk", spy):
            result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(seen), 1, "внутренняя дверь звала не тот вход")

    def test_internal_door_emits_per_op_isolation(self) -> None:
        """A consequence of the policy: a chunk goes with per-op isolation
        and WITHOUT wall auto-join. Checked against the C#, not against
        flags: a flag can be passed and not applied."""
        program = {"ir_version": "1.0", "ops": _wall_ops(3)}
        chat = compiler.compile_program(program, "2026",
                                        snapshot=GROUND_SNAPSHOT)
        internal = compiler.compile_rebuild_chunk(program, "2026",
                                                  snapshot=GROUND_SNAPSHOT)
        self.assertTrue(chat.ok and internal.ok)
        self.assertNotIn("SubTransaction", chat.csharp)
        self.assertIn("SubTransaction", internal.csharp)
        self.assertIn("DisallowWallJoin", internal.csharp)

    def test_partial_chunk_is_refused_not_blessed(self) -> None:
        """THE COST of per-op isolation, pinned explicitly: part of a chunk
        can commit while part does not. The door must say ok=false and NAME
        the op with no identity, rather than hand back a silent success.

        The receipt, in the process, loses elements already created (the
        payload never reaches the caller) — this is recorded here as KNOWN
        behavior, not as a surprise on the next live rebuild."""
        program = {"ir_version": "1.0", "ops": _wall_ops(3)}

        acceptance = PassingAcceptanceBridge(program, bulk=True)

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                return {"result": {"ok": True,
                                   "w0": {"id": 1},
                                   "w1": {"error": "short curve"},   # refused
                                   "w2": {"id": 3}}}

            return acceptance.dispatch(execute, code, op)

        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            result = _run(serving.handle_revit_ir_bulk(
                {"program": program}, self.llm, bridge_callback=None))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["diagnostics"][0]["code"], "KIR-X008")
        self.assertIn("w1", result["diagnostics"][0]["detail"])


# ---------------------------------------------------------------------------
# CHAT — the ceiling of 20 is not raised by ANY input field
# ---------------------------------------------------------------------------


class ChatDoorStaysAtTheAuthoredBudget(_DoorHarness):

    def _over_budget(self) -> list[dict]:
        return _query_ops(compiler.MAX_OPS_PER_PROGRAM + 1)

    def test_no_input_field_can_raise_the_chat_ceiling(self) -> None:
        """Everything the model could try in order to "ask for bulk."""
        ops = self._over_budget()
        attempts = [
            {"program": {"ir_version": "1.0", "ops": ops}, "bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops}, "internal_bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops}, "channel": "internal"},
            {"program": {"ir_version": "1.0", "ops": ops}, "mode": "rebuild"},
            {"program": {"ir_version": "1.0", "ops": ops, "bulk": True}},
            {"ir_version": "1.0", "ops": ops, "bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops},
             "program_id": "a" * 64},
        ]
        for args in attempts:
            with self.subTest(args=sorted(args)):
                result = self._call(serving.handle_revit_ir, {"ops": ops},
                                    args=args)
                self.assertFalse(result["ok"], result)
                codes = {d.get("code") for d in (result.get("diagnostics") or [])}
                # Either the budget (KIR-L001), or an unknown envelope
                # field (KIR-P003) — but NEVER "ok."
                self.assertTrue(codes & {"KIR-L001", "KIR-P003"}, result)

    def test_chat_door_signature_cannot_express_bulk(self) -> None:
        """Impossibility by CONSTRUCTION: the chat door has no parameter
        that turns bulk on. An agreement to "not pass the flag" gets
        forgotten; a missing parameter does not."""
        forbidden = ("bulk", "internal", "channel", "budget", "cap", "chunk")
        for name in inspect.signature(serving.handle_revit_ir).parameters:
            self.assertFalse(
                any(token in name.lower() for token in forbidden),
                f"у чат-двери появился параметр {name!r}, которым можно "
                f"попросить внутренний бюджет")

    def test_the_chat_call_site_never_names_the_internal_door(self) -> None:
        """The model's loop (kukai/llm) must not ACCESS the internal door.

        🔴 THIS IS A CLAIM ABOUT THE HOST, NOT ABOUT THE LANGUAGE, and it is
        read off the product's TREE. A standalone KIR install does not see
        this tree — then the check is SKIPPED with a named reason. Green
        without the tree would mean "the chat door has no violations,"
        while there is no door there at all.
        """
        if not (_BACKEND / "kukai" / "llm").is_dir():        # pragma: no cover
            self.skipTest("дерева хоста (kukai/llm) здесь нет — "
                          "утверждение о продукте непроверяемо")
        offenders = []
        for path in sorted((_BACKEND / "kukai" / "llm").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if "handle_revit_ir_bulk" in _referenced_names(path):
                offenders.append(str(path))
        self.assertEqual(offenders, [], "чат-петля зовёт внутреннюю дверь")

    def test_internal_door_reachable_only_from_the_admin_route(self) -> None:
        """Who in the tree ACCESSES this door at all: itself, and the admin
        route. Should someone else appear, that is a new door to the
        outside."""
        allowed = {
            pathlib.Path(__file__).resolve().parents[1] / "serving.py",
            _BACKEND / "kukai" / "api" / "admin_kir.py",
        }
        offenders = []
        for path in sorted((_BACKEND / "kukai").rglob("*.py")):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            if path in allowed:
                continue
            if "handle_revit_ir_bulk" in _referenced_names(path):
                offenders.append(str(path))
        self.assertEqual(offenders, [])
        # Positive control: the scanner ACTUALLY sees an access. Without
        # it, "nobody calls it" would pass even with a broken scanner.
        self.assertIn("handle_revit_ir_bulk",
                      _referenced_names(_BACKEND / "kukai" / "api"
                                        / "admin_kir.py"))
        # ...and does NOT count prose explaining the door as an access.
        self.assertNotIn("handle_revit_ir_bulk",
                         _referenced_names(_BACKEND / "kukai" / "ir"
                                           / "compiler.py"))

    def test_internal_door_still_needs_the_admin_device(self) -> None:
        """The second line of defense: the internal door is closed on a
        foreign device — and this is checked INDEPENDENTLY of the
        KUKAI_KIR_TOOL flag."""
        program = {"ir_version": "1.0", "ops": _query_ops(1)}
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="deadbeef"):
            result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result.get("error"), "gate")

    def test_internal_door_still_obeys_the_stage2_flag(self) -> None:
        """The first line of defense is in place: the internal door goes
        through the same body, hence the same gate. A separate device
        check does NOT replace it."""
        program = {"ir_version": "1.0", "ops": _query_ops(1)}
        подменить_env(self, "KUKAI_KIR_TOOL", "off")
        try:
            result = self._call(serving.handle_revit_ir_bulk, program)
        finally:
            подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result.get("error"), "gate")


# ---------------------------------------------------------------------------
# SEAM — the main investment: the two budgets cannot drift apart silently
# ---------------------------------------------------------------------------


class BudgetSeamContract(_DoorHarness):

    def _door_ceiling(self, door) -> int:
        """The ceiling the door ACCEPTS, measured behaviorally.

        The door names its own budget, in a typed refusal: the ASSERTION
        here is taken from its response, not from a constant — otherwise
        the test would be comparing a literal against a literal.

        🔴 THE PROBE'S SIZE IS A SEPARATE MATTER, and this became visible on
        18.08. It was a literal 4000 and silently stopped working when the
        author budget rose to 10,000: the probe PASSED, there was no
        refusal, and the test failed not on the subject but on its own
        yardstick. The probe must knowingly exceed ANY budget, so its size
        is computed from the constants — this is not a substitution of the
        assertion, but honest calibration of the instrument to the range it
        measures."""
        beyond = max(compiler.MAX_OPS_PER_PROGRAM, compiler.MAX_BULK_OPS) + 1
        result = self._call(door, {"ir_version": "1.0", "ops": _query_ops(beyond)})
        diagnostic = self._budget_diagnostic(result)
        match = re.search(r"<=(\d+)", str(diagnostic.get("expected")))
        self.assertIsNotNone(match, diagnostic)
        return int(match.group(1))

    def _materializer_ceiling(self) -> int:
        """The chunk's size ceiling, measured behaviorally: we ask the
        materializer for a ``chunk_target`` deliberately beyond its
        capacity and look at what it actually answered.

        🔴 THE PROBE'S YARDSTICK IS FROM THE CONSTANT, NOT A LITERAL (fixed
        19.08.2026). `_wall_leaves(1500)` used to stand here. While the
        internal budget was 300, the probe exceeded it and the ceiling was
        measured. After the raise to 10,000, fifteen hundred leaves stopped
        being ENOUGH to reach the ceiling: the probe returned 1500 (it all
        went into one chunk), the test compared 1500 to 10,000 and turned
        red ON ITS OWN RULER, not on the subject. The seam held throughout.

        This is the third case of the same shape in this file — a literal
        yardstick silently stops exceeding a raised limit — and it is cured
        the same way each time: the yardstick is derived from the same
        constant as the subject, plus one.
        """
        beyond = compiler.MAX_BULK_OPS + 1
        result = leaves_to_program(_wall_leaves(beyond), chunk_target=10 ** 9)
        return max(len(program["ops"]) for program in result.programs)

    def test_materializer_chunk_ceiling_equals_internal_door_ceiling(self) -> None:
        """The MAIN test of the seam. Fails the build if the budgets are pulled apart."""
        self.assertEqual(
            self._materializer_ceiling(),
            self._door_ceiling(serving.handle_revit_ir_bulk),
            "разборщик режет чанки одного размера, а живая дверь принимает "
            "другой — ровно тот стык, который стоил 318 раундов 30.07")

    def test_both_ends_read_the_same_constant_object(self) -> None:
        """One place, not two coinciding literals."""
        self.assertIs(materialize.MAX_BULK_OPS, compiler.MAX_BULK_OPS)

    def test_chat_ceiling_is_authored_and_the_script_door_keeps_headroom(self) -> None:
        """A literal DELIBERATELY STANDS here and must turn red on every
        move of the budget: checking against the constant itself would pass
        at any value of it, that is, would guard nothing.

        RAISED 20 -> 100 BY THE OWNER'S DECISION ON 15.08.2026. The pin
        fired exactly as intended: a fix to a single constant turned this
        red and demanded the decision be said out loud, rather than sail
        through silently. The argument AGAINST the raise (210 out of 586
        live refusals on 30.07 — this budget, working as a signal that "the
        wrong shape was chosen") is not withdrawn and is recorded in
        `compiler.py`; the owner took it into account and decided
        otherwise.

        🔴 RAISED 100 -> 10,000 BY THE OWNER'S DECISION ON 18.08.2026, and
        the tripwire fired again exactly as intended — turned red and
        demanded to be said out loud.

        THE OWNER'S ARGUMENT: the constitution's unit of utterance is the
        BUILDING, and the budget was permitting a room. The costs confirm
        this, measured on 18.08: a turn costs ~14 s fixed plus ~45 ms per
        op, meaning an op is almost free while a turn is expensive — it
        pays to build with ONE large program.

        🔴🔴 AND RIGHT HERE, HALF OF THIS TEST'S OWN NAME IS RETRACTED. The
        condition "author budget SMALLER than the internal one" NO LONGER
        HOLDS: the owner aligned both at 1000. The seam in NUMBERS is gone
        — it survives only in the WORDS of the refusal, and that matters
        more: different readers read them (the model versus the rebuild
        driver), and each needs a different next move. The debt is named in
        the process:

            THERE IS NO CHUNKING FOR THE DIRECT PATH (the reverse path has
            one — decompile/materialize.py). A program of 1000 ops will
            travel to Revit in ONE transaction. An accepted risk of the
            development stage.

        The test guards the equality: if the budgets drift apart in either
        direction, a red is mandatory, because a DECISION will have
        changed, not a number.
        """
        chat = self._door_ceiling(serving.handle_revit_ir)
        internal = self._door_ceiling(serving.handle_revit_ir_bulk)
        self.assertEqual(chat, compiler.MAX_OPS_PER_PROGRAM)
        # 🔴 THE OWNER'S DECISION OF 20.08.2026: 1000 -> 100,000, verbatim
        # "expand it to the 100k limit, everywhere, and make sure it never
        # comes up again."
        # The guard remains a ratchet: the number here is moved ONLY by a
        # decision, and the decision must be recorded right next to it —
        # otherwise the next wave will nudge it "to make the test green,"
        # which is exactly the outcome the guard was built against.
        #
        # WHAT THIS NUMBER MEANS NOW. Not "this many fit," but protection
        # against a runaway: a program never has more than a hundred
        # thousand operations, meaning the author's loop has gone off the
        # rails. The real walls are measured and sit LOWER in the pipeline:
        # compilation is linear (1 ms and 3.4 KB of C# per op: 100,000 ops
        # = 101 s, 343 MB of C#, 3.7 GB RSS), while the bridge's frame is
        # 16 MB — meaning transport breaks around 4,500 ops. So raising the
        # number GRANTS NO CAPABILITY until the direct path is chunked;
        # that has become the blocking debt.
        self.assertEqual(chat, 100_000, "авторский бюджет двигать только решением")
        # 🔴 THE EQUALITY WAS RETRACTED THE SAME DAY IT WAS INTRODUCED
        # (`e6f47d12`, 18.08), and the assertion here is brought in line
        # with the decision in force as of 19.08.2026. "1000 everywhere"
        # zeroed out the scripting door's HEADROOM, and its entire value
        # lies precisely in that headroom: "a script that can do exactly
        # twenty operations is strictly worse than twenty written by hand."
        # The retreat is named out loud:
        #     author (the model writes by hand into JSON)      1000
        #     internal = builder (rebuild, scripted)           10000
        # We now guard a STRICT INEQUALITY, and this is stronger than
        # equality: it turns red both when the budgets become equal
        # (headroom gone) and when the author budget outgrows the internal
        # one (the model's door becomes wider than the service door).
        self.assertGreater(
            internal, chat,
            "запас скриптовой двери обнулён: внутренний бюджет обязан быть "
            "СТРОГО больше авторского, иначе program_py теряет смысл")
        self.assertEqual(internal, compiler.MAX_BULK_OPS)

    def test_budget_refusal_names_which_budget_ran_out(self) -> None:
        """The refusal stays TYPED (KIR-L001 + expected/got) and NAMES the
        budget — otherwise "too many ops" sounds the same for two different
        causes, and the fix goes to the wrong place."""
        # The probe's yardstick is from the constants, not a literal: 4000
        # silently stopped exceeding the author budget on 18.08, when it
        # was raised to 10,000.
        beyond = max(compiler.MAX_OPS_PER_PROGRAM, compiler.MAX_BULK_OPS) + 1
        chat = self._budget_diagnostic(
            self._call(serving.handle_revit_ir,
                       {"ir_version": "1.0", "ops": _query_ops(beyond)}))
        internal = self._budget_diagnostic(
            self._call(serving.handle_revit_ir_bulk,
                       {"ir_version": "1.0", "ops": _query_ops(beyond)}))
        self.assertIn("АВТОРСКИЙ", chat["message_ru"])
        self.assertIn(compiler.BUDGET_AUTHORED, chat["message_ru"])
        self.assertIn("ВНУТРЕННИЙ", internal["message_ru"])
        self.assertIn(compiler.BUDGET_INTERNAL_BULK, internal["message_ru"])
        # The internal refusal explains WHY there are two budgets (it is
        # read by the operator or the rebuild driver, not the model).
        self.assertIn("Бюджета два", internal["message_ru"])
        self.assertNotEqual(chat["message_ru"], internal["message_ru"])
        # The internal budget's number does not flow into the chat
        # refusal: telling the model "300" already cost a round and a
        # program rewrite (measured 27.07).
        # 🔴 WE TELL THEM APART BY NAME, NOT BY NUMBER. Before 18.08 the
        # budgets stood at 100 and 300, and "the author refusal carries no
        # 300" worked. After the alignment to 1000, this requirement became
        # UNSATISFIABLE: the numbers coincided, and the check would turn
        # red forever without finding a defect. The real invariant was
        # always about the name — so the fix does not go to the wrong
        # place, a refusal must name ITS OWN budget and not call the other
        # one's.
        self.assertNotIn(compiler.BUDGET_INTERNAL_BULK, chat["message_ru"])
        self.assertIn(str(compiler.MAX_OPS_PER_PROGRAM), chat["message_ru"])
        # The budget's name and its value are taken as a PAIR from one
        # place: a refusal cannot name one budget while measuring against
        # another.
        self.assertEqual(compiler.pre_macro_budget(bulk=False),
                         (compiler.BUDGET_AUTHORED,
                          compiler.MAX_OPS_PER_PROGRAM))
        self.assertEqual(compiler.pre_macro_budget(bulk=True),
                         (compiler.BUDGET_INTERNAL_BULK,
                          compiler.MAX_BULK_OPS))

    def test_internal_door_does_not_lift_the_post_expansion_ceiling(self) -> None:
        """``MAX_VALIDATED_OPS`` is the ceiling AFTER macro expansion. The
        internal entry point raises only the pre-macro budget, never this
        one."""
        # Raised on 20.08 to follow the author budget (see the argument
        # above): the post-macro ceiling must stay ABOVE the author budget
        # and above the internal batch, or it would substitute itself for
        # their refusals.
        self.assertEqual(compiler.MAX_VALIDATED_OPS, 400_000,
                         "послемакросный потолок поднят 18.08 вслед за "
                         "авторским бюджетом; двигать только решением")
        blowup = {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
                  "name_prefix": "Этаж",
                  "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                             "p1_mm": [6000, 0], "height_mm": 2800}]}
        program = {"ir_version": "1.0",
                   "ops": _query_ops(compiler.MAX_BULK_OPS - 1) + [blowup]}
        result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertFalse(result["ok"], result)

    def test_internal_door_refuses_one_op_over_its_own_budget(self) -> None:
        program = {"ir_version": "1.0",
                   "ops": _query_ops(compiler.MAX_BULK_OPS + 1)}
        self._budget_diagnostic(self._call(serving.handle_revit_ir_bulk,
                                           program))


# ---------------------------------------------------------------------------
# THE ADMIN ROUTE — the only one with access to the internal door
# ---------------------------------------------------------------------------


class AdminRouteWiring(unittest.TestCase):

    def setUp(self) -> None:
        # The service door belongs to the HOST. Without it, the check is
        # SKIPPED with a named reason: green with no door would mean "the
        # door has no flaw," while there is no door at all.
        from kir import ports as _п
        try:
            admin_kir = _п.need(_п.ADMIN_KIR)
        except _п.PortMissing as _exc:  # pragma: no cover
            self.skipTest('служебная дверь — у хоста: ' + str(_exc))

        self.admin_kir = admin_kir
        self._rows = mock.patch.object(
            admin_kir, "_admin_ws_rows",
            return_value=[{"ws": object(), "ws_id": "ws-1",
                           "device_id": "dev", "document_name": "проект1",
                           "document_path": "", "revit_version": "2026",
                           "has_document": True, "warnings_count": 0}])
        self._rows.start()

    def tearDown(self) -> None:
        self._rows.stop()

    def _post(self, payload: dict) -> tuple[str, dict]:
        called: dict = {}

        async def chat_door(*args, **kwargs):
            called["door"] = "chat"
            return {"ok": True, "kir": True}

        async def bulk_door(*args, **kwargs):
            called["door"] = "bulk"
            return {"ok": True, "kir": True}

        with mock.patch.object(serving, "handle_revit_ir", chat_door), \
                mock.patch.object(serving, "handle_revit_ir_bulk", bulk_door):
            result = _run(self.admin_kir.run_program(payload))
        return called.get("door", ""), result

    def test_default_run_uses_the_chat_door(self) -> None:
        door, _ = self._post({"program": {"ir_version": "1.0",
                                          "ops": _query_ops(1)},
                              "doc_contains": "проект1"})
        self.assertEqual(door, "chat")

    def test_bulk_true_uses_the_internal_door(self) -> None:
        door, _ = self._post({"program": {"ir_version": "1.0",
                                          "ops": _query_ops(1)},
                              "doc_contains": "проект1", "bulk": True})
        self.assertEqual(door, "bulk")

    def test_bulk_field_is_typed(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self._post({"program": {"ir_version": "1.0", "ops": _query_ops(1)},
                        "doc_contains": "проект1", "bulk": "да"})


class TheLiveDefectEndToEnd(unittest.TestCase):
    """THE VERY SAME turn, whole: the rebuild driver's request body, the
    real serving doors, only the bridge substituted. Before 30.07,
    /admin/kir/run had exactly one path — the chat door — and every
    materializer chunk was refused with KIR-L001."""

    CHUNK = 250

    def setUp(self) -> None:
        # The service door belongs to the HOST. Without it, the check is
        # SKIPPED with a named reason: green with no door would mean "the
        # door has no flaw," while there is no door at all.
        from kir import ports as _п
        try:
            admin_kir = _п.need(_п.ADMIN_KIR)
        except _п.PortMissing as _exc:  # pragma: no cover
            self.skipTest('служебная дверь — у хоста: ' + str(_exc))

        self.admin_kir = admin_kir
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self._rows = mock.patch.object(
            admin_kir, "_admin_ws_rows",
            return_value=[{"ws": object(), "ws_id": "ws-1",
                           "device_id": serving.ADMIN_DEVICE,
                           "document_name": "проект1", "document_path": "",
                           "revit_version": "2026", "has_document": True,
                           "warnings_count": 0}])
        self._rows.start()
        self._bridge = mock.patch(
            "kukai.api.bridge_protocol._bridge_callback",
            new=mock.AsyncMock(return_value={}))
        self._bridge.start()
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._acceptance_dir.name)
        # THE GATE'S THIRD CONDITION (13.08): KIR mode is set EXPLICITLY.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._bridge.stop()
        self._rows.stop()
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()
        if self._prev_flag is None:
            os.environ.pop("KUKAI_KIR_TOOL", None)
        else:
            подменить_env(self, "KUKAI_KIR_TOOL", self._prev_flag)

    def _run_driver_payload(self, *, bulk: bool) -> dict:
        program = {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)}
        acceptance = PassingAcceptanceBridge(program, bulk=bulk)

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program["ops"]):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        #: 🔴 IT USED TO BE 200_000, AND THIS NUMBER SURVIVED ONLY BECAUSE
        #: THE DOOR NEVER READ IT. `4e4b7f95` (24.08) taught
        #: `/admin/kir/run` to read `timeout_ms` — before that it was
        #: documented TWICE and read NOT ONCE — and this rig immediately
        #: turned red with a named refusal, "must be in 1..190000." The
        #: ceiling is not ours: the bridge waits `min(timeout_ms/1000 + 10,
        #: 200)` seconds (`bridge_protocol.py:401`, `:421`), so above
        #: 190_000 the caller's number BECOMES A LIE — Revit is allowed
        #: more than the bridge is willing to wait. The ceiling does not
        #: cut a lawful program, and here even less so: the executor
        #: further down is mocked (`fake_exec`), the timeout is decorative
        #: and never expires. The test was pinning a DEFECT, not a
        #: property.
        body = {"program": program, "doc_contains": "проект1",
                "timeout_ms": 190_000}
        if bulk:
            body["bulk"] = True
        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            return _run(self.admin_kir.run_program(body))

    def test_the_defect_without_bulk_is_gone_and_that_is_the_decision(self) -> None:
        """🔴 THE SYMPTOM OF 30.07 NO LONGER REPRODUCES, AND THIS IS NOT A
        LOSS OF THE TEST.

        Verbatim, it used to read: "a chunk of 250 ops refused on a budget
        of 20." The budget was raised twice — 20 -> 100 (15.08) and 100 ->
        10,000 (18.08), both times by the owner's decision. After the
        second raise, the driver's chunk passes, and a refusal on the
        author budget for this input never happens at all.

        What the test guards now: that the absence of a refusal is
        NOTICED, should the budget ever be lowered back. A red here will
        mean not "the defect came back," but "the owner's decision was
        reversed" — and that needs to be read, not fixed.
        """
        answer = self._run_driver_payload(bulk=False)
        kir = answer["kir"]
        self.assertTrue(
            kir["ok"],
            "чанк драйвера снова отказан — значит авторский бюджет опустили "
            f"ниже его размера; сейчас он {compiler.MAX_OPS_PER_PROGRAM}: {kir}")

    def test_the_same_chunk_runs_with_bulk(self) -> None:
        """And the same body with ``bulk: true`` passes — 26 programs
        instead of 318."""
        answer = self._run_driver_payload(bulk=True)
        self.assertTrue(answer["bulk"])
        self.assertTrue(answer["kir"]["ok"], answer["kir"])


if __name__ == "__main__":
    unittest.main()
