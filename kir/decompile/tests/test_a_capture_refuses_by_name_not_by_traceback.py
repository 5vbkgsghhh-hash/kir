# -*- coding: utf-8 -*-
"""A REFUSAL IS NAMED BY A CODE, NOT BY A LIBRARY'S TRACEBACK.

🔴 A SELF-REVIEW WAS OPENED 07.09.2026, AND TWO OF FOUR PROBES WERE RED.
Four situations, each checked by a PROBE BEFORE the fix, not after:

* a race between two PROCESSES for one target — was GREEN: exactly one
  passes, the second gets `target_not_empty`, the target reopens whole
  (6 out of 6 pairs);
* an edit that would not survive an export — was GREEN: the seam catches it
  BEFORE the save (`offset_out_of_host`, `sill_out_of_host`,
  `bad_change_value`), the directory stays byte-for-byte unchanged, the
  target is not created;
* a BROKEN sidecar — was RED: a `json.JSONDecodeError` flew out of
  `open_capture`. "The file is missing" and "the file is corrupted" are
  different facts, and there was nothing to tell them apart with;
* a target WITH NO WRITE PERMISSION — was RED: a `PermissionError` flew out
  carrying the address of a TEMPORARY directory that the caller never
  named.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from uuid import UUID
from pathlib import Path

import pytest

from kir.decompile import capture_api as API
from kir.decompile import capture_edit as CE
from kir.decompile.capture_edit import CaptureEditError
from kir.decompile.snapshot_io import snapshot_file_exists

ROOT = str(Path(CE.__file__).resolve().parents[2])
DOOR = API.DEMO_DOOR


def _digest(directory) -> str:
    running = hashlib.sha256()
    for item in sorted(Path(directory).rglob("*")):
        if item.is_file():
            running.update(str(item.relative_to(directory)).encode())
            running.update(item.read_bytes())
    return running.hexdigest()


@pytest.fixture()
def building(tmp_path):
    API.write_demo_capture(tmp_path / "capture")
    return tmp_path / "capture"


def test_two_processes_racing_one_target_leave_exactly_one_winner(building, tmp_path):
    """A race for one target: EXACTLY ONE gets through, and the target
    stays whole.

    Checked with PROCESSES, not threads: a save is assembled in a
    neighboring directory and moves in with `os.replace`, and the window
    between "assembled" and "in place" is visible only to real parallelism.
    """
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from kir.decompile import capture_api as API\n"
        "from kir.decompile import capture_edit as CE\n"
        "try:\n"
        f"    cap = CE.open_capture({str(building)!r})\n"
        f"    got = API.apply_patch(cap, {DOOR!r}, {{'offset_mm': float(sys.argv[1])}},\n"
        "                          before={'offset_mm': 3000.0})\n"
        "    if got.refusal is not None:\n"
        "        print(json.dumps({'code': got.refusal.get('code')})); sys.exit(2)\n"
        "    CE.save(cap, sys.argv[2])\n"
        "    print(json.dumps({'ok': True}))\n"
        "except CE.CaptureEditError as error:\n"
        "    print(json.dumps({'code': error.code})); sys.exit(2)\n",
        encoding="utf-8")
    environment = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    expected = len(CE.open_capture(str(building)).nodes)
    # 🔴 THREE PROCESSES AND SEVERAL ROUNDS, BECAUSE ONE PAIR PASSES BY
    # LUCK. The first edition called TWO processes once and was green 6
    # times in a row — and under the load of neighboring tests it gave
    # `[0, 1]`: the loser died with a RAW `OSError: Directory not empty` on
    # `target.rmdir()`, because the `target_not_empty` check sits at the
    # start, while the target is claimed at the end. An instrument that is
    # green from a narrow window is guarding luck, not the subject.
    for round_number in range(3):
        target = tmp_path / f"out-{round_number}"
        started = [subprocess.Popen([sys.executable, str(worker), value, str(target)],
                                    env=environment, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                   for value in ("4000", "5000", "6000")]
        talked = [item.communicate() for item in started]
        codes = [item.returncode for item in started]
        assert sorted(codes) == [0, 2, 2], f"успех обязан быть ровно один: {codes}"
        # A traceback instead of a code is a refusal you cannot ask "which one" about.
        assert not any("Traceback" in item[1] for item in talked), talked
        losing = sorted(json.loads(item[0])["code"]
                        for item, code in zip(talked, codes) if code)
        assert losing == ["target_not_empty"] * 2, losing
        # The target is a COMPLETED capture, not half of one: a different law opens it.
        assert len(CE.open_capture(str(target)).nodes) == expected
        assert not list(target.parent.glob(".*partial*")), "мусор сборки остался"


def test_two_threads_own_distinct_staging_and_the_loser_refuses_by_name(building, tmp_path, monkeypatch):
    """The second real save finishes while the first is paused at the copy seam."""
    monkeypatch.setenv("KIR_CACHE_HOME", str(tmp_path / "cache"))
    before = _digest(building)
    target = tmp_path / "thread-out"
    captures = {name: CE.open_capture(building) for name in ("save-a", "save-b")}
    for name, value in (("save-a", 4000.0), ("save-b", 5000.0)):
        assert API.apply_patch(captures[name], DOOR, {"offset_mm": value}).refusal is None
    first_copy, second_done = threading.Event(), threading.Event()
    staging, outcomes = {}, {}
    original_copy = CE._copy_capture_tree

    def coordinated(source_dir, destination, source_root):
        name = threading.current_thread().name
        staging.setdefault(name, Path(destination))
        if name == "save-a":
            first_copy.set()
            if not second_done.wait(10):
                raise AssertionError("second save did not finish")
        return original_copy(source_dir, destination, source_root)

    def worker(name):
        try:
            CE.save(captures[name], target)
            outcomes[name] = ("saved", None)
        except CaptureEditError as error:
            outcomes[name] = ("refused", error.code)
        except Exception as error:
            outcomes[name] = ("unexpected", type(error).__name__)
        finally:
            if name == "save-b":
                second_done.set()

    threads = []
    with monkeypatch.context() as scoped:
        scoped.setattr(CE, "_copy_capture_tree", coordinated)
        try:
            a = threading.Thread(target=worker, args=("save-a",), name="save-a")
            a.start()
            threads.append(a)
            assert first_copy.wait(10), "first save did not reach copy"
            b = threading.Thread(target=worker, args=("save-b",), name="save-b")
            b.start()
            threads.append(b)
            b.join(15)
            a.join(15)
        finally:
            second_done.set()
            for thread in threads:
                thread.join(15)
    assert not any(thread.is_alive() for thread in threads), "save thread leaked"
    assert outcomes == {"save-a": ("refused", "target_not_empty"), "save-b": ("saved", None)}, outcomes
    assert staging["save-a"] != staging["save-b"]
    reopened = CE.open_capture(target)
    assert len(reopened.nodes) == len(captures["save-b"].nodes)
    assert API.read_element(reopened, DOOR).op_params["offset_mm"] == 5000.0
    assert _digest(building) == before
    assert not list(tmp_path.glob(".*partial*"))


def test_a_failed_save_cleans_only_its_staging_while_another_save_is_paused(building, tmp_path, monkeypatch):
    """Observe the second staging before/after the first save's actual cleanup."""
    monkeypatch.setenv("KIR_CACHE_HOME", str(tmp_path / "cache"))
    before = _digest(building)
    target = tmp_path / "interrupted-thread-out"
    captures = {name: CE.open_capture(building) for name in ("failing-a", "paused-b")}
    for name, value in (("failing-a", 4000.0), ("paused-b", 5000.0)):
        assert API.apply_patch(captures[name], DOOR, {"offset_mm": value}).refusal is None
    first_copy, second_paused, first_done = threading.Event(), threading.Event(), threading.Event()
    original_copy = CE._copy_capture_tree
    interrupted = OSError(errno.EIO, "injected copy interruption")
    outcomes, observations = {}, {}

    def coordinated(source_dir, destination, source_root):
        if threading.current_thread().name == "failing-a":
            first_copy.set()
            assert second_paused.wait(10), "second staging was not allocated"
            raise interrupted
        observations["before"] = _digest(destination)
        assert (Path(destination) / CE._PARTIAL_NAME).is_file()
        second_paused.set()
        assert first_done.wait(10), "first save did not finish cleanup"
        observations["after"] = _digest(destination)
        assert observations["before"] == observations["after"], "another save deleted this staging"
        return original_copy(source_dir, destination, source_root)

    def worker(name):
        try:
            CE.save(captures[name], target)
            outcomes[name] = None
        except Exception as error:
            outcomes[name] = error
        finally:
            if name == "failing-a":
                first_done.set()

    threads = []
    with monkeypatch.context() as scoped:
        scoped.setattr(CE, "_copy_capture_tree", coordinated)
        try:
            a = threading.Thread(target=worker, args=("failing-a",), name="failing-a")
            a.start()
            threads.append(a)
            assert first_copy.wait(10)
            b = threading.Thread(target=worker, args=("paused-b",), name="paused-b")
            b.start()
            threads.append(b)
            a.join(15)
            b.join(15)
        finally:
            second_paused.set()
            first_done.set()
            for thread in threads:
                thread.join(15)
    assert not any(thread.is_alive() for thread in threads)
    assert outcomes["failing-a"] is interrupted
    assert outcomes["paused-b"] is None, outcomes
    assert observations["before"] and observations["before"] == observations["after"]
    assert API.read_element(CE.open_capture(target), DOOR).op_params["offset_mm"] == 5000.0
    assert _digest(building) == before
    assert not list(tmp_path.glob(".*partial*"))


def test_demo_save_keeps_unowned_staging_and_refuses_a_name_collision(building, tmp_path, monkeypatch):
    capture = CE.open_capture(building)
    orphan = tmp_path / f".orphan.partial-{CE.os.getpid()}"
    orphan.mkdir()
    shutil.copy2(building / "L0.jsonl", orphan / "L0.jsonl")
    (orphan / CE._PARTIAL_NAME).write_text("unowned incomplete save", encoding="utf-8")
    (orphan / "foreign.txt").write_text("not ours", encoding="utf-8")
    before = _digest(orphan)
    with pytest.raises(CaptureEditError) as refused:
        CE.open_capture(orphan)
    assert refused.value.code == "capture_save_incomplete"
    saved = CE.save(capture, tmp_path / "orphan")
    assert orphan.is_dir() and _digest(orphan) == before
    assert not (saved / "foreign.txt").exists()

    identity = UUID("00112233-4455-6677-8899-aabbccddeeff")
    collision = tmp_path / f".collision.partial-{identity.hex}"
    collision.mkdir()
    (collision / "other-owner.txt").write_text("preserve", encoding="utf-8")
    collision_before = _digest(collision)
    monkeypatch.setattr(CE, "uuid4", lambda: identity)
    with pytest.raises(CaptureEditError) as refused:
        CE.save(capture, tmp_path / "collision")
    assert refused.value.code == "target_not_writable"
    assert _digest(collision) == collision_before
    assert not (tmp_path / "collision").exists()


def test_published_directory_keeps_the_existing_mkdir_permission_policy(building, tmp_path):
    reference = tmp_path / "ordinary-directory"
    reference.mkdir()
    saved = CE.save(CE.open_capture(building), tmp_path / "mode-preserved")
    # No process-global umask is read or changed by the implementation or test.
    assert stat.S_IMODE(saved.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


@pytest.mark.skipif(os.name != "posix", reason="this filename-byte control targets POSIX NAME_MAX")
def test_unique_staging_does_not_expand_a_legal_long_destination_name(building, tmp_path):
    # The old PID suffix fits this legal basename on NAME_MAX=255 filesystems;
    # appending a full UUID to the same unbounded basename would not fit.
    if os.pathconf(tmp_path, "PC_NAME_MAX") < 255:
        pytest.skip("filesystem does not provide the tested 255-byte name capacity")
    target = tmp_path / ("x" * 230)
    saved = CE.save(CE.open_capture(building), target)
    assert saved == target and CE.open_capture(saved).nodes
    assert not list(tmp_path.glob(".*partial*"))


@pytest.mark.parametrize("patch,code", [
    ({"offset_mm": 999_999.0}, "offset_out_of_host"),
    ({"sill_mm": -99_999.0}, "sill_out_of_host"),
    ({"symbol": "ТАКОГО ТИПА НЕТ"}, "bad_change_value"),
])
def test_a_patch_the_export_would_not_survive_is_refused_before_it_is_saved(
        building, tmp_path, patch, code):
    """An edit that fails the contract does NOT reach disk.

    The refusal arrives BY NAME before the save, the directory stays
    byte-for-byte unchanged, and the target is not created at all: "refusal"
    and "saved, but bad" are different outcomes.

    🔴 THE SNAPSHOT IS TAKEN AFTER OPENING, AND AS OF 07.09.2026 THIS IS NO
    LONGER A CONCESSION. The first edition measured FROM
    `write_demo_capture` and turned red on all three patches — not because
    of the edit: `open_capture` was placing an access marker `.last_access`
    (0 bytes) into the directory ITSELF, which the snapshot cleaner uses to
    gauge "this is still being visited". The marker changed not a single
    piece of data, but the directory after opening was no longer the same
    as before, and `open_capture`'s docstring, "the directory is ONLY
    read", was inaccurate in this one spot.

    By the owner's decision of 07.09.2026, the access marker moved to an
    EXTERNAL journal (`KIR_CACHE_HOME`/`XDG_CACHE_HOME`/`~/.cache` ->
    `kir/lift/<sha256 of the path>`, see
    `kir.model.snapshot_io.access_journal_dir`), and the requirement here
    became STRICTER than before: opening adds NOTHING at all, and the
    directory's snapshot is byte-for-byte equal to the pre-opening one. The
    former `appeared <= {".last_access"}` forgave a write to a file with
    that name; equality forgives nothing.
    """
    fresh = _digest(building)
    listing = {item.name for item in Path(building).iterdir()}
    capture = CE.open_capture(str(building))
    appeared = {item.name for item in Path(building).iterdir()} - listing
    assert appeared == set(), (
        f"открытие обязано не добавлять НИЧЕГО, добавило {appeared}")
    assert _digest(building) == fresh, "открытие изменило каталог побайтно"
    was = _digest(building)
    applied = API.apply_patch(capture, DOOR, patch)
    assert applied.refusal is not None, "негодная правка обязана отказать"
    assert applied.refusal["code"] == code, applied.refusal
    assert applied.diff == ()
    assert _digest(building) == was, "исходник обязан остаться байт в байт"
    assert not (tmp_path / "never").exists()


def test_a_capture_on_read_only_media_opens_and_stays_untouched(building, tmp_path,
                                                                monkeypatch):
    """🔴 PIN 07.09.2026: A CAPTURE WITH NO WRITE PERMISSION OPENS.

    Recon measurement from the same day: `chmod 555` WITHOUT a marker
    placed beforehand — the capture already opened, because
    `touch_last_access` was swallowing `OSError`. That is, the requirement
    was being met, but it was NOT PINNED DOWN: a line that broke reading on
    a read-only medium would have passed silently.

    Both outcomes are asked for at once, and the second is not derived from
    the first: the decompile CAME UP (nodes exist) AND the directory's
    contents did not change. A medium where the write simply failed would
    give the first without the second on any other machine — one where the
    same directory belongs to the caller.
    """
    from kir.decompile.snapshot_io import (LAST_ACCESS_MARKER,
                                            access_journal_dir)

    monkeypatch.setenv("KIR_CACHE_HOME", str(tmp_path / "cache"))
    listing = {item.name for item in Path(building).iterdir()}
    before = _digest(building)
    отметка = access_journal_dir(building) / LAST_ACCESS_MARKER
    Path(building).chmod(0o555)
    try:
        capture = CE.open_capture(str(building))
        assert capture.nodes, "read-only capture обязан подниматься"
        assert {item.name for item in Path(building).iterdir()} == listing
        assert _digest(building) == before
        # AND THE CLEANER'S DEFERRAL IS NOT LOST EITHER. Before, on a
        # read-only medium it used to get lost silently: the marker was
        # written inside, the write failed, `OSError` was swallowed —
        # opening succeeded, and "this is visited" was recorded nowhere.
        assert отметка.exists(), "доступ к read-only capture нигде не отмечен"
    finally:
        Path(building).chmod(0o755)


def test_a_damaged_sidecar_is_named_not_thrown(building, tmp_path):
    """A broken sidecar: NAMED corruption and `unknown`, not
    `JSONDecodeError`.

    A control INSIDE the instrument: corruption must differ from ABSENCE —
    a missing file and a corrupted file are handled differently, and the
    source's version must diverge, or old edits will replay silently onto
    a different geometry.
    """
    damaged = tmp_path / "damaged"
    shutil.copytree(building, damaged)
    sidecar = damaged / "sketch.index.json"
    # 🔴 NOT `is_file()`: a compressible name is asked with
    # `snapshot_file_exists`. The `test_snapshot_existence_is_asked` guard
    # caught exactly this line — the bare verb answers "no" about a sidecar
    # the cleaner has compressed.
    assert snapshot_file_exists(sidecar), "фикстура обязана нести применимую sidecar"
    sidecar.write_text("{ это не json", encoding="utf-8")

    healthy = CE.open_capture(str(building))
    broken = CE.open_capture(str(damaged))       # not an exception — this is exactly the subject
    assert healthy.unreadable_side_indexes == ()
    assert [row["index"] for row in broken.unreadable_side_indexes] == ["sketch"]
    assert "sketch.index.json" in broken.unreadable_side_indexes[0]["detail"]
    assert "sketch" in broken.missing_side_indexes

    read = API.read_element(broken, DOOR)
    states = {item.field: item.state for item in read.fields}
    assert states, "чтение обязано состояться"
    assert set(states.values()) <= {"represented", "approximate",
                                    "source_data", "unknown"}
    # Corruption is not absence: the source's version must diverge, or old
    # edits will land on a DIFFERENT geometry silently (mandate, part 2).
    assert broken.source_version != healthy.source_version


def test_a_target_that_cannot_be_written_is_refused_by_name(building, tmp_path, monkeypatch):
    """Permissions are a refusal too, and it has a code and the TARGET'S ADDRESS, not a temp path."""
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    capture = CE.open_capture(str(building))
    API.apply_patch(capture, DOOR, {"offset_mm": 4000.0})
    before = _digest(building)
    original_mkdir = os.mkdir
    denied = []

    def refuse_staging(path, mode=0o777, *, dir_fd=None):
        requested = Path(path)
        if requested.parent == barrier and requested.name.startswith(".out.partial-"):
            denied.append(requested)
            raise PermissionError(errno.EACCES, "permission denied by test filesystem seam", str(requested))
        return original_mkdir(path, mode, dir_fd=dir_fd)

    # chmod cannot deny root. Inject the actual OS error only at this target's
    # allocation; the save/error mapping and subsequent positive save are real.
    with monkeypatch.context() as scoped:
        scoped.setattr(os, "mkdir", refuse_staging)
        with pytest.raises(CaptureEditError) as caught:
            CE.save(capture, str(barrier / "out"))
    assert denied and not list(barrier.iterdir())
    assert caught.value.code == "target_not_writable"
    assert str(barrier) in str(caught.value)
    assert "partial" not in str(caught.value), "адрес времянки зовущий не называл"
    assert _digest(building) == before
    saved = CE.save(capture, barrier / "out")
    assert API.read_element(CE.open_capture(saved), DOOR).op_params["offset_mm"] == 4000.0
    assert _digest(building) == before


def test_a_read_only_capture_can_still_be_previewed(building):
    """A read-only view of a capture with no write permission WORKS and writes nothing."""
    for item in sorted(Path(building).rglob("*"), reverse=True):
        os.chmod(item, 0o444 if item.is_file() else 0o555)
    os.chmod(building, 0o555)
    try:
        was = _digest(building)
        capture = CE.open_capture(str(building))
        proposal = API.propose_patch(capture, DOOR, {"offset_mm": 4000.0})
        assert proposal.admissible and proposal.diff
        assert capture.edits == [], "предпросмотр не ведёт журнал правок"
        assert _digest(building) == was, "предпросмотр обязан не писать НИЧЕГО"
    finally:
        for item in sorted(Path(building).rglob("*"), reverse=True):
            os.chmod(item, 0o644 if item.is_file() else 0o755)
        os.chmod(building, 0o755)
