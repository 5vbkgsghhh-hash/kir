"""Audit rules: IFC export readiness."""
from __future__ import annotations

from kukai.audit.models import AuditRule, Category, Severity


def get_rules() -> list[AuditRule]:
    return [
        AuditRule(
            id="IFC-001",
            name="Стены имеют IfcExportAs",
            category=Category.IFC_READY,
            severity=Severity.WARNING,
            description="Для корректного IFC-экспорта стены должны иметь параметр IfcExportAs",
            check_code='''
var collector = new FilteredElementCollector(doc);
var walls = collector.OfClass(typeof(Wall)).Take(500).Cast<Wall>();
var bad = walls.Where(w => {
    var p = w.LookupParameter("IfcExportAs");
    if (p == null) p = w.LookupParameter("IFC Export As");
    return p == null || string.IsNullOrWhiteSpace(p.AsString());
}).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(w => w.Id.IntegerValue));
var msg = $"Найдено {bad.Count} стен без параметра IfcExportAs";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="IFC-002",
            name="Проект имеет адрес",
            category=Category.IFC_READY,
            severity=Severity.INFO,
            description="Для IFC Site должен быть задан адрес проекта в ProjectInfo",
            check_code='''
var info = doc.ProjectInformation;
var addr = info.Address;
if (!string.IsNullOrWhiteSpace(addr)) return "{\\"passed\\": true}";
var msg = "Адрес проекта не задан (ProjectInfo.Address пуст)";
return $"{{\\"passed\\": false, \\"element_ids\\": [], \\"count\\": 1, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="IFC-003",
            name="Координаты проекта заданы",
            category=Category.IFC_READY,
            severity=Severity.WARNING,
            description="Координаты проекта (Survey Point) должны быть отличны от нуля",
            check_code='''
var loc = doc.ActiveProjectLocation;
var pos = loc.GetProjectPosition(XYZ.Zero);
bool isZero = System.Math.Abs(pos.EastWest) < 0.001 && System.Math.Abs(pos.NorthSouth) < 0.001;
if (!isZero) return "{\\"passed\\": true}";
var msg = "Координаты проекта не заданы (Survey Point = 0,0)";
return $"{{\\"passed\\": false, \\"element_ids\\": [], \\"count\\": 1, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
        AuditRule(
            id="IFC-004",
            name="Base quantities доступны",
            category=Category.IFC_READY,
            severity=Severity.INFO,
            description="Стены и перекрытия должны иметь вычисляемые Area и Volume для IFC Base Quantities",
            check_code='''
var collector = new FilteredElementCollector(doc);
var elems = collector.OfClass(typeof(Wall)).Take(200).Cast<Element>().ToList();
var floors = new FilteredElementCollector(doc).OfClass(typeof(Floor)).Take(200).Cast<Element>();
elems.AddRange(floors);
var bad = elems.Where(e => {
    var area = e.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
    var vol = e.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);
    return (area == null || area.AsDouble() <= 0) && (vol == null || vol.AsDouble() <= 0);
}).ToList();
if (bad.Count == 0) return "{\\"passed\\": true}";
var ids = string.Join(",", bad.Select(e => e.Id.IntegerValue));
var msg = $"Найдено {bad.Count} элементов без вычисленных Area/Volume";
return $"{{\\"passed\\": false, \\"element_ids\\": [{ids}], \\"count\\": {bad.Count}, \\"message\\": \\"{msg}\\"}}";
'''.strip(),
        ),
    ]
