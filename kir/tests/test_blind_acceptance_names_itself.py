"""AN INSTRUMENT'S BLINDNESS IS OBLIGATED TO NAME ITSELF, NOT SEND THE AUTHOR OFF TO HUNT FOR SOMEONE ELSE'S DEFECT.

🔴 WHY THIS FILE EXISTS (08.24, bought by two live runs). Acceptance's census
is blind to part of the ops BY CONSTRUCTION: for `author_family` the category
is brought in by a template file from the user's machine, and the census
cell is never derived from the program at all. Such an op always returns
`inconclusive` — even with a committed commit and a satisfied witness.

The refusal text in this case said exactly the same thing as for a real read
failure: "check the model." For an author whose program worked, this is an
address to nowhere — and they followed it honestly: `author_family` burned
10 and 11 turns across two runs in a row, never once building.

The same kind of defect as `HAB000` ("no rooms in the model" instead of
"levels are not declared") and `design_check`: the instrument complains
about the SUBJECT where the fault is its own scope.
"""
from __future__ import annotations

from kir.acceptance import BlindOp
from kir.acceptance_evidence import AcceptanceReason, AcceptanceState
from kir.serving import _acceptance_diagnostic


class _Expectation:
    def __init__(self, blind_ops):
        self.blind_ops = tuple(blind_ops)


class _Registration:
    """The double is obligated to reproduce the FORM of real registration, not a convenient one.

    🔴 08.24: it reproduced exactly the carrier the function read
    (`expectation.blind_ops`) — and that is why this file was GREEN while
    prod stayed silent: for the live `create_type`, blindness comes from the
    carrier of the MUTATION. The double now hands out `blind_ops` the same
    way the real `AcceptanceRegistration` does, and the neighboring test
    (`test_blind_reason_reaches_both_readers`) holds so that this property
    does not disappear from the real class.
    """

    def __init__(self, blind_ops):
        self.expectation = _Expectation(blind_ops)
        self.blind_ops = tuple(blind_ops)


class _Evidence:
    def __init__(self, blind_ops, reason):
        self.state = AcceptanceState.INCONCLUSIVE
        self.reason = reason
        self.registration = _Registration(blind_ops)


_BLIND = BlindOp("AF1", "author_family",
                 "категорию семейства приносит ФАЙЛ ШАБЛОНА с машины "
                 "пользователя")


def test_blind_scope_says_it_is_our_boundary_not_their_defect():
    d = _acceptance_diagnostic(
        _Evidence([_BLIND], AcceptanceReason.PARTIAL_BLIND_SCOPE))
    assert d["code"] == "KIR-A007"
    msg = d["message_ru"]
    assert "ЗАКОММИЧЕНА" in msg
    assert "слепа ПО ПОСТРОЕНИЮ" in msg
    # The main point: the author is told NOT TO REPEAT. Ten turns were burned
    # exactly by repeating something that had already worked.
    assert "не надо" in msg.lower()
    assert "проверь модель" not in msg


def test_the_blind_op_is_named_with_its_reason():
    """A "blind" op with no name is indistinguishable from "forgot": nothing to fix."""
    d = _acceptance_diagnostic(
        _Evidence([_BLIND], AcceptanceReason.PARTIAL_BLIND_SCOPE))
    assert "author_family" in d["detail"]
    assert "ФАЙЛ ШАБЛОНА" in d["detail"]
    assert d["blind_ops"][0]["op"] == "author_family"
    assert d["acceptance_reason"] == "partial_blind_scope"


def test_a_real_unfinished_read_still_sends_the_author_to_the_model():
    """🔴 CONTROL-FAIL. When there are NO blind ops, "not finished" means that
    the re-read never happened — and that is a genuine reason to look at the model.
    A fix has no right to eat this case together with blindness."""
    d = _acceptance_diagnostic(
        _Evidence([], AcceptanceReason.POST_READ_UNAVAILABLE))
    assert d["code"] == "KIR-A007"
    assert "проверь модель" in d["message_ru"]
    assert "blind_ops" not in d
