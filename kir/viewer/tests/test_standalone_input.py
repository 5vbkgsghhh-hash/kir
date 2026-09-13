"""Inert display transport validation; no browser/native execution claims."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys

import pytest

from examples.residential_project import concept
from kir.geometry_materialization import materialize_project
from kir.project import _canonical, _hash
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.standalone import DisplayInputRefusal, load_display_artifact, _scene
from kir.viewer.standalone_export import export_standalone_scene


@pytest.fixture(scope="module")
def artifact():
    return export_standalone_scene(materialize_project(concept(), {}),
        consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])


def resign(data):
    data["artifact_digest"] = _hash({k: v for k, v in data.items() if k != "artifact_digest"})
    return _canonical(data).encode()


@pytest.fixture(scope="module")
def controls_artifact():
    root = Path(__file__).resolve().parents[3]
    child = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "fixtures_display.py"), "controls"],
        capture_output=True, check=True, timeout=20,
        env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"))
    return base64.b64decode(json.loads(child.stdout)["artifact_base64"])


@pytest.mark.parametrize("table_name", ["categories", "levels"])
@pytest.mark.parametrize("replacement", ["mapping", "string", "null", "number", "boolean", "nested"])
def test_fully_rehashed_scene_requires_typed_string_tables(controls_artifact, table_name, replacement):
    data = json.loads(controls_artifact)
    old = base64.b64decode(data["scene"]["base64"])
    base = 12 + struct.unpack_from("<I", old, 8)[0]
    header = json.loads(old[12:base])
    original = header[table_name]
    assert original and all(isinstance(value, str) for value in original)
    if replacement == "mapping":
        changed = {f"x{i}": value for i, value in enumerate(original)}
    elif replacement == "string":
        changed = "x" * len(original)
    else:
        invalid = {"null": None, "number": 1, "boolean": True, "nested": ["x"]}[replacement]
        changed = [invalid] * len(original)
    assert len(changed) == len(original)  # Bounds alone cannot qualify a table.
    header[table_name] = changed
    encoded = _canonical(header).encode()
    encoded += b" " * (-(12 + len(encoded)) % 4)
    blob = old[:8] + struct.pack("<I", len(encoded)) + encoded + old[base:]
    data["scene"].update(base64=base64.b64encode(blob).decode(), size_bytes=len(blob),
                         sha256=hashlib.sha256(blob).hexdigest())
    with pytest.raises(DisplayInputRefusal, match=f"{table_name}: expected string table"):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("labels", [[], [""], ["first", ""], ["A\u2028B\u2029C\u0085D\rE\vF\fG", ""]])
def test_raw_codec_lf_records_preserve_empty_labels_and_unicode_separators(labels):
    from kir.viewer.codec import SceneBuilder
    from kir.viewer.standalone import _FIDELITIES
    builder = SceneBuilder()
    for index, label in enumerate(labels):
        kind, slot = builder.add_box((index * 10, 0, 0), (index * 10 + 1, 1, 1))
        builder.add_element(element_id=f"box-{index}", category="control", level=None,
                            kind=kind, slot=slot, trust=3, fidelity=2, **({"label": label} if label else {}))
    blob = builder.finish({"fidelity_codes": _FIDELITIES})
    header, records = _scene(blob)
    assert len(records) == len(labels)
    assert header["levels"] == (["?"] if labels else [])
    assert builder.labels == labels


def test_real_authored_duct_graph_empty_segment_label_loads_without_losing_its_address():
    from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, output_id
    project = ProjectRevision("label-probe", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("duct", {"op": "route_duct_system", "level": {"by": "name", "value": "L"},
            "diameter_mm": 200, "nodes": [{"id": "A", "xyz_mm": [0, 0, 3000]},
                                          {"id": "B", "xyz_mm": [5000, 0, 3000]}],
            "segments": [{"from": "A", "to": "B"}]})])])
    exported = export_standalone_scene(materialize_project(project, {}))
    expected_id = "p1/" + output_id("label-probe", "i", "duct") + "#1"
    loaded = load_display_artifact(exported.dumps().encode())
    assert [row["display_id"] for row in loaded.data["scene"]["records"]] == [expected_id]
    assert list(loaded.data["unattributed_scene_ids"]) == [expected_id]
    assert len(loaded.data["omissions"]) == 1  # Child is not guessed to be its direct output.


def test_inert_loader_keeps_original_whitespace_and_python_scalar_bytes(artifact, monkeypatch):
    from kir.occt_geometry import GeometryBundle
    def forbidden(*args, **kwargs):
        raise AssertionError("inert loader entered native backend")
    monkeypatch.setattr(GeometryBundle, "read_body", forbidden)
    monkeypatch.setattr(GeometryBundle, "rederive_preview", forbidden)
    # The outer transport need not itself be canonical. Hashes are validated
    # in Python without JS's normalization of 0.0, -0.0 or exponents.
    raw = json.dumps(artifact.to_dict(), indent=2).encode()
    value = load_display_artifact(raw)
    assert value.original_bytes == raw
    assert value.transport["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    for payload, proxy in zip(value.transport["proxy_payloads"], artifact.to_dict()["proxies"]):
        exact = base64.b64decode(payload["payload_base64"], validate=True)
        assert b"0.0" in exact
        assert hashlib.sha256(exact).hexdigest() == payload["sha256"] == proxy["preview"]["preview_digest"]
        assert json.loads(exact) == {k: v for k, v in proxy["preview"].items() if k != "preview_digest"}
    with pytest.raises(TypeError):
        value.data["claims"]["native_execution"] = "verified"


@pytest.mark.parametrize("raw", [b"\xff", b'{"schema":1,"schema":2}', b'{"v":NaN}', b'{"v":1e999}', b"[" * 100 + b"0" + b"]" * 100])
def test_malformed_utf8_duplicate_nonfinite_deep_json_has_named_refusal(raw):
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(raw)


@pytest.mark.parametrize("case", ["schema", "digest", "scene_bytes", "scene_size", "source_address", "proxy_hash", "proxy_source",
    "proxy_claim", "capability", "status", "extra_omission", "scene_count", "artifact_claim", "unattributed"])
def test_resigned_internal_mixups_are_rejected_before_any_server(artifact, case):
    data = artifact.to_dict()
    if case == "schema": data["schema"] = "kir-standalone-display/999"
    elif case == "digest": data["artifact_digest"] = "0" * 64
    elif case == "scene_bytes": data["scene"]["base64"] = base64.b64encode(b"KIRSCN01").decode()
    elif case == "scene_size": data["scene"]["size_bytes"] += 1
    elif case == "source_address": data["source"]["operations"][0]["instance_key"] = "foreign"
    elif case == "proxy_hash": data["proxies"][0]["preview"]["mesh"]["vertices_mm"][0][0] += 1000
    elif case == "proxy_source": data["proxies"][0]["preview"]["source"]["operation_sha256"] = "0" * 64
    elif case == "proxy_claim": data["proxies"][0]["preview"]["claims"]["native_equivalence"] = "verified"
    elif case == "capability": data["consumer_contract"]["declared_capabilities"] = []
    elif case == "status": data["source"]["operations"][0]["display_status"] = "base_scene_record"
    elif case == "extra_omission": data["omissions"] = [{**data["source"]["operations"][0], "scope": "direct_output_address", "code": "invented"}]
    elif case == "scene_count": data["scene"]["counts"]["mesh"] = True
    elif case == "artifact_claim": data["claims"]["browser_rendering"] = "verified"
    else: data["unattributed_scene_ids"] = ["p1/foreign"]
    raw = _canonical(data).encode() if case == "digest" else resign(data)
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(raw)


def test_real_residential_inputs_validate_with_original_mesh_and_all_named_omissions():
    pytest.importorskip("OCP")
    from examples.residential_with_podium import workflow
    revisions, bundle = workflow()
    for revision in revisions[2:]:
        exported = export_standalone_scene(materialize_project(revision, {bundle.digest: bundle}),
            consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
        loaded = load_display_artifact(exported.dumps().encode())
        assert loaded.data["source"]["project_revision_id"] == revision.revision_id
        assert len(loaded.data["omissions"]) == (0 if revision == revisions[2] else 6)
    child = subprocess.run([sys.executable, "-c", """
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('display file loading imported native backend')
sys.meta_path.insert(0, NoOcp())
from kir.viewer.standalone import load_display_artifact
loaded = load_display_artifact(sys.stdin.buffer.read())
assert len(loaded.data['source']['body_sources']) == 1
assert not any(name == 'OCP' or name.startswith('OCP.') for name in sys.modules)
print('inert real-body display')
"""], input=exported.dumps().encode(), capture_output=True, timeout=20,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3]), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr.decode()
    assert child.stdout.strip() == b"inert real-body display"

#: 🔴 13.09.2026. Two checks stood here about the loopback inspector SERVER —
#: its allowlist, its single tail key, its 404/405/403. The window was removed
#: by the owner's word, and they went with it; what they guarded (the display
#: FILE is inert and fails closed) is what the checks above measure. Nothing
#: about the format was dropped: `load_display_artifact` keeps every refusal.
