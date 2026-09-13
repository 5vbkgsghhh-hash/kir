"""AN EXPLICIT helper: open the KIR gate's third condition for the duration
of a single test.

WHY. On 13.08.2026 the gate got a third condition (`61e276bb`, an operator
decision): the stage2 flag AND an admin device AND **an explicit KIR mode on
this turn**. An ordinary turn never sets the flag — that is the whole point,
KIR is unreachable in ordinary work BY CONSTRUCTION. But 95 tests were
opening the path with two conditions and started being refused on the third:
`{'ok': False, 'error': 'gate'}`.

A breakdown of the 97 new reds, taken from an AST walk over the test's BODY
(names lie: a regex on "mode" catches `the_model_can_read` and
`record_mode`):

    SUBJECT — the test asserts something ABOUT THE GATE ITSELF        2
    PRECONDITION — the gate is only needed to open the path           95

For the 95, this is not a change of meaning but bringing the fixture back in
line with reality: a test whose precondition production can no longer
satisfy is checking a path a live call never reaches. Giving it the mode back
restores its subject, it does not take one away.

WHY EXPLICIT, NOT AN AUTO-MIXIN. An auto-mixin would turn the mode on even
where its ABSENCE is the very thing under judgment, and would do so
silently. The test calls the helper itself, in one line, and that is visible
on reading.

**WHO NEVER GETS IT, UNDER ANY CONDITIONS** — the list is closed, and every
name here belongs precisely because its meaning lies in the absence of the
third condition:

    tests/test_kir_is_a_separate_mode.py            the operator's ban
    kir/tests/test_gate_refusal_names_the_cause.py   the refusal names its cause
    kir/tests/test_serving.py::DeviceGate      genus SUBJECT
    kir/tests/test_supply_neutrality.py::AdminDeviceAllowList   genus SUBJECT

Give them the helper, and they turn green for nothing, and the operator's
ban would become unguardable two hours after it was nearly lost. Meanwhile
`test_supply_neutrality.py` is MIXED: it has both SUBJECT and PRECONDITION
cases, so a shared `setUp` cannot be used there — **the unit of the
threshold is the subject under judgment, not the file.**

A REVIEW CONDITION, named because the helper is being set up today: it holds
true only while the mode flag is a **fact about the TURN**, set by the
client. It will expire if the mode becomes a property of the SESSION or of
the device: then "turn it on for a turn" will stop being something the
client does, and the tests will again start encoding a contract that does
not exist.

ITS OWN CONTROL LIVES IN `test_gate_fixture_can_fail.py` and is NOT inferred
from the greenness of those 95: a dummy helper would have turned all of them
green, and green for nothing — the gate would still be refusing, only no one
would notice. Ninety-five greens with no act of discrimination are worse
than ninety-five reds: reds are visible.
"""
from __future__ import annotations

import unittest

# A MODULE-LEVEL IMPORT, AND THIS IS NOT STYLE. `kukai.llm` pulls in
# litellm, and on import that runs `load_dotenv()` and pours live
# configuration keys into the process. A lazy import inside `setUp` does
# this DURING THE TEST — and the environment guard in `conftest.py`
# rightfully declares a leak, blaming the test that merely called the
# helper. Measured: the helper's first edition produced 32 errors in a
# couple of files where there had been 13 reds before it.
#
# At module level, the import happens during test COLLECTION, i.e. inside
# the snapshot conftest takes before the run, and creates no leak.
# 27.08.2026: we ask the PORT, not the product by name. The KIR-mode flag is
# a concept of the HOST, and a standalone language has no such thing.
#
# 🔴 THERE WILL BE NO DUMMY STUB HERE. Substituting `lambda: False` would
# make the tests that need the mode GREEN BY CONSTRUCTION. Without a port,
# the helper SKIPS the test with a named reason: a skip is visible, a
# vacuous green is not.
from kir import ports

try:
    _ХОД = ports.need(ports.TURN_CONTEXT)
    _ПРИЧИНА = ""
except ports.PortMissing as _exc:                          # pragma: no cover
    _ХОД, _ПРИЧИНА = None, str(_exc)


def enter_kir_mode(case: unittest.TestCase) -> None:
    """Declare that THIS test's turns run in KIR mode; restore as it was.

    The OBSERVED value is restored, not the constant `False`: the flag
    lives in a `ContextVar`, and a test that overwrote someone else's state
    with its own constant fixes global state as a side effect — exactly the
    crutch we already pulled out of `test_any_query`.
    """
    if _ХОД is None:                                        # pragma: no cover
        case.skipTest("режим КИР — понятие ХОСТА, а не языка: " + _ПРИЧИНА)
    observed = _ХОД.kir_mode_active()
    _ХОД.publish_kir_mode(True)
    case.addCleanup(_ХОД.publish_kir_mode, observed)
