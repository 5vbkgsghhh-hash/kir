"""A reconnaissance turn is an ANSWER. The tree says so; the door now agrees.

`kir/diag.py` about `KIR-B013` (`SANDBOX_RECON`): "`refused` is no longer true,
and no `err` block is set — **recon is not an error, it is an answer to the
question asked**." The sandbox returns `ok=False` because there is no program
and no record evidence — which is not the same as a fault.

🔴 FOUND BY A LIVE MODEL, 13.09.2026 (S's M5 run through this door): the door
carried a non-refusal inside a refusal envelope. And this is not cosmetic —
asking the language FROM INSIDE THE SCRIPT is the cheapest move an agent has
(`spec("create_wall")`, answer in the same receipt, no second trip), and the
door was punishing exactly it.
"""
from __future__ import annotations

from kir.door import registry as R
from kir.door.build import _RECON_CODE

RECON = 'print(create_level.__doc__[:60])'
BROKEN = 'program = [нет_такой_функции()]'


def test_the_code_comes_from_diag_and_not_from_a_literal():
    from kir.diag import SANDBOX_RECON

    assert _RECON_CODE == SANDBOX_RECON == "KIR-B013"


def test_a_recon_turn_is_ok_and_says_what_it_learned():
    out = R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))
    assert out["ok"] is True
    assert out["recon"] is True
    assert out["built"] is False
    assert out["wrote_nothing"] is True
    assert out["ops"] == 0
    assert "create_level" in out["words"]


def test_a_recon_turn_carries_no_error_envelope():
    """The defect in its exact shape."""
    out = R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))
    assert "err" not in out
    assert out.get("refused") is not True


def test_a_recon_turn_hands_over_the_next_move():
    out = R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))
    assert out["next"]["do"] == "kir_build"


def test_a_recon_turn_leaves_no_write_trace():
    """No program was built, so there is no identity to trace — the same law as
    a sandbox refusal."""
    out = R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))
    assert "trace" not in out


def test_in_script_reading_is_reported_so_the_budget_is_not_charged_twice():
    """A `spec()` call inside the script never went through `kir_read`, so it
    costs nothing against the expert's `help_calls` ceiling of 4. An expert
    charged twice for one question spends its budget on arithmetic."""
    out = R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))
    assert "help_in_script" in out
    assert R.budget()["help_calls"] == 4


def test_a_real_mistake_is_still_a_refusal():
    """The fix separated two kinds; it did not make everything green."""
    out = R.call("kir_build", {"source": BROKEN}, R.Ctx(role="expert"))
    assert out["ok"] is False
    assert out["err"]["code"] != _RECON_CODE
    assert out["next"]["do"] in {t.name for t in R.TOOLS}


def test_control_wrapping_recon_in_a_refusal_goes_red():
    from kir.sandbox import DEFAULT_POLICY, execute_author_script

    authored = execute_author_script(RECON, policy=DEFAULT_POLICY)
    # The sandbox itself says `ok=False` — that is what misled the door.
    assert authored.ok is False
    assert authored.refusal.code == _RECON_CODE
    # And the door must NOT repeat it.
    assert R.call("kir_build", {"source": RECON}, R.Ctx(role="expert"))["ok"] is True
