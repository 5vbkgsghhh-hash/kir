"""Deterministic C# code generator for PDF sheet export.

Generates code that uses doc.Export() (Autodesk.Revit.DB.Document method),
which is NOT System.IO and passes security validation.
"""

from __future__ import annotations


# Map quality names to PDFExportQualityType enum values
_QUALITY_MAP = {
    "draft": "DPI150",
    "standard": "DPI300",
    "high": "DPI600",
}


def generate_pdf_export_code(
    export_dir: str,
    sheet_ids: list[int] | None = None,
    combine: bool = False,
    quality: str = "standard",
) -> str:
    """Generate C# code body for PDF export via doc.Export().

    The generated code:
    1. Collects sheet ElementIds (specified or all)
    2. Configures PDFExportOptions
    3. Calls doc.Export(folder, viewIds, options)
    4. Returns result summary as JSON-serializable object

    Args:
        export_dir: Absolute path to export directory (created by Python beforehand).
        sheet_ids: List of sheet ElementIds. None/empty = export all sheets.
        combine: If True, combine all sheets into one PDF.
        quality: Export quality — "draft", "standard", or "high".

    Returns:
        C# code string (method body only, no class/namespace wrapper).
    """
    quality_enum = _QUALITY_MAP.get(quality, "DPI300")
    combine_str = "true" if combine else "false"

    # Escape backslashes for C# string literal
    safe_dir = export_dir.replace("\\", "\\\\")

    if sheet_ids:
        # Specific sheets
        ids_str = ", ".join(f"new ElementId({sid})" for sid in sheet_ids)
        collect_code = f"var sheetIds = new List<ElementId> {{ {ids_str} }};"
    else:
        # All sheets
        collect_code = (
            "var sheetIds = new FilteredElementCollector(doc)\n"
            "    .OfClass(typeof(ViewSheet))\n"
            "    .Cast<ViewSheet>()\n"
            "    .Where(s => !s.IsPlaceholder)\n"
            "    .Select(s => s.Id)\n"
            "    .ToList();"
        )

    return f"""{collect_code}

if (sheetIds.Count == 0)
    return new {{ success = false, message = "Нет листов для экспорта" }};

var options = new PDFExportOptions();
options.Combine = {combine_str};
options.ExportQuality = PDFExportQualityType.{quality_enum};
options.HideScopeBoxes = true;
options.HideCropBoundaries = true;
options.HideReferencePlane = true;
options.HideUnreferencedViewTags = true;

var exportDir = @"{safe_dir}";
var exported = doc.Export(exportDir, sheetIds, options);

// Collect sheet names for the result
var sheetNames = sheetIds
    .Select(id => doc.GetElement(id))
    .Where(e => e != null)
    .Select(e => new {{
        id = e.Id.Value,
        number = (e as ViewSheet)?.SheetNumber ?? "",
        name = e.Name
    }})
    .ToList();

return new {{
    success = exported,
    exported_count = sheetIds.Count,
    export_dir = exportDir,
    sheets = sheetNames,
    message = exported
        ? $"Экспортировано {{sheetIds.Count}} листов в PDF"
        : "Ошибка экспорта PDF — проверьте настройки принтера"
}};"""
