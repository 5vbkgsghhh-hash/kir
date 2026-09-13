"""Execute the actual query fragment against a fake API, never a Revit model.

This checks emitted control flow/units/field scope, not the Connector wrapper,
context-revision admission, actual Autodesk getter behavior, or native safety.
The independent actual-API reference-compilation lane is owned separately.
"""
import json
import shutil
import subprocess

import pytest

from kir.compiler import compile_program
from kir.contracts import ElementIdentityProof
from kir.element_query import emit_element_state


OPS = [
    {"op": "query_element_state", "id": "read-level", "unique_id": "level-uid"},
    {"op": "query_element_state", "id": "read-protected", "unique_id": "protected-uid"},
]
CASES = (
    "normal", "missing", "lookup_throw", "changed_id", "identity_throw", "identity_mismatch",
    "shared", "unknown_basis", "missing_elevation", "missing_basis", "wrong_elevation_id",
    "wrong_basis_id", "elevation_no_value", "basis_no_value", "wrong_elevation_storage",
    "wrong_basis_storage", "localized", "duplicate_name", "other_named_parameter",
    "missing_named_parameter", "read_only", "get_type_throw", "type_lookup_throw",
    "type_missing", "no_type", "type_identity_throw", "project_nan", "reported_infinity",
    "parameter_nan", "parameter_throw", "basis_throw", "name_lookup_throw", "name_throw",
    "category_throw", "category_null", "wide_id", "document_modifiable", "document_state_throw",
)


HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Text.Json;

// Test-only values. Equality against actual Autodesk enum values is covered by
// the real API/emitter seam; this fake checks that the selected BIP is enforced.
enum BuiltInParameter { LEVEL_ELEV = -1007102, LEVEL_RELATIVE_BASE_TYPE = -1007101 }
enum StorageType { Double, Integer, String }
static class UnitTypeId { public static readonly object Millimeters = new object(); }
static class UnitUtils {
    public static double ConvertFromInternalUnits(double value, object unit) {
        if (unit != UnitTypeId.Millimeters) throw new InvalidOperationException("wrong units");
        return value * 304.8;
    }
}
sealed class ElementId {
    readonly long value;
    public static readonly ElementId InvalidElementId = new ElementId(-1);
    public ElementId(long number) { value = number; }
    public int IntegerValue { get { return checked((int)value); } }
    public long Value { get { return value; } }
    public static bool operator ==(ElementId a, ElementId b) {
        return Object.ReferenceEquals(a, b) ||
            (!Object.ReferenceEquals(a, null) && !Object.ReferenceEquals(b, null) && a.value == b.value);
    }
    public static bool operator !=(ElementId a, ElementId b) { return !(a == b); }
    public override bool Equals(object other) { return other is ElementId && this == (ElementId)other; }
    public override int GetHashCode() { return value.GetHashCode(); }
}
sealed class Category { public ElementId Id { get { return new ElementId(-2000240); } } }
sealed class Definition { public string Name { get; set; } }
sealed class Parameter {
    readonly string scenario;
    readonly bool basis;
    public Parameter(string mode, bool isBasis) { scenario = mode; basis = isBasis; }
    public ElementId Id { get {
        return new ElementId(basis
            ? (scenario == "wrong_basis_id" ? -999 : (long)BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE)
            : (scenario == "wrong_elevation_id" ? -999
               : (long)BuiltInParameter.LEVEL_ELEV));
    } }
    public bool HasValue { get { return scenario != (basis ? "basis_no_value" : "elevation_no_value"); } }
    public StorageType StorageType { get {
        return scenario == (basis ? "wrong_basis_storage" : "wrong_elevation_storage")
            ? StorageType.String : basis ? StorageType.Integer : StorageType.Double;
    } }
    public bool IsReadOnly { get { return scenario == "read_only"; } }
    public Definition Definition { get {
        return new Definition {Name = scenario == "localized" ? "Отметка уровня" : "Elevation"};
    } }
    public double AsDouble() {
        if (scenario == "parameter_throw") throw new InvalidOperationException("secret parameter failure");
        return scenario == "parameter_nan" ? double.NaN : scenario == "shared" ? 110 : 10;
    }
    public int AsInteger() {
        if (scenario == "basis_throw") throw new InvalidOperationException("secret basis failure");
        return scenario == "shared" ? 1 : scenario == "unknown_basis" ? 2 : 0;
    }
}
class Element {
    protected readonly string scenario;
    readonly string uid;
    readonly long id;
    protected readonly bool type;
    public Element(string mode, string uniqueId, long number, bool isType = false) {
        scenario = mode; uid = uniqueId; id = number; type = isType;
    }
    public ElementId Id { get { return new ElementId(id); } }
    public string UniqueId { get {
        if (scenario == "identity_throw" && !type) throw new InvalidOperationException("secret UID failure");
        return scenario == "identity_mismatch" && !type ? "not-the-requested-uid" : uid;
    } }
    public Guid VersionGuid { get {
        if (scenario == "type_identity_throw" && type) throw new InvalidOperationException("secret type identity");
        return Guid.Parse("abcde123-4567-89ab-cdef-0123456789ab");
    } }
    public string Name { get {
        if (scenario == "name_throw") throw new InvalidOperationException("secret name");
        return type ? "Level type" : uid;
    } }
    public Category Category { get {
        if (scenario == "category_throw") throw new InvalidOperationException("secret category");
        return scenario == "category_null" ? null : new Category();
    } }
    public ElementId GetTypeId() {
        if (scenario == "get_type_throw") throw new InvalidOperationException("secret type id");
        return this is Level && scenario != "no_type" ? new ElementId(1000) : ElementId.InvalidElementId;
    }
    public Parameter get_Parameter(BuiltInParameter key) {
        bool basis = key == BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE;
        if ((basis && !type) || (!basis && !(this is Level)))
            throw new InvalidOperationException("parameter read from wrong owner");
        if (scenario == (basis ? "missing_basis" : "missing_elevation")) return null;
        return new Parameter(scenario, basis);
    }
}
sealed class Level : Element {
    public Level(string mode, long number) : base(mode, "level-uid", number) { }
    public double ProjectElevation { get { return scenario == "project_nan" ? double.NaN : 10; } }
    public double Elevation { get {
        return scenario == "reported_infinity" ? double.PositiveInfinity : scenario == "shared" ? 110 : 10;
    } }
    public IList<Parameter> GetParameters(string name) {
        if (scenario == "name_lookup_throw") throw new InvalidOperationException("secret name lookup");
        var elevation = get_Parameter(BuiltInParameter.LEVEL_ELEV);
        if (name != elevation.Definition.Name) throw new InvalidOperationException("not the observed localized name");
        if (scenario == "duplicate_name") return new List<Parameter> {elevation, new Parameter("wrong_elevation_id", false)};
        if (scenario == "other_named_parameter") return new List<Parameter> {new Parameter("wrong_elevation_id", false)};
        if (scenario == "missing_named_parameter") return new List<Parameter>();
        return new List<Parameter> {elevation};
    }
}
sealed class Document {
    readonly string scenario;
    public readonly List<string> UidLookups = new List<string>();
    public readonly List<long> IdLookups = new List<long>();
    public Document(string mode) { scenario = mode; }
    public bool IsModifiable { get {
        if (scenario == "document_state_throw") throw new InvalidOperationException("secret document state");
        return scenario == "document_modifiable";
    } }
    public Element GetElement(string uid) {
        UidLookups.Add(uid);
        if (uid == "protected-uid") return new Element("normal", uid, 800);
        if (uid != "level-uid") throw new InvalidOperationException("unexpected UID");
        if (scenario == "lookup_throw") throw new InvalidOperationException("secret lookup failure");
        if (scenario == "missing") return null;
        return new Level(scenario, scenario == "changed_id" ? 901 : scenario == "wide_id" ? 4000000000 : 700);
    }
    public Element GetElement(ElementId id) {
        IdLookups.Add(id.Value);
        if (id.Value != 1000) throw new InvalidOperationException("numeric origin lookup is forbidden");
        if (scenario == "type_lookup_throw") throw new InvalidOperationException("secret type lookup");
        return scenario == "type_missing" ? null : new Element(scenario, "type-uid", 1000, true);
    }
}
static class Program {
    static object Query2023(Document doc) {
        var __results = new Dictionary<string, object>();
        /* QUERY2023 */
        return __results;
    }
    static object Query2026(Document doc) {
        var __results = new Dictionary<string, object>();
        /* QUERY2026 */
        return __results;
    }
    public static void Main() {
        var rows = new Dictionary<string, object>();
        string[] cases = /* CASES */;
        foreach (int year in new[] {2023, 2026}) foreach (string scenario in cases) {
            var doc = new Document(scenario);
            object result = year == 2023 ? Query2023(doc) : Query2026(doc);
            rows[year + ":" + scenario] = new { result, uid_lookups = doc.UidLookups, id_lookups = doc.IdLookups };
        }
        Console.Write(JsonSerializer.Serialize(rows));
    }
}
'''


@pytest.fixture(scope="module")
def query_rows(tmp_path_factory):
    if shutil.which("dotnet") is None:
        pytest.skip(".NET SDK unavailable; fake query fragment not executed")
    root = tmp_path_factory.mktemp("element-query-fake-api")
    source = HARNESS
    for year in ("2023", "2026"):
        fragments = [emit_element_state(op, year) for op in OPS]
        compiled = compile_program({"ops": OPS}, revit_version=year)
        assert compiled.ok, compiled.diagnostics
        for fragment in fragments:
            assert fragment in compiled.csharp  # actual public compiler, not a copied query algorithm
        source = source.replace(f"/* QUERY{year} */", "\n".join(fragments))
    source = source.replace("/* CASES */", "new[] {" + ",".join(json.dumps(s) for s in CASES) + "}")
    # Generated fixtures stay in pytest's temporary directory. The only executed
    # compiled code is the actual query fragment plus this deliberately fake API.
    (root / "Query.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
        '<OutputType>Exe</OutputType><Nullable>disable</Nullable><NuGetAudit>false</NuGetAudit>'
        '</PropertyGroup></Project>', encoding="utf-8")
    (root / "Program.cs").write_text(source, encoding="utf-8")
    build = subprocess.run(["dotnet", "build", str(root / "Query.csproj"), "-c", "Release", "--nologo"],
                           capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run(["dotnet", str(root / "bin/Release/net8.0/Query.dll")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "secret" not in run.stdout and not run.stderr
    return json.loads(run.stdout)


def level_row(rows, year, scenario):
    return rows[f"{year}:{scenario}"]["result"]["read-level"]


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_found_changed_numeric_id_and_two_operations_use_original_uid_scope(year, query_rows):
    for scenario, number in (("normal", 700), ("changed_id", 901)):
        result = query_rows[f"{year}:{scenario}"]
        row = result["result"]["read-level"]
        assert row["status"] == "observed"
        proof = ElementIdentityProof.from_dict(row["element_identity"])
        assert proof.unique_id == "level-uid" and proof.element_id == number
        assert result["uid_lookups"] == ["level-uid", "protected-uid"]
        assert result["id_lookups"] == [1000]  # type only; never recover origin by old numeric id
        protected = result["result"]["read-protected"]
        assert protected["status"] == "observed" and protected["level_status"] == "not_level"
        assert ElementIdentityProof.from_dict(protected["element_identity"]).element_id == 800
        assert protected["type_state"]["status"] == "none"


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("scenario,status,reason", [
    ("missing", "not_found", None), ("lookup_throw", "unavailable", "lookup_failed"),
    ("identity_throw", "unavailable", "identity_unavailable"),
    ("identity_mismatch", "unavailable", "identity_mismatch"),
    ("get_type_throw", "unavailable", "metadata_read_failed"),
    ("type_lookup_throw", "unavailable", "metadata_read_failed"),
    ("name_throw", "unavailable", "metadata_read_failed"),
    ("category_throw", "unavailable", "metadata_read_failed"),
])
def test_lookup_and_metadata_failures_keep_an_explicit_denominator(year, scenario, status, reason, query_rows):
    row = level_row(query_rows, year, scenario)
    assert row["requested_unique_id"] == "level-uid"
    assert row["status"] == status and row["reason"] == reason
    assert row["level"] is None and row["level_status"] == "not_evaluated"
    assert query_rows[f"{year}:{scenario}"]["result"]["read-protected"]["status"] == "observed"


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("scenario,base,reported_feet", [("normal", 0, 10), ("shared", 1, 110), ("unknown_basis", 2, 10)])
def test_level_reports_project_coordinate_and_parameter_coordinate_separately(year, scenario, base, reported_feet, query_rows):
    row = level_row(query_rows, year, scenario)
    assert row["level_status"] == "observed"
    level = row["level"]
    assert level["project_elevation_mm"] == pytest.approx(3048)
    assert level["reported_elevation_mm"] == pytest.approx(reported_feet * 304.8)
    assert level["elevation_parameter"]["value_internal_feet"] == reported_feet
    assert level["elevation_base"] == base  # raw enum state, not automatic mutation support
    assert row["type_state"]["status"] == "observed"


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("scenario,reason", [
    ("missing_elevation", "level_parameters_unavailable"), ("missing_basis", "level_parameters_unavailable"),
    ("wrong_elevation_id", "level_parameter_identity_mismatch"), ("wrong_basis_id", "level_parameter_identity_mismatch"),
    ("elevation_no_value", "level_parameters_unavailable"), ("basis_no_value", "level_parameters_unavailable"),
    ("wrong_elevation_storage", "level_parameters_unavailable"), ("wrong_basis_storage", "level_parameters_unavailable"),
    ("type_missing", "level_parameters_unavailable"), ("no_type", "level_parameters_unavailable"),
    ("project_nan", "nonfinite_level_value"), ("reported_infinity", "nonfinite_level_value"),
    ("parameter_nan", "nonfinite_level_value"), ("parameter_throw", "level_read_failed"),
    ("basis_throw", "level_read_failed"), ("name_lookup_throw", "level_read_failed"),
])
def test_incomplete_level_state_is_not_zero_or_a_successful_level_read(year, scenario, reason, query_rows):
    row = level_row(query_rows, year, scenario)
    assert row["status"] == "observed"  # element fields remain separately observed
    assert row["level_status"] == "unavailable" and row["level_reason"] == reason
    assert row["level"] is None


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("scenario,count,resolves", [
    ("localized", 1, True), ("duplicate_name", 2, False), ("missing_named_parameter", 0, False),
    ("other_named_parameter", 1, False),
])
def test_actual_observed_parameter_name_is_preserved_without_claiming_ambiguous_binding(year, scenario, count, resolves, query_rows):
    row = level_row(query_rows, year, scenario)
    assert row["level_status"] == "observed"
    parameter = row["level"]["elevation_parameter"]
    assert parameter["name"] == ("Отметка уровня" if scenario == "localized" else "Elevation")
    assert parameter["name_match_count"] == count
    assert parameter["name_resolves_builtin"] is resolves


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_read_only_type_identity_failure_and_category_absence_are_not_hidden(year, query_rows):
    readonly = level_row(query_rows, year, "read_only")
    assert readonly["level"]["elevation_parameter"]["is_read_only"] is True
    typed = level_row(query_rows, year, "type_identity_throw")
    assert typed["status"] == "observed" and typed["level_status"] == "observed"
    assert typed["type_state"]["status"] == "unavailable"
    assert typed["type_state"]["element_identity"] is None
    category = level_row(query_rows, year, "category_null")
    assert category["status"] == "observed" and category["category_id"] is None


def test_64_bit_id_axis_is_not_silently_truncated(query_rows):
    legacy = level_row(query_rows, "2023", "wide_id")
    assert legacy["status"] == "unavailable" and legacy["element_identity"] is None
    current = level_row(query_rows, "2026", "wide_id")
    assert current["status"] == "observed"
    assert ElementIdentityProof.from_dict(current["element_identity"]).element_id == 4000000000


@pytest.mark.parametrize("year", ["2023", "2026"])
@pytest.mark.parametrize("scenario,reason", [("document_modifiable", "document_modifiable"),
                                           ("document_state_throw", "document_state_unavailable")])
def test_uncommitted_or_unknown_document_state_is_not_read_as_a_revision_baseline(year, scenario, reason, query_rows):
    actual = query_rows[f"{year}:{scenario}"]
    assert actual["uid_lookups"] == [] and actual["id_lookups"] == []
    for row in actual["result"].values():
        assert row["status"] == "unavailable" and row["reason"] == reason
        assert row["level_status"] == "not_evaluated" and row["element_identity"] is None
