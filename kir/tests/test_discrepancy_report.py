"""The author's revision against the observed graph: five outcomes via red
probes.

Real project/compiler/archive/receipt and a real `graph_from_l0`; the
native response and the L0 lines are synthetic. There is no Revit here,
and there should not be. One probe goes THROUGH A REAL capture on disk
(`write_demo_capture`), so that "observation without Revit" is a fact,
not a promise.
"""
from copy import deepcopy
import json

import pytest

from kir.create_publication import bind_create_receipt
from kir.decompile.building_graph import graph_from_l0
from kir.discrepancy import (
    DiscrepancyError, DiscrepancyReport, ObservedRevision,
    assess_authored_observed_discrepancies,
)
from kir.model.identity import DocumentIdentity, FederationContext
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.tests.test_revit_level_update import make_case
from kir.tests.test_revit_observation import identity


DOC = DocumentIdentity("doc-A")
ROOT = FederationContext("root-A")
WALL_UID = "wall-unique-id-0"
STAMP = "change-stamp-1"
DIGEST = "b" * 64


# ── the author's side ───────────────────────────────────────────────────


def project(*, height_mm=3000, walls=1):
    pid = "authored-observed"
    ref = {"by": "ref", "value": output_id(pid, "section", "level")}
    outputs = {"level": {"op": "create_level", "elev_mm": 0.0, "name": "L1"}}
    for index in range(walls):
        outputs[f"wall-{index}"] = {
            "op": "create_wall", "p0_mm": [index * 5000, 0],
            "p1_mm": [(index + 1) * 5000, 0], "height_mm": height_mm, "level": ref}
    return ProjectRevision(pid, [ModuleDefinition("explicit")],
                           [ModuleInstance("section", "explicit", outputs)])


def scenario(tmp_path, *, height_mm=3000, walls=1, uids=None, refuse=(), omit=()):
    """A publication in which the wall's UniqueId is assigned by the
    PROBE, not guessed by the code."""
    case = make_case(tmp_path, project=project(height_mm=height_mm, walls=walls))
    ids = {}
    for index, output in enumerate(case["record"].project_submission["outputs"]):
        key, oid = output["output_key"], output["output_id"]
        ids[key] = oid
        if key in omit:
            case["result"].pop(oid, None)
            continue
        if key in refuse:
            case["result"][oid] = {"refused": "native operation refused"}
            continue
        uid = (uids or {}).get(key, WALL_UID if key == "wall-0" else "uid-" + key)
        case["result"][oid] = {"id": str(900 + index), **identity(900 + index, uid)}
    case["ids"] = ids
    case["response"]["receipt"]["changes"]["added"] = [
        int(value["id"]) for value in case["result"].values()
        if type(value) is dict and "id" in value]
    return case


def bound(case):
    response = deepcopy(case["response"])
    response["receipt"]["result_json"] = json.dumps(case["result"])
    return bind_create_receipt(case["record"], json.dumps(response),
                               credentials=case["credentials"],
                               request_id=response["request_id"])


# ── the observed side ───────────────────────────────────────────────────


def wall_row(element_id="1001", *, uid=WALL_UID, height_mm=3000.0, params=None):
    return {"element_id": element_id, "category": "OST_Walls", "unique_id": uid,
            "level_id": "1500", "type_id": "1740", "type_name": "Типовой 200",
            "params": {"WALL_USER_HEIGHT_PARAM": height_mm} if params is None else params}


def level_row(element_id="1500", *, uid="uid-level"):
    return {"element_id": element_id, "category": "OST_Levels", "unique_id": uid,
            "params": {}}


def graph(elements, *, context=True):
    kwargs = ({"document_identity": DOC, "federation_context": ROOT} if context else {})
    return graph_from_l0({"doc_name": "стенд"}, elements, **kwargs)


def revision(*, document=DOC, stamp=STAMP, digest=DIGEST):
    return ObservedRevision(document, stamp, digest)


def report(case, observed_graph, observed=None):
    return assess_authored_observed_discrepancies(
        case["project"], case["record"], bound(case), observed_graph,
        observed or revision())


def rows_by_key(payload):
    return {row["output_key"]: row for row in payload["outputs"]}


# ── PROBE 1: the author's 3000 mm wall against the observed 3200 mm ─────


def test_authored_3000_against_observed_3200_is_both_differ(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    payload = report(case, graph([wall_row(height_mm=3200.0), level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_differ"
    assert (row["field"], row["units"]) == ("height_mm", "mm")
    assert (row["authored_value"], row["observed_value"]) == (3000.0, 3200.0)
    # The discrepancy is addressed from BOTH sides and signed by the
    # revision with its fingerprint.
    assert row["output_id"] == case["ids"]["wall-0"]
    assert row["unique_id"] == WALL_UID and row["observed_node_id"] == "1001"
    assert payload["observation"]["change_stamp"] == STAMP
    assert payload["observation"]["l0_sha256"] == DIGEST
    assert payload["authored"]["revision_id"] == case["project"].revision_id
    assert payload["counts"]["both_differ"] == 1


def test_equal_height_is_both_agree_and_names_the_compared_field(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    payload = report(case, graph([wall_row(height_mm=3000.0), level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["field"]) == ("both_agree", "height_mm")
    assert (row["authored_value"], row["observed_value"]) == (3000.0, 3000.0)


# ── PROBE 2: an observed element without an author address ────────────────────


def test_observed_element_without_an_authored_address_is_observed_only(tmp_path):
    case = scenario(tmp_path)
    stranger = wall_row("1002", uid="stranger-uid", height_mm=2500.0)
    payload = report(case, graph([wall_row(), level_row(), stranger])).to_dict()
    strangers = {row["unique_id"]: row for row in payload["observed_only"]}
    assert set(strangers) == {"stranger-uid"}
    row = strangers["stranger-uid"]
    assert (row["state"], row["node_id"], row["category"]) == (
        "observed_only", "1002", "OST_Walls")
    assert row["definition_key"].startswith("kir:definition:v1:")
    assert payload["counts"]["observed_only"] == 1


# ── PROBE 3: an author output without a built element ────────────────────


def test_refused_operation_is_authored_only(tmp_path):
    """The receipt said «отказ» — the absence is PROVEN, not assumed."""
    case = scenario(tmp_path, refuse=("wall-0",))
    payload = report(case, graph([level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "authored_only"
    assert row["diagnostic"] == "operation_refused_no_element_created"
    assert row["unique_id"] is None


def test_qualified_identity_absent_from_a_complete_graph_is_authored_only(tmp_path):
    case = scenario(tmp_path)
    payload = report(case, graph([level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "authored_only"
    assert row["diagnostic"] == "qualified_identity_absent_from_observation"
    assert row["unique_id"] == WALL_UID
    assert payload["census"]["graph_identity_authoritative"] is True


def test_a_missing_receipt_row_is_identity_unknown_not_authored_only(tmp_path):
    """🔴 «Без квитанции» does NOT equal «в модели нет»: there is no address — nothing to prove against."""
    case = scenario(tmp_path, omit=("wall-0",))
    payload = report(case, graph([level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "identity_unknown"
    assert row["publication_state"] == "unavailable"
    assert row["diagnostic"] == "result_row_missing"


# ── PROBE 4: an observation from a different revision ──────────────────────────────────


def test_observation_of_another_document_is_refused_by_name(tmp_path):
    case = scenario(tmp_path)
    observed = graph([wall_row(), level_row()])
    with pytest.raises(DiscrepancyError) as error:
        report(case, observed, revision(document=DocumentIdentity("doc-B")))
    assert error.value.code == "observation_revision_mismatch"


def test_the_same_document_identity_is_accepted(tmp_path):
    case = scenario(tmp_path)
    payload = report(case, graph([wall_row(), level_row()])).to_dict()
    assert payload["observation"]["graph_document_identity"] == DOC.as_dict()
    assert payload["observation"]["document_identity"] == DOC.as_dict()


# ── PROBE 5: an observation without identity context ────────────────────────────


def test_a_graph_without_identity_context_makes_every_row_identity_unknown(tmp_path):
    case = scenario(tmp_path)
    blind = graph([wall_row(height_mm=3200.0), level_row()], context=False)
    payload = report(case, blind).to_dict()
    assert {row["state"] for row in payload["outputs"]} == {"identity_unknown"}
    assert rows_by_key(payload)["wall-0"]["diagnostic"] == "observed_identity_incomplete"
    # The 3000/3200 discrepancy in the snapshot EXISTS, and the report is SILENT about the reason.
    assert payload["counts"]["both_differ"] == 0
    assert payload["counts"]["observed_only"] == 0
    assert payload["census"]["observed_refusals"]["node_identity_incomplete"] == 2
    assert payload["observation"]["identity_gaps"] == {"legacy_context_absent": 2}


# ── census and capture without Revit ────────────────────────────────────────


def test_every_authored_address_gets_a_named_outcome(tmp_path):
    case = scenario(tmp_path, walls=2, uids={"wall-1": "wall-unique-id-1"})
    payload = report(case, graph([wall_row(height_mm=3200.0), level_row()])).to_dict()
    census = payload["census"]
    assert census["authored_addresses"] == census["compared_rows"] + census["excluded_outputs"]
    assert sum(payload["counts"].values()) == len(payload["outputs"]) + len(payload["observed_only"])
    assert (census["observed_nodes"] == census["observed_matched"] + census["observed_only"]
            + sum(census["observed_refusals"].values()))
    # `create_level` is not in the profile of compared fields, and it NAMES this fact.
    assert [row["reason"] for row in payload["excluded_outputs"]] == ["not_in_comparable_field_profile"]


def test_a_real_offline_capture_reaches_the_report(tmp_path):
    """The observation comes from a real capture on disk, without Revit."""
    from kir.decompile.capture_api import write_demo_capture
    from kir.decompile.graph_store import build_graph_for_run

    directory = write_demo_capture(tmp_path / "capture")
    observed = build_graph_for_run(directory, document_identity=DOC, federation_context=ROOT)
    demo_wall_uid = "00000000-0000-0000-0000-000000000001-00000001"
    case = scenario(tmp_path, height_mm=3200, uids={"wall-0": demo_wall_uid})
    # The fingerprint is NOT declared: the `/2` graph is dated on its own, and the report takes it.
    payload = assess_authored_observed_discrepancies(
        case["project"], case["record"], bound(case), observed).to_dict()
    assert payload["observation"]["fingerprint_status"] == "derived"
    assert payload["observation"]["change_stamp"] == "capture-api-demo"
    assert payload["observation"]["l0_sha256"] == observed.observation.l0_sha256
    row = rows_by_key(payload)["wall-0"]
    # The snapshot's demo wall is 3000 mm, the author wrote 3200.
    assert row["state"] == "both_differ"
    assert (row["authored_value"], row["observed_value"]) == (3200.0, 3000.0)
    assert row["unique_id"] == demo_wall_uid
    # The snapshot's floor slab and two doors have no author addresses.
    assert payload["counts"]["observed_only"] == 3


def test_the_report_is_frozen_and_digested(tmp_path):
    case = scenario(tmp_path)
    first = report(case, graph([wall_row(), level_row()]))
    second = report(case, graph([wall_row(), level_row()]))
    assert first.digest == second.digest and len(first.digest) == 64
    with pytest.raises(TypeError):
        DiscrepancyReport()
    payload = first.to_dict()
    payload["outputs"].clear()
    assert first.to_dict()["outputs"], "выданный словарь не является телом отчёта"
