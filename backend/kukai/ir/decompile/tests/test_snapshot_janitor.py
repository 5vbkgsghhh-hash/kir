"""tools/snapshot_janitor.py — pre-1000-user wave, 2026-07-29.

Four things the coordinator named explicitly:

  * hot stuff (younger than MIN_AGE_HOURS) is never touched, whatever the
    other signals say;
  * an in-progress run (footer_written=false, or an A5 journal that has
    not reached "Completed") is untouchable, by ANY rule;
  * the janitor's own gzip output is readable back through
    kukai.ir.decompile.snapshot_io (Part 1+2 integration, not just two
    halves that were never actually plugged into each other);
  * retention groups by document_fingerprint, never by directory name —
    proven both ways (same name pattern, different documents: not
    grouped; wildly different names, same document: grouped).

classify()/plan_actions() are pure over already-read state, so most of
this is synthetic temp directories and no real time needs to pass.
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))

import tools.snapshot_janitor as J  # noqa: E402
from kukai.ir.decompile.snapshot_io import (  # noqa: E402
    open_snapshot, touch_last_access,
)

HOUR = 3600.0
DAY = 24 * HOUR


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_snapshot(
    root: Path,
    name: str,
    *,
    now: float,
    updated_ago_s: float = 2 * HOUR,
    footer_written: bool = True,
    header_written: bool = True,
    stage: str | None = "done",
    have_status: bool = True,
    have_checkpoint: bool = True,
    a5_last_phase: str | None = None,   # None = no a5_runs at all
    project_uid: str | None = "uid-A",
    path_name: str | None = None,
    title: str | None = None,
    with_snapshot_files: bool = True,
) -> Path:
    """A synthetic snapshot directory with just enough control-file shape
    for classify()/check_live() to read — never a real pipeline run, but
    the same field names and file layout one produces."""
    directory = root / name
    directory.mkdir(parents=True)
    if have_checkpoint:
        _write_json(directory / "L0.checkpoint.json", {
            "footer_written": footer_written, "header_written": header_written,
            "change_stamp": name,
        })
    if have_status:
        _write_json(directory / "status.json", {
            "stage": stage, "updated_at": now - updated_ago_s,
        })
    if project_uid or path_name or title:
        fp: dict = {}
        if project_uid:
            fp["project_uid"] = project_uid
        if path_name:
            fp["path_name"] = path_name
        if title:
            fp["title"] = title
        _write_json(directory / "open_model.profile.json",
                    {"document_fingerprint": fp})
    if a5_last_phase is not None:
        a5 = directory / "a5_runs"
        a5.mkdir()
        lines = [
            json.dumps({"event": "transition", "phase": "Prepared"}),
            json.dumps({"event": "effect_started"}),
            json.dumps({"event": "effect_finished"}),
            json.dumps({"event": "transition", "phase": a5_last_phase}),
        ]
        (a5 / "run1.state.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
    if with_snapshot_files:
        for fname in J.SNAPSHOT_FILES:
            (directory / fname).write_text(
                json.dumps({"fixture": fname, "for": name}), encoding="utf-8")
    return directory


class HotSnapshotIsNeverTouched(unittest.TestCase):
    """MIN_AGE_HOURS overrides EVERY other signal, including a document
    with many stale revisions and a snapshot that looks idle by every
    other measure."""

    def test_young_snapshot_is_skipped_even_with_excess_revisions(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Two OLD revisions (eligible for delete_old_revision on their
            # own) plus one FRESH one, all the same document.
            for i in range(2):
                _make_snapshot(root, f"old{i}", now=now,
                              updated_ago_s=10 * DAY, project_uid="uid-A")
            fresh = _make_snapshot(
                root, "fresh", now=now,
                updated_ago_s=30 * 60.0,  # 30 minutes — younger than MIN_AGE_HOURS=1h
                project_uid="uid-A")
            states = [J.classify(d, now)
                     for d in J.discover_snapshots(root)]
            actions = {a.directory: a for a in J.plan_actions(states)}
            self.assertEqual(actions[fresh].action, "skip")
            self.assertIn("MIN_AGE_HOURS", actions[fresh].reason)

    def test_idle_but_young_snapshot_is_not_gzipped(self) -> None:
        """idle_hours alone (last_access very old) must not win against a
        young status.json updated_at — a run that just finished and was
        immediately read once, long before, is still a fresh run."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * 60.0)
            # Force an ancient last-access marker directly (simulating a
            # read right after creation, long "idle" by that measure alone).
            marker = d / J.LAST_ACCESS_MARKER
            marker.touch()
            os_ancient = now - 100 * HOUR
            import os
            os.utime(marker, (os_ancient, os_ancient))
            state = J.classify(d, now)
            action = J.plan_actions([state])[0]
            self.assertEqual(action.action, "skip")


class InProgressRunIsUntouchable(unittest.TestCase):
    def test_footer_not_written_blocks_every_rule(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                _make_snapshot(root, f"r{i}", now=now, updated_ago_s=10 * DAY,
                              footer_written=(i != 0), project_uid="uid-B")
            states = {d.name: J.classify(d, now)
                     for d in J.discover_snapshots(root)}
            actions = {a.directory.name: a
                      for a in J.plan_actions(list(states.values()))}
            self.assertEqual(actions["r0"].action, "skip")
            self.assertIn("footer_written", actions["r0"].reason)

    def test_missing_checkpoint_blocks(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              have_checkpoint=False)
            action = J.plan_actions([J.classify(d, now)])[0]
            self.assertEqual(action.action, "skip")
            self.assertIn("checkpoint", action.reason)

    def test_stage_not_done_blocks(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              stage="extract")
            action = J.plan_actions([J.classify(d, now)])[0]
            self.assertEqual(action.action, "skip")
            self.assertIn("stage", action.reason)

    def test_a5_run_not_completed_blocks(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              a5_last_phase="Rebuilt")
            action = J.plan_actions([J.classify(d, now)])[0]
            self.assertEqual(action.action, "skip")
            self.assertIn("Rebuilt", action.reason)

    def test_a5_run_completed_does_not_block(self) -> None:
        """Negative control: a genuinely finished A5 run must NOT be
        treated as live just because a5_runs/ exists at all."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              a5_last_phase="Completed")
            live = J.check_live(d)
            self.assertFalse(live.live, live.reason)

    def test_effect_bookkeeping_tail_does_not_mask_a_real_completion(self) -> None:
        """Live bug fixed 2026-07-29 (sob62_fas_r23_v10): the journal's
        raw last LINE is often an effect_finished record with no phase at
        all — reading that naively must not misreport a genuinely
        Completed run as unknown/live."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              have_status=True, project_uid="uid-C")
            a5 = d / "a5_runs"
            a5.mkdir()
            lines = [
                json.dumps({"event": "transition", "phase": "Compared"}),
                json.dumps({"event": "transition", "phase": "CleanupPreviewed"}),
                json.dumps({"event": "transition", "phase": "Completed"}),
                json.dumps({"event": "effect_finished", "effect_id": "cleanup-1"}),
                json.dumps({"event": "effect_finished", "effect_id": "cleanup-2"}),
            ]
            (a5 / "run1.state.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            live = J.check_live(d)
            self.assertFalse(live.live, live.reason)


class GzipOutputIsReadable(unittest.TestCase):
    """Part 1 + Part 2 integration: the janitor's OWN compress action
    produces exactly what kukai.ir.decompile.snapshot_io's shim expects."""

    def test_executed_gzip_action_is_readable_via_the_shim(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY)
            original = {
                name: (d / name).read_text(encoding="utf-8")
                for name in J.SNAPSHOT_FILES
            }
            action = J.PlannedAction(d, "gzip", "test")
            J.execute(action)
            for name in J.SNAPSHOT_FILES:
                self.assertFalse((d / name).exists(), name)
                self.assertTrue((d / (name + ".gz")).exists(), name)
                got = open_snapshot(d / name, "rt", encoding="utf-8").read()
                self.assertEqual(got, original[name])

    def test_gzip_verifies_readback_before_removing_raw(self) -> None:
        """A corrupted compress must leave the raw file in place rather
        than lose the only copy."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY,
                              with_snapshot_files=False)
            raw = d / "L0.jsonl"
            raw.write_text("real content", encoding="utf-8")
            real_gzip_open = gzip.open

            def _corrupting_open(path, mode="rb", **kwargs):
                handle = real_gzip_open(path, mode, **kwargs)
                if "w" in mode:
                    return handle
                # Return something whose .read() lies, simulating a
                # corrupt archive on readback.
                class _Liar:
                    def read(self_inner):
                        return b"WRONG" if "b" in mode else "WRONG"

                    def __enter__(self_inner):
                        return self_inner

                    def __exit__(self_inner, *exc):
                        handle.close()
                return _Liar()

            J.gzip.open = _corrupting_open
            try:
                with self.assertRaises(RuntimeError):
                    J._gzip_file_verified(raw)
            finally:
                J.gzip.open = real_gzip_open
            self.assertTrue(raw.exists(), "raw file must survive a bad compress")
            self.assertEqual(raw.read_text(encoding="utf-8"), "real content")


class RetentionGroupsByFingerprintNotFilename(unittest.TestCase):
    def test_same_name_pattern_different_documents_not_grouped(self) -> None:
        """v1/v2/v3-style names that happen to belong to DIFFERENT
        documents must not be pruned as if they were revisions of one."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(4):
                _make_snapshot(root, f"v{i}", now=now, updated_ago_s=10 * DAY,
                              project_uid=f"uid-distinct-{i}")
            states = [J.classify(d, now) for d in J.discover_snapshots(root)]
            actions = J.plan_actions(states)
            self.assertTrue(
                all(a.action != "delete_old_revision" for a in actions),
                [(a.directory.name, a.action) for a in actions])

    def test_wildly_different_names_same_document_are_grouped(self) -> None:
        """night_bN / sob62_.../ demo-style unrelated names, same
        project_uid — retention must still see them as one document."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ["night_b7", "sob62_fas_r23_v11", "демо-снимок-3"]
            for i, name in enumerate(names):
                _make_snapshot(root, name, now=now,
                              updated_ago_s=(10 - i) * DAY,
                              project_uid="uid-shared")
            states = [J.classify(d, now) for d in J.discover_snapshots(root)]
            actions = {a.directory.name: a for a in J.plan_actions(states)}
            deleted = [n for n, a in actions.items()
                      if a.action == "delete_old_revision"]
            kept = [n for n, a in actions.items() if a.action != "delete_old_revision"]
            self.assertEqual(len(deleted), 1, actions)
            self.assertEqual(len(kept), 2, actions)
            # the OLDEST of the three (highest updated_ago_s) is the one dropped
            self.assertEqual(deleted, ["night_b7"])

    def test_fingerprint_key_ignores_directory_name_entirely(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _make_snapshot(root, "alpha", now=now, project_uid="same-uid")
            b = _make_snapshot(root, "totally-different-name-zzz", now=now,
                              project_uid="same-uid")
            self.assertEqual(
                J.document_fingerprint_key(a), J.document_fingerprint_key(b))

    def test_no_fingerprint_never_groups_with_anything(self) -> None:
        """A snapshot with no readable document_fingerprint at all must
        not be swept into someone else's retention count."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                _make_snapshot(root, f"legacy{i}", now=now,
                              updated_ago_s=10 * DAY, project_uid=None,
                              path_name=None, title=None)
            states = [J.classify(d, now) for d in J.discover_snapshots(root)]
            actions = J.plan_actions(states)
            self.assertTrue(
                all(a.action != "delete_old_revision" for a in actions),
                [(a.directory.name, a.action) for a in actions])


class InactiveDeleteAndKeepRevisionsThresholds(unittest.TestCase):
    def test_inactive_past_30_days_deletes_regardless_of_revision_count(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "solo", now=now,
                              updated_ago_s=40 * DAY, project_uid="uid-solo")
            action = J.plan_actions([J.classify(d, now)])[0]
            self.assertEqual(action.action, "delete_inactive")

    def test_keep_revisions_boundary_exact(self) -> None:
        """Exactly KEEP_REVISIONS snapshots of one document: none deleted."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(J.KEEP_REVISIONS):
                _make_snapshot(root, f"r{i}", now=now,
                              updated_ago_s=(i + 1) * DAY,
                              project_uid="uid-exact")
            states = [J.classify(d, now) for d in J.discover_snapshots(root)]
            actions = J.plan_actions(states)
            self.assertTrue(all(a.action != "delete_old_revision" for a in actions))

    def test_idle_gzip_threshold(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            just_under = _make_snapshot(
                root, "under", now=now,
                updated_ago_s=(J.IDLE_HOURS - 0.5) * HOUR)
            just_over = _make_snapshot(
                root, "over", now=now,
                updated_ago_s=(J.IDLE_HOURS + 0.5) * HOUR)
            actions = {a.directory.name: a.action for a in J.plan_actions(
                [J.classify(just_under, now), J.classify(just_over, now)])}
            self.assertEqual(actions["under"], "skip")
            self.assertEqual(actions["over"], "gzip")

    def test_already_gzipped_snapshot_is_not_re_gzipped(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _make_snapshot(root, "s", now=now, updated_ago_s=10 * DAY)
            for name in J.SNAPSHOT_FILES:
                raw = d / name
                with gzip.open(str(raw) + ".gz", "wb") as f:
                    f.write(raw.read_bytes())
                raw.unlink()
            action = J.plan_actions([J.classify(d, now)])[0]
            self.assertNotEqual(action.action, "gzip")


if __name__ == "__main__":
    unittest.main()
