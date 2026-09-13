"""The beam's reference-level witness: it was weakened CORRECTLY — and it
can still fail.

THE HISTORY WITHOUT WHICH THIS FILE FIXES SOMETHING ALREADY FIXED. In the
corpus `data/telemetry/kir_witness.jsonl` there are twelve red
`create_beam` rows, all on 27.07 (Revit 2023), all bearing one signature:

    13:05:17  KIR-X004  geometry_ok=true semantic_ok=true topology_ok=false
              ["BM3: level binding mismatch (topology)"]
    13:18:45  ["leg_sw: … leg_se: … leg_ne: … leg_nw: … f0a: … f0b: …
               f1a: … f1b: … f2a: … f2b: level binding mismatch (topology)"]
    13:22:47  ["base_test_tower: level binding mismatch (topology)"]

The last one is 13:22:47. Commit `158fadc9`, "the beam witness demanded
something Revit never promised" — 13:23:40, 53 seconds later; the first
green beam is at 13:23:16 (prod imports the working tree, so a fix is
live before the commit). So the defect was real and ALREADY CLOSED.
Fixing the emitter here would be fixing the wrong thing.

WHAT REVIT ACTUALLY GUARANTEES. Measured live on 27.07: L_01 @ 0 mm was
passed, the curve was placed at Z=3000 — the binding went to
L_01ДОО1_+2.500, the nearest one below. The `level` argument of
`NewFamilyInstance(Line, …, StructuralType.Beam)` is placement CONTEXT,
not a promise. So equality cannot be required; the invariant Revit
actually holds is that the reference level EXISTS. Which one exactly is
read from the witness (`reference_level_id`/`reference_level`), not
imposed.

WHY THIS FILE EXISTS THEN. A "witness that stopped asking" is
indistinguishable from "a witness that cannot fail," and the existing
pins
(`test_struct.py::test_topology_reference_level_and_structuraltype_semantic`,
`test_hangs_and_lies.py::BeamLevelWitnessMustReadTheParameterABeamActuallyHas`)
check for the PRESENCE of the new line and the ABSENCE of the old one —
but neither checks that the surviving check is even capable of firing.
Both holes are closed here:

  1. the check cannot be DELETED — the translation certificate refuses
     (mutation);
  2. the check cannot be GUTTED — the emitted condition is evaluated on
     three MEASURED parameter states and must fire on the two bad ones.

The states are not invented, they come from that same 27.07 trial:

    INSTANCE_REFERENCE_LEVEL_PARAM = 172458 («L_01_+0.000»)   -> silent
    FAMILY_LEVEL_PARAM  HasValue=True  AsElementId=-1          -> MUST fail
    LEVEL_PARAM         no such parameter (get_Parameter -> null) -> MUST fail

It was exactly the second state that broke the OLD chain: `HasValue` is
true even for InvalidElementId, so the chain broke on an empty link and
compared "-1" against the expected id. The surviving check must catch
this state — otherwise the weakening went further than the measurement
allows.
"""
from __future__ import annotations

import copy
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_beam_queue.jsonl"))

from kir import ground as ground_mod  # noqa: E402
from kir import spec, struct_emit  # noqa: E402
from kir.compiler import _parse_and_check, compile_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.translation_cert import certify_op  # noqa: E402

_BEAM = {"op": "create_beam", "id": "B",
         "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
         "level": {"by": "element_id", "value": 42},
         "symbol": {"by": "element_id", "value": 1000}}


def _prog():
    return {"ir_version": "1.0", "intent": "балка", "ops": [copy.deepcopy(_BEAM)]}


def _beam_cs() -> str:
    out = compile_program(_prog(), revit_version="2023",
                          snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


def _reference_level_condition(cs: str) -> str:
    """Extracts the guard's EMITTED condition — does not rewrite it."""
    block = cs[cs.index("INSTANCE_REFERENCE_LEVEL_PARAM"):]
    m = re.search(r"if \((.*?)\)\n\s*__post\.Add", block, re.S)
    assert m, "сторож опорного уровня не найден в эмитированном C#"
    return " ".join(m.group(1).split())


# The dictionary is CLOSED on purpose: a new term in the condition must
# bring the author here and force him to name the measured state under
# which it is true. Otherwise the test would silently let a gutted guard
# through.
def _term(term: str, *, param_exists: bool, as_element_id: int) -> bool:
    term = term.strip()
    if term == "__rl == null":
        return not param_exists
    if term == "__rl.AsElementId() == null":
        # For an existing parameter, AsElementId() returns -1, not null —
        # exactly why the old chain relying on `HasValue` used to miss.
        return False
    if term == "__rl.AsElementId() == ElementId.InvalidElementId":
        return as_element_id == -1
    raise AssertionError(
        f"незнакомый терм в стороже опорного уровня: {term!r} — допишите его "
        "в закрытый словарь и назовите замеренное состояние")


def _guard_fires(condition: str, *, param_exists: bool,
                 as_element_id: int) -> bool:
    """Evaluates the condition with short-circuit `||`, the way C# does."""
    for term in condition.split("||"):
        if _term(term, param_exists=param_exists,
                 as_element_id=as_element_id):
            return True
    return False


class TheSurvivingBeamWitnessCanStillFail(unittest.TestCase):
    """The main point: a weakened witness must still be able to fail."""

    def setUp(self):
        self.condition = _reference_level_condition(_beam_cs())

    def test_a_beam_with_a_real_reference_level_passes(self):
        """Otherwise the witness would always fail — the second way to
        be useless."""
        self.assertFalse(_guard_fires(self.condition, param_exists=True,
                                      as_element_id=172458))

    def test_an_empty_link_still_fails_the_witness(self):
        """The state that used to break the OLD chain (HasValue=True,
        AsElementId=-1) must remain a violation: a beam with no level is
        a real defect."""
        self.assertTrue(_guard_fires(self.condition, param_exists=True,
                                     as_element_id=-1))

    def test_a_missing_parameter_still_fails_the_witness(self):
        self.assertTrue(_guard_fires(self.condition, param_exists=False,
                                     as_element_id=-1))

    def test_the_guard_is_not_a_constant(self):
        """A direct statement of non-vacuity: the guard has both a
        firing case and a silent one."""
        fires = {_guard_fires(self.condition, param_exists=p, as_element_id=e)
                 for p, e in ((True, 172458), (True, -1), (False, -1))}
        self.assertEqual(fires, {True, False})


class TheBeamWitnessCannotBeSilentlyDeleted(unittest.TestCase):
    """A C5-style mutation: remove the check — the certificate must
    refuse."""

    def _certificate(self):
        grounded = ground_mod.ground(_parse_and_check(_prog()), GROUND_SNAPSHOT)
        return certify_op(grounded[0], "2023")

    def test_baseline_is_proven(self):
        cert = self._certificate()
        self.assertTrue(cert.proven, cert.gaps)

    def test_dropping_the_reference_level_check_breaks_the_certificate(self):
        """🔴 THE PATCH GOES WHERE DISPATCH ACTUALLY LOOKS (fixed
        02.09.2026).

        Before the layering wave, `authoring` held a WRAPPER — `return
        struct_emit.emit_beam(...)` — meaning it looked up the function
        by module name AT CALL TIME, and patching the module attribute
        worked. The wave removed the wrappers: each satellite declares
        its own `EMITTERS`, the hub COLLECTS the registry, and
        `authoring._EMITTERS["create_beam"]` holds the function OBJECT
        ITSELF. From that day on, patching `struct_emit.emit_beam` went
        nowhere — the FAIL control stopped gutting anything and turned
        red with "True is not false," blaming the certificate for
        something it never did.

        What is patched is the registry, and the FACT OF THE PATCH IS
        VERIFIED BY A COUNTER: a control that silently stopped patching
        is a green bought with blindness.
        """
        from kir import authoring
        original = authoring._EMITTERS["create_beam"]
        звали = []

        def hollowed(op, ver, stamp, isolation="atomic"):
            звали.append(1)
            decl, create, checks, readback = original(op, ver, stamp, isolation)
            return decl, create, [c for c in checks
                                  if c.obligation_key != "reference_level"], readback

        authoring._EMITTERS["create_beam"] = hollowed
        try:
            cert = self._certificate()
        finally:
            authoring._EMITTERS["create_beam"] = original
        self.assertTrue(звали, "подменённый эмиттер НЕ ЗВАЛСЯ — контроль ничего "
                               "не выхолостил, и его вердикт ни о чём")
        self.assertFalse(cert.proven)
        self.assertTrue(any("reference_level" in g for g in cert.gaps),
                        cert.gaps)


class TheBeamLevelIsNotASilentlyInjectedDefault(unittest.TestCase):
    """The task's second hard condition, answered by MEASUREMENT, not by
    reasoning.

    The rule from `tests/test_silent_defaults.py`: a silently
    substituted default must not be witnessed — the emitter cannot tell
    "this was explicitly requested" from "nothing was said." For
    `create_beam` the question is settled at the registry level: none of
    its parameters carries a default, and `level` is mandatory on top of
    that."""

    def test_create_beam_declares_no_defaults_at_all(self):
        defaulted = [p.name for p in spec.OPS["create_beam"].params
                     if getattr(p, "default", None) is not None]
        self.assertEqual(defaulted, [])

    def test_the_level_operand_is_required_so_silence_is_impossible(self):
        level = next(p for p in spec.OPS["create_beam"].params
                     if p.name == "level")
        self.assertTrue(level.required)


class TheOldEqualityDemandStaysGone(unittest.TestCase):
    """A regression lock against bringing back an equality the API
    never promised."""

    def test_no_level_binding_equality_for_a_beam(self):
        cs = _beam_cs()
        self.assertNotIn("level binding mismatch", cs)
        self.assertIn("нет опорного уровня (topology)", cs)
        # The level IS READ into the result — the weakening did not lose
        # observability.
        self.assertIn('"reference_level_id"', cs)
        self.assertIn('"reference_level"', cs)


if __name__ == "__main__":
    unittest.main()
