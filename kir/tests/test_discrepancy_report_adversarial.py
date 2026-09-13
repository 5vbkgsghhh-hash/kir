"""Ways to get a false «сошлось» or a false accusation out of the discrepancy report.

Every case here is not a matter of style but a form this house has already paid for: a word
that means two different facts; an absence declared an absence without coverage;
a field checked at a point where it had stopped being the truth.
"""
import pytest

from kir.discrepancy import (
    DiscrepancyError, ObservedRevision, assess_authored_observed_discrepancies,
)
from kir.model.identity import DocumentIdentity
from kir.tests.test_discrepancy_report import (
    ROOT,
    DOC, WALL_UID, bound, graph, level_row, report, revision, rows_by_key,
    scenario, wall_row,
)


def wall(**params):
    return wall_row(params={"WALL_USER_HEIGHT_PARAM": 3200.0, **params})


# ── TOP BOUND TO A LEVEL: THE HEIGHT PARAMETER STOPPED BEING THE TRUTH ────


def test_a_top_constrained_wall_is_unmeasured_not_differing(tmp_path):
    """🔴 65.8% of the corpus's walls are exactly like this. `both_differ` here would be a false accusation."""
    case = scenario(tmp_path, height_mm=3000)
    payload = report(case, graph([wall(WALL_HEIGHT_TYPE="1500"), level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_unmeasured"
    assert row["diagnostic"] == "top_constrained_height_is_not_the_truth"
    # The author's value is named, the observed one is NOT: it was never measured.
    assert (row["authored_value"], row["observed_value"]) == (3000.0, None)
    assert payload["counts"]["both_differ"] == 0


def test_a_top_level_outside_the_snapshot_is_still_not_a_comparison(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    payload = report(case, graph([wall(WALL_HEIGHT_TYPE="9999"), level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["diagnostic"]) == (
        "both_unmeasured", "top_constrained_to_a_level_outside_the_snapshot")


def test_a_wall_block_that_was_never_read_is_not_a_wall_without_a_top(tmp_path):
    """Reading blindness does not turn into a fact about the building (2 801 walls MNVNK)."""
    case = scenario(tmp_path, height_mm=3000)
    blind = wall_row(params={"FLOOR_HEIGHTABOVELEVEL_PARAM": 0})
    payload = report(case, graph([blind, level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["diagnostic"]) == (
        "both_unmeasured", "wall_parameter_block_not_read")


def test_a_row_without_any_parameter_names_its_own_silence(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    payload = report(case, graph([wall_row(params={}), level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["diagnostic"]) == (
        "both_unmeasured", "wall_top_constraint_not_witnessed")


def test_both_agree_never_appears_without_a_named_field(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    for elements in ([wall(WALL_HEIGHT_TYPE="1500"), level_row()],
                     [wall_row(params={}), level_row()],
                     [wall_row(height_mm=3000.0), level_row()]):
        payload = report(case, graph(elements)).to_dict()
        for row in payload["outputs"]:
            assert (row["state"] == "both_agree") == (
                row["field"] is not None and row["observed_value"] is not None)


# ── ABSENCE REQUIRES FULL COVERAGE ──────────────────────────────────


def test_one_unreadable_node_forbids_claiming_absence(tmp_path):
    """One node without a UniqueId — and «не нашли» stops being «в модели нет»."""
    case = scenario(tmp_path)
    nameless = {"element_id": "1777", "category": "OST_Floors", "params": {}}
    payload = report(case, graph([level_row(), nameless])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "identity_unknown"
    assert row["diagnostic"] == "observed_identity_incomplete"
    assert payload["census"]["graph_identity_authoritative"] is False
    assert payload["counts"]["authored_only"] == 0
    assert payload["census"]["observed_refusals"]["node_identity_incomplete"] == 1


def test_the_graph_itself_forbids_a_repeated_unique_id_in_one_document(tmp_path):
    """🔴 The defense stands ONE FLOOR BELOW, and that needs to be known, not duplicated."""
    from kir.decompile.building_graph import GraphBuildError

    twin = wall_row("1002", uid=WALL_UID, height_mm=9999.0)
    with pytest.raises(GraphBuildError, match="occurrence identity"):
        graph([wall_row(), twin, level_row()])


def test_one_definition_under_two_occurrences_removes_both_sides(tmp_path):
    """A form the type ALLOWS: one definition in two placements.

    `graph_from_l0` will not build such a thing — it has one federation context per
    graph — but `BuildingGraph` can also be assembled from a federated payload.
    Picking "the first of the two" would mean flipping a coin over the building.
    """
    from kir.decompile.building_graph import (
        Authority, AuthoritySource, BuildingGraph, Existence, GraphCensus, GraphNode,
    )
    from kir.model.identity import DefinitionIdentity, IdentityStatus, OccurrenceIdentity

    definition = DefinitionIdentity(DOC, WALL_UID)
    nodes = [GraphNode(node_id=node_id, category="OST_Walls",
                       authority=Authority.DECLARED,
                       authority_source=AuthoritySource.L0_ELEMENT,
                       existence=Existence.MATERIALIZED,
                       definition_identity=definition,
                       occurrence_identity=OccurrenceIdentity("root-A", chain, definition),
                       identity_status=IdentityStatus.AUTHORITATIVE, identity_gaps=())
             for node_id, chain in (("1001", ()), ("1002", ("link-1",)))]
    federated = BuildingGraph(
        doc_name="стенд", nodes=nodes, edges=(),
        census=GraphCensus(rows_seen=2, nodes=2, refusals={},
                           identity_authoritative_nodes=2, identity_incomplete_nodes=0,
                           identity_gaps={}, identity_context_authoritative=True),
        document_identity=DOC, federation_context=ROOT)
    case = scenario(tmp_path)
    payload = report(case, federated).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["diagnostic"]) == (
        "identity_unknown", "observed_identity_ambiguous")
    census = payload["census"]
    assert census["observed_refusals"]["observed_identity_ambiguous"] == 2
    assert (census["observed_nodes"] == census["observed_matched"] + census["observed_only"]
            + sum(census["observed_refusals"].values()))


def test_two_outputs_claiming_one_native_element_stay_unknown(tmp_path):
    case = scenario(tmp_path, walls=2, uids={"wall-0": WALL_UID, "wall-1": WALL_UID})
    payload = report(case, graph([wall_row(), level_row()])).to_dict()
    states = {key: row["state"] for key, row in rows_by_key(payload).items()}
    assert states == {"wall-0": "identity_unknown", "wall-1": "identity_unknown"}
    assert {row["publication_state"] for row in payload["outputs"]} == {"conflict"}


# ── MATCHED, BUT IT IS A DIFFERENT THING ─────────────────────────────────


def test_an_identity_landing_on_another_kind_is_named_by_field(tmp_path):
    case = scenario(tmp_path)
    door = {"element_id": "1001", "category": "OST_Doors", "unique_id": WALL_UID,
            "params": {"FAMILY_HEIGHT_PARAM": 2134.0}}
    payload = report(case, graph([door, level_row()])).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_differ"
    assert row["diagnostic"] == "observed_category_contradicts_source"
    assert (row["field"], row["units"]) == ("category", None)
    assert (row["authored_value"], row["observed_value"]) == ("OST_Walls", "OST_Doors")


# ── FINGERPRINT OF THE OBSERVATION ─────────────────────────────────────────────────


@pytest.mark.parametrize("stamp,digest,code", [
    ("", "b" * 64, "observation_change_stamp_required"),
    ("   ", "b" * 64, "observation_change_stamp_required"),
    ("stamp", "b" * 63, "observation_snapshot_digest_required"),
    ("stamp", "B" * 64, "observation_snapshot_digest_required"),
    ("stamp", "z" * 64, "observation_snapshot_digest_required"),
])
def test_a_malformed_observation_fingerprint_is_refused_by_name(stamp, digest, code):
    with pytest.raises(DiscrepancyError) as error:
        ObservedRevision(DOC, stamp, digest)
    assert error.value.code == code


def test_an_untyped_document_identity_is_refused():
    with pytest.raises(DiscrepancyError) as error:
        ObservedRevision("doc-A", "stamp", "b" * 64)
    assert error.value.code == "typed_observed_revision_required"


def test_a_graph_without_identity_context_cannot_contradict_the_fingerprint(tmp_path):
    """The graph has no identity — so there is nothing to prove a discrepancy against."""
    case = scenario(tmp_path)
    blind = graph([wall_row(), level_row()], context=False)
    payload = report(case, blind, revision(document=DocumentIdentity("doc-B"))).to_dict()
    assert payload["observation"]["graph_document_identity"] is None
    assert {row["state"] for row in payload["outputs"]} == {"identity_unknown"}


# ── INPUT TYPES ──────────────────────────────────────────────────────────


def test_untyped_inputs_are_refused_before_any_work(tmp_path):
    case = scenario(tmp_path)
    good = (case["project"], case["record"], bound(case),
            graph([wall_row(), level_row()]), revision())
    for index, wrong in enumerate(({"revision_id": "x"}, "record", "receipt",
                                   {"nodes": {}}, {"change_stamp": "x"})):
        args = list(good)
        args[index] = wrong
        with pytest.raises(DiscrepancyError) as error:
            assess_authored_observed_discrepancies(*args)
        assert error.value.code == "typed_discrepancy_inputs_required"


def test_a_serialized_report_is_not_an_observation(tmp_path):
    case = scenario(tmp_path)
    payload = report(case, graph([wall_row(), level_row()])).to_dict()
    assert payload["claims"]["current_model_state"] == "not_established"
    assert payload["claims"]["observation_revision"] == (
        "declared_by_caller_not_derived_from_the_graph")
    assert payload["claims"]["observation_to_publication_document_binding"] == "not_established"
    assert payload["claims"]["absence_claim"] == "requires_fully_authoritative_graph_identity"
