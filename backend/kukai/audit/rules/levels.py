"""Audit rules: levels validation."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="LVL-001",
            name="Все стены привязаны к уровню",
            category=Category.LEVELS,
            severity=Severity.WARNING,
            description="Каждая стена должна быть привязана к уровню (LevelId)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var walls = collector.OfClass(typeof(Wall)).Take(500).Cast<Wall>();
var bad = walls.Where(w => w.LevelId == null || w.LevelId == ElementId.InvalidElementId).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(w => w.Id.IntegerValue));
var msg = $"Найдено {bad.Count} стен без привязки к уровню";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="LVL-002",
            name="Нет неиспользуемых уровней",
            category=Category.LEVELS,
            severity=Severity.INFO,
            description="Все уровни в проекте должны содержать хотя бы один элемент",
            check_code='''
var collector = new FilteredElementCollector(doc);
var levels = collector.OfClass(typeof(Level)).Take(200).Cast<Level>().ToList();
var unusedIds = new System.Collections.Generic.List<int>();
foreach (var level in levels) {
    var elemsOnLevel = new FilteredElementCollector(doc).WhereElementIsNotElementType().Take(200);
    bool hasElem = elemsOnLevel.Any(e => {
        var p = e.get_Parameter(BuiltInParameter.LEVEL_PARAM);
        if (p == null) p = e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
        return p != null && p.AsElementId() == level.Id;
    });
    if (!hasElem) unusedIds.Add(level.Id.IntegerValue);
}
if (unusedIds.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", unusedIds);
var msg = $"Найдено {unusedIds.Count} неиспользуемых уровней";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {unusedIds.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="LVL-003",
            name="Высоты этажей в разумном диапазоне",
            category=Category.LEVELS,
            severity=Severity.WARNING,
            description="Расстояние между соседними уровнями должно быть 2.4-6.0 м (7.87-19.69 ft)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var levels = collector.OfClass(typeof(Level)).Take(200).Cast<Level>().OrderBy(l => l.Elevation).ToList();
var badIds = new System.Collections.Generic.List<int>();
for (int i = 1; i < levels.Count; i++) {
    double h = levels[i].Elevation - levels[i - 1].Elevation;
    if (h < 7.87 || h > 19.69) {
        badIds.Add(levels[i].Id.IntegerValue);
        badIds.Add(levels[i - 1].Id.IntegerValue);
    }
}
badIds = badIds.Distinct().ToList();
if (badIds.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", badIds);
var msg = $"Найдено {badIds.Count} уровней с нестандартной высотой этажа (норма 2.4-6.0 м)";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {badIds.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
    ]
