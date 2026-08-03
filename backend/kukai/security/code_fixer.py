"""
RevitCodeFixer — deterministic post-processor for LLM-generated Revit API code.

Like a spell checker: LLM writes approximately correct code,
the fixer automatically corrects common mistakes before compilation.

Applied AFTER LLM generates code, BEFORE wrapping in namespace/class.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Mapping: wrong BuiltInParameter name -> correct BuiltInParameter name
# ---------------------------------------------------------------------------
PARAM_FIXES: dict[str, str] = {
    # Wall parameters
    "WALL_LENGTH_PARAM": "CURVE_ELEM_LENGTH",
    "WALL_LENGTH": "CURVE_ELEM_LENGTH",
    "WALL_HEIGHT_PARAM": "WALL_USER_HEIGHT_PARAM",
    "WALL_HEIGHT": "WALL_USER_HEIGHT_PARAM",
    "WALL_WIDTH_PARAM": "WALL_ATTR_WIDTH_PARAM",
    "WALL_WIDTH": "WALL_ATTR_WIDTH_PARAM",
    "WALL_THICKNESS": "WALL_ATTR_WIDTH_PARAM",
    "WALL_BASE_LEVEL": "WALL_BASE_CONSTRAINT",
    "WALL_TOP_LEVEL": "WALL_TOP_CONSTRAINT",
    "WALL_BASE_OFFSET_PARAM": "WALL_BASE_OFFSET",
    "WALL_TOP_OFFSET_PARAM": "WALL_TOP_OFFSET",

    # Room parameters
    "ROOM_NAME_PARAM": "ROOM_NAME",
    "ROOM_NUMBER_PARAM": "ROOM_NUMBER",
    "ROOM_AREA_PARAM": "ROOM_AREA",
    "ROOM_VOLUME_PARAM": "ROOM_VOLUME",
    "ROOM_PERIMETER_PARAM": "ROOM_PERIMETER",
    "ROOM_HEIGHT_PARAM": "ROOM_HEIGHT",
    "ROOM_DEPARTMENT_PARAM": "ROOM_DEPARTMENT",

    # Door/Window parameters
    "DOOR_WIDTH_PARAM": "DOOR_WIDTH",
    "DOOR_HEIGHT_PARAM": "DOOR_HEIGHT",
    "WINDOW_WIDTH_PARAM": "WINDOW_WIDTH",
    "WINDOW_HEIGHT_PARAM": "WINDOW_HEIGHT",
    "INSTANCE_HEAD_HEIGHT": "INSTANCE_HEAD_HEIGHT_PARAM",
    "INSTANCE_SILL_HEIGHT": "INSTANCE_SILL_HEIGHT_PARAM",

    # Level parameters
    "LEVEL_ELEVATION": "LEVEL_ELEV",
    "LEVEL_ELEVATION_PARAM": "LEVEL_ELEV",
    "LEVEL_HEIGHT": "LEVEL_ELEV",
    "LEVEL_NAME_PARAM": "DATUM_TEXT",

    # Sheet parameters
    "SHEET_NUMBER_PARAM": "SHEET_NUMBER",
    "SHEET_NAME_PARAM": "SHEET_NAME",
    "SHEET_DRAWN_BY_PARAM": "SHEET_DRAWN_BY",

    # View parameters
    "VIEW_SCALE_PARAM": "VIEW_SCALE",
    "VIEW_NAME_PARAM": "VIEW_NAME",
    "VIEW_DETAIL_LEVEL_PARAM": "VIEW_DETAIL_LEVEL",

    # General
    "ALL_MODEL_MARK_PARAM": "ALL_MODEL_MARK",
    "MARK_PARAM": "ALL_MODEL_MARK",
    "MARK": "ALL_MODEL_MARK",
    "ALL_MODEL_COMMENTS": "ALL_MODEL_INSTANCE_COMMENTS",
    "COMMENTS_PARAM": "ALL_MODEL_INSTANCE_COMMENTS",
    "ELEM_FAMILY_PARAM_NAME": "ELEM_FAMILY_PARAM",
    "ELEM_TYPE_PARAM_NAME": "ELEM_TYPE_PARAM",
    "SYMBOL_NAME": "SYMBOL_NAME_PARAM",

    # Structural
    "STRUCTURAL_MATERIAL": "STRUCTURAL_MATERIAL_PARAM",
    "STRUCTURAL_VOLUME": "HOST_VOLUME_COMPUTED",
    "STRUCTURAL_AREA": "HOST_AREA_COMPUTED",
    "ELEMENT_VOLUME": "HOST_VOLUME_COMPUTED",
    "ELEMENT_AREA": "HOST_AREA_COMPUTED",

    # Length/area common mistakes
    "ELEMENT_LENGTH": "CURVE_ELEM_LENGTH",
    "LENGTH_PARAM": "CURVE_ELEM_LENGTH",
    "AREA_PARAM": "HOST_AREA_COMPUTED",
    "VOLUME_PARAM": "HOST_VOLUME_COMPUTED",

    # Floor parameters
    "FLOOR_AREA": "HOST_AREA_COMPUTED",
    "FLOOR_AREA_PARAM": "HOST_AREA_COMPUTED",
    "FLOOR_THICKNESS": "FLOOR_ATTR_THICKNESS_PARAM",

    # Ceiling parameters
    "CEILING_HEIGHT": "CEILING_HEIGHTABOVELEVEL_PARAM",

    # General element
    "ELEM_FAMILY_NAME": "ELEM_FAMILY_PARAM",
    "ELEM_TYPE_NAME": "ELEM_TYPE_PARAM",
    "ELEMENT_NAME": "ALL_MODEL_MARK",

    # Pipe/Duct
    "PIPE_DIAMETER": "RBS_PIPE_DIAMETER_PARAM",
    "DUCT_SIZE": "RBS_DUCT_SIZE_PARAM",
    "PIPE_LENGTH": "CURVE_ELEM_LENGTH",
    "DUCT_LENGTH": "CURVE_ELEM_LENGTH",
}

# Pre-compile regex patterns for parameter fixes (word-boundary matching)
_PARAM_REGEXES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bBuiltInParameter\." + re.escape(wrong) + r"\b"),
        f"BuiltInParameter.{correct}",
    )
    for wrong, correct in PARAM_FIXES.items()
]

# Regex for OfCategory without BuiltInCategory prefix
_CATEGORY_RE = re.compile(r"OfCategory\(\s*(OST_\w+)\s*\)")

# Regex for Console.WriteLine
_CONSOLE_RE = re.compile(r"^\s*Console\.WriteLine\(.*\);\s*$", re.MULTILINE)

# Regex for FilteredElementCollector chain
_FEC_TO_ELEMENTS_RE = re.compile(
    r"(\.OfCategory\([^)]+\))"
    r"((?:\s*\.\w+\([^)]*\))*?)"   # optional chained calls
    r"(\s*\.(?:ToElements|ToList|GetElementCount|FirstElement)\(\))",
)

# FilteredElementCollector + LINQ method (the #1 production failure).
# FEC implements non-generic IEnumerable, so .Cast/.Any/.First/.ToList/.Where/.Select
# all fail with CS1061. Insert .OfType<Element>() before the LINQ call.
# Only matches when the chain is rooted at FilteredElementCollector to avoid
# touching generic IEnumerable<Element> chains that already work.
_FEC_LINQ_METHODS = ("Cast", "Any", "First", "FirstOrDefault", "Single",
                     "SingleOrDefault", "Last", "LastOrDefault",
                     "Where", "Select", "OrderBy", "OrderByDescending",
                     "GroupBy", "Take", "Skip", "ToList", "ToArray",
                     "Count", "Sum", "Min", "Max")
# Balanced single-level paren matcher — handles patterns like OfClass(typeof(Wall))
# where one level of nesting is needed. Two levels is rare in Revit chains.
_PAREN_BAL = r"\([^()]*(?:\([^()]*\)[^()]*)*\)"
_FEC_LINQ_RE = re.compile(
    r"(new\s+FilteredElementCollector" + _PAREN_BAL +    # root: new FEC(doc)
    r"(?:\s*\.\w+" + _PAREN_BAL + r")*?)"                # zero or more chained calls
    r"(\s*\.)"                                            # the dot before the LINQ method
    r"(" + "|".join(_FEC_LINQ_METHODS) + r")"             # the LINQ method name
    r"(\s*[(<])"                                          # opening paren or generic <
)


class RevitCodeFixer:
    """Deterministic fixer for common LLM mistakes in Revit API C# code."""

    def __init__(self, revit_version: str = ""):
        self._version = revit_version
        self._version_year = 0
        if revit_version:
            try:
                self._version_year = int(revit_version[:4])
            except ValueError:
                pass

    def fix_from_error(self, code: str, error_message: str) -> str | None:
        """Try to fix code based on a known compilation error pattern.

        Returns fixed code if a known fix exists, None otherwise.
        Saves an LLM round-trip for common errors.

        Rules below are mined from 24h of production compile-fail logs
        (2026-05-12 → 2026-05-13). Each rule:
          - matches a specific CS-code + class-name + member-name signature
            so it CANNOT fire on unrelated code
          - returns None if regex didn't actually change anything (lets the
            LLM repair-loop try a real fix instead of looping on a no-op)
        """
        error_lower = error_message.lower()

        # CS1061: LINQ method on FilteredElementCollector. The #1 production
        # failure: FEC implements non-generic IEnumerable, so .Cast/.Any/.First/
        # .ToList/.Where/.Select all fail. Fix: insert .OfType<Element>() before.
        if (
            "cs1061" in error_lower
            and "filteredelementcollector" in error_lower
            and "не содержит определения" in error_lower
            or (
                "cs1061" in error_lower
                and "filteredelementcollector" in error_lower
                and "does not contain" in error_lower
            )
        ):
            fixed = self.fix_fec_linq(code)
            if fixed != code:
                return fixed

        # CS0117/CS1061: 'ElementId' does not contain 'IntegerValue'
        if "integervalue" in error_lower and ("cs0117" in error_lower or "cs1061" in error_lower):
            return re.sub(r'\.IntegerValue\b', '.Value', code)

        # CS0117/CS1061: 'ElementId' does not contain 'Value' (old Revit ≤2023)
        # PRECISE: only rewrite .Value that follows an ElementId-yielding token,
        # never kv.Value / nullable.Value (the old blind sub corrupted those).
        if ("does not contain" in error_lower
                and "value" in error_lower
                and "elementid" in error_lower):
            fixed = re.sub(r'\b(\w*[Ii]d(?:\(\))?)\.Value\b', r'\1.IntegerValue', code)
            return fixed if fixed != code else None

        # CS0246: type 'DisplayUnitType' not found (Revit 2022+)
        if "displayunittype" in error_lower and "cs0246" in error_lower:
            # Can't auto-fix ForgeTypeId -- too complex. Return None.
            return None

        # ─────────────────────────────────────────────────────────────
        # PROD HALLUCINATIONS (mined 2026-05-13 — top 80 compile-fails)
        # Each rule fires only on a precise CS-code + member-name match.
        # ─────────────────────────────────────────────────────────────

        # CS1061: 'Wall' does not contain 'GetInsertedElementIds' (4 prod cases)
        # Gemini invents .GetInsertedElementIds() — real API is .FindInserts(...)
        # taking 4 bools (addRectangularOpenings, includeShadows, includeEmbedded,
        # includeSharedEmbeddedInserts). Use (true,true,true,true) by default.
        if ("cs1061" in error_lower
                and "'wall'" in error_lower
                and "getinsertedelementids" in error_lower):
            fixed = re.sub(
                r'(\b\w+)\.GetInsertedElementIds\s*\(\s*\)',
                r'\1.FindInserts(true, true, true, true)',
                code,
            )
            if fixed != code:
                return fixed

        # CS0117: BuiltInCategory.OST_ScopeBox / OST_ScopeBoxes (3 cases)
        # Real value is OST_VolumeOfInterest.
        if ("cs0117" in error_lower
                and "builtincategory" in error_lower
                and "ost_scopebox" in error_lower):
            fixed = re.sub(
                r'\bBuiltInCategory\.OST_ScopeBoxe?s?\b',
                'BuiltInCategory.OST_VolumeOfInterest',
                code,
            )
            if fixed != code:
                return fixed

        # CS0117: BuiltInCategory.OST_ReferencePlanes (1 case)
        # Real value is OST_CLines.
        if ("cs0117" in error_lower
                and "builtincategory" in error_lower
                and "ost_referenceplanes" in error_lower):
            fixed = re.sub(
                r'\bBuiltInCategory\.OST_ReferencePlanes\b',
                'BuiltInCategory.OST_CLines',
                code,
            )
            if fixed != code:
                return fixed

        # CS0117: BuiltInCategory.OST_CurtainWalls (1 case)
        # Curtain walls don't have a dedicated category — they're OST_Walls,
        # filtered by WallKind==Curtain at the type level.
        if ("cs0117" in error_lower
                and "builtincategory" in error_lower
                and "ost_curtainwalls" in error_lower):
            fixed = re.sub(
                r'\bBuiltInCategory\.OST_CurtainWalls\b',
                'BuiltInCategory.OST_Walls',
                code,
            )
            if fixed != code:
                return fixed

        # CS0117: BuiltInCategory.OST_CableTrayTag (3 cases) — should be plural.
        if ("cs0117" in error_lower
                and "builtincategory" in error_lower
                and "ost_cabletraytag'" in error_lower):
            fixed = re.sub(
                r'\bBuiltInCategory\.OST_CableTrayTag\b',
                'BuiltInCategory.OST_CableTrayTags',
                code,
            )
            if fixed != code:
                return fixed

        # CS0117: ViewFamily.ThreeD (1 case) — real name is ThreeDimensional.
        if ("cs0117" in error_lower
                and "viewfamily" in error_lower
                and "'threed'" in error_lower):
            # Guard: don't touch ThreeDimensional (already correct)
            fixed = re.sub(
                r'\bViewFamily\.ThreeD(?!imensional)\b',
                'ViewFamily.ThreeDimensional',
                code,
            )
            if fixed != code:
                return fixed

        # CS1061: 'LinkElementId' does not contain 'ElementId' (1 case/24h)
        # Real API: LinkElementId.LinkedElementId.
        #
        # NOT AUTO-FIXED. The naive regex `\.ElementId\b → \.LinkedElementId`
        # would also clobber the VALID Reference.ElementId API which is used
        # everywhere in selection code (uidoc.Selection.PickObject(...).ElementId).
        # Trade-off: 1 LLM call/day saved is not worth breaking selection code.
        # Guidance lives in _RUNTIME_ERROR_HINTS ("linkelementid").

        # CS1061: 'Family' does not contain 'IsShared' (1 case)
        # Real path is family.FamilyCategory.IsSharedFamily? actually IsShared
        # is on the FamilySymbol/FamilyParameter — for family-instance check,
        # use family.IsInPlace and family.IsShared via parameter.
        # Conservative: don't auto-replace — let LLM repair with hint.
        # (no auto-fix here; hint in _RUNTIME_ERROR_HINTS handles it)

        # CS1501/CS7036: Document.NewModelCurveLoop (2 cases)
        # No such method. Use foreach + Document.Create.NewModelCurve.
        # Conservative: no regex auto-fix (multi-line refactor needed).
        # Hint added in _RUNTIME_ERROR_HINTS.

        # CS1061: View3D.ShadowsVisible / .ShadowsDisplay / .EnableShadows /
        # .IsOrientationLocked (4 cases) — all wrong. Real API:
        # view3D.GetSunAndShadowSettings() then property access.
        # Conservative: no auto-fix (needs setting object). Hint covers it.

        # CS1061: RevitLinkGraphicsSettings.GetCategoryHidden /
        # IsCategoryHidden / LinkVisibility (5 cases) — these don't exist.
        # Real API works through OverrideGraphicSettings on the view.
        # Conservative: no auto-fix. Hint covers it.

        # CS1061: RebarShapeDrivenAccessor.SetLayoutFixedSpacing (3 cases)
        # Real names: SetLayoutAsFixedNumber / SetLayoutAsMaximumSpacing /
        # SetLayoutAsMinimumClearSpacing. The "FixedSpacing" variant
        # legitimately doesn't exist. Hint redirects to correct API.

        # CS0117: BuiltInCategory.OST_AreaReinforcement /
        # OST_PathReinforcement / OST_StructuralAreaReinforcement / etc.
        # (12 cases — top hallucination cluster!)
        # The actual API uses:
        #   OST_AreaRein     (area reinforcement)   — 2024+
        #   OST_PathRein     (path reinforcement)   — 2024+
        # Pre-2024 used OST_StructuralAreaReinforcement / -PathReinforcement.
        # Pick based on revit version: 2024+ → short form, else → long form.
        if ("cs0117" in error_lower
                and "builtincategory" in error_lower
                and ("ost_areareinforcement" in error_lower
                     or "ost_pathreinforcement" in error_lower
                     or "ost_structuralareareinforcement" in error_lower
                     or "ost_structuralpathreinforcement" in error_lower
                     # Short forms — used by 2024+ but legacy Revit chokes
                     or "ost_arearein'" in error_lower
                     or "ost_pathrein'" in error_lower)):
            modern = self._version_year >= 2024 if self._version_year else True
            if modern:
                # Modern Revit (2024+) — short names
                replacements = [
                    (r'\bOST_StructuralAreaReinforcement\b', 'OST_AreaRein'),
                    (r'\bOST_StructuralPathReinforcement\b', 'OST_PathRein'),
                    (r'\bOST_AreaReinforcement\b', 'OST_AreaRein'),
                    (r'\bOST_PathReinforcement\b', 'OST_PathRein'),
                ]
            else:
                # Legacy Revit (2021-2023) — long names
                replacements = [
                    (r'\bOST_AreaRein\b', 'OST_StructuralAreaReinforcement'),
                    (r'\bOST_PathRein\b', 'OST_StructuralPathReinforcement'),
                    (r'\bOST_AreaReinforcement\b(?!_)', 'OST_StructuralAreaReinforcement'),
                    (r'\bOST_PathReinforcement\b(?!_)', 'OST_StructuralPathReinforcement'),
                ]
            fixed = code
            for pat, repl in replacements:
                fixed = re.sub(pat, repl, fixed)
            if fixed != code:
                return fixed

        # CS0117: TagMode.TM_AD_Standard / TM_AD_Point / TM_AD_Horizontal (4 cases)
        # All wrong. Real: TagMode.TM_ADDBY_CATEGORY + TagOrientation enum for
        # horizontal/vertical/etc. Conservative auto-fix: TM_AD_Standard is the
        # main offender — that maps to TM_ADDBY_CATEGORY.
        if ("cs0117" in error_lower
                and "tagmode" in error_lower
                and "tm_ad_" in error_lower):
            fixed = re.sub(
                r'\bTagMode\.TM_AD_(Standard|Point|Horizontal|Vertical)\b',
                'TagMode.TM_ADDBY_CATEGORY',
                code,
            )
            if fixed != code:
                return fixed

        # CS1061: 'IEnumerable<Element>' does not contain 'GetElementCount' (1/24h)
        # Real fix on a LINQ pipeline: use .Count() from System.Linq.
        #
        # NOT AUTO-FIXED. The naive regex `.GetElementCount() → .Count()` would
        # clobber VALID FilteredElementCollector.GetElementCount() calls in the
        # SAME code (which is THE canonical Revit pattern for counting without
        # materializing). Worse: FEC implements only non-generic IEnumerable, so
        # .Count() on FEC FAILS with CS1061 too — trading one error for another.
        # Guidance lives in _RUNTIME_ERROR_HINTS ("ienumerable<element>").

        # CS1061: 'Wall' does not contain 'WallTypeId' (1 case)
        # Real API: wall.WallType.Id (or wall.GetTypeId()).
        if ("cs1061" in error_lower
                and "'wall'" in error_lower
                and "'walltypeid'" in error_lower):
            fixed = re.sub(
                r'(\b\w+)\.WallTypeId\b',
                r'\1.GetTypeId()',
                code,
            )
            if fixed != code:
                return fixed

        # CS1061: 'CompoundStructure' does not contain 'IsCompound' (2026-05-14)
        # Tautological hallucination: a CompoundStructure object IS compound
        # by definition. The semantically meaningful check is "does it have
        # more than one layer" → LayerCount > 1.
        # Safe replace: rule fires only when error message explicitly cites
        # CompoundStructure + IsCompound, so we won't clobber unrelated
        # ".IsCompound" properties on different classes.
        if ("cs1061" in error_lower
                and "'compoundstructure'" in error_lower
                and "'iscompound'" in error_lower):
            fixed = re.sub(
                r'(\b\w+)\.IsCompound\b',
                r'(\1.LayerCount > 1)',
                code,
            )
            if fixed != code:
                return fixed

        # CS1061: 'CompoundStructure' does not contain 'CanHaveStructuralDeck' (2026-05-14)
        # CS1061: 'CompoundStructure' does not contain 'InsertLayer' (2026-05-14)
        # No auto-fix — both require multi-line refactor:
        #   - CanHaveStructuralDeck: iterate cs.GetLayers() and check
        #     layer.Function == MaterialFunctionAssignment.StructuralDeck
        #   - InsertLayer: build new List<CompoundStructureLayer>, copy from
        #     cs.GetLayers(), insert custom layer, call cs.SetLayers(newList)
        # Guidance lives in _RUNTIME_ERROR_HINTS.

        # CS0103: name 'xxx' not found -- could be a missing variable
        # Too risky to auto-fix, let LLM handle

        return None

    def fix(self, code: str) -> str:
        """Apply SAFE fixes only. Risky fixes disabled — with good RAG, LLM
        generates correct code and aggressive fixer can break it."""
        code = self.strip_wrappers(code)
        # SAFE: only adds prefix if missing
        code = self.fix_category_refs(code)
        # SAFE: only adds doc if constructor empty
        code = self.fix_fec_constructor(code)
        # SAFE: insert .OfType<Element>() before LINQ calls on FEC.
        # FEC implements non-generic IEnumerable; LINQ on it always errors —
        # this fix is structurally safe (idempotent) and closes the #1 production failure.
        code = self.fix_fec_linq(code)
        # SAFE: Console.WriteLine useless in Revit
        code = self.fix_console(code)
        # SAFE: method must return something
        code = self.ensure_return(code)
        # SAFE: version-aware ElementId fix (both directions, when version known)
        if self._version_year:
            code = self.fix_element_id_api(code)
        # DISABLED — can break correct code:
        # code = self.fix_parameter_names(code)  # may "fix" correct param names
        # code = self.fix_missing_filters(code)  # may add filter when types intended
        # code = self.fix_transaction(code)      # may double-wrap existing transaction
        return code

    # ------------------------------------------------------------------
    # 0. fix_element_id_api — ElementId API changes between versions
    # ------------------------------------------------------------------
    def fix_element_id_api(self, code: str) -> str:
        """Fix ElementId API changes between Revit versions.

        Revit 2024+: ElementId.Value (long) replaces ElementId.IntegerValue (int).
        Revit ≤2023: the reverse — ElementId.Value does NOT exist; use .IntegerValue.

        The ≤2023 rewrite is PRECISE: it only touches `.Value` that follows an
        ElementId-yielding token (a name ending in 'Id', optionally a getter like
        GetTypeId()). It deliberately does NOT touch `kv.Value`, `nullable.Value`,
        or other unrelated `.Value` access, so it can run safely on attempt 1.
        Audit F2/F5: 15.4% of the verified-recipe corpus used `.Value` and broke
        on this Revit-2023 model before this proactive fix existed.
        """
        if self._version_year >= 2024:
            # Blanket .IntegerValue→.Value is wrong for WorksetId: only ElementId got
            # .Value in 2024+; WorksetId.IntegerValue persists and has NO .Value. The two
            # are indistinguishable by regex (both `x.Id.IntegerValue`), so when a workset
            # is in play, skip the rewrite — those recipes already compile as-is.
            if "orkset" not in code:
                code = re.sub(r'\.IntegerValue\b', '.Value', code)
        elif self._version_year and self._version_year < 2024:
            code = re.sub(r'\b(\w*[Ii]d(?:\(\))?)\.Value\b', r'\1.IntegerValue', code)
        return code

    # ------------------------------------------------------------------
    # 1. strip_wrappers — remove using/namespace/class/method if LLM
    #    generated a full file.  Preserve `using (var tx = ...)` statements.
    # ------------------------------------------------------------------
    def strip_wrappers(self, code: str) -> str:
        # Strip markdown code fences that LLM sometimes includes
        code = re.sub(r'^```(?:csharp|cs)?\s*\n?', '', code.strip())
        code = re.sub(r'\n?```\s*$', '', code.strip())
        lines = code.strip().split("\n")
        cleaned: list[str] = []
        brace_depth = 0
        inside_wrapper = False
        # Track how many wrapper-opening braces we've consumed so we can
        # remove the corresponding closing braces at the end.
        wrapper_braces = 0

        for line in lines:
            stripped = line.strip()

            # Skip `using X;` directives (NOT `using (var …)` or `using var …`)
            if (
                stripped.startswith("using ")
                and stripped.endswith(";")
                and "=" not in stripped
                and "(" not in stripped
            ):
                continue

            # Skip `namespace X {` or `namespace X\n{` — but ONLY when it is a LEADING
            # wrapper (no real code emitted yet). A recipe may declare its own
            # `namespace _KukaiNNN { class _Pad {` AFTER the main body (escape pattern to
            # host helper types); that is not the wrapper and must not be stripped, or the
            # brace count goes wrong → CS1022.
            if re.match(r"^namespace\s+", stripped) and not any(c.strip() for c in cleaned):
                inside_wrapper = True
                # If opening brace is on same line, consume it
                if "{" in stripped:
                    wrapper_braces += 1
                continue

            # Inside wrapper: skip class / method declarations
            if inside_wrapper:
                # Standalone opening brace belonging to namespace/class/method
                if stripped == "{" and wrapper_braces < 3:
                    wrapper_braces += 1
                    continue

                # public class X  /  public static class X  etc.
                if re.match(
                    r"^(public\s+)?(static\s+)?(partial\s+)?class\s+", stripped
                ):
                    if "{" in stripped:
                        wrapper_braces += 1
                    continue

                # public static object Execute(Document doc, …)
                if re.match(
                    r"^(public\s+)?(static\s+)?(\w+\s+)?Execute\s*\(", stripped
                ):
                    if "{" in stripped:
                        wrapper_braces += 1
                    continue

            cleaned.append(line)

        # Remove trailing closing braces that belonged to the wrapper
        while wrapper_braces > 0 and cleaned:
            last = cleaned[-1].strip()
            if last == "}" or last == "":
                if last == "}":
                    wrapper_braces -= 1
                cleaned.pop()
            else:
                break

        # Remove trailing blank lines
        while cleaned and cleaned[-1].strip() == "":
            cleaned.pop()

        result = "\n".join(cleaned)

        # Safety: if stripping left nothing useful, return original
        if not result.strip():
            return code

        return result

    # ------------------------------------------------------------------
    # 2. fix_parameter_names — replace wrong BuiltInParameter names
    # ------------------------------------------------------------------
    def fix_parameter_names(self, code: str) -> str:
        for pattern, replacement in _PARAM_REGEXES:
            code = pattern.sub(replacement, code)
        return code

    # ------------------------------------------------------------------
    # 3. fix_category_refs — add BuiltInCategory. prefix if missing
    # ------------------------------------------------------------------
    def fix_category_refs(self, code: str) -> str:
        def _replace(m: re.Match[str]) -> str:
            cat = m.group(1)
            return f"OfCategory(BuiltInCategory.{cat})"

        return _CATEGORY_RE.sub(_replace, code)

    # ------------------------------------------------------------------
    # 3b. fix_fec_constructor — add doc to empty FilteredElementCollector()
    # ------------------------------------------------------------------
    def fix_fec_constructor(self, code: str) -> str:
        """Fix FilteredElementCollector() called without doc argument."""
        return re.sub(
            r'new\s+FilteredElementCollector\(\s*\)',
            'new FilteredElementCollector(doc)',
            code,
        )

    # ------------------------------------------------------------------
    # 3c. fix_fec_linq — insert .OfType<Element>() before LINQ on FEC.
    # The #1 production failure (CS1061 .Cast/.Any/.First/.ToList/.Where
    # on FilteredElementCollector). FEC implements non-generic IEnumerable
    # so LINQ extension methods don't bind. .OfType<T>() returns
    # IEnumerable<T> which LINQ binds to.
    # Safe-by-design: idempotent (won't insert before .OfType itself),
    # only matches chains rooted at `new FilteredElementCollector(...)`.
    # ------------------------------------------------------------------
    def fix_fec_linq(self, code: str) -> str:
        def _replace(m: re.Match[str]) -> str:
            chain, dot, method, opener = m.group(1), m.group(2), m.group(3), m.group(4)
            # Guard: only insert .OfType<Element>() when the chain is a PURE FEC chain
            # (OfClass/OfCategory/WhereElementIs.../WherePasses → still non-generic
            # IEnumerable, so LINQ doesn't bind). Skip when the chain already produces a
            # bound/typed enumerable, because inserting .OfType<Element>() there is wrong:
            #   .Cast<T>()/.OfType<T>()  → already typed; downcast to Element breaks w.Width
            #   .ToElementIds()          → yields ElementId, not Element (CS0029/CS1503)
            #   .ToElements()/.ToList()/.ToArray()/.Select(/.Where( → already IEnumerable
            # NB ".Where(" matches LINQ Where, NOT the FEC ".WhereElementIsNotElementType(".
            # The core fix still fires on genuinely-untyped chains (e.g. new FEC(doc).ToList()).
            _typed_or_terminal = (".OfType", ".Cast", ".ToElementIds", ".ToElements",
                                  ".ToList", ".ToArray", ".Select(", ".Where(")
            if any(t in chain for t in _typed_or_terminal):
                return m.group(0)
            return f"{chain}.OfType<Element>(){dot}{method}{opener}"
        return _FEC_LINQ_RE.sub(_replace, code)

    # ------------------------------------------------------------------
    # 4. fix_missing_filters — add WhereElementIsNotElementType()
    # ------------------------------------------------------------------
    def _wants_types(self, code: str) -> bool:
        """Check if the code appears to want element types rather than instances."""
        lower = code.lower()
        indicators = [
            "ofclass(typeof(",  # OfClass with a type
            "walltype", "floortype", "rooftype", "ceilingtype",
            "familysymbol", "familytype", "elementtype",
            "whereelementiselementtype",  # Already has the type filter
            "gettypeid", "gettype",
            # Russian indicators in comments
            "\u0442\u0438\u043f", "\u0442\u0438\u043f\u044b", "\u0442\u0438\u043f\u043e\u0432",
        ]
        return any(ind in lower for ind in indicators)

    def fix_missing_filters(self, code: str) -> str:
        # Only act if there is a FilteredElementCollector + OfCategory
        if "FilteredElementCollector" not in code:
            return code
        if "OfCategory" not in code:
            return code

        # If the code already has either filter, don't touch it
        if "WhereElementIsNotElementType" in code:
            return code
        if "WhereElementIsElementType" in code:
            return code

        # If the code wants types, don't add the instance-only filter
        if self._wants_types(code):
            return code

        # Insert .WhereElementIsNotElementType() after OfCategory(…) chain,
        # right before .ToElements() / .ToList() / .GetElementCount() / .FirstElement()
        def _insert_filter(m: re.Match[str]) -> str:
            return (
                m.group(1)
                + m.group(2)
                + ".WhereElementIsNotElementType()"
                + m.group(3)
            )

        result = _FEC_TO_ELEMENTS_RE.sub(_insert_filter, code)

        # Fallback: if regex didn't match (e.g. multiline), do a simpler
        # string-level insertion before .ToElements()
        if result == code:
            for terminal in (".ToElements()", ".ToList()", ".GetElementCount()", ".FirstElement()"):
                if terminal in code:
                    # Replace ALL occurrences (not just first) to handle multi-collector code
                    code = code.replace(
                        terminal,
                        f".WhereElementIsNotElementType(){terminal}",
                    )
            if code != result:
                return code

        return result

    # ------------------------------------------------------------------
    # 5. fix_console — remove Console.WriteLine, it doesn't work in Revit
    # ------------------------------------------------------------------
    def fix_console(self, code: str) -> str:
        code = _CONSOLE_RE.sub("// (console output removed)", code)
        return code

    # ------------------------------------------------------------------
    # 6. ensure_return — guarantee the code returns a value
    # ------------------------------------------------------------------
    def ensure_return(self, code: str) -> str:
        lines = code.rstrip().split("\n")

        # Find last non-empty, non-comment line
        last_meaningful = ""
        for line in reversed(lines):
            s = line.strip()
            if s and not s.startswith("//"):
                last_meaningful = s
                break

        if "return " in last_meaningful or "return;" in last_meaningful:
            return code

        # Don't add return null if code is clearly a block (ends with })
        # that likely already returns internally
        if last_meaningful == "}":
            # Check if ANY line has a return
            if any("return " in ln or "return;" in ln for ln in lines):
                return code

        # Escape-pattern recipes close the wrapper's Execute() early and declare helper
        # types (e.g. an IFailuresPreprocessor) at class/namespace level, then END with
        # an OPEN scope (`... public static void _Z() {`) that the wrapper footer closes.
        # Two tells: (a) the last meaningful line ends with '{' (an open scope), or
        # (b) the running brace balance dips below zero (it closed the wrapper's scope).
        # Appending a bare `return null;` here would land inside that trailing (often
        # `void`) scope → CS0127. Such recipes already return inside Execute(), so leave
        # them untouched; the wrapper footer closes the open scopes. (Safe: a normal
        # method-body snippet never ends with '{' and never goes net-negative.)
        running = 0
        dips_negative = False
        for ln in lines:
            running += ln.count("{") - ln.count("}")
            if running < 0:
                dips_negative = True
        if last_meaningful.endswith("{") or dips_negative:
            return code

        return code + "\nreturn null;"

    # ------------------------------------------------------------------
    # 7. fix_transaction — wrap mutating code in Transaction
    # ------------------------------------------------------------------
    def fix_transaction(self, code: str) -> str:
        """Wrap code in a Transaction if it mutates but has no Transaction."""
        mutating_patterns = [".Set(", ".Delete(", ".Create(", "doc.Delete("]
        has_mutation = any(p in code for p in mutating_patterns)

        if not has_mutation:
            return code
        if "Transaction" in code:
            # Already has Transaction — check for Commit
            if "Commit()" not in code and "transaction" in code.lower():
                # Add Commit before the last closing brace of the transaction
                code = code.replace(
                    "}", "    tx.Commit();\n}", 1
                )
            return code

        # Wrap entire code in transaction
        indented = "\n".join("    " + line for line in code.split("\n"))
        return (
            'using (var tx = new Transaction(doc, "KUKI"))\n'
            "{\n"
            "    tx.Start();\n"
            f"{indented}\n"
            "    tx.Commit();\n"
            "}"
        )

    # ------------------------------------------------------------------
    # 8. fix_unit_conversion — add conversion factors (aggressive)
    # ------------------------------------------------------------------
    def fix_unit_conversion(self, code: str) -> str:
        """Add unit conversion for .AsDouble() results.

        This method is aggressive and NOT called by fix() by default.
        """
        # If code returns AsDouble() without conversion and has mm/meter hints
        if ".AsDouble()" not in code:
            return code

        lower = code.lower()
        if "мм" in lower or "mm" in lower or "миллиметр" in lower:
            code = code.replace(".AsDouble()", ".AsDouble() * 304.8")
        elif "метр" in lower or "meter" in lower:
            code = code.replace(".AsDouble()", ".AsDouble() * 0.3048")

        return code
