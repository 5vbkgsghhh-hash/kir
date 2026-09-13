"""THE PROGRAM JOURNAL OUTLIVES THE PROCESS, AND "DIDN'T LOOK" IS
DISTINGUISHABLE FROM "EMPTY."

THE MEASUREMENT THAT PAID FOR THIS FILE (18.08.2026). `tools/axes_duel.py` —
an honest-comparison instrument, "the real project versus what KIR builds" —
was built, run, and **refused for lack of a subject**: there were NO
complete KIR programs anywhere in the tree. `live/journal.py` had **0 disk
accesses**, despite its own header promising "the journal is versioned,
diffed, replayed."

Run:
    venv/bin/python -m pytest kir/tests/test_journal_store.py -q
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from kir.live import journal, journal_store as S

#: 🔴 THE ROOT AFTER THE SPLIT (28.08.2026). `parents[3]` from
#: `kir/kir/tests/x.py` gives `/opt` — a directory where our package sits
#: next to other people's trees. Before 27.08 the same count from
#: `backend/kukai/ir/tests/x.py` gave the install root. The correct root is
#: the one the package sits INSIDE.
BACKEND = pathlib.Path(__file__).resolve().parents[2]


def _rec(seq: int, ops, stage: str = "planned"):
    return journal.ProgramRecord(seq=seq, ts=0.0, ops=tuple(ops), stage=stage)


class TheStoreWritesAndReadsBack(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._dir.name) / "kir_programs.jsonl"
        self._saved = os.environ.get(S.PATH_ENV)
        os.environ[S.PATH_ENV] = str(self.path)
        journal.reset()

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(S.PATH_ENV, None)
        else:
            os.environ[S.PATH_ENV] = self._saved
        journal.reset()
        self._dir.cleanup()

    def test_a_missing_file_is_a_named_refusal_not_an_empty_answer(self):
        rows, why = S.read_events()
        self.assertEqual(rows, ())
        self.assertTrue(why, "пустой ответ без причины неотличим от «пусто»")
        self.assertIn(str(self.path), why)

    def test_an_empty_read_says_so_with_an_empty_refusal(self):
        self.path.write_text("", encoding="utf-8")
        rows, why = S.read_events()
        self.assertEqual((rows, why), ((), ""),
                         "«смотрел, там пусто» — единственный случай, где "
                         "причина обязана быть ПУСТОЙ")

    def test_the_switch_off_is_a_named_refusal_too(self):
        os.environ[S.PATH_ENV] = ""
        rows, why = S.read_events()
        self.assertEqual(rows, ())
        self.assertIn("выключен", why)

    def test_a_broken_line_is_skipped_and_counted(self):
        S.record_program(("d", "k"), _rec(0, [{"op": "create_wall", "id": "w1"}]))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("{это не json\n")
        rows, why = S.read_events()
        self.assertEqual(len(rows), 1, "битая строка спрятала целую")
        self.assertIn("битых", why, "битая строка проглочена молча")

    def test_an_unknown_event_kind_is_counted_not_dropped(self):
        S.record_program(("d", "k"), _rec(0, [{"op": "create_wall", "id": "w1"}]))
        S.append_line(self.path, {"schema": S.SCHEMA, "event": "из будущего",
                                  "device_id": "d", "doc_key": "k", "seq": 9})
        rows, why = S.read_events()
        self.assertEqual(len(rows), 1)
        self.assertIn("неизвестного рода", why,
                      "файл переживает версии кода: «не понял» и «не было» — "
                      "разные факты")

    def test_the_file_is_private(self):
        S.record_program(("d", "k"), _rec(0, [{"op": "create_wall", "id": "w1"}]))
        mode = self.path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600,
                         "склад несёт координаты чужого проекта — права строже "
                         "umask, и это решение, а не деталь")


class TheJournalFeedsTheStore(unittest.TestCase):
    """The wire: a live journal must lay down the same thing on disk."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._dir.name) / "p.jsonl"
        self._saved = os.environ.get(S.PATH_ENV)
        os.environ[S.PATH_ENV] = str(self.path)
        journal.reset()

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(S.PATH_ENV, None)
        else:
            os.environ[S.PATH_ENV] = self._saved
        journal.reset()
        self._dir.cleanup()

    def test_append_lands_on_disk(self):
        key = journal.key_for("dev", "doc")
        journal.append(key, {"ops": [{"op": "create_wall", "id": "w1",
                                      "p0_mm": [0, 0, 0]}]})
        rows, why = S.read_events()
        self.assertEqual(why, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], S.EVENT_PROGRAM)
        self.assertEqual(rows[0]["ops"][0]["p0_mm"], [0, 0, 0],
                         "координаты остаются ЦЕЛИКОМ — программа без них не "
                         "программа (см. границу приватности в шапке склада)")

    def test_only_a_move_that_happened_is_stored(self):
        """The monotonicity law is not repeated in the store — it is not
        bypassed."""
        key = journal.key_for("dev", "doc")
        journal.append(key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertTrue(journal.advance(key, 0, "committed"))
        self.assertFalse(journal.advance(key, 0, "planned"),
                         "назад по главной линии ходить нельзя")
        rows, _ = S.read_events()
        stages = [r for r in rows if r["event"] == S.EVENT_STAGE]
        self.assertEqual([s["stage"] for s in stages], ["committed"],
                         "в складе оказался переход, которого в здании не было")

    def test_the_hot_path_survives_a_broken_store(self):
        """A store failure has NO right to drop the turn."""
        os.environ[S.PATH_ENV] = str(self.path / "нельзя" / "сюда.jsonl")
        key = journal.key_for("dev", "doc")
        self.path.write_text("", encoding="utf-8")   # a file instead of a directory
        rec = journal.append(key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertIsNotNone(rec, "склад уронил горячий путь")
        self.assertEqual(len(journal.get(key).records), 1)

    def test_what_memory_evicted_the_disk_still_has(self):
        """The main promise: the building survives eviction."""
        saved = os.environ.get("KUKAI_KIR_JOURNAL_PROGRAMS")
        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "8"
        try:
            key = journal.key_for("dev", "doc")
            for i in range(20):
                journal.append(key, {"ops": [{"op": "create_wall", "id": f"w{i}"}]})
            live = journal.get(key)
            self.assertEqual(len(live.records), 8, "потолок памяти не сработал")
            self.assertEqual(live.programs_evicted, 12)
        finally:
            if saved is None:
                os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)
            else:
                os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = saved
        rows, why = S.read_events()
        self.assertEqual(why, "")
        programs = S.replay(rows, key)
        self.assertEqual(len(programs), 20,
                         "склад потерял то, ради чего заведён: память "
                         "вытеснила 12 программ, диск обязан их помнить")

    def test_late_commit_needs_bound_id_and_authenticated_matching_receipt(self):
        key = journal.key_for("dev", "doc")
        operation_id = "11111111-1111-5111-8111-111111111111"
        other_id = "22222222-2222-5222-8222-222222222222"
        record = journal.append(
            key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertIsNotNone(record)
        self.assertTrue(journal.bind_operation_id(key, 0, operation_id))
        self.assertTrue(journal.advance(key, 0, "dispatched"))
        self.assertTrue(journal.advance(key, 0, "running_unknown"))
        self.assertFalse(
            journal.advance(key, 0, "committed"),
            "ordinary stage advancement must not escape running_unknown",
        )
        receipt = {
            "protocol_version": 2,
            "turn_id": "acceptance-run",
            "action_id": "action",
            "operation_id": operation_id,
            "payload_hash": "a" * 64,
            "outcome": "CommittedVerified",
            "transaction_status": "Committed",
        }
        self.assertFalse(journal.reconcile_late_commit(
            key, operation_id, receipt, identity_verified=False))
        self.assertFalse(journal.reconcile_late_commit(
            key, other_id, receipt, identity_verified=True))
        self.assertFalse(journal.reconcile_late_commit(
            key, operation_id, {**receipt, "outcome": "CommittedPartial"},
            identity_verified=True))

        self.assertTrue(journal.reconcile_late_commit(
            key, operation_id, receipt, identity_verified=True))
        committed = journal.get(key).records[0]
        self.assertEqual(committed.stage, "committed")
        self.assertEqual(
            committed.operation_ids, (operation_id,),
        )
        self.assertRegex(committed.late_receipt_digest, r"^[0-9a-f]{64}$")
        self.assertTrue(
            journal.reconcile_late_commit(
                key, operation_id, receipt, identity_verified=True),
            "the same durable receipt replay must be idempotent",
        )
        self.assertFalse(journal.reconcile_late_commit(
            key,
            operation_id,
            {**receipt, "unexpected_second_receipt": True},
            identity_verified=True,
        ))

        rows, why = S.read_events()
        self.assertEqual(why, "")
        replayed = S.replay(rows, key)
        self.assertEqual(replayed[0]["stage"], "committed")
        self.assertEqual(
            replayed[0]["operation_ids"], [operation_id])
        self.assertEqual(
            replayed[0]["late_receipt_digest"],
            committed.late_receipt_digest,
        )

    def test_legacy_record_without_operation_id_cannot_reconcile(self):
        key = journal.key_for("dev", "doc")
        journal.append(
            key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertTrue(journal.advance(key, 0, "dispatched"))
        self.assertTrue(journal.advance(key, 0, "running_unknown"))
        receipt = {
            "operation_id": "11111111-1111-5111-8111-111111111111",
            "outcome": "CommittedVerified",
        }
        self.assertFalse(journal.reconcile_late_commit(
            key, receipt["operation_id"], receipt, identity_verified=True))
        self.assertEqual(journal.get(key).records[0].stage, "running_unknown")

    def test_next_chunk_cannot_bind_after_the_program_committed(self):
        key = journal.key_for("dev", "doc")
        first = "11111111-1111-5111-8111-111111111111"
        second = "22222222-2222-5222-8222-222222222222"
        journal.append(
            key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertTrue(journal.bind_operation_id(key, 0, first))
        self.assertTrue(journal.advance(key, 0, "committed"))
        self.assertFalse(
            journal.bind_operation_id(key, 0, second),
            "a terminal program must not acquire a new unexecuted chunk",
        )
        self.assertEqual(
            journal.get(key).records[0].operation_ids, (first,))

    def test_one_chunk_receipt_cannot_commit_a_multi_chunk_program(self):
        key = journal.key_for("dev", "doc")
        first = "11111111-1111-5111-8111-111111111111"
        second = "22222222-2222-5222-8222-222222222222"
        journal.append(
            key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertTrue(journal.bind_operation_id(key, 0, first))
        self.assertTrue(journal.bind_operation_id(key, 0, second))
        self.assertTrue(journal.advance(key, 0, "dispatched"))
        self.assertTrue(journal.advance(key, 0, "running_unknown"))
        self.assertFalse(journal.reconcile_late_commit(
            key,
            first,
            {
                "operation_id": first,
                "outcome": "CommittedVerified",
                "transaction_status": "Committed",
            },
            identity_verified=True,
        ))
        record = journal.get(key).records[0]
        self.assertEqual(record.stage, "running_unknown")
        self.assertFalse(record.is_built)

    def test_partial_commit_is_terminal_and_never_expands_to_full_program(self):
        key = journal.key_for("dev", "doc")
        journal.append(
            key, {"ops": [
                {"op": "create_wall", "id": "w1"},
                {"op": "create_wall", "id": "w2"},
            ]})
        self.assertTrue(journal.advance(key, 0, "dispatched"))
        self.assertTrue(journal.advance(key, 0, "committed_partial"))
        entry = journal.get(key)
        self.assertEqual(entry.records[0].stage, "committed_partial")
        self.assertEqual(entry.built(), [])
        self.assertEqual(entry.standing(), [])
        self.assertFalse(journal.advance(key, 0, "committed"))

    def test_unknown_operation_can_reconcile_after_journal_restore(self):
        key = journal.key_for("dev", "doc")
        operation_id = "11111111-1111-5111-8111-111111111111"
        journal.append(
            key, {"ops": [{"op": "create_wall", "id": "w1"}]})
        self.assertTrue(journal.bind_operation_id(key, 0, operation_id))
        self.assertTrue(journal.advance(key, 0, "dispatched"))
        self.assertTrue(journal.advance(key, 0, "running_unknown"))

        journal.reset()
        restored = journal.restore(key)
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(journal.get(key).records[0].operation_ids,
                         (operation_id,))
        self.assertFalse(journal.reconcile_late_commit(
            key,
            operation_id,
            {
                "operation_id": operation_id,
                "outcome": "CommittedUnverified",
            },
            identity_verified=True,
        ))
        self.assertEqual(journal.get(key).records[0].stage, "running_unknown")
        self.assertFalse(journal.reconcile_late_commit(
            key,
            operation_id,
            {
                "operation_id": operation_id,
                "outcome": "CommittedVerified",
            },
            identity_verified=True,
        ))
        self.assertTrue(journal.reconcile_late_commit(
            key,
            operation_id,
            {
                "operation_id": operation_id,
                "outcome": "CommittedVerified",
                "transaction_status": "Committed",
            },
            identity_verified=True,
        ))
        self.assertEqual(journal.get(key).records[0].stage, "committed")


class TheReplayAndExport(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._dir.name) / "p.jsonl"
        self._saved = os.environ.get(S.PATH_ENV)
        os.environ[S.PATH_ENV] = str(self.path)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(S.PATH_ENV, None)
        else:
            os.environ[S.PATH_ENV] = self._saved
        self._dir.cleanup()

    def test_the_last_stage_wins_and_a_ghost_is_not_born(self):
        S.record_program(("d", "k"), _rec(0, [{"op": "create_wall", "id": "w1"}]))
        S.record_stage(("d", "k"), 0, "dispatched")
        S.record_stage(("d", "k"), 0, "committed")
        S.record_stage(("d", "k"), 7, "committed")   # there is no body
        rows, _ = S.read_events()
        programs = S.replay(rows, ("d", "k"))
        self.assertEqual(len(programs), 1, "стадия без тела родила призрак")
        self.assertEqual(programs[0]["stage"], "committed")

    def test_v1_store_rows_remain_readable(self):
        S.append_line(self.path, {
            "schema": "kir-journal-store/1",
            "event": S.EVENT_PROGRAM,
            "ts": "2026-08-31T00:00:00Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "planned",
            "ops": [{"op": "create_wall", "id": "w1"}],
        })
        rows, why = S.read_events()
        self.assertEqual(why, "")
        programs = S.replay(rows, ("d", "k"))
        self.assertEqual(len(programs), 1)
        self.assertNotIn("operation_ids", programs[0])

    def test_v1_and_malformed_rows_cannot_forge_operation_identity(self):
        valid_program = {
            "schema": "kir-journal-store/1",
            "event": S.EVENT_PROGRAM,
            "ts": "2026-08-31T00:00:00Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "running_unknown",
            "ops": [{"op": "create_wall", "id": "w1"}],
        }
        S.append_line(self.path, valid_program)
        S.append_line(self.path, {
            **valid_program,
            "event": S.EVENT_OPERATION,
            "operation_id": "11111111-1111-5111-8111-111111111111",
        })
        S.append_line(self.path, {
            "schema": S.SCHEMA,
            "event": S.EVENT_OPERATION,
            "ts": "2026-08-31T00:00:01Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "operation_id": {"похоже": "на id после str"},
        })
        S.append_line(self.path, {
            "schema": S.SCHEMA,
            "event": S.EVENT_STAGE,
            "ts": "2026-08-31T00:00:02Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "committed",
            "reconciled": True,
            "operation_id": "11111111-1111-5111-8111-111111111111",
            "receipt_digest": "не sha",
        })

        rows, why = S.read_events()
        self.assertEqual(len(rows), 1)
        self.assertIn("битых строк 3", why)
        with self.assertRaisesRegex(ValueError, "непроверенную"):
            S.replay(({
                "schema": S.SCHEMA,
                "event": S.EVENT_OPERATION,
                "seq": 0,
                "operation_id": 123,
            },))

    def test_reconciled_stage_cannot_invent_its_operation_or_skip_unknown(self):
        program = {
            "schema": S.SCHEMA,
            "event": S.EVENT_PROGRAM,
            "ts": "2026-08-31T00:00:00Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "planned",
            "operation_ids": [],
            "late_receipt_digest": "",
            "ops": [{"op": "create_wall", "id": "w1"}],
        }
        reconciled = {
            "schema": S.SCHEMA,
            "event": S.EVENT_STAGE,
            "ts": "2026-08-31T00:00:01Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "committed",
            "reconciled": True,
            "operation_id": "11111111-1111-5111-8111-111111111111",
            "receipt_digest": "a" * 64,
        }
        with self.assertRaisesRegex(ValueError, "без заранее связанного"):
            S.replay((program, reconciled), ("d", "k"))

        bound = {
            **program,
            "operation_ids": [reconciled["operation_id"]],
        }
        with self.assertRaisesRegex(ValueError, "без заранее связанного"):
            S.replay((bound, reconciled), ("d", "k"))

        running_unknown = {
            "schema": S.SCHEMA,
            "event": S.EVENT_STAGE,
            "ts": "2026-08-31T00:00:01Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "running_unknown",
        }
        restored = S.replay(
            (bound, running_unknown, reconciled), ("d", "k"))
        self.assertEqual(restored[0]["stage"], "committed")
        self.assertEqual(restored[0]["late_receipt_digest"], "a" * 64)

    def test_program_row_cannot_self_assert_build_or_late_receipt(self):
        base = {
            "schema": S.SCHEMA,
            "event": S.EVENT_PROGRAM,
            "ts": "2026-08-31T00:00:00Z",
            "device_id": "d",
            "doc_key": "k",
            "seq": 0,
            "stage": "planned",
            "operation_ids": [],
            "late_receipt_digest": "",
            "ops": [{"op": "create_wall", "id": "w1"}],
        }
        S.append_line(self.path, {**base, "stage": "committed"})
        S.append_line(self.path, {
            **base,
            "seq": 1,
            "late_receipt_digest": "a" * 64,
        })
        rows, why = S.read_events()
        self.assertEqual(rows, ())
        self.assertIn("битых строк 2", why)

    def test_identity_writers_refuse_coercion_and_invalid_sequences(self):
        operation_id = "11111111-1111-5111-8111-111111111111"
        self.assertFalse(S.record_operation(("d", "k"), 0, 123))
        self.assertFalse(S.record_operation(("d", "k"), True, operation_id))
        self.assertFalse(S.record_stage(
            ("d", "k"), 0, "committed",
            operation_id=operation_id, receipt_digest=123, reconciled=True))
        self.assertFalse(S.record_stage(
            ("d", "k"), 0, "committed", operation_id=operation_id))
        self.assertFalse(S.record_stage(("d", "k"), 0, "unknown"))
        self.assertFalse(self.path.exists())

    def test_export_separates_declared_from_built(self):
        S.record_program(("d", "k"), _rec(0, [{"op": "create_wall", "id": "w1"}]))
        S.record_program(("d", "k"), _rec(1, [{"op": "create_wall", "id": "w2"}]))
        S.record_stage(("d", "k"), 0, "committed")
        rows, _ = S.read_events()
        programs = S.replay(rows, ("d", "k"))

        declared = S.export_program(programs)
        self.assertEqual((declared["selection"], len(declared["ops"])),
                         ("declared", 2))
        built = S.export_program(programs, built_only=True)
        self.assertEqual((built["selection"], len(built["ops"]),
                          built["programs_skipped"]), ("built", 1, 1))

    def test_the_envelope_is_the_shape_axes_duel_eats(self):
        """The contract with the comparison instrument — by EXECUTION, not
        by word.

        🔴 THE FIRST DRAFT OF THIS TEST TURNED RED ON ITS OWN FIXTURE, and
        that is worth leaving on record. It referenced a level by a string
        (`"level": "L1"`) — the verdict door accepted the envelope and
        built ZERO walls, because a KIR reference has the shape
        `{"by": "ref", "value": …}` (`design_check._adapt_ref`). Measured
        across three forms: a string gives 0 walls, `by:"id"` gives 0
        walls, `by:"ref"` gives 1.

        The red was CORRECT, and it pointed somewhere other than where I
        first thought: the store's envelope is accepted exactly like a bare
        list (verified), and what was wrong was the operand's shape. Real
        programs arrive from the sandbox already in the right shape — here
        it was the fixture that was wrong.
        """
        from kir.design_check import spatial_model_from_ops
        S.record_program(("d", "k"), _rec(0, [
            {"op": "create_level", "id": "L1", "elev_mm": 0},
            {"op": "create_wall", "id": "w1",
             "level": {"by": "ref", "value": "L1"},
             "p0_mm": [0, 0, 0], "p1_mm": [6000, 0, 0], "height_mm": 3000},
        ]))
        rows, _ = S.read_events()
        envelope = S.export_program(S.replay(rows, ("d", "k")))
        model, _witness = spatial_model_from_ops(envelope, building_id="t")
        self.assertEqual(len(model.walls), 1,
                         "конверт склада не принимается дверью вердикта — "
                         "значит правой стороны сравнения по-прежнему нет")


class ItSurvivesARestart(unittest.TestCase):
    """🔴 SURVIVES A RESTART — VERIFIED BY A NEW PROCESS, NOT PROMISED.

    The whole point of this file is that the record survives the process's
    death. Checking this within the same process would mean checking a
    cache: the pages are still warm, and green would say nothing about
    durability.
    """

    def test_a_fresh_process_reads_what_this_one_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "p.jsonl"
            saved = os.environ.get(S.PATH_ENV)
            os.environ[S.PATH_ENV] = str(path)
            try:
                S.record_program(("dev", "doc"), _rec(0, [
                    {"op": "create_wall", "id": "w1", "p0_mm": [1, 2, 3]}]))
                S.record_stage(("dev", "doc"), 0, "accepted")
            finally:
                if saved is None:
                    os.environ.pop(S.PATH_ENV, None)
                else:
                    os.environ[S.PATH_ENV] = saved

            code = (
                "import json, os, sys;"
                "sys.path.insert(0, %r);"
                "os.environ[%r] = %r;"
                "from kir.live import journal_store as S;"
                "rows, why = S.read_events();"
                "p = S.replay(rows, ('dev','doc'));"
                "print(json.dumps({'why': why, 'n': len(p),"
                " 'stage': p[0]['stage'] if p else '',"
                " 'p0': p[0]['ops'][0]['p0_mm'] if p else []}))"
                % (str(BACKEND), S.PATH_ENV, str(path))
            )
            out = subprocess.run([sys.executable, "-c", code],
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[-800:])
            got = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(got["why"], "")
            self.assertEqual(got["n"], 1)
            self.assertEqual(got["stage"], "accepted",
                             "стадия не пережила процесс")
            self.assertEqual(got["p0"], [1, 2, 3],
                             "координаты не пережили процесс")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
