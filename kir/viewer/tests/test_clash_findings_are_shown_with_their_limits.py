"""Display of analysis findings: "0 findings" stopped being the only
answer.

Reconnaissance 06.09.2026: in the frontend the word `clash` occurred 5
times, and ALL five were negations; `scene.py:BLIND_SPOTS` wrote "clashes
are not searched for or shown here". This file guards the opposite — and
guards, alongside it, the thing without which the display would be worse
than no display at all: the list of analysis limitations.
"""
from __future__ import annotations

import json

import pytest

from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision
from kir.viewer import standalone, standalone_export as export
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.clash_findings import (CLASH_CAPABILITY, CLASH_CLAIMS, ClashDisplayRefusal,
                                       display_clash_findings)
from kir.viewer.reference_surfaces import SURFACE_CAPABILITY


def wall(ident, x0, x1):
    return {"op": "create_wall", "id": ident, "p0_mm": [x0, 0], "p1_mm": [x1, 0],
            "height_mm": 3000, "level": {"by": "name", "value": "L"}}


@pytest.fixture(scope="module")
def materialized():
    ops = [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "L"},
           wall("W1", 0, 6000), wall("W2", 3000, 9000)]
    outputs = [NamedOutput(f"out-{i}", {k: v for k, v in op.items() if k != "id"})
               for i, op in enumerate(ops)]
    project = ProjectRevision("clash-display", [ModuleDefinition("m")],
                              [ModuleInstance("i", "m", outputs)])
    return materialize_project(project, {})


def ids_of(materialized):
    """Display addresses are taken from the export itself, not assembled by
    hand."""
    plain = export.export_standalone_scene(materialized, consumer_capabilities=())
    return [row["display_id"] for row in plain.to_dict()["source"]["operations"]]


def finding(a, b, **over):
    row = {"finding_id": "F1", "display_id_a": a, "display_id_b": b,
           "status": "confirmed", "relation": "intersect", "depth_mm": 500.0,
           "overlap_volume_mm3": 3.8e10, "gap_mm": None,
           "hull_source_a": "brep", "hull_source_b": "brep", "refusal_ru": None}
    row.update(over)
    return row


def export_with(materialized, report, *, caps=(CLASH_CAPABILITY,)):
    return export.export_standalone_scene(materialized, consumer_capabilities=caps,
                                          clash_report=report)


# ───────────────────────────────────────────────── the display appeared

def test_a_finding_reaches_the_artifact_with_its_pair_number_and_status(materialized):
    a, b = ids_of(materialized)[1:3]
    artifact = export_with(materialized, {"findings": [finding(a, b)],
                                          "analysis_limits": ["проверено 1 из 1"]})
    data = artifact.to_dict()
    assert data["schema"] == export.DISPLAY_SCHEMA_V3
    row, = data["clash_findings"]
    assert (row["display_id_a"], row["display_id_b"]) == (a, b)
    assert row["status"] == "confirmed" and row["relation"] == "intersect"
    assert row["depth_mm"] == 500.0 and row["overlap_volume_mm3"] == 3.8e10
    assert row["hull_source_a"] == row["hull_source_b"] == "brep"
    assert data["clash_analysis_limits"] == ["проверено 1 из 1"]
    assert data["clash_claims"] == dict(CLASH_CLAIMS)
    # The loader accepts its own artifact and declares the /3 transport.
    loaded = standalone.load_display_artifact(artifact.dumps().encode())
    assert loaded.transport["schema"] == standalone.TRANSPORT_SCHEMA_V3


def test_zero_findings_and_no_analysis_are_different_answers(materialized):
    """"No findings" and "findings are not shown" must be distinguishable."""
    silent = export.export_standalone_scene(materialized, consumer_capabilities=())
    assert "clash_findings" not in silent.to_dict()
    assert silent.to_dict()["schema"] == export.DISPLAY_SCHEMA
    empty = export_with(materialized, {"findings": [], "analysis_limits": ["поиск неполон: тел 0"]})
    data = empty.to_dict()
    assert data["clash_findings"] == [] and data["clash_analysis_limits"] == ["поиск неполон: тел 0"]
    assert CLASH_CAPABILITY in data["consumer_contract"]["required_proxy_capabilities"]


def test_limits_travel_with_the_findings_and_are_not_optional(materialized):
    a, b = ids_of(materialized)[1:3]
    artifact = export_with(materialized, {"findings": [finding(a, b)]})
    assert artifact.to_dict()["clash_analysis_limits"] == []
    # A limitation coming from the analysis travels through verbatim.
    artifact = export_with(materialized, {"findings": [finding(a, b)],
                                          "analysis_limits": ["exact_budget_exhausted: не проверено 4"]})
    assert artifact.to_dict()["clash_analysis_limits"] == ["exact_budget_exhausted: не проверено 4"]


# ───────────────────────────────────────────── the capability and its absence

def test_a_report_without_the_capability_is_refused_not_dropped(materialized):
    with pytest.raises(export.StandaloneExportRefusal) as refusal:
        export.export_standalone_scene(materialized, consumer_capabilities=(),
                                       clash_report={"findings": []})
    assert refusal.value.code == "clash_capability_absent"


def test_the_capability_composes_with_the_two_older_ones(materialized):
    a, b = ids_of(materialized)[1:3]
    artifact = export_with(materialized, {"findings": [finding(a, b)]},
                           caps=(CLASH_CAPABILITY, SURFACE_CAPABILITY, REQUIRED_CONSUMER_CAPABILITY))
    data = artifact.to_dict()
    assert data["schema"] == export.DISPLAY_SCHEMA_V3
    assert "surfaces" in data and "clash_findings" in data
    assert standalone.load_display_artifact(artifact.dumps().encode()).transport["schema"] \
        == standalone.TRANSPORT_SCHEMA_V3


def test_an_unknown_capability_is_still_refused(materialized):
    with pytest.raises(export.StandaloneExportRefusal) as refusal:
        export.export_standalone_scene(materialized, consumer_capabilities=("display_whatever/9",))
    assert refusal.value.code == "unsupported_capability"


# ─────────────────────────────────────────── the record accepts nothing extra

@pytest.mark.parametrize("over,code", [
    ({"status": "maybe"}, "invalid_finding"),
    ({"relation": "touching"}, "invalid_finding"),
    ({"hull_source_a": "guess"}, "invalid_finding"),
    ({"depth_mm": float("nan")}, "invalid_finding"),
    ({"finding_id": ""}, "invalid_finding"),
])
def test_a_malformed_finding_is_a_named_refusal(over, code):
    with pytest.raises(ClashDisplayRefusal) as refusal:
        display_clash_findings({"findings": [finding("p1/a", "p1/b", **over)]}, ["p1/a", "p1/b"])
    assert refusal.value.code == code


def test_a_repeated_finding_id_is_refused():
    rows = [finding("p1/a", "p1/b"), finding("p1/a", "p1/b")]
    with pytest.raises(ClashDisplayRefusal):
        display_clash_findings({"findings": rows}, ["p1/a", "p1/b"])


def test_a_finding_whose_side_is_not_shown_becomes_a_named_limit_not_silence():
    shown = display_clash_findings(
        {"findings": [finding("p1/a", "p1/missing")]}, ["p1/a", "p1/b"])
    assert shown["findings"] == []
    assert any("не адресуются" in item and "F1" in item for item in shown["analysis_limits"])


# ─────────────────────────────────────────── the loader judges just as strictly

def edited(artifact, mutate):
    data = artifact.to_dict()
    mutate(data)
    data.pop("artifact_digest", None)
    from kir.project import _hash
    data["artifact_digest"] = _hash(data)
    return json.dumps(data).encode()


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d["clash_findings"][0].__setitem__("status", "maybe"), "status"),
    (lambda d: d["clash_findings"][0].__setitem__("display_id_b", "p1/nowhere"), "address"),
    (lambda d: d["clash_findings"][0].__setitem__("relation", "clear"), "clear+volume"),
    (lambda d: d["clash_findings"][0].__setitem__("overlap_volume_mm3", 0.0), "intersect-volume"),
    (lambda d: d["clash_findings"][0].pop("gap_mm"), "fields"),
    (lambda d: d["clash_claims"].__setitem__("bim_coverage", "claimed"), "claims"),
    (lambda d: d["clash_analysis_limits"].append(""), "empty limit"),
])
def test_an_edited_artifact_fails_closed(materialized, mutate, reason):
    a, b = ids_of(materialized)[1:3]
    artifact = export_with(materialized, {"findings": [finding(a, b)],
                                          "analysis_limits": ["проверено 1 из 1"]})
    with pytest.raises(standalone.DisplayInputRefusal):
        standalone.load_display_artifact(edited(artifact, mutate))
    # Control: the same, unedited artifact is accepted.
    assert standalone.load_display_artifact(artifact.dumps().encode()).transport["schema"] \
        == standalone.TRANSPORT_SCHEMA_V3, reason


def test_a_refuted_finding_carries_its_gap_and_no_volume(materialized):
    a, b = ids_of(materialized)[1:3]
    row = finding(a, b, status="refuted", relation="clear", depth_mm=None,
                  overlap_volume_mm3=0.0, gap_mm=1085.786438,
                  refusal_ru="оболочки пересеклись, тела — нет")
    artifact = export_with(materialized, {"findings": [row]})
    shown, = artifact.to_dict()["clash_findings"]
    assert shown["status"] == "refuted" and shown["relation"] == "clear"
    assert shown["overlap_volume_mm3"] == 0.0 and shown["gap_mm"] == 1085.786438
    assert standalone.load_display_artifact(artifact.dumps().encode()) is not None


def test_a_coarse_finding_is_shown_without_a_volume_and_a_proven_one_is_not(materialized):
    """The coarse phase HAS NO volume, and that is its honest claim, not a
    gap.

    🔴 MEASURED 07.09.2026. The requirement "every intersection must carry
    a volume" made the WHOLE coarse analysis unshowable:
    `analyze_project(exact=False)` on `examples/podium_passage.py` gives 5
    `possible` findings with `overlap_volume_mm3 = None`, and the loader
    rejected the whole artifact (`intersecting finding must carry its
    volume`). The application could show only exact analysis; "we looked
    coarsely" could not be expressed at all. The control below holds the
    second half of the law: for a PROVEN finding, a volume is still
    mandatory.
    """
    a, b = ids_of(materialized)[1:3]
    coarse = finding(a, b, status="possible", overlap_volume_mm3=None)
    artifact = export_with(materialized, {
        "findings": [coarse],
        "analysis_limits": ["exact narrow phase not requested (exact=False)"]})
    shown, = artifact.to_dict()["clash_findings"]
    assert shown["status"] == "possible" and shown["overlap_volume_mm3"] is None
    assert standalone.load_display_artifact(artifact.dumps().encode()) is not None
    proven = export_with(materialized, {"findings": [finding(a, b, overlap_volume_mm3=None)]})
    with pytest.raises(standalone.DisplayInputRefusal):
        standalone.load_display_artifact(proven.dumps().encode())
