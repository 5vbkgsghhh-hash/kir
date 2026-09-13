"""Shared compiler-owned C# helpers for independent Revit reads.

The level axis is part of KIR's L2 acceptance identity. Decompile extraction
and post-commit acceptance must resolve an element's level through the same
exact parameter chain; copying that chain would create two judges.

LAW OF THE LINK (2026-08-03). A link is accepted ONLY if it holds a real
``ElementId``. `HasValue` is true even for ``InvalidElementId`` — measured
2026-07-27 by a direct probe on a beam: ``FAMILY_LEVEL_PARAM: HasValue=True,
AsElementId=-1``. Before this fix the chain moved to the next link only on
``== null``, i.e. it stopped on a parameter that EXISTED but was EMPTY, and
the tail was unreachable: a beam's ``SCHEDULE_LEVEL_PARAM`` exists and equals
-1. The WRITE side has honoured this law since 2026-07-27
(``authoring._level_chain_check``); the READ side had not — and in a house
where there must be one judge, that is two answers to one question.

LINK ORDER IS PART OF THE CONTRACT. The chain short-circuits: the first link
with a real id wins. A new link is appended STRICTLY AT THE TAIL, so an
element whose level was already found keeps finding the EXACT SAME level:
every earlier link stands first and is checked first. Appending at the tail
cannot change an answer — it can only give an answer where there was none.
The order is pinned by ``decompile/tests/test_level_read_chain.py``.

THE TAIL WAS INTRODUCED BY MEASUREMENT (a scan of eight real decompiles,
2026-08-03): 2367 beams, 116 stairs and 21 railings sat in L0 with
``level_id: null`` — and none of these numbers is a property of the models;
all three categories hold their level in their own BuiltInParameter, which
was not in the chain.
"""
from __future__ import annotations


_ELEMENT_LEVEL_HELPERS_TEMPLATE = r"""
Func<Element, Level> __ElementLevel = (__e) =>
{
    try
    {
        ElementId __levelId = null;
        try { __levelId = __e.LevelId; } catch { }
        if (__levelId == null || __levelId == ElementId.InvalidElementId)
        {
            Func<Parameter, bool> __holdsLevel = (__p) =>
            {
                try
                {
                    if (__p == null || !__p.HasValue) return false;
                    if (__p.StorageType != StorageType.ElementId) return false;
                    var __v = __p.AsElementId();
                    return __v != null && __v != ElementId.InvalidElementId;
                }
                catch { return false; }
            };
            Parameter __levelParam = null;
            try { __levelParam = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM); } catch { }
            if (__holdsLevel(__levelParam))
                __levelId = __levelParam.AsElementId();
        }
        if (__levelId != null && __levelId != ElementId.InvalidElementId)
            return __DOC__.GetElement(__levelId) as Level;
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


def element_level_helpers_cs(document_var: str = "doc") -> str:
    """The level-reading chain, bound to the NAMED document.

    🔴 WHY A PARAMETER, NOT A LITERAL. Two paths with different sources read
    this helper: acceptance lives in the host's document and knows only
    `doc`, while extraction may read a LINK, where `doc` is the host but the
    data sits in `__src`. Identifier numbers in these documents COINCIDE, so
    a mismatch does not produce a refusal but a foreign level: `level_name`
    then arrives from someone else's level, and when there is no match the
    element silently loses its level and falls into `__none__`.

    Measured 2026-08-25: the link's body had five such reads in the package
    and one in the probe.
    """
    return _ELEMENT_LEVEL_HELPERS_TEMPLATE.replace("__DOC__", document_var)


#: The ready-made rendering for the host — the only source acceptance uses.
ELEMENT_LEVEL_HELPERS_CS = element_level_helpers_cs()

__all__ = ["ELEMENT_LEVEL_HELPERS_CS", "element_level_helpers_cs"]
