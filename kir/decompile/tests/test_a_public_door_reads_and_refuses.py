# -*- coding: utf-8 -*-
"""THE PUBLIC DOOR: reads from the ledger, refuses by name, writes nothing
during preview.

Five properties from the mandate (part 5), each its own measurement:

1. a second patch on the same element PRESERVES the first;
2. edits to two independent elements do not erase one another;
3. a stale `before` is refused BY NAME (a code, not a nameless exception);
4. a foreign source binding (a DIFFERENT capture's binding) is refused by
   name;
5. `propose_patch` writes NOTHING — checked BYTE-FOR-BYTE: the sha256 of
   every file in the capture directory before and after.

The building here is synthetic (`capture_api.write_demo_capture`) ON
PURPOSE: the measurement is about the contract of the door and the
opening, not about the corpus, and it must run on a machine where no
decompile corpus exists. No corpus numbers are derived from it. The check
on the real `bench_A` stands below and is skipped where no corpus exists.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kir.decompile import capture_api as API
from kir.decompile import capture_edit as CE
from kir.model.snapshot_io import snapshot_file_exists

CORPUS = Path("/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A")
CORPUS_DOOR = "286533"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """A synthetic capture. The directory is NEVER rewritten by the tests
    below."""
    return API.write_demo_capture(tmp_path_factory.mktemp("api") / "capture")


def _tree_digest(directory: Path) -> dict:
    """The sha256 of EVERY file in the directory. The snapshot against
    which "wrote nothing" is judged."""
    out = {}
    for item in sorted(Path(directory).rglob("*")):
        if item.is_file():
            out[str(item.relative_to(directory))] = hashlib.sha256(
                item.read_bytes()).hexdigest()
    return out


def test_read_element_names_the_host_the_dependants_and_the_state_of_every_field(demo):
    """Reading an element means its HOST, its DEPENDENCIES, and the STATE
    of every field."""
    capture = CE.open_capture(demo)
    door = API.read_element(capture, API.DEMO_DOOR)
    assert door.category == "OST_Doors" and door.op_name == "create_door"
    assert door.host is not None and door.host.element_id == API.DEMO_WALL
    assert door.host.relation == "hosted_by" and door.host.via == "L0.host_id"
    assert door.host.category == "OST_Walls"
    assert API.DEMO_WALL in {link.element_id for link in door.depends_on}
    assert door.editable_fields == CE._DOOR_FIELDS
    assert door.op_params["offset_mm"] == pytest.approx(3000.0)

    # The flip side of the same relationship: for the wall, both doors are
    # dependents, and the relationship is proven by TWO different bearers
    # (the node reference and the L0 row's `host_id`).
    wall = API.read_element(capture, API.DEMO_WALL)
    dependants = {link.element_id for link in wall.referenced_by}
    assert {API.DEMO_DOOR, API.DEMO_DOOR_2} <= dependants
    assert {link.relation for link in wall.referenced_by} == {"referenced_by", "hosts"}
    assert wall.host is None, "у стены хозяина нет — выдумывать его нельзя"

    # 🔴 A FIELD'S STATE COMES FROM THE LEDGER, NOT FROM ITS OWN FORMULA.
    # It is checked against a ledger built over the ENTIRE capture: a
    # slice on a single element has no right to change the verdict on a
    # field, or "state per the ledger" would be untrue.
    from kir.decompile.field_ledger import field_ledger

    whole = field_ledger(capture.document, capture.nodes)
    row = next(item for item in whole.rows if item.element_id == API.DEMO_DOOR)
    expected = {name: "represented" for name in row.kept}
    expected.update({item.field: item.state for item in row.lost})
    assert {item.field: item.state for item in door.fields} == expected
    assert set(door.supported) == set(row.kept)
    assert {item.state for item in door.fields} <= {
        "represented", "approximate", "source_data", "unknown"}
    assert door.field_states_from == "kir.decompile.field_ledger"


def test_a_second_patch_on_the_same_element_keeps_the_first(demo, tmp_path):
    """🔴 A SECOND ASSIGNMENT HAS NO RIGHT TO CANCEL THE FIRST, AND THIS IS
    CHECKED AFTER REOPENING."""
    capture = CE.open_capture(demo)
    first = API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0})
    assert first.refusal is None and first.diff
    second = API.apply_patch(capture, API.DEMO_DOOR, {"sill_mm": 150.0})
    assert second.refusal is None
    params = capture.by_source[API.DEMO_DOOR]["params"]
    assert params["offset_mm"] == pytest.approx(4000.0), "первая правка потеряна"
    assert params["sill_mm"] == pytest.approx(150.0)
    assert second.edits == 2

    saved = CE.save(capture, tmp_path / "twice")
    reopened = CE.open_capture(saved)
    again = reopened.by_source[API.DEMO_DOOR]["params"]
    assert again["offset_mm"] == pytest.approx(4000.0)
    assert again["sill_mm"] == pytest.approx(150.0)
    assert len(reopened.edits) == 2


def test_two_independent_elements_do_not_erase_each_other(demo, tmp_path):
    """An edit to the door and an edit to the opening are different nodes;
    both must survive."""
    capture = CE.open_capture(demo)
    ring = [[2500.0, 2500.0], [5500.0, 2500.0], [5500.0, 5500.0], [2500.0, 5500.0]]
    assert API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0}).refusal is None
    opening = API.apply_patch(capture, API.DEMO_FLOOR,
                              {"opening_index": 0, "opening_contour_mm": ring})
    assert opening.refusal is None, opening.refusal
    assert API.apply_patch(capture, API.DEMO_DOOR_2, {"offset_mm": 8000.0}).refusal is None

    saved = CE.save(capture, tmp_path / "three")
    reopened = CE.open_capture(saved)
    assert reopened.by_source[API.DEMO_DOOR]["params"]["offset_mm"] == pytest.approx(4000.0)
    assert reopened.by_source[API.DEMO_DOOR_2]["params"]["offset_mm"] == pytest.approx(8000.0)
    holes, _ = CE._holes_of(reopened.by_source[API.DEMO_FLOOR])
    assert CE._points_of(holes[0]) == ring
    assert len(reopened.edits) == 3


def test_a_stale_before_value_is_refused_by_name_and_changes_nothing(demo):
    """A stale `before` is a refusal CODE, not a nameless exception and not
    a silent write."""
    capture = CE.open_capture(demo)
    assert API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0}).refusal is None
    stale = API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4500.0},
                            before={"offset_mm": 3000.0})
    assert stale.refusal is not None, "устаревший before принят молча"
    assert stale.refusal["code"] == "edit_before_value_mismatch"
    assert stale.refusal["address"] == API.DEMO_DOOR
    assert stale.changed_ops == () and stale.diff == ()
    assert capture.by_source[API.DEMO_DOOR]["params"]["offset_mm"] == pytest.approx(4000.0)
    assert len(capture.edits) == 1, "отказ не вправе оставлять строку в журнале"
    # A fresh `before` does NOT refuse under the same code: a gate that is
    # always red is guarding silence.
    fresh = API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4500.0},
                            before={"offset_mm": 4000.0})
    assert fresh.refusal is None, fresh.refusal


def test_a_binding_from_another_capture_is_refused_by_name(demo, tmp_path):
    """🔴 THE ADDRESSES OF TWO BUILDINGS COINCIDE BY CONSTRUCTION — the
    binding is taken from the source."""
    other = API.write_demo_capture(tmp_path / "other")
    # The second building differs by ONE side-band line: `source_sha256`
    # is the same, but `source_version` is not. Exactly the case that is
    # only caught by binding to the ENTIRE source.
    payload = json.loads((other / "sketch.index.json").read_text(encoding="utf-8"))
    payload["profile_index"][API.DEMO_FLOOR]["holes"] = [
        [[3000.0, 3000.0], [6000.0, 3000.0], [6000.0, 6000.0], [3000.0, 6000.0]]]
    (other / "sketch.index.json").write_text(json.dumps(payload, ensure_ascii=False),
                                             encoding="utf-8")

    capture = CE.open_capture(demo)
    foreign = API.source_binding(CE.open_capture(other))
    assert foreign["source_sha256"] == API.source_binding(capture)["source_sha256"], \
        "снимки разошлись — замер перестал быть о ПРИВЯЗКЕ ко всему исходнику"

    refused = API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0},
                              source_binding=foreign)
    assert refused.refusal is not None, "чужая привязка принята молча"
    assert refused.refusal["code"] == "patch_binds_to_another_capture"
    assert "source_version" in refused.refusal["detail"]
    assert capture.by_source[API.DEMO_DOOR]["params"]["offset_mm"] == pytest.approx(3000.0)
    assert capture.edits == []
    # Its own binding passes through: otherwise the guard would be
    # forbidding something legitimate.
    assert API.apply_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0},
                           source_binding=API.source_binding(capture)).refusal is None
    # And the preview refuses under the SAME code, not "allowed."
    preview = API.propose_patch(CE.open_capture(demo), API.DEMO_DOOR,
                                {"offset_mm": 4000.0}, source_binding=foreign)
    assert preview.admissible is False
    assert preview.refusal["code"] == "patch_binds_to_another_capture"


def test_a_preview_writes_nothing_byte_for_byte(demo):
    """🔴 "PREVIEW THE CONSEQUENCES" WRITES NEITHER TO MEMORY NOR TO
    DISK."""
    capture = CE.open_capture(demo)
    before_tree = _tree_digest(demo)
    before_node = json.dumps(capture.by_source[API.DEMO_DOOR], sort_keys=True, default=str)

    good = API.propose_patch(capture, API.DEMO_DOOR, {"offset_mm": 4000.0})
    assert good.admissible is True and good.wrote_nothing is True
    assert [row["path"] for row in good.diff] == ["params.offset_mm"]
    assert good.diff[0]["before"] == pytest.approx(3000.0)
    assert good.diff[0]["after"] == pytest.approx(4000.0)
    assert good.before == {"offset_mm": 3000.0}
    assert good.open_questions, "нерешённые вопросы обязаны быть названы"

    bad = API.propose_patch(capture, API.DEMO_DOOR, {"offset_mm": 1e9})
    assert bad.admissible is False and bad.refusal["code"] == "offset_out_of_host"
    assert bad.diff == ()
    ring = [[2500.0, 2500.0], [5500.0, 2500.0], [5500.0, 5500.0], [2500.0, 5500.0]]
    assert API.propose_patch(capture, API.DEMO_FLOOR,
                             {"opening_index": 0, "opening_contour_mm": ring}).admissible

    assert json.dumps(capture.by_source[API.DEMO_DOOR], sort_keys=True,
                      default=str) == before_node, "предпросмотр тронул узел в памяти"
    assert capture.edits == [], "предпросмотр записал строку в журнал правок"
    assert _tree_digest(demo) == before_tree, "предпросмотр тронул каталог capture"


def test_an_unknown_element_is_named_and_not_answered_with_emptiness(demo):
    capture = CE.open_capture(demo)
    with pytest.raises(CE.CaptureEditError) as caught:
        API.read_element(capture, "0")
    assert caught.value.code == "unknown_element"
    assert API.propose_patch(capture, "0", {"offset_mm": 1.0}
                             ).refusal["code"] == "unknown_element"


@pytest.mark.skipif(not snapshot_file_exists(CORPUS / "L0.jsonl"),
                    reason="корпус bench_A недоступен на этой машине")
def test_the_public_door_reads_a_real_building_the_same_way(tmp_path):
    """The same contract on a REAL building: synthetic data does not stand
    in for the corpus."""
    import shutil

    work = tmp_path / "bench_A"
    work.mkdir()
    for item in CORPUS.iterdir():
        if item.is_file():
            shutil.copy2(item, work / item.name)
    capture = CE.open_capture(work)
    door = API.read_element(capture, CORPUS_DOOR)
    assert door.category == "OST_Doors" and door.op_name == "create_door"
    assert door.host is not None and door.host.category == "OST_Walls"
    assert door.host.element_id == "286530"
    assert any(item.state == "unknown" for item in door.fields)
    assert any(item.state == "represented" for item in door.fields)
    assert API.propose_patch(capture, CORPUS_DOOR, {"offset_mm": 3300.0}).admissible
    assert capture.edits == [], "предпросмотр на корпусе тоже ничего не пишет"
