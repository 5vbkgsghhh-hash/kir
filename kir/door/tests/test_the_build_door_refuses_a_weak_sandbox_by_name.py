"""G6 — the door executes somebody else's python, so the profile is a GATE.

ОПР-17, measured: in the WEAKENED profile the network is CONNECTED,
`os.execv('/bin/echo')` replaces the interpreter, and `execve` is absent from
seccomp (`grep -n execve kir/sandbox.py` -> 0). "No right to run weakened"
has to be a number; here it is one.
"""
from __future__ import annotations

from kir.door import registry as R
from kir.door.build import is_strict_policy, kir_build

SOURCE = 'program = [create_level(id="L1", elev_mm=0, name="Этаж 1")]'


def test_the_default_policy_of_the_tree_is_strict():
    from kir.sandbox import DEFAULT_POLICY

    assert is_strict_policy(DEFAULT_POLICY)
    assert DEFAULT_POLICY.filesystem_isolation is True
    assert str(DEFAULT_POLICY.network) == "required"


def test_a_weakened_policy_is_refused_by_name_before_any_execution():
    from kir.sandbox import SandboxPolicy

    weak = SandboxPolicy(filesystem_isolation=False)
    assert not is_strict_policy(weak)
    out = kir_build({"source": SOURCE}, R.Ctx(role="expert"), policy=weak)
    assert out["ok"] is False
    assert out["err"]["code"] == "weak_sandbox"
    # Nothing ran: no executor was even asked for, and the refusal says why
    # rather than blaming the program.
    assert out["wrote_nothing"] is True
    assert "ослабленном" in out["err"]["message_ru"]


def test_the_refusal_names_the_next_move_and_it_is_a_tool():
    from kir.sandbox import SandboxPolicy

    for role, expected in (("expert", "question_to_lead"), ("lead", "ask_user")):
        ctx = R.Ctx(role=role)
        out = kir_build({"source": SOURCE}, ctx,
                        policy=SandboxPolicy(filesystem_isolation=False))
        nxt = out["next"]["do"]
        assert nxt == expected
        # and it is a real tool of SOME role — never a variable, never prose
        assert nxt in {t.name for t in R.TOOLS}


def test_an_unreadable_policy_counts_as_not_strict():
    """Doubt means no. A policy object we cannot interrogate has no right to
    be taken for the strict one."""
    class Opaque:
        def __getattr__(self, name):  # noqa: D105
            raise RuntimeError("opaque")

    assert not is_strict_policy(Opaque())
    assert not is_strict_policy(None)


def test_control_a_silent_run_under_a_weak_policy_goes_red():
    """If the check were removed, a weakened policy would reach the sandbox.
    The control asserts the door's answer DIFFERS between strict and weak —
    identical answers would mean the gate does nothing."""
    from kir.sandbox import DEFAULT_POLICY, SandboxPolicy

    weak = kir_build({"source": SOURCE}, R.Ctx(role="expert"),
                     policy=SandboxPolicy(filesystem_isolation=False))
    strict = kir_build({"source": SOURCE}, R.Ctx(role="expert"),
                       policy=DEFAULT_POLICY)
    assert weak["err"]["code"] == "weak_sandbox"
    assert strict.get("err", {}).get("code") != "weak_sandbox"
