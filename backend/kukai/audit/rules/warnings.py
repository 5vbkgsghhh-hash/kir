"""Audit rules: Revit warnings."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="WRN-001",
            name="Количество предупреждений < 100",
            category=Category.WARNINGS,
            severity=Severity.WARNING,
            description="Общее количество предупреждений (warnings) в модели не должно превышать 100",
            check_code='''
var warnings = doc.GetWarnings();
int count = warnings.Count;
if (count <= 100) return $"{{\\"passed\\": true, \\"count\\": {count}, \\"message\\": \\"Предупреждений: {count}\\"}}";
var msg = $"В модели {count} предупреждений (допустимо не более 100)";
return $"{{\\"passed\\": false, \\"element_ids\\": [], \\"count\\": {count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="WRN-002",
            name="Нет overlap warnings",
            category=Category.WARNINGS,
            severity=Severity.ERROR,
            description="В модели не должно быть предупреждений о пересечении (overlap) или дублировании элементов",
            check_code='''
var warnings = doc.GetWarnings();
var overlaps = warnings.Where(w => {
    var desc = w.GetDescriptionText().ToLower();
    return desc.Contains("overlap") || desc.Contains("duplicate") || desc.Contains("пересечение") || desc.Contains("дублир");
}).ToList();
if (overlaps.Count == 0) return "{\\"passed\\": true}";
var elemIds = overlaps.SelectMany(w => w.GetFailingElements()).Select(id => id.IntegerValue).Distinct().Take(200).ToList();
var ids = string.Join(",", elemIds);
var msg = $"Найдено {overlaps.Count} предупреждений о пересечении/дублировании элементов";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {overlaps.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
    ]
