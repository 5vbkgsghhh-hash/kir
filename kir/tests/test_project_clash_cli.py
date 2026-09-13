"""The CLI obtains a scoped report without changing the saved authoring project."""
import json
import os

import pytest

from kir import __main__ as cli
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision
from kir.project_store import ProjectStore


def root():
    return ProjectRevision("clash-cli", [ModuleDefinition("m")], [ModuleInstance(
        "datum", "m", {"level": {"op": "create_level", "name": "L0", "elev_mm": 0}})])


@pytest.fixture
def stored(tmp_path):
    first = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", first)
    second = first.revise(expected_revision=first.revision_id, intent="later revision")
    store.commit(second, expected_revision=first.revision_id)
    return store, first, second


def contents(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def test_head_report_keeps_source_files_head_and_flags_unchanged(stored, capsys, monkeypatch):
    store, _, second = stored
    before = contents(store.path.parent)
    for key in ("KIR_CLASH", "KIR_REBUILD", "KIR_MERGE3"):
        monkeypatch.setenv(key, "0")
    assert cli.main(["project", "clash-report", str(store.path)]) == cli.ANSWERED
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["revision"] == second.revision_id
    assert report["bodies_declared"] == 0 and report["findings"] == []
    assert "analysis_limits" in report and "not_evaluated" in report
    assert "код 0 не означает отсутствия коллизий" in captured.err
    assert store.head().revision_id == second.revision_id
    assert contents(store.path.parent) == before
    assert all(os.environ[key] == "0" for key in ("KIR_CLASH", "KIR_REBUILD", "KIR_MERGE3"))


def test_revision_pin_reaches_the_existing_analyzer_with_a_readonly_store(stored, capsys, monkeypatch):
    from kir.clash import project_analysis
    store, first, second = stored
    original = project_analysis.analyze_project
    calls = []

    def observe(reader, revision_id=None, **kwargs):
        assert reader.readonly is True
        calls.append((revision_id, kwargs))
        # A later head must not replace the explicitly selected old revision.
        third = second.revise(expected_revision=second.revision_id, intent="another writer")
        store.commit(third, expected_revision=second.revision_id)
        return original(reader, revision_id=revision_id, **kwargs)

    monkeypatch.setattr(project_analysis, "analyze_project", observe)
    assert cli.main(["project", "clash-report", str(store.path), "--revision", first.revision_id,
                     "--exact", "--clearance-mm", "25"]) == cli.ANSWERED
    report = json.loads(capsys.readouterr().out)
    assert report["revision"] == first.revision_id
    assert calls == [(first.revision_id, {"exact": True, "tolerance_policy": {"clearance_mm": 25.0}})]
    assert store.head().revision_id != report["revision"]


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "-1", "1e400", "true", "not-a-number"])
def test_invalid_clearance_is_refused_before_store_or_kernel(tmp_path, monkeypatch, capsys, value):
    from kir.clash import project_analysis

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid input reached store/kernel")

    monkeypatch.setattr(ProjectStore, "open", forbidden)
    monkeypatch.setattr(project_analysis, "analyze_project", forbidden)
    assert cli.main(["project", "clash-report", str(tmp_path / "absent"),
                     "--clearance-mm=" + value]) == cli.NOT_DONE
    report = json.loads(capsys.readouterr().out)
    assert report["error"]["code"] == "invalid_clearance_mm"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "corrupt", "folded_json"])
def test_wrong_store_does_not_become_a_new_project(tmp_path, capsys, kind):
    path = tmp_path / "source"
    if kind != "missing":
        path.write_bytes(b"not sqlite" if kind == "corrupt" else b'{"node_id":"tree","children":[]}')
    before = contents(tmp_path)
    assert cli.main(["project", "clash-report", str(path)]) == cli.NOT_DONE
    report = json.loads(capsys.readouterr().out)
    assert report["error"]["code"] == "project_store_unavailable"
    assert report["report_obtained"] is False
    assert contents(tmp_path) == before


def test_absent_revision_is_named_before_analysis(stored, capsys, monkeypatch):
    from kir.clash import project_analysis
    store, _, _ = stored
    before = contents(store.path.parent)

    def forbidden(*args, **kwargs):
        raise AssertionError("unknown revision reached the analyzer")

    monkeypatch.setattr(project_analysis, "analyze_project", forbidden)
    assert cli.main(["project", "clash-report", str(store.path), "--revision", "0" * 64]) == cli.NOT_DONE
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "revision_unavailable"
    assert contents(store.path.parent) == before


def test_failed_analysis_is_not_an_empty_success_report(stored, capsys, monkeypatch):
    from kir.clash import project_analysis
    store, _, _ = stored

    def fail(*args, **kwargs):
        raise RuntimeError("kernel did not produce a report")

    monkeypatch.setattr(project_analysis, "analyze_project", fail)
    assert cli.main(["project", "clash-report", str(store.path)]) == cli.NOT_DONE
    report = json.loads(capsys.readouterr().out)
    assert report["error"] == {"code": "clash_report_unavailable", "type": "RuntimeError"}
    assert report["report_obtained"] is False and "findings" not in report


def test_real_overlapping_bodies_produce_findings_but_still_answer_successfully(tmp_path, capsys):
    pytest.importorskip("OCP", reason="the geometric control needs real OCCT")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from kir.occt_geometry import capture_body
    from kir.project import BodyRepresentation, NamedOutput, PROJECT_SCHEMA_V2, RecipePin

    pin = RecipePin("analytic overlapping box fixture; never executed on load", "a" * 64)
    instances, assets = [], []
    for key, start in (("a", 0), ("b", 500)):
        parameters = {"x_mm": start}
        shape = BRepPrimAPI_MakeBox(gp_Pnt(start, 0, 0), 1000, 1000, 1000).Shape()
        bundle = capture_body(shape, project_id="geometric-clash-cli", instance_key=key,
                              output_key="body", recipe=pin, parameters=parameters)
        assets.append(bundle)
        output = NamedOutput("body", {"op": "create_directshape", "category": "mass", "name": key},
                             BodyRepresentation(bundle.digest, bundle.body_digest))
        instances.append(ModuleInstance(key, "geometry", [output], parameters))
    revision = ProjectRevision("geometric-clash-cli", [ModuleDefinition("geometry", "sealed_evaluation", pin)],
                               instances, schema=PROJECT_SCHEMA_V2)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", revision,
                                schema="kir-project-store/2", assets=assets)
    before = contents(tmp_path)
    assert cli.main(["project", "clash-report", str(store.path), "--exact"]) == cli.ANSWERED
    report = json.loads(capsys.readouterr().out)
    assert report["bodies_declared"] == report["bodies_with_hull"] == 2
    assert len(report["findings"]) == 1
    assert report["findings"][0]["status"] == "confirmed"
    assert report["findings"][0]["overlap_volume_mm3"] == pytest.approx(500 * 1000 * 1000)
    assert report["revision"] == revision.revision_id
    assert store.head().revision_id == revision.revision_id and contents(tmp_path) == before
