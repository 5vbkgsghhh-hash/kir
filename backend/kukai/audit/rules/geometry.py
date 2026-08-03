"""Audit rules: geometry validation."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="GEO-001",
            name="Нет стен с нулевой длиной",
            category=Category.GEOMETRY,
            severity=Severity.ERROR,
            description="В модели не должно быть стен с нулевой или близкой к нулю длиной",
            check_code='''
var collector = new FilteredElementCollector(doc);
var walls = collector.OfClass(typeof(Wall)).Take(500).Cast<Wall>();
var bad = walls.Where(w => w.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)?.AsDouble() < 0.01).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(w => w.Id.IntegerValue));
var msg = $"Найдено {bad.Count} стен с нулевой длиной";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="GEO-002",
            name="Нет дублированных помещений",
            category=Category.GEOMETRY,
            severity=Severity.ERROR,
            description="Не должно быть помещений с одинаковым номером на одном уровне",
            check_code='''
var collector = new FilteredElementCollector(doc);
var rooms = collector.OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().Take(500).Cast<Room>();
var placed = rooms.Where(r => r.Area > 0).ToList();
var grouped = placed.GroupBy(r => r.Number + "|" + r.LevelId.IntegerValue).Where(g => g.Count() > 1);
var dupes = grouped.SelectMany(g => g).ToList();
if (dupes.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", dupes.Select(r => r.Id.IntegerValue));
var groups = grouped.Count();
var msg = $"Найдено {groups} групп дублированных помещений ({dupes.Count} элементов)";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {dupes.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="GEO-003",
            name="Нет перекрытий с нулевой площадью",
            category=Category.GEOMETRY,
            severity=Severity.ERROR,
            description="В модели не должно быть перекрытий с нулевой площадью",
            check_code='''
var collector = new FilteredElementCollector(doc);
var floors = collector.OfClass(typeof(Floor)).Take(500).Cast<Floor>();
var bad = floors.Where(f => f.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)?.AsDouble() <= 0).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(f => f.Id.IntegerValue));
var msg = $"Найдено {bad.Count} перекрытий с нулевой площадью";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="GEO-004",
            name="Bounding box модели в разумных пределах",
            category=Category.GEOMETRY,
            severity=Severity.WARNING,
            description="Габариты модели не должны превышать 500 м (1640 ft) по любой оси",
            check_code='''
var collector = new FilteredElementCollector(doc);
var elems = collector.WhereElementIsNotElementType().Take(200);
double minX = double.MaxValue, minY = double.MaxValue, minZ = double.MaxValue;
double maxX = double.MinValue, maxY = double.MinValue, maxZ = double.MinValue;
int count = 0;
foreach (var e in elems) {
    var bb = e.get_BoundingBox(null);
    if (bb == null) continue;
    count++;
    if (bb.Min.X < minX) minX = bb.Min.X;
    if (bb.Min.Y < minY) minY = bb.Min.Y;
    if (bb.Min.Z < minZ) minZ = bb.Min.Z;
    if (bb.Max.X > maxX) maxX = bb.Max.X;
    if (bb.Max.Y > maxY) maxY = bb.Max.Y;
    if (bb.Max.Z > maxZ) maxZ = bb.Max.Z;
}
if (count == 0) return "{\\"passed\\": true}";
double dx = maxX - minX, dy = maxY - minY, dz = maxZ - minZ;
double limit = 1640.0;
if (dx < limit && dy < limit && dz < limit) return "{\\"passed\\": true}";
var msg = $"Габариты модели превышают 500м: {dx*0.3048:F0}x{dy*0.3048:F0}x{dz*0.3048:F0} м";
return $"{{\\"passed\\": false, \\"element_ids\\": [], \\"count\\": 1, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
    ]
