"""The unit OWNING the transaction, and its C# against real RevitAPI
2023/2026.

Live Revit was never launched here, not once. Everything checked is: the
plan, the refusals, serialization, the absence of a repeated effect, and the
COMPILATION of the emitted C# against real reference assemblies. This is not
a successful live execution.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from kir.emit_transaction_unit import (
    IDENTITY_REPLACEMENT_POLICIES, IMPLEMENTED_IDENTITY_REPLACEMENT, SECTIONS,
    SKETCH_OWNER, UNIT_OWNER,
    PreparedTransactionUnit, TransactionUnitPlan, TransactionUnitRefusal,
    emit_transaction_unit_cs, load_transaction_unit_plan, plan_floor_sketch_opening,
    plan_wall_type_layer_width, prepare_transaction_unit, reserve_transaction_unit,
    settle_transaction_unit,
)
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.revit_observation import parse_element_observation, prepare_element_observation
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_type_creation_conformance import type_conformance_runner
from kir.type_definition_observation import (parse_type_definition_observation,
                                             prepare_type_definition_observation)


ROOT = Path(__file__).resolve().parents[2]
WALL_UID, FLOOR_UID = "wall-type-uid", "floor-uid"
NO_CHANGES = {"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False}


def identity(element_id, unique_id):
    return {"schema_version": "revit-element-identity/1", "element_id": element_id,
            "unique_id": unique_id, "version_guid": "b" * 32}


def base_row(uid, element_id, name, schema):
    return {"schema_version": schema, "requested_unique_id": uid, "status": "observed",
            "reason": None, "name": name, "category_id": -2000011, "is_level": False,
            "type_state": {"status": "none", "element_identity": None,
                           "element_identity_status": "unavailable",
                           "element_identity_reason": "element_missing"},
            "level_status": "not_level", "level_reason": None, "level": None,
            "element_identity": identity(element_id, uid),
            "element_identity_status": "captured", "element_identity_reason": None}


def type_row(uid, element_id, name, layers):
    row = base_row(uid, element_id, name, "kir-element-state/2")
    row["type_definition"] = {"status": "observed", "reason": None, "value": {
        "host_kind": "wall", "wall_kind": "Basic", "is_vertically_compound": False,
        "is_vertically_homogeneous": True, "name": name,
        "total_width_mm": float(sum(layer["width_mm"] for layer in layers)),
        "layers": [{"width_mm": float(layer["width_mm"]), "function": layer["function"],
                    "material_id": -1, "material_name": None, "material_identity": None,
                    "material_name_match_count": None} for layer in layers]}}
    return row


def type_users(count=3):
    return {"query_source_sha256": "c" * 64, "complete": True,
            "unique_ids": [f"user-{index}" for index in range(count)]}


@pytest.fixture
def bound(request):
    version = getattr(request, "param", "2026")
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    return target, SessionCredentials(target, str(uuid4()), "test-only"), ContextPrecondition("native-doc", 21)


def type_observation(bound, layers=((200.0, "Structure"), (20.0, "Finish1")), revision=None):
    target, auth, precondition = bound
    if revision is not None:
        precondition = ContextPrecondition(precondition.document_key, revision)
    query = prepare_type_definition_observation([WALL_UID], target=target,
        precondition=precondition, operation_id=str(uuid4()))
    rows = {"wall-uid-0" if False else query.planned.to_ops()[0]["id"]:
            type_row(WALL_UID, 501, "Наружная 220",
                     [{"width_mm": width, "function": function} for width, function in layers])}
    response = response_for(query, auth, rows, changes=NO_CHANGES)
    return parse_type_definition_observation(query, json.dumps(response), credentials=auth,
                                             request_id=response["request_id"])


def element_observation(bound, uid=FLOOR_UID):
    target, auth, precondition = bound
    query = prepare_element_observation([uid], target=target, precondition=precondition,
                                        operation_id=str(uuid4()))
    rows = {query.planned.to_ops()[0]["id"]: base_row(uid, 777, "Перекрытие 200", "kir-element-state/1")}
    response = response_for(query, auth, rows, changes=NO_CHANGES)
    return parse_element_observation(query, json.dumps(response), credentials=auth,
                                     request_id=response["request_id"])


def wall_plan(bound, **kwargs):
    target, _auth, precondition = bound
    fields = {"unique_id": WALL_UID, "layer_index": 0, "width_mm": 260.0, "target": target,
              "precondition": precondition, "type_users": type_users(),
              "protected_unique_ids": ("neighbour-wall",)}
    fields.update(kwargs)
    observation = fields.pop("observation", None) or type_observation(bound)
    return plan_wall_type_layer_width(observation, **fields)


# ───────────────────────────── plan, diff, ownership ──


def test_plan_names_the_owner_the_diff_and_the_users_of_the_type(bound):
    plan = wall_plan(bound)
    assert plan.transaction_owner == UNIT_OWNER == SECTIONS["wall_type_layer_width"]
    assert plan.diff["changed"] == [{"index": 0, "before_mm": 200.0, "after_mm": 260.0,
                                     "function": "Structure"}]
    # Preservation of the remaining layers is A NUMBER, not a promise.
    assert plan.diff["preserved_layers"] == [{"index": 1, "width_mm": 20.0, "function": "Finish1"}]
    assert plan.ownership["type_user_count"] == 3
    assert plan.ownership["identity_replacement"] == "in_place"
    assert plan.protected_unique_ids == ("neighbour-wall",)


def test_the_unnamed_scope_of_type_users_is_a_refusal_not_an_empty_list(bound):
    for users in (None, {}, {"query_source_sha256": "c" * 64, "unique_ids": [], "complete": False}):
        with pytest.raises(TransactionUnitRefusal) as error:
            wall_plan(bound, type_users=users)
        assert error.value.code in ("type_user_scope_unknown", "type_user_scope_incomplete")


def test_the_policy_list_stays_closed_and_every_named_policy_is_real(bound):
    """Both named policies are implemented; a made-up one gets a refusal, not
    a substitution.

    Before 07.09, `duplicate_and_reassign` was NAMED and refused
    (`identity_replacement_not_implemented`) — better than a silent
    substitution, but still a hole. Now the list is closed and matches what
    is implemented.
    """
    assert IMPLEMENTED_IDENTITY_REPLACEMENT == IDENTITY_REPLACEMENT_POLICIES
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, identity_replacement="invented")
    assert error.value.code == "unknown_identity_replacement"
    # A policy without its own arguments is not "a default," it's a refusal.
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, identity_replacement="duplicate_and_reassign")
    assert error.value.code == "duplicate_name_required"


# ───────────────────────────── a foreign UID and a foreign C0 ──


def test_a_foreign_unique_id_is_refused_before_any_emission(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, unique_id="somebody-elses-uid")
    assert error.value.code == "foreign_unique_id"


def test_an_observation_from_another_c0_is_refused(bound):
    stale = type_observation(bound, revision=20)
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, observation=stale)
    assert error.value.code == "observation_c0_differs"


def test_an_observation_from_another_document_is_refused(bound):
    target, auth, precondition = bound
    other = RuntimeTarget(str(uuid4()), str(uuid4()), target.revit_version)
    observation = type_observation((other, SessionCredentials(other, str(uuid4()), "t"), precondition))
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, observation=observation)
    assert error.value.code == "observation_target_differs"


def test_a_change_inside_tolerance_is_not_a_change(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, width_mm=200.4)
    assert error.value.code == "no_change_planned"


def test_a_layer_outside_the_observed_pie_is_refused(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, layer_index=7)
    assert error.value.code == "layer_index_out_of_range"


def test_the_changed_object_cannot_also_be_declared_protected(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, protected_unique_ids=(WALL_UID,))
    assert error.value.code == "protected_scope_conflict"


# ───────────────────────────── serialization and restart ──


def test_a_saved_plan_survives_restart_and_never_becomes_fresh_evidence(bound):
    plan = wall_plan(bound)
    retained = load_transaction_unit_plan(json.loads(json.dumps(plan.to_dict())))
    assert retained.matches(plan) and retained.plan_digest == plan.digest
    # An inert record is neither emitted nor prepared: it's a separate type.
    assert type(retained) is not TransactionUnitPlan
    with pytest.raises(TransactionUnitRefusal) as error:
        emit_transaction_unit_cs(retained)
    assert error.value.code == "transaction_unit_plan_required"
    with pytest.raises(TypeError):
        TransactionUnitPlan()


def test_a_tampered_saved_plan_is_caught_by_its_own_digest(bound):
    payload = wall_plan(bound).to_dict()
    payload["diff"]["changed"][0]["after_mm"] = 999.0
    with pytest.raises(TransactionUnitRefusal) as error:
        load_transaction_unit_plan(payload)
    assert error.value.code == "retained_plan_digest_mismatch"


def test_a_saved_plan_whose_owner_was_swapped_is_refused(bound):
    payload = wall_plan(bound).to_dict()
    payload["transaction_owner"] = SKETCH_OWNER
    with pytest.raises(TransactionUnitRefusal) as error:
        load_transaction_unit_plan(payload)
    assert error.value.code in ("transaction_owner_conflict", "retained_plan_digest_mismatch")


# ───────────────────────────── absence of a repeated effect ──


def test_the_effect_is_reserved_before_dispatch_and_never_reserved_twice(bound, tmp_path):
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    ledger = str(tmp_path / "unit.json")
    first = reserve_transaction_unit(prepared, ledger_path=ledger)
    assert first["state"] == "reserved" and first["receipt"] is None
    with pytest.raises(TransactionUnitRefusal) as error:
        reserve_transaction_unit(prepared, ledger_path=ledger)
    assert error.value.code == "effect_already_reserved"


def test_an_unknown_outcome_stays_unknown_and_still_blocks_a_second_send(bound, tmp_path):
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    ledger = str(tmp_path / "unit.json")
    reserve_transaction_unit(prepared, ledger_path=ledger)
    settled = settle_transaction_unit(prepared, ledger_path=ledger, outcome="unknown",
                                      receipt={"phase": "unit_committed", "effect": "committed"})
    assert settled["state"] == "settled" and settled["outcome"] == "unknown"
    # The partial fact is preserved, not erased by "unknown."
    assert settled["receipt"]["effect"] == "committed"
    with pytest.raises(TransactionUnitRefusal) as error:
        reserve_transaction_unit(prepared, ledger_path=ledger)
    assert error.value.code == "effect_already_reserved"


def test_settling_without_a_reservation_is_refused(bound, tmp_path):
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    # The receipt is VERIFIED — otherwise the refusal would have arrived
    # earlier, for a different reason, and "no reservation" would remain
    # unchecked.
    with pytest.raises(TransactionUnitRefusal) as error:
        settle_transaction_unit(prepared, ledger_path=str(tmp_path / "absent.json"),
                                outcome="committed", receipt={"state": "committed_verified"})
    assert error.value.code == "reservation_missing"


def test_a_foreign_unit_cannot_take_over_an_existing_ledger_address(bound, tmp_path):
    ledger = str(tmp_path / "unit.json")
    reserve_transaction_unit(prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4())),
                             ledger_path=ledger)
    other = prepare_transaction_unit(wall_plan(bound, width_mm=300.0), operation_id=str(uuid4()))
    with pytest.raises(TransactionUnitRefusal) as error:
        reserve_transaction_unit(other, ledger_path=ledger)
    assert error.value.code == "ledger_operation_conflict"


# ───────────────────────────── explicit phase order and negatives in C# ──


@pytest.mark.parametrize("section", ["wall_type_layer_width", "floor_sketch_opening"])
def test_the_emitted_unit_orders_observe_unit_observe_and_owns_its_transaction(bound, section):
    if section == "wall_type_layer_width":
        plan = wall_plan(bound)
    else:
        plan = plan_floor_sketch_opening(element_observation(bound), unique_id=FLOOR_UID,
            loop_mm=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 800.0), (0.0, 800.0)],
            target=bound[0], precondition=bound[2])
    source = prepare_transaction_unit(plan, operation_id=str(uuid4())).source
    # Phase order is by position in the text, not by function name.
    order = [source.index(mark) for mark in ('"observed_before"', '"unit_committed"', '"observed_after"')]
    assert order == sorted(order), order
    # A negative BEFORE start: the emitter's active transaction forbids the unit.
    assert source.index("if (doc.IsModifiable)") < order[0]
    # There is no emitter scaffold here in any form.
    assert "Transaction __t = new Transaction(doc," not in source
    if plan.transaction_owner == SKETCH_OWNER:
        assert "new SketchEditScope(doc" in source and "__scope.IsActive" in source
    else:
        assert source.count("new Transaction(doc") == 1
        assert '"unit_transaction_still_open"' in source


def test_a_body_wrapped_by_the_emitter_frame_is_refused_by_the_owner_guard(bound, monkeypatch):
    """FAIL control: slip in the emitter scaffold — the unit must refuse."""
    import kir.emit_transaction_unit as module

    original = module.emit_transaction_unit_cs
    monkeypatch.setattr(module, "emit_transaction_unit_cs", lambda plan:
        'using (Transaction __t = new Transaction(doc, "KIR: подделка"))\n{\n'
        + original(plan) + "\n}\n")
    with pytest.raises(TransactionUnitRefusal) as error:
        prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    assert error.value.code == "transaction_owner_conflict"


def test_a_unit_without_its_no_start_negative_is_refused(bound, monkeypatch):
    """FAIL control: remove the "active transaction" negative — the preparation refusal."""
    import kir.emit_transaction_unit as module

    original = module.emit_transaction_unit_cs
    monkeypatch.setattr(module, "emit_transaction_unit_cs",
                        lambda plan: original(plan).replace("if (doc.IsModifiable)", "if (false)"))
    with pytest.raises(TransactionUnitRefusal) as error:
        prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    assert error.value.code == "no_start_negative_missing"


def test_the_prepared_unit_binds_to_its_own_target_and_source(bound):
    target, auth, _precondition = bound
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    assert type(prepared) is PreparedTransactionUnit
    request = prepared.execute_request(auth, request_id=str(uuid4()))
    assert request["source_sha256"] == prepared.source_sha256 and request["kind"] == "execute"
    other = RuntimeTarget(str(uuid4()), str(uuid4()), target.revit_version)
    with pytest.raises(TransactionUnitRefusal) as error:
        prepared.execute_request(SessionCredentials(other, str(uuid4()), "t"), request_id=str(uuid4()))
    assert error.value.code == "target_mismatch"
    with pytest.raises(TypeError):
        PreparedTransactionUnit()


# ───────────── compilation against REAL RevitAPI 2023 and 2026 ───────────
# The instrument is the same as for the tree's other strips: the real
# Connector policy and real reference assemblies. Not one emitted byte is
# executed.


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_the_unit_csharp_compiles_against_the_actual_api(version, type_conformance_runner, request):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    auth = SessionCredentials(target, str(uuid4()), "test-only")
    precondition = ContextPrecondition("native-doc", 21)
    scope = (target, auth, precondition)
    wall = wall_plan(scope)
    floor = plan_floor_sketch_opening(element_observation(scope), unique_id=FLOOR_UID,
        loop_mm=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 800.0), (0.0, 800.0)],
        target=target, precondition=precondition)
    sources = [prepare_transaction_unit(plan, operation_id=str(uuid4())).source
               for plan in (wall, floor)]
    rows = type_conformance_runner(version, sources)
    for plan, row in zip((wall, floor), rows, strict=True):
        assert row["ok"] is True, (version, plan.section, row["diagnostics"])
        assert row["assembly_bytes"] > 0, (version, plan.section, row)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_a_broken_unit_body_is_still_caught_by_the_same_compiler(version, type_conformance_runner):
    """FAIL control of the instrument: the same instrument must SEE the breakage."""
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    scope = (target, SessionCredentials(target, str(uuid4()), "t"), ContextPrecondition("native-doc", 21))
    source = prepare_transaction_unit(wall_plan(scope), operation_id=str(uuid4())).source
    broken = source.replace(".SetLayerWidth(", ".SetLayerWidthThatDoesNotExist(")
    assert broken != source
    row, = type_conformance_runner(version, [broken])
    assert row["ok"] is False and row["assembly_bytes"] == 0
    assert any("SetLayerWidthThatDoesNotExist" in item for item in row["diagnostics"]), row


# ───────────── self-review: what a green test in one process cannot see ──


def test_two_processes_with_one_plan_reserve_the_effect_exactly_once(bound, tmp_path):
    """A race between TWO PROCESSES, not two calls within one.

    Bought by a probe on 07.09: in one process the check was green, while two
    processes BOTH passed the reservation — 2 out of 2 where exactly one
    must pass. The probe lives in the tree:
    `kir/tests/probes/native_race.py` (moved out of `.work/` on 07.09.2026 —
    in the scratchpad it never reached a clean clone, and the test was
    silently skipped).
    """
    import subprocess

    probe = ROOT / "kir/tests/probes/native_race.py"
    assert probe.is_file(), f"зонд гонки отсутствует в дереве: {probe}"
    result = subprocess.run([sys.executable, str(probe)], text=True, capture_output=True,
                            timeout=300, env={**os.environ, "PYTHONPATH": str(ROOT),
                                              "PYTHONDONTWRITEBYTECODE": "1"})
    assert "ПРОШЛО РЕЗЕРВИРОВАНИЙ: 1 " in result.stdout, result.stdout + result.stderr
    assert "['effect_already_reserved']" in result.stdout, result.stdout
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("count,index", [(5, 2), (5, 0), (5, 4), (2, 1)])
def test_every_untouched_layer_and_the_whole_thickness_are_checked(bound, count, index):
    """ALL n-1 remaining layers AND THE SUM are checked, not just the target's neighbors."""
    layers = tuple((100.0 + 10 * i, "Structure" if i == 0 else "Finish1") for i in range(count))
    observation = type_observation(bound, layers=layers)
    plan = wall_plan(bound, observation=observation, layer_index=index, width_mm=999.0)
    preserved = plan.diff["preserved_layers"]
    assert [row["index"] for row in preserved] == [i for i in range(count) if i != index]
    total = sum(width for width, _ in layers)
    assert plan.diff["observed_total_width_mm"] == total
    assert plan.diff["expected_total_width_mm"] == total - layers[index][0] + 999.0
    source = prepare_transaction_unit(plan, operation_id=str(uuid4())).source
    # Each untouched layer is named twice: before the edit and after the commit.
    for row in preserved:
        assert source.count(f'__receipt["preserved_layer_index"] = {row["index"]}') == 2, row
    assert '"preserved_layer_changed_since_observation"' in source
    assert '"preserved_layer_changed_by_unit"' in source
    assert '"total_width_changed_since_observation"' in source
    # The presence of a refusal NAME does not yet mean the sum is being
    # compared: we check the comparison itself against the plan's NUMBER.
    # Otherwise a mutation "if (false)" stays green.
    def feet(mm):
        return repr(float(mm) / 304.8)

    assert f"Math.Abs(__sumBefore - {feet(total)})" in source, source
    assert f"Math.Abs(__sumAfter - {feet(plan.diff['expected_total_width_mm'])})" in source


def test_a_break_inside_observe_after_leaves_committed_unverified_not_ok(bound):
    """A break in the middle of the after-observation is `committed_unverified`, not `ok`."""
    source = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4())).source
    unverified = source.index('__receipt["state"] = "committed_unverified"')
    verified = source.index('__receipt["state"] = "committed_verified"')
    # The state is set IMMEDIATELY after the commit and is only cleared by verification.
    assert source.index('__receipt["effect"] = "committed"') < unverified < verified
    assert unverified < source.index('"observed_after"')
    assert source.index('__receipt["ok"] = __good') > unverified


def test_python_cannot_call_an_unverified_commit_verified(bound, tmp_path):
    """The receipt outranks the caller's word: unverified is only ever closed by unknown."""
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    ledger = str(tmp_path / "unit.json")
    reserve_transaction_unit(prepared, ledger_path=ledger)
    unverified = {"state": "committed_unverified", "effect": "committed"}
    with pytest.raises(TransactionUnitRefusal) as error:
        settle_transaction_unit(prepared, ledger_path=ledger, outcome="committed", receipt=unverified)
    assert error.value.code == "receipt_is_not_verified"
    settled = settle_transaction_unit(prepared, ledger_path=ledger, outcome="unknown", receipt=unverified)
    assert settled["outcome"] == "unknown" and settled["receipt"]["effect"] == "committed"


def test_a_verified_receipt_is_the_only_road_to_a_committed_outcome(bound, tmp_path):
    prepared = prepare_transaction_unit(wall_plan(bound), operation_id=str(uuid4()))
    ledger = str(tmp_path / "unit.json")
    reserve_transaction_unit(prepared, ledger_path=ledger)
    settled = settle_transaction_unit(prepared, ledger_path=ledger, outcome="committed",
                                      receipt={"state": "committed_verified", "ok": True})
    assert settled["outcome"] == "committed" and settled["state"] == "settled"


def test_each_layered_guard_answers_for_its_own_named_cause(bound):
    """The guards are two-layered ON PURPOSE, and their codes differ —
    otherwise a mutation stays silent.

    07.09: removing one layer left the test green, because the second layer
    answered with THE SAME code. The check is now on the CODE, not on the
    fact of a refusal.
    """
    # A foreign address and "the row isn't under its own name" are different causes.
    with pytest.raises(TransactionUnitRefusal) as foreign:
        wall_plan(bound, unique_id="somebody-elses-uid")
    assert foreign.value.code == "foreign_unique_id"

    class Mislabelled:
        target, precondition = bound[0], bound[2]
        source_sha256, digest = "d" * 64, "e" * 64
        rows = {WALL_UID: dict(type_row(WALL_UID, 501, "Наружная 220",
                [{"width_mm": 200.0, "function": "Structure"}]), requested_unique_id="another")}

    import kir.emit_transaction_unit as module
    with pytest.raises(TransactionUnitRefusal) as mislabelled:
        module._observed_row(Mislabelled(), WALL_UID)
    assert mislabelled.value.code == "observation_row_mislabelled"

    # The emitter scaffold and "an extra transaction of one's own" are also different causes.
    original = module.emit_transaction_unit_cs
    plan = wall_plan(bound)
    try:
        module.emit_transaction_unit_cs = lambda p: (
            'using (Transaction __t = new Transaction(doc, "чужой каркас")) {\n'
            + original(p) + "\n}\n")
        with pytest.raises(TransactionUnitRefusal) as frame:
            prepare_transaction_unit(plan, operation_id=str(uuid4()))
        assert frame.value.code == "transaction_owner_conflict"
        module.emit_transaction_unit_cs = lambda p: (
            original(p) + '\nusing (Transaction __extra = new Transaction(doc, "вторая")) { }\n')
        with pytest.raises(TransactionUnitRefusal) as extra:
            prepare_transaction_unit(plan, operation_id=str(uuid4()))
        assert extra.value.code == "transaction_count_unexpected"
    finally:
        module.emit_transaction_unit_cs = original


# ───────────── the "section → minimum version" table ──

VERSION_MATRIX = [
    ("in_place", 2021), ("duplicate_and_reassign", 2021),
    ("floor_sketch_opening", 2022), ("floor_new_sketch", 2023),
]


def make_variant(kind, scope):
    target, _auth, precondition = scope
    loop = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 800.0), (0.0, 800.0)]
    if kind == "in_place":
        return wall_plan(scope)
    if kind == "duplicate_and_reassign":
        return duplicate_plan(scope)
    return plan_floor_sketch_opening(element_observation(scope), unique_id=FLOOR_UID,
        loop_mm=loop, target=target, precondition=precondition,
        allow_new_sketch=kind == "floor_new_sketch")


def duplicate_plan(scope, **kwargs):
    target, _auth, precondition = scope
    fields = {"unique_id": WALL_UID, "layer_index": 0, "width_mm": 260.0, "target": target,
              "precondition": precondition, "type_users": type_users(3),
              "identity_replacement": "duplicate_and_reassign",
              "new_type_name": "Наружная 260", "reassign_unique_ids": ["user-0", "user-2"]}
    fields.update(kwargs)
    observation = fields.pop("observation", None) or type_observation(scope)
    return plan_wall_type_layer_width(observation, **fields)


@pytest.mark.parametrize("version", ["2021", "2022", "2023", "2026"])
@pytest.mark.parametrize("kind,minimum", VERSION_MATRIX)
def test_the_version_table_is_confirmed_by_the_actual_compiler(
        version, kind, minimum, type_conformance_runner):
    """The version table is not an agreement but A MEASUREMENT: what is
    allowed compiles.

    The refusal must arrive at the PLAN stage. Before 07.09 there was none at
    all, and `floor_sketch_opening` under target 2021 handed back source
    that does not compile (`CS1061: 'Floor' … 'SketchId'`) — you would only
    find that out on the far end.
    """
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    scope = (target, SessionCredentials(target, str(uuid4()), "t"),
             ContextPrecondition("native-doc", 21))
    if int(version) < minimum:
        with pytest.raises(TransactionUnitRefusal) as error:
            make_variant(kind, scope)
        assert error.value.code.startswith("section_unsupported_on_version:"), error.value.code
        assert error.value.code.endswith(":" + version), error.value.code
        return
    source = prepare_transaction_unit(make_variant(kind, scope), operation_id=str(uuid4())).source
    row, = type_conformance_runner(version, [source])
    assert row["ok"] is True, (version, kind, row["diagnostics"])
    assert row["assembly_bytes"] > 0


@pytest.mark.parametrize("kind,minimum", [("floor_sketch_opening", 2022), ("floor_new_sketch", 2023)])
def test_what_the_table_forbids_really_does_not_compile(kind, minimum, type_conformance_runner):
    """The other side: the ban is not made up — on the older version the C#
    does NOT compile.

    A plan compiles for an ALLOWED version, and gets compiled against the
    older one. Without this, the table would be an agreement, not a number.
    """
    older = str(minimum - 1)
    allowed = RuntimeTarget(str(uuid4()), str(uuid4()), str(minimum))
    scope = (allowed, SessionCredentials(allowed, str(uuid4()), "t"),
             ContextPrecondition("native-doc", 21))
    source = prepare_transaction_unit(make_variant(kind, scope), operation_id=str(uuid4())).source
    row, = type_conformance_runner(older, [source])
    assert row["ok"] is False, (kind, older, row)
    assert row["assembly_bytes"] == 0
    expected = "SketchId" if kind == "floor_sketch_opening" else "SketchEditScope"
    assert any(expected in item for item in row["diagnostics"]), (kind, older, row["diagnostics"])


# ───────────── duplicate_and_reassign ──


def test_the_duplicate_plan_names_the_new_type_the_moved_and_the_stayers(bound):
    plan = duplicate_plan(bound)
    own = plan.ownership
    assert plan.identity_replacement == "duplicate_and_reassign"
    assert own["new_type_name"] == "Наружная 260"
    assert own["reassign_unique_ids"] == ["user-0", "user-2"] and own["reassign_count"] == 2
    # The remaining ones are named individually — "not all are converted" is a list, not a word.
    assert own["retained_on_source_unique_ids"] == ["user-1"]
    assert own["source_type_preserved"] is True and own["source_type_unique_id"] == WALL_UID
    assert own["changed_unique_ids"] == ["user-0", "user-2"]
    # The source's layer stack is recorded IN FULL and does not match the duplicate's stack.
    assert plan.diff["source_layers_unchanged"] == [
        {"index": 0, "width_mm": 200.0, "function": "Structure"},
        {"index": 1, "width_mm": 20.0, "function": "Finish1"}]
    assert plan.diff["duplicate_layers"][0]["width_mm"] == 260.0
    assert plan.diff["source_total_width_mm"] == 220.0
    assert plan.diff["expected_total_width_mm"] == 280.0


@pytest.mark.parametrize("kwargs,code", [
    ({"reassign_unique_ids": []}, "reassign_scope_empty"),
    ({"reassign_unique_ids": ["user-0", "чужой"]}, "reassign_outside_type_user_scope"),
    ({"reassign_unique_ids": ["user-0", "user-0"]}, "duplicate_reassign_identity"),
    ({"reassign_unique_ids": None}, "reassign_scope_required"),
    ({"new_type_name": ""}, "duplicate_name_required"),
    ({"new_type_name": "Плохое{имя}"}, "duplicate_name_invalid"),
    ({"new_type_name": "Наружная 220"}, "duplicate_name_collides"),
])
def test_the_duplicate_plan_refuses_before_any_effect(bound, kwargs, code):
    with pytest.raises(TransactionUnitRefusal) as error:
        duplicate_plan(bound, **kwargs)
    assert error.value.code == code


def test_duplicate_arguments_without_the_policy_are_refused(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        wall_plan(bound, new_type_name="Наружная 260")
    assert error.value.code == "duplicate_arguments_without_policy"


def test_the_duplicate_unit_checks_the_source_on_both_sides_and_reports_new_identity(bound):
    plan = duplicate_plan(bound)
    source = prepare_transaction_unit(plan, operation_id=str(uuid4())).source
    # The name is checked BEFORE the effect: the comparison happens before the transaction opens.
    assert source.index('"duplicate_name_collides"') < source.index("new Transaction(doc")
    # The source type is intact — for EVERY layer and on both sides of the
    # commit. We check the COMPARISONS THEMSELVES, not how many times the
    # refusal's name is mentioned: otherwise a mutation that removes one of
    # the three stays green (measured 07.09, control O).
    def feet(mm):
        return repr(float(mm) / 304.8)

    for row in plan.diff["source_layers_unchanged"]:
        assert f'__before[{row["index"]}].Width - {feet(row["width_mm"])}' in source, row
        assert f'__srcAfter[{row["index"]}].Width - {feet(row["width_mm"])}' in source, row
    assert '"source_layer_changed_since_observation"' in source
    assert f'__srcAfter.Count != {plan.diff["observed_layer_count"]}' in source
    assert f'Math.Abs(__srcSum - {feet(plan.diff["source_total_width_mm"])})' in source
    assert f'Math.Abs(__dupSum - {feet(plan.diff["expected_total_width_mm"])})' in source
    # New identities and types before/after for each converted one.
    for marker in ('"new_type_unique_id"', '"new_type_element_id"', '"type_id_before"',
                   '"type_id_after"', '"retained_on_source"', '__u.ChangeTypeId(__dupId)'):
        assert marker in source, marker
    order = [source.index(m) for m in ('"observed_before"', '"unit_committed"', '"observed_after"')]
    assert order == sorted(order)
    assert source.index('__receipt["state"] = "committed_unverified"') < order[2]
    assert source.count("new Transaction(doc") == 1
    assert "Transaction __t = new Transaction(doc," not in source


def test_a_duplicate_plan_survives_restart_and_reserves_its_effect_once(bound, tmp_path):
    plan = duplicate_plan(bound)
    retained = load_transaction_unit_plan(json.loads(json.dumps(plan.to_dict())))
    assert retained.matches(plan)
    prepared = prepare_transaction_unit(plan, operation_id=str(uuid4()))
    ledger = str(tmp_path / "dup.json")
    assert reserve_transaction_unit(prepared, ledger_path=ledger)["state"] == "reserved"
    with pytest.raises(TransactionUnitRefusal) as error:
        reserve_transaction_unit(prepared, ledger_path=ledger)
    assert error.value.code == "effect_already_reserved"


# ───────────── StartWithNewSketch ──


def test_a_new_sketch_happens_only_when_the_plan_says_so(bound):
    default = plan_floor_sketch_opening(element_observation(bound), unique_id=FLOOR_UID,
        loop_mm=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 800.0), (0.0, 800.0)],
        target=bound[0], precondition=bound[2])
    assert default.diff["allow_new_sketch"] is False
    quiet = prepare_transaction_unit(default, operation_id=str(uuid4())).source
    assert '"sketch_missing"' in quiet and "StartWithNewSketch" not in quiet
    assert "__scope.Start(__sketchId)" in quiet

    explicit = make_variant("floor_new_sketch", bound)
    assert explicit.diff["allow_new_sketch"] is True
    assert explicit.diff["expected_sketch_before"] == "absent"
    loud = prepare_transaction_unit(explicit, operation_id=str(uuid4())).source
    assert "__scope.StartWithNewSketch(__el.Id)" in loud
    # The other side of the flag: a sketch that ALREADY exists is a refusal, not a silent Start.
    assert '"sketch_already_present"' in loud and '"sketch_missing"' not in loud
    assert loud.index('"sketch_already_present"') < loud.index("new SketchEditScope")
    assert '__receipt["state"] = "committed_unverified"' in loud
    assert loud.index('__receipt["state"] = "committed_unverified"') < loud.index('"observed_after"')


def test_the_new_sketch_flag_is_strictly_boolean(bound):
    for flag in (1, "true", None, []):
        with pytest.raises(TransactionUnitRefusal) as error:
            plan_floor_sketch_opening(element_observation(bound), unique_id=FLOOR_UID,
                loop_mm=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 800.0)],
                target=bound[0], precondition=bound[2], allow_new_sketch=flag)
        assert error.value.code in ("invalid_input", "section_unsupported_on_version")


# ───────────── an element replacement on a type change — a legal outcome ──


def test_observe_after_reads_the_replacement_not_the_dead_old_uid(bound):
    """`ChangeTypeId` can create a NEW element; the old one is then dead.

    Found by the identity agent: the after-observation was reading by the
    OLD UniqueId, getting null, and declaring `after_observation_disagrees`
    — a failure on a successful replacement. `RevitAPI.xml`, verbatim: "In
    rare cases, applying a change in type will result in a new element being
    created… the new element id is returned."
    """
    source = prepare_transaction_unit(duplicate_plan(bound), operation_id=str(uuid4())).source
    body, after = source.split('__receipt["state"] = "committed_unverified"', 1)
    # Phase 2 remembers the live address, phase 3 reads THAT ONE.
    assert "string[] __replacement = new string[__reassign.Length];" in body
    assert "doc.GetElement(__replaced ? __newElement : __wasId)" in body
    assert "__replacement[__i]" in after
    assert "doc.GetElement(__reassign[__i])" not in after, "фаза 3 читает мёртвый старый uid"
    # The address and type are captured BEFORE the call: after the replacement the old object must not be touched.
    assert body.index("ElementId __wasId = __u.Id;") < body.index("__u.ChangeTypeId(__dupId)")
    # A lost address is a separate cause, not "the wrong type."
    assert '"reassigned_element_unreadable"' in after


def test_the_receipt_carries_the_named_identity_replacement_ledger(bound):
    from kir.emit_transaction_unit import IDENTITY_REPLACEMENT_ROW, IDENTITY_REPLACEMENT_SCHEMA

    assert IDENTITY_REPLACEMENT_SCHEMA == "kir-create-identity-replacement/1"
    assert set(IDENTITY_REPLACEMENT_ROW) >= {"schema", "old_unique_id", "new_unique_id",
                                             "identity_replaced"}
    source = prepare_transaction_unit(duplicate_plan(bound), operation_id=str(uuid4())).source
    assert f'"{IDENTITY_REPLACEMENT_SCHEMA}"' in source
    assert '__receipt["identity_replacements"] = __moved;' in source
    # The old/new pair appears in BOTH phases: in the effect record and in the after-observation.
    assert source.count('{ "old_unique_id"') == 2 and source.count('{ "new_unique_id"') == 2
    assert source.count('{ "identity_replaced"') == 2


def test_the_identity_replacement_probe_is_green(bound):
    """The same probe that was red 6/6 before the fix."""
    import subprocess

    probe = ROOT / "kir/tests/probes/native_identity_replacement.py"
    assert probe.is_file(), f"зонд отсутствует в дереве: {probe}"
    result = subprocess.run([sys.executable, str(probe)], text=True, capture_output=True,
                            timeout=300, env={**os.environ, "PYTHONPATH": str(ROOT),
                                              "PYTHONDONTWRITEBYTECODE": "1"})
    assert "НЕ ДЕРЖИТСЯ СВОЙСТВ: 0 " in result.stdout, result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_the_replacement_aware_unit_still_compiles(version, type_conformance_runner):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    scope = (target, SessionCredentials(target, str(uuid4()), "t"),
             ContextPrecondition("native-doc", 21))
    source = prepare_transaction_unit(duplicate_plan(scope), operation_id=str(uuid4())).source
    row, = type_conformance_runner(version, [source])
    assert row["ok"] is True, (version, row["diagnostics"])
    assert row["assembly_bytes"] > 0
