"""Bounded native element-state reading for reconciliation, not a write API.

The query resolves a supplied same-document UniqueId. It cannot establish that
the caller originally created/owned it, select its document, or provide a live
revision by itself. Connector query assessment supplies the execution binding;
the observation consumer must additionally validate the requested field scope.
"""
from __future__ import annotations

from kir.emit_utils import cs_identifier_fragment, cs_line_comment_fragment


ELEMENT_STATE_SCHEMA = "kir-element-state/1"
TYPE_DEFINITION_STATE_SCHEMA = "kir-element-state/2"


def validate_unique_id(value, op_id, diagnostics, fail):
    from kir import spec

    cap = spec.OPS["query_element_state"].params[0].max_val
    if not isinstance(value, str) or not value.strip():
        fail(diagnostics, code="KIR-T001", op_id=op_id, field_name="unique_id",
             expected="nonempty opaque UniqueId", got=value,
             message_ru="unique_id — непустой идентификатор ранее прочитанного элемента")
        return None
    if len(value) > cap:
        fail(diagnostics, code="KIR-T002", op_id=op_id, field_name="unique_id",
             expected=f"at most {cap} characters", got=len(value),
             message_ru=f"unique_id превышает предел {cap} символов")
        return None
    # Opaque identity is neither a name nor a canonicalizable UUID. In
    # particular, never trim, case-fold, or fall back to numeric/name lookup.
    return value


def validate_element_query(op, op_id, diagnostics, fail):
    uid = validate_unique_id(op.get("unique_id"), op_id, diagnostics, fail)
    flag = op.get("include_type_definition", False)
    if type(flag) is not bool:
        fail(diagnostics, code="KIR-T001", op_id=op_id, field_name="include_type_definition",
             expected="boolean", got=flag,
             message_ru="include_type_definition — логический флаг true/false")
    result = {"unique_id": uid} if uid is not None else {}
    if uid is not None and flag is True:
        result["include_type_definition"] = True
    return result


def _type_definition_cs(element, row, revit_version):
    """Read actual parallel-layer facts, never requested values or type writes."""
    from kir import spec
    from kir.emit_core import element_identity_readback_cs
    id_member = "Value" if revit_version >= "2024" else "IntegerValue"
    material_identity = element_identity_readback_cs(
        "__definitionMaterial", revit_version=revit_version, rb_var="__materialIdentity")
    return f'''    var __definition = (Dictionary<string, object>){row}["type_definition"];
    if ((string){row}["status"] == "observed")
    {{
        try
        {{
            var __wallType = {element} as WallType;
            var __floorType = {element} as FloorType;
            if (__wallType == null && __floorType == null)
            {{
                __definition["status"] = "not_applicable";
                __definition["reason"] = "unsupported_element_kind";
            }}
            else if (__wallType != null && __wallType.Kind != WallKind.Basic)
            {{
                __definition["status"] = "not_applicable";
                __definition["reason"] = "unsupported_wall_kind";
            }}
            else
            {{
                __definition["reason"] = "definition_getter_failed";
                var __structure = __wallType != null ? __wallType.GetCompoundStructure() : __floorType.GetCompoundStructure();
                if (__structure == null) __definition["reason"] = "compound_structure_missing";
                else if (!__structure.IsVerticallyHomogeneous())
                {{
                    __definition["status"] = "not_applicable";
                    __definition["reason"] = "non_simple_compound_structure";
                }}
                else
                {{
                    var __layers = __structure.GetLayers();
                    if (__layers == null) __definition["reason"] = "layers_unavailable";
                    else if (__layers.Count < 1 || __layers.Count > {spec.WALL_LAYERS_MAX})
                        __definition["reason"] = "layer_count_outside_profile";
                    else
                    {{
                        double __width = UnitUtils.ConvertFromInternalUnits(
                            __wallType != null ? __wallType.Width : __structure.GetWidth(), UnitTypeId.Millimeters);
                        if (double.IsNaN(__width) || double.IsInfinity(__width) || __width < 0)
                            __definition["reason"] = "invalid_width";
                        else
                        {{
                            var __observedLayers = new List<object>();
                            var __nameCounts = new Dictionary<string, int>(StringComparer.Ordinal);
                            bool __completeDefinition = true;
                            foreach (var __layer in __layers)
                            {{
                                double __layerWidth = UnitUtils.ConvertFromInternalUnits(__layer.Width, UnitTypeId.Millimeters);
                                if (double.IsNaN(__layerWidth) || double.IsInfinity(__layerWidth) || __layerWidth < 0)
                                {{ __completeDefinition = false; __definition["reason"] = "invalid_width"; break; }}
                                var __materialId = __layer.MaterialId;
                                if (__materialId == null)
                                {{ __completeDefinition = false; __definition["reason"] = "material_id_unavailable"; break; }}
                                long __materialNumber = (long)__materialId.{id_member};
                                string __materialName = null;
                                object __materialProof = null;
                                object __materialNameCount = null;
                                if (__materialId != ElementId.InvalidElementId)
                                {{
                                    if (__materialNumber <= 0)
                                    {{ __completeDefinition = false; __definition["reason"] = "material_id_unavailable"; break; }}
                                    var __definitionMaterial = doc.GetElement(__materialId) as Material;
                                    if (__definitionMaterial == null)
                                    {{ __completeDefinition = false; __definition["reason"] = "material_missing"; break; }}
                                    var __materialIdentity = new Dictionary<string, object>();
{material_identity}
                                    if ((string)__materialIdentity["element_identity_status"] != "captured")
                                    {{ __completeDefinition = false; __definition["reason"] = "material_identity_unavailable"; break; }}
                                    __materialProof = __materialIdentity["element_identity"];
                                    if ((long)((Dictionary<string, object>)__materialProof)["element_id"] != __materialNumber)
                                    {{ __completeDefinition = false; __definition["reason"] = "material_identity_mismatch"; break; }}
                                    __materialName = __definitionMaterial.Name;
                                    if (__materialName == null)
                                    {{ __completeDefinition = false; __definition["reason"] = "material_name_unavailable"; break; }}
                                    if (!__nameCounts.ContainsKey(__materialName))
                                        __nameCounts[__materialName] = new FilteredElementCollector(doc).OfClass(typeof(Material))
                                            .Cast<Material>().Count(__m => __m.Name == __materialName);
                                    __materialNameCount = __nameCounts[__materialName];
                                }}
                                var __layerRow = new Dictionary<string, object>();
                                __layerRow["width_mm"] = __layerWidth;
                                __layerRow["function"] = __layer.Function.ToString();
                                __layerRow["material_id"] = __materialNumber;
                                __layerRow["material_name"] = __materialName;
                                __layerRow["material_identity"] = __materialProof;
                                __layerRow["material_name_match_count"] = __materialNameCount;
                                __observedLayers.Add(__layerRow);
                            }}
                            if (__completeDefinition)
                            {{
                                var __value = new Dictionary<string, object>();
                                __value["host_kind"] = __wallType != null ? "wall" : "floor";
                                __value["wall_kind"] = __wallType != null ? "Basic" : null;
                                __value["is_vertically_compound"] = __structure.IsVerticallyCompound;
                                __value["is_vertically_homogeneous"] = true;
                                __value["name"] = {element}.Name;
                                __value["total_width_mm"] = __width;
                                __value["layers"] = __observedLayers;
                                __definition["value"] = __value;
                                __definition["status"] = "observed";
                                __definition["reason"] = null;
                            }}
                        }}
                    }}
                }}
            }}
        }}
        catch
        {{
            __definition["status"] = "unavailable";
            __definition["reason"] = "definition_getter_failed";
            __definition["value"] = null;
        }}
    }}
'''


def emit_element_state(op: dict, revit_version: str) -> str:
    from kir.emit_core import _cs, element_identity_readback_cs

    suffix = cs_identifier_fragment(op["id"])
    element = "__stateElement_" + suffix
    row = "__stateRow_" + suffix
    type_element = "__stateType_" + suffix
    type_row = "__stateTypeRow_" + suffix
    identity = element_identity_readback_cs(element, revit_version=revit_version, rb_var=row)
    type_identity = element_identity_readback_cs(type_element, revit_version=revit_version, rb_var=type_row)
    id_member = "Value" if revit_version >= "2024" else "IntegerValue"
    include_definition = op.get("include_type_definition") is True
    schema = TYPE_DEFINITION_STATE_SCHEMA if include_definition else ELEMENT_STATE_SCHEMA
    definition_init = (f'    {row}["type_definition"] = new Dictionary<string, object> '
        '{ {"status", "unavailable"}, {"reason", "base_observation_unavailable"}, {"value", null} };\n'
        if include_definition else "")
    definition_read = _type_definition_cs(element, row, revit_version) if include_definition else ""

    return f'''// query_element_state {cs_line_comment_fragment(op["id"])}
{{
    var {row} = new Dictionary<string, object>();
    {row}["schema_version"] = "{schema}";
    {row}["requested_unique_id"] = {_cs(op["unique_id"])};
    {row}["status"] = "unavailable";
    {row}["reason"] = "lookup_failed";
    {row}["name"] = null;
    {row}["category_id"] = null;
    {row}["is_level"] = null;
    {row}["type_state"] = null;
    {row}["level_status"] = "not_evaluated";
    {row}["level_reason"] = null;
    {row}["level"] = null;
{definition_init}    Element {element} = null;
    bool __lookupComplete = false;
    bool __documentReady = false;
    try
    {{
        __documentReady = !doc.IsModifiable;
        if (!__documentReady) {row}["reason"] = "document_modifiable";
    }}
    catch {{ {row}["reason"] = "document_state_unavailable"; }}
    if (__documentReady)
        try {{ {element} = doc.GetElement({_cs(op["unique_id"])}); __lookupComplete = true; }} catch {{ }}
    {identity}
    if (__lookupComplete && {element} == null)
    {{
        {row}["status"] = "not_found";
        {row}["reason"] = null;
    }}
    else if ({element} != null && (string){row}["element_identity_status"] == "captured")
    {{
        var __observedIdentity = (Dictionary<string, object>){row}["element_identity"];
        if (!String.Equals((string)__observedIdentity["unique_id"], {_cs(op["unique_id"])}, StringComparison.Ordinal))
            {row}["reason"] = "identity_mismatch";
        else try
        {{
            {row}["name"] = {element}.Name;
            var __category = {element}.Category;
            {row}["category_id"] = __category == null ? null : (object)(long)__category.Id.{id_member};
            {row}["is_level"] = {element} is Level;
            var __typeId = {element}.GetTypeId();
            Element {type_element} = __typeId == ElementId.InvalidElementId ? null : doc.GetElement(__typeId);
            var {type_row} = new Dictionary<string, object>();
            {type_identity}
            {type_row}["status"] = __typeId == ElementId.InvalidElementId ? "none"
                : ((string){type_row}["element_identity_status"] == "captured" ? "observed" : "unavailable");
            {row}["type_state"] = {type_row};
            {row}["status"] = "observed";
            {row}["reason"] = null;
            var __level = {element} as Level;
            if (__level == null) {row}["level_status"] = "not_level";
            else
            {{
                {row}["level_status"] = "unavailable";
                {row}["level_reason"] = "level_read_failed";
                try
                {{
                    var __elevation = __level.get_Parameter(BuiltInParameter.LEVEL_ELEV);
                    var __basis = {type_element} == null ? null : {type_element}.get_Parameter(BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE);
                    if (__elevation == null || __basis == null || !__elevation.HasValue || !__basis.HasValue
                        || __elevation.StorageType != StorageType.Double || __basis.StorageType != StorageType.Integer)
                        {row}["level_reason"] = "level_parameters_unavailable";
                    else if ((long)__elevation.Id.{id_member} != (long)BuiltInParameter.LEVEL_ELEV
                             || (long)__basis.Id.{id_member} != (long)BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE)
                        {row}["level_reason"] = "level_parameter_identity_mismatch";
                    else
                    {{
                        double __projectMm = UnitUtils.ConvertFromInternalUnits(__level.ProjectElevation, UnitTypeId.Millimeters);
                        double __reportedMm = UnitUtils.ConvertFromInternalUnits(__level.Elevation, UnitTypeId.Millimeters);
                        double __parameterFeet = __elevation.AsDouble();
                        if (double.IsNaN(__projectMm) || double.IsInfinity(__projectMm)
                            || double.IsNaN(__reportedMm) || double.IsInfinity(__reportedMm)
                            || double.IsNaN(__parameterFeet) || double.IsInfinity(__parameterFeet))
                            {row}["level_reason"] = "nonfinite_level_value";
                        else
                        {{
                            string __parameterName = __elevation.Definition.Name;
                            var __sameName = __level.GetParameters(__parameterName);
                            var __parameterRow = new Dictionary<string, object>();
                            __parameterRow["builtin"] = "LEVEL_ELEV";
                            __parameterRow["parameter_id"] = (long)__elevation.Id.{id_member};
                            __parameterRow["name"] = __parameterName;
                            __parameterRow["storage_type"] = __elevation.StorageType.ToString();
                            __parameterRow["is_read_only"] = __elevation.IsReadOnly;
                            __parameterRow["value_internal_feet"] = __parameterFeet;
                            __parameterRow["name_match_count"] = __sameName.Count;
                            __parameterRow["name_resolves_builtin"] = __sameName.Count == 1 && __sameName[0].Id == __elevation.Id;
                            var __levelRow = new Dictionary<string, object>();
                            __levelRow["project_elevation_mm"] = __projectMm;
                            __levelRow["reported_elevation_mm"] = __reportedMm;
                            __levelRow["elevation_base"] = __basis.AsInteger();
                            __levelRow["basis_parameter_id"] = (long)__basis.Id.{id_member};
                            __levelRow["elevation_parameter"] = __parameterRow;
                            {row}["level"] = __levelRow;
                            {row}["level_status"] = "observed";
                            {row}["level_reason"] = null;
                        }}
                    }}
                }}
                catch {{ }}
            }}
        }}
        catch
        {{
            {row}["status"] = "unavailable";
            {row}["reason"] = "metadata_read_failed";
        }}
    }}
    else if (__lookupComplete) {row}["reason"] = "identity_unavailable";
{definition_read}    __results[{_cs(op["id"])}] = {row};
}}'''
