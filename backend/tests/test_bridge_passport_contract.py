"""Source-level gates for the Revit-side passport algorithm and coverage."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = (
    ROOT
    / "src"
    / "Kukai.Revit.Bridge"
    / "Context"
    / "ContextCollector.cs"
)


def _source() -> str:
    return COLLECTOR.read_text(encoding="utf-8")


def test_parameter_binding_collector_is_inverted_to_two_model_passes() -> None:
    source = _source()
    start = source.index("private static (List<ParameterInfo> shared")
    end = source.index("/// <summary>", start + 20)
    method = source[start:end]

    assert "BuildCategorySampleIndexes(" in method
    assert "sample_definition_id" in method
    assert "sample_shared_guid" in method
    assert ".OfCategory(bic)" not in method
    assert "LookupParameter(definition.Name)" not in method


def test_family_hierarchy_is_two_linear_passes_not_collectors_per_category() -> None:
    source = _source()
    start = source.index(
        "private static Dictionary<string, List<FamilyTypeGroup>> "
        "GetFamilyTypeHierarchy"
    )
    end = source.index(
        "private sealed class FamilyHierarchyCategoryIndex", start
    )
    method = source[start:end]
    assert method.count("new FilteredElementCollector(doc)") == 2
    assert ".OfCategory(" not in method
    assert "TypeInstanceCounts" in method
    assert "WhereElementIsNotElementType()" in method
    assert "WhereElementIsElementType()" in method


def test_shared_parameter_identity_comes_from_document_element() -> None:
    source = _source()
    assert "as SharedParameterElement" in source
    assert 'sharedElement.GuidValue.ToString("D")' in source
    assert "DefinitionId" in source


def test_every_partial_passport_discloses_coverage_and_real_time() -> None:
    source = _source()
    assert 'SchemaVersion { get; set; } = "detailed-passport/2"' in source
    assert "CompletedSections" in source
    assert "PendingSections" in source
    assert "SectionTimingsMs" in source
    assert "SectionErrors" in source
    assert "passport.CollectionTimeMs = global.ElapsedMilliseconds" in source

    detailed_start = source.index("public string CollectDetailedAsJson")
    detailed_end = source.index(
        "private static readonly string[] DetailedSectionOrder",
        detailed_start,
    )
    detailed = source[detailed_start:detailed_end]
    assert "return Serialize(passport);" not in detailed
    assert detailed.count("FinishDetailedPassport(") >= 15
