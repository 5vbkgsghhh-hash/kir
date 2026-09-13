# -*- coding: utf-8 -*-
"""Offline edit of a saved building: an address, exactly one edit, named
losses.

The corpus at `/opt/kukai-rebuild1/backend/backend/data/decompile` is READ
and never written: the test copies the run into its own `tmp_path`. Without
the corpus, the test is skipped — it is about a REAL building, and
substituting a made-up one would mean measuring the wrong thing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists

CORPUS = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A")
DOOR = "286533"
OPENING = "294707"
FLOOR = "287227"
ROOT = Path(__file__).resolve().parents[3]

# 🔴 `snapshot_file_exists` is asked, not `exists()`: on a compressed
# snapshot the bare verb would say "no", and skipping the test would read
# as "there is no corpus".
pytestmark = pytest.mark.skipif(not snapshot_file_exists(CORPUS / "L0.jsonl"),
                                reason="корпус bench_A недоступен на этой машине")


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    target = tmp_path_factory.mktemp("capture")
    for item in CORPUS.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)
    return target


def _l0_rows(path):
    rows = {}
    with (Path(path) / "L0.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "element" in row:
                rows[str(row["element"]["element_id"])] = row["element"]
    return rows


def test_the_corpus_is_only_read(work):
    """The one thing that must not be corrupted — the source run."""
    before = sorted((item.name, item.stat().st_mtime_ns, item.stat().st_size)
                    for item in CORPUS.iterdir() if item.is_file())
    capture = CE.open_capture(work)
    CE.edit_element(capture, DOOR, {"offset_mm": 1234.0})
    CE.losses(capture)
    after = sorted((item.name, item.stat().st_mtime_ns, item.stat().st_size)
                   for item in CORPUS.iterdir() if item.is_file())
    assert before == after, "корпус обязан остаться байт в байт"


def test_describe_names_both_what_is_known_and_what_was_lost(work):
    capture = CE.open_capture(work)
    door = CE.describe(capture, DOOR)
    assert door.category == "OST_Doors" and door.unique_id
    assert door.l1_op is not None and door.atom is None
    assert door.l1_op["params"]["offset_mm"] == pytest.approx(3000.0)
    # Even a LIFTED element has losses: L1 speaks the language of
    # operations.
    #
    # 🔴 `host_id` WAS REMOVED FROM THIS LIST 07.09.2026, AND THIS IS A
    # REMOVED LOSS, NOT A WEAKENED EXPECTATION. `create_door` names its host
    # as A REFERENCE TO A NODE (`host: {"ref": …}`); the ledger resolves it
    # and asks the resolved node for the source element. A match means the
    # host is represented in the IR. A pin on an ABSENCE went stale for the
    # simple reason that the work succeeded.
    assert set(door.losses) >= {"phase_created", "unique_id"}
    assert "host_id" not in door.losses
    assert door.field_states["host_id"] == "represented"
    # 🔴 ONE SUBJECT — ONE ANSWER. `describe()` and `losses()` count ONE
    # ledger; they used to diverge while `describe()` built it on a SINGLE
    # node and there was nothing to resolve the door's reference to the
    # wall against (12 losses versus 11).
    row = next(item for item in CE.losses(capture) if item.element_id == DOOR)
    assert set(row.fields) == set(door.losses)
    opening = CE.describe(capture, OPENING)
    assert opening.category == "OST_FloorOpening"
    assert opening.l1_op is None and opening.atom is not None
    # The state is named for EVERY non-empty field: a name with no state
    # does not say whose repair this is or how much of the fact survived.
    assert set(opening.field_states) == set(opening.l0_fields)
    assert set(opening.field_states.values()) <= {
        "represented", "approximate", "source_data", "unknown"}


def test_one_addressed_edit_changes_exactly_one_operation(work, tmp_path):
    capture = CE.open_capture(work)
    before = json.dumps(capture.nodes, sort_keys=True, default=str)
    was = capture.by_source[DOOR]["params"]["offset_mm"]
    result = CE.edit_element(capture, DOOR, {"offset_mm": was + 300.0})
    assert result.refusal is None
    assert len(result.changed_ops) == 1
    assert result.untouched_count == len(capture.elements) - 1
    after = json.loads(json.dumps(capture.nodes, sort_keys=True, default=str))
    moved = [i for i, (a, b) in enumerate(zip(json.loads(before), after)) if a != b]
    assert len(moved) == 1, "правка обязана тронуть РОВНО один узел"
    # L0 is untouched down to the byte: the source of truth is not rewritten by an edit.
    assert _l0_rows(work)[DOOR]["p0_mm"] == list(capture.elements[DOOR].p0_mm)


def test_untouched_field_slots_survive_the_edit(work):
    """Acceptance measure (b): field sums for UNTOUCHED elements are counted from L0, not from L1."""
    capture = CE.open_capture(work)
    rows = _l0_rows(work)
    rest = [row for key, row in rows.items() if key != DOOR]
    slots = sum(len(row) for row in rest)
    keys = sum(len(row.get("params") or {}) for row in rest)
    # 🔴 4200, NOT 9999. The door's host is 7500 mm long, and 9999 is now a
    # named refusal (`offset_out_of_host`): a pin resting on a refused edit
    # would be measuring "the neighbors' fields are intact because nothing
    # changed at all".
    CE.edit_element(capture, DOOR, {"offset_mm": 4200.0})
    rest_after = [row for key, row in _l0_rows(work).items() if key != DOOR]
    assert sum(len(row) for row in rest_after) == slots == 88_662
    assert sum(len(row.get("params") or {}) for row in rest_after) == keys == 19_552


def test_a_floor_opening_is_refused_by_name_and_never_guessed(work):
    """🔴 A BOUNDING BOX IS NOT A CONTOUR, AND ONE CANNOT PASS FOR THE OTHER."""
    capture = CE.open_capture(work)
    element = capture.elements[OPENING]
    # NOT A SINGLE element of this run has a contour — the refusal is not made up.
    assert not getattr(element, "opening_boundary_mm", None)
    assert all(not getattr(item, "opening_boundary_mm", None)
               for item in capture.document.elements)
    assert capture.by_source[FLOOR]["kind"] == "atom", "перекрытие поднято атомом"
    result = CE.edit_element(capture, OPENING, {"contour_mm": [[0, 0], [1, 1]]})
    assert result.refusal is not None
    assert result.refusal["code"] in ("floor_is_opaque_atom", "opening_contour_not_captured")
    assert result.refusal["address"] == OPENING
    assert result.changed_ops == ()


def test_an_unsupported_change_refuses_instead_of_quietly_doing_nothing(work):
    capture = CE.open_capture(work)
    assert CE.edit_element(capture, DOOR, {"rotation_deg": 5.0}
                           ).refusal["code"] == "unsupported_door_field"
    assert CE.edit_element(capture, DOOR, {}).refusal["code"] == "empty_change"
    assert CE.edit_element(capture, "0", {"offset_mm": 1.0}).refusal["code"] == "unknown_element"
    wall = next(key for key, element in capture.elements.items()
                if element.category == "OST_Walls")
    assert CE.edit_element(capture, wall, {"offset_mm": 1.0}
                           ).refusal["code"] == "unsupported_category"


def test_losses_are_addressed_and_never_silently_short(work):
    """Acceptance measure (c): no fewer lines than the number of opaque elements, each with an address."""
    capture = CE.open_capture(work)
    rows = CE.losses(capture)
    assert len(rows) >= 1109
    assert all(row.element_id and row.unique_id and row.fields for row in rows)
    assert all(row.why for row in rows)
    # Both kinds have losses: declaring them a property of atoms alone would be a lie.
    kinds = {row.why.split(":")[-1] for row in rows}
    assert {"atom", "op_language"} <= kinds


def test_the_export_compiles_for_both_revit_versions_and_spares_the_neighbours(work):
    """Acceptance measure (e) and half of (a): the edit does not rewrite the neighbors."""
    import difflib

    clean = CE.open_capture(work)
    base_programs, base_sources = CE.export_program(clean, revit_version="2026")
    assert base_programs and all(program.get("lineage") for program in base_programs)
    assert {program["lineage"] for program in base_programs} == {clean.lineage}
    for version in ("2023", "2026"):
        programs, sources = CE.export_program(clean, revit_version=version)
        assert len(programs) == len(sources)
        # 🔴 "NOT EVERYTHING TRANSLATED" IS A NUMBER, NOT AN EMPTY STRING.
        # Two programs (ducts and pipes) require a SNAPSHOT of the live
        # model to resolve names, and honestly refuse with `KIR-G103`. The
        # pin checks both: how much translated AND that the refusal is
        # named.
        #
        # 🔴 THE NUMBER MOVED 16 -> 38, AND THIS IS NOT A WEAKENING OF THE
        # PIN (07.09.2026). `open_capture` was not feeding the lifter the
        # SKETCH index, even though `sketch.index.json` sits in the run:
        # 128 profile lines, 43 of them for slabs and ceilings. With them,
        # atoms go 1292 -> 1268, programs 18 -> 40, translated 16 -> 38,
        # emitted ops 2860 -> 2884, and the refusals stay the same two
        # `KIR-G103`. The same index, opened to ALL categories, would cost
        # a third refusal (`KIR-L004`: roof 298459 stops being an atom, and
        # `set_curtain_panel` addresses it by `ref` instead of
        # `element_id`) and 220 emitted ops — which is why it is opened
        # only to the categories whose editing the contract knows how to
        # express.
        assert sum(1 for source in sources if source) == 38
        assert len(clean.export_refusals) == 2
        assert all(row["codes"] == ["KIR-G103"] for row in clean.export_refusals)
        assert all(row["detail"] for row in clean.export_refusals)

    edited = CE.open_capture(work)
    was = edited.by_source[DOOR]["params"]["offset_mm"]
    CE.edit_element(edited, DOOR, {"offset_mm": was + 300.0})
    _programs, sources = CE.export_program(edited, revit_version="2026")
    changed = 0
    for before, after in zip(base_sources, sources):
        changed += sum(1 for line in difflib.unified_diff(
            before.splitlines(), after.splitlines(), lineterm="", n=0)
            if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    # 🔴 A NUMBER, NOT "A FEW". Without a stable `lineage` there would be
    # ~500 of them: the stamp `kir:<дайджест программы>:<элемент>` sits in
    # the comment of EVERY element.
    assert changed <= 8, f"правка одной двери тронула {changed} строк C#"
    assert changed >= 2, "правка обязана быть видна в эмиссии"


def test_a_saved_capture_reopens_in_another_process_with_its_edit(work, tmp_path):
    """Acceptance measure (g): a restart by a REAL second process."""
    capture = CE.open_capture(work)
    was = capture.by_source[DOOR]["params"]["offset_mm"]
    CE.edit_element(capture, DOOR, {"offset_mm": was + 300.0})
    saved = tmp_path / "saved"
    CE.save(capture, saved)
    assert (saved / "capture_edits.jsonl").read_text(encoding="utf-8").strip()

    child = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists
capture = CE.open_capture(sys.argv[1])
print(json.dumps({"offset_mm": capture.by_source[sys.argv[2]]["params"]["offset_mm"],
                  "edits": len(capture.edits), "losses": len(CE.losses(capture))}))
""", str(saved), DOOR], capture_output=True, text=True, timeout=900,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr[-800:]
    payload = json.loads(child.stdout)
    assert payload["offset_mm"] == pytest.approx(was + 300.0)
    assert payload["edits"] == 1, "повторное сохранение не вправе потерять историю правок"
    assert payload["losses"] == len(CE.losses(capture))
    with pytest.raises(CE.CaptureEditError, match="target_not_empty"):
        CE.save(capture, saved)


# ── review A4: an invalid edit looked DONE ──────────────────────────
#: Ten values from the adversarial review (`capture-edit/reviewX/attack.py`).
#: On 07.09.2026 all ten were accepted silently: `refusal` empty,
#: `changed_ops` one, the value settling into the node. Door 286533's host
#: is wall 286530, 7500 mm long, 4500 mm high; leaf 864 × 2134 mm.
_BAD_DOOR_EDITS = (
    ({"offset_mm": 1e9}, "offset_out_of_host"),
    ({"offset_mm": -50_000.0}, "offset_out_of_host"),
    ({"offset_mm": float("nan")}, "non_finite_value"),
    ({"offset_mm": float("inf")}, "non_finite_value"),
    ({"offset_mm": True}, "bad_change_value"),
    ({"sill_mm": 1e7}, "sill_out_of_host"),
    ({"sill_mm": -5000.0}, "sill_out_of_host"),
    ({"symbol": {"by": "name", "value": "НЕТ ТАКОГО ТИПА"}}, "unknown_symbol"),
    ({"symbol": {"by": "name", "value": "Типовой - 200мм"}}, "symbol_category_mismatch"),
    ({"symbol": {}}, "bad_change_value"),
)


def test_a_bad_door_edit_is_refused_by_name_and_never_half_applied(work):
    """🔴 "THERE IS A CHANGE, THERE IS NO REFUSAL" IS WORSE THAN A SILENT
    REFUSAL.

    Every case must name a code AND leave the node byte-for-byte unchanged:
    an edit refused halfway is the same lie from the other side.
    """
    capture = CE.open_capture(work)
    node = capture.by_source[DOOR]
    before = json.dumps(node, sort_keys=True, default=str)
    for change, code in _BAD_DOOR_EDITS:
        result = CE.edit_element(capture, DOOR, change)
        assert result.refusal is not None, f"{change} принята молча"
        assert result.refusal["code"] == code, (change, result.refusal)
        assert result.refusal["address"] == DOOR
        assert result.changed_ops == ()
        assert json.dumps(node, sort_keys=True, default=str) == before, change
    # A mixed edit: one field valid, the other not — NOTHING is applied.
    mixed = CE.edit_element(capture, DOOR, {"offset_mm": 4200.0, "symbol": {}})
    assert mixed.refusal["code"] == "bad_change_value"
    assert json.dumps(node, sort_keys=True, default=str) == before
    assert capture.edits == []


def test_a_legal_edit_still_passes_and_names_what_it_knows(work):
    """A gate must not refuse what is LEGAL: otherwise it is guarding
    silence.

    🔴 THE UPPER BOUND IS THE HOST'S LENGTH, NOT "LENGTH − LEAF WIDTH".
    Measured on the corpus: the rule "offset ≤ length − width" is violated
    by 89 of 151 existing doors in `sob62_r23_v3` (the door sits CENTERED
    on the opening), while the compiler's law `0..length` is violated by
    none, neither there nor in `bench_A`. A leaf that overhangs is named a
    NOTE, not a refusal.
    """
    capture = CE.open_capture(work)
    ok = CE.edit_element(capture, DOOR, {"offset_mm": 3300.0})
    assert ok.refusal is None and len(ok.changed_ops) == 1 and ok.notes == ()
    edge = CE.edit_element(capture, DOOR, {"offset_mm": 7500.0})
    assert edge.refusal is None, "длина хозяина включительно — это закон компилятора"
    assert any("leaf_overhangs_host" in note for note in edge.notes), edge.notes
    # A negative sill elevation is LEGAL: it is measured from the wall's
    # level, and in `sob62_r23_v3` there are 140 such doors out of 151 (131
    # at exactly −100 mm).
    low = CE.edit_element(capture, DOOR, {"sill_mm": -100.0})
    assert low.refusal is None, low.refusal
    assert any("sill_below_host_bottom" in note for note in low.notes), low.notes
    good = CE.edit_element(capture, DOOR, {"symbol": {"by": "name",
                                                     "value": "0915 x 2134 мм"}})
    assert good.refusal is None, good.refusal


def test_a_corrupt_edits_file_is_named_with_the_line_that_broke(work, tmp_path):
    """The one file the module writes itself must be NAMED as broken."""
    capture = CE.open_capture(work)
    CE.edit_element(capture, DOOR, {"offset_mm": 3300.0})
    saved = tmp_path / "saved"
    CE.save(capture, saved)
    for text in ("{это не json}\n", json.dumps({"schema": "kir-capture-edit/1"}) + "\n"):
        (saved / "capture_edits.jsonl").write_text(text, encoding="utf-8")
        with pytest.raises(CE.CaptureEditError) as caught:
            CE.open_capture(saved)
        assert caught.value.code == "edits_file_corrupt"
        assert caught.value.address.endswith("capture_edits.jsonl:1")


def test_writing_into_a_capture_is_refused_by_the_rule_not_by_the_filesystem(work, tmp_path):
    """🔴 FILESYSTEM PERMISSIONS ARE NOT A CONTRACT. It was them, not us, that saved the corpus's empty subdirectory."""
    capture = CE.open_capture(work)
    with pytest.raises(CE.CaptureEditError) as inside:
        CE.save(capture, work / "__pin_inside__")
    assert inside.value.code == "target_inside_source"
    assert not (work / "__pin_inside__").exists()
    # Someone else's run (the corpus itself) — by the same rule, not because it is not ours.
    with pytest.raises(CE.CaptureEditError) as corpus:
        CE.save(capture, CORPUS / "__pin_corpus__")
    assert corpus.value.code == "target_inside_capture"
    assert not (CORPUS / "__pin_corpus__").exists()
    ok = CE.save(capture, tmp_path / "elsewhere")
    # 🔴 `snapshot_file_exists` IS ASKED, NOT `exists()`: a snapshot is
    # entitled to sit compressed, and the bare verb by name would answer
    # "no" where the file exists — that is, "there was no save". The
    # `test_snapshot_existence_is_asked` guard has held this since
    # 20.08.2026 and caught exactly this line.
    assert snapshot_file_exists(ok / "L0.jsonl")


def test_a_non_finite_number_in_a_node_is_named_before_the_fold_breaks(work):
    """A NaN used to reach `fold_document` and blow up as a nameless `FoldError`."""
    capture = CE.open_capture(work)
    capture.by_source[DOOR]["params"]["offset_mm"] = float("nan")
    with pytest.raises(CE.CaptureEditError) as caught:
        CE.export_program(capture)
    assert caught.value.code == "non_finite_value"
    assert caught.value.address == DOOR
