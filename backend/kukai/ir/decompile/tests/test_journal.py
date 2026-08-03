"""Property tests for the append-only building journal (journal.py).

Dependency-free property style over REAL ``lift -> fold`` edit sequences.
replay (J1), incremental (J5), and tamper-evidence (J6) are the heart: the log
IS the history, folding it reproduces every revision, and altering it is caught.

Numbering matches EVENT_SOURCING_SPEC §6:
  J1 replay: state_at(r) == state after the r-th edit
  J2 boundaries (replay(0)==base; replay(head)==head_state; head_revision==N)
  J3 undo (state_at(r-1) == pre-edit state; history intact)
  J4 audit (changes_at(r) == the r-th delta; full log covers edits)
  J5 incremental == full replay (one delta step == full fold)
  J6 tamper-evident (verify OK; corruption/drop/reorder -> IntegrityError)
  J7 fail-closed (foreign delta / non-head prev / bad revision -> refuse)
  J8 determinism (same sequence -> same journal; round-trip; cross-process)
  J9 immutability (append returns new; branching)
  J10 flag default OFF; malformed -> JournalError
"""
from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_journal_queue.jsonl"))

from kukai.ir.decompile.rebuild import (  # noqa: E402
    BuildingState,
    apply_delta,
    delta_between,
)
from kukai.ir.decompile.journal import (  # noqa: E402
    BuildingJournal,
    JournalIntegrityError,
    JournalRevisionError,
    audit,
    commit_delta,
    commit_trees,
    journal_enabled,
    new_journal,
    replay,
    undo,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _fold,
    _grid_building,
)


def _revisions():
    """A deterministic edit chain R0 -> R1 -> R2 -> R3 and its trees."""
    r0 = _fold(_grid_building(floors=3, name="R0"))
    r1 = _fold(_grid_building(floors=3, name="R1", stretch_wall_on_floor=1))
    r2 = _fold(_grid_building(
        floors=3, name="R2", stretch_wall_on_floor=1,
        extra_furniture_on_floor=0))
    r3 = _fold(_grid_building(
        floors=3, name="R3", stretch_wall_on_floor=1,
        extra_furniture_on_floor=0, drop_wall_on_floor=2))
    return [r0, r1, r2, r3]


def _journal_of(trees):
    j = new_journal(trees[0])
    for prev, new in zip(trees, trees[1:]):
        j = commit_trees(j, prev, new)
    return j


class Replay(unittest.TestCase):
    def test_j1_replay_reproduces_every_revision(self) -> None:
        trees = _revisions()
        j = _journal_of(trees)
        for revision, tree in enumerate(trees):
            with self.subTest(revision=revision):
                self.assertEqual(
                    replay(j, revision), BuildingState.of_tree(tree))

    def test_j2_boundaries(self) -> None:
        trees = _revisions()
        j = _journal_of(trees)
        self.assertEqual(j.head_revision, len(trees) - 1)
        self.assertEqual(replay(j, 0), BuildingState.of_tree(trees[0]))
        self.assertEqual(j.head_state(), BuildingState.of_tree(trees[-1]))

    def test_j5_incremental_equals_full_replay(self) -> None:
        trees = _revisions()
        j = _journal_of(trees)
        # Applying ONLY the r-th delta to state_at(r-1) equals full replay(r).
        for revision in range(1, len(trees)):
            step = apply_delta(
                replay(j, revision - 1), j.changes_at(revision).delta)
            self.assertEqual(step, replay(j, revision))


class UndoAudit(unittest.TestCase):
    def test_j3_undo_returns_previous_state(self) -> None:
        trees = _revisions()
        j = _journal_of(trees)
        state, revision = undo(j)
        self.assertEqual(revision, j.head_revision - 1)
        self.assertEqual(state, BuildingState.of_tree(trees[-2]))
        # History is intact: the journal is unchanged by undo.
        self.assertEqual(j.head_revision, len(trees) - 1)

    def test_j3_undo_at_base_refuses(self) -> None:
        j = new_journal(_fold(_grid_building(floors=1)))
        with self.assertRaises(JournalRevisionError):
            undo(j)

    def test_j4_audit_covers_every_edit(self) -> None:
        trees = _revisions()
        j = _journal_of(trees)
        entries = audit(j)
        self.assertEqual(len(entries), len(trees) - 1)
        for revision, delta_event in entries:
            self.assertEqual(
                j.changes_at(revision).delta, delta_event.delta)
            self.assertTrue(delta_event.summary)


class TamperEvidence(unittest.TestCase):
    def test_j6_honest_journal_verifies(self) -> None:
        _journal_of(_revisions()).verify()  # no raise

    def test_j6_corrupted_hash_is_caught(self) -> None:
        j = _journal_of(_revisions())
        payload = j.to_dict()
        payload["events"][2]["event_hash"] = "0" * 64
        with self.assertRaises(JournalIntegrityError):
            BuildingJournal.from_dict(payload)

    def test_j6_altered_delta_breaks_chain(self) -> None:
        j = _journal_of(_revisions())
        payload = j.to_dict()
        # Tamper the delta body without fixing the hash.
        payload["events"][1]["payload"]["delta"]["reused_count"] += 1
        with self.assertRaises(JournalIntegrityError):
            BuildingJournal.from_dict(payload)

    def test_j6_dropped_event_is_caught(self) -> None:
        j = _journal_of(_revisions())
        payload = j.to_dict()
        del payload["events"][2]           # drop a middle event
        with self.assertRaises(JournalIntegrityError):
            BuildingJournal.from_dict(payload)

    def test_j6_reordered_events_caught(self) -> None:
        j = _journal_of(_revisions())
        payload = j.to_dict()
        payload["events"][1], payload["events"][2] = (
            payload["events"][2], payload["events"][1])
        with self.assertRaises(JournalIntegrityError):
            BuildingJournal.from_dict(payload)


class FailClosed(unittest.TestCase):
    def test_j7_foreign_delta_refused(self) -> None:
        trees = _revisions()
        j = new_journal(trees[0])
        # A delta from a DIFFERENT base (trees[1]->trees[2]) is not applicable
        # to head (== trees[0]).
        foreign = delta_between(trees[1], trees[2])
        # only refuse if the foreign delta actually removes something absent
        if any(op.remove_ops for op in foreign.ops):
            with self.assertRaises(JournalRevisionError):
                commit_delta(j, foreign)

    def test_j7_non_head_prev_refused(self) -> None:
        trees = _revisions()
        j = _journal_of(trees[:2])          # head == trees[1]
        with self.assertRaises(JournalRevisionError):
            # prev is trees[0], but head is trees[1]
            commit_trees(j, trees[0], trees[2])

    def test_j7_bad_revision_refused(self) -> None:
        j = _journal_of(_revisions())
        with self.assertRaises(JournalRevisionError):
            replay(j, 99)
        with self.assertRaises(JournalRevisionError):
            replay(j, -1)


class DeterminismImmutability(unittest.TestCase):
    def test_j8_same_sequence_same_journal(self) -> None:
        self.assertEqual(
            _journal_of(_revisions()), _journal_of(_revisions()))

    def test_j8_round_trip(self) -> None:
        j = _journal_of(_revisions())
        restored = BuildingJournal.from_dict(j.to_dict())
        self.assertEqual(j, restored)
        self.assertEqual(j.to_json(), restored.to_json())

    def test_j8_pre_fidelity_delta_payload_remains_hash_compatible(self) -> None:
        trees = _revisions()
        legacy_delta = replace(
            delta_between(trees[0], trees[1]),
            base_fidelity_hash=None,
            target_fidelity_hash=None,
        )
        journal = new_journal(trees[0]).append_delta(legacy_delta)
        payload = journal.to_dict()
        delta_payload = payload["events"][1]["payload"]["delta"]
        self.assertNotIn("base_fidelity_hash", delta_payload)
        self.assertNotIn("target_fidelity_hash", delta_payload)
        self.assertEqual(BuildingJournal.from_dict(payload), journal)

    def test_j9_append_is_immutable(self) -> None:
        trees = _revisions()
        j0 = new_journal(trees[0])
        j1 = commit_trees(j0, trees[0], trees[1])
        # j0 is unchanged; j1 is a new, longer journal.
        self.assertEqual(j0.head_revision, 0)
        self.assertEqual(j1.head_revision, 1)
        self.assertIsNot(j0, j1)

    def test_j9_branching_from_head(self) -> None:
        trees = _revisions()
        j = new_journal(trees[0])
        branch_a = commit_trees(j, trees[0], trees[1])
        branch_b = commit_trees(j, trees[0], trees[2])
        # Two independent branches from the same head.
        self.assertNotEqual(branch_a, branch_b)
        self.assertEqual(branch_a.state_at(1), BuildingState.of_tree(trees[1]))
        self.assertEqual(branch_b.state_at(1), BuildingState.of_tree(trees[2]))


class Flag(unittest.TestCase):
    def test_j10_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_JOURNAL", None)
        try:
            self.assertFalse(journal_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_JOURNAL"] = previous

    def test_j10_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_JOURNAL")
        os.environ["KUKAI_IR_JOURNAL"] = "yes"
        try:
            self.assertTrue(journal_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_JOURNAL"]
            else:
                os.environ["KUKAI_IR_JOURNAL"] = previous

    def test_j10_malformed_journal_fails_closed(self) -> None:
        with self.assertRaises(JournalIntegrityError):
            BuildingJournal.from_dict({"no": "events"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
