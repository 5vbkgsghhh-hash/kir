"""C# code obfuscation — rename user variables before sending to client.

Renames local variable declarations (var X = ..., Type X = ...) to
randomized _0x{hex} identifiers. Preserves Revit API names, C# keywords,
and .NET framework types.
"""

from __future__ import annotations

import os
import re
from typing import Optional


# C# keywords — never rename these
_CSHARP_KEYWORDS: frozenset[str] = frozenset({
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch",
    "char", "checked", "class", "const", "continue", "decimal", "default",
    "delegate", "do", "double", "else", "enum", "event", "explicit",
    "extern", "false", "finally", "fixed", "float", "for", "foreach",
    "goto", "if", "implicit", "in", "int", "interface", "internal", "is",
    "lock", "long", "namespace", "new", "null", "object", "operator",
    "out", "override", "params", "private", "protected", "public",
    "readonly", "ref", "return", "sbyte", "sealed", "short", "sizeof",
    "stackalloc", "static", "string", "struct", "switch", "this", "throw",
    "true", "try", "typeof", "uint", "ulong", "unchecked", "unsafe",
    "ushort", "using", "var", "virtual", "void", "volatile", "while",
    "async", "await", "yield", "dynamic", "nameof", "when", "where",
    "from", "select", "group", "into", "orderby", "join", "let",
    "ascending", "descending", "on", "equals",
})

# Revit API names — never rename these
_REVIT_API_NAMES: frozenset[str] = frozenset({
    # Core types
    "Document", "UIDocument", "Application", "UIApplication",
    "Transaction", "TransactionGroup", "SubTransaction",
    "Element", "ElementId", "ElementType",
    # Collections
    "FilteredElementCollector", "FilteredWorksetCollector",
    "ElementFilter", "LogicalAndFilter", "LogicalOrFilter",
    "ElementCategoryFilter", "ElementClassFilter",
    # Categories
    "BuiltInCategory", "BuiltInParameter", "Category",
    # Geometry
    "XYZ", "UV", "Line", "Arc", "Curve", "CurveLoop", "CurveArray",
    "Plane", "Transform", "BoundingBoxXYZ", "Outline",
    "Solid", "Face", "Edge", "GeometryElement", "GeometryInstance",
    "GeometryObject", "Options",
    # Elements
    "Wall", "Floor", "Ceiling", "Roof", "Door", "Window",
    "FamilyInstance", "FamilySymbol", "Family",
    "Level", "Grid", "ReferencePlane",
    "Room", "Area", "Space",
    "ViewPlan", "ViewSection", "View3D", "ViewSheet", "View",
    "Sheet", "Viewport",
    "Material", "Parameter", "ParameterSet",
    "Group", "GroupType",
    "Assembly", "AssemblyInstance", "AssemblyType",
    # DB operations
    "ElementTransformUtils", "UnitUtils",
    "InternalUnits", "DisplayUnitType", "UnitType",
    "ForgeTypeId",
    # Selection
    "Selection", "SelElementSet",
    # Overrides
    "OverrideGraphicSettings", "Color",
    # Other common types
    "TaskDialog", "ExternalEvent", "IExternalEventHandler",
    "FilterStringRule", "ParameterValueProvider",
    "FilterStringContains", "FilterStringEquals",
    "FilterNumericEquals", "FilterNumericGreater", "FilterNumericLess",
    "FilterDoubleRule", "FilterIntegerRule",
    "FilterElementIdRule", "FilterInverseRule",
    "ElementParameterFilter",
    # Collections / LINQ terms used with Revit
    "List", "IList", "ICollection", "IEnumerable",
    "Dictionary", "HashSet",
    "StringBuilder",
    # Common .NET types used in Revit context
    "Math", "Convert", "String", "Int32", "Double", "Boolean",
    "Enum", "Array", "Console", "Exception", "Type",
    "DateTime", "TimeSpan", "Guid",
    "Regex", "Match",
    "JsonConvert", "JObject", "JArray",
})

# Common .NET method/property names used in Revit — never rename
_REVIT_METHODS: frozenset[str] = frozenset({
    "doc", "uidoc", "app", "uiapp",
    "Id", "IntegerValue", "Value", "Name", "UniqueId",
    "Start", "Commit", "RollBack",
    "OfCategory", "OfClass", "WhereElementIsNotElementType",
    "WhereElementIsElementType", "ToElements", "ToElementIds",
    "FirstElement", "GetElementCount",
    "get_Parameter", "Set", "AsString", "AsDouble", "AsInteger",
    "AsValueString", "AsElementId", "HasValue",
    "Create", "NewFamilyInstance",
    "GetTypeId", "GetOrderedParameters",
    "LookupParameter", "GetParameters",
    "Location", "LocationPoint", "LocationCurve",
    "Point", "Curve", "Position", "Rotation",
    "Move", "Copy", "Rotate", "Mirror",
    "Delete", "GetElement", "GetElements",
    "get_Geometry", "GetBoundingBox",
    "Count", "Length", "Add", "Remove", "Clear",
    "Contains", "IndexOf", "ToList", "ToArray",
    "Select", "Where", "OrderBy", "GroupBy", "First",
    "FirstOrDefault", "Last", "LastOrDefault", "Any", "All",
    "Sum", "Average", "Min", "Max", "Distinct",
    "Cast", "OfType", "Aggregate",
    "ToString", "Equals", "GetHashCode", "GetType",
    "Format", "Join", "Split", "Trim", "Replace",
    "StartsWith", "EndsWith", "Substring", "ToLower", "ToUpper",
    "Parse", "TryParse",
    "Abs", "Round", "Ceiling", "Floor", "Sqrt", "Pow",
})

# Combined set of all protected names
_PROTECTED: frozenset[str] = _CSHARP_KEYWORDS | _REVIT_API_NAMES | _REVIT_METHODS

# Pattern for variable declarations:
#   var name =
#   Type name =
#   Type name;
#   specific typed declarations like int name, string name, etc.
_VAR_DECL_PATTERN = re.compile(
    r"""
    (?:^|(?<=\s)|(?<=[({,;]))    # preceded by whitespace, (, {, comma, semicolon, or start
    \s*
    (?:var|int|long|float|double|decimal|string|bool|char|byte|
       short|ushort|uint|ulong|
       [A-Z][A-Za-z0-9_]*(?:<[^>]+>)?)  # type (var, primitive, or PascalCase<Generic>)
    \s+
    ([a-z_][A-Za-z0-9_]*)        # capture group 1: variable name (camelCase or _prefix)
    \s*
    (?=[=;,)])                    # followed by =, ;, comma, or )
    """,
    re.VERBOSE | re.MULTILINE,
)

# Pattern for foreach variable:  foreach (Type name in ...)
_FOREACH_PATTERN = re.compile(
    r"""
    foreach\s*\(\s*
    (?:var|[A-Z][A-Za-z0-9_]*(?:<[^>]+>)?)\s+  # type
    ([a-z_][A-Za-z0-9_]*)                        # capture: variable name
    \s+in\s
    """,
    re.VERBOSE,
)

# Pattern for lambda parameters:  (x) => or x =>
_LAMBDA_PARAM_PATTERN = re.compile(
    r"""
    (?:
        \(\s*([a-z_][A-Za-z0-9_]*)\s*\)  # (x)
        |
        (?<=[\s,=(])                       # preceded by space, comma, =, or (
        ([a-z_][A-Za-z0-9_]*)             # x
    )
    \s*=>                                 # =>
    """,
    re.VERBOSE,
)


def _generate_hex_name() -> str:
    """Generate a random _0x{4 hex chars} variable name."""
    return f"_0x{os.urandom(2).hex()}"


def obfuscate_code(code: str) -> str:
    """Obfuscate user-defined variable names in C# code.

    - Finds local variable declarations (var x = ..., Type x = ...)
    - Replaces each unique variable name with _0x{random hex}
    - Does NOT touch Revit API names, C# keywords, or .NET framework types
    - Does NOT touch string literals or comments

    Args:
        code: C# source code string.

    Returns:
        Obfuscated code string.
    """
    return obfuscate_code_with_map(code)[0]


def obfuscate_code_with_map(code: str) -> tuple[str, dict[str, str]]:
    """Like :func:`obfuscate_code`, but also returns the rename map
    ``{original_name: obfuscated_name}``.

    Step 7 (RevitExecutionPipeline): the map is the de-obfuscation key — it
    lets the pipeline translate ``_0x…`` identifiers in client-side
    compile/runtime errors back to the names the model actually wrote before
    the repair LLM (or the user) sees them. Additive: the public
    ``obfuscate_code`` behaviour is unchanged (it now delegates here).
    """
    if not code or not code.strip():
        return code, {}

    # Step 1: Collect all user-defined variable names
    user_vars: set[str] = set()

    for match in _VAR_DECL_PATTERN.finditer(code):
        name = match.group(1)
        if name and name not in _PROTECTED and len(name) > 1:
            user_vars.add(name)

    for match in _FOREACH_PATTERN.finditer(code):
        name = match.group(1)
        if name and name not in _PROTECTED and len(name) > 1:
            user_vars.add(name)

    for match in _LAMBDA_PARAM_PATTERN.finditer(code):
        name = match.group(1) or match.group(2)
        if name and name not in _PROTECTED and len(name) > 1:
            user_vars.add(name)

    if not user_vars:
        return code, {}

    # Step 2: Generate unique replacement names
    rename_map: dict[str, str] = {}
    used_names: set[str] = set()
    for var_name in sorted(user_vars):  # sorted for determinism in tests
        new_name = _generate_hex_name()
        while new_name in used_names:
            new_name = _generate_hex_name()
        used_names.add(new_name)
        rename_map[var_name] = new_name

    # Step 3: Replace occurrences, but protect string literals and comments
    # First, extract and protect strings/comments with placeholders
    protected_segments: list[str] = []

    def _protect(match: re.Match[str]) -> str:
        text = match.group(0)
        # Don't protect interpolated strings — variables inside must be renamed
        if text.startswith('$"') or text.startswith('$@"'):
            return text
        idx = len(protected_segments)
        protected_segments.append(text)
        return f"\x00PROT{idx}\x00"

    # Protect: @"..." strings, "..." strings, '.' chars, // comments, /* */ comments
    # NOTE: Interpolated strings ($"..." and $@"...") are NOT protected so that
    # variables inside {expr} are renamed consistently with their declarations.
    protect_pattern = re.compile(
        r'\$@"(?:[^"]|"")*"'       # interpolated verbatim string — NOT protected (consumed but not replaced)
        r'|\$"(?:[^"\\]|\\.)*"'    # interpolated string — NOT protected
        r'|@"(?:[^"]|"")*"'        # verbatim string (protect)
        r'|"(?:[^"\\]|\\.)*"'      # regular string (protect)
        r"|'(?:[^'\\]|\\.)*'"      # char literal (protect)
        r"|//[^\n]*"               # line comment (protect)
        r"|/\*[\s\S]*?\*/"         # block comment (protect)
    )

    protected_code = protect_pattern.sub(_protect, code)

    # Step 4: Replace variable names with word boundary matching
    for old_name, new_name in rename_map.items():
        # Use word boundaries to avoid partial replacements
        pattern = re.compile(r'\b' + re.escape(old_name) + r'\b')
        protected_code = pattern.sub(new_name, protected_code)

    # Step 5: Restore protected segments
    def _restore(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return protected_segments[idx]

    result = re.sub(r'\x00PROT(\d+)\x00', _restore, protected_code)

    return result, rename_map
