"""REPLACING NATIVE IDENTITY: the link relocates, it does not tear.

🔴 WHAT IS MEASURED AND WHY THIS WAS EVEN STARTED (07.09.2026).
`Element.ChangeTypeId` is documented by the assemblies: «In rare cases,
applying a change in type will result in a new element being created. The
ONLY active examples of this are when applying a normal wall type to a
curtain panel, or converting such a wall back to a curtain panel. In this
situation the new element id is returned. Also, this element becomes
invalid.» That is, for ONE authored output, native identity can change
without the author's involvement.

Emission ALREADY carried this fact — `replacement_element_id` (the
transaction unit), `new_element_created` (`change_type`),
`panel_replaced`/`returned_panel_id` (the curtain-wall panel cell) — yet the
number of consumers for these four fields was **zero**. The 07.09
reconnaissance measured the consequence on a real discrepancy report: a
replacement produced `authored_only=1 + observed_only=1` where a control
without replacement gives `both_agree=1`. One building split into "the
author lied" and "there's someone else's stuff in the model," and neither
half was true.

THE PROBES HERE. 1 — the ledger is assembled only from CONFIRMED data, the
old link stays intact; 2 — republishing after a replacement does not build a
second element and names the refusal cause DISTINGUISHABLY; 3 — the
typed-links report after a replacement yields ONE `matched` line for the new
uid instead of unknown. Each comes with its own control, and probe 3 also
with a FAIL control: the address-resolution mechanism is deliberately
broken, and the probe must turn red.

There is no Revit here: a real project/compiler/archive/receipt/observation
parser, a synthetic native response.
"""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.create_publication import (CreatePublicationError, IDENTITY_REPLACEMENT_SCHEMA,
                                    IdentityReplacementLedger, assess_identity_replacement,
                                    validate_identity_replacement_ledger)
from kir.create_type_discrepancy import CreateTypeDiscrepancyError, assess_create_type_discrepancies
from kir.element_query import ELEMENT_STATE_SCHEMA, TYPE_DEFINITION_STATE_SCHEMA
from kir.created_ledger import extract_created, replacement_born_ids
from kir.staged_create_projection import StagedProjectionError, bind_staged_create_projection
from kir.tests.test_create_type_discrepancy import bind, consumer, observation, scenario
from kir.tests.test_revit_observation import identity


NEW_UID = "uid-wall-0-replaced"
NEW_ID = 1900
CLAIM = {"old_unique_id": "uid-wall-0", "new_unique_id": NEW_UID,
         "reason": "change_type_replacement"}


def gone(uid, *, typed=False):
    """The "no such element" line. Exactly what an observation sees for a
    dead uid."""
    row = {"schema_version": TYPE_DEFINITION_STATE_SCHEMA if typed else ELEMENT_STATE_SCHEMA,
           "requested_unique_id": uid, "status": "not_found", "reason": None, "name": None,
           "category_id": None, "is_level": None, "type_state": None,
           "level_status": "not_evaluated", "level_reason": None, "level": None,
           "element_identity": None, "element_identity_status": "unavailable",
           "element_identity_reason": "element_missing"}
    if typed:
        row["type_definition"] = {"status": "unavailable",
                                  "reason": "base_observation_unavailable", "value": None}
    return row


def replaced(rows, *, old="uid-wall-0", new=NEW_UID, new_id=NEW_ID, keep_old=False):
    """A replacement in the observation: the old uid is dead, the new one
    lives on the SAME type."""
    previous = rows[old]
    if not keep_old:
        rows[old] = gone(old)
    fresh = deepcopy(previous)
    fresh["requested_unique_id"] = new
    fresh.update(identity(new_id, new))
    rows[new] = fresh
    return rows


def ledger(case, observed, *, claims=(CLAIM,), bound=None):
    return assess_identity_replacement(case["project"], case["record"], bound or bind(case),
                                       observed, claims=list(claims))


# ── PROBE 1: the ledger is assembled only from confirmed data ─────────────


def test_a_confirmed_replacement_keeps_the_old_link_and_names_its_successor(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed)
    data = book.to_dict()

    assert data["schema"] == IDENTITY_REPLACEMENT_SCHEMA and data["replacement_count"] == 1
    entry, = data["replacements"]
    # The old link is NOT erased: it travels intact and gets a successor.
    assert entry["original_identity"]["unique_id"] == "uid-wall-0"
    assert entry["original_observed_status"] == "not_found"
    assert entry["superseded_by"] == NEW_UID
    assert entry["replacement_identity"] == {**identity(NEW_ID, NEW_UID)["element_identity"]}
    assert entry["reason"] == "change_type_replacement"
    assert entry["output_key"] == "wall-0" and entry["source_op"] == "create_wall"
    # The confirmation is signed by a revision of THAT SAME snapshot, not
    # "sometime."
    assert entry["confirmed_at_revision"] == data["observation"]["precondition"]["revision"] == 9
    assert data["execution"]["precondition"]["revision"] == 8

    assert book.superseded_by("uid-wall-0") == NEW_UID
    assert book.effective_unique_id("uid-wall-0") == NEW_UID
    # An unfamiliar address remains itself: the ledger does not invent links.
    assert book.effective_unique_id("uid-wall-type") == "uid-wall-type"
    validate_identity_replacement_ledger(case["record"], bind(case), data)


def test_the_ledger_is_frozen_and_cannot_be_built_from_its_own_serialization(tmp_path):
    case = scenario(tmp_path)
    book = ledger(case, observation(case, mutate=replaced))
    with pytest.raises(TypeError):
        IdentityReplacementLedger(**book.to_dict())
    with pytest.raises(CreatePublicationError, match="invalid_identity_replacement"):
        validate_identity_replacement_ledger(case["record"], bind(case),
                                             {**book.to_dict(), "replacement_count": 7})


# ── CONTROLS FOR PROBE 1: the unconfirmed is rejected BY NAME ─────────────


def test_a_replacement_whose_original_is_still_alive_is_refused_by_name(tmp_path):
    """The old uid is alive — meaning there was no replacement, whatever the
    caller claims."""
    case = scenario(tmp_path)
    observed = observation(case, mutate=lambda rows: replaced(rows, keep_old=True))
    with pytest.raises(CreatePublicationError, match="replacement_unconfirmed"):
        ledger(case, observed)


def test_a_replacement_whose_successor_was_not_requested_is_refused_by_name(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=lambda rows: rows.update({"uid-wall-0": gone("uid-wall-0")}))
    with pytest.raises(CreatePublicationError, match="replacement_unconfirmed"):
        ledger(case, observed)


def test_a_successor_that_the_model_does_not_have_is_refused_by_name(tmp_path):
    case = scenario(tmp_path)

    def both_gone(rows):
        rows["uid-wall-0"] = gone("uid-wall-0")
        rows[NEW_UID] = gone(NEW_UID)

    with pytest.raises(CreatePublicationError, match="replacement_unconfirmed"):
        ledger(case, observation(case, mutate=both_gone))


def test_a_replacement_of_a_foreign_identity_is_refused(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    with pytest.raises(CreatePublicationError, match="replacement_old_identity_unqualified"):
        ledger(case, observed, claims=({**CLAIM, "old_unique_id": "uid-not-ours"},))


@pytest.mark.parametrize("claims", [
    (),
    ({"old_unique_id": "uid-wall-0", "new_unique_id": NEW_UID},),
    ({**CLAIM, "reason": "because_i_said_so"},),
    ({**CLAIM, "new_unique_id": "uid-wall-0"},),
    ({**CLAIM}, {**CLAIM, "new_unique_id": "another"}),
])
def test_malformed_claims_never_become_a_ledger(tmp_path, claims):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    with pytest.raises(CreatePublicationError, match="identity_replacement_claims_invalid"):
        ledger(case, observed, claims=claims)


def test_a_snapshot_from_another_runtime_cannot_confirm_a_replacement(tmp_path):
    from kir.revit_connector import RuntimeTarget

    case = scenario(tmp_path)
    other = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    observed = observation(case, mutate=replaced, runtime=other)
    with pytest.raises(CreatePublicationError, match="observation_runtime_or_document_mismatch"):
        ledger(case, observed)


def test_a_snapshot_before_the_publication_cannot_confirm_a_replacement(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced, revision=8)
    with pytest.raises(CreatePublicationError, match="observation_not_after_publication"):
        ledger(case, observed)


# ── PROBE 3: the typed-links report after a replacement ───────────────────


def test_without_the_ledger_a_replacement_is_indistinguishable_from_blindness(tmp_path):
    """TODAY'S NUMBER WITHOUT A LEDGER. A replacement cannot be told apart
    from "wasn't read"."""
    case = scenario(tmp_path)
    data = assess_create_type_discrepancies(case["project"], case["record"], bind(case),
                                            observation(case, mutate=replaced)).to_dict()
    row = consumer(data)
    # "Not observed" and "replaced" are spoken with ONE name — that is the
    # whole blindness.
    assert (row["state"], row["diagnostic"]) == ("unavailable", "consumer_observation_unavailable")
    assert data["counts"] == {"matched": 0, "mismatch": 0, "unavailable": 1, "conflict": 0}
    assert data["identity_replacement"] is None


def test_with_the_ledger_the_replaced_consumer_is_one_matched_row(tmp_path):
    """PROBE. One `matched` line for the NEW uid, not a pair of "gone/foreign"."""
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed)
    data = assess_create_type_discrepancies(case["project"], case["record"], bind(case),
                                            observed, replacements=book).to_dict()
    row = consumer(data)
    assert (row["state"], row["diagnostic"]) == ("matched", "revision_bound_type_link_matches_output")
    assert data["counts"] == {"matched": 1, "mismatch": 0, "unavailable": 0, "conflict": 0}
    # The new identity is named, the old one is not forgotten, and the
    # transition is signed by the ledger.
    assert row["observed_consumer_identity"]["unique_id"] == NEW_UID
    assert row["original_consumer_identity"]["unique_id"] == "uid-wall-0"
    assert row["consumer_identity_replacement"] == {
        "original_unique_id": "uid-wall-0", "effective_unique_id": NEW_UID,
        "reason": "change_type_replacement"}
    # The type did not change — there is NO replacement record for it, and
    # this too is checked.
    assert row["expected_type_identity_replacement"] is None
    assert data["identity_replacement"]["ledger_digest"] == book.digest


def test_the_control_without_any_replacement_still_matches(tmp_path):
    """CONTROL. The ledger moves nothing where there is nothing to move."""
    case = scenario(tmp_path)
    data = assess_create_type_discrepancies(case["project"], case["record"], bind(case),
                                            observation(case)).to_dict()
    assert consumer(data)["state"] == "matched"
    assert consumer(data)["consumer_identity_replacement"] is None


def test_the_probe_goes_red_when_address_resolution_is_broken(tmp_path, monkeypatch):
    """FAIL CONTROL. We break ADDRESS RESOLUTION — the probe must turn red.

    Otherwise the green above would prove the report's shape, not the
    mechanism's work.
    """
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed)
    monkeypatch.setattr(IdentityReplacementLedger, "effective_unique_id",
                        lambda self, unique_id: unique_id)
    data = assess_create_type_discrepancies(case["project"], case["record"], bind(case),
                                            observed, replacements=book).to_dict()
    assert consumer(data)["state"] == "unavailable"
    assert data["counts"]["matched"] == 0


def test_a_ledger_from_another_snapshot_is_refused_not_silently_ignored(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed)
    other = observation(case, mutate=replaced, revision=11)
    with pytest.raises(CreateTypeDiscrepancyError, match="identity_replacement_observation_mismatch"):
        assess_create_type_discrepancies(case["project"], case["record"], bind(case),
                                         other, replacements=book)


def test_a_ledger_from_another_publication_is_refused(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed)
    (tmp_path / "second").mkdir()
    second = scenario(tmp_path / "second")
    with pytest.raises(CreateTypeDiscrepancyError, match="identity_replacement_publication_mismatch"):
        assess_create_type_discrepancies(second["project"], second["record"], bind(second),
                                         observation(second), replacements=book)


# ── PROBE 2: republishing after a replacement ─────────────────────────────

STAGED_NEW_UID = "uid-1-replaced"


def staged_case(**kwargs):
    from kir.tests.test_staged_create_projection import case as build
    return build(**kwargs)


def import_oid(value, unique_id):
    """The import address whose ORIGINAL identity is this uid. Not by list
    order."""
    from kir.create_publication import assess_create_identities

    outputs = assess_create_identities(value["project"], value["archive"],
                                       value["bound"]).to_dict()["outputs"]
    by_uid = {row["element_identity"]["unique_id"]: row["output_id"] for row in outputs
              if row["state"] in ("created_here", "reused_existing")}
    return by_uid[unique_id]


def staged_replaced(rows):
    """The type was replaced on a type change: the old uid is dead, the new
    one carries the same definition."""
    previous = rows.pop("uid-1")
    rows["uid-1"] = gone("uid-1", typed=True)
    fresh = deepcopy(previous)
    fresh["requested_unique_id"] = STAGED_NEW_UID
    fresh.update(identity(1901, STAGED_NEW_UID))
    rows[STAGED_NEW_UID] = fresh


def staged_ledger(value, *, old="uid-1", new=STAGED_NEW_UID):
    return assess_identity_replacement(value["project"], value["archive"], value["bound"],
        value["observation"], claims=[{"old_unique_id": old, "new_unique_id": new,
                                       "reason": "change_type_replacement"}])


def test_a_repeat_publication_names_an_unrequested_address_apart_from_a_dead_one():
    """THERE USED TO BE ONE REFUSAL FOR THREE CASES; now they are
    distinguished BY NAME."""
    value = staged_case(mutate_observed=lambda rows: rows.pop("uid-1"))
    with pytest.raises(StagedProjectionError, match="staged_import_observation_absent"):
        bind_staged_create_projection(value["partition"], import_sources=value["imports"],
                                      observation=value["observation"])


def test_a_repeat_publication_over_a_dead_address_says_the_element_is_gone():
    value = staged_case(mutate_observed=lambda rows: rows.update({"uid-1": gone("uid-1", typed=True)}))
    with pytest.raises(StagedProjectionError, match="staged_import_element_not_found"):
        bind_staged_create_projection(value["partition"], import_sources=value["imports"],
                                      observation=value["observation"])


def test_a_ledger_that_does_not_explain_this_address_gets_its_own_name():
    """The ledger is supplied and REAL, yet it does not explain this
    address — its own name.

    A level vanished, a type was replaced. The same ledger explains the
    second and says nothing about the first: that silence must not sound
    like "no such element," otherwise the caller would go off chasing a
    deletion instead of their own request.
    """
    def both(rows):
        staged_replaced(rows)
        rows["uid-0"] = gone("uid-0", typed=True)

    value = staged_case(mutate_observed=both)
    book = staged_ledger(value)
    everywhere = {oid: book for oid in value["partition"].import_output_ids}
    with pytest.raises(StagedProjectionError, match="staged_import_replacement_unconfirmed"):
        bind_staged_create_projection(value["partition"], import_sources=value["imports"],
                                      observation=value["observation"], replacements=everywhere)


def test_a_confirmed_replacement_lets_the_repeat_publication_bind_the_survivor():
    """PROBE. No second element gets built: the link relocates onto the
    replacement."""
    value = staged_case(mutate_observed=staged_replaced)
    book = staged_ledger(value)
    oid = import_oid(value, "uid-1")

    # WITHOUT a ledger — a refusal, and it names exactly what is missing.
    with pytest.raises(StagedProjectionError, match="staged_import_element_not_found"):
        bind_staged_create_projection(value["partition"], import_sources=value["imports"],
                                      observation=value["observation"])

    projection = bind_staged_create_projection(value["partition"], import_sources=value["imports"],
        observation=value["observation"], replacements={oid: book})
    core = projection.core
    assert STAGED_NEW_UID in core["required_import_unique_ids"]
    assert "uid-1" not in core["required_import_unique_ids"]
    line = next(row for row in core["import_lineage"] if row["output_id"] == oid)
    # The old link is named, the new one is named, the transition is signed
    # by the ledger.
    assert line["original_identity"]["unique_id"] == "uid-1"
    assert line["observed_identity"]["unique_id"] == STAGED_NEW_UID
    assert line["identity_replacement"] == {"original_unique_id": "uid-1",
        "effective_unique_id": STAGED_NEW_UID, "reason": "change_type_replacement",
        "ledger_digest": book.digest}
    # The turn guard points at a LIVE element, not a dead number.
    assert 1901 in {proof.element_id for proof in projection.expected_identities}
    projection.validate()


def test_the_control_repeat_publication_without_a_replacement_is_unchanged():
    """CONTROL. Where there was no replacement, nothing moved."""
    value = staged_case()
    projection = bind_staged_create_projection(value["partition"],
        import_sources=value["imports"], observation=value["observation"])
    assert projection.core["required_import_unique_ids"] == ["uid-0", "uid-1"]
    assert all(row["identity_replacement"] is None for row in projection.core["import_lineage"])
    projection.validate()


# ── PROBE ON THE REGISTRY OF CREATED ELEMENTS: what a replacement births is not lost ──


def test_a_mutating_op_that_replaced_an_element_leaves_a_trace():
    """🔴 WHAT A REPLACEMENT BIRTHS IS ALSO SOMETHING LEFT IN SOMEONE ELSE'S MODEL."""
    assert extract_created({"CT1": {"id": "900", "new_element_created": True}},
                           op_kinds={"CT1": "change_type"}) == {"CT1": ["900"]}
    assert extract_created({"CP1": {"panel_replaced": True, "returned_panel_id": "11401344"}},
                           op_kinds={"CP1": "set_curtain_panel"}) == {"CP1": ["11401344"]}
    assert replacement_born_ids({"replacement_element_id": "1200"}) == ["1200"]


def test_an_ordinary_mutation_still_owns_nothing():
    """CONTROL AND PIN ON F-297. Editing someone else's element leaves NO
    trace."""
    assert extract_created({"CT1": {"id": "800", "new_element_created": False}},
                           op_kinds={"CT1": "change_type"}) == {}
    assert extract_created({"SP1": {"id": "800"}}, op_kinds={"SP1": "set_param"}) == {}
    assert replacement_born_ids({"id": "800", "new_element_created": False}) == []
    assert replacement_born_ids({"replacement_element_id": None}) == []


def test_a_creating_op_is_untouched_by_the_replacement_rule():
    """CONTROL. The creating op is still counted as such; a flag cannot move
    it."""
    assert extract_created({"W1": {"id": "700"}}, op_kinds={"W1": "create_wall"}) == {"W1": ["700"]}


# ── CONVERGENCE OF FORMS: the unit's receipt line goes in WITHOUT RENAMING ─


def unit_row(*, old="uid-wall-0", new=NEW_UID, replaced=True, old_id="900", new_id=str(NEW_ID)):
    """A line of exactly the shape that `emit_transaction_unit` puts into
    the receipt.

    Assembled BY THE CONTRACT of the neighboring plot, not from memory: the
    field names are taken from `IDENTITY_REPLACEMENT_ROW`, and if the
    contract shifts, the probe will turn red here, not in someone else's
    model.
    """
    from kir.emit_transaction_unit import IDENTITY_REPLACEMENT_ROW, IDENTITY_REPLACEMENT_SCHEMA

    row = dict(zip(IDENTITY_REPLACEMENT_ROW,
                   (IDENTITY_REPLACEMENT_SCHEMA, old, new, replaced, old_id, new_id)))
    assert set(row) == set(IDENTITY_REPLACEMENT_ROW)
    # The unit also lays down its own bookkeeping alongside; it must not get
    # in the way.
    row["type_id_before"] = "7469627"
    return row


def test_both_sides_name_one_schema_from_one_place():
    """🔴 THE SCHEMA'S NAME LIVES IN ONE PLACE, NOT IN TWO LITERALS."""
    from kir.emit_transaction_unit import IDENTITY_REPLACEMENT_SCHEMA as native

    assert native == IDENTITY_REPLACEMENT_SCHEMA == "kir-create-identity-replacement/1"


def test_a_native_unit_row_becomes_a_ledger_without_being_renamed(tmp_path):
    """CONVERGENCE PROBE. Unit receipt -> identity carrier, ingested as-is."""
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    book = ledger(case, observed, claims=(unit_row(),))
    entry, = book.to_dict()["replacements"]
    assert entry["original_identity"]["unique_id"] == "uid-wall-0"
    assert entry["superseded_by"] == NEW_UID
    assert entry["reason"] == "change_type_replacement"
    assert book.effective_unique_id("uid-wall-0") == NEW_UID


def test_a_row_reporting_no_replacement_is_not_a_claim(tmp_path):
    """CONTROL. `identity_replaced: false` — the type changed IN PLACE."""
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    with pytest.raises(CreatePublicationError, match="identity_replacement_claims_invalid"):
        ledger(case, observed, claims=(unit_row(replaced=False),))


def test_a_row_with_a_foreign_schema_is_refused(tmp_path):
    case = scenario(tmp_path)
    observed = observation(case, mutate=replaced)
    with pytest.raises(CreatePublicationError, match="identity_replacement_claims_invalid"):
        ledger(case, observed, claims=({**unit_row(), "schema": "someone-elses/1"},))


def test_a_native_row_still_needs_its_observation_confirmation(tmp_path):
    """CONTROL. The receipt is a claim, not a confirmation: the old one is
    alive -> refusal."""
    case = scenario(tmp_path)
    observed = observation(case, mutate=lambda rows: replaced(rows, keep_old=True))
    with pytest.raises(CreatePublicationError, match="replacement_unconfirmed"):
        ledger(case, observed, claims=(unit_row(),))


# ── CONVERGENCE IN THE OTHER DIRECTION: carrier -> discrepancy bridge (graph) ──


def two_sided_observation(case, old_uid, new_uid, *, revision=9, document="native-doc"):
    """A snapshot carrying BOTH sides of the replacement: the dead address
    and its replacement."""
    from kir.revit_connector import ContextPrecondition, SessionCredentials
    from kir.revit_observation import parse_element_observation, prepare_element_observation
    from kir.tests.test_revit_observation import row as observed_row
    from kir.tests.test_revit_level_update import response_for

    live = observed_row(new_uid, is_level=False)
    live.update(identity(1900, new_uid))
    live["category_id"] = -2000011
    live["type_state"] = {"status": "observed", **identity(1740, "type-uid-wall")}
    values = {old_uid: gone(old_uid), new_uid: live}
    prepared = prepare_element_observation(list(values), target=case["prepared"].target,
        precondition=ContextPrecondition(document, revision), operation_id=str(uuid4()))
    credentials = SessionCredentials(prepared.target, str(uuid4()), "query-fixture-only")
    payload = {op["id"]: values[op["unique_id"]] for op in prepared.planned.to_ops()}
    response = response_for(prepared, credentials, payload,
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    return parse_element_observation(prepared, json.dumps(response), credentials=credentials,
                                     request_id=response["request_id"])


def test_the_bridge_form_carries_three_fields_and_not_one_more(tmp_path):
    """The bridge rejects an extra key in the row — meaning the shape must be
    narrow."""
    case = scenario(tmp_path)
    book = ledger(case, observation(case, mutate=replaced))
    bridge = book.to_bridge_dict()
    assert bridge["schema"] == IDENTITY_REPLACEMENT_SCHEMA
    assert bridge["replacements"] == [{"superseded_uid": "uid-wall-0",
                                       "superseded_by": NEW_UID,
                                       "reason": "change_type_replacement"}]


def test_a_native_row_travels_end_to_end_into_one_both_agree(tmp_path):
    """🔴 END-TO-END PROBE: native receipt -> identity carrier -> graph
    bridge.

    The 07.09 reconnaissance measurement without this path: `authored_only=1
    + observed_only=1` instead of `both_agree=1`. Here the same case passes
    through all three plots without a single renaming — and yields ONE line.
    """
    from kir.decompile.building_graph import graph_from_l0
    from kir.discrepancy import ObservedRevision, assess_authored_observed_discrepancies
    from kir.tests import test_discrepancy_report as bridge_case

    story = bridge_case.scenario(tmp_path)
    old_uid, new_uid = bridge_case.WALL_UID, bridge_case.WALL_UID + "-replaced"

    # 1. The transaction unit's receipt — a line of its own contract.
    claim = unit_row(old=old_uid, new=new_uid, old_id="900", new_id="1900")

    # 2. The publish observation: the old one is gone, the replacement is
    # there.
    element_observation = two_sided_observation(story, old_uid, new_uid)
    book = assess_identity_replacement(story["project"], story["record"],
        bridge_case.bound(story), element_observation, claims=[claim])

    # 3. The discrepancy bridge receives the ledger DICTIONARY and a graph
    # with the replacement.
    graph = graph_from_l0({"doc_name": "стенд"},
        [bridge_case.wall_row("1001", uid=new_uid, height_mm=3000.0), bridge_case.level_row()],
        document_identity=bridge_case.DOC, federation_context=bridge_case.ROOT)
    report = assess_authored_observed_discrepancies(
        story["project"], story["record"], bridge_case.bound(story), graph,
        ObservedRevision(bridge_case.DOC, bridge_case.STAMP, bridge_case.DIGEST),
        replacements=book.to_bridge_dict()).to_dict()

    row = next(item for item in report["outputs"] if item["output_key"] == "wall-0")
    assert row["state"] == "both_agree"
    assert report["counts"]["authored_only"] == 0 and report["counts"]["observed_only"] == 0
    assert report["observed_only"] == []
