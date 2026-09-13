"""THE TRANSLATION CERTIFICATE IN THE LIVE WRITE PATH — an instrument that is finally switched on.

WHAT WAS WRONG BEFORE 09.08.2026.  ``translation_cert`` can prove that
every promised postcondition has a witness and that this witness IS CAPABLE
of firing (17 vacuum forms, 940 op instances, 0 findings, a traversal of 3748 out of
3748 verdicts).  Yet the LIVE WRITE PATH never called it, not once: the gate
``KUKAI_IR_TRANSLATION_CERT`` was read only from the tests, and
``tools/capability_map.py`` honestly reported «НА СКЛАДЕ».  A vacuum detector
that never looks at the real program protects nothing — it is
a signature in place of a check.

WHAT IS PINNED DOWN HERE, one class per section:

  * MODES — one flag, three states, and "on" cannot drift apart from
    "refuses";
  * THE ABSENT STAYS ABSENT — with the flag off, the write path is
    byte-for-byte the same, and the certifier is not invoked AT ALL;
  * A FINDING REFUSES BEFORE THE EFFECT — an implanted vacuum witness wraps the
    write in a typed diagnostic bound to the op, and the bridge sees
    nothing but the ground snapshot;
  * OBSERVATION WRITES, IT DOES NOT FORBID — ``record`` mode lets the same
    program through, but the receipt names the finding;
  * THE CONTRACT PRECEDES THE INSTRUMENT — a new write op without an
    ``OpRefinementSpec`` gets a typed plan refusal before the Bridge;
  * SILENCE FROM AN OPTIONAL INSTRUMENT IS NOT A FINDING — an already honestly planned
    program is not wrapped by either an unavailable certifier table or its own
    exception. This is exactly the boundary at which acceptance once broke on
    Cyrillic and for months wrapped up CORRECTLY built rooms.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_cert_wiring_queue.jsonl"),
)

from kir import authoring                                    # noqa: E402
from kir import serving                                      # noqa: E402
from kir import translation_cert as tc                       # noqa: E402
from kir.compiler import plan_program                        # noqa: E402
from kir.emit_model import BarePost, WitnessCheck            # noqa: E402
from kir.tests.acceptance_fakes import (                     # noqa: E402
    PassingAcceptanceBridge,
)
from kir.tests.fixtures import GROUND_SNAPSHOT               # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode
from kir.tests.envtools import подменить_env  # noqa: E402




_FLAG = "KUKAI_IR_TRANSLATION_CERT"

WRITE_PROGRAM = {"ir_version": "1.0", "ops": [{
    "op": "create_wall",
    "id": "W1",
    "p0_mm": [0, 0],
    "p1_mm": [6000, 0],
    "level": {"by": "element_id", "value": 42},
}]}

#: A seedling: a verdict that CANNOT succeed on any run.
DEAD_VERDICT = '    if (false) __post.Add("never");\n'

def _paths(left, right, prefix: str = "") -> set[str]:
    """The addresses of the fields by which two receipts DIFFER.

    This test cannot be written with a "volatile fields" list eyeballed by hand: the list
    would go stale silently and turn the proof into decoration.  The noise
    level IS MEASURED (two runs under identical conditions), and only then is the
    flag's effect compared against it.
    """

    if isinstance(left, dict) and isinstance(right, dict):
        out: set[str] = set()
        for key in set(left) | set(right):
            out |= _paths(left.get(key), right.get(key), f"{prefix}.{key}")
        return out
    if (isinstance(left, list) and isinstance(right, list)
            and len(left) == len(right)):
        out = set()
        for index, (one, two) in enumerate(zip(left, right)):
            out |= _paths(one, two, f"{prefix}[{index}]")
        return out
    return set() if left == right else {prefix}


@contextlib.contextmanager
def planted(op_name: str, key: str, verdict_cs: str):
    """Implant a vacuum verdict into the witness ``key`` of the live op ``op_name``.

    A mutation, not a made-up dictionary: exactly the emitter that writes C# in
    production is what gets certified.
    """

    original = authoring._EMITTERS[op_name]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
                continue
            out.append(WitnessCheck(
                obligation_key=check.obligation_key,
                reader_cs="",
                verdict_cs=verdict_cs,
                message=check.message,
                tol=None,
                style="plain"))
        return decl, create, (BarePost(tuple(out)) if bare else out), readback

    authoring._EMITTERS[op_name] = broken
    try:
        yield
    finally:
        authoring._EMITTERS[op_name] = original


class Modes(unittest.TestCase):
    """One flag, three states — and they cannot contradict one another."""

    def setUp(self) -> None:
        self._previous = os.environ.get(_FLAG)

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop(_FLAG, None)
        else:
            подменить_env(self, _FLAG, self._previous)

    def _set(self, value) -> None:
        if value is None:
            os.environ.pop(_FLAG, None)
        else:
            подменить_env(self, _FLAG, value)

    def test_default_is_off(self) -> None:
        self._set(None)
        self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_OFF)
        self.assertFalse(tc.certificate_enabled())

    def test_truthy_values_refuse(self) -> None:
        for value in ("1", "true", "yes", "on", "refuse", "REFUSE", " On "):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_REFUSE)
                self.assertTrue(tc.certificate_enabled())

    def test_record_is_on_but_does_not_refuse(self) -> None:
        for value in ("record", "observe", "RECORD"):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_RECORD)
                self.assertTrue(tc.certificate_enabled())

    def test_enabled_and_mode_can_never_disagree(self) -> None:
        """The flip side: there is NO value where the instrument is "on" but has
        no mode, and no value with a mode while the instrument is off."""

        for value in (None, "", "0", "off", "no", "false", "1", "on", "yes",
                      "true", "refuse", "record", "observe", "мусор", "2"):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(
                    tc.certificate_enabled(),
                    tc.certificate_mode() != tc.CERT_MODE_OFF,
                    f"{value!r}: «включён» и режим разъехались")


class _ServingHarness(unittest.TestCase):
    """The live write path with a deterministic bridge (without Revit)."""

    def setUp(self) -> None:
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        self._dir = tempfile.TemporaryDirectory()
        self._prev_dir = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._dir.name)
        self._prev_flag = os.environ.get(_FLAG)
        os.environ.pop(_FLAG, None)
        # THE THIRD GATE CONDITION (13.08): KIR mode is set EXPLICITLY.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        if self._prev_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            подменить_env(self, "KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_dir)
        if self._prev_flag is None:
            os.environ.pop(_FLAG, None)
        else:
            подменить_env(self, _FLAG, self._prev_flag)
        self._dir.cleanup()

    def _write(self, program=WRITE_PROGRAM) -> tuple[dict, list[str]]:
        """(the turn's result, the list of stages the bridge SAW)."""

        acceptance = PassingAcceptanceBridge(program)
        seen: list[str] = []

        async def execute(_llm, _bridge, _code, op, _timeout_ms):
            seen.append(op)
            if op == "ground_snapshot":
                result = {"result": GROUND_SNAPSHOT}
            else:
                result = {"result": {"ok": True, "W1": {"id": "9001"}}}
            return acceptance.dispatch(lambda _c, _o: result, _code, op)

        with mock.patch.object(
                serving, "_run_declarative", side_effect=execute):
            result = asyncio.run(serving.handle_revit_ir(
                {"program": copy.deepcopy(program)}, self.llm, None))
        return result, seen


class AbsentStaysAbsent(_ServingHarness):
    """A cleared flag must change NOTHING — not a byte, not a call."""

    def test_flag_off_never_calls_the_certifier(self) -> None:
        with mock.patch.object(
                serving, "_certify_translation",
                side_effect=AssertionError(
                    "сертификатор вызван при снятом флаге")) as spy:
            result, _seen = self._write()
        self.assertEqual(spy.call_count, 0)
        self.assertTrue(result["ok"])

    def test_flag_off_leaves_no_trace_in_the_receipt(self) -> None:
        result, seen = self._write()
        self.assertTrue(result["ok"])
        self.assertNotIn("certificate", result)
        self.assertNotIn("ground_snapshot", seen[1:])

    def test_a_proven_program_is_byte_identical_apart_from_the_receipt(self):
        """A switched-on instrument on a HEALTHY emitter does not change the outcome.

        This is half of the law "the absent stays absent": the second
        half is that switching it on does not change the RESULT where there is no finding.
        If it did, the cost of switching it on would be unknown.
        """

        os.environ.pop(_FLAG, None)
        first, _ = self._write()
        second, _ = self._write()
        # THE NOISE LEVEL, MEASURED RATHER THAN DECLARED: two runs under identical
        # conditions (the run identifier, the journal checksum,
        # the building's cumulative counter).
        noise = _paths(first, second)
        self.assertTrue(
            noise, "шума нет вовсе — замер сломан, сравнивать не с чем")

        подменить_env(self, _FLAG, "1")
        on, _ = self._write()
        moved = _paths(second, on) - noise
        self.assertEqual(
            moved, {".certificate"},
            f"включение прибора сдвинуло квитанцию сверх квитанции: {moved}")

        certificate = on["certificate"]
        self.assertEqual(certificate["status"], "proven")
        self.assertEqual(certificate["mode"], tc.CERT_MODE_REFUSE)
        self.assertFalse(certificate["refused"])
        self.assertEqual(certificate["ops"], 1)
        self.assertIsInstance(certificate["duration_ms"], float)


class AFindingRefusesBeforeAnyEffect(_ServingHarness):
    """A witness that cannot fail does not let the write happen."""

    def test_planted_vacuity_refuses_with_a_typed_op_bound_diagnostic(self):
        подменить_env(self, _FLAG, "1")
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, seen = self._write()

        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(result["stage"], "translation_certificate")
        # The refusal does not lead off into free-floating C#: there will be no witness there at all.
        self.assertIsNone(result["handoff"])

        lead = result["diagnostics"][0]
        self.assertEqual(lead["code"], "KIR-R002")
        self.assertEqual(lead["op_id"], "W1")
        self.assertEqual(lead["op_index"], 0)
        self.assertEqual(lead["field_name"], "endpoints")
        self.assertEqual(lead["got"], tc.VACUITY_CONSTANT_FALSE)
        self.assertIn("вакуумный свидетель", lead["message_ru"])

        # THERE IS NO EFFECT BY CONSTRUCTION: the bridge saw exactly the ground snapshot and
        # nothing more — no acceptance read, no write.
        self.assertEqual(seen, ["ground_snapshot"])
        self.assertEqual(result["outcome"]["execution"], "not_started")

    def test_the_refusal_carries_a_machine_readable_err(self) -> None:
        подменить_env(self, _FLAG, "1")
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, _ = self._write()
        self.assertEqual(result["err"]["kir_code"], "KIR-R002")
        self.assertEqual(result["err"]["op_id"], "W1")
        self.assertTrue(result["err"]["kir"])

    def test_a_missing_witness_refuses_under_its_own_code(self) -> None:
        """"There is no witness" and "the witness exists and is dead" are different defects and
        must arrive under different codes."""

        подменить_env(self, _FLAG, "1")
        original = authoring._EMITTERS["create_wall"]

        def broken(op, ver, stamp, isolation="atomic"):
            decl, create, post, rb = original(op, ver, stamp, isolation)
            bare = isinstance(post, BarePost)
            checks = [c for c in (post.checks if bare else post)
                      if c.obligation_key != "endpoints"]
            return decl, create, (BarePost(tuple(checks)) if bare
                                  else checks), rb

        authoring._EMITTERS["create_wall"] = broken
        try:
            result, seen = self._write()
        finally:
            authoring._EMITTERS["create_wall"] = original

        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "translation_certificate")
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertEqual(codes, {"KIR-R001"})
        self.assertEqual(seen, ["ground_snapshot"])


class ObservationRecordsButDoesNotForbid(_ServingHarness):
    """Different behavior must be reachable through CONFIGURATION, not through a code change."""

    def test_record_mode_lets_the_same_program_through_and_says_so(self):
        подменить_env(self, _FLAG, "record")
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, seen = self._write()

        self.assertTrue(result["ok"], "режим наблюдения не должен запрещать")
        self.assertIn("ground_snapshot", seen)
        self.assertGreater(len(seen), 1, "запись не дошла до моста")

        certificate = result["certificate"]
        self.assertEqual(certificate["mode"], tc.CERT_MODE_RECORD)
        self.assertEqual(certificate["status"], "vacuous")
        self.assertFalse(certificate["refused"])
        # The finding IS RECORDED, not lost: an observation with no trace is silence,
        # and silence is indistinguishable from cleanliness.
        self.assertEqual(certificate["diagnostics"][0]["code"], "KIR-R002")
        self.assertEqual(certificate["diagnostics"][0]["op_id"], "W1")


class SilenceOfTheInstrumentIsNotAFinding(_ServingHarness):
    """The boundary on which "acceptance broke on Cyrillic".

    An instrument that DID NOT HAVE ENOUGH data must stay silent and be NAMED, rather than
    wrapping up a correctly built program because of our own bookkeeping.
    """

    def test_missing_refinement_refuses_before_any_bridge_call(self) -> None:
        """Incomplete OpContract is a typed planning refusal, not P000."""

        подменить_env(self, _FLAG, "1")
        table = tc._ensure_table()
        previous = tc.REFINEMENT
        tc.REFINEMENT = {k: v for k, v in table.items() if k != "create_wall"}
        try:
            result, seen = self._write()
        finally:
            tc.REFINEMENT = previous

        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(seen, [], "Bridge touched before OpContract refusal")
        self.assertEqual(result["outcome"]["execution"], "not_started")
        self.assertEqual(len(result["diagnostics"]), 1)
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-L007")
        self.assertEqual(diagnostic["op_index"], 0)
        self.assertEqual(diagnostic["op_id"], "W1")
        self.assertEqual(diagnostic["field_name"], "op")
        self.assertEqual(diagnostic["got"], "create_wall")
        self.assertNotEqual(diagnostic["code"], "KIR-P000")

    def test_optional_instrument_silence_does_not_refuse_preplanned_write(
            self) -> None:
        """Instrument drift after an honest immutable plan is not a finding."""

        подменить_env(self, _FLAG, "1")
        planned = plan_program(copy.deepcopy(WRITE_PROGRAM))
        table = tc._ensure_table()
        previous = tc.REFINEMENT
        tc.REFINEMENT = {k: v for k, v in table.items() if k != "create_wall"}
        try:
            result, seen = self._write(planned)
        finally:
            tc.REFINEMENT = previous

        self.assertTrue(result["ok"], "молчание прибора завернуло запись")
        self.assertGreater(len(seen), 1)
        certificate = result["certificate"]
        self.assertEqual(certificate["status"], "uncertifiable")
        self.assertFalse(certificate["refused"])
        self.assertIn("create_wall", certificate["detail"])

    def test_a_crashing_certifier_does_not_refuse(self) -> None:
        подменить_env(self, _FLAG, "1")
        with mock.patch.object(
                tc, "certify_program",
                side_effect=RuntimeError("прибор сломался")):
            result, seen = self._write()

        self.assertTrue(result["ok"], "сломанный прибор завернул запись")
        self.assertGreater(len(seen), 1)
        certificate = result["certificate"]
        self.assertEqual(certificate["status"], "instrument_failed")
        self.assertFalse(certificate["refused"])
        self.assertIn("RuntimeError", certificate["detail"])

    def test_a_query_is_never_certified(self) -> None:
        """A query has neither a witness nor obligations: REFINEMENT knows nothing
        about it by construction, and attempting to certify it would be a refusal
        of the entire reading path."""

        подменить_env(self, _FLAG, "1")

        async def execute(_llm, _bridge, _code, _op, _timeout_ms):
            return {"result": {"Q1": {"total": 0, "rows": []}}}

        with mock.patch.object(
                serving, "_run_declarative", side_effect=execute):
            result = asyncio.run(serving.handle_revit_ir({"program": {
                "ir_version": "1.0",
                "ops": [{"op": "query_count", "id": "Q1", "kind": "wall"}],
            }}, self.llm, None))

        self.assertNotIn("certificate", result)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
