"""A SECTION'S DECISION SURVIVES A NEIGHBOR'S REBUILD. TODAY — 12 OF 12, IT
WAS 0.

🔴 AN OWNER'S REQUIREMENT FROM 02.09.2026 THAT WAS NOT IN THE PLAN. "A
multi-agent environment will build in KIR" — meaning the structural agent
(KR) has no right to demolish a decision by the architecture agent (AR).
Recon BEFORE construction (`kir/tests/test_a_decision_is_not_an_element.py`)
overturned the intended shape: `BuildingState` is declared by its own
docstring as "a multiset of canonical ops", `leaves_to_program` sets ZERO
envelope keys — a decision at the PROGRAM level gets demolished BY
CONSTRUCTION by a neighbor, whatever shape it was recorded in. The number
back then was **0 out of N by construction**.

A durable carrier must sit where a rebuild READS FROM, not where it
REBUILDS. There is exactly one such place in the tree — the REVISION
JOURNAL. A decision became ITS OWN EVENT there, and from that follow all
four properties of the gate.

THE SUBJECT OF MEASUREMENT IS NAMED HONESTLY. Three REAL decompile journals
sit on disk and are UNREADABLE (`-rw-------`, owner `kukai`) — the subject
of the owner's E-8 sheet. So the measurement runs on the tree's own
sample buildings (`test_merkle`), the same ones it uses to check its own
Merkle hashes: a grid with 44 different ops out of 60, a cluster 21 out of
21.
"""
from __future__ import annotations

import json
import unittest

from kir.decompile import journal as J
from kir.decompile.rebuild import BuildingState, DeltaOp, DeltaProgram
from kir.decompile.tests import test_merkle as M


def _снять(canon: str, n: int) -> DeltaOp:
    return DeltaOp(kind="retire", reason="removed", path=None, hash=None,
                   remove_ops=tuple([canon] * n), add_ops=(),
                   remove_source_ids=(), add_source_ids=())


def _поставить(canon: str) -> DeltaOp:
    return DeltaOp(kind="emit", reason="added", path=None, hash=None,
                   remove_ops=(), add_ops=(canon,),
                   remove_source_ids=(), add_source_ids=())


def _дельта(*ops: DeltaOp) -> DeltaProgram:
    return DeltaProgram(ops=ops, reused_count=0)


def _здание(документ) -> BuildingState:
    return BuildingState.of_tree(M._fold(документ))


class РешениеПереживаетПересборку(unittest.TestCase):
    """🔴 THE MAIN NUMBER OF STAGE 4.1."""

    def setUp(self) -> None:
        self.здания = [("сетка", M._grid_building()),
                       ("кластер", M._cluster_building())]

    def _с_решениями(self, документ):
        с = _здание(документ)
        топ = с.as_counter().most_common(5)
        ж = J.new_journal(с)
        for canon, n in топ:
            ж = ж.append_decision(J.DecisionEvent(
                discipline="architectural", mode="keep", canon=canon, count=n,
                addressed_to=None, note="несущая ось АР, не сносить"))
        return ж, топ

    def test_все_решения_переживают_пересборку_соседа(self) -> None:
        записано = пережило = 0
        for имя, док in self.здания:
            ж, _топ = self._с_решениями(док)
            # THE DENOMINATOR: an empty journal would pass the check vacuously
            self.assertGreaterEqual(len(ж.decisions_at()), 5, имя)
            записано += len(ж.decisions_at())
            # the neighbor REBUILDS: the same state, an empty delta
            после = ж.append_delta(_дельта())
            пережило += len(после.decisions_at())
            self.assertEqual(после.violations(), (), имя)
        self.assertEqual((записано, пережило), (10, 10),
                         "решение обязано пережить пересборку соседа; до "
                         "02.09.2026 переживало 0 ПО ПОСТРОЕНИЮ")

    def test_решение_не_двигает_состояние(self) -> None:
        """The journal's discipline: state is a multiset of `canon_op`.

        A decision that ended up in the state would make reproduction
        depend on intentions, and a rebuild — non-repeatable.
        """
        for имя, док in self.здания:
            до = _здание(док)
            ж, _ = self._с_решениями(док)
            self.assertEqual(ж.head_state(), до, имя)

    def test_снос_решённого_отвергнут_и_НАЗВАН(self) -> None:
        for имя, док in self.здания:
            ж, топ = self._с_решениями(док)
            canon0, n0 = топ[0]
            with self.assertRaises(J.JournalDecisionError) as e:
                ж.append_delta(_дельта(_снять(canon0, n0)))
            текст = str(e.exception)
            self.assertIn("architectural", текст, имя)
            self.assertIn("keep", текст, имя)
            self.assertIn("несущая ось АР", текст,
                          "отказ обязан нести СЛОВА решившего, а не пересказ")

    def test_дырка_видна_адресату_и_закрывается_наблюдением(self) -> None:
        """Closing a gap is an observable fact, not a neighbor's intention."""
        док = self.здания[0][1]
        ж = J.new_journal(_здание(док)).append_decision(J.DecisionEvent(
            discipline="architectural", mode="hole", canon="__ЖДЁМ_КР__",
            count=1, addressed_to="structural",
            note="здесь ждут КР: колонна на пересечении"))
        self.assertEqual(len(ж.open_holes("structural")), 1)
        self.assertEqual(len(ж.open_holes("mechanical")), 0,
                         "дырка видна ТОЛЬКО своему адресату")
        # an unfilled gap is open work, NOT a violation
        self.assertEqual(ж.violations(), ())
        закрыто = ж.append_delta(_дельта(_поставить("__ЖДЁМ_КР__")))
        self.assertEqual(len(закрыто.open_holes("structural")), 0)

    def test_решение_переживает_круг_через_диск(self) -> None:
        """A carrier that gets lost on write is not a carrier."""
        for имя, док in self.здания:
            ж, _ = self._с_решениями(док)
            круг = J.BuildingJournal.from_dict(json.loads(ж.to_json()))
            круг.verify()          # the hash chain covers decisions
            self.assertEqual(len(круг.decisions_at()), len(ж.decisions_at()), имя)
            self.assertEqual(круг.head_state(), ж.head_state(), имя)


class РешениеОтказываетНАЗВАННО(unittest.TestCase):

    def setUp(self) -> None:
        self.состояние = _здание(M._grid_building())
        self.canon = self.состояние.as_counter().most_common(1)[0][0]

    def test_решение_о_несуществующем_отвергнуто(self) -> None:
        """A decision about something that is not in the state is a promise, not a decision."""
        ж = J.new_journal(self.состояние)
        with self.assertRaises(J.JournalDecisionError) as e:
            ж.append_decision(J.DecisionEvent(
                discipline="architectural", mode="keep",
                canon="__НИКОГДА_НЕ_БЫЛО__", count=1, addressed_to=None,
                note=""))
        self.assertIn("обещание", str(e.exception))

    def test_раздел_вне_закрытого_списка_реестра_отвергнут(self) -> None:
        """Sections are `spec.DISCIPLINES`, not made-up ones like "AR/KR/HVAC"."""
        ж = J.new_journal(self.состояние)
        with self.assertRaises(J.JournalDecisionError) as e:
            ж.append_decision(J.DecisionEvent(
                discipline="АР", mode="keep", canon=self.canon, count=1,
                addressed_to=None, note=""))
        self.assertIn("вне закрытого списка", str(e.exception))

    def test_дырка_без_адресата_отвергнута(self) -> None:
        ж = J.new_journal(self.состояние)
        with self.assertRaises(J.JournalDecisionError) as e:
            ж.append_decision(J.DecisionEvent(
                discipline="architectural", mode="hole", canon="__X__",
                count=1, addressed_to=None, note=""))
        self.assertIn("некому её увидеть", str(e.exception))


class ЖурналБезРешенийВЕДЁТСЕБЯКАКПРЕЖДЕ(unittest.TestCase):
    """🔴 INERT BY CONSTRUCTION, NOT BY A FLAG.

    A journal with no decisions performs NOT ONE extra check: the
    protection switches on because someone RECORDED a decision. Otherwise
    the addition would change the behavior of everyone already using the
    journal — and it is declared «inert, additive, opt-in».
    """

    def test_дельта_принимается_как_прежде(self) -> None:
        с = _здание(M._grid_building())
        canon = с.as_counter().most_common(1)[0][0]
        ж = J.new_journal(с)
        self.assertEqual(ж.decisions_at(), ())
        self.assertEqual(ж.violations(), ())
        # demolition WITH NO decisions goes through: forbidding it would be a new policy
        после = ж.append_delta(_дельта(_снять(canon, 1)))
        self.assertEqual(len(после), 2)
        self.assertEqual(после.head_state().as_counter().get(canon, 0),
                         с.as_counter()[canon] - 1)


if __name__ == "__main__":
    unittest.main()
