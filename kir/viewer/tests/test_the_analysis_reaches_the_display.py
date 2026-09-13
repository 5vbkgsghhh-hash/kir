"""END-TO-END PASS: saved scene -> analysis -> display artifact /3.

🔴 WHAT THIS FILE GUARDS, AND WHY EXACTLY THIS. Acceptance on 06.09.2026
(entry 6) found a gap no test had seen: the display of findings was
built and checked, but was NOT CONNECTED to the analysis. The report
addresses bodies by the project's `output_id`, the display by the
scene's display-id, and without translation into the artifact,
`clash_findings: 0` would land there even with FIVE real findings. A
zero obtained this way is indistinguishable from an honest "no
clashes" — and that is exactly why it is more dangerous than a crash.
"""
from __future__ import annotations

import json

import pytest

from kir.viewer import standalone, standalone_export as export
from kir.viewer.clash_findings import CLASH_CAPABILITY, display_clash_findings

pytest.importorskip("OCP", reason="сцена приёмки строится настоящим кернелом")


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    from examples.podium_passage import save
    return save(tmp_path_factory.mktemp("passage") / "store")


@pytest.fixture(scope="module")
def exported(saved):
    return export.export_saved_project_scene(saved, exact=True)


def test_every_finding_of_the_analysis_reaches_the_artifact(exported):
    artifact, report = exported
    data = artifact.to_dict()
    assert data["schema"] == export.DISPLAY_SCHEMA_V3
    assert len(report.findings) == 5, "сцена приёмки несёт пять пар"
    assert len(data["clash_findings"]) == len(report.findings), (
        "находки анализа не доехали до показа — ровно тот разрыв, ради которого файл заведён")
    kinds = sorted((row["status"], row["relation"]) for row in data["clash_findings"])
    assert kinds == [("confirmed", "contained"), ("confirmed", "contained"),
                     ("confirmed", "contained"), ("confirmed", "intersect"),
                     ("refuted", "clear")]


def test_the_acceptance_numbers_survive_the_trip(exported):
    """38.000 m³ and a gap of 1085.786 mm — the same numbers as in the
    acceptance contract."""
    artifact, _ = exported
    rows = artifact.to_dict()["clash_findings"]
    crossing = [row for row in rows if row["relation"] == "intersect"]
    assert len(crossing) == 1
    assert crossing[0]["overlap_volume_mm3"] == pytest.approx(3.8e10, rel=1e-3)
    void = [row for row in rows if row["relation"] == "clear"]
    assert len(void) == 1 and void[0]["status"] == "refuted"
    assert void[0]["gap_mm"] == pytest.approx(1085.786438, abs=0.5)
    assert void[0]["overlap_volume_mm3"] == 0.0


def test_addresses_are_translated_not_copied(exported):
    """The display address comes from materialization, not from the
    analysis's `output_id` as-is."""
    artifact, report = exported
    data = artifact.to_dict()
    shown = {row["display_id_a"] for row in data["clash_findings"]} | \
            {row["display_id_b"] for row in data["clash_findings"]}
    known = {row["display_id"] for row in data["source"]["operations"]}
    assert shown and shown <= known, "сторона находки обязана адресоваться показанной сценой"
    analysed = {f.a_output_id for f in report.findings} | {f.b_output_id for f in report.findings}
    assert not (shown & analysed), "адресные пространства разные — перевод обязан состояться"
    for row in data["clash_findings"]:
        assert row["hull_source_a"] == row["hull_source_b"] == "brep"


def test_the_limits_of_the_analysis_travel_with_the_findings(exported):
    artifact, report = exported
    limits = artifact.to_dict()["clash_analysis_limits"]
    assert limits, "показ без ограничений анализа читается как «больше ничего нет»"
    assert set(report.analysis_limits) <= set(limits)


def test_the_loader_and_its_js_mirror_accept_the_real_artifact(exported):
    artifact, _ = exported
    loaded = standalone.load_display_artifact(artifact.dumps().encode())
    assert loaded.transport["schema"] == standalone.TRANSPORT_SCHEMA_V3
    assert CLASH_CAPABILITY in json.loads(artifact.dumps())["consumer_contract"]["declared_capabilities"]


def test_an_untranslatable_side_is_named_not_dropped():
    """Control reverting the defect: without an address map, findings
    are not shown."""
    report = {"findings": [{"finding_id": "F1", "a_output_id": "out-1", "b_output_id": "out-2",
                            "status": "confirmed", "relation": "intersect", "depth_mm": 1.0,
                            "overlap_volume_mm3": 2.0, "gap_mm": None}],
              "hull_source": {"out-1": "brep", "out-2": "brep"}}
    blind = display_clash_findings(report, ["p1/a", "p1/b"])
    assert blind["findings"] == [] and any("не адресуются" in item for item in blind["analysis_limits"])
    seeing = display_clash_findings(report, ["p1/a", "p1/b"],
                                    address_map={"out-1": "p1/a", "out-2": "p1/b"})
    assert len(seeing["findings"]) == 1 and seeing["analysis_limits"] == []
    assert seeing["findings"][0]["hull_source_a"] == "brep"
