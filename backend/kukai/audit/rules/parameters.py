"""Audit rules: parameter completeness."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="PAR-001",
            name="Стены имеют материал",
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            description="У стен должен быть назначен конструкционный материал",
            check_code='''
var collector = new FilteredElementCollector(doc);
var walls = collector.OfClass(typeof(Wall)).Take(500).Cast<Wall>();
var bad = walls.Where(w => {
    var cs = w.WallType.GetCompoundStructure();
    if (cs == null) return true;
    return cs.GetLayers().All(layer => layer.MaterialId == ElementId.InvalidElementId);
}).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(w => w.Id.IntegerValue));
var msg = $"Найдено {bad.Count} стен без назначенного материала";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="PAR-002",
            name="Помещения имеют имя и номер",
            category=Category.PARAMETERS,
            severity=Severity.ERROR,
            description="Все помещения (Rooms) должны иметь заполненные Name и Number",
            check_code='''
var collector = new FilteredElementCollector(doc);
var rooms = collector.OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().Take(500).Cast<Room>();
var placed = rooms.Where(r => r.Area > 0);
var bad = placed.Where(r => string.IsNullOrWhiteSpace(r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString()) || string.IsNullOrWhiteSpace(r.Number)).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(r => r.Id.IntegerValue));
var msg = $"Найдено {bad.Count} помещений без имени или номера";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="PAR-003",
            name="Двери имеют размеры в типе",
            category=Category.PARAMETERS,
            severity=Severity.INFO,
            description="Имена типов дверей должны содержать числовые размеры",
            check_code='''
var collector = new FilteredElementCollector(doc);
var doors = collector.OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().Take(500);
var bad = doors.Where(d => !System.Text.RegularExpressions.Regex.IsMatch(d.Name, @"\\d")).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(d => d.Id.IntegerValue));
var msg = $"Найдено {bad.Count} дверей без размеров в имени типа";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="PAR-004",
            name="Несущие колонны имеют Mark",
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            description="Все несущие колонны должны иметь заполненный параметр Mark",
            check_code='''
var collector = new FilteredElementCollector(doc);
var columns = collector.OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType().Take(500);
var bad = columns.Where(c => string.IsNullOrWhiteSpace(c.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)?.AsString())).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(c => c.Id.IntegerValue));
var msg = $"Найдено {bad.Count} колонн без параметра Mark";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="PAR-005",
            name="Фаза создания задана",
            category=Category.PARAMETERS,
            severity=Severity.INFO,
            description="Элементы должны иметь назначенную фазу создания (CreatedPhaseId)",
            check_code='''
var collector = new FilteredElementCollector(doc);
var elems = collector.WhereElementIsNotElementType().Take(500);
var bad = elems.Where(e => {
    var p = e.get_Parameter(BuiltInParameter.PHASE_CREATED);
    return p != null && p.AsElementId() == ElementId.InvalidElementId;
}).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(e => e.Id.IntegerValue));
var msg = $"Найдено {bad.Count} элементов без назначенной фазы создания";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="PAR-006",
            name="Workset назначен",
            category=Category.PARAMETERS,
            severity=Severity.INFO,
            description="В проектах с worksharing все элементы должны иметь назначенный рабочий набор",
            check_code='''
if (!doc.IsWorkshared) return "{\\"passed\\": true}";
var collector = new FilteredElementCollector(doc);
var elems = collector.WhereElementIsNotElementType().Take(500);
var bad = elems.Where(e => {
    var p = e.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
    return p != null && p.AsInteger() < 0;
}).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(e => e.Id.IntegerValue));
var msg = $"Найдено {bad.Count} элементов без назначенного рабочего набора";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
    ]
