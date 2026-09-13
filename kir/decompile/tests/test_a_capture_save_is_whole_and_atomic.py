# -*- coding: utf-8 -*-
"""A SELF-SUFFICIENT SAVE: whole, atomic, never reaching outside the
capture.

Provenance of the scenes at the bottom of the file: external audit
07.09.2026, KIR-F002/F003/G001, snapshot `ad78e64`; re-measured on a frozen
copy (`git archive ad78e64`, PYTHONNOUSERSITE=1) — all three reproduced
verbatim.

Four recon measurements from 07.09.2026 on `bench_A` (probe
`.work/marathon-fable-20260907/capture/probe.py`), each by execution:

D. `save` was copying ONLY top-level files (`item.is_file()`), while the
   run carries a nested sidecar `lift_cache/<sha>.json` weighing
   2 727 173 bytes. After the save, it was gone: "saved" meant "part was
   saved".
E. A symlink `stolen.json -> /etc/hostname`, placed in the capture, passed
   `is_file()` and TRAVELED WITH ITS CONTENTS: the saved capture carried the
   machine's hostname. The application's path reached outside the capture
   and carried off an arbitrary file from the computer.
G. A save interrupted midway (L0 landed, `capture_meta.json` not yet there)
   was accepted by `open_capture` as COMPLETE: `lineage` was derived from
   the directory's name, there was no refusal. Half the work, declared as
   the work.
F. The metadata carried neither the `profiles` mode nor the interpretation
   version, even though `profiles` CHANGES the lift: with it, `bench_A` has
   21 nodes carrying opening rings, without it — zero.

The corpus is READ and never written.
"""
from __future__ import annotations

import json
import shutil
import tracemalloc
from pathlib import Path

import pytest

from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists

CORPUS = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A")
DOOR = "286533"

pytestmark = pytest.mark.skipif(not snapshot_file_exists(CORPUS / "L0.jsonl"),
                                reason="корпус bench_A недоступен на этой машине")


def _copy_whole(source: Path, target: Path) -> Path:
    """A copy of a run TOGETHER WITH its nested directories — otherwise the wrong thing would be measured."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_symlink():
            continue
        if item.is_dir():
            shutil.copytree(item, target / item.name)
        elif item.is_file():
            shutil.copy2(item, target / item.name)
    return target


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    return _copy_whole(CORPUS, tmp_path_factory.mktemp("whole") / "bench_A")


def _accepts_as_complete(path: Path) -> bool:
    """Whether `open_capture` accepts this directory as a COMPLETE save."""
    try:
        CE.open_capture(path)
        return True
    except CE.CaptureEditError:
        return False


def test_a_nested_sidecar_survives_the_save(work, tmp_path):
    """A nested sidecar — declared data of the run, not top-level junk."""
    nested = work / "lift_cache"
    assert nested.is_dir(), "в прогоне нет вложенного sidecar — замер не о том"
    original = sorted(item.name for item in nested.iterdir())
    assert original, "lift_cache пуст — замер не о том"

    saved = CE.save(CE.open_capture(work), tmp_path / "saved")

    assert (saved / "lift_cache").is_dir(), (
        f"вложенный sidecar не доехал: в сохранённом caption только "
        f"{sorted(item.name for item in saved.iterdir())}")
    assert sorted(item.name for item in (saved / "lift_cache").iterdir()) == original
    for name in original:
        assert (saved / "lift_cache" / name).read_bytes() == (nested / name).read_bytes(), \
            f"lift_cache/{name} доехал изменённым"


def test_a_path_that_leaves_the_capture_is_refused_and_never_copied(work, tmp_path):
    """A symlink pointing outward is not part of the capture, it is an arbitrary file on the computer."""
    scene = _copy_whole(work, tmp_path / "scene")
    secret = tmp_path / "outside_secret.json"
    secret.write_text('{"not":"part of this building"}', encoding="utf-8")
    (scene / "stolen.index.json").symlink_to(secret)

    capture = CE.open_capture(scene)
    target = tmp_path / "escaped"
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.save(capture, target)
    assert caught.value.code == "capture_path_escapes", caught.value.code
    assert "stolen.index.json" in str(caught.value)
    assert not (target / "stolen.index.json").exists(), "чужой файл всё-таки уехал"


def test_a_save_that_dies_midway_leaves_nothing_that_opens_as_complete(work, tmp_path,
                                                                       monkeypatch):
    """A mid-way error does not leave behind a directory that gets accepted as a save."""
    capture = CE.open_capture(work)
    target = tmp_path / "torn"
    # 🔴 THE INTERRUPTION MUST HAPPEN AFTER L0 HAS ALREADY LANDED, otherwise
    # the measurement runs idle: `open_capture` would not accept a directory
    # with no snapshot anyway.
    seen = {"l0": False}
    real = CE.shutil.copy2

    def dying_copy(source, destination, *args, **kwargs):
        if Path(source).name.startswith("L0.jsonl"):
            seen["l0"] = True
            return real(source, destination, *args, **kwargs)
        if seen["l0"]:
            raise OSError(28, "No space left on device (подстановка замера)")
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(CE.shutil, "copy2", dying_copy)
    with pytest.raises(OSError):
        CE.save(capture, target)

    assert seen["l0"], "замер не состоялся: обрыв случился до того, как L0 лёг"
    leftovers = [item for item in tmp_path.iterdir()
                 if item.is_dir() and snapshot_file_exists(item / "L0.jsonl")]
    accepted = [str(item) for item in leftovers if _accepts_as_complete(item)]
    assert not accepted, (
        f"оборванное сохранение принято за завершённое: {accepted}")


def test_the_profiles_mode_is_pinned_in_the_saved_metadata(work, tmp_path):
    """The `profiles` mode changes the lift — meaning it is part of a save's identity."""
    saved = CE.save(CE.open_capture(work, profiles="editable"), tmp_path / "pinned")
    meta = json.loads((saved / CE._META_NAME).read_text(encoding="utf-8"))
    assert meta.get("profiles") == "editable", meta
    assert isinstance(meta.get("source_version"), str) and meta["source_version"], meta


def test_replaying_old_edits_under_another_interpretation_is_refused_by_name(work, tmp_path):
    """Old edits replayed under a different reading mode are a different geometry."""
    capture = CE.open_capture(work, profiles="editable")
    assert CE.edit_element(capture, DOOR, {"offset_mm": 1300.0}).refusal is None
    saved = CE.save(capture, tmp_path / "mode")

    assert CE.open_capture(saved, profiles="editable").lineage == capture.lineage
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(saved, profiles="all")
    assert caught.value.code == "interpretation_mode_changed", caught.value.code


def test_the_save_does_not_hold_every_sidecar_in_memory(work, tmp_path):
    """"Do not require loading all applications fully into memory" — as a number."""
    capture = CE.open_capture(work)
    on_disk = sum(item.stat().st_size for item in work.rglob("*") if item.is_file())
    assert on_disk > 4 << 20, f"прогон слишком мал ({on_disk} Б) — замер ничего не скажет"

    tracemalloc.start()
    try:
        CE.save(capture, tmp_path / "streamed")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < on_disk // 4, (
        f"пик {peak} Б при {on_disk} Б приложений: сохранение держит их в памяти")


def test_a_second_save_over_a_finished_capture_is_refused_and_spares_it(work, tmp_path):
    """Re-saving over a finished capture: a named refusal, the old one intact."""
    capture = CE.open_capture(work)
    assert CE.edit_element(capture, DOOR, {"offset_mm": 1300.0}).refusal is None
    saved = CE.save(capture, tmp_path / "twice")
    before = {item.name: item.stat().st_size for item in saved.rglob("*") if item.is_file()}

    again = CE.open_capture(saved)
    assert CE.edit_element(again, DOOR, {"offset_mm": 1400.0}).refusal is None
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.save(again, saved)
    assert caught.value.code == "target_not_empty", caught.value.code
    # No mixing: the second reader sees THE SAME THING as before the attempt.
    assert {item.name: item.stat().st_size
            for item in saved.rglob("*") if item.is_file()} == before
    assert CE.open_capture(saved).by_source[DOOR]["params"]["offset_mm"] == 1300.0


def test_an_orphaned_partial_is_never_adopted_and_never_grows(work, tmp_path):
    """An orphaned intermediate directory — neither a capture nor someone else's legacy."""
    orphan = tmp_path / f".orph.partial-{CE.os.getpid()}"
    orphan.mkdir()
    shutil.copy2(work / "L0.jsonl", orphan / "L0.jsonl")
    (orphan / CE._PARTIAL_NAME).write_text("оборвано", encoding="utf-8")
    (orphan / "чужое.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(orphan)
    assert caught.value.code == "capture_save_incomplete", caught.value.code

    before = {str(path.relative_to(orphan)): path.read_bytes()
              for path in orphan.rglob("*") if path.is_file()}
    saved = CE.save(CE.open_capture(work), tmp_path / "orph")
    assert not (saved / "чужое.json").exists(), "осиротевший partial подхвачен как своё"
    # A PID in the name proves no ownership. An old or concurrently used
    # partial belongs to someone else until a separate recovery decision.
    assert orphan.is_dir()
    assert {str(path.relative_to(orphan)): path.read_bytes()
            for path in orphan.rglob("*") if path.is_file()} == before


def test_a_symlinked_directory_is_refused_outward_and_in_a_loop(work, tmp_path):
    """A directory that is a link: no cycle back into itself, and no carrying off someone else's tree."""
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("не отсюда", encoding="utf-8")

    outward = _copy_whole(work, tmp_path / "outward")
    (outward / "linked_dir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.save(CE.open_capture(outward), tmp_path / "outward_saved")
    assert caught.value.code in ("capture_path_escapes", "capture_directory_is_a_symlink")
    assert not (tmp_path / "outward_saved" / "linked_dir").exists()

    looped = _copy_whole(work, tmp_path / "looped")
    (looped / "loop").symlink_to(looped, target_is_directory=True)
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.save(CE.open_capture(looped), tmp_path / "loop_saved")
    assert caught.value.code == "capture_directory_is_a_symlink", caught.value.code


def test_the_source_version_does_not_depend_on_the_order_of_the_filesystem(work, tmp_path):
    """A source's version is a property of its content, not of the directory traversal order."""
    twin = _copy_whole(work, tmp_path / "twin")
    first = CE.open_capture(work)
    second = CE.open_capture(twin)
    assert first.source_version == second.source_version
    assert first.sidecar_digests == second.sidecar_digests

    shuffled = dict(reversed(list(first.sidecar_digests.items())))
    assert CE._source_version(first.source_sha256, shuffled, "editable") \
        == first.source_version

    # A renamed sidecar with the SAME content gives a DIFFERENT version, and
    # this is a decision: under a different name the lifter no longer reads
    # it, so the lift is different.
    renamed = _copy_whole(work, tmp_path / "renamed_side")
    (renamed / "sketch.index.json").rename(renamed / "sketch.index.json.bak")
    assert CE.open_capture(renamed).source_version != first.source_version


# ── scenes from the external audit ───────────────────────────────────────────────────
# 🔴 EXTERNAL AUDIT 07.09.2026, KIR-F003 and KIR-G001, SNAPSHOT `ad78e64`.
# Both reproduced verbatim on a frozen copy (`git archive ad78e64`,
# PYTHONNOUSERSITE=1):
#   F003 — `save`, whose `OSError` arrives on the SECOND file (already after
#          copying `L0.jsonl`), left behind the `f003_target` directory, and
#          `open_capture` ACCEPTED it: the slab came up as `kind=atom`,
#          0 edits. The source stayed byte-for-byte unchanged throughout —
#          meaning the trouble was exactly that half the work was declared
#          as the work.
#   G001 — the nested `assets/opaque.bin` was lost, the top-level
#          `unknown_sidecar.json` was saved: "saved" meant "the top level
#          was saved".
AUDIT_OPAQUE = b"\x00KIR-OPAQUE-ASSET\xff" * 16


def _audit_capture(where: Path, source: Path) -> Path:
    """Audit scene: a real run + `unknown_sidecar.json` + `assets/`."""
    _copy_whole(source, where)
    (where / "unknown_sidecar.json").write_text('{"неизвестно":"но заявлено"}',
                                                encoding="utf-8")
    (where / "assets").mkdir(exist_ok=True)
    (where / "assets" / "opaque.bin").write_bytes(AUDIT_OPAQUE)
    return where


def test_the_audit_scene_f003_an_oserror_after_l0_leaves_nothing_that_opens(work, tmp_path,
                                                                            monkeypatch):
    """KIR-F003 as an audit scene: an `OSError` on the second file, already after copying L0."""
    source = _audit_capture(tmp_path / "f003_src", work)
    capture = CE.open_capture(source)
    before = {item.relative_to(source).as_posix(): item.read_bytes()
              for item in source.rglob("*") if item.is_file()}
    seen = {"l0": False}
    real = CE.shutil.copy2

    def dying(item, destination, *args, **kwargs):
        if Path(item).name.startswith("L0.jsonl"):
            seen["l0"] = True
            return real(item, destination, *args, **kwargs)
        if seen["l0"]:
            raise OSError(28, "No space left on device (сцена аудита)")
        return real(item, destination, *args, **kwargs)

    monkeypatch.setattr(CE.shutil, "copy2", dying)
    with pytest.raises(OSError):
        CE.save(capture, tmp_path / "f003_target")
    monkeypatch.undo()

    assert seen["l0"], "сцена не состоялась: обрыв случился до копии L0"
    # First condition: no directory is left that `open_capture` accepts.
    leftovers = [item for item in tmp_path.iterdir()
                 if item.is_dir() and snapshot_file_exists(item / "L0.jsonl")
                 and item.name.lstrip(".").startswith("f003_target")]
    assert not [str(item) for item in leftovers if _accepts_as_complete(item)], \
        f"оборванное сохранение принято за завершённое: {leftovers}"
    # Second condition: a directory WITH THE MARKER refuses by EXACTLY this name.
    marked = tmp_path / "f003_marked"
    marked.mkdir()
    shutil.copy2(source / "L0.jsonl", marked / "L0.jsonl")
    (marked / CE._PARTIAL_NAME).write_text("оборвано", encoding="utf-8")
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(marked)
    assert caught.value.code == "capture_save_incomplete", caught.value.code
    # The source is untouched by the interruption.
    assert {item.relative_to(source).as_posix(): item.read_bytes()
            for item in source.rglob("*") if item.is_file()} == before


def test_the_audit_scene_g001_a_nested_asset_is_kept_byte_for_byte(work, tmp_path):
    """KIR-G001 as an audit scene: `assets/opaque.bin` and `unknown_sidecar.json`."""
    source = _audit_capture(tmp_path / "g001_src", work)
    saved = CE.save(CE.open_capture(source), tmp_path / "g001_saved")

    asset = saved / "assets" / "opaque.bin"
    assert asset.exists(), (
        f"вложенный `assets/opaque.bin` потерян; в сохранённом caption "
        f"{sorted(item.name for item in saved.iterdir())}")
    assert asset.read_bytes() == AUDIT_OPAQUE, "вложенный asset доехал изменённым"
    assert (saved / "unknown_sidecar.json").read_text(encoding="utf-8") == \
        '{"неизвестно":"но заявлено"}'
