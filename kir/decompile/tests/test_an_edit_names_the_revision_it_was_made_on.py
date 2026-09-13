# -*- coding: utf-8 -*-
"""The `capture_revision` seam: an edit knows the document revision it was
based on.

🔴 BEFORE 07.09.2026 THIS SEAM DID NOT EXIST AT ALL — IT EXISTED AS TEXT.
The only mention of `capture_revision` in the tree was in
`docs/DELIVERY_PLAN_RU.md:92`, on the line "F5 — NOT done," and it meant
exactly what it said: the name exists, the subject does not.
`capture_edit` never once read the `revision.proof.json` file, even
though decompile writes it in 80 of 81 corpus runs (missing only for
`demo-v3`), and `serving.py:8818` judges the live model by it
(`active_revision != manifest.revision_proof.fingerprint`).

THE MEASUREMENT THAT REVEALED THIS (probe `p7_revision.py`, 07.09.2026).
A `bench_A` slice, door 286533, an `offset_mm` edit 3000 -> 1111, saved.
Then a `revision.proof.json` from a DIFFERENT building (`k4_geom_wave2`,
fingerprint `390371:c10b26…`) is placed into the SAVED capture, while
`L0.jsonl` and every side index remain byte-for-byte the same. Opening it
went through SILENTLY: the edit replayed, `offset_mm` became 1111.0, and
`Capture.integrity` kept answering `pinned:source_version` — that is, the
capture claimed to be bound to the ENTIRE source while actually being
bound to everything EXCEPT the revision.

WHY NOT JUST FOLD THE REVISION INTO `source_version`. These are different
questions, and one digest would answer both with a single word.
`source_version` answers "will the SAME THING come up": it covers exactly
what the lifter reads (L0, `_SIDE`, `profiles` mode). The lifter never
reads the revision at all — it answers "WHAT WAS THIS EDITED THING
CAPTURED FROM." Merging them, the `source_sidecar_changed` refusal would
start firing where no index had moved at all, leaving nothing to fix.

THREE STATES, NOT TWO. `Capture.capture_revision` distinguishes "no file"
(`absent:…`), "the file exists and cannot be read" (`unreadable:…`), and
the revision itself; `Capture.revision_binding` distinguishes "no edits"
(`none`), "every edit names a revision" (`pinned`), and "there are rows
from the old record" (`unpinned`). Treating an old record as pinned would
mean reporting a guard that is not actually present in it.
"""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from kir.decompile import capture_edit as CE

SLICES = pathlib.Path(__file__).resolve().parent / "capture_slices"
HOME = "bench_A"
FOREIGN = "k4_geom_wave2"


def _seeds(name: str) -> dict:
    return json.loads((SLICES / name / "SLICE.json").read_text(encoding="utf-8"))["семена"]


@pytest.fixture
def work(tmp_path):
    target = tmp_path / HOME
    shutil.copytree(SLICES / HOME, target)
    return target


def _edited(work, tmp_path, name="saved"):
    door = _seeds(HOME)["door"]
    capture = CE.open_capture(work)
    assert CE.edit_element(capture, door, {"offset_mm": 1111.0}).refusal is None
    return CE.save(capture, tmp_path / name), door


# ── the revision EXISTS and it is named ─────────────────────────────────
def test_a_capture_says_which_document_revision_it_came_from(work):
    """Not an empty string, but a parsed decompile proof."""
    capture = CE.open_capture(work)
    proof = json.loads((work / "revision.proof.json").read_text(encoding="utf-8"))
    assert capture.capture_revision == (
        f"{proof['schema_version']}|{proof['change_stamp']}|{proof['fingerprint']}")
    assert capture.revision_binding == "none", "правок нет — привязывать нечего"


def test_an_edit_carries_the_revision_into_the_journal(work, tmp_path):
    """The edit row NAMES the revision, rather than relying on a
    neighboring file."""
    saved, _door = _edited(work, tmp_path)
    rows = [json.loads(line) for line
            in (saved / "capture_edits.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert rows and all(row.get("capture_revision") for row in rows)
    meta = json.loads((saved / "capture_meta.json").read_text(encoding="utf-8"))
    assert meta["capture_revision"] == rows[0]["capture_revision"]
    assert meta["revision_schema"] == CE._REVISION_SCHEMA
    reopened = CE.open_capture(saved)
    assert reopened.revision_binding == "pinned"


# ── the revision HAS MOVED — refusal BY NAME ───────────────────────────────
def test_a_foreign_revision_under_the_same_snapshot_is_refused_by_name(work, tmp_path):
    """L0 and the sidecars are the same, the revision is foreign —
    `capture_revision_moved`.

    This is exactly the measurement that was RED before this fix.
    """
    saved, _door = _edited(work, tmp_path)
    before = (saved / "L0.jsonl.gz").read_bytes()
    (saved / "revision.proof.json").write_text(
        (SLICES / FOREIGN / "revision.proof.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    assert (saved / "L0.jsonl.gz").read_bytes() == before, "подменять надо ТОЛЬКО ревизию"

    with pytest.raises(CE.CaptureEditError) as refusal:
        CE.open_capture(saved)
    assert refusal.value.code == "capture_revision_moved"
    assert FOREIGN in str(refusal.value), "отказ обязан назвать, КУДА уехала ревизия"


def test_a_removed_revision_proof_is_also_a_move(work, tmp_path):
    """Removing the proof is also a shift: "no revision" ≠ "the same
    revision"."""
    saved, _door = _edited(work, tmp_path)
    (saved / "revision.proof.json").unlink()
    with pytest.raises(CE.CaptureEditError) as refusal:
        CE.open_capture(saved)
    assert refusal.value.code == "capture_revision_moved"
    assert CE._REVISION_ABSENT in str(refusal.value)


def test_a_damaged_revision_proof_is_not_the_same_as_a_missing_one(work, tmp_path):
    """Corruption is CALLED corruption, not absence: there are three
    states, not two."""
    saved, _door = _edited(work, tmp_path)
    (saved / "revision.proof.json").write_text("{ это не json", encoding="utf-8")
    assert CE._capture_revision(saved).startswith("unreadable:")
    assert CE._capture_revision(saved) != CE._REVISION_ABSENT
    with pytest.raises(CE.CaptureEditError) as refusal:
        CE.open_capture(saved)
    assert refusal.value.code == "capture_revision_moved"


# ── what the seam does NOT do ───────────────────────────────────────────
def test_a_capture_without_a_proof_still_opens_and_says_so(work, tmp_path):
    """A run WITHOUT the proof is readable — and names this in words
    rather than staying silent.

    Refusing it would mean declaring unreadable every corpus run captured
    before this file existed. The reader must see the difference, and it
    does.
    """
    (work / "revision.proof.json").unlink()
    capture = CE.open_capture(work)
    assert capture.capture_revision == CE._REVISION_ABSENT
    door = _seeds(HOME)["door"]
    assert CE.edit_element(capture, door, {"offset_mm": 1111.0}).refusal is None
    saved = CE.save(capture, tmp_path / "no-proof")
    again = CE.open_capture(saved)
    assert again.revision_binding == "pinned", "«ревизии нет» тоже закрепляется"
    assert again.capture_revision == CE._REVISION_ABSENT
    assert again.by_source[door]["params"]["offset_mm"] == 1111.0


def test_an_old_edit_row_without_a_revision_is_unpinned_not_refused(work, tmp_path):
    """A record from before 07.09.2026 is read WITH ITS OWN, WEAKER
    guarantee.

    🔴 TREATING IT AS PINNED WOULD BE REPORTING A GUARD THAT DOES NOT
    EXIST. Refusing it would declare unreadable everything saved earlier.
    So there is a third state, and it is read in words.
    """
    saved, door = _edited(work, tmp_path)
    path = saved / "capture_edits.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    for row in rows:
        row.pop("capture_revision", None)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            for row in rows), encoding="utf-8")
    meta_path = saved / "capture_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("capture_revision", None)
    meta.pop("revision_schema", None)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    capture = CE.open_capture(saved)
    assert capture.revision_binding == "unpinned"
    assert capture.by_source[door]["params"]["offset_mm"] == 1111.0
