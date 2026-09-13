"""The report takes its date from the graph, and an identity swap stops
being a pair of discrepancies.

A continuation of `test_discrepancy_report.py`: the same real
project/archive/receipt and the same real `graph_from_l0`, but the graph
is now DATED ITSELF.
"""
from pathlib import Path

import pytest

from kir.decompile.building_graph import ObservationFingerprint, graph_from_l0
from kir.discrepancy import (
    IDENTITY_REPLACEMENT_SCHEMA, OBSERVATION_FINGERPRINT_ABSENT,
    DiscrepancyError, ObservedRevision, assess_authored_observed_discrepancies,
)
from kir.model.identity import DocumentIdentity
from kir.tests.test_discrepancy_report import (
    DOC, ROOT, WALL_UID, bound, level_row, rows_by_key, scenario, wall_row,
)


STAMP = "observed-stamp-1"
SNAPSHOT = "d" * 64


def dated(elements, *, stamp=STAMP, digest=SNAPSHOT, context=True):
    kwargs = ({"document_identity": DOC, "federation_context": ROOT} if context else {})
    return graph_from_l0({"doc_name": "стенд"}, elements,
                         observation=ObservationFingerprint(stamp, digest), **kwargs)


def undated(elements, *, context=True):
    kwargs = ({"document_identity": DOC, "federation_context": ROOT} if context else {})
    return graph_from_l0({"doc_name": "стенд"}, elements, **kwargs)


def assess(case, graph, observed=None, **kwargs):
    return assess_authored_observed_discrepancies(
        case["project"], case["record"], bound(case), graph, observed, **kwargs)


# ── THE FINGERPRINT IS TAKEN FROM THE GRAPH ─────────────────────────────


def test_the_report_takes_the_date_from_the_graph(tmp_path):
    case = scenario(tmp_path)
    payload = assess(case, dated([wall_row(), level_row()])).to_dict()
    observation = payload["observation"]
    assert observation["fingerprint_status"] == "derived"
    assert (observation["change_stamp"], observation["l0_sha256"]) == (STAMP, SNAPSHOT)
    assert observation["diagnostic"] is None
    assert observation["document_identity"] == DOC.as_dict()


def test_an_undated_graph_names_its_missing_fingerprint(tmp_path):
    """🔴 Artifact `/1` lands here whole: there is nothing to invent a
    date from for it."""
    case = scenario(tmp_path)
    payload = assess(case, undated([wall_row(height_mm=3200.0), level_row()])).to_dict()
    observation = payload["observation"]
    assert observation["fingerprint_status"] == "absent"
    assert observation["diagnostic"] == OBSERVATION_FINGERPRINT_ABSENT
    assert (observation["change_stamp"], observation["l0_sha256"]) == (None, None)
    # The report still HAPPENED: an undated observation doesn't mean an
    # incorrect one.
    assert rows_by_key(payload)["wall-0"]["state"] == "both_differ"


def test_a_declaration_contradicting_the_measurement_is_refused(tmp_path):
    case = scenario(tmp_path)
    with pytest.raises(DiscrepancyError) as error:
        assess(case, dated([wall_row(), level_row()]),
               ObservedRevision(DOC, "another-stamp", SNAPSHOT))
    assert error.value.code == "observation_revision_mismatch"


def test_a_declaration_agreeing_with_the_measurement_is_still_derived(tmp_path):
    case = scenario(tmp_path)
    payload = assess(case, dated([wall_row(), level_row()]),
                     ObservedRevision(DOC, STAMP, SNAPSHOT)).to_dict()
    assert payload["observation"]["fingerprint_status"] == "derived"


def test_a_declaration_over_an_undated_graph_is_named_declared(tmp_path):
    """A claim remains a legitimate input — but it IS NAMED a claim."""
    case = scenario(tmp_path)
    payload = assess(case, undated([wall_row(), level_row()]),
                     ObservedRevision(DOC, STAMP, SNAPSHOT)).to_dict()
    assert payload["observation"]["fingerprint_status"] == "declared"
    assert payload["observation"]["diagnostic"] is None


# ── THE SUBSTITUTION LEDGER ─────────────────────────────────────────────


def ledger(*pairs):
    return {"schema": IDENTITY_REPLACEMENT_SCHEMA,
            "replacements": [{"superseded_uid": old, "superseded_by": new,
                              "reason": "republished"} for old, new in pairs]}


NEW_UID = "wall-unique-id-0-republished"


def test_without_the_ledger_a_replacement_looks_like_two_discrepancies(tmp_path):
    """A control: exactly the false accusation the ledger was set up to remove."""
    case = scenario(tmp_path)
    payload = assess(case, dated([wall_row(uid=NEW_UID), level_row()])).to_dict()
    assert rows_by_key(payload)["wall-0"]["state"] == "authored_only"
    assert [row["unique_id"] for row in payload["observed_only"]] == [NEW_UID]
    assert payload["counts"]["authored_only"] == payload["counts"]["observed_only"] == 1


def test_the_ledger_turns_the_pair_into_one_agreeing_row(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    payload = assess(case, dated([wall_row(uid=NEW_UID, height_mm=3000.0), level_row()]),
                     replacements=ledger((WALL_UID, NEW_UID))).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_agree"
    assert (row["unique_id"], row["resolved_unique_id"]) == (WALL_UID, NEW_UID)
    assert row["superseded"] is True
    assert payload["observed_only"] == []
    assert payload["counts"]["authored_only"] == payload["counts"]["observed_only"] == 0
    assert payload["observation"]["identity_replacements"] == 1


def test_a_replacement_does_not_hide_a_real_difference(tmp_path):
    """A substitution carries over the ADDRESS, not agreement: 3000
    against 3200 still stands."""
    case = scenario(tmp_path, height_mm=3000)
    payload = assess(case, dated([wall_row(uid=NEW_UID, height_mm=3200.0), level_row()]),
                     replacements=ledger((WALL_UID, NEW_UID))).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_differ"
    assert (row["authored_value"], row["observed_value"]) == (3000.0, 3200.0)


def test_a_chain_resolves_to_its_last_link(tmp_path):
    case = scenario(tmp_path, height_mm=3000)
    third = "wall-unique-id-0-third"
    payload = assess(case, dated([wall_row(uid=third, height_mm=3000.0), level_row()]),
                     replacements=ledger((WALL_UID, NEW_UID), (NEW_UID, third))).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert (row["state"], row["resolved_unique_id"]) == ("both_agree", third)


@pytest.mark.parametrize("payload,code", [
    (ledger((WALL_UID, NEW_UID), (NEW_UID, WALL_UID)), "identity_replacement_cycle"),
    ({"schema": IDENTITY_REPLACEMENT_SCHEMA, "replacements": [
        {"superseded_uid": WALL_UID, "superseded_by": "a"},
        {"superseded_uid": WALL_UID, "superseded_by": "b"}]},
     "identity_replacement_forks"),
    (ledger((WALL_UID, WALL_UID)), "identity_replacement_self"),
    ({"schema": "kir-create-identity-replacement/9", "replacements": []},
     "unsupported_identity_replacement_schema"),
    ({"schema": IDENTITY_REPLACEMENT_SCHEMA, "replacements": {}},
     "invalid_identity_replacement_ledger"),
    ({"schema": IDENTITY_REPLACEMENT_SCHEMA, "replacements": [
        {"superseded_uid": WALL_UID, "superseded_by": NEW_UID, "extra": 1}]},
     "invalid_identity_replacement_ledger"),
    ({"schema": IDENTITY_REPLACEMENT_SCHEMA, "replacements": [
        {"superseded_uid": WALL_UID, "superseded_by": "  "}]},
     "invalid_identity_replacement_ledger"),
])
def test_an_ambiguous_ledger_refuses_by_name(tmp_path, payload, code):
    """A bridge that picks between two answers is a coin flip, not a bridge."""
    case = scenario(tmp_path)
    with pytest.raises(DiscrepancyError) as error:
        assess(case, dated([wall_row(), level_row()]), replacements=payload)
    assert error.value.code == code


def test_no_ledger_is_not_an_empty_ledger_in_the_report(tmp_path):
    case = scenario(tmp_path)
    payload = assess(case, dated([wall_row(), level_row()])).to_dict()
    assert payload["observation"]["identity_replacements"] == 0
    assert rows_by_key(payload)["wall-0"]["superseded"] is False


# ── THE `not_established` CAUSE IS MECHANICAL, AND BOTH PRODUCERS READ IT ──


def test_the_two_document_keys_are_different_kinds_by_construction(tmp_path):
    """🔴 Linking the observation to the publication's `document_key` is
    not "not done yet."

    The publication key is born fresh from the runtime ON EVERY LAUNCH of
    the add-in; the snapshot's document identity survives a restart.
    Neither is derivable from the other, and `not_established` must point
    to this, not to our own laziness.
    """
    from kir.decompile import extract

    # The producer for the observed side lives in the package and is read
    # directly.
    source = Path(extract.__file__).read_text(encoding="utf-8")
    assert 'f"revit:{source}:{identity_value}"' in source

    payload = assess(tmp := scenario(tmp_path), dated([wall_row(), level_row()])).to_dict()
    assert tmp is not None
    claims = payload["claims"]
    assert claims["observation_to_publication_document_binding"] == "not_established"
    assert "per-session runtime handle" in claims[
        "observation_to_publication_document_binding_reason"]


def test_the_publication_side_key_is_a_per_session_handle():
    """The second half of the measurement — at the publication key's
    producer.

    The runtime file lives outside the wheel, so its absence is a NAMED
    skip, not a green pass: a guard with no subject must be
    distinguishable from a guard with no findings.
    """
    tracker = (Path(__file__).resolve().parents[2] / "connector" / "revit" / "src"
               / "Kir.Revit.Connector" / "Context" / "DocumentRevisionTracker.cs")
    if not tracker.is_file():
        pytest.skip(f"производителя ключа публикации нет рядом: {tracker}")
    text = tracker.read_text(encoding="utf-8")
    assert 'Guid.NewGuid().ToString("N")' in text
    # The wording is carried across the comment's lines — both halves are
    # checked.
    assert "not a file or a persisted" in text and "BIM identity" in text


# ── CONVERGENCE WITH THE IDENTITY CARRIER ───────────────────────────────


def _identity_scene(tmp_path):
    """A neighboring holding's scene, taken WHOLE: its project, its
    receipt, its ledger.

    🔴 A FOREIGN SCENE WAS TAKEN, NOT A LOOKALIKE OF OUR OWN. Our own scene
    would only prove that our own consumer agrees with itself; convergence
    is when a ledger, assembled by SOMEONE ELSE's code from SOMEONE ELSE's
    confirmation, is accepted by our bridge without a single change of
    shape along the way.
    """
    from kir.tests.test_create_type_discrepancy import bind, observation, scenario
    from kir.tests.test_identity_replacement_after_change_type import (
        NEW_UID, ledger, replaced,
    )

    case = scenario(tmp_path)
    book = ledger(case, observation(case, mutate=replaced))
    return case, bind(case), book, NEW_UID


def test_a_ledger_built_by_identity_passes_through_this_report(tmp_path):
    case, receipt, book, new_uid = _identity_scene(tmp_path)
    graph = dated([wall_row(uid=new_uid, height_mm=3000.0)])
    payload = assess_authored_observed_discrepancies(
        case["project"], case["record"], receipt, graph, replacements=book).to_dict()
    row = rows_by_key(payload)["wall-0"]
    assert row["state"] == "both_agree"
    assert (row["unique_id"], row["resolved_unique_id"]) == ("uid-wall-0", new_uid)
    assert row["superseded"] is True
    assert payload["observation"]["identity_replacement_source"] == "confirmed_ledger"
    assert payload["observed_only"] == []


def test_without_that_ledger_the_same_scene_splits_into_a_pair(tmp_path):
    """A control: without the ledger, the same scene prints two discrepancies."""
    case, receipt, _book, new_uid = _identity_scene(tmp_path)
    graph = dated([wall_row(uid=new_uid, height_mm=3000.0)])
    payload = assess_authored_observed_discrepancies(
        case["project"], case["record"], receipt, graph).to_dict()
    assert rows_by_key(payload)["wall-0"]["state"] == "authored_only"
    assert [row["unique_id"] for row in payload["observed_only"]] == [new_uid]
    assert payload["observation"]["identity_replacement_source"] is None


def test_my_resolution_agrees_with_the_ledgers_own(tmp_path):
    """Two independent passes over one chain must produce a single address."""
    from kir.discrepancy import _resolve_replacements

    case, _receipt, book, new_uid = _identity_scene(tmp_path)
    assert _resolve_replacements(book) == {"uid-wall-0": new_uid}
    assert book.effective_unique_id("uid-wall-0") == new_uid
    # And an unfamiliar uid stays itself for both, rather than
    # disappearing.
    assert book.effective_unique_id("uid-wall-type") == "uid-wall-type"
    assert "uid-wall-type" not in _resolve_replacements(book)


class _Forked:
    """An impostor ledger: the same pair of capabilities, a forked line.

    The identity carrier itself would never assemble one like this — it
    rejects a fork at assembly. But the bridge's strictness has no right
    to lean on SOMEONE ELSE's check: anyone can forge two capabilities,
    and the report must refuse on its own.
    """

    replacements = [
        {"original_identity": {"unique_id": "uid-wall-0"}, "superseded_by": "a"},
        {"original_identity": {"unique_id": "uid-wall-0"}, "superseded_by": "b"},
    ]

    def effective_unique_id(self, unique_id):
        return unique_id


@pytest.mark.parametrize("rows,code", [
    (_Forked.replacements, "identity_replacement_forks"),
    ([{"original_identity": {"unique_id": "x"}, "superseded_by": "y"},
      {"original_identity": {"unique_id": "y"}, "superseded_by": "x"}],
     "identity_replacement_cycle"),
    ([{"original_identity": {"unique_id": "x"}, "superseded_by": "x"}],
     "identity_replacement_self"),
    ([{"original_identity": "not a mapping", "superseded_by": "y"}],
     "invalid_identity_replacement_ledger"),
    ([{"original_identity": {"unique_id": "x"}, "superseded_by": "  "}],
     "invalid_identity_replacement_ledger"),
])
def test_a_ledger_shaped_object_gets_the_very_same_refusals(tmp_path, rows, code):
    book = _Forked()
    book.replacements = rows
    case = scenario(tmp_path)
    with pytest.raises(DiscrepancyError) as error:
        assess(case, dated([wall_row(), level_row()]), replacements=book)
    assert error.value.code == code
