"""Audit rules: naming conventions."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="NAM-001",
            name="Семейства без спецсимволов",
            category=Category.NAMING,
            severity=Severity.WARNING,
            description="Имена семейств не должны содержать спецсимволы (#, *, ?, <, >, |)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var families = collector.OfClass(typeof(Family)).Take(500).Cast<Family>();
var bad = families.Where(f => f.Name.IndexOfAny(new[]{'#','*','?','<','>','|'}) >= 0).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(f => f.Id.IntegerValue));
var msg = $"Найдено {bad.Count} семейств со спецсимволами";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
            norm_ref="ГОСТ 21.501-2018",
        ),
        AuditRule(
            id="NAM-002",
            name="Типы стен содержат толщину",
            category=Category.NAMING,
            severity=Severity.INFO,
            description="Имена типов стен должны содержать числовое значение толщины (мм)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var wallTypes = collector.OfClass(typeof(WallType)).Take(500).Cast<WallType>();
var bad = wallTypes.Where(wt => !System.Text.RegularExpressions.Regex.IsMatch(wt.Name, @"\\d")).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(wt => wt.Id.IntegerValue));
var msg = $"Найдено {bad.Count} типов стен без указания толщины в имени";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
            norm_ref="ГОСТ 21.501-2018",
        ),
        AuditRule(
            id="NAM-003",
            name="Виды именованы корректно",
            category=Category.NAMING,
            severity=Severity.WARNING,
            description="Имена видов не должны содержать 'Copy of', 'Копия' и подобные шаблонные имена",
            check_code='''
var collector = new FilteredElementCollector(doc);
var views = collector.OfClass(typeof(View)).Take(500).Cast<View>().Where(v => !v.IsTemplate);
var bad = views.Where(v => v.Name.StartsWith("Copy of") || v.Name.Contains("Копия") || System.Text.RegularExpressions.Regex.IsMatch(v.Name, @"^View \\d")).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(v => v.Id.IntegerValue));
var msg = $"Найдено {bad.Count} видов с шаблонными именами";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="NAM-004",
            name="Уровни именованы последовательно",
            category=Category.NAMING,
            severity=Severity.INFO,
            description="Имена уровней должны содержать числовое обозначение этажа",
            check_code='''
var collector = new FilteredElementCollector(doc);
var levels = collector.OfClass(typeof(Level)).Take(200).Cast<Level>();
var bad = levels.Where(l => !System.Text.RegularExpressions.Regex.IsMatch(l.Name, @"\\d")).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(l => l.Id.IntegerValue));
var msg = $"Найдено {bad.Count} уровней без числового обозначения";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="NAM-005",
            name="Листы имеют номер",
            category=Category.NAMING,
            severity=Severity.WARNING,
            description="Все листы должны иметь заполненный номер (SheetNumber)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var sheets = collector.OfClass(typeof(ViewSheet)).Take(500).Cast<ViewSheet>();
var bad = sheets.Where(s => string.IsNullOrWhiteSpace(s.SheetNumber)).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(s => s.Id.IntegerValue));
var msg = $"Найдено {bad.Count} листов без номера";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
            norm_ref="ГОСТ 21.101-2020",
        ),
    ]
