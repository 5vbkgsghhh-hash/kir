"""Shared compiler-owned C# helpers for independent Revit reads.

The level axis is part of KIR's L2 acceptance identity. Decompile extraction
and post-commit acceptance must resolve an element's level through the same
exact parameter chain; copying that chain would create two judges.
"""
from __future__ import annotations


ELEMENT_LEVEL_HELPERS_CS = r"""
Func<Element, Level> __ElementLevel = (__e) =>
{
    try
    {
        ElementId __levelId = null;
        try { __levelId = __e.LevelId; } catch { }
        if (__levelId == null || __levelId == ElementId.InvalidElementId)
        {
            Parameter __levelParam = null;
            try { __levelParam = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT); } catch { }
            if (__levelParam == null)
                try { __levelParam = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM); } catch { }
            if (__levelParam == null)
                try { __levelParam = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM); } catch { }
            if (__levelParam == null)
                try { __levelParam = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); } catch { }
            if (__levelParam != null && __levelParam.HasValue)
                __levelId = __levelParam.AsElementId();
        }
        if (__levelId != null && __levelId != ElementId.InvalidElementId)
            return doc.GetElement(__levelId) as Level;
    }
    catch { }
    return null;
};
Func<Element, string> __LevelKey = (__e) =>
{
    var __level = __ElementLevel(__e);
    return __level == null ? "__none__" : __level.Id.ToString();
};
""".strip()


__all__ = ["ELEMENT_LEVEL_HELPERS_CS"]
