# -*- coding: utf-8 -*-
"""ONE SELECTOR — ONE TYPE · IDENTITY IS PINNED · THE OPENING CAN BE
EDITED.

Three findings by the owner, 07.09.2026:

(4a) `symbol={by:"name", value:"DoorTypeA"}` was ACCEPTED by the
     validator, while export dropped it ("_id None is not an
     integer"); `{by:"name", value:"A", _id:102}` was checked by the
     validator as "A," while export set type 102 (`materialize.py:1396`
     reads ONLY `_id`). Now there is ONE translation —
     `capture_edit.resolve_type` — and it is the same one that guards
     export.
(4b) `lineage` was derived from THE DIRECTORY'S NAME, yet it travels in
     the program's envelope: an `mv` of a saved capture changed the
     exported program's digest without touching anything in the
     building.
(8)  Editing a floor slab opening was an UNCONDITIONAL refusal. The
     refusal was honest, but it measured a document lifted WITHOUT the
     sketch index: `open_capture` was not feeding `profile_index` to
     the lifter, even though `sketch.index.json` sits in the run. With
     it, 21 nodes of `bench_A` carry real opening rings.

The corpus is READ and never written to.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists

CORPUS = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A")
OTHER = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/k4_geom_wave_15aug")
DOOR = "286533"
OPENING = "294707"

pytestmark = pytest.mark.skipif(not snapshot_file_exists(CORPUS / "L0.jsonl"),
                                reason="корпус bench_A недоступен на этой машине")


def _copy(source: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)
    return target


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    return _copy(CORPUS, tmp_path_factory.mktemp("selector") / "bench_A")


def _door_type(capture):
    catalog = CE.type_catalog(capture)
    names = sorted(name for name, cats in catalog["name_categories"].items()
                   if "OST_Doors" in cats)
    assert names, "в capture нет ни одного дверного типа"
    ids = sorted(catalog["by_name"][names[0]])
    assert len(ids) == 1, f"имя {names[0]} носят {len(ids)} типа — сцена не та"
    return names[0], ids[0]


def test_by_name_and_by_id_mean_the_same_type_in_the_node(work):
    """Both selectors must settle in the node as ONE canonical shape."""
    name, identifier = _door_type(CE.open_capture(work))

    by_name = CE.open_capture(work)
    assert CE.edit_element(by_name, DOOR, {"symbol": {"by": "name", "value": name}}).refusal is None
    by_id = CE.open_capture(work)
    assert CE.edit_element(by_id, DOOR,
                           {"symbol": {"by": "element_id", "value": identifier}}).refusal is None

    left = by_name.by_source[DOOR]["params"]["symbol"]
    right = by_id.by_source[DOOR]["params"]["symbol"]
    assert left == right == {"by": "name", "value": name, "_id": identifier}
    # 🔴 THE MAIN NUMBER: `_id` IS SET. Without it, export dropped
    # `MaterializeError` — meaning the validator was accepting an edit
    # that could not be carried out.
    assert "_id" in left and str(left["_id"]) == str(identifier)


def test_a_selector_whose_name_and_id_disagree_is_refused_by_name(work):
    capture = CE.open_capture(work)
    name, identifier = _door_type(capture)
    catalog = CE.type_catalog(capture)
    alien = next(key for key in sorted(catalog["by_id"]) if key != identifier)
    result = CE.edit_element(capture, DOOR,
                             {"symbol": {"by": "name", "value": name, "_id": alien}})
    assert result.refusal is not None
    assert result.refusal["code"] == "selector_inconsistent", result.refusal
    assert str(alien) in result.refusal["detail"]
    assert result.changed_ops == ()
    # The node is not touched: a partial result declared as a refusal
    # is the same falsehood.
    assert str(capture.by_source[DOOR]["params"]["symbol"]["_id"]) == str(identifier)


def test_a_document_default_symbol_is_refused_instead_of_breaking_the_export(work):
    """`by:"default"` was accepted with a marker and dropped export:
    there is nowhere to take `_id` from."""
    capture = CE.open_capture(work)
    result = CE.edit_element(capture, DOOR, {"symbol": {"by": "default"}})
    assert (result.refusal or {}).get("code") == "symbol_unresolvable_offline", result.refusal


def test_the_export_guard_uses_the_same_resolver(work, tmp_path):
    """Export's guard is the same catalogue: a mismatch is caught
    BEFORE the compiler."""
    capture = CE.open_capture(work)
    name, identifier = _door_type(capture)
    catalog = CE.type_catalog(capture)
    alien = next(key for key in sorted(catalog["by_id"])
                 if key != identifier and catalog["by_id"][key] != name)
    # The forgery goes AROUND the validator — straight into the node,
    # the way a foreign node writer would do it. The guard must catch
    # it at export.
    capture.by_source[DOOR]["params"]["symbol"] = {"by": "name", "value": name,
                                                   "_id": alien}
    with pytest.raises(CE.CaptureEditError) as raised:
        CE.export_program(capture)
    assert raised.value.code == "selector_inconsistent"
    assert raised.value.address == DOOR


def test_lineage_is_pinned_at_save_and_survives_a_rename(work, tmp_path):
    """🔴 RENAMING THE DIRECTORY DOES NOT CHANGE THE PROGRAM'S
    IDENTITY."""
    capture = CE.open_capture(work)
    assert capture.lineage_source == "directory_name"
    CE.edit_element(capture, DOOR, {"offset_mm": 3300.0})
    saved = CE.save(capture, tmp_path / "saved-here")
    assert (saved / "capture_meta.json").exists()

    first = CE.open_capture(saved)
    assert first.lineage_source == "capture_meta.json"
    assert first.lineage == capture.lineage
    programs_first, _ = CE.export_program(first)

    renamed = saved.parent / "renamed-XYZ"
    saved.rename(renamed)
    second = CE.open_capture(renamed)
    programs_second, _ = CE.export_program(second)

    assert second.lineage == first.lineage
    digest = lambda rows: hashlib.sha256(                       # noqa: E731
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest(programs_first) == digest(programs_second), (
        "дайджест программы поехал от переименования каталога")
    # A tautology control: the directory's name IS ACTUALLY different.
    assert renamed.name != saved.name
    assert CE._lineage_of(renamed) != second.lineage


@pytest.mark.skipif(not snapshot_file_exists(OTHER / "L0.jsonl"),
                    reason="второго прогона корпуса нет на этой машине")
def test_edits_bound_to_another_capture_are_refused_by_name(work, tmp_path):
    """The element addresses of the two buildings match by
    construction — that is not enough."""
    capture = CE.open_capture(work)
    CE.edit_element(capture, DOOR, {"offset_mm": 3300.0})
    saved = CE.save(capture, tmp_path / "bound")

    alien = _copy(OTHER, tmp_path / "alien")
    shutil.copy2(saved / "capture_meta.json", alien / "capture_meta.json")
    shutil.copy2(saved / "capture_edits.jsonl", alien / "capture_edits.jsonl")
    with pytest.raises(CE.CaptureEditError) as raised:
        CE.open_capture(alien)
    assert raised.value.code == "edits_belong_to_another_capture"


def test_a_floor_opening_contour_is_editable_where_the_capture_carries_one(work):
    """🔴 THE POSITIVE SCENARIO (8). The ring EXISTS — meaning it can
    be edited."""
    capture = CE.open_capture(work)
    assert "sketch" in capture.side_indexes, (
        "эскизный индекс не прочитан: контур измерялся бы у беднее поднятого "
        "документа, и «контура нет» было бы свойством НАШЕГО чтения")
    holed = [(str(node.get("source_element_id")), node)
             for node in capture.nodes if CE._holes_of(node)[0]]
    assert len(holed) == 21, f"узлов с отверстиями {len(holed)}, ожидалось 21"

    element_id = "286551"
    node = capture.by_source[element_id]
    before = [list(point) for point in CE._holes_of(node)[0][0]]
    assert before == [[12000.0, 2000.0], [24000.0, 2000.0],
                      [24000.0, 9500.0], [12000.0, 9500.0]]

    ring = [[13000.0, 3000.0], [23000.0, 3000.0], [23000.0, 9000.0], [13000.0, 9000.0]]
    result = CE.edit_element(capture, element_id,
                             {"opening_index": 0, "opening_contour_mm": ring})
    assert result.refusal is None, result.refusal
    assert result.changed_ops == (str(node.get("_id")),)
    assert result.untouched_count == len(capture.elements) - 1
    assert CE._holes_of(capture.by_source[element_id])[0][0] == ring
    # Export after the edit TRANSLATES, not merely "did not crash."
    programs, sources = CE.export_program(capture)
    assert sum(1 for source in sources if source) == 38
    assert all(row["codes"] == ["KIR-G103"] for row in capture.export_refusals)


def test_a_contour_outside_the_slab_is_refused_by_the_forward_law(work):
    """The forward path's own law, not ours: `geom.check_holes_relation`."""
    capture = CE.open_capture(work)
    huge = [[-1e6, -1e6], [1e6, -1e6], [1e6, 1e6]]
    result = CE.edit_element(capture, "286551",
                             {"opening_index": 0, "opening_contour_mm": huge})
    assert (result.refusal or {}).get("code") == "opening_outside_outline", result.refusal
    assert CE._holes_of(capture.by_source["286551"])[0][0] != huge


def test_the_opening_whose_slab_has_no_contour_is_still_refused_with_an_address(work):
    """🔴 THE HONEST REFUSAL IS NOT CANCELED. 287227 has two dependent
    sketches, the profile is unreachable."""
    capture = CE.open_capture(work)
    result = CE.edit_element(capture, OPENING,
                             {"opening_contour_mm": [[0., 0.], [1., 0.], [1., 1.]]})
    assert (result.refusal or {}).get("code") == "floor_is_opaque_atom", result.refusal
    assert result.refusal["address"] == OPENING
    assert "287227" in result.refusal["detail"]


def test_the_corpus_is_only_read_by_this_file(work):
    before = sorted((item.name, item.stat().st_mtime_ns, item.stat().st_size)
                    for item in CORPUS.iterdir() if item.is_file())
    capture = CE.open_capture(work)
    CE.edit_element(capture, "286551", {"opening_index": 0,
                                        "opening_contour_mm": [[13000.0, 3000.0],
                                                               [23000.0, 3000.0],
                                                               [23000.0, 9000.0],
                                                               [13000.0, 9000.0]]})
    after = sorted((item.name, item.stat().st_mtime_ns, item.stat().st_size)
                   for item in CORPUS.iterdir() if item.is_file())
    assert before == after


@pytest.mark.skipif(not snapshot_file_exists(OTHER / "L0.jsonl"),
                    reason="второго прогона корпуса нет на этой машине")
def test_edits_without_a_pinned_snapshot_are_refused_by_name(work, tmp_path):
    """🔴 THE GUARD STOOD EXACTLY WHERE AN ATTACKER WOULD HAVE HAD TO
    BRING THE EVIDENCE.

    Review 6's measurement: drop a lone `capture_edits.jsonl` (without
    metadata) into SOMEONE ELSE'S snapshot — the edit went through
    silently, a door's `offset_mm` changed from 3000.0 to 3300.0 in a
    different house; metadata WITHOUT `source_sha256` was accepted
    along with SOMEONE ELSE'S `lineage`, and that travels into the
    program's envelope and into every element's stamp.
    """
    capture = CE.open_capture(work)
    CE.edit_element(capture, DOOR, {"offset_mm": 3300.0})
    saved = CE.save(capture, tmp_path / "bound")

    lonely = _copy(OTHER, tmp_path / "lonely")
    shutil.copy2(saved / "capture_edits.jsonl", lonely / "capture_edits.jsonl")
    with pytest.raises(CE.CaptureEditError) as orphan:
        CE.open_capture(lonely)
    assert orphan.value.code == "capture_meta_missing"

    partial = _copy(OTHER, tmp_path / "partial")
    meta = json.loads((saved / "capture_meta.json").read_text(encoding="utf-8"))
    (partial / "capture_meta.json").write_text(
        json.dumps({key: value for key, value in meta.items() if key != "source_sha256"},
                   ensure_ascii=False), encoding="utf-8")
    shutil.copy2(saved / "capture_edits.jsonl", partial / "capture_edits.jsonl")
    with pytest.raises(CE.CaptureEditError) as unbound:
        CE.open_capture(partial)
    assert unbound.value.code == "capture_meta_incomplete"

    # Control: ONE'S OWN directory with full metadata still opens.
    again = CE.open_capture(saved)
    assert again.lineage_source == "capture_meta.json"
    assert (again.by_source[DOOR]["params"]["offset_mm"]) == 3300.0
