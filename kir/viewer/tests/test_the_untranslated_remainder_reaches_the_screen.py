"""THE UNTRANSLATED REMAINDER AND ACCEPTED DECISIONS REACH THE SCREEN.

🔴 WHY THIS WAS INTRODUCED (07.09.2026). The owner's word: "explicitly
show untranslated remainders and accepted decisions." By this day the
numbers for the display already exist — `kir/refine/deviation.py` and
`refine_after_source_change` give the remainder, three sets, and
questions — but there is no display for them at all: the `/3` artifact
carries surfaces, proxies and clash findings, and NOT A SINGLE line
about what the translation failed to translate. Exactly the gap
acceptance found on 06.09 with findings: the carrier is built, there is
no call, and "displayed 0" holds not because of a breakage but because
of a missing step.

WHAT IS GUARDED, AND WHY EXACTLY THIS.

1. THE COUNT IS TAKEN BEFORE ADDRESS TRANSLATION. The sum of the three
   sets equals ALL of the instance's outputs, and part of the outputs
   (types) lives in a different instance and has no address in the
   scene. Counting after translation would mean silently losing the
   equality.
2. EMPTINESS IS NAMED. "There is no remainder" and "the fix was never
   introduced" look like the same empty list; the cause must sit in a
   string.
3. A NUMBER WITHOUT A UNIT IS NOT SHOWN. `−5 000 000` without a unit
   name means nothing, but looks like knowledge.
4. CLOSED LISTS ARE EQUAL IN BOTH LANGUAGES. If they silently diverge,
   there are two dictionaries.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from kir.viewer import standalone, standalone_export as export
from kir.viewer.refinement_display import (REFINEMENT_CAPABILITY, REFINEMENT_CLAIMS,
                                           REFINEMENT_RECORD_SCHEMA, SET_NAMES,
                                           RefinementDisplayRefusal, display_refinement)

KNOWN = ("p1/a", "p1/b", "p1/c")


def report(**over):
    base = {"revision_before": "r0", "revision_after": None, "source_output_id": "p1/concept",
            "recomputed": ["p1/a"], "preserved": ["p1/b"], "needs_decision": ["p1/c"],
            "residue": [{"address": "p1/concept", "what": "concept_twist_removed", "count": 1}],
            "deviation": {"measure": "plan_area_delta_mm2", "value": [-5_000_000.0], "unit": "mm2"},
            "lineage": {}, "decisions_digest": "d0",
            "questions": [{"question_id": "q1", "address": "p1/c",
                           "choices": ["keep_wall_and_shrink_atrium", "split_wall_around_the_opening"],
                           "why": "новый контур пересекает ось стены"}],
            "analysis_limits": []}
    base.update(over)
    return base


def test_the_three_sets_are_counted_before_the_addresses_are_translated():
    """Types live in a different instance: the scene does not address
    them, and the count must still add up."""
    shown = display_refinement(report(preserved=["p1/b", "p1/type-library-wall"]), KNOWN)
    counts = shown["refinement"]["counts"]
    assert counts == {"recomputed": 1, "preserved": 2, "needs_decision": 1,
                      "total": 4, "unaddressed": 1}
    assert shown["refinement"]["preserved"] == ["p1/b"], "непоказуемый адрес не рисуется"
    assert any("не адресуемые этой сценой (1)" in line for line in shown["analysis_limits"]), (
        "непоказанный выход обязан быть НАЗВАН, иначе он исчезает молча")


def test_an_address_is_translated_by_the_map_not_by_string_surgery():
    shown = display_refinement(report(recomputed=["out-1"]), KNOWN,
                               address_map={"out-1": "p1/a"})
    assert shown["refinement"]["recomputed"] == ["p1/a"]
    assert shown["refinement"]["counts"]["unaddressed"] == 0


def test_the_residue_keeps_its_source_address_even_outside_the_scene():
    """The remainder is addressed by its SOURCE; discarding it for that
    reason would hide the subject."""
    shown = display_refinement(report(), KNOWN)
    assert shown["refinement"]["residue"] == [
        {"address": "p1/concept", "what": "concept_twist_removed",
         "count": 1, "volume_mm3": None}]
    assert any("адрес исходной части не показан этой сценой" in line
               for line in shown["analysis_limits"])


def test_a_number_without_a_named_method_is_flagged_not_hidden():
    shown = display_refinement(report(), KNOWN)
    assert shown["refinement"]["deviation"] == {
        "measure": "plan_area_delta_mm2", "value": [-5_000_000.0], "unit": "mm2", "method": None}
    assert any("метод меры plan_area_delta_mm2 не назван" in line
               for line in shown["analysis_limits"])


def test_a_number_without_a_measure_is_refused():
    with pytest.raises(RefinementDisplayRefusal):
        display_refinement(report(deviation={"value": [1.0]}), KNOWN)


def test_the_three_sets_may_not_overlap():
    with pytest.raises(RefinementDisplayRefusal):
        display_refinement(report(preserved=["p1/a"]), KNOWN)


def test_a_question_without_choices_is_not_a_question():
    with pytest.raises(RefinementDisplayRefusal):
        display_refinement(report(questions=[{"question_id": "q", "address": "p1/c",
                                              "choices": [], "why": "x"}]), KNOWN)


def test_a_repeated_question_id_is_refused():
    row = {"question_id": "q1", "address": "p1/c", "choices": ["a"], "why": "x"}
    with pytest.raises(RefinementDisplayRefusal):
        display_refinement(report(questions=[row, dict(row)]), KNOWN)


def test_the_record_field_set_is_closed():
    record = display_refinement(report(), KNOWN)["refinement"]
    assert sorted(record) == sorted(
        ["schema", "source_display_id", "revision_before", "revision_after", "recomputed",
         "preserved", "needs_decision", "counts", "residue", "deviation", "decisions_digest"])
    assert record["schema"] == REFINEMENT_RECORD_SCHEMA


def test_a_typed_report_object_is_accepted_as_well_as_its_dict():
    class Typed:
        def to_dict(self):
            return report()

    assert display_refinement(Typed(), KNOWN)["refinement"]["counts"]["total"] == 3


# ─────────────────────────────────────────── mirror of the closed lists in JS


#: 🔴 13.09.2026. Four checks stood here: the capability name, the claims, the
#: set names and the record schema had to be THE SAME STRINGS in Python and in
#: `frontend/standalone/src/scene-reader.js`, so the two halves of one screen
#: could not drift apart. The browser window was removed by the owner's word and
#: the JS half went with it; there is no second language left to agree with. The
#: Python side of every one of those constants is still checked above, by the
#: tests that read `REFINEMENT_CAPABILITY`, `REFINEMENT_CLAIMS`, `SET_NAMES` and
#: `REFINEMENT_RECORD_SCHEMA` through the report they produce.


@pytest.fixture(scope="module")
def saved_with_a_pending_change(tmp_path_factory):
    """The same chain as mission-2 acceptance: concept -> section ->
    types -> fix C."""
    pytest.importorskip("shapely", reason="оси стен решает shapely, а не глаз")
    from examples.residential_project import concept
    from examples.residential_refinement import develop_section
    from examples.residential_typed_section import add_section_types
    from kir.project import output_id
    from kir.project_refinement import record_pending_change
    from kir.project_store import ProjectStore
    from kir.tests.fixtures import GROUND_SNAPSHOT as G

    source = concept()
    base = develop_section(source, height_mm=4200.0, setback_mm=1800.0)
    detailed = add_section_types(
        base, source=source, expected_revision=base.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id", "value": G["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id", "value": G["floor_types"][0]["id"]})
    path = tmp_path_factory.mktemp("refinement") / "scene.sqlite"
    store = ProjectStore.create(path, source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    #: Fix C of mission-2 acceptance: the atrium void carried through to the wall.
    change = {"kind": "atrium_contour", "hole_mm": [[4500.0, 2500.0], [7500.0, 9500.0]],
              "why": "контур атриума доведён до стены: часть решений неоднозначна"}
    record_pending_change(store, store.head(),
                          source_output_id=output_id(source.project_id, "tower-a",
                                                     "concept-volume"),
                          change=change)
    return store


def test_without_the_capability_nothing_of_the_remainder_is_shown(saved_with_a_pending_change):
    """RED: the same turn without the capability. Zero shown — and that
    IS the previous tree."""
    artifact, _ = export.export_saved_project_scene(saved_with_a_pending_change,
                                                   exact=False, refinement=None)
    data = artifact.to_dict()
    assert data["schema"] == export.DISPLAY_SCHEMA_V3
    assert "refinement" not in data and "refinement_questions" not in data
    assert REFINEMENT_CAPABILITY not in data["consumer_contract"]["declared_capabilities"]


def test_with_the_capability_the_remainder_and_the_questions_reach_the_artifact(
        saved_with_a_pending_change):
    """GREEN: a remainder of 3 lines, 3 questions, and the three sets
    cover all 23 outputs."""
    artifact, _ = export.export_saved_project_scene(saved_with_a_pending_change,
                                                   exact=False, refinement="auto")
    data = artifact.to_dict()
    assert data["schema"] == export.DISPLAY_SCHEMA_V4
    assert REFINEMENT_CAPABILITY in data["consumer_contract"]["declared_capabilities"]
    record = data["refinement"]
    assert len(record["residue"]) == 3, (
        "две объявленные потери и один неактивный параметр — это и есть остаток")
    assert sorted(row["what"] for row in record["residue"]) == [
        "concept_top_taper_removed", "concept_twist_removed", "inactive_parameter:twist_deg"]
    assert len(data["refinement_questions"]) == 3, "правка C задевает три оси стен"
    counts = record["counts"]
    assert counts["recomputed"] + counts["preserved"] + counts["needs_decision"] == counts["total"]
    assert counts["total"] == 23 and counts["needs_decision"] == 3
    assert {q["address"] for q in data["refinement_questions"]} <= set(record["needs_decision"])
    for question in data["refinement_questions"]:
        assert question["choices"] and len(question["choices"]) == len(set(question["choices"]))


def test_the_artifact_survives_its_own_loader(saved_with_a_pending_change):
    artifact, _ = export.export_saved_project_scene(saved_with_a_pending_change,
                                                   exact=False, refinement="auto")
    validated = standalone.load_display_artifact(artifact.dumps().encode("utf-8"))
    assert validated.transport["schema"] == standalone.TRANSPORT_SCHEMA_V4
    assert validated.data["refinement_claims"] == dict(REFINEMENT_CLAIMS)


def test_an_edited_artifact_is_refused_by_the_loader(saved_with_a_pending_change):
    """Three fakes: a sum of counters, an intersection of sets, a
    number without a unit."""
    artifact, _ = export.export_saved_project_scene(saved_with_a_pending_change,
                                                   exact=False, refinement="auto")
    for mutate in (
            lambda d: d["refinement"]["counts"].update(total=99),
            lambda d: d["refinement"]["preserved"].append(d["refinement"]["recomputed"][0]),
            lambda d: d["refinement"]["deviation"].update(measure=None, value=[1.0]),
            lambda d: d["refinement_questions"][0].update(choices=[]),
            lambda d: d["refinement_claims"].update(roles_and_losses="proven")):
        data = json.loads(artifact.dumps())
        mutate(data)
        from kir.project import _hash
        data["artifact_digest"] = _hash({k: v for k, v in data.items() if k != "artifact_digest"})
        with pytest.raises(standalone.DisplayInputRefusal):
            standalone.load_display_artifact(json.dumps(data).encode("utf-8"))


def test_a_store_without_a_pending_change_says_so_instead_of_showing_zero(tmp_path):
    """«There is no remainder» and «the fix was never introduced» must
    be DISTINGUISHABLE."""
    report_row, reason = export.saved_refinement_report(
        _store_without_change(tmp_path))
    assert report_row is None
    assert "правка источника не заведена" in reason


def _store_without_change(tmp_path):
    from examples.residential_project import concept
    from kir.project_store import ProjectStore

    source = concept()
    return ProjectStore.create(tmp_path / "plain.sqlite", source)


def test_the_private_seam_to_the_pending_change_is_pinned():
    """C2's fix key is private; a rename must break LOUDLY.

    There is no public name next door that reports "which fix was
    introduced": `open_questions` returns only the questions. As long
    as the name is private, this pin is the only thing that tells a
    rename apart from a silent zero on screen.
    """
    from kir import project_refinement

    assert hasattr(project_refinement, "_PENDING_KEY")
    assert project_refinement._PENDING_KEY == "pending_source_change"
