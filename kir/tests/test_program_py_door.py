"""THE SOURCE-LANGUAGE DOOR — `program_py` next to `ops`.

WHY THIS FILE EXISTS. The source-language layer (`kir/dsl.py` +
`kir/sandbox.py`) was built and verified by 328 + N tests, and the model
could not make use of it: there was no door. What is checked here is
exactly the door — and its main property:

    BELOW THE GATE THERE IS NOT A SINGLE BRANCH FOR "WHAT IF THIS WAS A SCRIPT".

A script turns into operations in EXACTLY one place
(`serving._authored_input`), and from there the program follows the same
path as JSON: `plan_program` → grounding → emission → witness → intake →
journal. The test `test_the_same_program_written_
two_ways_is_byte_identical_below_the_gate` measures this assertion rather
than retelling it: the two input forms must produce ONE `plan_digest`.

WHAT ELSE IS PINNED HERE:
  * the mutual exclusion of the forms, and a refusal on "both"/"neither"/
    "not text";
  * `author_digest` reaches the RECEIPT and the JOURNAL alongside
    `plan_digest`;
  * the sandbox's refusal comes out typed, with the MODEL's line number,
    and lands meaningfully in the `ErrCode` taxonomy (see "RETRYABLE"
    below);
  * THE BUDGET SEAM: enumeration is still measured against the author's
    20, while the script's output is measured against the internal
    budget. This is not a relaxation but a consequence of WHAT the
    authorial unit is here; a separate test holds both sides of the seam.

RETRYABLE — why the sandbox's refusal is retryable, and B012 is not. The
answer is in two facts, each with its own test below: (1) the case never
reached the bridge, there was no effect, so a retry cannot duplicate the
build — and `retryable=false` in this system means exactly "an effect
could have occurred"; (2) the refusal is deterministic (this is what
`author_digest` rests on), so `transient=false`: waiting is pointless, fix
the SOURCE. B012 flips the first fact: this is OUR defect, there is
nothing for the model to fix.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import compiler, serving  # noqa: E402
from kir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode
from kir.tests.envtools import подменить_env  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


#: A real script: computes an ellipse, builds a polyline wall along it, and
#: PRINTS the approximation's discrepancy as a number. 25 operations from
#: 21 lines — that is, more than the author budget and well under the
#: internal one.
ELLIPSE_SCRIPT = '''
import math
envelope(intent="кольцевая стена по эллипсу")
lvl = create_level(elev_mm=0, name="Отм. 0.000")
N = 24
A, B = 18000.0, 11000.0
def pt(i):
    a = 2 * math.pi * i / N
    return [round(A * math.cos(a)), round(B * math.sin(a))]
per = 0.0
for i in range(N):
    p0, p1 = pt(i), pt(i + 1)
    per += math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    create_wall(p0_mm=p0, p1_mm=p1, height_mm=3300, level=lvl,
                type={"by": "element_id", "value": 100})
ideal = 2 * math.pi * math.sqrt((A * A + B * B) / 2)
print("расхождение ломаной с эллипсом: %.2f%%" % (100 * abs(per - ideal) / ideal))
'''


class _DoorHarness(unittest.TestCase):
    """The gate is open, the device is admin, the bridge is substituted — the whole prod path."""

    def setUp(self) -> None:
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._acceptance_dir.name)
        self._feed_dir = tempfile.TemporaryDirectory()
        self._prev_feed = os.environ.get("KIR_WITNESS_PATH")
        self.feed_path = os.path.join(self._feed_dir.name, "witness.jsonl")
        подменить_env(self, "KIR_WITNESS_PATH", self.feed_path)
        # THE GATE'S THIRD CONDITION (13.08): KIR mode is set EXPLICITLY.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        for name, prev in (("KUKAI_KIR_TOOL", self._prev_flag),
                           ("KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_acceptance),
                           ("KIR_WITNESS_PATH", self._prev_feed)):
            if prev is None:
                os.environ.pop(name, None)
            else:
                подменить_env(self, name, prev)
        self._acceptance_dir.cleanup()
        self._feed_dir.cleanup()

    # -- calls -------------------------------------------------------------
    def _no_bridge(self):
        async def boom(*_a, **_kw):
            raise AssertionError("мост не должен быть тронут")
        return mock.patch.object(serving, "_run_declarative", side_effect=boom)

    def _call_refusing(self, args: dict) -> dict:
        """A call that MUST refuse before the bridge."""
        with self._no_bridge():
            return _run(serving.handle_revit_ir(args, self.llm,
                                                bridge_callback=None))

    def _call_executing(self, args: dict, *, bulk_plan: bool = True) -> dict:
        """A call all the way to the end of the path: snapshot, write, witness, intake, journal."""
        state: dict = {}

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            program = state.get("program") or {"ops": []}
            acceptance = state.get("acceptance")
            if acceptance is None:
                acceptance = state["acceptance"] = PassingAcceptanceBridge(
                    program, bulk=bulk_plan)

            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        async def go():
            # The bridge needs the same program that will go to the body:
            # we get it through the SAME gate, not a second parse of the
            # script.
            authored = await serving._authored_input(dict(args))
            if authored.refusal is None:
                state["program"] = authored.args["program"]
            with mock.patch.object(serving, "_run_declarative",
                                   side_effect=fake_exec):
                return await serving.handle_revit_ir(args, self.llm,
                                                     bridge_callback=None)
        return _run(go())

    def _journal_rows(self) -> list[dict]:
        if not os.path.exists(self.feed_path):
            return []
        with open(self.feed_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


# ═════════════════════════════════════════════════════════════════════════════
# THE DOOR WORKS
# ═════════════════════════════════════════════════════════════════════════════

class TheDoorOpens(_DoorHarness):

    def test_a_script_becomes_a_program_and_goes_the_whole_way(self) -> None:
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["ok"], result)
        # the whole path, not just the gate: witness and INDEPENDENT intake
        # The trio — by name: see the same fix in `test_v11_regressions`.
        for axis in ("geometry_ok", "semantic_ok", "topology_ok"):
            self.assertIs(result["witness"][axis], True, axis)
        self.assertIn("unwitnessed_axes", result["witness"])
        self.assertEqual(result["outcome"]["execution"], "committed")
        self.assertEqual(result["outcome"]["acceptance"], "accepted")

    def test_the_receipt_carries_the_signature_of_the_source(self) -> None:
        """`author_digest` next to `plan_digest` — a new provability.

        The receipt must read as "this program was produced by this exact
        script": intake provides the plan's signature, this block provides
        the source's signature.
        """
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        source = result["program_source"]
        self.assertEqual(source["language"], "python")
        self.assertEqual(len(source["author_digest"]), 64)
        self.assertEqual(len(source["program_digest"]), 64)
        self.assertEqual(source["op_count"], 25)
        # …and both signatures sit in ONE receipt, otherwise there is nothing to link them
        self.assertEqual(len(result["acceptance"]["plan_digest"]), 64)

    def test_the_print_of_the_script_comes_back_to_the_model(self) -> None:
        """Shape examples print the approximation's discrepancy AS A
        NUMBER. Cutting off this channel would mean bringing back "said
        sine, built a polyline, stayed silent".
        """
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertIn("расхождение ломаной с эллипсом",
                      result["program_source"]["stdout"])

    def test_the_signature_is_of_the_bytes_and_moves_with_them(self) -> None:
        """The signature is of the source, not the intent: a space changes it."""
        first = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        second = self._call_executing({"program_py": ELLIPSE_SCRIPT + "\n"})
        self.assertNotEqual(first["program_source"]["author_digest"],
                            second["program_source"]["author_digest"])
        # …while the program stays THE SAME: the signatures of two different things are independent
        self.assertEqual(first["program_source"]["program_digest"],
                         second["program_source"]["program_digest"])

    def test_the_journal_gets_the_author_digest_beside_the_plan_digest(self) -> None:
        """The journal follows the same rule as the receipt. `plan_digest`
        answers "what was compiled", `author_digest` — "what it was
        written with"."""
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        rows = self._journal_rows()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["author_digest"],
                         result["program_source"]["author_digest"])
        self.assertEqual(row["authored_in"], "python")
        self.assertEqual(len(row["plan_digest"]), 64)

    def test_a_json_program_carries_no_authorship_at_all(self) -> None:
        """An empty string in the corpus would read as "there was a script
        and it did not sign". The field is not there at all."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]}
        result = self._call_executing({"program": program}, bulk_plan=False)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("program_source", result)
        row = self._journal_rows()[0]
        self.assertNotIn("author_digest", row)
        self.assertNotIn("authored_in", row)

    def test_the_envelope_the_script_set_survives_the_gate(self) -> None:
        """`intent`/`defaults` are what the author NAMED explicitly.
        Reassembling the envelope by eye means losing what was named."""
        script = (
            'envelope(intent="этаж", defaults={"symbol": {"by": "element_id", '
            '"value": 1101}})\n'
            'lvl = create_level(elev_mm=0, name="L")\n'
            'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, '
            'level=lvl)\n')
        authored = _run(serving._authored_input({"program_py": script}))
        self.assertIsNone(authored.refusal)
        self.assertEqual(authored.args["program"]["intent"], "этаж")
        self.assertEqual(authored.args["program"]["defaults"],
                         {"symbol": {"by": "element_id", "value": 1101}})

    def test_defaults_cannot_fill_a_required_selector_and_the_doc_says_so(self):
        """MEASUREMENT 03.08, THE REASON THE DESCRIPTION CARRIES A CAVEAT.

        The `defaults` envelope fills in ONLY THE OMITTED field (measured
        below: an omitted `level` gets the envelope's value, while an
        explicit `{"by": "default"}` does not). In the language, however,
        `level` is a REQUIRED argument, and Python will not let it be
        omitted. So the advice "a selector used once per program belongs
        in `defaults`", correct for the `program` field, would have cost a
        round trip in a script — since 04.08 this is KIR-P005 (before that
        it was a bare Python `TypeError: missing a required argument`,
        which named one slot out of ten; see `dsl._bind_refusal`).

        The test holds both halves: the measurement of the behavior, and
        the fact that the instrument's description WARNS about it.
        """
        base = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "height_mm": 3000}
        envelope = {"level": {"by": "name", "value": "Этаж 1"}}
        omitted = compiler.plan_program(
            {"ir_version": "1.0", "defaults": envelope, "ops": [dict(base)]})
        self.assertEqual(omitted.to_ops()[0]["level"], envelope["level"])
        explicit = compiler.plan_program({
            "ir_version": "1.0", "defaults": envelope,
            "ops": [{**base, "level": {"by": "default"}}]})
        self.assertEqual(explicit.to_ops()[0]["level"], {"by": "default"})

        # …while in a script a required argument is not omitted at all
        refused = _run(serving._authored_input({"program_py": (
            'envelope(defaults={"level": {"by": "name", "value": "Этаж 1"}})\n'
            'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000)\n')}))
        self.assertIsNotNone(refused.refusal)
        message = refused.refusal["message_ru"]
        self.assertIn("KIR-P005", message)
        self.assertIn("level", message)
        # The refusal must carry through to the next turn, not just name the slot.
        self.assertIn("СЛЕДУЮЩИЙ ХОД", message)

        from kir.tool_doc import build_tool_description
        self.assertIn("заполняет только ОПУЩЕННОЕ поле",
                      build_tool_description())


# ═════════════════════════════════════════════════════════════════════════════
# ONE PATH BELOW THE GATE — the architecture's main assertion, measured
# ═════════════════════════════════════════════════════════════════════════════

class OnePathBelowTheGate(_DoorHarness):

    #: The same program, written two different ways.
    OPS = [
        {"op": "create_level", "id": "level1", "elev_mm": 0, "name": "L"},
        {"op": "create_wall", "id": "wall1", "p0_mm": [0, 0],
         "p1_mm": [6000, 0], "height_mm": 3000,
         "level": {"by": "ref", "value": "level1"}},
    ]
    SCRIPT = ('lvl = create_level(elev_mm=0, name="L")\n'
              'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, '
              'level=lvl)\n')

    def test_the_same_program_written_two_ways_is_identical_below_the_gate(self):
        """TWO INPUT FORMS — ONE PROOF.

        `plan_digest` covers not only the payload but also the registry's
        typed contracts. Matching digests mean that below the gate the
        compiler received THE SAME THING — that is, there truly is no
        branch for "what if this was a script" down there.
        """
        from_json = compiler.plan_program(
            {"ir_version": "1.0", "ops": self.OPS}, bulk=True)
        authored = _run(serving._authored_input({"program_py": self.SCRIPT}))
        self.assertIsNone(authored.refusal,
                          authored.refusal and authored.refusal["message_ru"])
        from_script = compiler.plan_program(authored.args["program"], bulk=True)
        self.assertEqual(from_script.plan_digest, from_json.plan_digest)

    def test_the_gate_is_the_only_place_that_knows_about_python(self) -> None:
        """STRUCTURALLY, NOT BY AGREEMENT: the instrument's body has no
        right to ask about the script. The only things it knows are which
        BUDGET to measure against (`authored_in_python`) and what the
        journal is signed with (`author_digest`); there can be not a
        single execution fork based on the language of origin.
        """
        import inspect
        body = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertNotIn("program_py", body)
        self.assertNotIn("sandbox", body)
        self.assertNotIn("execute_author_script", body)
        # …while the names the body does know about can be counted on one
        # hand.
        #
        # FOUR, NOT TWO, AS OF 21.08.2026, AND THIS IS NOT A RELAXATION. To
        # the parameter declaration and `pre_macro_bulk`, ONE handoff was
        # added: the body passes the budget on to the chunk driver
        # (`_drive_chunked_program`), because a slice must be measured
        # against the SAME budget as the whole — otherwise splitting the
        # program would silently change its budget. There is STILL no
        # execution fork based on the language of origin: the name is only
        # ever passed along, and is never asked about as a condition
        # anywhere.
        self.assertEqual(body.count("authored_in_python"), 4)
        self.assertNotIn("if authored_in_python", body)


# ═════════════════════════════════════════════════════════════════════════════
# THE INPUT FORMS ARE MUTUALLY EXCLUSIVE
# ═════════════════════════════════════════════════════════════════════════════

class ExactlyOneForm(_DoorHarness):

    def _form_refusal(self, args: dict) -> dict:
        result = self._call_refusing(args)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"], "program_form", result)
        self.assertEqual(result["err"]["code"], "tool.invalid_args")
        # fixed by editing the CALL, and a retry is safe by construction
        self.assertTrue(result["err"]["retryable"])
        self.assertIsNone(result["handoff"])
        return result

    def test_both_forms_at_once_is_a_typed_refusal(self) -> None:
        result = self._form_refusal({
            "program": {"ir_version": "1.0", "ops": [
                {"op": "query_count", "id": "q", "kind": "wall"}]},
            "program_py": 'create_level(elev_mm=0, name="L")'})
        self.assertIn("СРАЗУ", result["message_ru"])

    def test_neither_form_is_a_typed_refusal(self) -> None:
        """Previously such a call would reach the compiler and get
        «программа отклонена компилятором» — a lie: no program had been
        sent."""
        result = self._form_refusal({})
        self.assertIn("program_py", result["message_ru"])

    def test_a_script_that_is_not_text_is_named_by_its_type(self) -> None:
        result = self._form_refusal({"program_py": ["create_level()"]})
        self.assertIn("list", result["message_ru"])

    def test_the_schema_offers_both_and_says_the_rule(self) -> None:
        tools: list = []
        serving.inject_revit_ir_schema(tools)
        params = tools[0]["function"]["parameters"]
        # THERE ARE THREE PROPERTIES, TWO PROGRAM FORMS, and these are
        # DIFFERENT lists. `example` builds nothing — it shows a corpus
        # level as source, so the rule "exactly one of the two" below
        # remains true word for word. That `example` does not count toward
        # the forms is checked by the NEXT test, not this one: the list's
        # composition by itself does not carry that distinction.
        # 19.08: the list grew to five, while the number of PROGRAM FORMS
        # is STILL TWO. `rehearse` ("rehearse and don't write") and
        # `created` ("show the journal of what was created") are not
        # programs — any more than `example` is, which the next test
        # states from both sides. The list is deliberately pinned as
        # COMPLETE: a new input field must go through a test edit, because
        # a field the model reads about but the test does not is exactly
        # the kind of capability with no reader.
        self.assertEqual(sorted(params["properties"]),
                         ["created", "example", "program", "program_py",
                          "rehearse"])
        self.assertEqual(params["properties"]["program_py"]["type"], "string")
        # "exactly one of the two" is stated in words, because `required`
        # does not express this, and none of the tools has yet carried
        # `oneOf` at the root
        self.assertIn("РОВНО ОДНИМ", params["description"])
        self.assertNotIn("required", params)

    def test_the_example_field_is_a_property_and_not_a_third_form(self) -> None:
        """A property in the schema does not make a field a FORM, and the
        distinction is needed from BOTH sides — otherwise the previous test
        would go green simply from the list's composition.

        FROM ABOVE: `example` together with both forms still refuses as
        "both at once" — meaning it does not count toward the forms.
        FROM BELOW: `example` ALONE does not get a "no form at all"
        refusal, even though there is no program in the call — meaning
        this is a legitimate call with no program, not a forgotten third
        form.
        """
        both = self._form_refusal({
            "example": "жилая башня",
            "program": {"ir_version": "1.0", "ops": [
                {"op": "query_count", "id": "q", "kind": "wall"}]},
            "program_py": 'create_level(elev_mm=0, name="L")'})
        self.assertIn("СРАЗУ", both["message_ru"])

        alone = self._call_refusing({"example": "жилая башня"})
        self.assertNotEqual(alone.get("error"), "program_form", alone)


# ═════════════════════════════════════════════════════════════════════════════
# THE SANDBOX'S REFUSAL COMES OUT UNDISTORTED
# ═════════════════════════════════════════════════════════════════════════════

class SandboxRefusalsReachTheModel(_DoorHarness):

    def _refuse(self, script: str) -> dict:
        result = self._call_refusing({"program_py": script})
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "author_script")
        return result

    def test_a_syntax_error_names_the_line_of_the_model(self) -> None:
        result = self._refuse("create_wall(p0_mm=[0,0], p1_mm=[6000,0]\n")
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B001")
        self.assertEqual(diagnostic["script_line"], 1)
        self.assertIn("create_wall", diagnostic["script_line_text"])
        # the line is visible both in the text the model reads and in err.fix
        self.assertIn("строка 1", result["message_ru"])
        self.assertIn("строка 1", result["err"]["fix"])

    def test_a_runtime_error_names_the_line_inside_the_loop(self) -> None:
        result = self._refuse(
            'lvl = create_level(elev_mm=0, name="L")\n'
            'for i in range(3):\n'
            '    create_wall(p0_mm=[0,0], p1_mm=[6000/i, 0], height_mm=3000, '
            'level=lvl)\n')
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B006")
        self.assertEqual(diagnostic["kind"], "ZeroDivisionError")
        self.assertEqual(diagnostic["script_line"], 3)

    def test_a_foreign_import_teaches_instead_of_forbidding(self) -> None:
        """A refusal must TEACH: the model will read "not allowed" as a
        whim and try a neighboring module."""
        result = self._refuse("import numpy as np\n")
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B004")
        # WE ASK THE AUTHORITY, RATHER THAN REPEATING IT. Before 20.08
        # there was a literal "math, itertools, functools" here, and it was
        # a SECOND CARRIER of the whitelist: extending the list would
        # color this test red without saying anything about the subject.
        # The assertion stays the same and non-empty — the refusal must
        # ENUMERATE the whole allowed set, not just say "not allowed".
        from kir import sandbox
        self.assertIn(", ".join(sandbox.allowed_imports_for_env()),
                      result["message_ru"])

    def test_no_frame_of_ours_leaks_into_the_refusal(self) -> None:
        """The model needs to fix ITS OWN code: our frames in the refusal
        would be a repair sent to the wrong address."""
        result = self._refuse("create_wall(p0_mm=[0,0])\n")
        text = json.dumps(result, ensure_ascii=False)
        for ours in ("kir", "site-packages", "Traceback (most recent",
                     "sandbox.py", "dsl.py"):
            self.assertNotIn(ours, text)

    def test_the_bridge_is_never_touched_by_a_refused_script(self) -> None:
        """By itself: `_no_bridge` fails the call, so a green test IS proof
        that the case never reached the bridge. The answer about retryable
        rests on this."""
        self._refuse("while True:\n    pass\n")

    # -- taxonomy -------------------------------------------------------------

    def test_every_sandbox_code_has_a_deliberate_taxonomy_row(self) -> None:
        """Not a single "by default" code: each one is resolved by name.

        🔴 ASKED OF THE DISPATCHER SINCE 02.09.2026. Previously the
        question was put to the `serving._KIR_B_TO_ERRCODE` table — one of
        six where the outcome lived a SECOND time next to the registry's
        `taxonomy` column. The tables were removed, and the property
        stays the same: for every sandbox code the outcome is NAMED, not
        taken as a default by letter.
        """
        from kir import diag
        declared = {value for name, value in vars(diag).items()
                    if name.startswith("SANDBOX_") and isinstance(value, str)}
        unnamed = sorted(c for c in declared if diag.taxonomy_of(c) is None)
        self.assertEqual(unnamed, [],
                         f"коды песочницы без исхода у распорядителя: {unnamed}")
        # The other side: the dispatcher did not invent letter-B codes
        # that the sandbox does not declare (except B1xx — that has its
        # own dispatcher).
        registered_b = {c for c, s in diag.CODES.items()
                        if s.family == "sandbox"}
        self.assertEqual(sorted(registered_b - declared), [])

    def test_recon_row_blames_us_and_is_loud_if_ever_read(self) -> None:
        """A PROBE IN THE TAXONOMY MEANS "OUR BREAKAGE", NOT "A BAD
        SCRIPT".

        The `KIR-B013` line is read ONLY when the structural guard in
        `_stamp_refusal` did not fire — a probe turn cannot reach it by
        construction. So both halves are pinned here:

        * the line's value is `INTERNAL_UNHANDLED` (our defect). Before,
          the line did not exist at all, and the `.get()` default declared
          a probe `KIR_PROGRAM_REFUSED`, that is, it put the blame on the
          AUTHOR;
        * landing here is logged at the ERROR level. The level is
          load-bearing: the sole caller is wrapped in `except Exception`
          with `logger.debug`, so an exception from here would be
          SWALLOWED, while a log entry survives the wrapper.
        """
        from kir.diag import SANDBOX_RECON
        from kir.envelope import ErrCode

        res = {"ok": False, "kir": True, "refused": False,
               "diagnostics": [{"code": SANDBOX_RECON, "message_ru": "разведка"}]}
        with self.assertLogs("kir.serving", level="ERROR") as caught:
            code, _lead = serving._classify_refusal(res)
        self.assertIs(code, ErrCode.INTERNAL_UNHANDLED)
        self.assertTrue(any(SANDBOX_RECON in line for line in caught.output),
                        f"громкая запись не назвала код: {caught.output}")

    def test_a_recon_turn_still_carries_no_error_block(self) -> None:
        """AND THE FIX DID NOT BRING BACK WHAT THE WAVE REMOVED.

        Adding the line to the table makes it easy to roll back the main
        point: a probe would become a refusal again. What is checked here
        is the real path — on a probe turn, `_stamp_refusal` must NOT set
        `err` and must not touch `ok`/`refused`.
        """
        from kir.diag import SANDBOX_RECON

        recon = {"ok": False, "kir": True, "refused": False, "recon": True,
                 "diagnostics": [{"code": SANDBOX_RECON,
                                  "message_ru": "разведка"}]}
        out = serving._stamp_refusal(dict(recon))
        self.assertNotIn("err", out)
        self.assertIs(out.get("ok"), False)
        self.assertIs(out.get("refused"), False)
        self.assertIs(out.get("recon"), True)

    def test_an_author_refusal_is_retryable_and_not_transient(self) -> None:
        """THE ANSWER ABOUT RETRYABLE, PINNED WITH A NUMBER.

        retryable=True — because there was NO effect (the test above
        measures exactly this: the bridge fails the call). The ban on
        retries in this system guards against duplicating a build, and
        there is nothing to duplicate here.
        transient=False — because the same source will give the same
        error; this is what `author_digest` itself rests on. Waiting is
        pointless, the source gets fixed.
        """
        result = self._refuse("import numpy\n")
        self.assertEqual(result["err"]["code"], "kir.program_refused")
        self.assertTrue(result["err"]["retryable"])
        self.assertFalse(result["err"]["transient"])
        self.assertTrue(result["err"]["kir"])
        self.assertEqual(result["err"]["kir_code"], "KIR-B004")

    def test_our_own_defect_is_not_retryable_and_says_what_to_do(self) -> None:
        """B012 is the only one with `blame="sandbox"`. There is nothing
        for the model to fix, and "retryable" would send it off to
        rewrite a script that is already correct."""
        from kir.sandbox import SandboxRefusal, SandboxResult

        broken = SandboxResult(
            ok=False, author_digest="a" * 64,
            refusal=SandboxRefusal(
                code="KIR-B012", kind="NamespaceUnavailable", blame="sandbox",
                message_ru="сетевое пространство имён не создано"))
        with mock.patch("kir.sandbox.execute_author_script",
                        return_value=broken):
            result = self._call_refusing({"program_py": "create_level()"})
        self.assertEqual(result["diagnostics"][0]["blame"], "sandbox")
        self.assertEqual(result["err"]["code"], "internal.unhandled")
        self.assertFalse(result["err"]["retryable"])
        self.assertFalse(result["err"]["transient"])
        # …and NAMES the second input form: the sandbox cannot utter this
        # phrase, it does not know about the `program` field
        self.assertIn("`program`", result["message_ru"])

    def test_a_refused_script_still_signs_its_source(self) -> None:
        """The signature of a source that did NOT compile is just as much
        evidence."""
        result = self._refuse("import numpy\n")
        self.assertEqual(len(result["program_source"]["author_digest"]), 64)
        self.assertEqual(result["program_source"]["op_count"], 0)
        self.assertNotIn("program_digest", result["program_source"])

    def test_the_receipt_reports_measured_isolation_not_intent(self) -> None:
        result = self._refuse("import numpy\n")
        isolation = result["program_source"]["isolation"]
        self.assertIn("namespaces", isolation)
        self.assertIn("filesystem", isolation)
        self.assertIn("network_probe", isolation)

    def test_determinism_is_measured_on_the_production_path(self) -> None:
        """`replay_check` is enabled in prod: a signature nobody has
        verified is a promise, not proof."""
        self.assertTrue(serving._sandbox_policy().replay_check)
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["program_source"]["replay_checked"])


# ═════════════════════════════════════════════════════════════════════════════
# THE BUDGET SEAM — both sides, by name
# ═════════════════════════════════════════════════════════════════════════════

class TheBudgetSeamAfterTheSourceLayer(_DoorHarness):
    """THE UNIT OF AUTHORSHIP DECIDES WHICH BUDGET MEASURES IT.

    The author budget (20) measures the ENUMERATION written by the model.
    When a SCRIPT was sent, the authorial thing is its lines, while the
    operations were written by the front end, and measuring them against
    the author budget is the same seam that cost 318 rounds instead of 26
    on the Snowdon rebuild (30.07). So the script's output is measured
    against the internal budget — and ONLY that: the compilation policy
    changes in no way.
    """

    def _script_of(self, count: int) -> str:
        return (f"for i in range({count}):\n"
                f"    query_count(kind='wall')\n")

    def test_enumeration_still_hits_the_authored_budget(self) -> None:
        """The side that must not be weakened: the `program` field stays as it was."""
        ops = [{"op": "query_count", "id": f"q{i}", "kind": "wall"}
               for i in range(compiler.MAX_OPS_PER_PROGRAM + 1)]
        result = self._call_refusing({"program": {"ir_version": "1.0",
                                                  "ops": ops}})
        self.assertFalse(result["ok"])
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-L001")
        self.assertEqual(diagnostic["expected"],
                         f"<={compiler.MAX_OPS_PER_PROGRAM}")

    def test_a_script_may_exceed_the_authored_budget(self) -> None:
        """Otherwise the door is useless: a script that can manage exactly
        twenty operations is strictly worse than twenty written by hand."""
        count = compiler.MAX_OPS_PER_PROGRAM + 5
        authored = _run(serving._authored_input(
            {"program_py": self._script_of(count)}))
        self.assertIsNone(authored.refusal)
        result = self._call_executing({"program_py": self._script_of(count)})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["program_source"]["op_count"], count)

    def test_a_script_stops_at_the_internal_budget_and_names_it(self) -> None:
        """The ceiling stands in the language too (`dsl._append`), and it
        NAMES what to do next: chunking the direct turn."""
        result = self._call_refusing(
            {"program_py": self._script_of(compiler.MAX_BULK_OPS + 1)})
        self.assertFalse(result["ok"])
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B006")
        self.assertIn(str(compiler.MAX_BULK_OPS), result["message_ru"])
        self.assertIn("чанкование", result["message_ru"])

    def test_the_post_expansion_ceiling_is_untouched(self) -> None:
        """`MAX_VALIDATED_OPS` is the emitter's limit, not policy: no door
        and no input form raises it.

        🔴 THE PIN WAS MOVED 320 -> 22 000 (18.08.2026, by the owner's
        "1000 everywhere" decision). The literal is left here ON PURPOSE —
        it is a tripwire: any move of the limit must be named out loud,
        not slip through silently. A check against the constant itself
        would pass at any value of it.

        THE PROBE, HOWEVER, IS TAKEN FROM THE CONSTANT, and this is not an
        inconsistency: the ASSERTION pins the policy, while the GAUGE must
        land within range. Literal gauges have already, three times now,
        silently stopped exceeding the raised budget — the tests were
        failing not on the subject but on their own ruler."""
        self.assertEqual(compiler.MAX_VALIDATED_OPS, 22000)
        result = self._call_refusing(
            {"program_py": self._script_of(compiler.MAX_VALIDATED_OPS + 1)})
        self.assertFalse(result["ok"])

    def test_a_script_does_not_buy_per_op_isolation(self) -> None:
        """EXACTLY THE BUDGET IS RAISED. A script is compiled with
        `compile_program` (one transaction, strict postconditions, a full
        rollback), and NOT `compile_rebuild_chunk` with per-op isolation
        and report mode: a partially committed program does not become
        the script's right.
        """
        seen: list = []
        real = compiler.compile_rebuild_chunk

        def spy(*args, **kwargs):
            seen.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(compiler, "compile_rebuild_chunk", spy):
            result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen, [], "скрипт пошёл политикой ПЕРЕСБОРКИ чанка")

    def test_the_chat_signature_still_cannot_express_bulk(self) -> None:
        """The law in `test_op_budget_seam` remains true word for word: no
        field and no parameter raises the enumeration budget."""
        import inspect
        forbidden = ("bulk", "internal", "channel", "budget", "cap", "chunk")
        for name in inspect.signature(serving.handle_revit_ir).parameters:
            self.assertFalse(any(tok in name.lower() for tok in forbidden), name)


if __name__ == "__main__":
    unittest.main()
