"""Shared compiler-owned C# helpers for independent Revit reads.

The level axis is part of KIR's L2 acceptance identity. Decompile extraction
and post-commit acceptance must resolve an element's level through the same
exact parameter chain; copying that chain would create two judges.

ЗАКОН ЗВЕНА (03.08.2026). Звено принимается, ТОЛЬКО если держит настоящий
``ElementId``. `HasValue` истинен и для ``InvalidElementId`` — замерено 27.07
прямой пробой на балке: ``FAMILY_LEVEL_PARAM: HasValue=True, AsElementId=-1``.
До этой правки цепочка переходила к следующему звену лишь по ``== null``, то
есть обрывалась на СУЩЕСТВУЮЩЕМ, но ПУСТОМ параметре и хвост был недостижим:
у балки ``SCHEDULE_LEVEL_PARAM`` существует и равен -1. Сторона ЗАПИСИ этот
закон соблюдала с 27.07 (``authoring._level_chain_check``), сторона ЧТЕНИЯ —
нет; в доме, где судья обязан быть один, это два ответа на один вопрос.

ПОРЯДОК ЗВЕНЬЕВ — ЧАСТЬ ДОГОВОРА. Цепочка короткозамкнутая: побеждает первое
звено с настоящим id. Новое звено дописывается СТРОГО В ХВОСТ, поэтому
элемент, у которого уровень находился раньше, находит РОВНО ТОТ ЖЕ уровень:
все прежние звенья стоят раньше и проверяются первыми. Приписка в хвост не
может изменить ответ — только дать ответ там, где его не было. Порядок
закреплён тестом ``decompile/tests/test_level_read_chain.py``.

ХВОСТ ЗАВЁДЕН ЗАМЕРОМ (обход восьми настоящих разборов, 03.08): 2367 балок,
116 лестниц и 21 ограждение лежали в L0 с ``level_id: null`` — и ни одно из
этих чисел не свойство моделей, все три категории держат уровень в
собственном BuiltInParameter, которого в цепочке не было.
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
