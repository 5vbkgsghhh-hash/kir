"""Safe C# code generators for deterministic write operations.

Generates transaction-wrapped, error-handling C# code for common
write operations: set parameter, create schedule, hide/isolate, rename.

All generators:
- Wrap code in TransactionGroup + Transaction
- Handle null elements gracefully
- Return structured results with success/failed/total/working_set
- Highlight changed elements via uidoc.Selection.SetElementIds()
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _escape_csharp_string(s: str) -> str:
    """Escape a string for use in a C# regular string literal.

    Note: braces {} are NOT escaped — they have no special meaning
    in regular C# string literals (only in interpolated $"" strings).
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _coerce_ids(ids: list[Any]) -> list[int]:
    """Validate and coerce element IDs to positive integers."""
    result = []
    for eid in ids:
        try:
            val = int(eid)
            if val > 0:
                result.append(val)
        except (ValueError, TypeError):
            continue
    return result


def generate_set_parameter_code(
    target_ids: list[int],
    param_name: str,
    value: str,
    category: Optional[str] = None,
) -> str:
    """Generate C# code to set a parameter on target elements.

    Args:
        target_ids: List of ElementId integers.
        param_name: Parameter name to set (e.g., "Марка").
        value: Value to set (as string — will be auto-detected as string or numeric).
        category: Optional BuiltInCategory for collector fallback.

    Returns:
        Complete C# code string ready for execution.
    """
    safe_param = _escape_csharp_string(param_name)
    safe_value = _escape_csharp_string(value)
    ids = _coerce_ids(target_ids)

    # Determine if value is numeric
    import math
    is_numeric = False
    try:
        fval = float(value)
        if not math.isnan(fval) and not math.isinf(fval):
            is_numeric = True
    except (ValueError, TypeError):
        pass

    set_call = f'p.Set({float(value)})' if is_numeric else f'p.Set("{safe_value}")'

    # Read-back verification expression. Parameter.Set returns a bool and a
    # committed transaction can still be silently rolled back, yet a naive loop
    # counter would report every iteration as a success — that is the
    # "459 set / 0 in model" false-success bug (W2). After commit we re-read each
    # element and confirm it actually carries the intended value, then report
    # the VERIFIED count, not the attempted one.
    if is_numeric:
        _fval = float(value)
        _int_branch = (
            f' || (p2.StorageType == StorageType.Integer && p2.AsInteger() == {int(_fval)})'
            if _fval.is_integer() else ''
        )
        verify_expr = (
            f'(p2.StorageType == StorageType.Double && Math.Abs(p2.AsDouble() - {_fval}) < 1e-6)'
            + _int_branch
        )
    else:
        verify_expr = f'((p2.AsString() ?? "").Trim() == "{safe_value}".Trim())'

    ids_array = ", ".join(str(i) for i in ids)

    code = f'''
var targetIds = new int[] {{ {ids_array} }};
int setOk = 0, failed = 0;
var changedIds = new List<ElementId>();

using (var tg = new TransactionGroup(doc, "KUKI: Изменение параметра"))
{{
    tg.Start();
    using (var t = new Transaction(doc, "Set {safe_param}"))
    {{
        t.Start();
        foreach (var id in targetIds)
        {{
            var elem = doc.GetElement(new ElementId(id));
            if (elem == null) {{ failed++; continue; }}
            var p = elem.LookupParameter("{safe_param}");
            if (p == null || p.IsReadOnly) {{ failed++; continue; }}
            bool ok = {set_call};          // Parameter.Set returns bool — do NOT ignore it
            if (ok) {{ setOk++; changedIds.Add(new ElementId(id)); }}
            else {{ failed++; }}
        }}
        t.Commit();
    }}
    tg.Assimilate();
}}

// Read-back: re-read AFTER commit and count elements that TRULY hold the value.
int verified = 0;
foreach (var id in changedIds)
{{
    var e2 = doc.GetElement(id);
    if (e2 == null) continue;
    var p2 = e2.LookupParameter("{safe_param}");
    if (p2 == null) continue;
    try {{ if ({verify_expr}) verified++; }} catch {{ }}
}}

if (changedIds.Count > 0)
    uidoc.Selection.SetElementIds(changedIds);

// success == verified: the truthful, read-back-confirmed count.
return new {{
    success = verified,
    set_attempted = setOk,
    verified,
    failed,
    total = targetIds.Length,
    parameter = "{safe_param}",
    value = "{safe_value}"
}};
'''
    return code.strip()


# Common field name translations RU<->EN for schedule creation
_FIELD_TRANSLATIONS: dict[str, str] = {
    "тип": "Type", "type": "Тип",
    "длина": "Length", "length": "Длина",
    "площадь": "Area", "area": "Площадь",
    "объём": "Volume", "объем": "Volume", "volume": "Объём",
    "ширина": "Width", "width": "Ширина",
    "высота": "Height", "height": "Высота",
    "имя": "Name", "name": "Имя",
    "уровень": "Level", "level": "Уровень",
    "марка": "Mark", "mark": "Марка",
    "комментарий": "Comments", "comments": "Комментарий",
}


def generate_create_schedule_code(
    category: str,
    schedule_name: Optional[str] = None,
    fields: Optional[list[str]] = None,
) -> str:
    """Generate C# code to create a ViewSchedule.

    Args:
        category: BuiltInCategory string (e.g., "OST_Walls").
        schedule_name: Optional name for the schedule.
        fields: Optional list of field names to add.
    """
    safe_name = _escape_csharp_string(schedule_name or f"KUKI — {category}")
    safe_category = _escape_csharp_string(category)

    field_code = ""
    if fields:
        field_lines = []
        for f in fields:
            safe_f = _escape_csharp_string(f)
            # Look up alternative name from translation table
            alt_name = _FIELD_TRANSLATIONS.get(f.lower(), "")
            safe_alt = _escape_csharp_string(alt_name) if alt_name else ""
            if safe_alt:
                field_lines.append(f'''
    try {{
        var fieldName = "{safe_f}";
        var altName = "{safe_alt}";
        var fieldDef = scheduleDef.GetSchedulableFields()
            .FirstOrDefault(sf => {{
                var name = sf.GetName(doc);
                return name.Equals(fieldName, StringComparison.OrdinalIgnoreCase)
                    || name.Equals(altName, StringComparison.OrdinalIgnoreCase);
            }});
        if (fieldDef != null) schedule.Definition.AddField(fieldDef);
    }} catch {{ }}''')
            else:
                # No known translation — use case-insensitive match on original only
                field_lines.append(f'''
    try {{
        var fieldDef = scheduleDef.GetSchedulableFields()
            .FirstOrDefault(sf => sf.GetName(doc).Equals("{safe_f}", StringComparison.OrdinalIgnoreCase));
        if (fieldDef != null) schedule.Definition.AddField(fieldDef);
    }} catch {{ }}''')
        field_code = "\n".join(field_lines)

    code = f'''
using (var t = new Transaction(doc, "KUKI: Создание спецификации"))
{{
    t.Start();
    var catId = new ElementId(BuiltInCategory.{safe_category});
    var schedule = ViewSchedule.CreateSchedule(doc, catId);
    schedule.Name = "{safe_name}";
    var scheduleDef = schedule.Definition;
    {field_code}
    t.Commit();
    return new {{ success = true, schedule_name = "{safe_name}", schedule_id = schedule.Id.ToString() }};
}}
'''
    return code.strip()


def generate_hide_or_isolate_code(
    target_ids: list[int],
    action: str = "hide",
    view_name: Optional[str] = None,
) -> str:
    """Generate C# code to hide or isolate elements.

    Args:
        target_ids: List of ElementId integers.
        action: "hide" or "isolate".
        view_name: Optional specific view name (defaults to active view).
    """
    ids = _coerce_ids(target_ids)
    ids_array = ", ".join(str(i) for i in ids)
    safe_action = "Скрытие" if action == "hide" else "Изоляция"
    method = "HideElements" if action == "hide" else "IsolateElementsTemporary"

    code = f'''
var targetIds = new int[] {{ {ids_array} }};
var elementIds = targetIds.Select(id => new ElementId(id)).ToList();
var view = doc.ActiveView;

using (var t = new Transaction(doc, "KUKI: {safe_action} элементов"))
{{
    t.Start();
    view.{method}(elementIds);
    t.Commit();
}}

return new {{ success = true, action = "{action}", count = elementIds.Count }};
'''
    return code.strip()


def generate_rename_code(
    target_ids: list[int],
    new_name: str,
    mode: str = "exact",
) -> str:
    """Generate C# code to rename elements.

    Args:
        target_ids: List of ElementId integers.
        new_name: New name or name component.
        mode: "exact", "prefix", "suffix", or "replace".
    """
    ids = _coerce_ids(target_ids)
    ids_array = ", ".join(str(i) for i in ids)
    safe_name = _escape_csharp_string(new_name)

    valid_modes = {"exact", "prefix", "suffix"}
    if mode not in valid_modes:
        logger.warning("Unknown rename mode '%s', falling back to 'exact'", mode)
        mode = "exact"

    if mode == "exact":
        name_expr = f'"{safe_name}"'
    elif mode == "prefix":
        name_expr = f'"{safe_name}" + elem.Name'
    elif mode == "suffix":
        name_expr = f'elem.Name + "{safe_name}"'

    code = f'''
var targetIds = new int[] {{ {ids_array} }};
int success = 0, failed = 0;
var changedIds = new List<ElementId>();

using (var tg = new TransactionGroup(doc, "KUKI: Переименование"))
{{
    tg.Start();
    using (var t = new Transaction(doc, "Rename"))
    {{
        t.Start();
        foreach (var id in targetIds)
        {{
            var elem = doc.GetElement(new ElementId(id));
            if (elem == null) {{ failed++; continue; }}
            try
            {{
                elem.Name = {name_expr};
                success++;
                changedIds.Add(new ElementId(id));
            }}
            catch {{ failed++; }}
        }}
        t.Commit();
    }}
    tg.Assimilate();
}}

if (changedIds.Count > 0)
    uidoc.Selection.SetElementIds(changedIds);

return new {{ success, failed, total = targetIds.Length, new_name = "{safe_name}", mode = "{mode}" }};
'''
    return code.strip()


def generate_delete_elements_code(
    target_ids: list[int],
) -> str:
    """Generate C# code to delete elements from the model.

    Args:
        target_ids: List of ElementId integers to delete.

    Returns:
        Complete C# code string ready for execution.
    """
    ids = _coerce_ids(target_ids)
    ids_array = ", ".join(str(i) for i in ids)

    code = f'''
using (var tx = new Transaction(doc, "KUKI: Delete elements"))
{{
    tx.Start();
    var deleted = 0;
    foreach (var id in new int[] {{ {ids_array} }})
    {{
        try {{ doc.Delete(new ElementId(id)); deleted++; }}
        catch {{ }}
    }}
    tx.Commit();
    return new {{ success = true, deleted, total = {len(ids)} }};
}}
'''
    return code.strip()


def generate_copy_elements_code(
    target_ids: list[int],
    offset_x: float,
    offset_y: float,
    offset_z: float,
) -> str:
    """Generate C# code to copy elements with an offset.

    Args:
        target_ids: List of ElementId integers to copy.
        offset_x: X offset in millimeters.
        offset_y: Y offset in millimeters.
        offset_z: Z offset in millimeters.

    Returns:
        Complete C# code string ready for execution.
    """
    offset_x, offset_y, offset_z = float(offset_x), float(offset_y), float(offset_z)
    import math
    for val, name in [(offset_x, "offset_x"), (offset_y, "offset_y"), (offset_z, "offset_z")]:
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"{name} must be a finite number, got {val}")
    ids = _coerce_ids(target_ids)
    ids_init = ", ".join(f"new ElementId({i})" for i in ids)

    code = f'''
using (var tx = new Transaction(doc, "KUKI: Copy elements"))
{{
    tx.Start();
    var ids = new List<ElementId> {{ {ids_init} }};
    var offset = new XYZ({offset_x}/304.8, {offset_y}/304.8, {offset_z}/304.8);
    var copied = ElementTransformUtils.CopyElements(doc, ids, offset);
    tx.Commit();
    return new {{ success = true, copied_count = copied.Count, offset_mm = new {{ x = {offset_x}, y = {offset_y}, z = {offset_z} }} }};
}}
'''
    return code.strip()


# create_element (2026-07-04): recovery query for the timeout-unconfirmed hole.
# BuiltInCategory token allowlist-shape only — never interpolate a raw string.
_RECOVERY_OST_RE = re.compile(r"^OST_[A-Za-z0-9_]{1,64}$")


def generate_create_recovery_code(op_id: str, category: str) -> str:
    """Generate READ-ONLY C# that finds elements stamped with the create's
    correlation ``op_id`` (ALL_MODEL_INSTANCE_COMMENTS) inside one category.

    This is the §2.6 recovery/idempotency probe for
    ``apply_revit_write(operation="create_element")``: after a
    TRANSPORT_TOOL_BUDGET_EXCEEDED / bridge timeout the handler runs this ONE
    query — found ⇒ late-confirmed success (no double-create), not found ⇒
    honest "not committed, safe to retry".

    Raises ValueError when ``category`` is not a plausible OST_* token
    (defense against C# injection through a model-derived category string).
    """
    if not _RECOVERY_OST_RE.match(category or ""):
        raise ValueError(f"invalid BuiltInCategory token: {category!r}")
    safe_op = _escape_csharp_string(op_id or "")

    code = f'''
var __found = new List<Dictionary<string, object>>();
try
{{
    foreach (Element __e in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.{category}).WhereElementIsNotElementType())
    {{
        string __c = null;
        try {{ var __p = __e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__p != null) __c = __p.AsString(); }} catch {{ }}
        if (__c != "{safe_op}") continue;
        var __d = new Dictionary<string, object>();
        try {{ __d["id"] = long.Parse(__e.Id.ToString()); }} catch {{ continue; }}
        try {{ __d["name"] = __e.Name ?? ""; }} catch {{ }}
        try {{ __d["category"] = (__e.Category != null) ? __e.Category.BuiltInCategory.ToString() : ""; }} catch {{ }}
        __found.Add(__d);
    }}
}}
catch {{ }}
var __r = new Dictionary<string, object>();
__r["found"] = __found;
__r["op_id"] = "{safe_op}";
return __r;
'''
    return code.strip()


def generate_move_elements_code(
    target_ids: list[int],
    offset_x: float,
    offset_y: float,
    offset_z: float,
) -> str:
    """Generate C# code to move elements by an offset.

    Args:
        target_ids: List of ElementId integers to move.
        offset_x: X offset in millimeters.
        offset_y: Y offset in millimeters.
        offset_z: Z offset in millimeters.

    Returns:
        Complete C# code string ready for execution.
    """
    offset_x, offset_y, offset_z = float(offset_x), float(offset_y), float(offset_z)
    import math
    for val, name in [(offset_x, "offset_x"), (offset_y, "offset_y"), (offset_z, "offset_z")]:
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"{name} must be a finite number, got {val}")
    ids = _coerce_ids(target_ids)
    ids_init = ", ".join(f"new ElementId({i})" for i in ids)

    code = f'''
using (var tx = new Transaction(doc, "KUKI: Move elements"))
{{
    tx.Start();
    var ids = new List<ElementId> {{ {ids_init} }};
    var offset = new XYZ({offset_x}/304.8, {offset_y}/304.8, {offset_z}/304.8);
    ElementTransformUtils.MoveElements(doc, ids, offset);
    tx.Commit();
    return new {{ success = true, moved_count = ids.Count, offset_mm = new {{ x = {offset_x}, y = {offset_y}, z = {offset_z} }} }};
}}
'''
    return code.strip()
