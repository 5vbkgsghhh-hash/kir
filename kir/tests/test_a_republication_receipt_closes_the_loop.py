"""The receipt closes the loop: the SECOND republication asks Revit for nothing.

Measured live on 13.09.2026: three publications of one program gave walls
4→8→12, floors 1→2→3, **+25 instances per repeat**
(`/root/kir-live-20260909/live-20260913-slice-opening-receipt.json`). The reason
was not the emitter — it was that nothing carried the RESULT back, so every
republication started from nothing and planned everything as `create`.

The round trip pinned here is offline and complete:
план₁ → программа₁ → квитанция₁ → ledger → план₂.
"""
import pytest

from kir.project_republish import RepublishError, plan_republish, previous_from_store
from kir.project_republish_program import republish_program
from kir.project_republish_receipt import (RepublishReceiptError, receipt_as_previous,
                                           import_edges, republish_receipt, retained_payload)

LEVEL, WALL_TYPE, FLOOR = "1" * 64, "3" * 64, "8" * 64
WALLS = [str(index) * 64 for index in (4, 5, 6, 7)]


def section(*, height_mm=3000, type_width_mm=230, walls=4, type_name="секция"):
    corners = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0], [0.0, 6000.0]]
    ops = [{"op": "create_level", "id": LEVEL, "elev_mm": 0, "name": "Уровень 1"},
           {"op": "create_wall_type", "id": WALL_TYPE, "host_kind": "wall",
            "new_name": type_name, "source_type": {"by": "name", "value": "Типовой"},
            "layers": [{"width_mm": type_width_mm, "function": "Structure",
                       "material": "Бетон"}]}]
    for index in range(walls):
        ops.append({"op": "create_wall", "id": WALLS[index], "p0_mm": corners[index],
                    "p1_mm": corners[(index + 1) % 4], "height_mm": height_mm,
                    "level": {"by": "ref", "value": LEVEL},
                    "type": {"by": "ref", "value": WALL_TYPE}})
    ops.append({"op": "create_floor_by_contour", "id": FLOOR,
                "level": {"by": "ref", "value": LEVEL},
                "contour": {"outer": {"shape": "poly", "points_mm": corners}}})
    return {"ir_version": "1.0", "intent": "секция", "lineage": "sec", "ops": ops}


def first_ledger(program):
    """The very first publication, in the shape `assess_create_identities` gives."""
    return {"program": program, "identity": {
        "schema": "kir-create-identity-assessment/1", "receipt_digest": "d" * 64,
        "outputs": [{"output_id": op["id"], "source_op": op["op"], "state": "created_here",
                     "element_identity": {"schema_version": "revit-element-identity/1",
                                          "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{42980 + index:08x}",
                                          "element_id": 274500 + index,
                                          "version_guid": "7ff4b512b2994d75810762effd492f45"}}
                    for index, op in enumerate(program["ops"])]}}


def round_trip(program, previous, *, results=None):
    """One republication, end to end, offline: plan -> program -> receipt."""
    plan = plan_republish(None, program, previous)
    derived = republish_program(plan, program)
    receipt = republish_receipt(plan, derived, results or {}, published_program=program)
    return plan, derived, receipt


def test_the_second_republication_of_the_same_program_asks_revit_for_nothing():
    """THE POINT OF THE WHOLE PROGRAMME, in one number: 0 operations."""
    base = section()
    first = section(height_mm=3300)
    plan1, derived1, receipt1 = round_trip(first, first_ledger(base))
    assert plan1.counts()["update"] == 4 and len(derived1.program["ops"]) == 4

    plan2, derived2, _ = round_trip(first, receipt_as_previous(receipt1))
    assert plan2.counts() == {"keep": 7, "update": 0, "replace": 0,
                              "delete": 0, "create": 0}
    assert derived2.program["ops"] == [], "повтор без изменений просит у Ревита НОЛЬ операций"
    assert plan2.creates_over_known_identity() == ()


def test_the_second_round_compares_against_what_was_published_not_the_original():
    """The ledger carries VALUES, so `expected_current` is the published one."""
    base = section()
    first = section(height_mm=3300)
    _, _, receipt1 = round_trip(first, first_ledger(base))

    _, derived, _ = round_trip(section(height_mm=3600), receipt_as_previous(receipt1))
    ops = derived.program["ops"]
    assert [op["op"] for op in ops] == ["set_param"] * 4
    assert {op["expected_current"]["value"] for op in ops} == {3300}, (
        "второй круг обязан сверяться с ОПУБЛИКОВАННЫМ значением, а не с первым")
    assert {op["value"]["value"] for op in ops} == {3600}


def test_a_deleted_output_leaves_the_ledger_and_is_not_deleted_twice():
    base = section()
    first = section(height_mm=3300)
    _, _, receipt1 = round_trip(first, first_ledger(base))
    assert len(receipt1.outputs) == 7

    smaller = section(height_mm=3300, walls=3)
    plan, _, receipt2 = round_trip(smaller, receipt_as_previous(receipt1))
    assert plan.counts()["delete"] == 1
    assert len(receipt2.outputs) == 6, "удалённый выход обязан УЙТИ из ledger'а"

    plan3, derived3, _ = round_trip(smaller, receipt_as_previous(receipt2))
    assert plan3.counts() == {"keep": 6, "update": 0, "replace": 0,
                              "delete": 0, "create": 0}
    assert derived3.program["ops"] == []


def test_a_replacement_writes_its_new_identity_and_the_link_to_the_old_one():
    # A type with NO users: with users the replacement needs two programs
    # (`replace_of_a_type_needs_two_programs`), which is its own pin.
    base = section(walls=0)
    new_uid = "7ff4b512-b299-4d75-8107-62effd492f45-0004a000"
    plan, derived, receipt = round_trip(
        section(walls=0, type_width_mm=300, type_name="секция 300"), first_ledger(base),
        results={WALL_TYPE: {"identity": {"unique_id": new_uid, "element_id": 275000,
                                          "version_guid": "7ff4b512b2994d75810762effd492f45"}}})
    assert plan.counts()["replace"] == 1
    row = next(row for row in receipt.outputs if row["output_id"] == WALL_TYPE)
    assert row["element_identity"]["unique_id"] == new_uid
    old_uid = next(row["element_identity"]["unique_id"]
                   for row in first_ledger(base)["identity"]["outputs"]
                   if row["output_id"] == WALL_TYPE)
    assert receipt.replacements == ({"output_id": WALL_TYPE, "old": old_uid,
                                     "new": new_uid,
                                     "reason": "replace_no_update_op"},)
    # and the next round sees the NEW identity, not the dead one
    plan2, _, _ = round_trip(section(walls=0, type_width_mm=300, type_name="секция 300"),
                             receipt_as_previous(receipt))
    kept = next(r for r in plan2.to_dict()["rows"] if r["output_id"] == WALL_TYPE)
    assert kept["action"] == "keep" and kept["identity_before"]["unique_id"] == new_uid


def test_control_a_lost_identity_is_refused_by_name_and_never_becomes_a_create():
    """🔴 THE DANGEROUS CASE. A silently missing identity would let the NEXT plan
    build the element again — over a live one."""
    base = section(walls=0)
    program = section(walls=0, type_width_mm=300, type_name="секция 300")
    plan = plan_republish(None, program, first_ledger(base))
    derived = republish_program(plan, program)
    with pytest.raises(RepublishReceiptError) as caught:
        republish_receipt(plan, derived, {}, published_program=program)
    assert caught.value.code == "identity_after_missing"
    assert "СЛЕДУЮЩИЙ ХОД" in str(caught.value)


def test_control_a_row_the_emitter_reported_failed_is_not_written_at_all():
    base = section()
    program = section(height_mm=3300)
    plan = plan_republish(None, program, first_ledger(base))
    derived = republish_program(plan, program)
    with pytest.raises(RepublishReceiptError) as caught:
        republish_receipt(plan, derived, {WALLS[0]: {"ok": False}},
                          published_program=program)
    assert caught.value.code == "row_reported_failed"


def test_control_the_authored_program_is_required_not_the_derived_delta():
    """The derived program is a DELTA — four `set_param`s carry no wall."""
    base = section()
    program = section(height_mm=3300)
    plan = plan_republish(None, program, first_ledger(base))
    derived = republish_program(plan, program)
    with pytest.raises(RepublishReceiptError) as caught:
        republish_receipt(plan, derived, {}, published_program=derived.program)
    assert caught.value.code == "authored_program_does_not_cover_the_receipt"


# ── the store route: a REAL store, opened from disk ───────────────────────
#
# 🔴 THE FAKE STORE THAT USED TO STAND HERE WAS THE WORST KIND OF GREEN.
# It answered whatever this file wanted, and section N measured on a real SQLite
# что no product writer ever puts an `identity_assessment` blob into a stored
# receipt row — those rows are closed to five fields by
# `create_publication.validate_create_receipt_claims`. So the reader passed here
# and refused there. The fake is gone; the publication below goes through the
# product path (reserve → native receipt → bind → record), and the store is
# CLOSED AND REOPENED FROM DISK before it is read.


def _published(tmp_path):
    """One full publication through the product path; the handle is dropped.

    The builders are section N's (`test_a_receipt_becomes_a_record_the_store_can_hold`):
    one publication path, not a second one written here to suit this file.
    """
    import kir.tests.test_a_receipt_becomes_a_record_the_store_can_hold as record_pin

    return record_pin.published(tmp_path), record_pin


def test_the_ledger_is_read_back_from_a_real_store_on_disk(tmp_path):
    from kir.project_store import ProjectStore

    digest, _ = _published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")

    previous = previous_from_store(store, digest)
    assert previous["identity"]["schema"] == "kir-create-identity-assessment/1"
    assert "program" in previous, "значения обязаны ехать вместе с личностями"

    program = previous["program"]
    plan = plan_republish(store, program, digest)
    assert plan.counts()["create"] == 0
    assert plan.creates_over_known_identity() == ()
    assert republish_program(plan, program).program["ops"] == [], "повтор — НОЛЬ операций"


def test_a_receipt_built_here_still_reads_back_through_the_same_reader(tmp_path):
    """The module's own receipt shape stays readable — by the same entry point."""
    digest, record_pin = _published(tmp_path)
    from kir.project_store import ProjectStore
    from kir.republish_archive import previous_from_stored_publication

    store = ProjectStore.open(tmp_path / "project.sqlite")
    stored = previous_from_stored_publication(store, digest)
    plan = plan_republish(None, stored["program"], stored)
    derived = republish_program(plan, stored["program"])
    receipt = republish_receipt(plan, derived, {}, published_program=stored["program"])

    # and the receipt this module writes is accepted by the planner unchanged
    again = plan_republish(None, stored["program"], receipt_as_previous(receipt))
    assert again.counts()["create"] == 0
    assert sum(again.counts().values()) == len(again.rows)


def test_control_a_publication_with_no_receipt_refuses_through_this_reader_too(tmp_path):
    """The refusal N measured stays a refusal — it just has the right name now."""
    from kir.project_store import ProjectStore

    digest, _ = _published(tmp_path)
    store = ProjectStore.open(tmp_path / "project.sqlite")
    with pytest.raises(RepublishError) as caught:
        previous_from_store(store, "f" * 64)
    assert caught.value.code == "previous_publication_unreadable"


def test_the_import_edges_are_the_existing_tables_row_shape():
    base = section()
    program = section(height_mm=3300)
    _, _, receipt = round_trip(program, first_ledger(base))
    edges = import_edges(receipt, archive_digest="a" * 64,
                         original_archive_digest="b" * 64,
                         original_receipt_digest="c" * 64)
    assert len(edges) == len(receipt.outputs)
    assert all(len(edge) == 4 for edge in edges), "create_imports — четыре колонки"
    assert {edge[0] for edge in edges} == {"a" * 64}
    with pytest.raises(RepublishReceiptError):
        import_edges(receipt, archive_digest="короткий",
                     original_archive_digest="b" * 64, original_receipt_digest="c" * 64)
