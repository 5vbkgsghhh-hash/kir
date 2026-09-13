"""THE OPERATION PHASE GRAPH IS CLOSED, AND THIS IS CHECKED BY A NUMBER, NOT
BY MEMORY.

WHY THIS FILE APPEARED ON 30.08.2026 (audit finding F-330).

`transition_allowed` is the ONLY guard on an operation's phase:
`store.py:119` raises `OperationConflict`, and there are no other checks.
Before F-330, anything not caught by the five exception branches was
resolved by comparing RANKS, and so `CREATED -> ACKNOWLEDGED` was ALLOWED:
an operation never once sent could be declared terminally accepted with
outcome `CommittedVerified`.

🔴 BUT THAT IS NOT THE MAIN POINT. When the fix was ready, a counter on a
substituted name showed that across a run of six suites (142 passed,
EXIT=0), `transition_allowed` was called **ZERO times**: nowhere in the
whole KIR tree was there a single test that touches it. So a green suite
would say nothing about a broken graph — neither before the fix nor after.
Fifty-one forbidden pairs would have stayed without a guard.

The only consumers are `kir/operations/store.py` (inside KIR) and the live
owner `kukai/api/bridge_protocol.py` (OUTSIDE KIR, not checked by this
tree). So what is guarded here is exactly what can be guarded from here: the
graph's properties and its completeness.
"""
from __future__ import annotations

import unittest

from kir.operations.protocol import (
    OperationPhase as P,
    PHASE_RANK,
    _ALLOWED_TRANSITIONS,
    transition_allowed,
)

#: Transitions the LIVE OWNER ACTUALLY MAKES. The list is closed and was
#: taken from `kukai/api/bridge_protocol.py` by reading it on 29.08.2026. It
#: is here because a graph written "as it should be" rather than "as it is"
#: would break prod within the first hour: the client reports to the server
#: neither ACCEPTED_CLIENT, nor QUEUED_REVIT, nor STARTED — it all travels in
#: one receipt, and `SENT -> RECEIPT_DELIVERED_SERVER` must remain legal.
#:
#: 🔴 THIS LIST IS NOT CHECKED FOR COMPLETENESS BY THIS TREE: it is about a
#: FOREIGN tree, and KIR has no right to reach into it. It guards one thing
#: only — that we do not forbid what the owner does today.
LIVE_HOST_TRANSITIONS: tuple[tuple[P, P], ...] = (
    (P.CREATED, P.PERSISTED_SERVER),
    (P.PERSISTED_SERVER, P.DISPATCH_CLAIMED),
    (P.DISPATCH_CLAIMED, P.SENT),
    (P.SENT, P.RECEIPT_DELIVERED_SERVER),
    (P.SENT, P.RUNNING_UNKNOWN),
    (P.RUNNING_UNKNOWN, P.COMMITTED),
    (P.COMMITTED, P.VERIFIED),
    (P.RECEIPT_DELIVERED_SERVER, P.ACKNOWLEDGED),
)

#: Phases, each of which ASSERTS that execution took place or that its
#: outcome is known. Reaching any of them without having sent the operation
#: means declaring a building side effect where no one observed it.
PHASES_ASSERTING_EXECUTION = frozenset({
    P.COMMITTED, P.COMMITTED_PARTIAL, P.ROLLED_BACK,
    P.VERIFIED, P.UNVERIFIED, P.ACKNOWLEDGED,
    P.RECEIPT_PERSISTED_CLIENT, P.RECEIPT_DELIVERED_SERVER,
})

#: Phases BEFORE any bytes could have gone out on the wire.
PHASES_BEFORE_THE_WIRE = (P.CREATED, P.PERSISTED_SERVER)

#: The number of allowed pairs (idempotent-retry loops included). The number
#: is a RATCHET: a silent expansion of the graph must turn red. Measured at
#: F-330: it was 151.
ALLOWED_PAIR_COUNT = 100


class ГрафПолонИЗакрыт(unittest.TestCase):

    def test_every_phase_has_a_row(self) -> None:
        """A new phase with no row would give a KeyError AT RUNTIME FOR A
        USER."""
        self.assertEqual(set(_ALLOWED_TRANSITIONS), set(P))

    def test_the_allowed_pair_count_is_pinned(self) -> None:
        """The number guards EXPANSION. Narrowing the graph can be done
        deliberately — then this constant is edited too; silent widening
        cannot happen."""
        pairs = sum(1 for a in P for b in P if transition_allowed(a, b))
        self.assertEqual(pairs, ALLOWED_PAIR_COUNT)

    def test_a_replay_of_the_same_phase_is_idempotent(self) -> None:
        for phase in P:
            with self.subTest(phase=phase.value):
                self.assertTrue(transition_allowed(phase, phase))

    def test_an_unknown_phase_is_refused_not_guessed(self) -> None:
        self.assertFalse(transition_allowed("нет такой фазы", P.SENT))
        self.assertFalse(transition_allowed(P.SENT, "нет такой фазы"))


class ЧтоНеОтправлено_ТоНеИсполнено(unittest.TestCase):
    """THE SUBJECT OF F-330, verbatim."""

    def test_nothing_before_the_wire_may_claim_execution(self) -> None:
        for old in PHASES_BEFORE_THE_WIRE:
            for nxt in sorted(PHASES_ASSERTING_EXECUTION, key=lambda p: p.value):
                with self.subTest(переход=f"{old.value}->{nxt.value}"):
                    self.assertFalse(
                        transition_allowed(old, nxt),
                        "операция, ни разу не отправленная, объявлена "
                        "исполненной: побочный эффект здания либо случился и "
                        "не записан, либо не случится никогда")

    def test_the_rank_fallback_would_have_allowed_them(self) -> None:
        """THE NARROWNESS CONTROL, and it matters more than the others:
        without it, the test above is green both on the graph and on any
        stricter rule, i.e. it does not prove that what got fixed was
        SPECIFICALLY the rank comparison."""
        было_бы_разрешено = [
            (old, nxt)
            for old in PHASES_BEFORE_THE_WIRE
            for nxt in PHASES_ASSERTING_EXECUTION
            if PHASE_RANK[nxt] >= PHASE_RANK[old]
        ]
        self.assertTrue(
            было_бы_разрешено,
            "ранг больше не разрешает ничего из этого — предмет теста исчез, "
            "и тест обязан быть переписан, а не оставлен зелёным")


class ДоказанноеНеПонижается(unittest.TestCase):

    def test_verified_and_unverified_are_different_facts(self) -> None:
        """Both have rank 80, and so rank allowed rewriting one into the
        other IN BOTH DIRECTIONS."""
        self.assertEqual(PHASE_RANK[P.VERIFIED], PHASE_RANK[P.UNVERIFIED])
        self.assertFalse(transition_allowed(P.VERIFIED, P.UNVERIFIED))
        self.assertFalse(transition_allowed(P.UNVERIFIED, P.VERIFIED))

    def test_a_started_execution_cannot_become_never_started(self) -> None:
        self.assertFalse(
            transition_allowed(P.STARTED, P.CANCELLED_BEFORE_START))


class ЖивойХозяинНеСломан(unittest.TestCase):

    def test_every_live_host_transition_is_allowed(self) -> None:
        for old, nxt in LIVE_HOST_TRANSITIONS:
            with self.subTest(переход=f"{old.value}->{nxt.value}"):
                self.assertTrue(
                    transition_allowed(old, nxt),
                    "запрещён переход, который живой хозяин делает СЕГОДНЯ")


if __name__ == "__main__":
    unittest.main()
