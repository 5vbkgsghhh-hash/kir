"""A building is a BATCH, and its links meet through receipts — as product.

🔴 THE MEASURED SENTENCE THIS CLOSES. `create_stairs` owns its own transactions,
so it is the ONLY op of its program (`spec.SOLO_OPS`, KIR-L002): the levels it
stands on are built by a NEIGHBOURING program. And a level addressed BY NAME does
not ground offline (`KIR-G103` «программа требует снапшот модели»), so the
neighbour's `element_id` is the only address that works — and it does not exist
until that neighbour has run. Measured 13.09.2026 in the production matrix (P05)
and again in the team rehearsal, where a HUMAN typed the ids out of `facts.json`.

Here the batch does it itself: link → receipt → the next link's addresses.

Revit is not launched: the executor is the offline fake port, and every row
carries `native_execution: "not_run"`.
"""
import pytest

from kir.project_pack import (OfflineExecutor, Pack, PackError, PackLink,
                              pack_as_previous, pack_previous_from_store, pack_ref,
                              resolve_link, run_pack)

LEVEL_1, LEVEL_2, WALL_TYPE = "1" * 64, "2" * 64, "3" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]
STAIRS = "9" * 64


def levels_link():
    return {"ir_version": "1.0", "intent": "звено 1: уровни", "ops": [
        {"op": "create_level", "id": LEVEL_1, "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_level", "id": LEVEL_2, "elev_mm": 3000, "name": "Этаж 2"}]}


def shell_link(*, height_mm=3000.0):
    corners = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0], [0.0, 6000.0]]
    ops = [{"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
            "new_name": "секция", "source_type": {"by": "element_id", "value": 274477},
            "layers": [{"width_mm": 230.0, "function": "Structure", "material": "Бетон"}]}]
    for index in range(4):
        ops.append({"op": "create_wall", "id": WALLS[index], "p0_mm": corners[index],
                    "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                    # 🔴 THE LEVEL IS NOT KNOWN YET — it is a link, not an id.
                    "level": pack_ref("levels", LEVEL_1),
                    "type": {"by": "ref", "value": WALL_TYPE}})
    return {"ir_version": "1.0", "intent": "звено 2: оболочка", "ops": ops}


def stairs_link():
    return {"ir_version": "1.0", "intent": "звено 3: лестница", "ops": [
        {"op": "create_stairs", "id": STAIRS,
         "base_level": pack_ref("levels", LEVEL_1),
         "top_level": pack_ref("levels", LEVEL_2),
         "p0_mm": [2000.0, 2000.0], "p1_mm": [4000.0, 5000.0], "width_mm": 1200.0}]}


def three_links(*, height_mm=3000.0):
    return Pack([PackLink("levels", levels_link()),
                 PackLink("shell", shell_link(height_mm=height_mm), needs=("levels",)),
                 PackLink("stairs", stairs_link(), needs=("levels",))])


def test_a_three_link_batch_goes_through_whole_offline():
    run = run_pack(three_links(), executor=OfflineExecutor())
    rows = {row["link"]: row for row in run.rows}

    assert [row["link"] for row in run.rows] == ["levels", "shell", "stairs"]
    assert all(row["compile"]["ok"] for row in run.rows), rows
    assert rows["levels"]["ops"] == 2 and rows["levels"]["resolved_refs"] == []
    # the shell's four walls each learned their level from the receipt
    assert rows["shell"]["ops"] == 5 and len(rows["shell"]["resolved_refs"]) == 4
    # and the SOLO op stands alone in its own link, on two resolved levels
    assert rows["stairs"]["ops"] == 1 and len(rows["stairs"]["resolved_refs"]) == 2
    assert run.operations() == 8
    assert run.to_dict()["claims"]["native_execution"] == "not_run"


def test_a_resolved_reference_takes_the_form_its_slot_accepts():
    """A catalogue selector gets `element_id`; it does not know `unique_id`."""
    run = run_pack(three_links(), executor=OfflineExecutor())
    program, used = resolve_link(
        PackLink("stairs", stairs_link(), needs=("levels",)), run.receipts)
    stairs = program["ops"][0]
    for slot in ("base_level", "top_level"):
        assert stairs[slot]["by"] == "element_id", "слот `sel` про unique_id не знает"
        assert isinstance(stairs[slot]["value"], int)
    assert {row["slot"].split(".")[-1] for row in used} == {"base_level", "top_level"}


def test_a_repeat_of_the_same_batch_asks_revit_for_nothing_in_every_link():
    """THE NUMBER: 0 operations, link by link, not just in total."""
    pack = three_links()
    first = run_pack(pack, executor=OfflineExecutor())
    assert first.operations() == 8

    again = run_pack(pack, executor=OfflineExecutor(), previous=pack_as_previous(first))
    assert again.operations() == 0
    for row in again.rows:
        assert row["ops"] == 0, row["link"]
        assert row["republish"]["creates_over_known"] == 0, row["link"]
        assert row["republish"]["counts"]["create"] == 0, row["link"]
        assert row["compile"]["sent"] is False, "пустую программу не отправляют"


def test_a_changed_link_moves_only_that_link():
    pack = three_links()
    first = run_pack(pack, executor=OfflineExecutor())
    changed = run_pack(three_links(height_mm=3300.0), executor=OfflineExecutor(),
                       previous=pack_as_previous(first))
    rows = {row["link"]: row for row in changed.rows}
    assert rows["levels"]["ops"] == 0 and rows["stairs"]["ops"] == 0
    assert rows["shell"]["ops"] == 4, "изменилась высота четырёх стен — и только"
    assert rows["shell"]["republish"]["counts"]["update"] == 4
    assert rows["shell"]["republish"]["counts"]["create"] == 0


# ── controls ───────────────────────────────────────────────────────────────
def test_control_a_link_that_reads_an_unexecuted_link_refuses_by_name():
    """🔴 NOT a silent `element_id = 0`: that compiles, ships and hits the model."""
    with pytest.raises(PackError) as caught:
        resolve_link(PackLink("stairs", stairs_link(), needs=("levels",)), receipts={})
    assert caught.value.code == "pack_link_not_executed"
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)
    assert "квитанц" in str(caught.value)


def test_control_a_lost_receipt_is_a_refusal_not_a_create():
    """A receipt that went missing must stop the batch, not restart the building."""
    run = run_pack(three_links(), executor=OfflineExecutor())
    lost = {key: value for key, value in pack_as_previous(run).items() if key != "levels"}
    with pytest.raises(PackError) as caught:
        run_pack(three_links(), executor=OfflineExecutor(), previous=lost)
    # 🔴 THE SILENT READING WOULD BE «этого звена ещё не было» — and the batch
    # would build its levels AGAIN, over the ones already standing.
    assert caught.value.code == "pack_receipt_lost"
    assert "levels" in str(caught.value)
    assert "построить то, что уже стоит" in str(caught.value)
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)


def test_control_an_output_absent_from_the_receipt_is_named():
    run = run_pack(three_links(), executor=OfflineExecutor())
    program = {"ir_version": "1.0", "intent": "чужой адрес", "ops": [
        {"op": "create_stairs", "id": STAIRS, "base_level": pack_ref("levels", "0" * 64),
         "top_level": pack_ref("levels", LEVEL_2), "p0_mm": [0.0, 0.0],
         "p1_mm": [3000.0, 3000.0], "width_mm": 1200.0}]}
    with pytest.raises(PackError) as caught:
        resolve_link(PackLink("stairs", program, needs=("levels",)), run.receipts)
    assert caught.value.code == "pack_output_not_in_receipt"
    assert "догадываться об id нельзя" in str(caught.value)


def test_control_a_link_that_needs_a_later_link_is_refused_when_the_pack_is_built():
    with pytest.raises(PackError) as caught:
        Pack([PackLink("stairs", stairs_link(), needs=("levels",)),
              PackLink("levels", levels_link())])
    assert caught.value.code == "pack_link_needs_a_later_link"
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)


def test_control_a_link_that_does_not_compile_stops_the_batch():
    """Half a building is worse than none: the batch stops at the bad link."""
    broken = {"ir_version": "1.0", "intent": "битое звено", "ops": [
        {"op": "create_wall", "id": WALLS[0], "p0_mm": [0.0, 0.0], "p1_mm": [6000.0, 0.0],
         "height_mm": 3000.0, "level": pack_ref("levels", LEVEL_1),
         "type": {"by": "name", "value": "тип, которого офлайн не заземлить"}}]}
    pack = Pack([PackLink("levels", levels_link()),
                 PackLink("bad", broken, needs=("levels",)),
                 PackLink("stairs", stairs_link(), needs=("levels",))])
    with pytest.raises(PackError) as caught:
        run_pack(pack, executor=OfflineExecutor())
    assert caught.value.code == "pack_link_did_not_compile"
    assert "наполовину построенной" in str(caught.value)


# ── the repeat through a REAL store, not through the run's memory ──────────

def test_a_repeat_reads_its_receipts_out_of_a_real_store(tmp_path):
    """🔴 THE RUN'S MEMORY IS NOT A LEDGER. A batch whose process died must be
    able to come back — and the only thing that survives it is the store.

    Section N measured on a real SQLite that a stored receipt row holds no
    identity blob (those rows are closed to five fields); the identities are
    DERIVED by the product's own path. Here the batch reads them that way.
    """
    import kir.tests.test_a_receipt_becomes_a_record_the_store_can_hold as record_pin
    from kir.project_store import ProjectStore

    digest = record_pin.published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")

    previous = pack_previous_from_store(store, {"section": digest})
    assert set(previous) == {"section"}
    assert previous["section"]["schema"] == "kir-create-identity-assessment/1"
    assert previous["section"]["program_as_published"]["ops"], "значения приехали с личностями"

    # the same program, replanned against what the STORE says: nothing to do
    program = previous["section"]["program_as_published"]
    pack = Pack([PackLink("section", program)])
    again = run_pack(pack, executor=OfflineExecutor(), previous=previous)
    assert again.operations() == 0
    row, = again.rows
    assert row["republish"]["counts"]["create"] == 0
    assert row["republish"]["creates_over_known"] == 0
    assert row["compile"]["sent"] is False


def test_control_an_unknown_publication_is_named_not_rebuilt(tmp_path):
    """A digest the store does not know must refuse — not read as «не было»."""
    import kir.tests.test_a_receipt_becomes_a_record_the_store_can_hold as record_pin
    from kir.project_store import ProjectStore

    record_pin.published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    with pytest.raises(PackError) as caught:
        pack_previous_from_store(store, {"section": "f" * 64})
    assert caught.value.code == "pack_publication_unknown_to_the_store"
    assert "section" in str(caught.value)
    assert "дубль поверх уже стоящего" in str(caught.value)


def test_the_lost_receipt_refusal_names_the_working_reader():
    """The next move must be a door that EXISTS: the old one was a dead end."""
    pack = three_links()
    first = run_pack(pack, executor=OfflineExecutor())
    lost = {key: value for key, value in pack_as_previous(first).items() if key != "levels"}
    with pytest.raises(PackError) as caught:
        run_pack(pack, executor=OfflineExecutor(), previous=lost)
    text = str(caught.value)
    assert caught.value.code == "pack_receipt_lost"
    assert "previous_from_stored_publication" in text, (
        "ход обязан вести в рабочий путь, а не в читателя, который отказывал "
        "на настоящем store")
    assert "previous_from_store(" not in text
