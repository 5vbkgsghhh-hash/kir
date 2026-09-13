"""FORWARD-PASS CHUNKING IS WIRED INTO THE PROD DOOR: IT EXECUTES, IT DOES
NOT REFUSE.

WHAT STOOD HERE BEFORE 21.08.2026. This file guarded a TEMPORARY GUARD,
`program_too_large_for_one_send`: a program that did not fit in the
bridge's frame was bounced BEFORE compilation, and the refusal honestly
stated that chunking was already built (`kir.chunking`) and not wired to
the door. The guard was true ABOUT US, not about the program: the compiler
could already execute five thousand walls, while the author got a refusal.

MEASUREMENTS THIS WHOLE THING EXISTS FOR (20.08.2026, Revit 2026, DO NOT
re-measure):

    ops     compile      C# MB   peak RSS MB     chunked
     1000        1.0 s      3.4          69      — (fits, one transaction)
     5000        5.0 s     16.9         222      3 chunks
    20000       20.8 s     68.0         830      17 s, 9 chunks, peak RSS 206
   100000      101   s    343         3723      94 s, 42 chunks, peak RSS 250

The websocket frame is 16 MB, and there is no length guard on the bridge at
all. So at 1000 operations, what stood in the way was not the budget (it
has since been raised to 100 000), but an UNNAMED TRANSPORT WALL — and
chunking fixes the service's memory along the way, fifteenfold.

🔴 WHAT THIS FILE GUARDS NOW — TWO THINGS, AND THE SECOND MATTERS MORE THAN
THE FIRST:
  1. the door EXECUTES a large program in chunks, in order, linking
     references;
  2. THE WEAKENING OF ATOMICITY IS NAMED. The program is no longer one
     transaction. A refusal on chunk k means chunks 1..k-1 are ALREADY IN
     THE MODEL, and the receipt must say so in FLAT SCALARS (a dict
     collapses under the history folder at ANY level — measured
     15.08.2026), list what was built by name, and forbid a retry
     (`retry: forbidden`). A silent "built halfway" is the worst outcome
     this compiler allows.
"""
from __future__ import annotations

import asyncio
import types
import unittest
from unittest import mock

from kir import chunking
from kir import serving


def _walls(n: int, **extra) -> list:
    out = []
    for i in range(n):
        row, col = divmod(i, 300)
        x, y = col * 300.0, row * 400.0
        op = {"op": "create_wall", "id": f"W{i}",
              "p0_mm": [x, y], "p1_mm": [x + 250.0, y],
              "level": {"by": "element_id", "value": 355},
              "height_mm": 3000.0}
        op.update(extra)
        out.append(op)
    return out


def _level_then_walls(n: int) -> list:
    return ([{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "К1"}]
            + _walls(n, level={"by": "ref", "value": "L1"}))


def _ok_chunk(ops: list, *, first_id: int = 90000) -> dict:
    """The receipt for a SUCCESSFUL chunk is exactly the shape that prod
    prints."""
    return {
        "ok": True, "kir": True, "witness": "satisfied",
        "element_map": {o["id"]: [str(first_id + i)]
                        for i, o in enumerate(ops)},
        "outcome": {"execution": "committed", "witness": "satisfied",
                    "acceptance": "accepted"},
    }


def _failed_chunk() -> dict:
    return {
        "ok": False, "kir": True, "stage": "execute", "witness": "incomplete",
        "message_ru": "Revit отказал на операции",
        "diagnostics": [{"code": "KIR-X003", "op_id": "W4000"}],
        "outcome": {"execution": "rolled_back", "witness": "incomplete",
                    "acceptance": "not_run"},
    }


class _DriverHarness(unittest.TestCase):
    """Replaces the door's BODY, leaving the real driver in place.

    The driver calls `serving._handle_revit_ir_inner` by module name, so
    the replacement captures exactly the arguments prod would have handed
    to the chunk.
    """

    def setUp(self) -> None:
        self._real_inner = serving._handle_revit_ir_inner
        self.calls: list = []

    def tearDown(self) -> None:
        serving._handle_revit_ir_inner = self._real_inner

    def drive(self, ops: list, replies) -> dict:
        plan = chunking.plan_chunks(ops)
        self.assertTrue(plan.split, "набор обязан делиться, иначе тест пуст")

        async def fake(args, llm, bridge, **kw):
            index = kw["chunk_of"][0]
            self.calls.append((kw["chunk_of"], args))
            return replies(index, args["program"]["ops"])

        serving._handle_revit_ir_inner = fake
        result = asyncio.run(serving._drive_chunked_program(
            plan, args={"program": {"ops": ops, "intent": "проверка"}},
            llm_client=None, bridge_callback=None, query_id="q", bulk=False,
            turn_id="t", action_id="a", query_fingerprint="f",
            source_kind="test", authored_in_python=False,
            author_digest="", env_digest=""))
        return result


class TheDoorExecutesInsteadOfRefusing(_DriverHarness):

    def test_the_temporary_guard_is_GONE_from_serving(self) -> None:
        """Refusal and execution are two different answers to one input.

        What is searched for is a STRING LITERAL — something the door could
        return as a refusal stage — not just any mention: the removed
        guard's name lives on in a comment at its old spot, and that is
        correct. The question to ask is "is it produced", not "does it
        appear".
        """
        import inspect
        src = inspect.getsource(serving)
        self.assertNotIn('"program_too_large_for_one_send"', src)
        self.assertIn("program_too_large_for_one_send", src,
                      "история снятого стража стёрта вместе с ним")

    def test_a_split_program_is_executed_chunk_by_chunk_IN_ORDER(self) -> None:
        ops = _walls(5000)
        self.drive(ops, lambda i, o: _ok_chunk(o))
        self.assertGreater(len(self.calls), 1)
        seen = [c[0][0] for c in self.calls]
        self.assertEqual(seen, sorted(seen), "чанки ушли не по порядку")
        flat = [o for _, a in self.calls for o in a["program"]["ops"]]
        self.assertEqual([o["id"] for o in flat], [o["id"] for o in ops],
                         "порядок автора не сохранён по всей программе")

    def test_the_driver_is_REACHED_by_the_door_body(self) -> None:
        """Reachability, not the presence of a string.

        The body is called with a real program; everything that requires a
        live Revit is switched off, and exactly one thing remains the
        subject: whether the turn reached the driver.
        """
        reached: dict = {}

        async def fake_driver(plan, **kw):
            reached["chunks"] = len(plan.chunks)
            reached["atomicity"] = plan.atomicity
            return {"ok": True, "sentinel": True}

        with _door_stubs(fake_driver):
            res = asyncio.run(serving._handle_revit_ir_inner(
                {"program": {"ops": _walls(2500)}}, None, None, query_id="q"))
        self.assertTrue(res.get("sentinel"), "ход не дошёл до водителя чанков")
        self.assertEqual(reached["atomicity"], "per_chunk")
        self.assertGreater(reached["chunks"], 1)

    def test_a_program_that_FITS_never_reaches_the_driver(self) -> None:
        """A NARROWNESS CONTROL, and it matters more than the rest.

        An ordinary program must still run as ONE transaction. Fixing
        transport at the cost of atomicity for everyone would mean curing
        the wrong disease.
        """
        reached: dict = {}

        async def fake_driver(plan, **kw):
            reached["called"] = True
            return {"ok": True, "sentinel": True}

        with _door_stubs(fake_driver):
            asyncio.run(serving._handle_revit_ir_inner(
                {"program": {"ops": _walls(100)}}, None, None, query_id="q"))
        self.assertNotIn("called", reached)

    def test_a_REFUSED_program_is_not_chunked_but_refused(self) -> None:
        """🔴 A DEFECT OF ITS OWN, CAUGHT BY THE SUITE BEFORE A LIVE RUN.

        The first edition of the intercept was also pulling operations from
        the RAW program — the one `plan_program` had already refused. The
        consequence: a program of 200 001 operations, which was supposed
        to get a typed budget refusal (KIR-L001), instead went off to
        Revit as eighty-four chunks. Chunking fixes TRANSPORT; it has no
        license whatsoever to bypass the budget or the validation.
        """
        reached: dict = {}

        async def fake_driver(plan, **kw):
            reached["called"] = True
            return {"ok": True, "sentinel": True}

        # The subject is "the planner refused", not a number: 200 001
        # operations are not assembled in the test (that is exactly the
        # memory cost in question). AN OPERATION OF UNKNOWN KIND is enough
        # to make `plan_program` refuse and leave `routed_plan` empty;
        # meanwhile there are enough ops left for several chunks, meaning
        # without the fix the driver would have been called.
        broken = {"program": {"ops": [{"op": "нет такого опа", "id": "X%d" % i}
                                      for i in range(3000)]}}
        self.assertTrue(chunking.plan_chunks(broken["program"]["ops"]).split,
                        "набор обязан делиться, иначе тест доказывает не то")
        with _door_stubs(fake_driver):
            res = asyncio.run(serving._handle_revit_ir_inner(
                broken, None, None, query_id="q"))
        self.assertNotIn("called", reached,
                         "отвергнутая программа ушла в исполнение чанками")
        self.assertFalse(res.get("ok"))

    def test_a_BARE_LIST_program_is_not_chunked_either(self) -> None:
        """21.08: the admin door no longer judges the SHAPE of `program`,
        only its PRESENCE; the shape is judged by the compiler (`KIR-P001`:
        «получен СПИСОК операций, оберни его»). So a LIST, not a dict, can
        now reach this intercept.

        The rule "we only chunk what the planner has admitted" closes this
        case too: for a list, `plan_program` refuses, `routed_plan` is
        empty, the driver is not called. The guard stands HERE because a
        claim about SOMEONE ELSE'S door will stop being true tomorrow,
        while this body will remain.
        """
        reached: dict = {}

        async def fake_driver(plan, **kw):
            reached["called"] = True
            return {"ok": True, "sentinel": True}

        with _door_stubs(fake_driver):
            res = asyncio.run(serving._handle_revit_ir_inner(
                {"program": _walls(3000)}, None, None, query_id="q"))
        self.assertNotIn("called", reached)
        self.assertFalse(res.get("ok"))
        # and assembling the slice does not fail on a foreign input shape
        sub = serving._chunk_sub_args({"program": _walls(3000)}, _walls(2))
        self.assertEqual(len(sub["program"]["ops"]), 2)

    def test_a_chunk_never_chunks_itself(self) -> None:
        """`chunk_of` cancels planning: there can be no recursion."""
        reached: dict = {}

        async def fake_driver(plan, **kw):
            reached["called"] = True
            return {"ok": True, "sentinel": True}

        with _door_stubs(fake_driver):
            asyncio.run(serving._handle_revit_ir_inner(
                {"program": {"ops": _walls(2500)}}, None, None,
                query_id="q", chunk_of=(0, 2)))
        self.assertNotIn("called", reached)

    def test_chunk_of_is_never_read_from_args(self) -> None:
        """The same law as for `bulk`: the CALLER sets the switch.

        The input field sooner or later arrives from the tool's arguments,
        and this switch cancels both chunk planning and publishing the
        intent.
        """
        import inspect
        src = inspect.getsource(serving)
        for form in ('args.get("chunk_of")', "args.get('chunk_of')",
                     '"chunk_of" in args'):
            self.assertNotIn(form, src)


class TheRefsSurviveTheBoundary(_DriverHarness):

    def test_a_backward_ref_becomes_an_element_id_in_the_next_chunk(self):
        ops = _level_then_walls(5000)
        self.drive(ops, lambda i, o: _ok_chunk(o, first_id=90000))
        second = self.calls[1][1]["program"]["ops"][0]
        self.assertEqual(second["level"], {"by": "element_id", "value": 90000},
                         "ссылка через границу не связалась квитанцией")

    def test_an_intra_chunk_ref_stays_a_ref(self) -> None:
        """A NARROWNESS CONTROL: only what crosses the boundary needs
        linking.

        An intra-chunk reference is resolved by the compiler, as it always
        was; replacing it with a number would take away both its work and
        its check.
        """
        ops = _level_then_walls(5000)
        self.drive(ops, lambda i, o: _ok_chunk(o))
        first = self.calls[0][1]["program"]["ops"]
        self.assertEqual(first[1]["level"], {"by": "ref", "value": "L1"})

    def test_an_unbindable_ref_refuses_and_still_names_what_was_built(self):
        """A LINKING refusal is also a refusal at chunk k: the chunks
        before it are in the model."""
        ops = _level_then_walls(5000)
        plan = chunking.plan_chunks(ops)

        async def fake(args, llm, bridge, **kw):
            # the first chunk built the level but did NOT hand back the map
            return {"ok": True, "kir": True, "witness": "satisfied",
                    "outcome": {"execution": "committed",
                                "witness": "satisfied",
                                "acceptance": "accepted"}}

        serving._handle_revit_ir_inner = fake
        res = asyncio.run(serving._drive_chunked_program(
            plan, args={"program": {"ops": ops}}, llm_client=None,
            bridge_callback=None, query_id="q", bulk=False, turn_id="t",
            action_id="a", query_fingerprint="f", source_kind="test",
            authored_in_python=False, author_digest="", env_digest=""))
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"],
                         serving.KIR_CHUNK_BIND_FAILED)
        self.assertIn("УЖЕ В МОДЕЛИ", res["chunked_note_ru"])
        self.assertEqual(res["outcome"]["retry"], "forbidden")


class TheWeakeningIsNamedInTheReceipt(_DriverHarness):

    def test_a_green_chunked_program_still_says_per_chunk(self) -> None:
        """Success does NOT cancel the weakening: there were N
        transactions, not one.

        Undoing such a program will take N undos, and the author must learn
        this from the green receipt, not from the next disaster.
        """
        res = self.drive(_walls(5000), lambda i, o: _ok_chunk(o))
        self.assertTrue(res["ok"])
        self.assertEqual(res["atomicity"], "per_chunk")
        self.assertIn("ТРАНЗАКЦИЯМИ", res["chunked_note_ru"])
        self.assertEqual(res["outcome"]["execution"], "committed")
        self.assertEqual(res["outcome"]["acceptance"], "accepted")

    def test_the_naming_is_SCALAR_at_the_top_level(self) -> None:
        """🔴 MEASURED 15.08.2026 with the real history folder: EVERY dict
        at ANY level turns into «<объект, N полей — свёрнуто>», a scalar
        gets through. A weakening named only inside the `chunked` block
        would evaporate after thirty messages — meaning it would be named
        exactly where nobody reads it.
        """
        res = self.drive(_walls(5000), lambda i, o: _ok_chunk(o))
        for field in ("atomicity", "atomicity_note_ru", "chunked_note_ru"):
            self.assertIsInstance(res.get(field), str,
                                  f"{field} обязано быть скаляром верхнего "
                                  f"уровня, иначе история его съест")

    def test_a_failure_at_chunk_k_says_1_to_k_minus_1_are_IN_THE_MODEL(self):
        ops = _walls(5000)
        res = self.drive(
            ops, lambda i, o: _failed_chunk() if i == 2 else _ok_chunk(o))
        self.assertFalse(res["ok"])
        self.assertIn("УЖЕ В МОДЕЛИ", res["chunked_note_ru"])
        self.assertIn("ОТКАЗ НА ЧАНКЕ 3 ИЗ 3", res["chunked_note_ru"])
        self.assertEqual(res["chunked"]["failed_chunk"], 2)
        self.assertEqual(res["chunked"]["executed"], 2)
        self.assertEqual(res["atomicity"], "per_chunk")

    def test_the_survivors_are_listed_BY_NAME(self) -> None:
        """"Listed" means by element numbers, not "there were this many of
        them".

        From this list the author either continues, or cleans up after
        themselves; a number alone can do neither.
        """
        ops = _walls(5000)
        res = self.drive(
            ops, lambda i, o: _failed_chunk() if i == 2 else _ok_chunk(o))
        built = res["element_map"]
        self.assertEqual(len(built), sum(
            r["ops"] for r in res["chunked"]["per_chunk"] if r["ok"]))
        self.assertEqual(built["W0"], ["90000"])
        # and the flat shape next to the dict is the same one an ordinary
        # receipt uses
        self.assertTrue(res["element_map_note"].startswith("элементы: "))

    def test_a_partial_build_FORBIDS_a_blind_retry(self) -> None:
        """Repeating it in full would duplicate what was already built.

        `unconfirmed` here would be WEAKER knowledge than what we actually
        have: we know for certain that the model has been changed.
        """
        res = self.drive(_walls(5000),
                         lambda i, o: _failed_chunk() if i == 2 else _ok_chunk(o))
        self.assertEqual(res["outcome"]["execution"], "committed")
        self.assertEqual(res["outcome"]["retry"], "forbidden")
        self.assertIsNone(res["handoff"], "рецептурный путь = повтор замысла")
        self.assertIs(res["rolled_back"], False,
                      "построенные чанки НЕ откачены, и это надо сказать")

    def test_the_public_envelope_forbids_the_retry_too(self) -> None:
        """What is called is WHAT PROD CALLS, not a hand-rewritten shape.

        `outcome.retry` is an internal value; what rides outward, into the
        model's loop, is the `err` block. If it declares a partially built
        program retryable, the model will retry it and duplicate what was
        already built — meaning the internal ban would end up named where
        nobody reads it.
        """
        res = self.drive(_walls(5000),
                         lambda i, o: _failed_chunk() if i == 2 else _ok_chunk(o))
        stamped = serving._stamp_refusal(dict(res))
        self.assertIs(stamped["err"]["retryable"], False)
        self.assertIsNone(stamped["handoff"])
        self.assertEqual(stamped["err"]["kir_code"], "KIR-X003")

    def test_the_first_chunk_failing_did_NOT_change_the_model(self) -> None:
        """The inverse control: not every refusal leaves a trace.

        An instrument that always says "the model was changed" cannot tell
        half from zero — and then the message carries no information at
        all.
        """
        res = self.drive(_walls(5000), lambda i, o: _failed_chunk())
        self.assertEqual(res["chunked"]["executed"], 0)
        self.assertNotIn("element_map", res)
        self.assertEqual(res["outcome"]["execution"], "rolled_back")
        self.assertEqual(res["outcome"]["retry"], "safe")

    def test_execution_stops_at_the_first_refusal(self) -> None:
        """A human wrote the order: you cannot build on top of what wasn't
        built."""
        self.drive(_walls(5000),
                   lambda i, o: _failed_chunk() if i == 0 else _ok_chunk(o))
        self.assertEqual(len(self.calls), 1)


class TheJournalSeesOnlyTheFoldedProgram(unittest.TestCase):

    def test_binding_before_dispatch_marks_crash_recovery_unknown(self) -> None:
        slot_token = serving._TURN_JOURNAL_SLOT.set((("dev", "doc"), 7))
        identity = types.SimpleNamespace(operation_id="operation-1")
        try:
            with mock.patch.object(
                    serving, "execution_operation_identity",
                    return_value=identity), \
                    mock.patch("kir.live.journal.bind_operation_id",
                               return_value=True), \
                    mock.patch("kir.live.journal.advance") as advance:
                assert serving._bind_turn_operation_id(
                    types.SimpleNamespace(), "wrapped") == "operation-1"
                advance.assert_called_once_with(
                    ("dev", "doc"), 7, "dispatched")
        finally:
            serving._TURN_JOURNAL_SLOT.reset(slot_token)

    def test_an_inner_chunk_cannot_commit_the_whole_program(self) -> None:
        slot_token = serving._TURN_JOURNAL_SLOT.set((("dev", "doc"), 7))
        defer_token = serving._JOURNAL_STAGE_DEFERRED.set(True)
        try:
            with mock.patch("kir.live.journal.advance") as advance:
                serving._with_outcome(
                    {"ok": True},
                    serving.write_committed(
                        witness=serving.WitnessState.SATISFIED),
                )
                advance.assert_not_called()
        finally:
            serving._JOURNAL_STAGE_DEFERRED.reset(defer_token)
            serving._TURN_JOURNAL_SLOT.reset(slot_token)

    def test_a_partial_fold_is_terminal_but_not_fully_built(self) -> None:
        slot_token = serving._TURN_JOURNAL_SLOT.set((("dev", "doc"), 7))
        try:
            with mock.patch("kir.live.journal.advance") as advance:
                serving._with_outcome(
                    {"ok": False, "stage": "chunked"},
                    serving.write_committed(
                        witness=serving.WitnessState.INCOMPLETE),
                )
                advance.assert_called_once_with(
                    ("dev", "doc"), 7, "committed_partial")
        finally:
            serving._TURN_JOURNAL_SLOT.reset(slot_token)


class TheEnvelopeAndTheEstimate(_DriverHarness):

    def test_the_authors_envelope_reaches_EVERY_chunk(self) -> None:
        """`intent`/`allow_destructive`/`ir_version` is a declaration about
        the WHOLE program. Losing it on a slice would mean building the
        chunks by different rules than the ones that were written."""
        args = {"program": {"ops": _walls(5000), "intent": "стройка",
                            "allow_destructive": False, "ir_version": "1.1"}}
        sub = serving._chunk_sub_args(args, _walls(3))
        self.assertEqual(sub["program"]["intent"], "стройка")
        self.assertEqual(sub["program"]["ir_version"], "1.1")
        self.assertEqual(len(sub["program"]["ops"]), 3)

    def test_the_script_and_its_slider_do_NOT_ride_along(self) -> None:
        """`program_py` has already become operations, while the slider is
        a capability OF THE SOURCE: in a slice there is nothing to bind it
        to. Two carriers of one intent diverge silently."""
        sub = serving._chunk_sub_args(
            {"program": {"ops": _walls(5000)}, "program_py": "x = 1",
             "params": {"h": 3000}}, _walls(2))
        self.assertNotIn("program_py", sub)
        self.assertNotIn("params", sub)

    def test_program_py_output_takes_THE_SAME_path(self) -> None:
        """The script becomes operations in `_authored_input` — BEFORE the
        body.

        Which means there is no separate tap for it, and there should not
        be one: the same code chunks its output. We are guarding the SHAPE
        that the sandbox hands back.
        """
        script_args = {"program": {"intent": "из скрипта",
                                   "ops": _walls(5000)}}
        sub = serving._chunk_sub_args(script_args, _walls(4))
        self.assertEqual(sub["program"]["intent"], "из скрипта")
        self.assertEqual(len(sub["program"]["ops"]), 4)

    def test_the_estimate_is_asked_BEFORE_compiling(self) -> None:
        """Order is the very subject here: planning AFTER compilation would
        have saved the frame and saved neither the memory nor the hundred
        seconds."""
        import inspect
        src = inspect.getsource(serving)
        estimate = src.index("_chunking.plan_chunks(_ops_for_size)")
        compile_call = src.index("def _compile_for_serving")
        self.assertLess(estimate, compile_call)

    def test_the_estimate_does_not_compile(self) -> None:
        import time
        t0 = time.time()
        chunking.plan_chunks(_walls(5000))
        self.assertLess(time.time() - t0, 2.0,
                        "оценка стала дороже своей цели")

    def test_one_oversized_op_is_a_NAMED_refusal_not_an_internal_error(self):
        """KIR-K001 was losing its name along the way: `ChunkTooBig` went
        into the body's catch-all `except Exception` and turned into
        «внутренней ошибкой KIR»."""
        real = chunking.plan_chunks

        def boom(ops, **kw):
            raise chunking.ChunkTooBig(
                f"{chunking.CHUNK_OP_TOO_BIG}: операция не влезает")

        chunking.plan_chunks = boom
        try:
            async def fake_driver(plan, **kw):
                return {"ok": True, "sentinel": True}
            with _door_stubs(fake_driver):
                res = asyncio.run(serving._handle_revit_ir_inner(
                    {"program": {"ops": _walls(5)}}, None, None, query_id="q"))
        finally:
            chunking.plan_chunks = real
        self.assertEqual(res.get("error"), "chunk_op_too_big")
        self.assertIn(chunking.CHUNK_OP_TOO_BIG, res["message_ru"])


class _door_stubs:
    """Everything that requires a live Revit — out; exactly one subject
    remains."""

    def __init__(self, driver) -> None:
        self._driver = driver

    def __enter__(self):
        self._saved = {
            "enabled": serving.revit_ir_enabled,
            "writes": serving._program_writes,
            "hold": serving._kir_hold_active,
            "version": serving._resolved_revit_version,
            "driver": serving._drive_chunked_program,
        }
        serving.revit_ir_enabled = lambda: True
        serving._program_writes = lambda *a, **k: False
        serving._kir_hold_active = lambda: False
        serving._resolved_revit_version = (
            lambda c: types.SimpleNamespace(version="2026"))
        serving._drive_chunked_program = self._driver
        return self

    def __exit__(self, *exc) -> None:
        serving.revit_ir_enabled = self._saved["enabled"]
        serving._program_writes = self._saved["writes"]
        serving._kir_hold_active = self._saved["hold"]
        serving._resolved_revit_version = self._saved["version"]
        serving._drive_chunked_program = self._saved["driver"]


if __name__ == "__main__":
    unittest.main()
