"""Original create-object identity capture; compile/stub controls, not live Revit."""
from collections import Counter
import json
import pathlib
import shutil
import subprocess

import pytest

from kir.compiler import compile_program
from kir.contracts import ElementIdentityProof
from kir.emit_core import _safe, element_identity_readback_cs
from kir.tests.test_connector_compiler_conformance import conformance_runner, prepared
from kir.tests.test_connector_result import case

ROOT = pathlib.Path(__file__).resolve().parents[2]


#: 🔴 THE LIST IS GONE, AND THAT IS THE POINT (E1, 2026-09-13). This used to be
#: seven names typed by hand, while the code captured in eight places and the
#: registry said 8 — three carriers of one number, and they had already drifted.
#: Whether an op captured is not an opinion: the emission either carries that
#: op's own identity readback or it does not, so the emission is the only source
#: asked below. The SEAM has its own exact number and its own guard:
#: `test_every_shared_receipt_call_asks_for_identity`.
def captured_op_ids(source: str, planned) -> set[str]:
    """Op ids whose identity readback is actually present in this emission."""
    return {op.op_id for op in planned.ops
            if f"Element __kirIdentityEl = __el_{_safe(op.op_id)};" in source}


def test_every_shared_receipt_call_asks_for_identity():
    """Every emitter standing on the shared receipt seam captures identity.

    The producer half of E1 is exactly this: `_readback_block` is the one place
    an op's receipt is built, and before 13.09.2026 only three of its 24 callers
    passed `identity_version`, so 63 of 71 create ops returned an element nobody
    could name afterwards. A new emitter joining the seam without identity would
    reopen that hole silently; this reddens instead.
    """
    import ast

    modules = ("kir/authoring.py", "kir/struct_emit.py", "kir/arch_emit.py",
               "kir/mep_emit.py", "kir/opening_emit.py", "kir/site_emit.py")
    silent = []
    total = 0
    for name in modules:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_readback_block"):
                total += 1
                if "identity_version" not in {kw.arg for kw in node.keywords}:
                    silent.append(f"{name}:{node.lineno}")
    assert total >= 24, f"the seam lost call sites: {total}"
    assert not silent, ("эти вызовы общего шва квитанции не просят личность, "
                        f"значит их выходы не привязать: {silent}")


def selected_program():
    from examples.residential_project import concept
    from kir.viewer.tests.test_live_scene_mesh import _VAULT

    return {"ops": [
        {"op": "create_level", "id": "level", "elev_mm": 1200, "name": "L"},
        {"op": "create_directshape", "id": "mesh", "mesh": _VAULT,
         "name": "Podium", "category": "mass"},
        *concept().to_program()["ops"],
    ]}


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_selected_create_readbacks_capture_original_objects_after_commit(year):
    result = compile_program(selected_program(), revit_version=year, bulk=True)
    assert result.ok, result.diagnostics
    source = result.csharp
    expected = len(result.planned.ops)
    assert source.count('["element_identity_status"] = "captured"') == expected
    assert source.index("__t.Commit()") < source.index('"element_identity_status"')
    assert captured_op_ids(source, result.planned) == {op.op_id for op in result.planned.ops}
    assert "VersionGuid.ToString(\"N\")" in source
    assert ('__kirIdentityId.IntegerValue' in source) is (year == "2023")
    assert ('__kirIdentityId.Value' in source) is (year == "2026")


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_selected_create_source_passes_actual_connector_policy_and_api(year, conformance_runner):
    artifact = prepared(selected_program(), year, bulk=True)
    row, = conformance_runner(year, [artifact.source])
    assert row["ok"] is True, row
    assert row["assembly_bytes"] > 0


def test_other_solid_readbacks_do_not_silently_claim_capture():
    from kir.tests.test_solid import _extrusion, _revolve

    sweep = {"op": "create_solid_sweep", "id": "sweep", "variety": "fixed_reference",
             "profile": {"outer": {"shape": "rect", "origin": [-100, -100],
                                      "size_mm": [200, 200]}},
             "path_mm": [[0, 0, 0], [5000, 0, 0]],
             "ref_dir": [0, 0, 1], "category": "mass", "name": "Sweep"}
    for op in (_extrusion(), _revolve(), sweep):
        result = compile_program({"ops": [op]}, revit_version="2026")
        assert result.ok, result.diagnostics
        assert '"element_identity"' not in result.csharp


def test_saved_residential_named_sources_capture_only_selected_original_objects(tmp_path):
    pytest.importorskip("OCP")
    from examples.residential_with_podium import create_store, materialize_saved
    from kir.project_store import ProjectStore

    store = create_store(tmp_path / "project.sqlite")
    revision = store.head()
    reopened = ProjectStore.open(store.path)
    materialized = materialize_saved(reopened)
    assert reopened.head().revision_id == revision.revision_id
    counts = Counter(op.op_name for op in materialized.planned.ops)
    assert counts["create_level"] == 3
    assert counts["create_solid_blend"] == 2
    assert counts["create_directshape"] == 1
    for year in ("2023", "2026"):
        result = compile_program(materialized.planned, revit_version=year,
                                 bulk=materialized.planned.bulk)
        assert result.ok, result.diagnostics
        assert counts["create_wall"] == 12 and counts["create_floor_by_contour"] == counts["create_room"] == 3
        expected_captures = len(materialized.planned.ops)
        assert captured_op_ids(result.csharp, materialized.planned) == {
            op.op_id for op in materialized.planned.ops}
        assert result.csharp.count('["element_identity_status"] = "captured"') == expected_captures
        # Every op of this saved project captures; the emission says so itself,
        # and `captured_op_ids` above already compared the two sets. Kept as the
        # per-op form so a failure names WHICH output lost its identity.
        for op in materialized.planned.ops:
            binding = f"Element __kirIdentityEl = __el_{_safe(op.op_id)};"
            assert binding in result.csharp, op.op_name


@pytest.mark.parametrize("year", ["2021", "2022", "2023", "2024", "2025", "2026"])
def test_reader_only_reads_supplied_object_and_has_no_effect_or_lookup_authority(year):
    source = element_identity_readback_cs("original", revit_version=year, rb_var="receipt")
    assert "Element __kirIdentityEl = original;" in source
    assert 'receipt["element_identity"]' in source
    assert "IntegerValue" in source if int(year) <= 2023 else ".Value" in source
    for forbidden in ("doc.", "GetElement", "__post", "Commit", "RollBack", "throw", '["ok"]'):
        assert forbidden not in source


@pytest.mark.parametrize("variable", ["x.Id", "x; return null", "", "1x", "é"])
def test_reader_refuses_nonvariable_source_fragments(variable):
    with pytest.raises(ValueError):
        element_identity_readback_cs(variable, revit_version="2026")
    with pytest.raises(ValueError):
        element_identity_readback_cs("original", revit_version="2026", rb_var=variable)


HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Text.Json;

sealed class ElementId {
    readonly long number;
    public ElementId(long value) { number = value; }
    public int IntegerValue { get { return checked((int)number); } }
    public long Value { get { return number; } }
}
sealed class Element {
    readonly int fault;
    readonly long number;
    public Element(int value, long id) { fault = value; number = id; }
    public ElementId Id { get {
        if (fault == 1) throw new InvalidOperationException("id getter secret must not leak");
        return fault == 4 ? null : new ElementId(number);
    } }
    public string UniqueId { get {
        if (fault == 2) throw new InvalidOperationException("uid getter secret must not leak");
        return fault == 6 ? "" : fault == 7 ? "  " : fault == 8 ? null : "original-UID-ЖК";
    } }
    public Guid VersionGuid { get {
        if (fault == 3) throw new InvalidOperationException("version getter secret must not leak");
        return Guid.Parse("abcde123-4567-89ab-cdef-0123456789ab");
    } }
}
static class Program {
    public static object Read2023(Element original) {
        var __rb = new Dictionary<string, object>();
        // The transaction has already committed before this reader is called.
        __rb["ok"] = true;
        __rb["transaction"] = "committed";
        /* READER2023 */
        return __rb;
    }
    public static object Read2026(Element original) {
        var __rb = new Dictionary<string, object>();
        __rb["ok"] = true;
        __rb["transaction"] = "committed";
        /* READER2026 */
        return __rb;
    }
    public static void Main() {
        var rows = new Dictionary<string, object>();
        foreach (var year in new[] {2023, 2026}) {
            Func<Element, object> read = year == 2023 ? Read2023 : Read2026;
            rows[year + ":null"] = read(null);
            for (int fault = 0; fault <= 8; ++fault)
                rows[year + ":" + fault] = read(new Element(fault, fault == 5 ? -1 : 700));
            rows[year + ":wide"] = read(new Element(0, 4000000000));
        }
        Console.Write(JsonSerializer.Serialize(rows));
    }
}
'''


@pytest.fixture(scope="module")
def identity_reader_rows(tmp_path_factory):
    if shutil.which("dotnet") is None:
        pytest.skip(".NET SDK unavailable; reader getter-failure stubs not executed")
    root = tmp_path_factory.mktemp("identity-reader-stubs")
    # These are generated test-only fixtures, not modified native runtime code.
    (root / "Reader.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
        '<OutputType>Exe</OutputType><Nullable>disable</Nullable>'
        '<NuGetAudit>false</NuGetAudit></PropertyGroup></Project>', encoding="utf-8")
    source = HARNESS
    for year in ("2023", "2026"):
        source = source.replace(f"/* READER{year} */", element_identity_readback_cs(
            "original", revit_version=year))
    (root / "Program.cs").write_text(source, encoding="utf-8")
    build = subprocess.run(["dotnet", "build", str(root / "Reader.csproj"),
                            "-c", "Release", "--nologo"],
                           capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run(["dotnet", str(root / "bin/Release/net8.0/Reader.dll")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "secret" not in run.stdout and not run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("case,reason", [
    ("null", "element_missing"),
    ("1", "identity_unreadable"), ("2", "identity_unreadable"),
    ("3", "identity_unreadable"), ("4", "identity_incomplete"),
    ("5", "identity_incomplete"), ("6", "identity_incomplete"),
    ("7", "identity_incomplete"), ("8", "identity_incomplete"),
])
def test_stub_missing_or_throwing_getter_is_unavailable_not_a_rollback(year, case, reason, identity_reader_rows):
    row = identity_reader_rows[f"{year}:{case}"]
    assert row == {"ok": True, "transaction": "committed", "element_identity": None,
                   "element_identity_status": "unavailable", "element_identity_reason": reason}


@pytest.mark.parametrize("year,case,expected_id", [
    ("2023", "0", 700), ("2026", "0", 700), ("2026", "wide", 4000000000),
])
def test_stub_captured_wire_roundtrips_existing_identity_contract(year, case, expected_id, identity_reader_rows):
    row = identity_reader_rows[f"{year}:{case}"]
    assert row["ok"] is True and row["transaction"] == "committed"
    assert row["element_identity_status"] == "captured" and row["element_identity_reason"] is None
    proof = ElementIdentityProof.from_dict(row["element_identity"])
    assert proof.element_id == expected_id
    assert proof.unique_id == "original-UID-ЖК"
    assert proof.version_guid == "abcde123456789abcdef0123456789ab"


def test_stub_legacy_integer_overflow_is_unavailable(identity_reader_rows):
    row = identity_reader_rows["2023:wide"]
    assert row["element_identity"] is None
    assert row["element_identity_reason"] == "identity_unreadable"
    assert row["ok"] is True


@pytest.mark.parametrize("identity_case", ["0", "3", "legacy"])
def test_bound_receipt_retains_capture_without_inventing_legacy_identity(case, identity_case, identity_reader_rows):
    _, _, response, assess = case
    readback = {"id": "700"}
    if identity_case != "legacy":
        readback.update({key: value for key, value in identity_reader_rows[f"2023:{identity_case}"].items()
                         if key.startswith("element_identity")})
    response["receipt"]["result_json"] = json.dumps({"ok": True, "L": readback})
    verdict = assess()
    # Existing D1 checks the ordinary per-op return contract. It does not
    # qualify an original identity for future mutation; that is a separate path.
    assert verdict.ok and verdict.outcome.execution.value == "committed"
    retained = json.loads(verdict.receipt["result_json"])["L"]
    assert retained == readback
    if identity_case == "0":
        assert ElementIdentityProof.from_dict(retained["element_identity"]).element_id == 700
    elif identity_case == "3":
        assert retained["element_identity"] is None
    else:
        assert "element_identity" not in retained
