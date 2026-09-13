# -*- coding: utf-8 -*-
"""AN EDIT IS BOUND TO THE ENTIRE SOURCE, NOT TO A SINGLE L0.

Scene provenance at the bottom of the file: an external audit on
07.09.2026, KIR-F002/F003/G001, snapshot `ad78e64`; re-measured on a
FROZEN copy (`git archive ad78e64`, PYTHONNOUSERSITE=1) — all three
reproduced verbatim.

A reconnaissance measurement, 07.09.2026 (probe
`.work/marathon-fable-20260907/capture/probe.py`, line H): in a saved
capture, `sketch.index.json` was replaced wholesale —
`{"profile_index": {}}` instead of 128 lines of profiles — and
`open_capture` accepted this SILENTLY: `source_sha256` was computed only
from the bytes of `L0.jsonl` and stayed the same. That is, for `bench_A`
all 21 nodes carrying opening rings vanished, old opening edits would
replay against DIFFERENT geometry, and the source version claimed the
building was unchanged.

The second half: an edit row carried only the address (`element_id`) and
the `change`. It contained no expected PRIOR value, so a matching address
was enough for an edit to land on a different value while saying nothing
about it.

The corpus is READ and never written to.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists

CORPUS = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A")
DOOR = "286533"

pytestmark = pytest.mark.skipif(not snapshot_file_exists(CORPUS / "L0.jsonl"),
                                reason="корпус bench_A недоступен на этой машине")


def _copy_whole(source: Path, target: Path) -> Path:
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
    return _copy_whole(CORPUS, tmp_path_factory.mktemp("bind") / "bench_A")


@pytest.fixture(scope="module")
def saved(work, tmp_path_factory):
    """A saved capture WITH AN EDIT — the subject of every measurement
    below."""
    capture = CE.open_capture(work)
    assert CE.edit_element(capture, DOOR, {"offset_mm": 1300.0}).refusal is None
    return CE.save(capture, tmp_path_factory.mktemp("bound") / "saved")


def test_a_changed_sidecar_at_the_same_l0_is_refused_by_name(saved, tmp_path):
    """One applicable sidecar changed — a named refusal, not different
    geometry."""
    scene = _copy_whole(saved, tmp_path / "moved_sketch")
    payload = json.loads((scene / "sketch.index.json").read_text(encoding="utf-8"))
    assert payload.get("profile_index"), "в прогоне нет профилей — замер не о том"
    payload["profile_index"] = {}
    (scene / "sketch.index.json").write_text(json.dumps(payload), encoding="utf-8")

    assert (scene / "L0.jsonl").read_bytes() == (saved / "L0.jsonl").read_bytes(), \
        "L0 тоже изменился — замер перестал быть о sidecar"
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(scene)
    assert caught.value.code == "source_sidecar_changed", caught.value.code
    assert "sketch" in str(caught.value), str(caught.value)


def test_an_untouched_move_of_the_saved_capture_still_opens(saved, tmp_path):
    """A counterweight: the version guard has no right to turn red from a
    rename."""
    moved = _copy_whole(saved, tmp_path / "renamed")
    capture = CE.open_capture(moved)
    assert capture.lineage == CE.open_capture(saved).lineage
    assert capture.integrity == "pinned:source_version", capture.integrity


def test_the_written_edit_carries_the_value_it_expected_to_find(saved):
    """An address without an expected prior value is not a binding, it is
    a coincidence."""
    rows = [json.loads(line) for line
            in (saved / CE._EDITS_NAME).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, "правок не записано — замер не о том"
    row = rows[0]
    assert "before" in row, f"строка правки без ожидаемого прежнего значения: {row}"
    assert "offset_mm" in row["before"], row["before"]
    assert row["before"]["offset_mm"] != row["change"]["offset_mm"], row


def test_an_edit_whose_previous_value_moved_is_refused_by_name(saved, tmp_path):
    """The value under the edit has moved — a named refusal, not a silent
    overwrite."""
    scene = _copy_whole(saved, tmp_path / "moved_value")
    rows = [json.loads(line) for line
            in (scene / CE._EDITS_NAME).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["before"]["offset_mm"] = -12345.0
    (scene / CE._EDITS_NAME).write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8")

    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(scene)
    assert caught.value.code == "edit_before_value_mismatch", caught.value.code
    assert DOOR in str(caught.value.address or ""), caught.value.address


def test_legacy_metadata_is_read_with_the_lesser_guarantee_it_actually_has(saved, tmp_path):
    """Old metadata cannot be silently granted the integrity of the new
    format."""
    scene = _copy_whole(saved, tmp_path / "legacy")
    meta = json.loads((scene / CE._META_NAME).read_text(encoding="utf-8"))
    legacy = {"schema": meta["schema"], "lineage": meta["lineage"],
              "source_sha256": meta["source_sha256"], "edits": meta.get("edits", 0)}
    (scene / CE._META_NAME).write_text(json.dumps(legacy, sort_keys=True), encoding="utf-8")

    capture = CE.open_capture(scene)
    assert capture.integrity == "pinned:l0_only", capture.integrity
    assert capture.lineage == meta["lineage"]

    # And this is not a formality: for legacy records a swapped sidecar is
    # NOT caught, because the old record never pinned it in the first
    # place. Reporting it as "intact" would mean passing off the absence
    # of a guard as its silence.
    payload = json.loads((scene / "sketch.index.json").read_text(encoding="utf-8"))
    payload["profile_index"] = {}
    (scene / "sketch.index.json").write_text(json.dumps(payload), encoding="utf-8")
    assert CE.open_capture(scene).integrity == "pinned:l0_only"


def test_a_capture_names_how_its_edits_are_bound(saved, tmp_path):
    """The kind of edit binding is a property the caller must be able to
    read."""
    assert CE.open_capture(saved).edit_binding == "before_value"

    scene = _copy_whole(saved, tmp_path / "address_only")
    rows = [json.loads(line) for line
            in (scene / CE._EDITS_NAME).read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row.pop("before", None)
    (scene / CE._EDITS_NAME).write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8")
    assert CE.open_capture(scene).edit_binding == "address_only"


@pytest.mark.parametrize("written,found,same", [
    (0.0, -0.0, True),
    (2100, 2100.0, True),
    (1300.0, json.loads(json.dumps(1300.0)), True),
    ([[0.0, 1.0]], [[-0.0, 1]], True),
    (2100.0, 2101.0, False),
    (2100.0, 2100.000001, False),
])
def test_the_before_value_compares_content_not_the_shape_of_the_number(written, found, same):
    """A false refusal on an unchanged value is worse than a miss: it
    stalls the work."""
    assert (CE._canon(written) == CE._canon(found)) is same


def test_a_round_trip_through_the_edits_file_does_not_invent_a_mismatch(saved, tmp_path):
    """Save-open-save-open: `before` survives the JSON round trip without
    drift."""
    twice = CE.save(CE.open_capture(saved), tmp_path / "twice")
    capture = CE.open_capture(twice)
    assert capture.edit_binding == "before_value"
    assert capture.by_source[DOOR]["params"]["offset_mm"] == 1300.0


# ── the external-audit scene ────────────────────────────────────────────────
# 🔴 EXTERNAL AUDIT 07.09.2026, KIR-F002, SNAPSHOT `ad78e64`. The audit
# reproduced, on published main: a VALID replacement of
# `sketch.index.json` with a byte-for-byte unchanged `L0.jsonl` —
# the outer contour 4000 -> 5000, the opening moved to [2800,3400]² —
# was accepted SILENTLY, and the old edit replayed on top of the NEW
# geometry. A re-measurement on a frozen copy (`git archive ad78e64`,
# PYTHONNOUSERSITE=1) confirmed it verbatim: no refusal, the opening after
# the replay is [[1200,1200],[1800,1200],[1800,1800],[1200,1800]] — a ring
# computed over the OLD contour and landing on the NEW one. Below is the
# same scene with the same numbers.
AUDIT_FLOOR = "286551"
AUDIT_PROFILE_BEFORE = {
    "arc_midpoints": [[None] * 4, [None] * 4],
    "curve_kinds": [["line"] * 4, ["line"] * 4],
    "exterior_loop": [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]],
    "holes": [[[1000.0, 1000.0], [2000.0, 1000.0], [2000.0, 2000.0], [1000.0, 2000.0]]],
    "profile_available": True}
AUDIT_PROFILE_AFTER = {
    "arc_midpoints": [[None] * 4, [None] * 4],
    "curve_kinds": [["line"] * 4, ["line"] * 4],
    "exterior_loop": [[0.0, 0.0], [5000.0, 0.0], [5000.0, 5000.0], [0.0, 5000.0]],
    "holes": [[[2800.0, 2800.0], [3400.0, 2800.0], [3400.0, 3400.0], [2800.0, 3400.0]]],
    "profile_available": True}
AUDIT_EDIT_RING = [[1200.0, 1200.0], [1800.0, 1200.0], [1800.0, 1800.0], [1200.0, 1800.0]]


def _audit_l0_rows():
    """L0 rows for the scene: a real corpus header and a REAL floor slab.

    A synthetic element here would be a second answer to the question
    "what is a floor slab": the row is taken from the corpus, and what
    remains in dispute in the scene is exactly what the audit changed —
    the sketch profile.
    """
    from kir.decompile.extract import EXTRACT_CATEGORIES
    header = floor = None
    with (CORPUS / "L0.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "document" in row and header is None:
                header = row
            if str((row.get("element") or {}).get("element_id")) == AUDIT_FLOOR:
                floor = row
                break
    assert floor is not None, f"в корпусе нет перекрытия {AUDIT_FLOOR} — сцена не та"
    rows = [header]
    for category in EXTRACT_CATEGORIES:
        count = 1 if category == "OST_Floors" else 0
        if count:
            rows.append(floor)
        rows.append({"record": "category_status",
                     "status": {"category": category, "error": None,
                                "expected_count": count, "extracted_count": count,
                                "section_receipts": [], "state": "complete"}})
    rows.append({"record": "footer", "category_count": len(EXTRACT_CATEGORIES),
                 "element_count": 1, "link_count": 0, "stream_complete": True,
                 "dialect": "kir-decompile-l0-dialect/7"})
    return rows


def _audit_scene(where: Path, profile: dict, rows) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    (where / "L0.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    (where / "sketch.index.json").write_text(json.dumps(
        {"schema_version": "kir-decompile-sketch/1",
         "profile_index": {AUDIT_FLOOR: profile}}, ensure_ascii=False), encoding="utf-8")
    return where


@pytest.fixture(scope="module")
def audit_rows():
    return _audit_l0_rows()


def test_the_audit_scene_f002_a_valid_sidecar_swap_at_the_same_l0(audit_rows, tmp_path):
    """KIR-F002 via the audit's scene: contour 4000->5000, opening at
    [2800,3400]²."""
    source = _audit_scene(tmp_path / "f002_src", AUDIT_PROFILE_BEFORE, audit_rows)
    capture = CE.open_capture(source)
    assert CE.edit_element(capture, AUDIT_FLOOR,
                           {"opening_index": 0,
                            "opening_contour_mm": AUDIT_EDIT_RING}).refusal is None
    saved = CE.save(capture, tmp_path / "f002_saved")

    l0_before = (saved / "L0.jsonl").read_bytes()
    payload = json.loads((saved / "sketch.index.json").read_text(encoding="utf-8"))
    payload["profile_index"][AUDIT_FLOOR] = AUDIT_PROFILE_AFTER
    (saved / "sketch.index.json").write_text(json.dumps(payload, ensure_ascii=False),
                                             encoding="utf-8")
    assert (saved / "L0.jsonl").read_bytes() == l0_before, \
        "L0 изменился — сцена перестала быть о sidecar при прежнем L0"

    with pytest.raises(CE.CaptureEditError) as caught:
        CE.open_capture(saved)
    assert caught.value.code == "source_sidecar_changed", caught.value.code
    # The refusal names the KIND of sidecar that moved; the filename for
    # that kind is exactly the one the audit swapped.
    assert "sketch" in str(caught.value), str(caught.value)
    assert CE._side_path(saved, "sketch").name == "sketch.index.json"

    # The source version of the two scenes is DIFFERENT — while the L0 is
    # byte-for-byte identical.
    untouched = _audit_scene(tmp_path / "f002_after", AUDIT_PROFILE_AFTER, audit_rows)
    assert CE.open_capture(source).source_version != CE.open_capture(untouched).source_version

    # The edit was NOT replayed, the new opening [2800,3400]² is intact —
    # both on disk and when the scene is brought up without edits.
    on_disk = json.loads((saved / "sketch.index.json").read_text(
        encoding="utf-8"))["profile_index"][AUDIT_FLOOR]["holes"][0]
    assert on_disk == AUDIT_PROFILE_AFTER["holes"][0]
    holes, _ = CE._holes_of(CE.open_capture(untouched).by_source.get(AUDIT_FLOOR))
    assert CE._points_of(holes[0]) == AUDIT_PROFILE_AFTER["holes"][0]
    assert CE._points_of(holes[0]) != AUDIT_EDIT_RING
